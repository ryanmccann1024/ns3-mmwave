"""Behavior checks preserved from the experiment pilots; no native simulation."""
import subprocess
from pathlib import Path
import pytest
from scripts.rl.env.rewards import RewardComposer
from scripts.rl.policy.schedules import SamplingSchedule as EscapeSchedule
from scripts.rl.policy.episode_review import contact_audit
from scripts.rl.policy.reward_audit import reconstruct_position_replay as replay

ROOT=Path(__file__).resolve().parents[4];INPUT=ROOT/'inputs/custom/10-23-2'

@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:(_ for _ in ()).throw(AssertionError('process execution forbidden')))


def test_available_travel_excludes_failed_peers_and_prefix():
    c={'node_ids':['a','b','c'],'slot_node_ids':['a','b','c',None],'slot_speed_mps':[2,2,2,0],'tick_s':.5}
    f={'nodes':[[2,0],[0,0],[100,100]],'node_available':[True,True,False],
       'window':{'scored_ticks':2},'deployment':{'active':True,'eligible_ticks':2}}
    inputs={'previous_nodes':[[0,0],[0,0],[100,100]],'elapsed_ticks':2}
    q=RewardComposer(['available_peer_travel_fraction_v1'],[-.05]);context=q.context(f,c,inputs)
    assert q.compose(f['window'],0,c,context).total==pytest.approx(-.025)
    f['deployment']['eligible_ticks']=1
    assert q.compose(f['window'],0,c,q.context(f,c,inputs)).total==0
    f['node_available']=[False]*3
    assert q.compose(f['window'],0,c,q.context(f,c,inputs)).total==0


def test_weakest_service_ignores_failed_and_no_demand():
    c={};f={'node_available':[True,True,False,True],
        'mission':{'survivor_node_service':[[10,10],[10,0],[10,0],[0,0]]},
        'node_service':[[10,10],[10,0],[10,0],[0,0]],'deployment':{'active':True,'eligible_ticks':2},'window':{'scored_ticks':2}}
    for component in ('weakest_active_delivery_fraction_v1','weakest_survivor_delivery_fraction_v1'):
        q=RewardComposer([component],[1]);assert q.compose(f['window'],0,c,q.context(f,c)).total==0
        f['node_available'][1]=False
        assert q.compose(f['window'],0,c,q.context(f,c)).total==1
        f['node_available']=[False]*4
        v=q.compose(f['window'],0,c,q.context(f,c));assert v.total==0 and not v.valid[component]
        f['node_available']=[True,True,False,True]


def test_worst_proximity_and_roles_use_measured_positions():
    c={'mission':{'goal_x':400,'goal_y':200,'team_radius_m':50,'investigator_id':'drone'},
       'bounds':{'x_min':0,'x_max':400,'y_min':0,'y_max':400},'node_ids':['drone','ground','vehicle']}
    x={'nodes':[[100,200],[100,200],[100,200]],'node_available':[True]*3}
    def score(name):return RewardComposer([name],[1]).compose({'scored_ticks':2},0,c,x).total
    assert score('followers_investigator_then_target_proximity_v1')==1
    assert score('followers_target_proximity_v1')<1
    old=score('worst_peer_target_proximity_v1');x['nodes'][0]=[400,200]
    assert score('worst_peer_target_proximity_v1')==old
    assert score('followers_investigator_then_target_proximity_v1')==score('followers_target_proximity_v1')
    x['nodes'][0]=[100,200]
    assert score('followers_investigator_then_target_proximity_v1')==1 # measured fallback


def test_boundary_counts_contacts_not_proximity_or_hold():
    c={'slot_node_ids':['a','b'],'node_ids':['a','b']}
    q=RewardComposer(['boundary_contact_fraction_v1'],[-.01])
    f={'window':{'scored_ticks':2},'node_available':[True,True],'safety':{'boundary_contacted_slots':[0]}}
    assert q.compose(f['window'],0,c,q.context(f,c)).total==-.005
    f['safety']['boundary_contacted_slots']=[]
    assert q.compose(f['window'],0,c,q.context(f,c)).total==0
    f['safety']={}
    with pytest.raises(ValueError,match='rebuilt'):q.compose(f['window'],0,c,q.context(f,c))
    h={'contract':{'node_ids':['a'],'slot_node_ids':['a'],'bounds':{'x_min':0,'x_max':400,'y_min':0,'y_max':400}}}
    def row(i,x,y,seen):return dict(decision=i,facts={'nodes':[[x,y]],'node_available':[True],'window':{'scored_ticks':int(i>0)},'safety':{'boundary_contacted_slots':seen}})
    rows=[row(0,399,200,[]),row(1,400,200,[0]),row(2,400,200,[]),row(3,400,201,[])]
    assert contact_audit(h,rows)['contacts']==1
    rows[2]['facts']['safety']['boundary_contacted_slots']=[0]
    with pytest.raises(ValueError,match='disagrees'):contact_audit(h,rows)


def settings(kind):
    all_settings = {'initial_sample_decisions': 60, 'burst_decisions': 20, 'cooldown_decisions': 40, 'max_bursts': 3, 'rejected_window': 20, 'rejected_threshold': 10, 'movement_threshold_m': 1.0, 'progress_window': 60, 'progress_threshold': 0.01}
    from scripts.rl.policy.schedules import SAMPLING_REQUIRED
    return {k: all_settings[k] for k in SAMPLING_REQUIRED[kind]}


def test_initial_sampling_exactly_60_eligible_decisions():
    s=EscapeSchedule('initial-sampling',settings('initial-sampling'));flags=[]
    for i in range(100):
        flags.append(s.sampled());s.observe(.1,False,[False],[0.])
    assert flags==[True]*60+[False]*40


def test_stall_trigger_burst_cooldown_and_limit():
    s=EscapeSchedule('stall-burst',settings('stall-burst'));flags=[]
    for i in range(260):
        flags.append(s.sampled());s.observe(.1,False,[True],[0.])
    assert flags[:20]==[False]*20 and flags[20:40]==[True]*20
    assert flags[40:80]==[False]*40
    assert len(s.events)==3 and sum(flags)==60
    assert all('score_after' in e for e in s.events)
    good=EscapeSchedule('stall-burst',settings('stall-burst'))
    for i in range(100):
        assert not good.sampled();good.observe(1.,True,[False],[0.])
    assert not good.events


def test_reward_replay_uses_previous_positions_and_detects_tampering():
    c={'node_ids':['a'],'slot_node_ids':['a'],'slot_speed_mps':[2.],'tick_s':.5,'warmup_s':0,'reward_warmup':'exclude','coverage':{}}
    selection={'reward_components':['connected_outdoor_area_fraction_v1','available_peer_travel_fraction_v1'],'reward_weights':[1,-.05]}
    rows=[]
    for i in range(601):
        rows.append(dict(decision=i,time_s=i,ticks_in_step=2,legacy_reward=0,reward={'total':.75-.05},
           facts={'nodes':[[2*i,0]],'node_available':[True],'coverage':{'fraction':.75},'window':{'scored_ticks':2}}))
    h={'selection':selection,'contract':c}
    assert replay(h,rows,verify=True)['return_']==pytest.approx(420.)
    rows[-1]['reward']['total']=.75
    with pytest.raises(ValueError,match='replay'):replay(h,rows,verify=True)


def test_native_contact_protocol_remains_backward_compatible():
    from scripts.rl.env.protocol import CentralizedProtocol
    from scripts.rl.env.protocol import ProtocolError
    basic=dict(threshold_m=5,unsafe_ticks=0,min_pair_distance_m=20)
    for s in (basic,dict(basic,building_rejected_slots=[],peer_rejected_slots=[]),
              dict(basic,building_rejected_slots=[],peer_rejected_slots=[],boundary_contacted_slots=[0])):
        CentralizedProtocol._check_safety(s,2,3,3)
    with pytest.raises(ProtocolError):CentralizedProtocol._check_safety(dict(basic,building_rejected_slots=[],peer_rejected_slots=[],boundary_contacted_slots=[3]),2,3,3)


