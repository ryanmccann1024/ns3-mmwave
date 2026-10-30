"""Behavior checks preserved from the experiment pilots; no native simulation."""
import copy
import json
from types import SimpleNamespace

import pytest

from scripts.rl.env.rewards import RewardComposer


def score(name,context,contract,parameters=None):
    return RewardComposer([name],[1],parameters).compose({'scored_ticks':2},0,contract,context).total


def test_investigation_approach_rewards_every_peer_and_weights_the_slowest():
    c={'mission':{'goal_x':0,'goal_y':0,'team_radius_m':50,'arrival_radius_m':15}}
    x={'nodes':[[200,0,0],[100,0,0],[15,0,20]],'node_available':[True]*3}
    start=score('team_approach_cost_v1',x,c)
    slow=copy.deepcopy(x);slow['nodes'][0][0]-=10
    fast=copy.deepcopy(x);fast['nodes'][1][0]-=10
    assert score('team_approach_cost_v1',slow,c)<score('team_approach_cost_v1',fast,c)<start
    x['nodes']=[[50,0,0],[45,0,0],[15,0,20]]
    assert score('team_approach_cost_v1',x,c)==0


def test_local_setup_reward_requires_current_team_arrival_and_falls_back():
    c={'mission':{'dwell_s':30}}
    x={'mission':{'goal_coverage_fraction':1},'mission_state':{'connected_arrival':False,'arrival_streak_s':30}}
    assert score('investigation_setup_v1',x,c)==0
    x['mission_state']['connected_arrival']=True
    assert score('investigation_setup_v1',x,c)==1
    x['mission_state'].update(connected_arrival=False,investigation_completed_at_s=100)
    assert score('investigation_setup_v1',x,c)==0


def test_recovery_preserves_deployment_only_before_measured_failure():
    c={'bounds':{'x_min':0,'x_max':400,'y_min':0,'y_max':400},'mission':{}}
    x={'origin_fraction':.1,'mission_state':{'failure_at_s':None}}
    assert score('recovery_deployment_cost_v1',x,c)>0
    x['mission_state']['failure_at_s']=300
    assert score('recovery_deployment_cost_v1',x,c)==0


def test_recovery_requires_current_service_and_geographic_coverage():
    c={'mission':{'recovery_delivery_target':.9,'recovery_worst_target':.8,'dwell_s':30}}
    x={'coverage_fraction':.1,'mission_state':{'failure_at_s':300,'survivor_delivery':1,'survivor_worst_service':1,'coverage_target':.09,'recovery_streak_s':30}}
    assert score('recovery_response_deficit_v1',x,c)==0
    assert score('recovery_settle_v1',x,c)==1
    x['coverage_fraction']=.01
    assert score('recovery_response_deficit_v1',x,c)>0
    assert score('recovery_settle_v1',x,c)==0
    x['coverage_fraction']=.1;x['mission_state']['survivor_delivery']=.4
    assert score('recovery_settle_v1',x,c)==0


def test_post_update_validation_runs_first_and_last_after_optimizer_only(tmp_path):
    from scripts.rl.agents.post_update import PostUpdateValidation
    calls=[]
    class Child:
        def update_locals(self,values):pass
        def on_step(self):calls.append(self.n_calls+1);return True
        def on_training_end(self):pass
    callback=PostUpdateValidation([Child()],tmp_path,3000)
    callback.model=SimpleNamespace(num_timesteps=600,_n_updates=0)
    callback._on_rollout_start();assert calls==[]
    callback.model._n_updates=10
    callback._on_rollout_start();assert calls==[600]
    callback._on_rollout_start();assert calls==[600]
    callback.model.num_timesteps=1200;callback.model._n_updates=20
    callback._on_rollout_start();assert calls==[600]
    callback.model.num_timesteps=3000;callback.model._n_updates=50
    callback._on_rollout_start();assert calls==[600,3000]
    callback.model.num_timesteps=18000;callback.model._n_updates=300
    callback._on_training_end();assert calls==[600,3000,18000]
    assert len(json.loads((tmp_path/'post_update_validation.json').read_text())['events'])==3


def test_post_update_schedule_rejects_partial_rollouts_before_environment_start():
    from scripts.rl.agents.post_update import validate_schedule
    cfg=SimpleNamespace(n_steps=600,total_timesteps=18000)
    cadence=SimpleNamespace(eval_every=3000,checkpoint_every=3000)
    validate_schedule(cfg,cadence)
    for bad in (SimpleNamespace(n_steps=2048,total_timesteps=18000),
                SimpleNamespace(n_steps=600,total_timesteps=18500)):
        with pytest.raises(ValueError):validate_schedule(bad,cadence)
    with pytest.raises(ValueError):validate_schedule(cfg,cadence,resume=object())


