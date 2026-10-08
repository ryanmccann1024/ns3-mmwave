"""Cluster CLI flows against fake_slurm: submission protocol, compare, cancel, refusals.

Expectations come from scripts/rl/ops/README.md "Cluster runs" and its
subsections. The scheduler is always scripts/rl/tests/fake_slurm.py.
"""

import json
import os
import textwrap

import pytest

from scripts.rl.ops import receipts, slurm

from ._ops_gen_helpers import (array_of, cluster_env, complete, flag, live_states,
                               read_receipt, run_cluster, tree)


@pytest.fixture
def env(tmp_path, monkeypatch):
    return cluster_env(tmp_path, monkeypatch, n_tasks=4)


def _lock(env):
    return env.root / "cluster" / "submit.lock"


def _receipt_files(env):
    directory = env.root / "cluster" / "receipts"
    return sorted(path.name for path in directory.glob("*.json")) \
        if directory.is_dir() else []


# --- submission protocol -----------------------------------------------------


def test_gen_the_intent_is_on_disk_and_the_lock_held_while_sbatch_runs(env,
                                                                       monkeypatch):
    seen = []
    original = slurm.submit

    def spy(argv):
        name = flag(argv, "job-name")
        stored = [json.loads(path.read_text())
                  for path in (env.root / "cluster" / "receipts").glob("*.json")]
        role = "compare" if name.endswith("-compare") else "tasks"
        holder = next(entry if role == "tasks" else entry["compare"]
                      for entry in stored
                      if (entry if role == "tasks" else entry.get("compare") or {})
                      .get("job_name") == name)
        seen.append({"role": role, "state": holder["state"],
                     "job_id": holder["job_id"], "locked": _lock(env).is_file(),
                     "script": os.path.isfile(argv[-1]),
                     "argv_recorded": holder["argv"] == argv})
        return original(argv)

    monkeypatch.setattr(slurm, "submit", spy)
    assert run_cluster(env, "submit") == 0
    assert [entry["role"] for entry in seen] == ["tasks", "compare"]
    for entry in seen:
        assert entry == {**entry, "state": "submitting", "job_id": None, "locked": True,
                         "script": True, "argv_recorded": True}
    assert not _lock(env).exists()


def test_gen_an_interrupted_sbatch_leaves_an_uncertain_intent_and_no_lock(env,
                                                                          monkeypatch):
    def interrupted(argv):
        raise KeyboardInterrupt

    monkeypatch.setattr(slurm, "submit", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_cluster(env, "submit", "--tasks", "0")
    stored = read_receipt(env, "0001")
    assert stored["state"] == "submit_uncertain" and stored["job_id"] is None
    assert "KeyboardInterrupt" in stored["error"]
    assert not _lock(env).exists()
    assert live_states(env)[0] == "unknown"


def test_gen_an_unparseable_sbatch_response_is_never_trusted(env, monkeypatch, capsys):
    odd = env.tmp / "odd-bin"
    odd.mkdir()
    sbatch = odd / "sbatch"
    sbatch.write_text("#!/bin/sh\necho 'Submitted batch job 77'\nexit 0\n")
    sbatch.chmod(0o755)
    monkeypatch.setenv("PATH", f"{odd}{os.pathsep}{os.environ['PATH']}")

    assert run_cluster(env, "submit", "--tasks", "0") == 1
    err = capsys.readouterr().err
    assert "did not return a job id" in err and "--abandon-intent 0001:tasks" in err
    stored = read_receipt(env, "0001")
    assert stored["state"] == "submit_uncertain"
    assert "Submitted batch job 77" in stored["error"]
    assert not _lock(env).exists()


@pytest.mark.parametrize("extra", [("--tasks", "9"), ("--tasks", "x"), ("--tasks", ",")])
def test_gen_the_lock_is_released_after_a_refused_selection(env, extra, capsys):
    assert run_cluster(env, "submit", *extra) == 1
    assert not _lock(env).exists()
    assert env.fake.submissions() == []
    assert _receipt_files(env) == []


def test_gen_a_held_lock_refuses_resume_but_not_a_dry_run(env, capsys):
    _lock(env).parent.mkdir(parents=True)
    _lock(env).write_text('{"pid": 99999, "host": "login9"}')
    assert run_cluster(env, "resume") == 1
    assert "login9" in capsys.readouterr().err
    assert run_cluster(env, "submit", "--dry-run") == 0
    assert run_cluster(env, "resume", "--dry-run") == 0
    assert _lock(env).read_text() == '{"pid": 99999, "host": "login9"}'
    assert env.fake.submissions() == []


def test_gen_dry_runs_and_plan_never_query_the_scheduler(env, monkeypatch, capsys):
    assert run_cluster(env, "submit", "--tasks", "0,1") == 0
    capsys.readouterr()

    def forbidden(argv):
        raise AssertionError(f"scheduler queried: {argv}")

    monkeypatch.setattr(slurm, "_run", forbidden)
    assert run_cluster(env, "submit", "--dry-run") == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if "row-0" in line]
    assert "unknown" in lines[0] and "unknown" in lines[1]
    assert "unsubmitted" in lines[2]
    assert "--array=2-3" in out
    assert run_cluster(env, "resume", "--dry-run") == 0
    assert run_cluster(env, "plan") == 0


def test_gen_too_many_tasks_for_the_site_array_limit_are_refused(tmp_path,
                                                                 monkeypatch, capsys):
    env = cluster_env(tmp_path, monkeypatch, n_tasks=4, max_array_size=3)
    assert run_cluster(env, "plan") == 1
    assert "exceed max_array_size 3" in capsys.readouterr().err
    assert run_cluster(env, "submit") == 1
    assert env.fake.submissions() == [] and _receipt_files(env) == []
    assert not _lock(env).exists()


def test_gen_a_missing_sbatch_refuses_a_real_submit_but_not_a_dry_run(env, monkeypatch,
                                                                     capsys):
    monkeypatch.setenv("PATH", str(env.tmp / "nowhere"))
    assert run_cluster(env, "submit") == 1
    assert "sbatch is not on PATH" in capsys.readouterr().err
    assert run_cluster(env, "submit", "--dry-run") == 0
    assert not (env.root / "cluster" / "receipts").exists()


@pytest.mark.parametrize("problem", ["relative binary", "missing run_config"])
def test_gen_plan_validation_refuses_unusable_inputs(env, problem, capsys):
    plan_path = env.root / "experiment_plan.json"
    plan = json.loads(plan_path.read_text())
    if problem == "relative binary":
        plan["sim_binary"] = "build/mesh-sim"
        message = "not an absolute path"
    else:
        plan["rows"][1]["run_config"] = str(env.tmp / "gone.ini")
        message = "row row-01: run_config"
    plan_path.write_text(json.dumps(plan))
    assert run_cluster(env, "submit") == 1
    assert message in capsys.readouterr().err
    assert env.fake.submissions() == []


def test_gen_a_corrupt_receipt_blocks_status_and_submission(env, capsys):
    assert run_cluster(env, "submit", "--tasks", "0") == 0
    (env.root / "cluster" / "receipts" / "0002.json").write_text("")
    before = len(env.fake.submissions())
    capsys.readouterr()
    assert run_cluster(env, "status") == 1
    assert "0002.json" in capsys.readouterr().err
    assert run_cluster(env, "resume") == 1
    assert len(env.fake.submissions()) == before
    assert not _lock(env).exists()


# --- compare job -------------------------------------------------------------


def test_gen_the_compare_job_waits_on_every_active_array(env):
    assert run_cluster(env, "submit", "--tasks", "0") == 0
    first = env.fake.last_job_id()
    assert run_cluster(env, "submit") == 0
    second = env.fake.job_ids()[1]
    compare_argv = env.fake.submissions()[-1]
    assert flag(compare_argv, "dependency") == f"afterany:{first}:{second}"
    assert array_of(compare_argv) is None
    stored = read_receipt(env, "0002")
    assert stored["compare"]["depends_on"] == [first, second]
    assert stored["compare"]["state"] == "submitted"


def test_gen_an_earlier_active_compare_is_cancelled_before_a_new_one(env):
    assert run_cluster(env, "submit") == 0
    array, old_compare = env.fake.job_ids()
    env.fake.set_element(array, 2, "TIMEOUT", exit_code="0:1")

    assert run_cluster(env, "resume") == 0
    assert env.fake.scancel_calls() == [[old_compare]]
    first = read_receipt(env, "0001")
    assert [request["job_ids"] for request in first["cancel_requests"]] \
        == [[old_compare]]
    assert first["cancel_requests"][0]["role"] == "compare"
    second = read_receipt(env, "0002")
    assert second["indices"] == [2] and second["array_spec"] == "2"
    assert second["compare"]["depends_on"] == sorted([array, second["job_id"]])


def test_gen_a_failed_scancel_of_the_earlier_compare_refuses_the_new_one(env, capsys):
    assert run_cluster(env, "submit") == 0
    array, _ = env.fake.job_ids()
    env.fake.set_element(array, 2, "TIMEOUT", exit_code="0:1")
    env.fake.fail("scancel")

    assert run_cluster(env, "resume") == 1
    assert "no new compare job was submitted" in capsys.readouterr().err
    assert read_receipt(env, "0001")["cancel_requests"] == []
    second = read_receipt(env, "0002")
    assert second["state"] == "submitted" and second["compare"] is None
    assert len(env.fake.submissions()) == 3
    assert not _lock(env).exists()


def test_gen_a_lost_compare_submission_is_not_requeued_by_a_later_resume(env,
                                                                         monkeypatch,
                                                                         capsys):
    original = slurm.submit

    def compare_fails(argv):
        if flag(argv, "job-name").endswith("-compare"):
            return {"ok": False, "stdout": "", "stderr": "socket timed out",
                    "returncode": 1, "argv": argv, "job_id": None}
        return original(argv)

    monkeypatch.setattr(slurm, "submit", compare_fails)
    assert run_cluster(env, "submit") == 1
    stored = read_receipt(env, "0001")
    assert stored["state"] == "submitted"
    assert stored["compare"]["state"] == "submit_uncertain"
    monkeypatch.setattr(slurm, "submit", original)

    before = len(env.fake.submissions())
    assert run_cluster(env, "resume") == 0
    assert "nothing to resume" in capsys.readouterr().out
    assert len(env.fake.submissions()) == before
    assert _receipt_files(env) == ["0001.json"]


def test_gen_accounting_alone_still_covers_a_canary_when_the_queue_is_down(env):
    # A PENDING accounting row is a positive active observation, so the canary is
    # covered and the compare job waits on both arrays.
    assert run_cluster(env, "submit", "--tasks", "0") == 0
    first = env.fake.last_job_id()
    env.fake.fail("squeue")
    assert run_cluster(env, "resume") == 0
    second = read_receipt(env, "0002")
    assert second["indices"] == [1, 2, 3]
    assert second["compare"]["depends_on"] == [first, second["job_id"]]


def test_gen_a_canary_with_no_scheduler_view_never_queues_compare(env, capsys):
    assert run_cluster(env, "submit", "--tasks", "0") == 0
    env.fake.fail("squeue")
    env.fake.fail("sacct")
    capsys.readouterr()

    assert run_cluster(env, "resume") == 0
    out = capsys.readouterr().out
    second = read_receipt(env, "0002")
    assert second["indices"] == [1, 2, 3] and second["compare"] is None
    assert "no compare job was submitted" in out
    assert len(env.fake.submissions()) == 2


# --- reconciled states through the fake --------------------------------------


def test_gen_a_requeued_element_is_pending_and_never_resubmitted(env):
    assert run_cluster(env, "submit", "--no-compare") == 0
    array = env.fake.last_job_id()
    env.fake.set_element(array, 1, "REQUEUED")
    assert live_states(env)[1] == "pending"
    assert run_cluster(env, "resume") == 0
    assert len(env.fake.submissions()) == 1


@pytest.mark.parametrize("state", ["NODE_FAIL", "OUT_OF_MEMORY", "PREEMPTED",
                                   "TIMEOUT"])
def test_gen_a_terminal_failure_is_resubmitted_alone(env, state):
    assert run_cluster(env, "submit", "--no-compare") == 0
    array = env.fake.last_job_id()
    env.fake.set_job(array, "COMPLETED")
    for index in (0, 2, 3):
        complete(env.root, index)
    env.fake.set_element(array, 1, state, exit_code="0:9")
    assert live_states(env)[1] == "failed"

    assert run_cluster(env, "resume") == 0
    assert array_of(env.fake.submissions()[1]) == "1"
    assert flag(env.fake.submissions()[2], "dependency") \
        == f"afterany:{env.fake.job_ids()[1]}"


def test_gen_a_vanished_element_without_accounting_is_never_resubmitted(env):
    assert run_cluster(env, "submit", "--no-compare") == 0
    array = env.fake.last_job_id()
    env.fake.fail("sacct")
    env.fake.drop_element(array, 1)
    assert live_states(env)[1] == "unknown"
    assert run_cluster(env, "resume") == 0
    assert len(env.fake.submissions()) == 1


def test_gen_status_shows_the_scheduler_start_estimate_for_queued_rows(env, capsys):
    assert run_cluster(env, "submit", "--no-compare") == 0
    array = env.fake.last_job_id()
    env.fake.set_element(array, 0, "PENDING", reason="Resources",
                         start="2026-05-01T12:00:00")
    env.fake.set_element(array, 1, "RUNNING", start="2026-04-30T08:00:00")
    capsys.readouterr()
    assert run_cluster(env, "status") == 0
    out = capsys.readouterr().out
    assert out.count("scheduler-estimated start:") == 1
    assert "scheduler-estimated start: 2026-05-01T12:00:00 (may change)" in out


def test_gen_status_json_has_a_compare_row(env, capsys):
    assert run_cluster(env, "submit") == 0
    capsys.readouterr()
    assert run_cluster(env, "status", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    compare = payload["compare"]
    assert compare["state"] == "pending" and compare["job_id"] == env.fake.job_ids()[1]
    assert compare["outcome"] == "absent" and compare["receipt"] == "0001"


# --- human assertions --------------------------------------------------------


def test_gen_an_inactive_assertion_for_an_unknown_job_is_refused(env, capsys):
    assert run_cluster(env, "submit", "--no-compare") == 0
    before = tree(env.root / "cluster" / "receipts")
    assert run_cluster(env, "resume", "--inactive-job", "4242") == 1
    assert "no receipt holds that job id" in capsys.readouterr().err
    assert tree(env.root / "cluster" / "receipts") == before


@pytest.mark.parametrize("token,message", [
    ("0001", "expected NNNN:tasks or NNNN:compare"),
    ("0001:array", "expected NNNN:tasks or NNNN:compare"),
    ("0009:tasks", "no receipt 0009"),
    ("0001:tasks", "not an unresolved no-ID intent"),
    ("0001:compare", "not an unresolved no-ID intent")])
def test_gen_malformed_or_inapplicable_abandon_tokens_are_refused(env, token, message,
                                                                  capsys):
    assert run_cluster(env, "submit", "--no-compare") == 0
    before = tree(env.root / "cluster" / "receipts")
    assert run_cluster(env, "resume", "--abandon-intent", token) == 1
    assert message in capsys.readouterr().err
    assert tree(env.root / "cluster" / "receipts") == before


def test_gen_abandoning_while_the_scheduler_is_unreachable_records_that_fact(env):
    env.fake.fail("sbatch")
    assert run_cluster(env, "submit", "--tasks", "0") == 1
    env.fake.fail("sbatch", False)
    env.fake.fail("squeue")
    env.fake.fail("sacct")
    assert run_cluster(env, "resume", "--abandon-intent", "0001:tasks") == 0
    stored = read_receipt(env, "0001")
    assert stored["state"] == "abandoned"
    assert stored["human_assertions"][0]["queried"] is False


# --- cancellation ------------------------------------------------------------


def test_gen_cancel_never_confuses_task_1_with_task_11(tmp_path, monkeypatch):
    env = cluster_env(tmp_path, monkeypatch, n_tasks=12)
    assert run_cluster(env, "submit", "--no-compare") == 0
    array = env.fake.last_job_id()
    assert run_cluster(env, "cancel", "--tasks", "1") == 0
    assert env.fake.scancel_calls() == [[f"{array}_1"]]
    states = live_states(env)
    assert states[1] == "canceled" and states[11] == "pending" and states[10] == "pending"


def test_gen_cancel_picks_the_active_element_from_the_right_receipt(env):
    assert run_cluster(env, "submit") == 0
    array, _ = env.fake.job_ids()
    env.fake.set_element(array, 2, "TIMEOUT", exit_code="0:1")
    assert run_cluster(env, "resume") == 0
    resubmitted = read_receipt(env, "0002")["job_id"]

    assert run_cluster(env, "cancel", "--tasks", "2") == 0
    assert env.fake.scancel_calls()[-1] == [f"{resubmitted}_2"]
    request = read_receipt(env, "0002")["cancel_requests"][-1]
    assert request["job_ids"] == [f"{resubmitted}_2"] and request["indices"] == [2]
    assert request["selector"] == "--tasks 2"
    assert request["user"] and request["requested_at"]
    assert all(f"{array}_2" not in entry["job_ids"]
               for entry in read_receipt(env, "0001")["cancel_requests"])


def test_gen_cancel_by_submission_with_nothing_active_records_nothing(env, capsys):
    assert run_cluster(env, "submit") == 0
    array, compare = env.fake.job_ids()
    env.fake.set_job(array, "COMPLETED")
    env.fake.set_job(compare, "COMPLETED")
    assert run_cluster(env, "cancel", "--submission", "0001") == 0
    assert "no active job" in capsys.readouterr().out
    assert env.fake.scancel_calls() == []
    assert read_receipt(env, "0001")["cancel_requests"] == []


@pytest.mark.parametrize("extra,message", [
    (("--submission", "0009"), "no receipt 0009"),
    (("--tasks", "4"), "outside the plan"),
    (("--tasks", "-1"), "outside the plan"),
    (("--tasks", "1-3"), "comma-separated"),
    (("--tasks", ""), "at least one")])
def test_gen_bad_cancel_selections_are_refused_without_scancel(env, extra, message,
                                                               capsys):
    assert run_cluster(env, "submit") == 0
    capsys.readouterr()
    assert run_cluster(env, "cancel", *extra) == 1
    assert message in capsys.readouterr().err
    assert env.fake.scancel_calls() == []


def test_gen_a_cancel_dry_run_prints_exact_element_ids(env, capsys):
    assert run_cluster(env, "submit", "--no-compare") == 0
    array = env.fake.last_job_id()
    capsys.readouterr()
    assert run_cluster(env, "cancel", "--tasks", "3,1", "--dry-run") == 0
    assert f"dry run: scancel {array}_1 {array}_3" in capsys.readouterr().out
    assert env.fake.scancel_calls() == []
    assert read_receipt(env, "0001")["cancel_requests"] == []


def test_gen_cancel_does_not_need_the_submit_lock(env):
    # README does not put cancel under cluster/submit.lock; this pins that a held
    # lock neither blocks a cancel nor is touched by it. See report (QUESTION).
    assert run_cluster(env, "submit", "--no-compare") == 0
    _lock(env).write_text('{"pid": 1}')
    assert run_cluster(env, "cancel", "--tasks", "0") == 0
    assert _lock(env).read_text() == '{"pid": 1}'


def test_gen_the_fake_scheduler_is_the_only_one_reachable(env):
    # Guard for this module: every scheduler command resolves to the fake shims.
    for command in ("sbatch", "squeue", "sacct", "scancel"):
        path = os.popen(f"command -v {command}").read().strip()
        assert path == str(env.fake.bin / command), textwrap.shorten(path, 80)


def test_gen_a_non_object_comparison_json_reads_unknown_in_status(env, capsys):
    # `status` renders a non-object comparison.json instead of crashing.
    (env.root / "comparison").mkdir()
    (env.root / "comparison" / "comparison.json").write_text("[]")
    assert run_cluster(env, "status", "--json") == 0
    assert json.loads(capsys.readouterr().out)["compare"]["state"] == "unknown"
