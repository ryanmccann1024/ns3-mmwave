"""Behavior checks preserved from the experiment pilots; no native simulation."""
import subprocess
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from scripts.rl.env.rewards import RewardComposer
from scripts.rl.env.rewards import reward_schema
from scripts.rl.env.rewards.objectives import COMPONENT_NAMES
from scripts.rl.tests.env.test_observations_rewards import CONTRACT

ROOT=Path(__file__).resolve().parents[4]
INPUT=ROOT/'inputs/custom/10-23-1'


@pytest.fixture(autouse=True)
def forbid_processes(monkeypatch):
    def forbidden(*a,**k):raise AssertionError('no simulator, fake peer or training subprocess')
    monkeypatch.setattr(subprocess,'Popen',forbidden)


def score(mission,context,window=None,contract=None):
    return RewardComposer([COMPONENT_NAMES[mission]],[1]).compose(window or {'scored_ticks':2},0,contract or {},context)


@pytest.mark.parametrize('fraction',[0.,.2,.49,.5,.89,1.])
def test_coverage_is_continuous_not_thresholded(fraction):
    assert score('coverage',{'coverage':{'fraction':fraction}}).total==fraction


def test_investigation_single_mean_distance_and_availability():
    contract={'mission':{'goal_x':345,'goal_y':300,'team_radius_m':50},
              'bounds':{'x_min':0,'x_max':400,'y_min':0,'y_max':400}}
    context={'nodes':[[345,300],[445,300]],'node_available':[True,True]}
    far=score('investigation',context,contract=contract).total
    assert far==pytest.approx(1-25/np.hypot(400,400))
    context['nodes'][1]=[395,300]
    assert score('investigation',context,contract=contract).total==1
    context['nodes'][1]=[445,300];context['node_available'][1]=False
    assert score('investigation',context,contract=contract).total==1
    context['node_available']=[False,False]
    assert score('investigation',context,contract=contract).total==0


@pytest.mark.parametrize('mission',['recovery','jamming'])
@pytest.mark.parametrize('ratio',[0.,.2,.89,.9,1.])
def test_event_reward_delivers_partial_feedback_and_no_free_demand(mission,ratio):
    context={'deployment':{'active':True,'eligible_ticks':2},'mission':{
        'survivor_demand_mbps_sum':10,'survivor_delivered_mbps_sum':10*ratio}}
    window={'scored_ticks':2,'demand_mbps_sum':10,'delivered_mbps_sum':10*ratio}
    assert score(mission,context,window).total==pytest.approx(ratio)
    context['deployment']['eligible_ticks']=1
    assert score(mission,context,window).total==0
    context['deployment']={'active':False,'eligible_ticks':0}
    assert score(mission,context,window).total==0
    context['deployment']={'active':True,'eligible_ticks':2}
    context['mission']['survivor_demand_mbps_sum']=0;window['demand_mbps_sum']=0
    assert score(mission,context,window).total==0


def test_jammer_onset_not_reward_identity_but_geometry_is():
    contract={**CONTRACT,'deployment_gate':{'version':1,'source':'control_start_s'},'control_start_s':160}
    comp=COMPONENT_NAMES['jamming'];a=reward_schema([comp],[1],contract=contract)
    contract['control_start_s']=180
    assert a==reward_schema([comp],[1],contract=contract)
    comp=COMPONENT_NAMES['investigation'];contract['mission']={'goal_x':345,'goal_y':300,'team_radius_m':50}
    a=reward_schema([comp],[1],contract=contract)
    contract['bounds']={**contract['bounds'],'x_max':400}
    assert a!=reward_schema([comp],[1],contract=contract)








