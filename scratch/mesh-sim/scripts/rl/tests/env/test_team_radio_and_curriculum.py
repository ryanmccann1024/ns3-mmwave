"""Behavior checks preserved from the experiment pilots; no native simulation."""
import copy,json,math,subprocess
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from scripts.rl.env.rewards.radio import global_bridge_support
from scripts.rl.env.rewards.radio import decomposition
from scripts.rl.env.state.measurements import link_support
from scripts.rl.env.observations import get_preset
from scripts.rl.env.observations import observation_schema
from scripts.rl.env.rewards import RewardComposer
from scripts.rl.env.selection import resolve_selection
from scripts.rl.env.state.extensions import make_extensions
from scripts.rl.policy.mission_metrics import read_episode
from scripts.rl.policy.reward_audit import reconstruct_team_radio as reconstruct
from scripts.rl.env.curriculum import CurriculumEnv

ROOT=Path(__file__).resolve().parents[4];INPUT=ROOT/'inputs/custom/10-23-6'


@pytest.fixture(autouse=True)
def no_process(monkeypatch):
    def deny(*a,**k):raise AssertionError('No simulator, fake subprocess, build or optimizer allowed')
    monkeypatch.setattr(subprocess,'Popen',deny)


@pytest.fixture(scope='module')
def plan():
    path=INPUT/'phase-seven.json'
    if not path.exists(): pytest.skip('private saved-data fixture unavailable')
    return json.loads(path.read_text())


def saved(name):
    path=ROOT/'outputs/custom/10-23-5/baselines'/name/'eval_manifest.json'
    if not path.is_file(): pytest.skip('private recorded trajectory unavailable')
    manifest=json.loads(path.read_text())
    return read_episode(manifest['policies']['scripted']['episodes'][0]['episode_dir'])


def test_global_bridge_finds_partition_hidden_by_recovery_traffic():
    c={'node_ids':['ground-1','vehicle-1','ground-2','vehicle-2'],'mission':{'kind':'recovery'}}
    f={'node_available':[True]*4,'links':[[15,0,1],[-20,0,0],[-20,0,0],[-20,0,0],[-20,0,0],[15,0,1]]}
    assert link_support(f,c,[0,1,2,3])>.99
    assert global_bridge_support(f,c)<.04
    f['links'][3][0]=10 # vehicle1 -> ground2 provides a radio bridge
    assert global_bridge_support(f,c)>.98
    f['node_available'][1]=False
    assert global_bridge_support(f,c)<.04 # failed relay cannot be used


def test_global_bridge_small_team_redundancy_and_threshold():
    c={'node_ids':['a','b','c'],'mission':{'kind':'coverage'}}
    f={'node_available':[True]*3,'links':[[-6.7,0,1],[-20,0,0],[10,0,1]]}
    assert global_bridge_support(f,c)==pytest.approx(.5)
    assert global_bridge_support(f,c)==pytest.approx(link_support(f,c,[0,1,2]))
    f['node_available']=[True,False,False];assert global_bridge_support(f,c)==0


@pytest.mark.parametrize('name',['urban-recovery-6-peers','rural-jamming-3-peers','urban-investigation-9-peers','rural-coverage-9-peers'])
def test_full_saved_trajectory_reward_observation_and_decomposition(plan,name):
    c=next(c for c in plan['cases'] if c['name']==name);a=c['variants'][0];h,rows=saved(name)
    s=resolve_selection(str(INPUT/a['configs']['101']));preset=get_preset(s.observation_preset,s.observation_parameters);q=RewardComposer(s.reward_components,s.reward_weights,s.reward_parameters);extension=make_extensions(preset,q)[0]
    for r in rows:
        f=copy.deepcopy(r['facts']);extension.advance(f,h['contract'],r['time_s'],r['action_sent'])
        assert preset.space(h['contract']).contains(preset.build(f,h['contract']))
        if r['decision'] and c['mission']!='investigation':
            t,w=decomposition(f,h['contract'],q.parameters[a['components'][0]])
            if c['mission'] in ('recovery','jamming'):assert 'I' not in w and w['radio_deficit']==-.05
            else:assert 'area' not in w and t['useful_area']<=c['coverage_target']
            score=q.compose(f['window'],0,h['contract'],q.context(f,h['contract']))
            if score.valid[a['components'][0]]:assert score.total==pytest.approx(sum(t[k]*v for k,v in w.items()))
    audited=reconstruct(h,rows,s.describe());assert math.isfinite(audited['return_'])
    assert 0<=audited['physical_team_metrics']['final_minute_global_bridge_support']<=1


@pytest.mark.parametrize('peers',[3,6,9])
def test_observation_probe_substitutes_exactly_one_feature(peers):
    h,rows=saved(f'urban-investigation-{peers}-peers');f=copy.deepcopy(rows[100]['facts'])
    from scripts.rl.env.state.coordination import CoordinationState
    CoordinationState({'mission_code':1}).advance(f,h['contract'],100.)
    old=get_preset('mission_coordination_v1');new=get_preset('mission_bridge_v1');a=old.build(f,h['contract']);b=new.build(f,h['contract'])
    oldnames=old.feature_names(h['contract']);newnames=new.feature_names(h['contract']);index=oldnames.index('team.path_support')
    assert len(a)==len(b) and sum(x!=y for x,y in zip(oldnames,newnames))==1
    assert newnames[index]=='team.global_bridge_support' and b[index]==pytest.approx(global_bridge_support(f,h['contract']))
    assert np.array_equal(np.delete(a,index),np.delete(b,index))
    assert observation_schema('mission_coordination_v1',h['contract'])['sha256']!=observation_schema('mission_bridge_v1',h['contract'])['sha256']


def test_curriculum_counts_completed_episodes_not_probe_resets(tmp_path,monkeypatch):
    from scripts.rl.env.mesh_env import MeshRlEnv
    from scripts.rl.env import curriculum as module
    env=object.__new__(CurriculumEnv);env.schedule={s:tmp_path/s for s in ('near','intermediate','original')}
    env.completed_episodes=0;env.reset_records=[];env._session=SimpleNamespace(_episode_dir=tmp_path);env._protocol=SimpleNamespace(facts={'nodes':[[0,0,1.5]]});env._output_dir=tmp_path
    monkeypatch.setattr(MeshRlEnv,'reset',lambda *a,**k:('observation',{}));monkeypatch.setattr(MeshRlEnv,'step',lambda *a,**k:('observation',0,True,False,{}))
    monkeypatch.setattr(module,'read_scenario_identity',lambda p:{'config':p});monkeypatch.setattr(env,'_write_schedule',lambda:None)
    env.reset();env.reset() # initial space probe and learner reset both stay near
    assert env.completed_episodes==0
    for _ in range(25):env.step([4]);env.reset()
    assert [r['stage'] for r in env.reset_records if r['completed']]==['near']*5+['intermediate']*5+['original']*15
    assert env.stage()=='original'


