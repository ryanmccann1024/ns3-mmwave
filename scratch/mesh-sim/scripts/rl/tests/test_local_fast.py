"""Reduced output cadence, reward ablations, and scenario difficulty gates."""

import copy
import json
from pathlib import Path
import sys

import pytest

from scripts.rl import campaign, experiment, preflight_campaign
from scripts.rl.env.config import read_manifest_every_decisions
from scripts.rl.env.mesh_env import MeshRlEnv
from scripts.sim_support import find_mesh_root


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "true"])
def test_manifest_cadence_rejects_invalid_values(multi_run_config, value):
    ini = Path(multi_run_config)
    ini.write_text(ini.read_text()+f"manifest_every_decisions = {value}\n")
    with pytest.raises(ValueError, match="positive integer"):
        read_manifest_every_decisions(str(ini))


def test_manifest_cadence_keeps_final_totals(sim_binary, multi_run_config, tmp_path):
    ini = Path(multi_run_config)
    ini.write_text(ini.read_text()+"manifest_every_decisions = 50\n")
    env = MeshRlEnv(sim_binary, str(ini), output_dir=str(tmp_path/"episode"))
    try:
        env.reset()
        path = tmp_path/"episode/episode-0000/rl_episode.json"
        _, first, _, _, _ = env.step([4,4,4])
        assert json.loads(path.read_text())["steps"] == 0
        _, second, _, _, _ = env.step([4,4,4])
        saved = json.loads(path.read_text())
        assert saved["status"] == "completed" and saved["steps"] == 2
        assert saved["cumulative_reward"] == pytest.approx(first+second)
    finally:
        env.close()


def test_manifest_cadence_flushes_interrupted_totals(sim_binary, multi_run_config, tmp_path):
    ini = Path(multi_run_config)
    ini.write_text(ini.read_text()+"manifest_every_decisions = 50\n")
    env = MeshRlEnv(sim_binary, str(ini), output_dir=str(tmp_path/"episode"))
    env.reset()
    env.step([4,4,4])
    env.close()
    saved = json.loads((tmp_path/"episode/episode-0000/rl_episode.json").read_text())
    assert saved["status"] == "interrupted" and saved["steps"] == 1


def _episodes(delivery, coverage=1):
    return [{"metrics": {"delivery_ratio": delivery, "coverage_fraction_mean": coverage}}]


def test_difficulty_gate_requires_healthy_hold_and_degraded_challenges():
    preflight_campaign.check_difficulty("small-hold", _episodes(1), .8)
    preflight_campaign.check_difficulty("large-jammer", _episodes(.4), .8)
    with pytest.raises(RuntimeError, match="not saturated"):
        preflight_campaign.check_difficulty("small-hold", _episodes(.99), .8)
    with pytest.raises(RuntimeError, match="exceeds"):
        preflight_campaign.check_difficulty("large-jammer", _episodes(1), .8)
    # Existing campaigns without a challenge criterion retain their behavior.
    preflight_campaign.check_difficulty("large-jammer", _episodes(1), None)


def test_preflight_signature_includes_difficulty_criteria(tmp_path):
    (tmp_path/"campaign.json").write_text(json.dumps({"scenarios":[], "preflight": {"seeds":[201,202],"challenge_delivery_max":.8}}))
    first = preflight_campaign.signature(tmp_path, Path(sys.executable))
    (tmp_path/"campaign.json").write_text(json.dumps({"scenarios":[], "preflight": {"seeds":[201,202],"challenge_delivery_max":.5}}))
    assert first != preflight_campaign.signature(tmp_path, Path(sys.executable))


def test_quick_campaign_has_one_seed_three_rewards_and_reduced_budget(tmp_path):
    path = find_mesh_root()/"inputs/custom/10-09/local-fast/campaign.json"
    if not path.exists():
        pytest.skip("local experiment inputs are not present")
    config = json.loads(path.read_text())
    assert config["execution"]["stages"] == ["preflight","main"]
    config.update(inputs=str(path.parent))
    config["execution"].update(sim_binary=sys.executable,output_root=str(tmp_path/"plans"))
    plans, jobs = campaign.prepare_phase(config,"main")
    assert len(plans) == 8 and len(jobs) == 24
    assert "small-hold" in jobs[0]["root"]
    for root in plans:
        plan = experiment.load_plan(root)
        assert plan["seeds"] == {"training":[101],"model_selection":[201,202],"held_out":[301,302,303]}
        assert len(plan["rows"]) == 3
        assert sum("coverage_fraction" in r["reward_components"] for r in plan["rows"]) == 1
        for task in campaign.build_tasks(plan):
            args = task["train"]["args"]
            assert args[args.index("--total-timesteps")+1] == "10000"
            assert args[args.index("--checkpoint-every-steps")+1] == "0"
            assert len(task["evaluate"]["args"][task["evaluate"]["args"].index("--seeds")+1].split(',')) == 3


def test_reward_summary_uses_common_metrics_and_excludes_failed_episodes(tmp_path, monkeypatch):
    target = tmp_path/"eval";target.mkdir()
    good = {"status":"completed", "metrics":{"delivery_ratio":.7,"coverage_fraction_mean":.5}}
    bad = {"status":"failed", "metrics":{"delivery_ratio":1}}
    (target/"eval_manifest.json").write_text(json.dumps({"policies":{"model":{"episodes":[good,bad]}}}))
    monkeypatch.setattr(experiment,"load_plan",lambda _: {"evaluations":[{"label":"reward-a","training_seed":101,"eval_dir":str(target)}]})
    campaign.write_reward_summary([tmp_path/"scene"], tmp_path)
    import csv
    rows = list(csv.DictReader((tmp_path/"reward_comparison.csv").open()))
    assert len(rows) == 1 and rows[0]["delivery_ratio"] == "0.7"
    assert rows[0]["completed_episodes"] == "1" and "return" not in rows[0]


def test_quick_training_without_telemetry_still_writes_full_evaluation(tmp_path, sim_binary,
                                                                     multi_run_config, monkeypatch):
    pytest.importorskip("sb3_contrib")
    ini = Path(multi_run_config)
    ini.write_text(ini.read_text()+"manifest_every_decisions = 50\ntelemetry = none\ncoverage_enabled = true\n")
    path = find_mesh_root()/"inputs/custom/10-09/local-fast/matrices/small-hold.json"
    if not path.exists():
        pytest.skip("local experiment inputs are not present")
    matrix = copy.deepcopy(json.loads(path.read_text()))
    matrix["run_config"] = str(ini)
    matrix["training"].update(total_timesteps=16,n_steps=8,eval_every_steps=8)
    matrix["evaluation"]["policies"] = ["model","hold","random_valid"]
    (tmp_path/"matrix.json").write_text(json.dumps(matrix))
    config = {"inputs":str(tmp_path),"main_matrices":["matrix.json"],"execution":{
        "sim_binary":sim_binary,"output_root":str(tmp_path/"output"),"max_workers":2,
        "threads_per_worker":1,"stages":["main"]}}
    monkeypatch.setattr(campaign,"run_preflight",lambda *args:0)
    result = campaign.run_campaign(config)
    root = tmp_path/"output"
    logs = '\n'.join(p.read_text() for p in root.rglob('*.log'))
    assert result == 0, logs
    assert len(list(root.rglob('train_manifest.json'))) == 3
    assert len(list(root.rglob('eval_manifest.json'))) == 3
    assert not list(root.rglob('checkpoint_*_steps.zip'))
    for p in root.glob('**/train/*/train-seed-*/episode-*/steps.jsonl'):
        pytest.fail(f"training telemetry should be disabled: {p}")
    for p in root.glob('**/eval/*/train-seed-*/model/reward_matrix.json'):
        data = json.loads(p.read_text());assert len(data['reward']) == 3 and len(data['reward'][0]) == 2
    assert (root/'reward_comparison.csv').is_file()
