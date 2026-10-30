"""Scripted reference controllers and baseline execution/outcome validation.

Two route formats exist and keep their own controllers:

- `ReferencePolicy` follows scenario-check `reference.json` routes
  (`routes: {node_id: [[x, y, z], ...]}`) after the env's `gate_s`, with joint
  swept-distance reservation between peers.
- `ScriptedMissionPolicy` follows mission-pilot waypoints
  (`waypoints`, `node_order`, `start_after_failure`, optional `start_after_s`,
  `start_below_delivery` and `parallel`).

Both read live facts from `env._protocol.facts` and only propose actions that the
native mask allows; the simulator owns final validation.
"""

import json
from pathlib import Path

import numpy as np

from scripts.artifact_io import now_iso, sha256_file, write_json
from scripts.rl.env.geometry import swept_distance


class ScriptedMissionPolicy:
    name = 'scripted'

    def __init__(self, env, reference):
        self.env = env
        self.reference = reference
        self.cursor = {}

    def start_episode(self, seed):
        self.cursor = {node: 0 for node in self.reference['waypoints']}
        self.triggered = False

    def act(self, obs, mask, contract):
        actions = np.full(contract['max_controlled_nodes'], 4, dtype=np.int64)
        facts = self.env._protocol.facts
        if not self.triggered and 'start_below_delivery' in self.reference:
            self.triggered = facts['mission_state']['survivor_delivery'] < self.reference['start_below_delivery']
            if not self.triggered:
                return actions
        if facts['mission_state']['time_s'] < self.reference.get('start_after_s', 0):
            return actions
        if self.reference['start_after_failure'] and all(facts['node_available']):
            return actions
        for node in self.reference['node_order']:
            i = contract['node_ids'].index(node)
            if not facts['node_available'][i]:
                continue
            slot = contract['slot_node_ids'].index(node)
            tolerance = .51*contract['slot_speed_mps'][slot]*contract['decision_interval_s']
            points = self.reference['waypoints'][node]
            while self.cursor[node] < len(points):
                target = points[self.cursor[node]]
                position = facts['nodes'][i]
                if max(abs(target[a]-position[a]) for a in (0, 1)) <= tolerance:
                    self.cursor[node] += 1
                    continue
                axis = 0 if abs(target[0]-position[0]) > tolerance else 1
                action = 2*axis+int(target[axis] > position[axis])
                if mask[slot*5+action]:
                    actions[slot] = action
                # Sequential (legacy) references move only the first unfinished node.
                if not self.reference.get('parallel', False):
                    return actions
                break
        return actions


class ReferencePolicy:
    """Follow precomputed routes after the event, using the live native masks.

    Joint swept-distance reservation selects safe proposals. The simulator owns
    final action validation. A stalled route is reported, never counted as proof
    that the scenario is feasible.
    """
    name = 'scripted'

    def __init__(self, env, reference, *, random_valid=False):
        self.env, self.reference, self.random_valid = env, reference, random_valid

    def start_episode(self, seed):
        self.cursor = dict.fromkeys(self.reference['routes'], 0)
        self.rng = np.random.default_rng(seed)

    def act(self, obs, mask, contract):
        facts = self.env._protocol.facts
        actions = np.full(contract['max_controlled_nodes'], 4, dtype=np.int64)
        if facts['mission_state']['time_s'] < self.env.gate_s:
            return actions
        if self.random_valid:
            for slot in range(len(actions)):
                actions[slot] = self.rng.choice(np.flatnonzero(mask[slot*5:(slot+1)*5]))
            return actions
        nodes = [list(p[:3]) for p in facts['nodes']]
        proposed = [list(p) for p in nodes]
        by_id = {node: i for i, node in enumerate(contract['node_ids'])}
        # Highest priority rotates, avoiding permanent preference for node zero.
        slots = list(range(contract['num_controlled']))
        tick = round(facts['mission_state']['time_s'])
        slots = slots[tick % len(slots):] + slots[:tick % len(slots)]
        for slot in slots:
            node = contract['slot_node_ids'][slot]
            i = by_id[node]
            if not facts['node_available'][i]:
                continue
            if facts['mission_state']['time_s'] < self.env.gate_s + 12*(i//3):
                continue
            speed = contract['slot_speed_mps'][slot] * contract['decision_interval_s']
            tolerance = .51*speed
            points = self.reference['routes'][node]
            while self.cursor[node] < len(points):
                target = points[self.cursor[node]]
                if max(abs(target[k]-nodes[i][k]) for k in (0, 1)) <= tolerance:
                    self.cursor[node] += 1
                    continue
                axis = 0 if abs(target[0]-nodes[i][0]) > tolerance else 1
                action = 2*axis + int(target[axis] > nodes[i][axis])
                if mask[slot*5+action]:
                    end = list(nodes[i])
                    end[axis] += speed * (1 if action % 2 else -1)
                    if all(not facts['node_available'][j] or j == i or
                           swept_distance(nodes[i], end, nodes[j], proposed[j]) >= contract['unsafe_separation_m'] + .05
                           for j in range(len(nodes))):
                        actions[slot], proposed[i] = action, end
                break
        return actions


def run_baselines(config, scene, output):
    """Hold / random / scripted mission references for one pilot scene; reuse a completed manifest."""
    from scripts.rl.env.mesh_env import MeshRlEnv
    from scripts.rl.env.selection import resolve_selection
    from scripts.rl.policy.evaluate import evaluate, PolicySpec, Prepared, HoldPolicy, RandomValidPolicy
    output = Path(output)
    manifest = output/'eval_manifest.json'
    if manifest.exists():
        saved = json.loads(manifest.read_text())
        if saved['status'] == 'completed':
            return saved
        raise ValueError(f'incomplete baseline artifacts: {output}; use a fresh output root')
    folder = Path(config['inputs'])/scene['name']
    ini = folder/'run.ini'
    reference = json.loads((folder/'reference.json').read_text())
    selection = resolve_selection(str(ini), telemetry='steps')
    def make_env(policy):
        return MeshRlEnv(config['execution']['sim_binary'], str(ini), seed=config['pilot']['preflight_seeds'][0],
            output_dir=str(output/policy), selection=selection, band='sub-6')
    specs = [PolicySpec('hold', lambda e, s: Prepared(HoldPolicy())),
             PolicySpec('random_valid', lambda e, s: Prepared(RandomValidPolicy())),
             PolicySpec('scripted', lambda e, s: Prepared(ScriptedMissionPolicy(e, reference)), {'description': reference['description']})]
    return evaluate(make_env, specs, config['pilot']['preflight_seeds'], output,
        {'label': 'Hold / random / scripted mission references', 'sim_binary': config['execution']['sim_binary'],
         'run_config': str(ini), 'band': 'sub-6', 'seed_roles': {'evaluation': 'scenario-validation diagnostics; not held out'}})


def validate_outcomes(config, scene, manifest):
    """Reject trivial or infeasible scenes from completed hold/scripted reference episodes."""
    from scripts.rl.policy.episode_review import inspect_episode, write_motion_review
    if manifest['status'] != 'completed':
        raise ValueError(f'incomplete references: {scene["name"]}')
    folder = Path(config['inputs'])/scene['name']
    buildings = json.loads((folder/'buildings.json').read_text())
    results = {}
    for policy, block in manifest['policies'].items():
        for episode in block['episodes']:
            values = inspect_episode(episode['episode_dir'], buildings)
            results[(policy, episode['seed'])] = values
            write_motion_review(episode['episode_dir'])
    p = config['pilot']
    for seed in p['preflight_seeds']:
        hold, script = results[('hold', seed)], results[('scripted', seed)]
        if scene['mission'] == 'coverage':
            if script['final_minute_coverage']-hold['final_minute_coverage'] < p['coverage_min_gain']:
                raise ValueError(f'{scene["name"]} seed {seed}: moving reference does not improve coverage enough')
            if script['final_minute_original_delivery'] < .8:
                raise ValueError('coverage reference loses too much service')
        elif scene['mission'] == 'investigation':
            if hold['investigation_success'] or not script['investigation_success']:
                raise ValueError(f'{scene["name"]} seed {seed}: team investigation is trivial or infeasible')
        else:
            if hold['pre_failure_survivor_delivery'] < p['recovery_pre_delivery_min']:
                raise ValueError(f'{scene["name"]} seed {seed}: service already poor before failure')
            if hold['post_failure_survivor_delivery'] > p['recovery_hold_post_delivery_max'] or hold['recovery_success']:
                raise ValueError(f'{scene["name"]} seed {seed}: hold already solves recovery')
            if script['final_minute_survivor_delivery'] < p['recovery_scripted_final_delivery_min'] or not script['recovery_success']:
                raise ValueError(f'{scene["name"]} seed {seed}: scripted regrouping fails')
    return {f'{policy}/seed-{seed}': values for (policy, seed), values in results.items()}


def _physical_ini(path, base):
    """Physics, windows and gates of an INI; referenced inputs by content; selection keys excluded."""
    from scripts.sim_support import parse_ini
    value = {section: dict(keys) for section, keys in parse_ini(path).items()}
    value.get("scenario", {}).pop("name", None)
    for key in ("nodes_file", "buildings_file", "jammers_file"):
        ref = value.get("scenario", {}).get(key)
        if ref:
            target = Path(ref) if Path(ref).is_absolute() else Path(base) / ref
            value["scenario"][key] = sha256_file(target)
    for key in list(value.get("rl", {})):
        if key.startswith(("reward_", "observation_", "telemetry")):
            value["rl"].pop(key)
    return value


def _baseline_policy(policy, env, reference_kind, reference, gate_s):
    from scripts.rl.policy.evaluate import HoldPolicy, RandomValidPolicy
    if policy == "hold":
        return HoldPolicy()
    if policy == "random_valid":
        # Gated scenarios wait for the event before random actions, as their original controls did.
        return ReferencePolicy(env, {"routes": {}}, random_valid=True) if gate_s is not None else RandomValidPolicy()
    if policy != "scripted":
        raise ValueError(f"unknown baseline policy {policy!r}")
    if reference_kind == "scenario_routes_v1":
        return ReferencePolicy(env, reference)
    if reference_kind == "mission_waypoints_v1":
        return ScriptedMissionPolicy(env, reference)
    raise ValueError("scripted baseline needs a reference of kind scenario_routes_v1 or mission_waypoints_v1")


def run_baseline(policy, seed, seed_role, run_config, output_dir, sim_binary, *, gate_s=None,
                 reference_kind=None, reference_path=None, band=None, case=None, decision_records=None):
    """One baseline policy for one seed on the seeded env; writes ``eval_manifest.json``."""
    from scripts.rl.env.config import read_scenario_identity
    from scripts.rl.policy.operation import DiagnosticEnv, decision_recording
    from scripts.rl.policy.evaluate import PolicySpec, Prepared, evaluate
    from scripts.rl.env.seeded_env import resolve_band
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"refusing to overwrite baseline output {output}; use a new attempt directory")
    reference = json.loads(Path(reference_path).read_text()) if reference_path else None
    configs = {str(seed): str(run_config)}
    case = dict(case or {})
    if gate_s is not None:
        case["seeds"] = {str(seed): {"gate_s": gate_s}}
    spec = PolicySpec(policy, lambda env, s: Prepared(_baseline_policy(policy, env, reference_kind, reference, gate_s)),
                      {"reference_kind": reference_kind, "reference_sha256": sha256_file(reference_path)
                       if reference_path else None})
    resolved, _ = resolve_band(run_config, band)
    manifest = evaluate(lambda name: DiagnosticEnv(sim_binary, configs, output / name, case, initial_seed=seed,
                                                   band=band,
                                                   decision_records=decision_recording(decision_records, name)),
                        [spec], [seed], output,
                        dict(label=f"baseline {policy} seed {seed}", sim_binary=str(sim_binary),
                             run_config=str(run_config), band=resolved,
                             scenario_identity=read_scenario_identity(str(run_config)),
                             seed_roles={"role": seed_role, "seed": int(seed)}))
    return manifest


def import_baseline(source, policy, seed, run_config, output_dir, *, band=None):
    """Import one completed control episode after its physical identity, windows and seed match."""
    import copy
    import shutil
    source, output = Path(source), Path(output_dir)
    manifest_path = source / "eval_manifest.json"
    saved = json.loads(manifest_path.read_text())
    if saved.get("status") != "completed":
        raise ValueError(f"{manifest_path} is not a completed evaluation")
    block = (saved.get("policies") or {}).get(policy)
    episode = next((e for e in (block or {}).get("episodes", []) if int(e["seed"]) == int(seed)), None)
    if episode is None or episode.get("status") != "completed":
        raise ValueError(f"{manifest_path} has no completed {policy} episode for seed {seed}")
    episode_dir = Path(episode["episode_dir"])
    metadata = json.loads((episode_dir / "rl_episode.json").read_text())
    if int(metadata.get("seed", -1)) != int(seed) or metadata.get("status") != "completed":
        raise ValueError(f"{episode_dir} is not a completed seed {seed} episode")
    command = metadata.get("command") or []
    source_ini = next((Path(x.split("=", 1)[1]) for x in command if x.startswith("--run-config=")), None)
    source_band = next((x.split("=", 1)[1] for x in command if x.startswith("--band=")), None)
    archived = episode_dir / "inputs" / "run.ini"
    if source_ini is None or not archived.is_file():
        raise ValueError(f"{episode_dir} does not record its archived run.ini and source path")
    from scripts.rl.env.seeded_env import resolve_band
    ran, wanted = resolve_band(archived, source_band)[0], resolve_band(run_config, band)[0]
    if ran != wanted:
        raise ValueError(f"{episode_dir} ran band {ran!r}, not {wanted!r}")
    if _physical_ini(archived, source_ini.parent) != _physical_ini(run_config, Path(run_config).parent):
        raise ValueError(f"{episode_dir}: physical scenario, windows or gate differ from {run_config}")
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"refusing to overwrite baseline output {output}; use a new attempt directory")
    target = output / policy / episode_dir.name
    shutil.copytree(episode_dir, target)
    imported = copy.deepcopy(episode)
    imported["episode_dir"] = str(target)
    result = copy.deepcopy(saved)
    result.update(seeds=[int(seed)], episodes_expected=1, episodes_completed=1,
                  imported_from=dict(eval_manifest=str(manifest_path), eval_manifest_sha256=sha256_file(manifest_path),
                                     episode_dir=str(episode_dir),
                                     steps_sha256=sha256_file(episode_dir / "steps.jsonl"),
                                     rl_episode_sha256=sha256_file(episode_dir / "rl_episode.json"),
                                     imported_at=now_iso(), new_evaluation=False))
    value = imported.get("return")
    result["policies"] = {policy: {**{k: v for k, v in block.items() if k not in ("episodes", "summary")},
                                   "episodes": [imported],
                                   "summary": dict(expected_episodes=1, completed_episodes=1, mean_return=value,
                                                   min_return=value, max_return=value,
                                                   revalidated_slots_total=imported.get("revalidated_slots_total") or 0,
                                                   mask_violations_total=imported.get("mask_violations") or 0)}}
    write_json(output / "eval_manifest.json", result)
    return result


