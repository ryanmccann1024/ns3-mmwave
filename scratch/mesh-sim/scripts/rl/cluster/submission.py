"""Submit task arrays and dependent comparisons under one operation lock."""

from pathlib import Path

from scripts.artifact_io import sha256_file
from scripts.rl.ops import tasks
from scripts.rl.cluster import receipts, reconcile, slurm, jobs
from scripts.sim_support import find_mesh_root

from scripts.rl.cluster.config import load_cluster_config
from scripts.rl.cluster.slurm import get_snapshot
from scripts.rl.cluster.plan import _plan_and_tasks, _validate, _write_task_table, _parse_indices
from scripts.rl.cluster.reporting import _print_rows, _preview
from scripts.rl.cluster.recovery import _recover_intents, _assert_inactive_job, _abandon_intent


def offline_snapshot(reason: str) -> dict:
    return {"queue": {"ok": False, "jobs": {}, "error": reason},
            "accounting": {"ok": False, "jobs": {}, "error": reason}}


def _select_submit(rows: list[dict], requested: list[int] | None) -> list[int]:
    ready = [row["index"] for row in rows if row["state"] == "unsubmitted"]
    if requested is None:
        return ready
    known = {row["index"]: row for row in rows}
    unknown = [index for index in requested if index not in known]
    if unknown:
        raise ValueError(f"--tasks names indices outside 0..{len(rows) - 1}: {unknown}")
    wrong = [f"{index} is {known[index]['state']}" for index in requested
             if index not in ready]
    if wrong:
        raise ValueError("submit only starts tasks in state unsubmitted: "
                      + "; ".join(wrong) + "\nuse resume for failed or canceled tasks")
    return sorted(set(requested))


def _submit_job(output_root, path, receipt: dict, role: str, argv: list[str]) -> str:
    try:
        result = slurm.submit(argv)
    except BaseException as exc:
        receipts.mark_uncertain(path, receipt, role, f"{type(exc).__name__}: {exc}")
        raise
    if not result["ok"] or not result["job_id"]:
        detail = (result["stderr"] or result["stdout"] or "no output").strip()
        receipts.mark_uncertain(path, receipt, role, detail)
        raise ValueError(f"sbatch for {role} did not return a job id "
                      f"(exit {result['returncode']}): {detail[:400]}\n"
                      f"submission {receipt['submission']} is left as a no-ID intent; "
                      "it is never retried automatically. Run resume to search for it "
                      f"by job name, or abandon it with --abandon-intent "
                      f"{receipt['submission']}:{role} once you confirm SLURM never "
                      "accepted it")
    receipts.finalize(path, receipt, role, result["job_id"])
    return result["job_id"]


def _submit_tasks(output_root, config: dict, plan_sha: str, config_sha: str,
                  indices: list[int]) -> tuple[dict, Path, str]:
    submission, path = receipts.allocate(output_root)
    paths = receipts.paths(output_root, submission)
    spec = jobs.array_spec(indices, config["max_concurrent_tasks"])
    name = jobs.job_name("tasks")
    argv = jobs.sbatch_argv(config, "tasks", name, paths["logs"] / "slurm-%A_%a.out",
                             paths["script_tasks"], array=spec)
    receipt = receipts.intent(submission, name, indices, spec, plan_sha, config,
                              config_sha, paths["script_tasks"], argv)
    receipts.save(path, receipt)

    root = Path(output_root).resolve()
    paths["script_tasks"].parent.mkdir(parents=True, exist_ok=True)
    paths["script_tasks"].write_text(
        jobs.render_task_script(config, find_mesh_root(), root, paths["records"]))
    paths["script_tasks"].chmod(0o755)
    paths["logs"].mkdir(parents=True, exist_ok=True)
    paths["records"].mkdir(parents=True, exist_ok=True)

    job_id = _submit_job(output_root, path, receipt, "tasks", argv)
    print(f"submission {submission}: job {job_id} array {spec} "
          f"({len(indices)} task{'s' if len(indices) != 1 else ''})")
    return receipt, path, job_id


def _clear_earlier_compare(output_root, entries: list[dict], snapshot: dict) -> None:
    for receipt in entries:
        job_id = reconcile.active_compare(receipt, snapshot)
        if not job_id:
            continue
        result = slurm.cancel([job_id])
        if not result["ok"]:
            raise ValueError(f"scancel {job_id} failed ({result['stderr'].strip()}); no "
                          "new compare job was submitted and no cancellation was "
                          "recorded")
        receipts.add_cancel_request(
            receipts.path_for(output_root, receipt["submission"]), receipt,
            {"job_ids": [job_id], "indices": [], "role": "compare",
             "reason": "superseded by a new compare job"})
        print(f"cancelled earlier compare job {job_id}")
    fresh = get_snapshot(entries)
    blockers = reconcile.compare_blockers(entries, fresh)
    if blockers:
        raise ValueError("another writer of comparison.json may still exist:\n"
                      + "\n".join(f"  {reason}" for reason in blockers))


def _submit_compare(output_root, config, entries, snapshot, rows, submitted,
                    receipt=None, path=None, plan_sha=None, config_sha=None):
    uncovered = reconcile.uncovered_for_compare(rows, submitted)
    if uncovered:
        print(f"no compare job was submitted: tasks {uncovered} are neither finished "
              "nor covered by an active job")
        return
    if receipt is not None:
        _clear_earlier_compare(output_root, entries, snapshot)
    else:
        blockers = reconcile.compare_blockers(entries, snapshot)
        if blockers:
            raise ValueError("another writer of comparison.json may still exist:\n"
                             + "\n".join(blockers))
    fresh = get_snapshot(entries)
    current_rows = reconcile.task_rows(_plan_and_tasks(output_root)[1], entries, fresh)
    uncovered = reconcile.uncovered_for_compare(current_rows, submitted)
    if uncovered:
        raise ValueError(f"task coverage changed during submission: {uncovered}; "
                         "no comparison was queued")
    depends = set(reconcile.active_job_ids(entries, fresh))
    if receipt is not None:
        depends.add(str(receipt["job_id"]))
    else:
        number, path = receipts.allocate(output_root)
        receipt = receipts.compare_receipt(number, plan_sha, config, config_sha)
    depends = sorted(depends)
    paths = receipts.paths(output_root, receipt["submission"])
    name = jobs.job_name("compare")
    argv = jobs.sbatch_argv(config, "compare", name,
                             paths["logs"] / "compare-%j.out", paths["script_compare"],
                             dependency="afterany:" + ":".join(depends) if depends else None)
    receipt["compare"] = receipts.compare_intent(name, argv, paths["script_compare"], depends)
    receipts.save(path, receipt)
    paths["script_compare"].parent.mkdir(parents=True, exist_ok=True)
    paths["logs"].mkdir(parents=True, exist_ok=True)
    paths["records"].mkdir(parents=True, exist_ok=True)
    paths["script_compare"].write_text(
        jobs.render_compare_script(config, find_mesh_root(),
                                   Path(output_root).resolve(), paths["records"]))
    paths["script_compare"].chmod(0o755)
    job_id = _submit_job(output_root, path, receipt, "compare", argv)
    print(f"submission {receipt['submission']}: compare job {job_id} "
          + (f"afterany:{':'.join(depends)}" if depends else "without dependencies"))


def _ensure_comparison(root, config, plan, entries, snapshot, rows, plan_sha, config_sha):
    if tasks.comparison_outcome(plan)["state"] == "complete":
        print("comparison is already complete")
        return
    if any(reconcile.active_compare(entry, snapshot) for entry in entries):
        print("comparison is already scheduled; no new job was submitted")
        return
    _submit_compare(root, config, entries, snapshot, rows, [],
                    plan_sha=plan_sha, config_sha=config_sha)


def _submit_flow(args, mode: str) -> int:
    config = load_cluster_config(args.cluster_config)
    plan, table = _plan_and_tasks(args.output_root)
    _validate(plan, table, args.output_root, config, need_sbatch=not args.dry_run)
    root = Path(args.output_root).resolve()
    requested = _parse_indices(getattr(args, "tasks", None))

    if args.dry_run:
        entries = receipts.load(root)
        receipts.require_owner(entries)
        offline = offline_snapshot("dry run: the scheduler was not queried")
        rows = reconcile.task_rows(table, entries, offline)
        indices = ([] if mode == "submit-compare" else
                   _select_submit(rows, requested) if mode == "submit" else
                   reconcile.resume_targets(table, rows, entries, offline)["eligible"])
        print("dry run: no lock, receipt, script, tasks.json, or scheduler call")
        _print_rows(rows)
        if not indices:
            if mode in ("resume", "submit-compare") and not getattr(args, "no_compare", False):
                _preview(config, root, [], with_compare=True)
                print("comparison preview only; scheduler coverage must be checked at submission")
                return 0
            print(f"{mode} would submit nothing")
            return 0
        _preview(config, root, indices,
                 with_compare=not getattr(args, "no_compare", False)
                 and not reconcile.uncovered_for_compare(rows, indices))
        return 0

    config_sha = sha256_file(args.cluster_config)
    with receipts.operation_lock(root) as entries:
        plan_sha = _write_task_table(root, table)
        entries = _recover_intents(root, entries)
        snapshot = get_snapshot(entries)
        for job_id in getattr(args, "inactive_job", None) or []:
            _assert_inactive_job(root, entries, snapshot, job_id)
        for token in getattr(args, "abandon_intent", None) or []:
            _abandon_intent(root, entries, token)
        entries = receipts.load(root)
        snapshot = get_snapshot(entries)
        rows = reconcile.task_rows(table, entries, snapshot)

        if mode == "submit":
            indices = _select_submit(rows, requested)
        elif mode == "submit-compare":
            indices = []
        else:
            targets = reconcile.resume_targets(table, rows, entries, snapshot)
            for blocked in targets["blocked"]:
                print(f"{blocked['index']:>4}  {blocked['id']}  not submitted: "
                      f"{blocked['detail']}")
            indices = targets["eligible"]
        if not indices:
            _print_rows(rows)
            print(f"nothing to {mode}")
            if mode in ("resume", "submit-compare") and not getattr(args, "no_compare", False):
                _ensure_comparison(root, config, plan, entries, snapshot, rows,
                                   plan_sha, config_sha)
            return 0

        receipt, path, _ = _submit_tasks(root, config, plan_sha, config_sha, indices)
        if getattr(args, "no_compare", False):
            print("--no-compare: no comparison job was submitted")
            return 0
        _submit_compare(root, config, entries, snapshot, rows, indices, receipt, path)
        return 0


def _cmd_submit(args):
    return _submit_flow(args, "submit")


def _cmd_resume(args):
    return _submit_flow(args, "resume")


def _cmd_submit_compare(args):
    return _submit_flow(args, "submit-compare")
