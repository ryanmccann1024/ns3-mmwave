"""Behavior checks preserved from the experiment pilots; no native simulation."""
import copy
from pathlib import Path
import subprocess
import pytest
from scripts.rl.env.rewards import RewardComposer
from scripts.rl.env.rewards import reward_schema
from scripts.rl.env.protocol import CentralizedProtocol
from scripts.rl.env.protocol import ProtocolError
from scripts.rl.tests.env.test_observations_rewards import CONTRACT
from scripts.rl.tests.env.test_observations_rewards import FACTS

ROOT=Path(__file__).resolve().parents[4]
INPUT=ROOT/'inputs/custom/10-23/phase-1'

@pytest.fixture(autouse=True)
def forbid_processes(monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('no simulator, fake peer or training in pure tests')
    monkeypatch.setattr(subprocess,'Popen',forbidden)


def score(mission,context,window=None,contract=None,parameters=None):
    name=f'level0_{mission}_v1'
    composer=RewardComposer([name],[1],{name:parameters or {}})
    return composer.compose(window or {'scored_ticks':2},0,contract or {},context)

@pytest.mark.parametrize('fraction,expected',[(.49,-.001),(.5,1),(.9,1)])
def test_coverage_single_threshold(fraction,expected):
    assert score('coverage',{'coverage':{'fraction':fraction}},parameters={'target':.5}).total==expected


def test_team_arrival_all_peers_and_no_service_gate():
    contract={'mission':{'goal_x':345,'goal_y':300,'team_radius_m':50}}
    context={'nodes':[[345,300],[395,300],[345,350]],'node_available':[True]*3}
    assert score('investigation',context,contract=contract).total==1
    context['nodes'][-1]=[345,350.01]
    assert score('investigation',context,contract=contract).total==-.001
    context['node_available'][-1]=False
    assert score('investigation',context,contract=contract).total==1
    context['node_available']=[False]*3
    assert score('investigation',context,contract=contract).total==-.001

@pytest.mark.parametrize('mission',['recovery','jamming'])
@pytest.mark.parametrize('active,ticks,expected',[(False,0,0),(True,1,0),(True,2,1)])
def test_zero_reward_waiting_and_event_boundary(mission,active,ticks,expected):
    context={'deployment':{'active':active,'eligible_ticks':ticks},'mission':{
        'survivor_demand_mbps_sum':10,'survivor_delivered_mbps_sum':9}}
    window={'scored_ticks':2,'demand_mbps_sum':10,'delivered_mbps_sum':9}
    assert score(mission,context,window).total==expected

@pytest.mark.parametrize('mission',['recovery','jamming'])
def test_no_demand_no_free_success(mission):
    context={'deployment':{'active':True,'eligible_ticks':2},'mission':{
        'survivor_demand_mbps_sum':0,'survivor_delivered_mbps_sum':0}}
    assert score(mission,context,{'scored_ticks':2,'demand_mbps_sum':0,'delivered_mbps_sum':0}).total==-.001


def test_reward_identity_independent_of_jammer_onset_but_not_goal():
    contract={**CONTRACT,'deployment_gate':{'version':1,'source':'control_start_s'},'control_start_s':160}
    a=reward_schema(['level0_jamming_v1'],[1],contract=contract)
    contract['control_start_s']=180
    assert a==reward_schema(['level0_jamming_v1'],[1],contract=contract)
    contract['coverage']={}
    a=reward_schema(['level0_coverage_v1'],[1],contract=contract,parameters={'level0_coverage_v1':{'target':.5}})
    b=reward_schema(['level0_coverage_v1'],[1],contract=contract,parameters={'level0_coverage_v1':{'target':.6}})
    assert a['sha256']!=b['sha256']


def test_protocol_extension_validates_boundary_samples():
    init={**CONTRACT,'deployment_gate':{'version':1,'source':'control_start_s'},'control_start_s':.5}
    protocol=CentralizedProtocol(init)
    facts=copy.deepcopy(FACTS);facts['deployment']={'active':True,'eligible_ticks':0}
    msg={'facts':facts,'scored_ticks':5,'reward':1,'time_s':.5}
    protocol.validate_facts(msg)
    facts['deployment']['eligible_ticks']=5
    with pytest.raises(ProtocolError,match='sample times'):protocol.validate_facts(msg)
    facts['deployment']={'active':False,'eligible_ticks':0}
    with pytest.raises(ProtocolError,match='active disagrees'):protocol.validate_facts(msg)


def test_unadvertised_extension_rejected():
    protocol=CentralizedProtocol(CONTRACT)
    facts=copy.deepcopy(FACTS);facts['deployment']={'active':True,'eligible_ticks':5}
    with pytest.raises(ProtocolError,match='unadvertised'):
        protocol.validate_facts({'facts':facts,'scored_ticks':5,'reward':1})


