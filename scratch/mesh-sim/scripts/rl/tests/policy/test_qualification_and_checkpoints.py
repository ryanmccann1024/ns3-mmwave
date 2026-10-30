"""Behavior checks preserved from the experiment pilots; no native simulation."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import pytest

from scripts.rl.policy.schedules import CoverageSchedule
from scripts.rl.policy.mission_metrics import connected

ROOT=Path(__file__).resolve().parents[4]
INPUT=ROOT/'inputs/custom/10-30'


@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    def forbidden(*a,**k):raise AssertionError('No child process or simulation is allowed in these checks')
    monkeypatch.setattr(subprocess,'Popen',forbidden)


@pytest.mark.parametrize('kind,state',[('sample-then-deterministic','deterministic'),('sample-then-hold','hold')])
def test_stopping_qualification_and_fallback(kind,state):
    s=CoverageSchedule(kind,.6)
    for t in range(1,30):s.observe(t,.65,.95,.85)
    assert s.state=='sampled'
    s.observe(30,.65,.95,.85);assert s.state==state
    for t in range(31,35):s.observe(t,.57,.95,.85)
    assert s.state==state
    s.observe(35,.57,.95,.85);assert s.state=='sampled'
    for t in range(36,66):s.observe(t,.65,.95,.85)
    assert s.state==state
    s.observe(66,.65,.95,.19);assert s.state=='sampled'
    assert s.events[-1]['reason']=='severe service loss'


def test_qualification_uses_both_delivery_and_single_worst_peer():
    s=CoverageSchedule('sample-then-hold',.6)
    for t in range(1,51):s.observe(t,.8,1.,.79)
    assert s.state=='sampled' and s.qualified==0
    for t in range(51,101):s.observe(t,.8,.89,1.)
    assert s.state=='sampled'


def test_native_unity_is_graph_connectivity_not_los_or_all_isolated():
    f=dict(nodes=[[0,0,0]]*3,node_available=[True]*3,links=[[10,0,0],[-20,0,1],[10,0,0]])
    assert connected(f)  # NLOS is not itself disconnection; a multihop path works.
    f['node_available'][1]=False
    assert not connected(f)  # Failed relay cannot connect the other two.
    f['node_available']=[True,False,False];assert connected(f)


def test_post_update_checkpoint_never_saves_parent_or_preoptimization(tmp_path):
    from scripts.rl.agents.post_update import PostUpdateCheckpoints as OptimizedCheckpoints
    saved=[]
    def record(path,steps,keep):saved.append((steps,path.name))
    callback=OptimizedCheckpoints(SimpleNamespace(out_dir=tmp_path,record_checkpoint=record), every=6000, keep=10, decisions_per_episode=600)
    callback.model=SimpleNamespace(num_timesteps=15000,_n_updates=250,
        save=lambda path:Path(path).write_bytes(b'checkpoint stub; not a model'))
    callback._on_training_start();callback._on_rollout_start();assert not saved
    callback.model.num_timesteps=18000;callback._on_rollout_start();assert not saved
    callback.model._n_updates=300;callback._on_rollout_start();callback._on_rollout_start()
    assert saved==[(18000,'checkpoint_18000_steps.zip')]
    callback.model.num_timesteps=30000;callback.model._n_updates=500
    callback._on_training_end()
    assert saved[-1]==(30000,'checkpoint_30000_steps.zip')
    events=json.loads((tmp_path/'post_update_checkpoints.json').read_text())['events']
    assert [e['steps'] for e in events]==[18000,30000]


@pytest.mark.parametrize('resumed',[False,True])
def test_training_hook_wiring_suppresses_preupdate_checkpoint_without_optimization(tmp_path,monkeypatch,resumed):
    from scripts.rl.policy import training as t
    from scripts.rl.agents.config import Cadence
    calls={};token=object()
    class FakeArtifacts:
        def __init__(self,*a):self.out_dir=tmp_path
        def record_contract(self,*a):pass
        def complete(self,trainer):return 'inert-result'
        def fail(self,*a):raise AssertionError('unexpected training orchestration error')
    class FakeEnv:
        def __init__(self,*a,**k):pass
        def reset(self):pass
        def close(self):calls['closed']=True
    class FakeTrainer:
        def __init__(self,*a):self.model=SimpleNamespace(set_logger=lambda log:None)
        @classmethod
        def resume(cls,*a):calls['resumed']=True;return cls()
        def train(self,callback,continuing):
            calls['callback']=callback;calls['continuing']=continuing
    def callbacks(out,every,*a,**k):calls['ordinary_checkpoint_cadence']=every;return [],None
    monkeypatch.setattr(t,'TrainingArtifacts',FakeArtifacts)
    monkeypatch.setattr(t,'MeshRlEnv',FakeEnv)
    monkeypatch.setattr(t,'MaskablePpoTrainer',FakeTrainer)
    monkeypatch.setattr(t,'read_episode_output',lambda p:dict(compact_training=True,validation_after_update=False))
    monkeypatch.setattr(t,'read_scenario_identity',lambda p:{})
    monkeypatch.setattr(t,'check_compatibility',lambda *a,**k:None)
    monkeypatch.setattr(t,'configure',lambda *a:None)
    monkeypatch.setattr(t,'build_callbacks',callbacks)
    cfg=SimpleNamespace(seed=101,verbose=0,tensorboard_log=None)
    parent=SimpleNamespace(num_timesteps=15000,manifest={}) if resumed else None
    result=t.train_mppo(cfg,'not-executed','not-read',str(tmp_path),'sub-6','cli',object(),
        Cadence(checkpoint_every=3000,keep_checkpoints=5),resume=parent,
        post_update_callback_factory=lambda a:token)
    assert result=='inert-result' and calls['ordinary_checkpoint_cadence']==0
    assert calls['callback']==[token] and calls['continuing']==resumed and calls['closed']
