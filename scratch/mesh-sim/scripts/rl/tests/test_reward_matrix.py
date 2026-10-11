"""Coverage rewards, distinct validation seeds, and aligned evaluation reward curves."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.rl import experiment, train
from scripts.rl.agents.callbacks import ValidationSeeds
from scripts.rl.env.mesh_env import MeshRlEnv
from scripts.rl.env.selection import resolve_selection
from scripts.rl.policy.bundle import seed_roles
from scripts.rl.policy.reward_matrix import aggregate_rows, write_reward_matrix
from scripts.rl.env.telemetry import replay_file


def test_validation_seeds_restart(multi_run_config, sim_binary, tmp_path):
    raw = MeshRlEnv(sim_binary, multi_run_config, seed=1, output_dir=tmp_path/"eval")
    raw.reset()
    env = ValidationSeeds(raw, (21,22,23))
    try:
        for expected in (21,22,23,21):
            env.reset()
            assert raw.seed_value == expected
        env.begin_evaluation()
        env.reset()
        assert raw.seed_value == 21
    finally:
        env.close()


def test_multiple_validation_seeds_are_reserved():
    manifest = {"seed": 1, "evaluation": {"seed": 21, "seeds": [21,22,23]}}
    assert seed_roles(manifest, "best", [22,30])["overlap"] == [22]


def test_matrix_builds_validation_seed_set(tmp_path):
    matrix = {"seeds": {"model_selection": [21,22,23]}, "training": {}}
    row = {"run_config": "run.ini", "band": None, "observation_preset": "local_links_v1",
           "reward_components": ["delivery_ratio"], "reward_weights": [1]}
    args = experiment._train_args(matrix,row,"sim",str(tmp_path),1)
    assert args[args.index("--eval-episodes")+1] == "3"
    assert args[args.index("--eval-seeds")+1] == "21,22,23"
    with pytest.raises(ValueError, match="disjoint"):
        experiment._seeds({"training":[1],"model_selection":[21,22],"held_out":[22]},
                          {"eval_every_steps":10})


def test_reward_matrix_excludes_reset_and_incomplete_rows(tmp_path):
    results=[]
    for i, values in enumerate(((1,3),(3,5))):
        d=tmp_path/f"episode-{i}"; d.mkdir()
        records=[{"type":"header"},{"type":"step","decision":0,"reward":None}]
        records += [{"type":"step","decision":j+1,"time_s":j+1,
                     "reward":{"total":v,"components":{"delivery_ratio":v}}}
                    for j,v in enumerate(values)]
        (d/"steps.jsonl").write_text("\n".join(json.dumps(s) for s in records))
        results.append(SimpleNamespace(status="completed",seed=i+1,decisions=2,episode_dir=str(d)))
    payload=write_reward_matrix(results,tmp_path/"matrix")
    assert payload["reward"] == [[1,3],[3,5]]
    assert payload["reward_curve"]["mean"] == [2,4]
    assert payload["cumulative_reward_curve"]["mean"] == [2,6]
    assert aggregate_rows([[1,3],[3]])["mean"] == [2,3]
    results[1].decisions=3
    payload=write_reward_matrix(results,tmp_path/"matrix")
    assert len(payload["reward"]) == 1
    assert payload["excluded"][0]["seed"] == 2


def test_coverage_reward_replays(sim_binary, multi_run_config, tmp_path):
    ini=Path(multi_run_config)
    ini.write_text(ini.read_text()+"coverage_enabled = true\nunsafe_separation_m = 1.0\n")
    selection=resolve_selection(str(ini),observation_preset="local_links_v1",
         reward_components="coverage_fraction",reward_weights="0.5",telemetry="steps")
    env=MeshRlEnv(sim_binary,str(ini),seed=1,output_dir=tmp_path/"reward",selection=selection)
    try:
        env.reset()
        _,reward,_,_,info=env.step([4,4,4])
        assert reward == pytest.approx(.375)
        assert info["reward"]["components"]["coverage_fraction"] == .75
    finally:
        env.close()
    replay=replay_file(tmp_path/"reward/episode-0000/steps.jsonl")
    assert replay.reward_mismatches == replay.obs_mismatches == 0


def test_checkpoint_uses_each_validation_seed(sim_binary, multi_run_config, tmp_path, monkeypatch):
    argv=["train","--sim-binary",sim_binary,"--run-config",multi_run_config,
          "--output-dir",str(tmp_path/"train"),"--verbose","0","m-ppo",
          "--seed","1","--total-timesteps","16","--n-steps","16",
          "--eval-every-steps","8","--eval-episodes","3","--eval-seeds","21-23"]
    monkeypatch.setattr(sys,"argv",argv)
    assert train.main() == 0
    for step in (8,16):
        payload=json.loads((tmp_path/f"train/eval/checkpoint-{step}/reward_matrix.json").read_text())
        assert [e["seed"] for e in payload["episodes"]] == [21,22,23]
        assert len(payload["reward"]) == 3


def test_missing_coverage_facts_rejected(sim_binary, multi_run_config, tmp_path):
    from scripts.rl.env.protocol import ProtocolError
    ini=Path(multi_run_config)
    ini.write_text(ini.read_text()+"coverage_enabled=true\n")
    env=MeshRlEnv(sim_binary,str(ini),seed=1,output_dir=tmp_path/"missing")
    try:
        env.reset()
        message={"facts":dict(env._protocol.facts),"ticks_in_step":env._protocol.facts["window"]["ticks"],
                 "reward":env._protocol.facts["window"]["legacy_reward_sum"]}
        del message["facts"]["coverage"]
        with pytest.raises(ProtocolError,match="coverage missing"):
            env._protocol._validated_facts(message)
        message["facts"]["coverage"]={"fraction":0.5}
        message["facts"]["safety"]={**message["facts"]["safety"],"threshold_m":2.0}
        with pytest.raises(ProtocolError,match="threshold does not match"):
            env._protocol._validated_facts(message)
    finally:
        env.close()
