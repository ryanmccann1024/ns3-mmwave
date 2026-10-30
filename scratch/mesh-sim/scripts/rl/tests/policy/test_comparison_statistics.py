"""Gaps in policy/compare.py and policy/compare_inputs.py on hand-built eval manifests.

Contract sources: scripts/rl/policy/README.md ("Comparison", "Reading the output",
exit_code table), scripts/rl/policy/CLAUDE.md, scripts/rl/CLAUDE.md (version
mirroring). Differences are always model minus baseline; a seed is dropped when
either side is missing, not completed, or null; groups are keyed by scenario
digests and training settings and mixing them is an error.
"""

import json
import math
from pathlib import Path

import pytest

from scripts.rl.policy.compare import build_comparison, load_evaluation

SEEDS = (11, 12, 13)


def _episode(seed, value, status="completed", **metric_overrides):
    """A completed episode whose metrics all equal `value` unless overridden."""
    if status != "completed" and value is not None:
        value = None
    metrics = {"delivery_ratio": value, "connectivity": value, "los_fraction": value,
               "unroutable_fraction": value, "first_all_los_decision": None,
               "travel_m_total": None, "displacement_m_final": None}
    metrics.update(metric_overrides)
    return {"seed": seed, "status": status, "error": None,
            "return": None if value is None else -float(value),
            "decisions": 0 if status == "not_run" else 10,
            "mask_violations": 0, "revalidated_slots_total": 0,
            "actions_sha256": "c" * 64, "episode_dir": f"/eval/{seed}",
            "summary_json": None, "metrics": metrics}


def _manifest(policies, *, seeds=SEEDS, label=None, training_seed=101,
              model_sha256="a" * 64, held_out=True, band="mmwave",
              model_selection="best", num_timesteps=256):
    """policies: {name: {seed: value | "failed" | "not_run" | None | dict}}."""
    blocks = {}
    for name, per_seed in policies.items():
        episodes = []
        for seed, value in per_seed.items():
            if isinstance(value, dict):
                episodes.append(value)
            elif isinstance(value, str):
                episodes.append(_episode(seed, None, status=value))
            else:
                episodes.append(_episode(seed, value))
        blocks[name] = {"episodes": episodes, "summary": {}}
    return {
        "eval_manifest_version": 6, "status": "completed", "label": label,
        "seeds": list(seeds),
        "metric_source": {"kind": "telemetry_window", "warmup_excluded": True},
        "seed_roles": {"training_seed": training_seed, "held_out": held_out},
        "training": {"algorithm": "MaskablePPO", "seed": training_seed,
                     "evaluation_seed": 201,
                     "scenario_identity": {"run_ini_sha256": "t" * 64,
                                           "nodes_json_sha256": "n" * 64,
                                           "buildings_json_sha256": None,
                                           "jammers_json_sha256": None},
                     "hyperparameters": {"total_timesteps": 256, "n_steps": 64,
                                         "gamma": 0.95, "ent_coef": 0.01,
                                         "eval_every_steps": 128, "eval_episodes": 1}},
        "bundle": {"model_selection": model_selection, "model_sha256": model_sha256,
                   "num_timesteps": num_timesteps},
        "selection": {"observation_preset": "local_links_v1",
                      "reward_components": ["delivery_ratio"], "reward_weights": [1.0]},
        "observation_schema": {"sha256": "o" * 64},
        "reward_schema": {"sha256": "r" * 64},
        "scenario_identity": {"run_ini_sha256": "s" * 64, "nodes_json_sha256": "n" * 64,
                              "buildings_json_sha256": None, "jammers_json_sha256": None},
        "band": band, "policies": blocks,
    }


def _write(path: Path, manifest: dict) -> str:
    path.mkdir(parents=True, exist_ok=True)
    (path / "eval_manifest.json").write_text(json.dumps(manifest, indent=2))
    return str(path)


def _load(tmp_path: Path, manifest: dict, name="eval"):
    return load_evaluation(_write(tmp_path / name, manifest))


def _pick(block, baseline="hold", metric="delivery_ratio"):
    return next(c for c in block["comparisons"]
                if c["baseline"] == baseline and c["metric"] == metric)


# 1. Version / constant mirroring ----------------------------------------------------


# 2. load_evaluation validation ------------------------------------------------------


# 3. Paired statistics: signs, exclusions, intervals ---------------------------------

def test_difference_is_model_minus_baseline_even_when_negative(tmp_path):
    evaluation = _load(tmp_path, _manifest({"model": {11: 0.5, 12: 0.4, 13: 0.3},
                                            "hold": {11: 0.7, 12: 0.7, 13: 0.7}}))
    entry = _pick(build_comparison([evaluation])["evaluations"][0])
    assert [p["difference"] for p in entry["pairs"]] == pytest.approx([-0.2, -0.3, -0.4])
    assert entry["mean_difference"] == pytest.approx(-0.3)
    assert entry["mean_difference"] == pytest.approx(entry["model_mean"]
                                                     - entry["baseline_mean"])
    assert entry["interval"]["low"] < entry["mean_difference"] < entry["interval"]["high"]


def test_two_pairs_use_df_one(tmp_path):
    evaluation = _load(tmp_path, _manifest({"model": {11: 0.9, 12: 0.7},
                                            "hold": {11: 0.6, 12: 0.6}}, seeds=(11, 12)))
    entry = _pick(build_comparison([evaluation])["evaluations"][0])
    interval = entry["interval"]
    std = math.sqrt(((0.3 - 0.2) ** 2 + (0.1 - 0.2) ** 2) / 1)
    assert (interval["n"], interval["df"], interval["level"]) == (2, 1, 0.95)
    assert interval["t"] == 12.706
    assert interval["half_width"] == pytest.approx(12.706 * std / math.sqrt(2))
    assert interval["low"] + interval["high"] == pytest.approx(2 * entry["mean_difference"])


# 4. exit_code -----------------------------------------------------------------------


# 5. Groups across training runs ------------------------------------------------------

def _run(tmp_path, index, model, *, label="a", seeds=(11, 12), **kwargs):
    kwargs.setdefault("training_seed", 101 + index)
    kwargs.setdefault("model_sha256", chr(97 + index) * 64)
    manifest = _manifest({"model": model, "hold": {s: 0.6 for s in seeds}},
                         seeds=seeds, label=label, **kwargs)
    return _load(tmp_path, manifest, f"run-{index}")


def test_group_mean_difference_is_the_mean_of_per_run_means(tmp_path):
    runs = [_run(tmp_path, 0, {11: 0.7, 12: 0.9}),    # mean diff 0.2
            _run(tmp_path, 1, {11: 0.5, 12: 0.5})]    # mean diff -0.1
    entry = _pick(build_comparison(runs)["groups"][0])
    assert [r["mean_difference"] for r in entry["per_run"]] == pytest.approx([0.2, -0.1])
    assert entry["mean_difference"] == pytest.approx(0.05)
    assert entry["std_across_runs"] == pytest.approx(math.sqrt(0.045))
    assert entry["interval"]["df"] == 1 and entry["interval"]["t"] == 12.706
    assert entry["interval"]["fixed_model"] is False


def test_runs_without_a_common_usable_seed_yield_no_group_value(tmp_path):
    runs = [_run(tmp_path, 0, {11: "failed", 12: 0.8}),
            _run(tmp_path, 1, {11: 0.8, 12: "failed"})]
    payload = build_comparison(runs)
    group = payload["groups"][0]
    assert group["runs_used"] == 2
    entry = _pick(group)
    assert entry["common_seeds"] == []
    assert entry["seeds_dropped_for_commonality"] == [11, 12]
    assert [r["mean_difference"] for r in entry["per_run"]] == [None, None]
    assert entry["mean_difference"] is None and entry["interval"] is None
    assert entry["interval_omitted"] == "fewer than 2 usable runs"


def test_a_run_with_no_usable_pairs_is_excluded_from_its_group(tmp_path):
    runs = [_run(tmp_path, 0, {11: 0.8, 12: 0.8}),
            _run(tmp_path, 1, {11: "failed", 12: "failed"})]
    group = build_comparison(runs)["groups"][0]
    assert group["runs_used"] == 1 and group["runs_expected"] == 2
    assert group["excluded_runs"] == [{"training_seed": 102, "reason": "no_usable_pairs"}]
