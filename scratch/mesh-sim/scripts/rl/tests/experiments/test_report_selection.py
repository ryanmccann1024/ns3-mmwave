"""Evidence from planned operations for batch selection."""

import json
import shutil
from pathlib import Path

import pytest

from scripts.artifact_io import sha256_file
from scripts.rl.experiments import reporting
from scripts.rl.experiments.config import load_matrix_v2
from scripts.rl.experiments.plan import build_batch_plan
from scripts.rl.tests.support.report_fixtures import (
    BATCH,
    EXAMPLE,
    SCENE,
    _dir,
    _edited_plan,
    _task,
    _write_operate,
)


def _stage_plan(tmp_path, sim_binary, rule):
    inputs = tmp_path / "inputs"
    shutil.copytree(EXAMPLE, inputs)
    data = json.loads((inputs / "batch.json").read_text())
    base = data["rows"][0]
    data["rows"] = [
        {**base, "name": n, "profile": p}
        for n, p in (
            ("screen-a", "a"),
            ("screen-b", "b"),
            ("main-a", "a"),
            ("main-b", "b"),
        )
    ]
    for op in data["evaluation"]["operations"]:
        op["at_steps"] = ["final"]
    selection = {
        "rule": rule,
        "candidates": {"a": ["screen-a"], "b": ["screen-b"]},
        "branches": {"a": ["main-a"], "b": ["main-b"]},
    }
    if rule == "legacy-validation-profile-v1":
        data["seeds"]["model_selection"] = [301]
        data["training"].update(eval_every_steps=128, checkpoint_timing="standard")
        data["execution"]["recovery"] = "none"
        selection["normalization_decisions"] = 64
    elif rule == "replay":
        selection.update(
            winners=["b"], provenance="recorded winner of an earlier screen"
        )
    else:
        selection["source_operation"] = (
            "online-sb3"
            if rule == "legacy-online-profile-v1"
            else "frozen-deterministic"
        )
    data["stages"] = [
        {"name": "screen", "rows": ["screen-a", "screen-b"], "selection": selection},
        {"name": "main", "rows": ["main-a", "main-b"], "needs": ["screen"]},
    ]
    (inputs / "batch.json").write_text(json.dumps(data))
    matrix = load_matrix_v2(inputs / "batch.json")
    root = tmp_path / BATCH
    plan = build_batch_plan(matrix, root, sim_binary)
    return plan, root, _task(plan, "select/screen")


def _score_leaves(plan, root, task, scores, monkeypatch):
    """Operation leaves for every declared source; mission scores keyed by episode directory."""
    from scripts.rl.policy import mission_metrics

    by_dir, accepted, shas = {}, {}, {}
    for candidate, ids in task["selection_rule"]["sources"].items():
        for index, source_id in enumerate(ids):
            source = _task(plan, source_id)
            binding = source["binding"]
            shas.setdefault(
                (binding["producer"], binding["checkpoint"]), ("7" * 64, 256, "final")
            )
            leaf = _write_operate(plan, root, source, shas)
            accepted[source_id] = str(leaf)
            by_dir[str((leaf / "episode-0001").resolve())] = scores[candidate][index]
    monkeypatch.setattr(
        mission_metrics,
        "mission_episode_metrics",
        lambda d: {"mission_score": by_dir[str(Path(d).resolve())]},
    )
    return accepted


def test_selection_evidence_for_mission_rule_feeds_select(
    tmp_path, sim_binary, monkeypatch
):
    from scripts.rl.experiments.selection import select

    plan, root, task = _stage_plan(tmp_path, sim_binary, "legacy-mission-profile-v1")
    accepted = _score_leaves(
        plan, root, task, {"a": [0.2, 0.4], "b": [0.9, 0.7]}, monkeypatch
    )
    evidence = reporting.selection_evidence(task, plan, str(root), accepted)
    assert set(evidence) == {"a", "b"} and all(
        len(items) == 2 for items in evidence.values()
    )
    item = evidence["b"][0]
    assert (
        item["task"] in task["selection_rule"]["sources"]["b"]
        and item["seed_role"] == "diagnostic"
    )
    assert item["path"].endswith("/eval_manifest.json") and item["attempt"].endswith(
        "/attempt-1"
    )
    assert item["sha256"] == sha256_file(root / item["path"]) and item["samples"] == 1
    assert item["values"] == [0.9] and item["case"] == SCENE
    receipt = select({**task["selection_rule"], "settings": {"retain": []}}, evidence)
    assert receipt["selected"] == ["b"] and receipt["selected_branches"] == ["main-b"]
    assert receipt["held_out_seeds_used"] is False and len(receipt["sources"]) == 4


def test_selection_evidence_online_rule_reads_online_episodes(
    tmp_path, sim_binary, monkeypatch
):
    from scripts.rl.experiments.selection import select

    plan, root, task = _stage_plan(tmp_path, sim_binary, "legacy-online-profile-v1")
    accepted = _score_leaves(
        plan, root, task, {"a": [0.5, 0.6], "b": [0.1, 0.2]}, monkeypatch
    )
    evidence = reporting.selection_evidence(task, plan, str(root), accepted)
    assert all(
        i["path"].endswith("/online_manifest.json")
        for items in evidence.values()
        for i in items
    )
    assert select(task["selection_rule"], evidence)["selected"] == ["a"]


def test_selection_evidence_refuses_missing_and_held_out(
    tmp_path, sim_binary, monkeypatch
):
    plan, root, task = _stage_plan(tmp_path, sim_binary, "legacy-mission-profile-v1")
    accepted = _score_leaves(
        plan, root, task, {"a": [0.2, 0.4], "b": [0.9, 0.7]}, monkeypatch
    )
    dropped = task["selection_rule"]["sources"]["a"][0]
    with pytest.raises(
        ValueError, match="selection blocked: .* has no accepted result"
    ):
        reporting.selection_evidence(
            task, plan, str(root), {k: v for k, v in accepted.items() if k != dropped}
        )
    source = _task(plan, dropped)
    source["identity"]["seed_role"] = "held_out"
    with pytest.raises(ValueError, match="never consumes 'held_out'"):
        reporting.selection_evidence(task, plan, str(root), accepted)


def test_selection_evidence_validation_and_replay(tmp_path, sim_binary):
    import numpy as np

    from scripts.rl.experiments.selection import select

    plan, root, task = _stage_plan(tmp_path, sim_binary, "legacy-validation-profile-v1")
    accepted = {}
    for candidate, best in (("a", 32.0), ("b", 48.0)):
        (source_id,) = task["selection_rule"]["sources"][candidate]
        attempt = _dir(plan, root, _task(plan, source_id)) / "attempt-1"
        attempt.mkdir(parents=True)
        (attempt / "train_manifest.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "best_mean_reward": best,
                    "evaluation": {"seeds": [301]},
                }
            )
        )
        np.savez(
            attempt / "evaluations.npz",
            results=np.array([[1.0, 3.0], [2.0, 2.0], [4.0, 6.0]]),
        )
        accepted[source_id] = str(attempt)
    evidence = reporting.selection_evidence(task, plan, str(root), accepted)
    item = evidence["b"][0]
    assert item["seed_role"] == "model_selection" and item["checkpoint_means"] == [
        2.0,
        2.0,
        5.0,
    ]
    assert item["path"].endswith("/train_manifest.json") and item[
        "evaluations"
    ].endswith("evaluations.npz")
    receipt = select(task["selection_rule"], evidence)
    assert (
        receipt["selected"] == ["b"]
        and receipt["ranking"][0]["validation_mean_reward"] == 48.0 / 64
    )
    plan["seeds"]["held_out"] = [301]
    with pytest.raises(ValueError, match="held-out"):
        reporting.selection_evidence(task, plan, str(root), accepted)

    replay_plan, replay_root, replay_task = _stage_plan(
        tmp_path / "r", sim_binary, "replay"
    )
    assert (
        reporting.selection_evidence(replay_task, replay_plan, str(replay_root), {})
        == {}
    )
    assert select(replay_task["selection_rule"], {})["selected"] == ["b"]


def test_operation_candidates_feed_select_at_exact_checkpoint(
    tmp_path, sim_binary, monkeypatch
):
    from scripts.rl.experiments.selection import select

    def edit(data, _):
        base = data["rows"][0]
        data["rows"] = [{**base, "name": n} for n in ("screen", "main")]
        data["stages"] = [
            {
                "name": "screen",
                "rows": ["screen"],
                "selection": {
                    "rule": "legacy-mission-profile-v1",
                    "source_checkpoint": "final",
                    "candidates": {
                        "det": [{"row": "screen", "operation": "frozen-deterministic"}],
                        "sam": [{"row": "screen", "operation": "frozen-sampled"}],
                    },
                    "branches": {
                        "det": [{"row": "main", "operation": "frozen-deterministic"}],
                        "sam": [{"row": "main", "operation": "frozen-sampled"}],
                    },
                },
            },
            {"name": "main", "rows": ["main"], "needs": ["screen"]},
        ]

    plan, root = _edited_plan(tmp_path, sim_binary, edit)
    task = _task(plan, "select/screen")
    assert (
        task["selection_rule"]["form"] == "operations"
        and task["selection_rule"]["source_kind"] == "operation"
    )
    accepted = _score_leaves(
        plan, root, task, {"det": [0.3, 0.5], "sam": [0.8, 0.6]}, monkeypatch
    )
    evidence = reporting.selection_evidence(task, plan, str(root), accepted)
    items = [i for group in evidence.values() for i in group]
    assert len(items) == 4 and {i["checkpoint"] for i in items} == {"final"}
    assert {(i["row"], i["operation"]) for i in evidence["sam"]} == {
        ("screen", "frozen-sampled")
    }
    receipt = select(task["selection_rule"], evidence)
    assert receipt["selected"] == ["sam"] and receipt["held_out_seeds_used"] is False
    # A source at another checkpoint is never a declared input.
    stray = next(
        t
        for t in plan["tasks"]
        if t["kind"] == "operate" and t["identity"]["checkpoint"] == "128"
    )
    task["selection_rule"]["sources"]["det"].append(stray["id"])
    with pytest.raises(ValueError, match="not a declared input"):
        reporting.selection_evidence(task, plan, str(root), accepted)


@pytest.mark.parametrize(
    "foreign_seed, foreign_attempt, message",
    [
        (True, False, "one episode for seed 201"),
        (False, True, "outside its accepted attempt"),
    ],
)
def test_selection_rejects_evidence_from_wrong_seed_or_attempt(
    tmp_path,
    sim_binary,
    monkeypatch,
    foreign_seed,
    foreign_attempt,
    message,
):
    plan, root, task = _stage_plan(tmp_path, sim_binary, "legacy-mission-profile-v1")
    accepted = _score_leaves(
        plan, root, task, {"a": [0.2, 0.4], "b": [0.9, 0.7]}, monkeypatch
    )
    first, second = task["selection_rule"]["sources"]["a"]
    path = Path(accepted[first]) / "eval_manifest.json"
    manifest = json.loads(path.read_text())
    episode = manifest["policies"]["model"]["episodes"][0]
    if foreign_seed:
        episode["seed"] = 202
    if foreign_attempt:
        episode["episode_dir"] = str(Path(accepted[second]) / "episode-0001")
    path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match=message):
        reporting.selection_evidence(task, plan, root, accepted)
