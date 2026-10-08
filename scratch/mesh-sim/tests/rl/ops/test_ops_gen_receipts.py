"""Receipt bookkeeping: lock and allocation contention, corrupt files, state transitions.

Expectations come from scripts/rl/ops/README.md "Receipts and the submission
protocol" and "Layout under the output root".
"""

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from scripts.rl.ops import receipts
from scripts.sim_support import find_mesh_root

N_PROCS = 8


def _race(tmp_path: Path, body: str) -> list[str]:
    """Start N processes that wait on a go-file, then run `body`; return stdout lines."""
    go = tmp_path / "go"
    script = tmp_path / "racer.py"
    script.write_text(textwrap.dedent(f"""\
        import sys, time
        from pathlib import Path
        sys.path.insert(0, {str(find_mesh_root())!r})
        from scripts.rl.ops import receipts
        go = Path({str(go)!r})
        while not go.exists():
            time.sleep(0.001)
        root = Path({str(tmp_path / "run")!r})
        """) + textwrap.dedent(body))
    procs = [subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
             for _ in range(N_PROCS)]
    time.sleep(0.3)
    go.write_text("go")
    outputs = []
    for proc in procs:
        out, err = proc.communicate(timeout=60)
        assert proc.returncode == 0, err
        outputs.append(out.strip())
    return outputs


def test_gen_exactly_one_of_many_concurrent_submitters_gets_the_lock(tmp_path):
    outputs = _race(tmp_path, """\
        try:
            receipts.acquire_lock(root)
            print("acquired")
        except ValueError as exc:
            print("refused" if "Remove it by hand" in str(exc) else f"odd {exc}")
        """)
    assert sorted(outputs) == ["acquired"] + ["refused"] * (N_PROCS - 1)
    holder = json.loads((tmp_path / "run" / "cluster" / "submit.lock").read_text())
    assert set(holder) == {"pid", "host", "created_at"}


def test_gen_concurrent_allocations_never_share_a_number(tmp_path):
    outputs = _race(tmp_path, """\
        submission, path = receipts.allocate(root)
        print(submission)
        """)
    assert sorted(outputs) == [f"{n:04d}" for n in range(1, N_PROCS + 1)]


def test_gen_a_held_lock_names_its_holder_and_is_left_in_place(tmp_path):
    lock = receipts.acquire_lock(tmp_path)
    before = lock.read_text()
    holder = json.loads(before)
    assert holder["pid"] == os.getpid()
    with pytest.raises(ValueError) as caught:
        receipts.acquire_lock(tmp_path)
    assert str(holder["pid"]) in str(caught.value)
    assert holder["host"] in str(caught.value)
    assert lock.read_text() == before
    receipts.release_lock(lock)
    receipts.release_lock(lock)
    assert not lock.exists()
    receipts.release_lock(receipts.acquire_lock(tmp_path))


def test_gen_an_unreadable_lock_still_refuses(tmp_path):
    (tmp_path / "cluster" / "submit.lock").mkdir(parents=True)
    with pytest.raises(ValueError, match="unreadable"):
        receipts.acquire_lock(tmp_path)


def test_gen_layout_is_absolute_and_under_cluster(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = receipts.layout("run")
    assert paths["cluster"] == (tmp_path / "run" / "cluster").resolve()
    assert paths["lock"].name == "submit.lock" and paths["table"].name == "tasks.json"
    for key in ("receipts", "scripts", "logs", "records"):
        assert paths[key].parent == paths["cluster"]


# --- loading -----------------------------------------------------------------


def _receipts_dir(tmp_path: Path) -> Path:
    path = receipts.layout(tmp_path)["receipts"]
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_gen_no_receipt_directory_means_no_receipts(tmp_path):
    assert receipts.load(tmp_path) == []


def test_gen_load_orders_by_submission_and_ignores_temp_and_foreign_files(tmp_path):
    directory = _receipts_dir(tmp_path)
    for number in ("0003", "0001", "0002"):
        (directory / f"{number}.json").write_text(json.dumps({"submission": number}))
    (directory / "0004.json.tmp").write_text("{half")
    (directory / "notes.txt").write_text("hello")
    assert [entry["submission"] for entry in receipts.load(tmp_path)] \
        == ["0001", "0002", "0003"]


@pytest.mark.parametrize("text", ["", "{\"submission\": \"0001\"", "not json"],
                         ids=["allocated but never written", "truncated", "garbage"])
def test_gen_a_corrupt_receipt_is_a_refusal_naming_the_file(tmp_path, text):
    path = _receipts_dir(tmp_path) / "0001.json"
    path.write_text(text)
    with pytest.raises(ValueError, match=f"unreadable receipt {path}"):
        receipts.load(tmp_path)


# --- allocation --------------------------------------------------------------


def test_gen_allocate_reserves_the_file_before_anything_is_written(tmp_path):
    submission, path = receipts.allocate(tmp_path)
    assert submission == "0001" and path.is_file() and path.read_text() == ""
    assert receipts.allocate(tmp_path)[0] == "0002"


def test_gen_allocate_refuses_past_the_submission_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(receipts, "MAX_SUBMISSIONS", 2)
    receipts.allocate(tmp_path)
    receipts.allocate(tmp_path)
    with pytest.raises(ValueError, match="more than 2 submissions"):
        receipts.allocate(tmp_path)


# --- receipt bodies and transitions ------------------------------------------


def _intent(tmp_path: Path) -> tuple[dict, Path]:
    submission, path = receipts.allocate(tmp_path)
    body = receipts.intent(submission, "meshops-" + "0" * 32 + "-tasks", [0, 1],
                           "0-1", "planhash", {"name": "site"}, "cfghash",
                           Path("/s/0001-tasks.sh"), ["sbatch", "x"])
    receipts.save(path, body)
    return body, path


def test_gen_an_intent_has_exactly_the_documented_fields(tmp_path):
    body, path = _intent(tmp_path)
    assert set(body) == {"receipt_version", "submission", "state", "created_at",
                         "host", "user", "job_name", "indices", "array_spec",
                         "plan_sha256", "cluster_config", "cluster_config_sha256",
                         "script", "argv", "job_id", "compare", "cancel_requests",
                         "human_assertions"}
    assert body["state"] == "submitting" and body["job_id"] is None
    assert body["compare"] is None and body["script"] == "/s/0001-tasks.sh"
    assert json.loads(path.read_text()) == body
    assert not list(path.parent.glob("*.tmp"))


def test_gen_a_compare_intent_has_exactly_the_documented_fields():
    element = receipts.compare_intent("meshops-x-compare", ["sbatch"], "/s/c.sh",
                                      ["1000"])
    assert set(element) == {"job_name", "job_id", "state", "created_at", "script",
                            "argv", "depends_on"}
    assert element["state"] == "submitting" and element["job_id"] is None


def test_gen_finalize_and_recover_mark_the_submission_accepted(tmp_path):
    body, path = _intent(tmp_path)
    receipts.finalize(path, body, "tasks", "1000")
    stored = json.loads(path.read_text())
    assert stored["state"] == "submitted" and stored["job_id"] == "1000"
    assert stored["submitted_at"]

    body["compare"] = receipts.compare_intent("meshops-x-compare", [], "/c.sh", [])
    receipts.mark_recovered(path, body, "compare", "1001")
    stored = json.loads(path.read_text())
    assert stored["compare"]["state"] == "submitted"
    assert stored["compare"]["job_id"] == "1001" and stored["compare"]["recovered_at"]
    assert stored["state"] == "submitted" and stored["job_id"] == "1000"


def test_gen_an_uncertain_submission_keeps_only_the_tail_of_the_error(tmp_path):
    body, path = _intent(tmp_path)
    detail = "H" * 500 + "T" * 2000
    receipts.mark_uncertain(path, body, "tasks", detail)
    stored = json.loads(path.read_text())
    assert stored["state"] == "submit_uncertain" and stored["job_id"] is None
    assert stored["error"] == "T" * 2000 and stored["uncertain_at"]


def test_gen_abandoning_the_compare_role_leaves_the_tasks_role_alone(tmp_path):
    body, path = _intent(tmp_path)
    receipts.finalize(path, body, "tasks", "1000")
    body["compare"] = receipts.compare_intent("meshops-x-compare", [], "/c.sh", [])
    receipts.mark_abandoned(path, body, "compare")
    stored = json.loads(path.read_text())
    assert stored["compare"]["state"] == "abandoned"
    assert stored["state"] == "submitted"


@pytest.mark.parametrize("call", [
    lambda path, body: receipts.finalize(path, body, "compare", "1"),
    lambda path, body: receipts.mark_uncertain(path, body, "compare", "x"),
    lambda path, body: receipts.mark_abandoned(path, body, "array")])
def test_gen_a_missing_compare_element_or_unknown_role_is_refused(tmp_path, call):
    body, path = _intent(tmp_path)
    before = path.read_text()
    with pytest.raises(ValueError):
        call(path, body)
    assert path.read_text() == before


def test_gen_assertions_and_cancellations_are_stamped_and_persisted(tmp_path):
    body, path = _intent(tmp_path)
    entry = receipts.add_assertion(path, body, {"kind": "inactive_job",
                                                "job_id": "1000"})
    assert entry["user"] == receipts.user() and entry["asserted_at"]
    cancel = receipts.add_cancel_request(path, body, {"job_ids": ["1000_1"],
                                                      "indices": [1]})
    assert cancel["user"] and cancel["requested_at"]
    stored = json.loads(path.read_text())
    assert stored["human_assertions"] == [entry]
    assert stored["cancel_requests"] == [cancel]


def test_gen_job_ids_collects_both_roles_once():
    entries = [{"submission": "0001", "job_id": "1000",
                "compare": {"job_id": "1001"}},
               {"submission": "0002", "job_id": None, "compare": None},
               {"submission": "0003", "job_id": "1000", "compare": {"job_id": None}},
               {"submission": "0004", "job_id": 1002}]
    assert receipts.job_ids(entries) == ["1000", "1001", "1002"]


# --- task table --------------------------------------------------------------


def _table() -> list[dict]:
    return [{"index": 0, "id": "r/train-seed-1", "train": {"id": "train/r/train-seed-1"},
             "evaluate": {"id": "evaluate/r/train-seed-1"}}]


def test_gen_the_task_table_is_written_once_and_left_untouched_when_equal(tmp_path):
    payload = receipts.task_table("abc", _table())
    assert payload == {"tasks_version": 1, "plan_sha256": "abc",
                       "tasks": [{"index": 0, "id": "r/train-seed-1",
                                  "train_id": "train/r/train-seed-1",
                                  "evaluate_id": "evaluate/r/train-seed-1"}]}
    path = receipts.write_task_table(tmp_path, payload)
    stamp = path.stat().st_mtime_ns
    os.utime(path, ns=(stamp - 10**9, stamp - 10**9))
    stamp = path.stat().st_mtime_ns
    assert receipts.write_task_table(tmp_path, payload) == path
    assert path.stat().st_mtime_ns == stamp


@pytest.mark.parametrize("existing", ['{"tasks_version": 1, "plan_sha256": "zzz", '
                                      '"tasks": []}', "{broken"])
def test_gen_a_differing_or_corrupt_task_table_is_never_overwritten(tmp_path,
                                                                     existing):
    path = receipts.layout(tmp_path)["table"]
    path.parent.mkdir(parents=True)
    path.write_text(existing)
    with pytest.raises(ValueError):
        receipts.write_task_table(tmp_path, receipts.task_table("abc", _table()))
    assert path.read_text() == existing
