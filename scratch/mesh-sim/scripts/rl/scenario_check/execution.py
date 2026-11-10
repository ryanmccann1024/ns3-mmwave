"""Scenario-check execution and artifact ownership, invoked only by the user."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import shutil
import threading
import time
import traceback

from scripts.artifact_io import write_json, sha256_file, now_iso, canonical_sha256
from scripts.sim_support import find_mesh_root, parse_ini
from scripts.rl.env.seeded_env import SeededEnv as BaseSeededEnv
from scripts.rl.scenario_check.inputs import read_ini
from scripts.rl.scenario_check.inputs import write_ini
from scripts.rl.scenario_check.reports import inspect
from scripts.rl.scenario_check.reports import acceptance
from scripts.rl.scenario_check.reports import write_campaign_report

_ACTIVE = set()
_LOCK = threading.Lock()
_CANCEL = threading.Event()


class SeededEnv(BaseSeededEnv):
    """Per-seed env tracked by this queue's interrupt handling; jamming resets record event timing."""

    def __init__(self, binary, configs, output, case):
        super().__init__(binary, configs, output, case, initial_seed=201, band='sub-6')
        with _LOCK:
            _ACTIVE.add(self)

    def reset(self, *, seed, options=None):
        if _CANCEL.is_set():
            raise RuntimeError('scenario check interrupted')
        initial = super().reset(seed=seed, options=options)
        if self.case.get('mission')=='jamming':
            from scripts.rl.scenario_check.validation import jammer_timing
            verified = jammer_timing(self.configs[str(seed)],self.case,seed,self.inner._cmd)
            directory = next(Path(x.split('=',1)[1]) for x in self.inner._cmd if x.startswith('--output-dir='))
            write_json(directory/'event_timing.json',verified)
        return initial

    def close(self):
        super().close()
        with _LOCK:
            _ACTIVE.discard(self)


def placement_methods(case):
    methods = case.get('placement_benchmarks', ['geometric','optimization'] if case['mission']=='coverage' else [])
    if len(set(methods))!=len(methods) or any(m not in ('geometric','optimization') for m in methods):
        raise ValueError('unknown or repeated placement benchmark')
    if methods and case['mission']!='coverage':
        raise ValueError('placement benchmarks apply only to coverage')
    return methods


def validate_inputs(source):
    source = Path(source)
    campaign = json.loads((source/'scenario-check.json').read_text())
    if campaign['scenario_check_version'] not in (1,2) or campaign['training_enabled'] is not False:
        raise ValueError('expected a version 1 or 2 checks-only campaign')
    for relative,digest in campaign['input_hashes'].items():
        if sha256_file(source/relative) != digest:
            raise ValueError(f'input changed after preparation: {relative}; review before replacing its fingerprint')
    cases = campaign['cases']
    count = sum((3+len(placement_methods(c)))*len(c['seeds']) for c in cases)
    if not cases or len({c['name'] for c in cases})!=len(cases) or count!=campaign['episodes_expected']:
        raise ValueError('case inventory and expected episode count disagree')
    if campaign['scenario_check_version']==1 and (len(cases)!=24 or count!=168):
        raise ValueError('expected original 24 scenarios / 168 episodes')
    if campaign['scenario_check_version']==2:
        from scripts.rl.scenario_check.validation import jammer_timing
        for case in cases:
            if set(case['seeds'])!={'201','202'}:
                raise ValueError('correction checks require paired diagnostic seeds 201/202')
            for seed,settings in case['seeds'].items():
                config = source/case['name']/settings['run_config']
                if case['mission']=='jamming':
                    jammer_timing(config,case,int(seed))
    return campaign


def require_binary(binary, mesh):
    binary = Path(binary).resolve()
    if not binary.is_file() or not os.access(binary,os.X_OK):
        raise ValueError(f'simulator binary missing or not executable: {binary}; build first')
    sources = [mesh/'sim.cc',mesh/'CMakeLists.txt',*mesh.joinpath('src').rglob('*.cc'),*mesh.joinpath('src').rglob('*.h')]
    newer = [p for p in sources if p.stat().st_mtime > binary.stat().st_mtime]
    if newer:
        raise ValueError('simulator build is older than sources; run ./ns3 build scratch/mesh-sim/sim from the ns3-mmwave root')
    return binary


def snapshot(source, target):
    shutil.copytree(source,target)
    source_root = source.resolve()
    target_root = target.resolve()
    # Pin every input reference to this archive, including per-seed jammer routes.
    for archived_ini in target_root.rglob("*.ini"):
        source_ini = source_root / archived_ini.relative_to(target_root)
        ini = read_ini(archived_ini)
        scenario = parse_ini(source_ini).get("scenario", {})
        for key in ('nodes_file','buildings_file','jammers_file'):
            value = scenario.get(key)
            if value:
                original = (source_ini.parent / value).resolve()
                relative = original.relative_to(source_root)
                ini['scenario'][key] = str(target_root / relative)
        write_ini(archived_ini, ini)
    hashes = {str(p.relative_to(target)):sha256_file(p) for p in sorted(target.rglob('*'))
              if p.is_file() and p.name != 'scenario-check.json'}
    saved = json.loads((target/'scenario-check.json').read_text())
    saved['input_hashes'] = hashes
    saved['source_campaign_sha256'] = sha256_file(source/'scenario-check.json')
    write_json(target/'scenario-check.json',saved)
    return {**hashes,'scenario-check.json':sha256_file(target/'scenario-check.json')}


def run_case(case, source, output, binary):
    from scripts.rl.policy.evaluate import evaluate, PolicySpec, Prepared, HoldPolicy
    from scripts.rl.policy.scripted import ReferencePolicy
    from scripts.rl.scenario_check.placement import prepare
    started = time.monotonic()
    folder = source/case['name']
    destination = output/'Main'/case['name']
    destination.mkdir(parents=True)
    reference = json.loads((folder/'reference.json').read_text())
    (destination/'README.md').write_text(
        f'# {case["name"]}\n\n'
        'Standalone baseline-only GUI evaluation: select this folder.\n'
        'Policies and episode directories are indexed by eval_manifest.json.\n'
        'Scenario checks and thresholds are in scenario_check.json.\n'
        'Per-episode scenario_timeline.csv and link_timeline.csv contain mission and LOS/SINR histories.\n')
    configs = {s:folder/v['run_config'] for s,v in case['seeds'].items()}
    specs = [PolicySpec('hold',lambda env,seed:Prepared(HoldPolicy())),
             PolicySpec('random_valid',lambda env,seed:Prepared(ReferencePolicy(env,reference,random_valid=True)),
                        {'description':'Uniform native-valid actions, frozen before scenario event.'}),
             PolicySpec('scripted',lambda env,seed:Prepared(ReferencePolicy(env,reference)),
                        {'description':reference['description']})]
    prepared = {}
    if placement_methods(case):
        for method in placement_methods(case):
            # Preparation runs in make_env, after the three shared-start controls.
            specs.append(PolicySpec(method,lambda env,seed:Prepared(HoldPolicy()),
                {'description':'Initial-placement benchmark; no route from common start.'}))
    def make_env(policy):
        chosen = configs
        if policy in ('geometric','optimization'):
            chosen,meta = prepare(policy,folder,output/'planning'/case['name']/policy,binary)
            prepared[policy] = meta
            specs_by_name[policy].metadata.update(meta)
        return SeededEnv(binary,chosen,destination/policy,case)
    specs_by_name = {spec.name:spec for spec in specs}
    from scripts.rl.env.config import read_scenario_identity
    base = dict(label=f'10-23 scenario check {case["name"]}',sim_binary=str(binary),
        run_config=str(folder/'run.ini'),band='sub-6',training=None,
        seed_roles=dict(training_seed=None,diagnostic_evaluation=[201,202],channel_planning=[311],optimizer=[7]),
        scenario_identity=read_scenario_identity(str(folder/'run.ini')))
    errors = []
    try:
        manifest = evaluate(make_env,specs,[201,202],destination,base)
    except Exception as exc:
        errors.append(f'{type(exc).__name__}: {exc}')
        (destination/'execution_error.log').write_text(traceback.format_exc())
        manifest = json.loads((destination/'eval_manifest.json').read_text())
    if manifest['status'] != 'completed':
        errors.append(f'evaluation {manifest["status"]}; inspect eval_manifest.json')
    buildings = json.loads((folder/'buildings.json').read_text())
    results,episodes = {},[]
    for policy,block in manifest['policies'].items():
        for episode in block['episodes']:
            if episode['status'] != 'completed':
                continue
            try:
                metrics = inspect(episode['episode_dir'],case,episode['seed'],buildings)
            except Exception as exc:
                errors.append(f'{policy} seed {episode["seed"]} audit failed: {exc}')
                continue
            results[(policy,episode['seed'])] = metrics
            episodes.append(dict(policy=policy,seed=episode['seed'],episode_dir=episode['episode_dir'],**metrics))
    if all((p,s) in results for p in ('hold','scripted') for s in (201,202)):
        gate = acceptance(case,results)
    else:
        gate = dict(accepted=False,reasons=['hold/scripted reference evidence incomplete'],coverage_threshold=None)
    outcome = {**case,'status':'failed' if errors else 'accepted' if gate['accepted'] else 'needs_review',
        'error': '; '.join(errors) if errors else None,
        'acceptance':gate,'episodes':episodes,'wall_s':time.monotonic()-started}
    write_json(destination/'scenario_check.json',outcome)
    return outcome


def run(source, output, binary, workers):
    mesh = find_mesh_root()
    source,output = Path(source).resolve(),Path(output).resolve()
    campaign = validate_inputs(source)
    binary = require_binary(binary,mesh)
    if output.exists():
        raise FileExistsError(f'output already exists: {output}; inspect its status, or use --output with a fresh directory. Nothing overwritten.')
    _CANCEL.clear()
    output.mkdir(parents=True)
    archived = output/'inputs'
    digests = snapshot(source,archived)
    # Resolve linked libraries only on the user's launch, before simulator work.
    from scripts.baselines.runtime_identity import channel_runtime_identity, planner_code_identity
    identity = dict(binary=channel_runtime_identity(binary),planners=planner_code_identity(),
        scripts={str(p.relative_to(mesh)):sha256_file(p) for p in sorted((mesh/'scripts').rglob('*.py'))
                 if '__pycache__' not in p.parts and 'tests' not in p.parts},inputs=digests)
    write_json(output/'runtime_identity.json',identity)
    main = output/'Main'
    main.mkdir()
    (main/'README.md').write_text('# October 23 scenario checks\n\n'
        'Open the scenario folder of interest as a standalone evaluation in the GUI.\n\n'+
        '\n'.join(f'- {c["name"]}' for c in campaign['cases'])+'\n')
    status = dict(scenario_check_status_version=1,status='running',started_at=now_iso(),
        ended_at=None,training_launched=False,episodes_expected=campaign['episodes_expected'],cases_expected=len(campaign['cases']),
        cases_completed=0,identity_sha256=canonical_sha256(identity),workers=workers,
        cases={c['name']:'queued' for c in campaign['cases']})
    write_json(output/'scenario_check_status.json',status)
    started = time.monotonic()
    outcomes = []
    status_lock = threading.Lock()
    print(f'10-23 scenario checks only: {len(campaign["cases"])} cases, {campaign["episodes_expected"]} episodes, {workers} workers. No training, no wall-clock cutoff.',flush=True)
    print(f'Results: {output}\nCompletion: scenario_check_status.json and RESULTS.md',flush=True)
    def job(case):
        with status_lock:
            status['cases'][case['name']] = 'running'
            write_json(output/'scenario_check_status.json',status)
        try:
            return run_case(case,archived,output,binary)
        except Exception as exc:
            error = f'{type(exc).__name__}: {exc}'
            log = output/'errors'
            log.mkdir(exist_ok=True)
            (log/f'{case["name"]}.log').write_text(traceback.format_exc())
            return {**case,'status':'failed','error':error,'episodes':[]}
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        pending = {pool.submit(job,case):case for case in campaign['cases']}
        for future in as_completed(pending):
            outcome = future.result()
            outcomes.append(outcome)
            with status_lock:
                status['cases'][outcome['name']] = outcome['status']
                status['cases_completed'] = len(outcomes)
                status['wall_s'] = time.monotonic()-started
                write_json(output/'scenario_check_status.json',status)
            print(f'{len(outcomes)}/{len(campaign["cases"])} {outcome["name"]}: {outcome["status"]}',flush=True)
    except BaseException:
        _CANCEL.set()
        for future in pending:
            future.cancel()
        with _LOCK:
            active = list(_ACTIVE)
        for env in active:
            env.close()
        status.update(status='interrupted',ended_at=now_iso())
        write_json(output/'scenario_check_status.json',status)
        raise
    finally:
        pool.shutdown(wait=True,cancel_futures=True)
    outcomes.sort(key=lambda item:item['name'])
    write_campaign_report(output,outcomes)
    failed = sum(o['status']=='failed' for o in outcomes)
    rejected = sum(o['status']=='needs_review' for o in outcomes)
    status.update(status='failed' if failed else 'completed_with_rejections' if rejected else 'completed',
                  ended_at=now_iso(),cases_failed=failed,cases_rejected=rejected,
                  wall_s=time.monotonic()-started)
    write_json(output/'scenario_check_status.json',status)
    print(f'DONE: {status["status"]}; {failed} execution errors; {rejected} cases need review. No training launched.',flush=True)
    print(f'Read {output}/RESULTS.md',flush=True)
    return 1 if failed else 2 if rejected else 0
