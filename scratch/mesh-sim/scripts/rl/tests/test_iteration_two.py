"""Iteration two: service measurements, cached rescoring, compact output and scheduling."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.rl import campaign, campaign_diagnostics, evaluate, experiment
from scripts.rl.env.config import read_jammer_onsets
from scripts.rl.env.mesh_env import MeshRlEnv
from scripts.rl.env.protocol import ProtocolError
from scripts.rl.env.rewards import RewardComposer, position_context
from scripts.rl.env.selection import resolve_selection
from scripts.rl.policy.baseline_cache import ensure_baselines
from scripts.rl.policy.evaluate import episode_metrics
from scripts.rl.tests.test_evaluation_pipeline import _train
from scripts.sim_support import find_mesh_root


def test_service_measurement_zero_demand_and_protocol(multi_run_config, sim_binary, tmp_path):
    env = MeshRlEnv(sim_binary, multi_run_config, seed=1, output_dir=tmp_path/'env')
    try:
        env.reset()
        facts, contract = copy.deepcopy(env._protocol.facts), env.contract
        facts['node_service'] = [[10, 8], [20, 5], [0, 0]]
        context = position_context(facts, facts['nodes'], facts['nodes'], contract)
        composer = RewardComposer(('worst_node_delivery_fraction',), (0.5,))
        breakdown = composer.compose(facts['window'], 0, contract, context)
        assert breakdown.total == pytest.approx(.125)
        facts['node_service'] = [[0, 0]] * 3
        context = position_context(facts, facts['nodes'], facts['nodes'], contract)
        assert composer.compose(facts['window'], 0, contract, context).valid['worst_node_delivery_fraction'] == 0
        with pytest.raises(ValueError, match='rebuilt simulator'):
            composer.compose(facts['window'], 0, contract, {})
        facts = copy.deepcopy(env._protocol.facts)
        message = {'facts': facts, 'ticks_in_step': facts['window']['ticks'], 'reward': facts['window']['legacy_reward_sum']}
        facts['node_service'][0][0] += 1
        with pytest.raises(ProtocolError, match='endpoint sums'):
            env._protocol._validated_facts(message)
        del facts['node_service']
        with pytest.raises(ProtocolError, match='node_service missing'):
            env._protocol._validated_facts(message)
    finally:
        env.close()


def test_compact_command_and_delayed_onsets(multi_run_config, sim_binary, tmp_path):
    ini = Path(multi_run_config)
    text = ini.read_text().replace('[scenario]', '[scenario]\njammers_file = jammers.json').replace('[rl]', '[rl]\ntraining_jammer_onsets_s = 0.25, 0.75\nevaluation_jammer_onsets_s = 0.25, 0.75')
    ini.write_text(text)
    (ini.parent/'jammers.json').write_text('[]')
    assert read_jammer_onsets(str(ini)) == ((.25, .75), (.25, .75))
    env = MeshRlEnv(sim_binary, str(ini), seed=1, output_dir=tmp_path/'compact', record_viz=False)
    try:
        env.reset()
        assert '--no-viz' in env._cmd and '--jammer-onset-s=0.25' in env._cmd
        env.reset()
        assert '--jammer-onset-s=0.75' in env._cmd
        env.reset(seed=301, options={'seed_source':'eval'})
        assert '--jammer-onset-s=0.75' in env._cmd
    finally:
        env.close()
    ini.write_text(text.replace('0.25, 0.75', 'nan'))
    with pytest.raises(ValueError, match='finite times'):
        read_jammer_onsets(str(ini))


def test_baseline_cache_rescores_without_mutating_cache(sim_binary, multi_run_config, tmp_path, monkeypatch):
    pytest.importorskip('sb3_contrib')
    training = tmp_path/'train'
    from scripts.rl import train
    import sys
    for label, weight in (('train', '1'), ('train2', '2')):
        monkeypatch.setattr(sys, 'argv', ['train','--sim-binary',sim_binary,'--run-config',multi_run_config,
            '--output-dir',str(tmp_path/label),'--verbose','0','--reward-components','delivery_ratio',
            '--reward-weights',weight,'m-ppo','--total-timesteps','16','--n-steps','16','--seed','1'])
        assert train.main() == 0
    cache = tmp_path/'baseline-cache'
    argv = ['--sim-binary',sim_binary,'--run-dir',str(training),'--seeds','11,12',
            '--policies','model,hold,random_valid','--baseline-cache-dir',str(cache)]
    assert evaluate.main(argv+['--output-dir',str(tmp_path/'eval1')]) == 0
    originals = {p.relative_to(cache):p.read_bytes() for p in cache.rglob('*') if p.is_file()}
    argv2=list(argv); argv2[argv2.index('--run-dir')+1]=str(tmp_path/'train2')
    assert evaluate.main(argv2+['--output-dir',str(tmp_path/'eval2')]) == 0
    assert originals == {p.relative_to(cache):p.read_bytes() for p in cache.rglob('*') if p.is_file()}
    first = json.loads((tmp_path/'eval1/eval_manifest.json').read_text())
    second = json.loads((tmp_path/'eval2/eval_manifest.json').read_text())
    assert second['status'] == 'completed' and second['episodes_completed'] == 6
    assert second['eval_manifest_version'] == 3
    for policy in ('hold','random_valid'):
        for a,b in zip(first['policies'][policy]['episodes'],second['policies'][policy]['episodes']):
            assert a['actions_sha256'] == b['actions_sha256']
            assert a['metrics'] == b['metrics']
            assert b['return'] == pytest.approx(2*a['return'])


def test_incomplete_baseline_cache_is_not_overwritten(tmp_path):
    root = tmp_path/'cache'; root.mkdir()
    (root/'cache_identity.json').write_text('{}')
    (root/'trajectories').mkdir()
    with pytest.raises(ValueError, match='incomplete'):
        ensure_baselines(root, {}, lambda out: pytest.fail('must not overwrite'))


def test_main_only_skips_preflight_and_runs_priority_group(tmp_path, monkeypatch):
    config = {'inputs':str(tmp_path),'main_matrices':[], 'initial_scenarios':['small-hold'],
              'execution':{'sim_binary':'unused','output_root':str(tmp_path/'out'),
                           'stages':['main'],'max_workers':4,'threads_per_worker':1}}
    jobs = [{'id':name,'root':str(tmp_path/name),'index':0} for name in ('small-jammer','small-hold')]
    monkeypatch.setattr(campaign,'prepare_phase',lambda *args:([], jobs))
    monkeypatch.setattr(campaign,'run_preflight',lambda *args:pytest.fail('main only'))
    groups=[]
    monkeypatch.setattr(campaign,'run_jobs',lambda group,*args:groups.append([j['id'] for j in group]) or set())
    monkeypatch.setattr(campaign,'write_reward_summary',lambda *args:None)
    assert campaign.run_campaign(config) == 0
    assert groups == [['small-hold'],['small-jammer']]
    assert not (tmp_path/'out/preflight').exists()


def test_iteration_configuration_has_40_jobs_and_18_diagnostics(tmp_path):
    config=campaign.load_config(find_mesh_root()/'inputs/custom/10-09-2/campaign.json')
    config['execution']['output_root']=str(tmp_path/'output')
    plans,jobs=campaign.prepare_phase(config,'main')
    assert len(plans)==10 and len(jobs)==40
    diagnostics=campaign_diagnostics.diagnostic_jobs(config)
    assert len(diagnostics)==18
    for job in diagnostics:
        if '--run-config' in job['command']:
            assert Path(job['command'][job['command'].index('--run-config')+1]).is_file()


def test_delayed_metrics_and_worst_node_delivery(tmp_path):
    records=[{'contract':{'node_ids':['a','b'],'tick_s':.5}}]
    for decision in range(1,36):
        ratio=1 if decision<=2 or decision>=6 else .2
        records.append({'type':'step','decision':decision,'time_s':decision,'ticks_in_step':2,
          'facts':{'window':{'ticks':2,'demand_mbps_sum':10,'delivered_mbps_sum':10*ratio,
                  'connected_pairs_sum':2,'los_pairs_sum':2,'flow_ticks_with_demand':2,
                  'unroutable_flow_ticks':0},'links':[[10,1]],'node_service':[[10,10*ratio],[10,10*ratio]],
                  'safety':{'min_pair_distance_m':1,'unsafe_ticks':0}}})
    (tmp_path/'steps.jsonl').write_text('\n'.join(json.dumps(r) for r in records))
    (tmp_path/'rl_episode.json').write_text(json.dumps({'command':['--jammer-onset-s=2']}))
    metrics=episode_metrics(tmp_path,1)
    assert metrics['pre_jammer_delivery_ratio']==1
    assert metrics['recovery_time_s']==3
    assert metrics['worst_node_delivery_fraction_episode']==pytest.approx((32+3*.2)/35)
    assert metrics['per_node_isolated_decisions']=={'a':0,'b':0}


def test_layout_collision_constraint_is_3d():
    import numpy as np
    from scripts.baselines.planners.objective import layout_separated
    ctx=SimpleNamespace(minimum_separation_m=1)
    assert not layout_separated(ctx,np.array([[0,0,0],[.5,0,0]]))
    assert layout_separated(ctx,np.array([[0,0,0],[0,0,20]]))
