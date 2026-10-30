"""Behavior checks preserved from the experiment pilots; no native simulation."""
from pathlib import Path
import subprocess
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[4]
INPUT=ROOT/'inputs/custom/10-30/phase-9'


@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    def forbidden(*a,**k):raise AssertionError('No simulator, training process or inference allowed')
    monkeypatch.setattr(subprocess,'Popen',forbidden)


@pytest.mark.parametrize('start',[0,25,50])
def test_milestones_are_post_update_and_all_retained(tmp_path,start):
    from scripts.rl.agents.post_update import PostUpdateCheckpoints as OptimizedCheckpoints
    saved=[]
    c=OptimizedCheckpoints(SimpleNamespace(out_dir=tmp_path,record_checkpoint=lambda path,steps,keep:saved.append((steps,keep))),every=6000,keep=10,decisions_per_episode=600)
    c.model=SimpleNamespace(num_timesteps=start*600,_n_updates=start*10,
        save=lambda p:Path(p).write_bytes(b'inert checkpoint stub'))
    c._on_training_start();c._on_rollout_start();assert not saved
    for steps in range((start//10+1)*6000,60001,6000):
        c.model.num_timesteps=steps;c._on_rollout_start()
        assert steps not in [n for n,k in saved]
        c.model._n_updates+=10;c._on_rollout_start();c._on_rollout_start()
    c._on_training_end()
    assert [n for n,k in saved]==list(range((start//10+1)*6000,60001,6000))
    assert all(k==10 for n,k in saved)


