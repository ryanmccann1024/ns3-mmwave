"""End-to-end train, evaluate, compare, and matrix runs driven by fake_sim.py."""

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from scripts.rl import compare as compare_cli
from scripts.rl import evaluate as evaluate_cli
from scripts.rl import experiment
from scripts.rl.policy.compare import ACROSS_RUNS_KIND, PAIRED_KIND, PRIMARY_METRIC

requires_sb3 = pytest.mark.skipif(importlib.util.find_spec("sb3_contrib") is None,
                                  reason="sb3_contrib not installed")


def _train(sim_binary, run_config, out_dir, monkeypatch, *extra: str) -> int:
    from scripts.rl import train

    monkeypatch.setattr(sys, "argv", [
        "train", "--sim-binary", sim_binary, "--run-config", run_config,
        "--output-dir", str(out_dir), "--verbose", "0",
        "m-ppo", "--total-timesteps", "16", "--n-steps", "16", "--seed", "1",
        *extra])
    return train.main()


def _primary(block: dict, baseline: str) -> dict:
    entry, = [c for c in block["comparisons"]
              if c["baseline"] == baseline and c["metric"] == PRIMARY_METRIC]
    return entry


def _csv_rows(path: Path) -> list:
    with path.open(newline="") as handle:
        return list(csv.reader(handle))[1:]


@requires_sb3
def test_failed_seed_survives_evaluation_and_narrows_the_comparison(
        sim_binary, multi_run_config, tmp_path, monkeypatch):
    run_dir = tmp_path / "train"
    assert _train(sim_binary, multi_run_config, run_dir, monkeypatch) == 0

    eval_dir = tmp_path / "eval"
    monkeypatch.setenv("FAKE_SIM_FAIL_SEEDS", "12")
    assert evaluate_cli.main([
        "--sim-binary", sim_binary, "--run-dir", str(run_dir),
        "--output-dir", str(eval_dir), "--seeds", "11-13",
        "--policies", "model,hold,random_valid", "--label", "pipeline"]) == 1

    manifest = json.loads((eval_dir / "eval_manifest.json").read_text())
    assert manifest["status"] == "partial"
    assert manifest["episodes_expected"] == 9 and manifest["episodes_completed"] == 6

    out_dir = tmp_path / "comparison"
    assert compare_cli.main(["--eval-dirs", str(eval_dir),
                             "--output-dir", str(out_dir)]) == 1

    comparison = json.loads((out_dir / "comparison.json").read_text())
    assert comparison["status"] == "incomplete"
    block, = comparison["evaluations"]
    for baseline in ("hold", "random_valid"):
        entry = _primary(block, baseline)
        assert (entry["n_expected"], entry["n_used"]) == (3, 2)
        assert [pair["seed"] for pair in entry["pairs"]] == [11, 13]
        assert entry["excluded"] == [
            {"seed": 12, "reasons": ["model:failed", f"{baseline}:failed"]}]
        assert entry["interval"]["kind"] == PAIRED_KIND

    assert len(_csv_rows(out_dir / "episodes.csv")) == 9


@requires_sb3
def test_experiment_run_groups_two_training_runs(sim_binary, multi_run_config, tmp_path):
    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_text(json.dumps({
        "matrix_version": 1,
        "name": "pipeline-smoke",
        "description": "Two training seeds on the fake simulator; smoke-sized budgets.",
        "run_config": multi_run_config,
        "band": None,
        "seeds": {"training": [1, 2], "model_selection": 5, "held_out": "11-12"},
        "training": {"total_timesteps": 16, "n_steps": 16, "eval_every_steps": 8},
        "evaluation": {"model": "best", "policies": ["model", "hold"]},
        "rows": [{"name": "local-delivery", "observation_preset": "local_links_v1",
                  "action_profile": "move_2d", "reward_components": ["delivery_ratio"],
                  "reward_weights": [1.0]}],
    }))

    root = tmp_path / "root"
    code = experiment.main(["run", "--matrix", str(matrix_path),
                            "--output-root", str(root), "--sim-binary", sim_binary])
    assert code in (0, 2), f"experiment run exited {code}"

    plan = experiment.load_plan(root)
    states = {step["id"]: experiment.step_state(step)[0] for step in plan["steps"]}
    assert set(states.values()) == {"done"}, states

    comparison = json.loads((root / "comparison" / "comparison.json").read_text())
    assert len(comparison["evaluations"]) == 2
    for block in comparison["evaluations"]:
        entry = _primary(block, "hold")
        assert (entry["n_expected"], entry["n_used"]) == (2, 2)
        assert entry["interval"]["kind"] == PAIRED_KIND

    group, = comparison["groups"]
    assert group["label"] == "local-delivery"
    assert (group["runs_expected"], group["runs_used"]) == (2, 2)
    assert group["excluded_runs"] == []
    entry = _primary(group, "hold")
    assert entry["common_seeds"] == [11, 12]
    assert entry["interval"]["kind"] == ACROSS_RUNS_KIND
