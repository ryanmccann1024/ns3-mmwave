"""Scenario indexes, reviews and reward summaries from fake batch artifacts.

Plans come from the public coordination-smoke example; every accepted attempt
is a small hand-written leaf (eval manifest v8, online manifest v5, bindings,
tiny model ZIPs). No simulator runs. The contract fixtures under
``tests/fixtures/`` are what these writers produce; set
``MESH_REGENERATE_BATCH_FIXTURES=1`` to rewrite them deliberately.
"""

import csv
import json
import os
import shutil
from pathlib import Path

import pytest

from scripts.artifact_io import sha256_file
from scripts.rl.experiments import reporting
from scripts.rl.experiments.config import load_matrix_v2
from scripts.rl.experiments.plan import build_batch_plan
from scripts.rl.policy import episode_review
from scripts.rl.tests.support.report_fixtures import (
    BATCH,
    EXAMPLE,
    MESH,
    SB3_FINAL_202,
    SCENE,
    _dir,
    _edited_plan,
    _leaves,
    _pipeline,
    _plan,
    _review_stub,
    _row_configs,
    _task,
)

FIXTURES = MESH / "tests/fixtures"


INDEX_FIXTURE = FIXTURES / "batch_index_v4_example.json"


ONLINE_FIXTURE = FIXTURES / "batch_online_manifest_v5_example.json"


REGENERATE = os.environ.get("MESH_REGENERATE_BATCH_FIXTURES") == "1"


PATH_KEYS = {
    "path",
    "attempt",
    "eval_manifest",
    "online_manifest",
    "weight_audit",
    "episode_dir",
    "inputs",
    "binding",
    "model_path",
    "run_dir",
    "train_manifest",
    "curves",
    "source",
    "comparison",
    "phase_comparison",
    "reward_summary",
    "batch_reward_summary",
    "plan",
}


def _check_paths(value, root, key=None):
    if isinstance(value, dict):
        for k, v in value.items():
            _check_paths(v, root, k)
    elif isinstance(value, list):
        for v in value:
            _check_paths(v, root, key)
    elif isinstance(value, str):
        assert not value.startswith("/") and "://" not in value, (key, value)
        if key in PATH_KEYS:
            reporting.check_relative(value)
            assert (root / value).exists(), (key, value)


def _fixture(path: Path, payload):
    if REGENERATE:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    assert (
        json.loads(path.read_text()) == payload
    ), f"{path.name} drifted from the writer; see module docstring"


def test_index_v4_fields_relative_paths_and_contract_fixtures(
    tmp_path, sim_binary, monkeypatch
):
    plan, root = _plan(tmp_path, sim_binary)
    accepted, result, index = _pipeline(plan, root, monkeypatch, skip={SB3_FINAL_202})
    assert (
        reporting.MISSION_SCENARIO_VERSION == 4
        and index["mission_scenario_version"] == 4
    )
    assert index["batch"]["name"] == BATCH and index["scene"] == SCENE
    assert index["incomplete"] is True and result["incomplete"] is True
    assert index["missing"] == [SB3_FINAL_202]
    _check_paths(index, root)
    for key in (
        "case",
        "assets",
        "models",
        "baselines",
        "reports",
        "seeds",
        "validation_seeds",
    ):
        assert key in index
    assert index["assets"]["run_config"]["run_config"]["path"].startswith(
        f"main/{SCENE}/assets/"
    )
    assert index["assets"]["reference"]["kind"] == "scenario_routes_v1"
    model = index["models"][0]
    for key in (
        "row",
        "profile",
        "training_seed",
        "checkpoint",
        "selection",
        "ppo",
        "schemas",
        "model",
        "training",
        "evaluations",
        "reward_label",
    ):
        assert key in model
    assert model["model"]["status"] == "bound" and model["model"]["binding"].startswith(
        "state/bindings/"
    )
    refs = [r for m in index["models"] for r in m["evaluations"]]
    assert len(refs) == 16 and {r["protocol"] for r in refs} == {
        "frozen_deterministic",
        "frozen_sampled",
        "online_gated_v1",
        "online_sb3_v1",
    }
    missing = [r for r in refs if r["status"] == "missing"]
    assert [r["task"] for r in missing] == [SB3_FINAL_202] and missing[0][
        "attempt"
    ] is None
    sb3 = next(
        r
        for r in refs
        if r["protocol"] == "online_sb3_v1" and r["status"] == "complete"
    )
    assert sb3["eval_manifest"] is None and sb3["online_manifest"].endswith(
        "/online_manifest.json"
    )
    det = next(r for r in refs if r["protocol"] == "frozen_deterministic")
    assert det["online_manifest"] is None and det["eval_manifest"].endswith(
        "/eval_manifest.json"
    )
    assert all(
        e["inputs"] for r in refs if r["status"] == "complete" for e in r["episodes"]
    )
    assert len(index["baselines"]) == 3 and all(
        len(b["evaluations"]) == 2 for b in index["baselines"]
    )
    assert (
        index["reports"]["mission_review"]["path"]
        == f"main/{SCENE}/mission_review.json"
    )
    assert index["reports"]["curves"][0]["curves"].endswith("/training_curves.csv")
    for path in root.rglob("mission_scenario.json"):
        assert json.loads(path.read_text())["mission_scenario_version"] == 4
    assert all(reporting.check_relative(p) for p in result["outputs"])

    _fixture(INDEX_FIXTURE, index)
    gated = _task(
        plan,
        f"operate/{SCENE}/raw-delivery/train-seed-101/checkpoint-final/online-gated/"
        "diagnostic/seed-201",
    )
    _fixture(
        ONLINE_FIXTURE,
        json.loads((Path(accepted[gated["id"]]) / "online_manifest.json").read_text()),
    )


def test_arbitrary_batch_name_complete_index(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary, name="zz-any-name-7")
    _, result, index = _pipeline(plan, root, monkeypatch)
    assert index["batch"]["name"] == "zz-any-name-7"
    assert (
        index["incomplete"] is False
        and index["missing"] == []
        and index["issues"] == []
    )
    refs = [r for m in index["models"] for r in m["evaluations"]] + [
        r for b in index["baselines"] for r in b["evaluations"]
    ]
    assert refs and all(r["status"] == "complete" and not r["issues"] for r in refs)
    assert result["incomplete"] is False
    _check_paths(index, root)


def test_missing_leaves_label_index_incomplete(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary)
    _, _, index = _pipeline(plan, root, monkeypatch, baselines=False)
    assert index["incomplete"] is True
    baseline_ids = sorted(t["id"] for t in plan["tasks"] if t["kind"] == "baseline")
    assert index["missing"] == baseline_ids
    for entry in index["baselines"]:
        assert all(
            r["status"] == "missing" and r["eval_manifest"] is None
            for r in entry["evaluations"]
        )


def test_skipped_selection_is_not_counted_missing(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary)
    monkeypatch.setattr(episode_review, "review_metrics", _review_stub)
    accepted = _leaves(plan, root, skip={SB3_FINAL_202})
    task = _task(plan, f"index/{SCENE}")
    reporting.run_report_task(task, plan, root, accepted, skipped={SB3_FINAL_202})
    index = json.loads((root / "main" / SCENE / "mission_scenario.json").read_text())
    assert SB3_FINAL_202 not in index["missing"]
    ref = next(
        r
        for m in index["models"]
        for r in m["evaluations"]
        if r["task"] == SB3_FINAL_202
    )
    assert ref["status"] == "skipped_selection"


def test_groups_agree_only_on_full_identity(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary)
    _, _, index = _pipeline(plan, root, monkeypatch)
    refs = {
        (r["operation"], m["checkpoint"], r["seed"]): r
        for m in index["models"]
        for r in m["evaluations"]
    }
    assert (
        refs[("frozen-deterministic", "128", 201)]["group"]
        == refs[("frozen-deterministic", "128", 202)]["group"]
    )
    distinct = {
        refs[(op, ckpt, 201)]["group"]
        for op in (
            "frozen-deterministic",
            "frozen-sampled",
            "online-gated",
            "online-sb3",
        )
        for ckpt in ("128", "final")
    }
    assert len(distinct) == 8
    assert (
        refs[("frozen-deterministic", "128", 201)]["model_sha256"]
        != refs[("frozen-deterministic", "final", 201)]["model_sha256"]
    )
    baselines = {b["policy"]: b["evaluations"] for b in index["baselines"]}
    assert (
        baselines["hold"][0]["group"]
        == baselines["hold"][1]["group"]
        != baselines["scripted"][0]["group"]
    )


def test_recorded_model_digest_mismatch_is_incomplete(
    tmp_path, sim_binary, monkeypatch
):
    plan, root = _plan(tmp_path, sim_binary)
    monkeypatch.setattr(episode_review, "review_metrics", _review_stub)
    accepted = _leaves(plan, root)
    task_id = f"operate/{SCENE}/raw-delivery/train-seed-101/checkpoint-128/frozen-deterministic/diagnostic/seed-201"
    path = Path(accepted[task_id]) / "eval_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["bundle"]["model_sha256"] = "9" * 64
    path.write_text(json.dumps(manifest))
    reporting.run_report_task(_task(plan, f"index/{SCENE}"), plan, root, accepted)
    index = json.loads((root / "main" / SCENE / "mission_scenario.json").read_text())
    ref = next(
        r for m in index["models"] for r in m["evaluations"] if r["task"] == task_id
    )
    assert (
        ref["status"] == "incomplete"
        and "differs from the bound model" in ref["issues"][0]
    )
    assert index["incomplete"] is True


def test_reward_summary_keeps_campaign_meanings_and_nulls(
    tmp_path, sim_binary, monkeypatch
):
    plan, root = _plan(tmp_path, sim_binary)
    nulls = {
        t["id"]: None
        for t in plan["tasks"]
        if t["kind"] == "operate"
        and t["identity"]["operation"] == "frozen-sampled"
        and t["identity"]["checkpoint"] == "final"
    }
    half = {
        f"operate/{SCENE}/raw-delivery/train-seed-101/checkpoint-128/frozen-deterministic/"
        "diagnostic/seed-202": 0.4
    }
    _pipeline(plan, root, monkeypatch, values={**nulls, **half})
    with (root / "main" / SCENE / reporting.REWARD_SUMMARY_CSV).open() as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames) == reporting.REWARD_SUMMARY_FIELDS
        assert reader.fieldnames[:13] == [
            "scenario",
            "reward",
            "training_seed",
            "policy",
            "completed_episodes",
            *reporting.REWARD_SUMMARY_METRICS,
        ]
        rows = list(reader)
    sampled = next(
        r
        for r in rows
        if r["operation"] == "frozen-sampled" and r["checkpoint"] == "final"
    )
    assert sampled["delivery_ratio"] == "" and sampled["completed_episodes"] == "2"
    data = json.loads(
        (root / "main" / SCENE / reporting.REWARD_SUMMARY_JSON).read_text()
    )
    row = next(
        r
        for r in data["rows"]
        if r["operation"] == "frozen-sampled" and r["checkpoint"] == "final"
    )
    assert row["delivery_ratio"] is None and row["post_jammer_delivery_ratio"] is None
    det = next(
        r
        for r in data["rows"]
        if r["operation"] == "frozen-deterministic" and r["checkpoint"] == "128"
    )
    assert det["delivery_ratio"] == pytest.approx(0.6) and det["evaluation_seeds"] == [
        201,
        202,
    ]
    assert len(det["sources"]) == 2 and all(
        reporting.check_relative(s["manifest"]) for s in det["sources"]
    )
    hold = next(r for r in data["rows"] if r["policy"] == "hold")
    assert (
        hold["reward"] is None
        and hold["training_seed"] is None
        and hold["delivery_ratio"] == 0.5
    )
    assert "not ranked" in data["note"] and "rank" not in json.dumps(data["rows"])
    batch = json.loads((root / "main" / reporting.REWARD_SUMMARY_JSON).read_text())
    assert batch["scope"] == "batch" and batch["rows"] == data["rows"]
    assert (
        batch["scenarios"][0]["path"] == f"main/{SCENE}/{reporting.REWARD_SUMMARY_JSON}"
    )
    assert (root / "main" / reporting.REWARD_SUMMARY_CSV).is_file()


def test_review_is_v1_without_status_and_projected(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary)
    accepted, _, _ = _pipeline(plan, root, monkeypatch)
    source = Path(accepted[f"review/{SCENE}"]) / "mission_review.json"
    review = json.loads(source.read_text())
    assert set(review) == {
        "mission_review_version",
        "objective",
        "ranking_basis",
        "ranking",
        "episodes",
    }
    assert review["mission_review_version"] == 1 and review["objective"] == "coverage"
    assert (
        len(review["ranking"]) == 2
    )  # frozen deterministic, one per checkpoint; seeds pooled
    leaves = [t for t in plan["tasks"] if t["kind"] in ("operate", "baseline")]
    assert len(review["episodes"]) == len(leaves)
    assert all(not k.startswith("/") for k in review["episodes"])
    assert (
        root / "main" / SCENE / "mission_review.json"
    ).read_bytes() == source.read_bytes()


def test_main_rebuild_never_moves_or_changes_siblings(
    tmp_path, sim_binary, monkeypatch
):
    plan, root = _plan(tmp_path, sim_binary)
    accepted, _, _ = _pipeline(plan, root, monkeypatch)

    def snapshot():
        return {
            p.relative_to(root).as_posix(): sha256_file(p)
            for p in root.rglob("*")
            if p.is_file() and p.relative_to(root).parts[0] != "main"
        }

    before = snapshot()
    index_path = root / "main" / SCENE / "mission_scenario.json"
    first = index_path.read_bytes()
    reporting.run_report_task(_task(plan, f"index/{SCENE}"), plan, root, accepted)
    assert snapshot() == before and index_path.read_bytes() == first


def test_accepted_directory_must_belong_to_its_task(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary)
    accepted = _leaves(plan, root)
    operate = next(t for t in plan["tasks"] if t["kind"] == "operate")
    baseline = next(t for t in plan["tasks"] if t["kind"] == "baseline")
    accepted[operate["id"]] = accepted[baseline["id"]]
    with pytest.raises(ValueError, match="not inside that task's destination"):
        reporting.run_report_task(_task(plan, f"index/{SCENE}"), plan, root, accepted)
    with pytest.raises(ValueError, match="escapes|not a batch-relative"):
        reporting.check_relative("../outside")
    with pytest.raises(ValueError):
        reporting.check_relative("/abs/path")


def test_absolute_episode_dirs_become_relative(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary)
    _, _, index = _pipeline(plan, root, monkeypatch, absolute=True)
    _check_paths(index, root)
    det = next(
        r
        for m in index["models"]
        for r in m["evaluations"]
        if r["protocol"] == "frozen_deterministic"
    )
    assert det["episodes"][0]["episode_dir"].startswith("operations/")


def test_scheduler_record_forms_are_accepted(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary)
    monkeypatch.setattr(episode_review, "review_metrics", _review_stub)
    accepted = _leaves(plan, root, skip={SB3_FINAL_202})
    records = {
        t["id"]: {"state": "completed", "attempt_dir": accepted[t["id"]]}
        if t["id"] in accepted
        else {
            "state": "skipped_selection" if t["id"] == SB3_FINAL_202 else "pending",
            "attempt_dir": None,
        }
        for t in plan["tasks"]
    }
    task = _task(plan, f"review/{SCENE}")
    attempt = _dir(plan, root, task) / "attempt-3"
    attempt.mkdir(parents=True)
    result = reporting.run_report_task(
        {**task, "attempt_dir": str(attempt)}, plan, str(root), records
    )
    assert (
        result["attempt_dir"].endswith("/attempt-3") and result["incomplete"] is False
    )
    reporting.run_report_task(_task(plan, f"index/{SCENE}"), plan, str(root), records)
    index = json.loads((root / "main" / SCENE / "mission_scenario.json").read_text())
    assert SB3_FINAL_202 not in index["missing"]
    assert f"review/{SCENE}" in index["missing"]  # still pending in this record set


def test_placement_baseline_entry_carries_planning(tmp_path, sim_binary, monkeypatch):
    def edit(data, _):
        data["scenarios"][SCENE]["baselines"] = {
            "policies": ["scripted", "hold", "geometric"],
            "seed_role": "diagnostic",
            "planning_seed": 401,
        }

    plan, root = _edited_plan(tmp_path, sim_binary, edit)
    mapping = tmp_path / "inputs" / "mapping.json"
    mapping.write_text('{"cells": []}')
    for task in plan["tasks"]:
        if task["kind"] == "baseline" and task["identity"]["policy"] == "geometric":
            task["planning"]["mapping_file"] = str(mapping)
    plan["inputs"][str(mapping.resolve())] = {
        "kind": "mapping",
        "sha256": sha256_file(mapping),
        "reference": None,
    }
    _, _, index = _pipeline(plan, root, monkeypatch)
    entries = {e["policy"]: e for e in index["baselines"]}
    planning = entries["geometric"]["planning"]
    assert planning["planning_seed"] == 401 and planning["planner_settings_sha256"]
    assert planning["planning_seed_source"] is not None
    assert planning["mapping_file"]["sha256"] == sha256_file(mapping)
    assert planning["mapping_file"]["path"].startswith(f"main/{SCENE}/assets/mapping-")
    assert all(r["planning"] == planning for r in entries["geometric"]["evaluations"])
    assert (
        "planning" not in entries["hold"]
        and "planning" not in entries["hold"]["evaluations"][0]
    )
    ref = entries["geometric"]["evaluations"][0]
    assert ref["config"]["config_source"] == "run_config" and ref["config"][
        "path"
    ].startswith("main/")
    _check_paths(index, root)


def test_row_specific_inis_never_share_a_group(tmp_path, sim_binary, monkeypatch):
    plan, root = _edited_plan(tmp_path, sim_binary, _row_configs)
    _, _, index = _pipeline(plan, root, monkeypatch)
    refs = [
        r
        for m in index["models"]
        for r in m["evaluations"]
        if r["operation"] == "frozen-deterministic" and m["checkpoint"] == "final"
    ]
    assert len(refs) == 4 and len({r["config"]["sha256"] for r in refs}) == 4
    assert len({r["group"] for r in refs}) == 4
    assert all(
        r["config"]["config_source"] == "row"
        and r["config"]["path"].startswith("main/")
        for r in refs
    )
    hold = next(e for e in index["baselines"] if e["policy"] == "hold")["evaluations"]
    seed_201 = [r for r in hold if r["seed"] == 201]
    assert (
        len({r["config"]["sha256"] for r in seed_201})
        == len(seed_201)
        == len({r["group"] for r in seed_201})
    )
    _check_paths(index, root)


def test_index_keeps_assets_for_identical_inis_with_different_node_files(
    tmp_path, sim_binary
):
    inputs = tmp_path / "inputs"
    shutil.copytree(EXAMPLE, inputs)
    matrix_path = inputs / "batch.json"
    data = json.loads(matrix_path.read_text())
    seed_config_paths = {}
    for seed, offset in ((201, 1), (202, 2)):
        directory = inputs / f"seed-{seed}"
        directory.mkdir()
        for filename in ("run.ini", "buildings.json"):
            shutil.copyfile(inputs / filename, directory / filename)
        nodes = json.loads((inputs / "nodes.json").read_text())
        nodes[0]["position"]["x"] += offset
        (directory / "nodes.json").write_text(json.dumps(nodes))
        seed_config_paths[str(seed)] = f"seed-{seed}/run.ini"
    data["scenarios"][SCENE]["configs"] = {"diagnostic": seed_config_paths}
    matrix_path.write_text(json.dumps(data))
    root = tmp_path / "batch"
    plan = build_batch_plan(load_matrix_v2(matrix_path), root, sim_binary)

    reporting.run_report_task(_task(plan, f"index/{SCENE}"), plan, root, {})
    index = json.loads((root / "main" / SCENE / "mission_scenario.json").read_text())
    configs = index["assets"]["configs"]["diagnostic"]
    assert configs["201"]["nodes"]["path"] != configs["202"]["nodes"]["path"]
    for seed in ("201", "202"):
        record = configs[seed]["nodes"]
        expected = sha256_file(inputs / f"seed-{seed}/nodes.json")
        assert sha256_file(root / record["path"]) == record["sha256"] == expected
        leaves = [
            leaf
            for baseline in index["baselines"]
            for leaf in baseline["evaluations"]
            if leaf["seed"] == int(seed)
        ]
        assert leaves
        assert all(
            leaf["config"]["path"] == configs[seed]["run_config"]["path"]
            for leaf in leaves
        )
