"""Behavior checks preserved from the experiment pilots; no native simulation."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from scripts.rl.env.rewards import RewardComposer


def score(name,x,c=None,parameters=None):
    return RewardComposer([name],[1],parameters).compose({'scored_ticks':2},0,c or {'mission':{}},x).total


def test_progress_has_signed_immediate_feedback_and_no_terminal_bonus():
    x={'mission_state':{'previous_distance_m':100,'distance_m':98,'done':False}}
    assert score('team_distance_delta_v2',x)==pytest.approx(.4)
    x['mission_state']['done']=True
    assert score('team_distance_delta_v2',x)==pytest.approx(.4)
    x['mission_state'].update(previous_distance_m=98,distance_m=100)
    assert score('team_distance_delta_v2',x)==pytest.approx(-.4)


def test_coverage_does_not_reward_isolating_peers_for_more_area():
    healthy={'coverage_fraction':.75,'mission_state':{'survivor_delivery':1,'survivor_worst_service':1}}
    spread={'coverage_fraction':.9,'mission_state':{'survivor_delivery':.6,'survivor_worst_service':.43}}
    assert score('service_gated_coverage_v2',healthy)>score('service_gated_coverage_v2',spread)


def test_settling_cost_increases_only_when_current_goal_conditions_hold():
    x={'coverage_fraction':.8,'travel_fraction':1,'mission_state':{'survivor_delivery':1,'survivor_worst_service':1}}
    assert score('coverage_settle_cost_v2',x)==.01
    x['coverage_fraction']=.9
    assert score('coverage_settle_cost_v2',x)==.2
    x['mission_state']['survivor_delivery']=.3
    assert score('coverage_settle_cost_v2',x)==.01


def test_recovery_partial_service_and_available_pair_sinr_are_measured_not_oracle():
    x={'mission_state':{'failure_at_s':None,'survivor_delivery':.1,'survivor_worst_service':.1},
       'links':[[40,0,1],[-10,0,1],[40,0,1]],'node_available':[True,False,True]}
    assert score('post_failure_service_v2',x)==0
    assert score('post_failure_sinr_v2',x)==0
    x['mission_state']['failure_at_s']=10
    assert score('post_failure_service_v2',x)==.1
    assert score('post_failure_sinr_v2',x)==pytest.approx(1/6)
    x['links'][1][0]=20;x['mission_state'].update(survivor_delivery=.4,survivor_worst_service=.4)
    assert score('post_failure_service_v2',x)==.4
    assert score('post_failure_sinr_v2',x)==pytest.approx(2/3)


def test_frozen_only_cli_cannot_request_online_by_default_in_generated_command(tmp_path,monkeypatch):
    from scripts.rl import online
    captured=[]
    monkeypatch.setattr(online,'run_online',lambda *args,**kwargs:captured.append(args))
    monkeypatch.setattr(sys,'argv',['online','--run-dir',str(tmp_path/'train'),'--sim-binary','unused',
        '--output-dir',str(tmp_path/'frozen'),'--modes','fixed_sampled'])
    online.main()
    assert online.operation_modes(captured[0][-1])==('fixed_sampled',)
    assert online.operation_modes(online.DEFAULT_MODES)==('fixed_sampled','online')
    with pytest.raises(ValueError):online.operation_modes(['fixed_sampled','fixed_sampled'])


def test_frozen_only_operation_never_calls_learn_and_verifies_parameters(tmp_path,monkeypatch):
    """Exercise the real mode loop with in-memory doubles; no process or PPO training."""
    from scripts.rl import online
    manifest={'run_config':'unused','seed':101,'band':'sub-6','hyperparameters':{},'evaluation':{'seeds':[201,202]}}
    bundle=SimpleNamespace(manifest=manifest,model_path='unused',describe=lambda:{'verified':'stub'})
    monkeypatch.setattr(online,'read_bundle',lambda *a:bundle)
    monkeypatch.setattr(online,'selection_from_manifest',lambda *a:None)
    monkeypatch.setattr(online,'eval_selection',lambda *a:None)
    monkeypatch.setattr(online,'read_scenario_identity',lambda *a:{'identity':'stub'})
    monkeypatch.setattr(online,'check_compatibility',lambda *a,**k:None)
    monkeypatch.setattr(online,'parameter_digest',lambda *a:'unchanged-parameters')
    monkeypatch.setattr(online,'ActionMasker',lambda env,*a:env)
    class Env:
        def __init__(self,*a,**k):self.contract={'num_decisions':600,'num_links':3};self.destination=Path(k['output_dir'])
        def reset(self,**k):return 'initial'
        def close(self):pass
    class Model:
        def set_random_seed(self,seed):pass
        def learn(self,*a,**k):pytest.fail('frozen-only mode called learn')
    monkeypatch.setattr(online,'MeshRlEnv',Env)
    monkeypatch.setattr(online.MaskablePPO,'load',lambda *a,**k:Model())
    monkeypatch.setattr(online,'ModelPolicy',lambda model,deterministic:SimpleNamespace(deterministic=deterministic))
    def episode(env,policy,seed,initial):
        assert not policy.deterministic and initial=='initial'
        dest=env.destination/'episode-0000';dest.mkdir(parents=True)
        (dest/'rl_episode.json').write_text(json.dumps({'status':'completed','steps':600,'cumulative_reward':1}))
        return SimpleNamespace(episode_dir=str(dest))
    monkeypatch.setattr(online,'run_episode',episode)
    monkeypatch.setattr(online,'episode_metrics',lambda *a:{'delivery_ratio':1})
    monkeypatch.setattr(online,'endpoint_metrics',lambda *a:{})
    monkeypatch.setattr(online,'write_reward_matrix',lambda *a:None)
    binary=tmp_path/'not-a-simulator';binary.write_text('file identity only')
    result=online.run_online('unused',binary,tmp_path/'frozen',[201,202],modes=['fixed_sampled'])
    assert result['online_experiment_version']==4 and result['modes']==['fixed_sampled']
    assert len(result['episodes'])==2 and result['status']=='completed'
    assert all(e['mode']=='fixed_sampled' and e['update_cycles']==0 and e['initial_parameter_sha256']==e['final_parameter_sha256'] for e in result['episodes'])
    assert online.run_online('unused',binary,tmp_path/'frozen',[201,202],modes=['fixed_sampled'])==result
