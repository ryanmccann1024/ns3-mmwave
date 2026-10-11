"""Real rsync against disposable local trees; no SSH, scheduler, or simulator."""

import json
import shutil
from pathlib import Path

import pytest

from scripts.rl.cli_common import write_json
from scripts.rl.ops import fetch, retrieval
from scripts.rl.tests.test_ops_fetch import _plan

pytestmark = pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")

# Real output paths, independent of retrieval's include patterns. Keep the payloads tiny.
LEAF = "row-a/train-seed-1"
TRAIN = f"train/{LEAF}"
EVAL = f"eval/{LEAF}"
EPISODE = f"{EVAL}/model/episode-0000"
BASELINE = f"{EVAL}/channel/baseline"
ALWAYS = {"experiment_plan.json", "cluster/tasks.json", "cluster/receipts/submit.json"}
ARTIFACTS = {
    "manifests": {f"{TRAIN}/train_manifest.json", f"{EVAL}/eval_manifest.json",
                  f"{EPISODE}/rl_episode.json", f"{EPISODE}/policy_decisions_manifest.json",
                  f"{BASELINE}/baseline_manifest.json", f"{BASELINE}/effective-inputs/baseline-plan.json"},
    "models": {f"{TRAIN}/maskable_ppo_mesh.zip", f"{TRAIN}/best_model.zip",
               f"{TRAIN}/checkpoints/checkpoint_16_steps.zip"},
    "inputs": {f"{EPISODE}/inputs/run.ini", f"{BASELINE}/source-inputs/run.ini",
               f"{BASELINE}/effective-inputs/nodes.json", f"{BASELINE}/effective-inputs/baseline-plan.json"},
    "decision-records": {f"{EPISODE}/policy_decisions.jsonl"},
    "telemetry": {f"{EPISODE}/steps.jsonl"},
    "selection-logs": {f"{TRAIN}/evaluations.npz"},
    "comparison": {"comparison/comparison.json", "comparison/episodes.csv"},
    "logs": {"cluster/logs/job.out"},
}


def _fixture(source: Path):
    source.mkdir()
    for relative in ALWAYS | set.union(*ARTIFACTS.values()):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("tiny artifact fixture\n")
    write_json(source / "experiment_plan.json", _plan(source))
    write_json(source / f"{TRAIN}/train_manifest.json", {"status": "completed"})
    write_json(source / f"{EVAL}/eval_manifest.json", {"status": "completed"})
    write_json(source / "comparison/comparison.json", {"status": "complete"})
    (source / "unselected.txt").write_text("do not copy")
    return source


def _run(source, dest, select=None, update=False):
    args = ["--remote", str(source), "--dest", str(dest)]
    if select is not None:
        args += ["--select", select]
    if update:
        args += ["--update"]
    return fetch.main(args)


def _copied(dest):
    return {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()
            and not p.name.startswith("fetch_manifest")}


@pytest.mark.parametrize("category", [None, *ARTIFACTS])
def test_real_rsync_selects_only_requested_artifacts(tmp_path, category):
    source = _fixture(tmp_path / "source")
    dest = tmp_path / "dest"
    assert _run(source, dest, category) == 0
    expected = ALWAYS | (ARTIFACTS[category] if category else set())
    assert _copied(dest) == expected
    for relative in expected:
        assert (dest / relative).read_bytes() == (source / relative).read_bytes()


def test_real_update_preserves_old_files_and_new_destination_refreshes(tmp_path, capsys):
    source = _fixture(tmp_path / "source")
    train_manifest = f"{TRAIN}/train_manifest.json"
    eval_manifest = f"{EVAL}/eval_manifest.json"
    write_json(source / train_manifest, {"status": "running"})
    write_json(source / eval_manifest, {"status": "running"})
    dest = tmp_path / "first"
    selection = "manifests,decision-records"
    assert _run(source, dest, selection) == 0
    first = json.loads((dest / retrieval.FETCH_MANIFEST_NAME).read_text())
    assert first["tasks"][0]["state"] == "running"
    original = {name: (dest / name).read_bytes() for name in _copied(dest)}
    write_json(source / train_manifest, {"status": "completed"})
    write_json(source / eval_manifest, {"status": "completed"})
    (source / f"{EPISODE}/policy_decisions.jsonl").write_text("remote grew\n")
    new_episode = f"{EVAL}/hold/episode-0001/rl_episode.json"
    (source / new_episode).parent.mkdir(parents=True)
    write_json(source / new_episode, {"status": "completed"})
    assert _run(source, dest, selection, update=True) == 0
    assert all((dest / name).read_bytes() == data for name, data in original.items())
    assert (dest / new_episode).exists()
    updated = json.loads((dest / retrieval.FETCH_MANIFEST_NAME).read_text())
    assert updated["transfer_mode"] == "add_missing" and updated["files_may_be_stale"] is True
    assert updated["inventory_scope"] == "destination"
    assert updated["tasks"][0]["state"] == "running"
    assert json.loads((dest / "fetch_manifest.1.json").read_text()) == first
    assert "new --dest" in capsys.readouterr().err
    fresh = tmp_path / "finished"
    assert _run(source, fresh, selection) == 0
    assert (fresh / train_manifest).read_bytes() == (source / train_manifest).read_bytes()
    assert (fresh / f"{EPISODE}/policy_decisions.jsonl").read_bytes() != original[f"{EPISODE}/policy_decisions.jsonl"]
    assert json.loads((fresh / retrieval.FETCH_MANIFEST_NAME).read_text())["files_may_be_stale"] is False
    assert json.loads((fresh / retrieval.FETCH_MANIFEST_NAME).read_text())["tasks"][0]["state"] == "completed"


def test_real_episode_data_includes_decisions_but_not_sibling_baseline_tree(tmp_path):
    source = _fixture(tmp_path / "source")
    dest = tmp_path / "dest"
    assert _run(source, dest, "episode-data") == 0
    episode_files = {name for names in ARTIFACTS.values() for name in names
                     if name.startswith(f"{EPISODE}/")}
    assert _copied(dest) == ALWAYS | episode_files


def test_real_failed_transfer_writes_no_fetch_manifest(tmp_path):
    dest = tmp_path / "dest"
    assert _run(tmp_path / "missing-source", dest, "manifests") == 1
    assert not (dest / retrieval.FETCH_MANIFEST_NAME).exists()


@pytest.mark.parametrize("payload", [[], None, "invalid", {"status": "unknown"}])
def test_unrecognized_manifest_is_incomplete(tmp_path, payload):
    source = _fixture(tmp_path / "source")
    write_json(source / f"{TRAIN}/train_manifest.json", payload)
    write_json(source / f"{EVAL}/eval_manifest.json", payload)
    dest = tmp_path / "dest"
    assert _run(source, dest, "manifests") == 0
    manifest = json.loads((dest / retrieval.FETCH_MANIFEST_NAME).read_text())
    assert manifest["tasks"][0]["state"] == "incomplete"


@pytest.mark.parametrize("payload", [[], None, "invalid", True])
def test_non_object_comparison_is_unreadable(tmp_path, payload):
    source = _fixture(tmp_path / "source")
    write_json(source / "comparison/comparison.json", payload)
    dest = tmp_path / "dest"
    assert _run(source, dest, "comparison") == 0
    manifest = json.loads((dest / retrieval.FETCH_MANIFEST_NAME).read_text())
    assert manifest["comparison"] == "unreadable"
    assert "comparison/comparison.json" in {entry["path"] for entry in manifest["files"]}


@pytest.mark.parametrize("case", ["non_object", "bad_step", "missing_id", "outside_root", "parent_escape"])
def test_uninspectable_plan_still_publishes_inventory(tmp_path, case):
    source = _fixture(tmp_path / "source")
    plan = _plan(source)
    if case == "non_object":
        plan = []
    elif case == "bad_step":
        plan["steps"] = [1]
    elif case == "missing_id":
        del plan["steps"][0]["id"]
    elif case == "outside_root":
        plan["steps"][0]["output_dir"] = str(tmp_path / "outside")
    elif case == "parent_escape":
        plan["steps"][0]["output_dir"] = str(source / "../outside")
    write_json(source / "experiment_plan.json", plan)
    dest = tmp_path / "dest"
    assert _run(source, dest, "manifests,comparison") == 0
    manifest = json.loads((dest / retrieval.FETCH_MANIFEST_NAME).read_text())
    assert manifest["tasks"] == [] and manifest["snapshot_of_incomplete_run"] is None
    assert manifest["comparison"] == "complete"
    assert "experiment_plan.json" in {entry["path"] for entry in manifest["files"]}
