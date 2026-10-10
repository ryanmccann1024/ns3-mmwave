"""Ownership, comparison recovery and writer exclusion with a fake scheduler."""

import json
import subprocess

import pytest

from scripts.rl.cluster import jobs, operations, receipts, reconcile, recovery, slurm, submission
from scripts.rl.tests.test_ops_cluster import (
    env, venv, _run, _complete, _tree, _CompareStub, _snapshot, _receipt,
)


def _finish(env):
    for index in range(8):
        _complete(env.root, index)
    for job_id in env.fake.job_ids():
        env.fake.set_job(job_id, "COMPLETED")


@pytest.mark.parametrize("command,extra", [
    ("plan", []), ("submit", []), ("resume", []),
    ("resume", ["--abandon-intent", "0001:tasks"]),
    ("resume", ["--inactive-job", "1000"]),
    ("cancel", ["--submission", "0001"]), ("compare", []),
    ("submit-compare", []),
])
def test_foreign_receipts_refuse_mutations_without_side_effects(env, capsys, command, extra):
    assert _run(env, "submit", "--tasks", "0") == 0
    path = receipts.path_for(env.root, "0001")
    entry = json.loads(path.read_text())
    entry["user"] = "another-cluster-user"
    entry.update(state="submit_uncertain", job_id=None)
    path.write_text(json.dumps(entry))
    before, scheduler = _tree(env.root), env.fake.read()
    assert _run(env, command, *extra) == 1
    assert "belongs to another-cluster-user" in capsys.readouterr().err
    assert _tree(env.root) == before
    assert env.fake.read() == scheduler


def test_account_identity_does_not_trust_user_environment(monkeypatch):
    before = receipts.user()
    monkeypatch.setenv("USER", "another-cluster-user")
    monkeypatch.setenv("LOGNAME", "another-cluster-user")
    assert receipts.user() == before


def test_status_queries_the_recorded_owner_without_writing(env, monkeypatch):
    assert _run(env, "submit", "--tasks", "0") == 0
    path = receipts.path_for(env.root, "0001")
    entry = json.loads(path.read_text())
    entry["user"] = "another-cluster-user"
    path.write_text(json.dumps(entry))
    seen = []
    monkeypatch.setattr(slurm, "snapshot", lambda ids, owner: seen.append(owner) or _snapshot())
    before = _tree(env.root)
    assert _run(env, "status", "--json") == 0
    assert seen == ["another-cluster-user"]
    assert _tree(env.root) == before


@pytest.mark.parametrize("command", ["resume", "submit-compare"])
def test_completed_tasks_need_only_one_compare_job(env, command):
    assert _run(env, "submit", "--no-compare") == 0
    _finish(env)
    before = len(env.fake.submissions())
    assert _run(env, command) == 0
    assert len(env.fake.submissions()) == before + 1
    entry = receipts.load(env.root)[-1]
    assert entry["receipt_version"] == 2 and entry["kind"] == "compare"
    assert entry["indices"] == [] and entry["job_id"] is None
    assert entry["state"] == "not_applicable"
    assert entry["compare"]["depends_on"] == []
    assert not any(arg.startswith(("--array=", "--dependency="))
                   for arg in env.fake.submissions()[-1])
    assert _run(env, command) == 0
    assert len(env.fake.submissions()) == before + 1


def test_compare_only_waits_for_every_active_array(env):
    assert _run(env, "submit", "--tasks", "0", "--no-compare") == 0
    assert _run(env, "submit", "--no-compare") == 0
    arrays = env.fake.job_ids()
    assert _run(env, "submit-compare") == 0
    entry = receipts.load(env.root)[-1]
    assert entry["compare"]["depends_on"] == arrays
    assert f"--dependency=afterany:{':'.join(arrays)}" in env.fake.submissions()[-1]


def test_compare_only_does_not_cover_unsubmitted_tasks(env, capsys):
    assert _run(env, "submit-compare") == 0
    assert env.fake.submissions() == []
    assert receipts.load(env.root) == []
    assert "neither finished nor covered" in capsys.readouterr().out


def test_lost_compare_response_is_recovered_without_another_job(env):
    assert _run(env, "submit", "--no-compare") == 0
    env.fake.die_after_queue(True)
    assert _run(env, "submit-compare") == 1
    env.fake.die_after_queue(False)
    entry = receipts.load(env.root)[-1]
    assert entry["compare"]["state"] == "submit_uncertain"
    before = len(env.fake.submissions())
    assert _run(env, "resume") == 0
    assert len(env.fake.submissions()) == before
    assert receipts.load(env.root)[-1]["compare"]["job_id"] == env.fake.last_job_id()


def test_refused_compare_submission_can_be_abandoned_and_replaced(env):
    assert _run(env, "submit", "--no-compare") == 0
    _finish(env)
    env.fake.fail("sbatch")
    assert _run(env, "submit-compare") == 1
    env.fake.fail("sbatch", False)
    before = len(env.fake.submissions())
    assert _run(env, "resume") == 1
    assert len(env.fake.submissions()) == before
    assert _run(env, "resume", "--abandon-intent", "0002:compare") == 0
    assert len(env.fake.submissions()) == before + 1
    assert receipts.load(env.root)[1]["compare"]["state"] == "abandoned"


@pytest.mark.parametrize("command,extra", [
    ("plan", []), ("submit", []), ("resume", []), ("submit-compare", []),
    ("cancel", ["--tasks", "0"]), ("compare", []),
])
def test_operation_lock_blocks_every_mutating_command(env, command, extra):
    lock = receipts.acquire_lock(env.root)
    try:
        before, scheduler = _tree(env.root), env.fake.read()
        assert _run(env, command, *extra) == 1
        assert _tree(env.root) == before
        assert env.fake.read() == scheduler
    finally:
        receipts.release_lock(lock)


def test_local_comparison_holds_lock_through_execution(env, monkeypatch):
    _finish(env)
    def stub(collected):
        def execute(step):
            assert receipts.layout(env.root)["lock"].is_file()
            assert _run(env, "submit-compare") == 1
            collected.append(0)
            return 0
        return execute
    monkeypatch.setattr(operations, "_compare_executor", stub)
    assert _run(env, "compare") == 0
    assert not receipts.layout(env.root)["lock"].exists()


def test_comparison_exception_releases_lock(env, monkeypatch):
    _finish(env)
    def fail(collected):
        def execute(step):
            raise OSError("fake process failed")
        return execute
    monkeypatch.setattr(operations, "_compare_executor", fail)
    assert _run(env, "compare") == 1
    assert not receipts.layout(env.root)["lock"].exists()


def test_scheduled_compare_ignores_only_its_own_job_and_writes_record(env, monkeypatch):
    assert _run(env, "submit") == 0
    _finish(env)
    job_id = env.fake.last_job_id()
    env.fake.set_job(job_id, "RUNNING")
    monkeypatch.setenv("SLURM_JOB_ID", job_id)
    stub = _CompareStub("complete", 0)
    monkeypatch.setattr(operations, "_compare_executor", stub)
    record = env.root / "cluster/records/0001/compare.json"
    assert _run(env, "compare", "--scheduled-job", job_id, "--record", str(record)) == 0
    assert stub.calls == 1 and record.is_file()


def test_scheduled_compare_refuses_unmatched_job(env, monkeypatch):
    monkeypatch.setenv("SLURM_JOB_ID", "9999")
    assert _run(env, "compare", "--scheduled-job", "9999") == 1
    monkeypatch.setenv("SLURM_JOB_ID", "9998")
    assert _run(env, "compare", "--scheduled-job", "9999") == 1


def test_cancellation_request_alone_does_not_clear_comparison_blocker():
    entry = _receipt(compare={"state": "submitted", "job_id": "1009"},
                     cancel_requests=[{"job_ids": ["1009"]}])
    assert reconcile.compare_blockers([entry], _snapshot())
    assert reconcile.compare_blockers([entry], _snapshot(
        accounting={"1009": {"state": "CANCELLED"}})) == []


def test_unrecognized_state_cannot_prove_termination():
    entry = _receipt(compare={"state": "submitted", "job_id": "1009"})
    assert reconcile.compare_blockers([entry], _snapshot(
        accounting={"1009": {"state": "NEW_UNKNOWN_STATE"}}))


def test_delayed_cancellation_refuses_a_second_comparison(env, monkeypatch):
    assert _run(env, "submit") == 0
    array, comparison = env.fake.job_ids()
    env.fake.set_job(array, "FAILED", exit_code="1:0")
    monkeypatch.setattr(slurm, "cancel", lambda ids: {"ok": True})
    before = len(env.fake.submissions())
    assert _run(env, "resume") == 1
    assert len(env.fake.submissions()) == before + 1
    assert env.fake.jobs()[comparison]["elements"][comparison]["state"] == "PENDING"


def test_compare_only_dry_run_touches_nothing(env):
    before, scheduler = _tree(env.root), env.fake.read()
    assert _run(env, "submit-compare", "--dry-run") == 0
    assert _tree(env.root) == before and env.fake.read() == scheduler


def test_version_one_receipt_with_owner_remains_readable(env):
    assert _run(env, "submit", "--tasks", "0") == 0
    path = receipts.path_for(env.root, "0001")
    entry = json.loads(path.read_text())
    entry["receipt_version"] = 1
    entry.pop("kind")
    path.write_text(json.dumps(entry))
    assert receipts.load(env.root)[0]["receipt_version"] == 1
    assert _run(env, "resume") == 0


def test_historical_recovery_passes_an_explicit_accounting_start(monkeypatch):
    calls = []
    def run(argv):
        calls.append(argv)
        return {"ok": True, "stdout": "", "stderr": ""}
    monkeypatch.setattr(slurm, "_run", run)
    slurm.find_jobs_by_name("meshops-old-compare", "owner", "2026-10-01")
    assert "--starttime=2026-10-01" in calls[1]
    assert "--user=owner" in calls[1]
    assert recovery._history_start({"created_at": "2026-10-02T00:05:00+00:00"}) == "2026-10-01"
    assert recovery._history_start({}) == "1970-01-01"


def test_recovery_and_abandonment_use_the_intent_history(env, monkeypatch):
    env.fake.die_after_queue(True)
    assert _run(env, "submit", "--tasks", "0") == 1
    path = receipts.path_for(env.root, "0001")
    entry = json.loads(path.read_text())
    entry["created_at"] = "2026-10-02T00:05:00+00:00"
    receipts.save(path, entry)
    seen = []
    def find(name, owner, start):
        seen.append((owner, start))
        return {"job_ids": [], "ok": True}
    monkeypatch.setattr(slurm, "find_jobs_by_name", find)
    recovery._recover_intents(env.root, receipts.load(env.root))
    recovery._abandon_intent(env.root, receipts.load(env.root), "0001:tasks")
    assert seen == [(receipts.user(), "2026-10-01")] * 2


def test_scheduled_compare_does_not_ignore_another_writer(env, monkeypatch):
    assert _run(env, "submit") == 0
    _finish(env)
    job_id = env.fake.last_job_id()
    other_job = env.fake.clone_job(job_id)
    for selected in (job_id, other_job):
        env.fake.set_job(selected, "RUNNING")
    entry = receipts.load(env.root)[0]
    entry["submission"] = "0002"
    entry["compare"]["job_id"] = other_job
    receipts.save(receipts.path_for(env.root, "0002"), entry)
    monkeypatch.setenv("SLURM_JOB_ID", job_id)
    stub = _CompareStub("complete", 0)
    monkeypatch.setattr(operations, "_compare_executor", stub)
    assert _run(env, "compare", "--scheduled-job", job_id) == 1
    assert stub.calls == 0


def test_changed_scheduler_coverage_refuses_compare_only(env, monkeypatch):
    assert _run(env, "submit", "--no-compare") == 0
    before = len(env.fake.submissions())
    original, calls = submission.get_snapshot, []
    def snapshot(entries):
        calls.append(1)
        return original(entries) if len(calls) < 3 else _snapshot(queue_ok=False, accounting_ok=False)
    monkeypatch.setattr(submission, "get_snapshot", snapshot)
    assert _run(env, "submit-compare") == 1
    assert len(env.fake.submissions()) == before


def test_compare_executor_uses_the_shared_process_owner(monkeypatch):
    collected = []
    monkeypatch.setattr(operations, "execute_step", lambda step: 2)
    assert operations._compare_executor(collected)({"kind": "compare"}) == 2
    assert collected == [2]


def test_rendered_scripts_are_valid_bash(env):
    from scripts.rl.cluster.config import load_cluster_config
    config = load_cluster_config(env.config)
    for render in (jobs.render_task_script, jobs.render_compare_script):
        script = render(config, env.tmp / "mesh with spaces", env.root, env.tmp / "records")
        result = subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
