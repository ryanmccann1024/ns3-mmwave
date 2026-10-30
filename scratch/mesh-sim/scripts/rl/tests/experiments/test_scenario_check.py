"""Pure October 23 checks: no simulator, fake peer, planner worker, or PPO launch."""

import copy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.baselines.planners.objective import GridSettings, ProbeSettings, coverage_grid
from scripts.rl.scenario_check.execution import validate_inputs, snapshot, require_binary
from scripts.rl.scenario_check.geometry import safe_segment, swept_distance
from scripts.rl.scenario_check.inputs import traffic, jammer, read_ini
from scripts.rl.scenario_check.reports import reduce_records, acceptance

ROOT = Path(__file__).resolve().parents[4]
INPUT = ROOT/'inputs/custom/10-23/scenario-check'


@pytest.fixture(autouse=True)
def forbid_process_creation(monkeypatch):
    def forbidden(*args,**kwargs):
        raise AssertionError('scenario checks must not run during these pure tests')
    monkeypatch.setattr(subprocess,'Popen',forbidden)


@pytest.mark.skipif(not INPUT.is_dir() or not (ROOT/'inputs/custom/10-23/scenario-check-02').is_dir(), reason='private scenario fixtures unavailable')
def test_workload_routes_and_normalized_sources():
    c = validate_inputs(INPUT)
    assert c['episodes_expected']==168 and not c['training_enabled']
    for case in c['cases']:
        folder = INPUT/case['name']
        nodes = json.loads((folder/'nodes.json').read_text())
        boxes = [b['bounds'] for b in json.loads((folder/'buildings.json').read_text())]
        reference = json.loads((folder/'reference.json').read_text())
        for seed in (201,202):
            ini = read_ini(folder/f'seed-{seed}/run.ini')
            assert ini['rl']['controlled_nodes']=='all'
            assert ini.getint('rl','max_controlled_nodes')==case['peers']
            assert ini.getint('baseline','coverage_grid_cells')==400
            assert ini.getfloat('baseline','coverage_sinr_db')==10
        flows = traffic(nodes,case['mission'])
        assert len({(p['src'],p['dst']) for p in flows})==len(flows)
        for node in nodes:
            assert node['role']=='peer' and node['node_type'] in ('pedestrian','vehicle','drone')
            assert sum(f['demand_mbps'] for f in flows if f['src']==node['id'])==pytest.approx(3)
            start = tuple(node['position'][k] for k in 'xyz')
            points = [start]+reference['routes'][node['id']]
            assert all(safe_segment(a,b,boxes,3) for a,b in zip(points,points[1:]))
        if case['mission']=='recovery':
            survivors = {n['id'] for n in nodes if 'failure_at_s' not in n}
            assert sum(p['demand_mbps'] for p in flows if p['src'] in survivors and p['dst'] in survivors)==2*case['peers']
            assert all(n['failure_at_s']==10 for n in nodes if n['node_type']=='drone')


@pytest.mark.skipif(not INPUT.is_dir() or not (ROOT/'inputs/custom/10-23/scenario-check-02').is_dir(), reason='private scenario fixtures unavailable')
def test_snapshot_rebases_and_fingerprint_rejects_edit(tmp_path):
    digests = snapshot(INPUT,tmp_path/'inputs')
    assert digests
    assert validate_inputs(tmp_path/'inputs')['episodes_expected']==168
    for p in (tmp_path/'inputs').rglob('*.ini'):
        ini = read_ini(p)
        for key in ('nodes_file','buildings_file','jammers_file'):
            value = ini['scenario'][key]
            assert not value or Path(value).is_relative_to(tmp_path/'inputs')
    p = tmp_path/'inputs'/next(iter(validate_inputs(INPUT)['input_hashes']))
    p.write_text(p.read_text()+'\n')
    with pytest.raises(ValueError,match='input changed'):
        validate_inputs(tmp_path/'inputs')


@pytest.mark.skipif(not INPUT.is_dir() or not (ROOT/'inputs/custom/10-23/scenario-check-02').is_dir(), reason='private scenario fixtures unavailable')
def test_jammer_silent_approach_and_paired_schedule():
    routes = []
    for seed in (201,202):
        spec,onset = jammer(seed)
        assert onset in (160,180,200)
        assert spec['waypoints'][1]['t']==onset-60
        assert spec['intervals']==[dict(start=onset,end=600.5)]
        assert spec['waypoints'][2]['x']==spec['waypoints'][3]['x']
        assert spec['waypoints'][2]['y']==spec['waypoints'][3]['y']
        assert spec['max_range_m']==140
        routes.append(spec)
        for c in validate_inputs(INPUT)['cases']:
            if c['mission']=='jamming':
                saved = json.loads((INPUT/c['name']/f'seed-{seed}/jammers.json').read_text())[0]
                assert saved == spec
    assert routes[0]['waypoints'][0]['x'] != routes[1]['waypoints'][0]['x']
    assert routes[0]['waypoints'][2]['x'] != routes[1]['waypoints'][2]['x']


def test_outdoor_probe_grid_matches_native_inclusive_centers():
    box = dict(x_min=5,x_max=15,y_min=5,y_max=15,z_min=0,z_max=10)
    request = SimpleNamespace(rectangle=dict(x_min=0,x_max=40,y_min=0,y_max=40),
        grid=GridSettings(16,16,1),probe=ProbeSettings(1.5,3,10),probe_exclusion_buildings=(box,))
    points,cell,weights = coverage_grid(request)
    assert cell==10 and len(points)==12 and sum(weights)==1200
    assert all(not (5<=x<=15 and 5<=y<=15) for x,y in points)
    request.probe = ProbeSettings(20,3,10)
    assert len(coverage_grid(request)[0])==16
    request.probe_exclusion_buildings = ()
    assert len(coverage_grid(request)[0])==16


def test_swept_crossing_is_not_endpoint_distance():
    assert swept_distance((0,0,0),(10,0,0),(10,0,0),(0,0,0))==0
    # Protocol node rows also contain velocity and slot data, not spatial axes.
    assert swept_distance((0,0,0,1,0,0,0),(10,0,0,1,0,0,0),
                          (10,0,0,-1,0,0,9),(0,0,0,-1,0,0,9))==0
    assert swept_distance((0,0,20),(10,0,20),(10,0,1.5),(0,0,1.5))==18.5


def test_no_binary_or_stale_binary_is_rejected_without_launch(tmp_path):
    with pytest.raises(ValueError,match='missing'):
        require_binary(tmp_path/'missing',ROOT)
    fake = tmp_path/'binary'
    fake.write_text('not a simulator')
    fake.chmod(0o700)
    import os
    os.utime(fake,(1,1))
    with pytest.raises(ValueError,match='older'):
        require_binary(fake,ROOT)


def _record(time,positions,delivery=1):
    return dict(decision=time,time_s=time,ticks_in_step=1,facts=dict(nodes=positions,
        node_available=[True,True],links=[[5,10,1]],coverage=dict(fraction=.5),
        window=dict(demand_mbps_sum=6,delivered_mbps_sum=6*delivery),
        mission=dict(survivor_demand_mbps_sum=6,survivor_delivered_mbps_sum=6*delivery),
        mission_state=dict(survivor_worst_service=delivery)))


def test_goal_requires_thirty_seconds_through_end_and_event_boundary_excluded():
    far = [[0,0,1.5],[20,0,1.5]]
    near = [[345,300,1.5],[355,300,1.5]]
    contract = dict(num_decisions=60,decision_interval_s=1,node_ids=['a','b'])
    rows = [_record(t,far if t<=30 else near) for t in range(61)]
    m,timeline = reduce_records(rows,contract,'investigation',10)
    assert m['team_sustained_through_end'] and m['team_completion_s']==60
    assert m['pre_event_delivery']==1
    assert m['travel_m_total']>800
    rows[-1] = _record(60,far)
    m,_ = reduce_records(rows,contract,'investigation',10)
    assert not m['team_sustained_through_end'] and not m['team_completed_ever']
    rows[10] = _record(10,far,0)
    m,_ = reduce_records(rows,contract,'recovery',10)
    assert m['pre_event_delivery']==1 and m['post_event_delivery']==1


def test_coverage_requires_both_seeds_and_reports_candidate_threshold():
    case = dict(mission='coverage')
    results = {(p,s):dict(final_minute_coverage=.2 if p=='hold' else .4,
                         final_minute_delivery=1) for p in ('hold','scripted') for s in (201,202)}
    report = acceptance(case,results)
    assert report['accepted'] and report['coverage_threshold']['proposed_target']==pytest.approx(.3)
    results[('scripted',202)]['final_minute_coverage']=.21
    report = acceptance(case,results)
    assert not report['accepted'] and report['coverage_threshold'] is None


def test_seeded_env_switches_configs_without_mixing_output_locations(monkeypatch,tmp_path):
    from scripts.rl.env import mesh_env, selection
    from scripts.rl.scenario_check.execution import SeededEnv
    created=[]
    class StubEnv:
        def __init__(self,binary,config,**kwargs):
            self.config,self.kwargs=config,kwargs
            created.append(self)
        def close(self):
            pass
        def reset(self,**kwargs):
            return self.config,kwargs
    monkeypatch.setattr(mesh_env,'MeshRlEnv',StubEnv)
    monkeypatch.setattr(selection,'resolve_selection',lambda *a,**k:None)
    env=SeededEnv('unused',{'201':'one.ini','202':'two.ini'},tmp_path,
        dict(seeds={'201':dict(gate_s=160),'202':dict(gate_s=180)}))
    try:
        assert env.reset(seed=201)[0]=='one.ini' and env.gate_s==160
        assert env.reset(seed=202)[0]=='two.ini' and env.gate_s==180
        assert all(e.kwargs['output_dir']==str(tmp_path) for e in created)
    finally:
        env.close()


CORRECTION = ROOT/'inputs/custom/10-23/scenario-check-02'


@pytest.mark.skipif(not INPUT.is_dir() or not (ROOT/'inputs/custom/10-23/scenario-check-02').is_dir(), reason='private scenario fixtures unavailable')
def test_correction_inventory_unchanged_conditions_and_routes():
    c=validate_inputs(CORRECTION)
    assert len(c['cases'])==17 and c['episodes_expected']==102
    assert c['placement_searches_expected']==0
    for case in c['cases']:
        assert case['placement_benchmarks']==[]
        folder=CORRECTION/case['name']
        old=INPUT/case['name']
        assert (folder/'nodes.json').read_bytes()==(old/'nodes.json').read_bytes()
        assert (folder/'buildings.json').read_bytes()==(old/'buildings.json').read_bytes()
        nodes=json.loads((folder/'nodes.json').read_text())
        boxes=[b['bounds'] for b in json.loads((folder/'buildings.json').read_text())]
        ref=json.loads((folder/'reference.json').read_text())
        for seed in (201,202):
            original=read_ini(old/f'seed-{seed}/run.ini')
            new=read_ini(folder/f'seed-{seed}/run.ini')
            for section in ('traffic','routing','channel','baseline','mission'):
                assert dict(new[section])==dict(original[section])
        for node in nodes:
            points=[tuple(node['position'][k] for k in 'xyz')]+ref['routes'][node['id']]
            assert all(safe_segment(a,b,boxes,3) for a,b in zip(points,points[1:]))
        if case['mission']=='recovery':
            for group in range(1,case['peers']//3+1):
                a,b=(ref['targets'][f'{kind}-{group}'] for kind in ('ground','vehicle'))
                assert np.linalg.norm(np.array(a)-b)==40
    archive=__import__('hashlib').sha256((ROOT/'outputs/custom/10-23/scenario-check/scenario_check_report.json').read_bytes()).hexdigest()
    assert json.loads((CORRECTION/'preparation.json').read_text())['source_report_sha256']==archive


def _investigation_contract():
    ini=read_ini(CORRECTION/'urban-investigation-3-peers/seed-201/run.ini')
    mission={key:ini.getfloat('mission',key) for key in ('goal_x','goal_y','arrival_radius_m',
        'coverage_radius_m','dwell_s','goal_coverage_target','recovery_delivery_target',
        'recovery_coverage_ratio','recovery_worst_target','team_radius_m','team_delivery_target')}
    mission.update(version=2,kind='investigation',investigator_id='drone-1',team_investigation=True,
                   progress_distance_scale_m=100,coverage_domain='outdoor_probe_cells')
    return dict(mission=mission,slot_node_ids=['ground-1','drone-1','vehicle-1'])


@pytest.mark.skipif(not INPUT.is_dir() or not (ROOT/'inputs/custom/10-23/scenario-check-02').is_dir(), reason='private scenario fixtures unavailable')
def test_investigation_zero_secondary_gates_are_valid_but_distances_stay_positive():
    from scripts.rl.env.state.mission import validate_mission_contract
    contract=_investigation_contract()
    validate_mission_contract(contract)
    contract['mission']['team_radius_m']=0
    with pytest.raises(ValueError):validate_mission_contract(contract)


@pytest.mark.skipif(not INPUT.is_dir() or not (ROOT/'inputs/custom/10-23/scenario-check-02').is_dir(), reason='private scenario fixtures unavailable')
@pytest.mark.parametrize('key',['goal_coverage_target','team_delivery_target'])
@pytest.mark.parametrize('value',[-.1,1.1,float('nan')])
def test_invalid_investigation_secondary_targets_rejected(key,value):
    from scripts.rl.env.state.mission import validate_mission_contract
    c=_investigation_contract();c['mission'][key]=value
    with pytest.raises(ValueError):validate_mission_contract(c)


@pytest.mark.skipif(not INPUT.is_dir() or not (ROOT/'inputs/custom/10-23/scenario-check-02').is_dir(), reason='private scenario fixtures unavailable')
def test_jammer_actual_command_and_final_active_interval_are_checked(tmp_path):
    from scripts.rl.scenario_check.validation import jammer_timing
    c=validate_inputs(CORRECTION)
    for case in c['cases']:
        if case['mission']!='jamming':continue
        for seed in (201,202):
            config=CORRECTION/case['name']/f'seed-{seed}/run.ini'
            command=[f'--run-config={config}']
            v=jammer_timing(config,case,seed,command)
            assert v['command_checked'] and v['end_s']==600.5
            assert v['onset_s']==(160 if seed==201 else 180)
            with pytest.raises(ValueError,match='override'):
                jammer_timing(config,case,seed,command+['--jammer-onset-s=200'])
    # The original bug is caught from the immutable original input as well.
    case=next(c for c in c['cases'] if c['name']=='urban-jamming-3-peers')
    with pytest.raises(ValueError,match='inherited'):
        jammer_timing(INPUT/case['name']/'seed-201/run.ini',case,201)
    import shutil
    clone=tmp_path/'clone'
    shutil.copytree(CORRECTION/case['name'],clone)
    ini=read_ini(clone/'seed-201/run.ini')
    spec=json.loads((clone/'seed-201/jammers.json').read_text())
    spec[0]['intervals'][0]['end']=600
    p=clone/'bad-jammer.json';p.write_text(json.dumps(spec))
    ini['scenario']['jammers_file']=str(p)
    from scripts.rl.scenario_check.inputs import write_ini
    write_ini(clone/'bad.ini',ini)
    with pytest.raises(ValueError,match='beyond final'):
        jammer_timing(clone/'bad.ini',case,201)


@pytest.mark.skipif(not INPUT.is_dir() or not (ROOT/'inputs/custom/10-23/scenario-check-02').is_dir(), reason='private scenario fixtures unavailable')
def test_disabled_investigation_secondary_gates_do_not_block_team_dwell():
    from scripts.rl.env.state.mission import MissionState
    from scripts.rl.env.state.mission import validate_mission_contract
    c=_investigation_contract();c['node_ids']=c['slot_node_ids']
    validate_mission_contract(c)
    facts=dict(nodes=[[345,300,1.5],[340,300,20],[350,300,1.5]],links=[[10,5,1]]*3,
        coverage=dict(fraction=0),node_available=[True]*3,
        mission=dict(goal_coverage_fraction=0,survivor_demand_mbps_sum=6,
            survivor_delivered_mbps_sum=0,survivor_node_service=[[4,0]]*3))
    state=MissionState();state.advance(facts,c,0)
    result=state.advance(facts,c,30)
    assert result['investigation_completed_at_s']==30
    assert result['survivor_delivery']==0
