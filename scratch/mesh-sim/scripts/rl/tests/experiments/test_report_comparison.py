"""Reporting comparisons and accepted training history."""

import csv
import json
from pathlib import Path

import pytest

from scripts.artifact_io import sha256_file
from scripts.rl.experiments import reporting
from scripts.rl.policy.compare import build_comparison, load_evaluation
from scripts.rl.tests.support.report_fixtures import (
    SCENE,
    _dir,
    _edited_plan,
    _leaves,
    _plan,
    _progress,
    _row_configs,
    _task,
    _train_episodes,
    _train_manifest,
    _zip,
)


def _resumed_train(plan, root):
    train = _task(plan, f"train/{SCENE}/raw-delivery/train-seed-101")
    first = _dir(plan, root, train) / "attempt-1"
    checkpoint = first / "checkpoints/checkpoint_128_steps.zip"
    sha = _zip(checkpoint, 128, 8)
    _train_episodes(first, 1, 3)
    tail = first / "episode-0004"
    tail.mkdir()
    (tail / "rl_episode.json").write_text(
        json.dumps({"status": "interrupted", "steps": 10, "seed": 101})
    )
    _progress(first, range(32, 193, 32))
    _train_manifest(
        first, plan, 192, status="interrupted", checkpoints=[(checkpoint, 128)]
    )
    second = _dir(plan, root, train) / "attempt-2"
    _zip(second / "maskable_ppo_mesh.zip", 256, 16)
    _train_episodes(second, 1, 2)
    _progress(second, range(160, 257, 32))
    parent = {
        "run_dir": str(first),
        "model_selection": "checkpoint",
        "model_path": str(checkpoint),
        "model_sha256": sha,
        "num_timesteps": 128,
        "train_manifest_sha256": sha256_file(first / "train_manifest.json"),
    }
    _train_manifest(
        second,
        plan,
        256,
        resume={
            "parent": parent,
            "restored_timesteps": 128,
            "target_timesteps": 256,
            "remaining_timesteps": 128,
        },
    )
    return train, first, second, checkpoint


def test_curves_follow_accepted_history_and_exclude_abandoned_tail(
    tmp_path, sim_binary
):
    plan, root = _plan(tmp_path, sim_binary)
    train, first, second, _ = _resumed_train(plan, root)
    before = {p: sha256_file(p) for p in first.rglob("*") if p.is_file()}
    task = _task(plan, f"curves/{SCENE}")
    result = reporting.run_report_task(task, plan, root, {train["id"]: str(second)})
    assert result["incomplete"] is False
    attempt = root / result["attempt_dir"]
    folder = attempt / "raw-delivery/train-seed-101"
    with (folder / "training_curves.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert [int(r["total_episode"]) for r in rows] == [1, 2, 3, 4]
    assert [r["source"] for r in rows] == [
        "recovered",
        "recovered",
        "attempt",
        "attempt",
    ]
    assert len({r["episode_dir"] for r in rows}) == 4
    assert rows[0]["episode_dir"].endswith("attempt-1/episode-0001")
    sources = json.loads((folder / "training_curve_sources.json").read_text())
    assert set(sources) == {"training_curve_version", "sources", "note"}
    assert (
        sources["training_curve_version"]
        == reporting.TRAINING_CURVE_SOURCES_VERSION
        == 1
    )
    parent, child = sources["sources"]
    assert "status" not in parent and "status" not in child
    assert (
        parent["total_episodes"] == 2
        and parent["complete_episodes_after_checkpoint_excluded"] == 1
    )
    assert parent["selected_checkpoint"]["model_path"].endswith(
        "checkpoint_128_steps.zip"
    )
    assert not parent["selected_checkpoint"]["model_path"].startswith("/")
    assert child["restored_episodes"] == 2 and child["total_episodes"] == 4
    with (root / parent["ppo_progress"]).open() as handle:
        steps = [int(r["time/total_timesteps"]) for r in csv.DictReader(handle)]
    with (root / child["ppo_progress"]).open() as handle:
        steps += [int(r["time/total_timesteps"]) for r in csv.DictReader(handle)]
    assert steps == sorted(set(steps)) and max(steps[:4]) <= 128
    top = json.loads((attempt / "training_curve_sources.json").read_text())
    assert top["sources"] == sources["sources"]
    assert before == {p: sha256_file(p) for p in first.rglob("*") if p.is_file()}


def test_curves_refuse_changed_checkpoint_bytes(tmp_path, sim_binary):
    plan, root = _plan(tmp_path, sim_binary)
    train, _, second, checkpoint = _resumed_train(plan, root)
    _zip(checkpoint, 128, 9)
    with pytest.raises(ValueError, match="checkpoint bytes differ"):
        reporting.run_report_task(
            _task(plan, f"curves/{SCENE}"), plan, root, {train["id"]: str(second)}
        )


def _compare_plan(tmp_path, sim_binary, allow_incomplete=False):
    plan, root = _plan(
        tmp_path,
        sim_binary,
        comparison={
            "operation": "frozen-deterministic",
            "allow_incomplete": allow_incomplete,
        },
    )
    task = _task(plan, f"compare/{SCENE}/frozen-deterministic/checkpoint-128")
    return plan, root, task


def test_comparison_view_pools_seeds_for_compare(tmp_path, sim_binary):
    plan, root, task = _compare_plan(tmp_path, sim_binary)
    accepted = _leaves(plan, root)
    attempt = _dir(plan, root, task) / "attempt-1"
    dirs = reporting.build_comparison_view(
        task, plan, root, accepted, attempt_dir=attempt
    )
    assert dirs == [str(attempt.resolve() / "view" / "raw-delivery--train-seed-101")]
    evaluation = load_evaluation(dirs[0])
    assert evaluation.seeds == (201, 202)
    assert set(evaluation.records) == {"model", "hold", "random_valid", "scripted"}
    assert evaluation.label == "raw-delivery checkpoint-128 frozen-deterministic"
    comparison = build_comparison([evaluation])
    assert comparison["status"] == "complete"
    sources = json.loads((Path(dirs[0]) / reporting.VIEW_SOURCES).read_text())
    assert [s["role"] for s in sources["sources"]].count("model") == 2 and len(
        sources["sources"]
    ) == 8
    assert all(not s["eval_manifest"].startswith("/") for s in sources["sources"])


def test_comparison_view_refuses_mixed_or_missing_inputs(tmp_path, sim_binary):
    plan, root, task = _compare_plan(tmp_path, sim_binary)
    accepted = _leaves(plan, root)
    seed_202 = next(i for i in task["view"]["sources"] if i.endswith("seed-202"))
    path = Path(accepted[seed_202]) / "eval_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["scenario_identity"]["run_ini_sha256"] = "0" * 64
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="refusing to pool .*scenario_identity"):
        reporting.build_comparison_view(task, plan, root, accepted)
    without = {k: v for k, v in accepted.items() if k != seed_202}
    with pytest.raises(ValueError, match="missing accepted evaluations"):
        reporting.build_comparison_view(task, plan, root, without)
    online = [
        t["id"]
        for t in plan["tasks"]
        if t["kind"] == "operate"
        and t["identity"]["operation"] == "online-sb3"
        and t["identity"]["checkpoint"] == "128"
    ]
    task["view"].update(operation="online-sb3", sources=online)
    with pytest.raises(ValueError, match="writes no evaluation manifest"):
        reporting.build_comparison_view(task, plan, root, accepted)


def test_incomplete_view_is_explicit(tmp_path, sim_binary):
    plan, root, task = _compare_plan(tmp_path, sim_binary, allow_incomplete=True)
    accepted = _leaves(
        plan,
        root,
        values={i: None for i in task["view"]["sources"] if i.endswith("201")},
    )
    seed_202 = next(i for i in task["view"]["sources"] if i.endswith("seed-202"))
    del accepted[seed_202]
    dirs = reporting.build_comparison_view(task, plan, root, accepted)
    evaluation = load_evaluation(dirs[0])
    assert evaluation.manifest["status"] == "partial" and evaluation.seeds == (201, 202)
    assert 202 not in evaluation.records["model"]
    assert evaluation.records["model"][201]["metrics"]["delivery_ratio"] is None
    assert build_comparison([evaluation])["status"] == "incomplete"


def test_comparison_view_refuses_mixed_inis(tmp_path, sim_binary):
    def edit(data, inputs):
        _row_configs(data, inputs)
        data["evaluation"]["comparison"] = {
            "operation": "frozen-deterministic",
            "allow_incomplete": False,
        }

    plan, root = _edited_plan(tmp_path, sim_binary, edit)
    accepted = _leaves(plan, root)
    task = _task(plan, f"compare/{SCENE}/frozen-deterministic/checkpoint-final")
    with pytest.raises(ValueError, match="different INIs"):
        reporting.build_comparison_view(task, plan, root, accepted)
