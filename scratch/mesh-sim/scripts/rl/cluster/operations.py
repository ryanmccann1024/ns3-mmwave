"""Plan, report, cancel and run local comparisons for cluster experiments."""

import json
from pathlib import Path
import sys

from scripts.rl.ops import tasks, task_execution
from scripts.rl.cluster import receipts, reconcile, slurm

from scripts.rl.cluster.config import load_cluster_config
from scripts.rl.cluster.plan import _plan_and_tasks, _validate, _write_task_table, _parse_indices
from scripts.rl.cluster.reporting import _print_rows, _preview
from scripts.rl.cluster.slurm import get_snapshot
from scripts.rl.ops.process import execute_step

STATUS_VERSION = 2
_OUTCOME_LINES = {("complete", 0): "complete",
                  ("complete", 2): "complete with health counters or seed overlap",
                  ("incomplete", 1): "incomplete"}


def _cmd_plan(args) -> int:
    config = load_cluster_config(args.cluster_config)
    plan, table = _plan_and_tasks(args.output_root)
    _validate(plan, table, args.output_root, config, need_sbatch=False)
    root = Path(args.output_root).resolve()
    with receipts.operation_lock(root):
        _write_task_table(root, table)
    for task in table:
        print(f"{task['index']:>4}  {task['id']:<40}  {task['train']['id']} -> "
              f"{task['evaluate']['id']}")
    _preview(config, root, [task["index"] for task in table], with_compare=True)
    return 0


def _cmd_status(args) -> int:
    plan, table = _plan_and_tasks(args.output_root)
    entries = receipts.load(args.output_root)
    snapshot = get_snapshot(entries)
    rows = reconcile.task_rows(table, entries, snapshot)
    compare = reconcile.compare_row(plan, entries, snapshot)
    scheduler = {"queue_ok": snapshot["queue"]["ok"],
                 "accounting_ok": snapshot["accounting"]["ok"],
                 "queue_error": snapshot["queue"].get("error", ""),
                 "accounting_error": snapshot["accounting"].get("error", "")}
    if args.json:
        json.dump({"status_version": STATUS_VERSION,
                   "output_root": str(Path(args.output_root).resolve()),
                   "scheduler": scheduler, "tasks": rows, "compare": compare},
                  sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    _print_rows(rows, compare)
    for name, key in (("queue", "queue"), ("accounting", "accounting")):
        if not snapshot[key]["ok"]:
            print(f"scheduler {name} unavailable: "
                  f"{snapshot[key].get('error') or 'query failed'}; states that depend "
                  "on it are reported as unknown")
    return 0


def _cancel_locked(args, entries) -> int:
    table = _plan_and_tasks(args.output_root)[1]
    if (args.submission is None) == (args.tasks is None):
        raise ValueError("pass exactly one of --submission or --tasks")
    snapshot = get_snapshot(entries)
    if not snapshot["queue"]["ok"]:
        raise ValueError("the scheduler queue is unavailable "
                      f"({snapshot['queue'].get('error') or 'query failed'}), so active "
                      "job elements cannot be resolved; nothing was cancelled and "
                      "nothing was recorded")
    targets: dict[str, list[str]] = {}
    indices: dict[str, list[int]] = {}

    if args.submission is not None:
        receipt = next((entry for entry in entries
                        if entry["submission"] == args.submission), None)
        if receipt is None:
            raise ValueError(f"no receipt {args.submission}")
        elements = reconcile.active_elements(receipt, snapshot)
        compare_job = reconcile.active_compare(receipt, snapshot)
        targets[receipt["submission"]] = elements + ([compare_job] if compare_job else [])
        indices[receipt["submission"]] = [int(element.rsplit("_", 1)[1])
                                          for element in elements]
    else:
        wanted = _parse_indices(args.tasks)
        known = {task["index"] for task in table}
        unknown = [index for index in wanted if index not in known]
        if unknown:
            raise ValueError(f"--tasks names indices outside the plan: {unknown}")
        for receipt in entries:
            elements = [element for element in reconcile.active_elements(receipt, snapshot)
                        if int(element.rsplit("_", 1)[1]) in wanted]
            if elements:
                targets[receipt["submission"]] = elements
                indices[receipt["submission"]] = [int(element.rsplit("_", 1)[1])
                                                  for element in elements]

    flat = [element for elements in targets.values() for element in elements]
    if not flat:
        print("no active job from these receipts matches the selection")
        return 0
    if args.dry_run:
        print("dry run: " + " ".join(["scancel", *flat]))
        return 0
    result = slurm.cancel(flat)
    if not result["ok"]:
        print(f"scancel failed (exit {result['returncode']}): "
              f"{result['stderr'].strip()}\nno cancellation was recorded",
              file=sys.stderr)
        return 1
    for submission, elements in targets.items():
        receipt = next(entry for entry in entries
                       if entry["submission"] == submission)
        receipts.add_cancel_request(
            receipts.path_for(args.output_root, submission), receipt,
            {"job_ids": elements, "indices": indices.get(submission, []),
             "selector": f"--submission {args.submission}" if args.submission
                         else f"--tasks {args.tasks}"})
        print(f"cancelled {' '.join(elements)}")
    return 0


def _cmd_cancel(args):
    if args.dry_run:
        entries = receipts.load(args.output_root)
        receipts.require_owner(entries)
        return _cancel_locked(args, entries)
    with receipts.operation_lock(args.output_root) as entries:
        return _cancel_locked(args, entries)


def _compare_executor(collected: list[int]):
    def execute(step: dict) -> int:
        code = execute_step(step)
        collected.append(code)
        return code
    return execute


def _compare_locked(args, entries) -> int:
    plan, table = _plan_and_tasks(args.output_root)
    snapshot = get_snapshot(entries)
    scheduled = getattr(args, "scheduled_job", None)
    other_entries = entries
    if scheduled:
        matched = [entry for entry in entries
                   if str((entry.get("compare") or {}).get("job_id")) == scheduled]
        if len(matched) != 1:
            raise ValueError(f"scheduled compare job {scheduled} has no unique receipt")
        other_entries = [entry for entry in entries if entry is not matched[0]]
    blockers = reconcile.compare_blockers(other_entries, snapshot)
    if blockers:
        print("refusing to run compare here; a scheduled comparison may write the "
              "same files:", file=sys.stderr)
        for reason in blockers:
            print(f"  {reason}", file=sys.stderr)
        return 1
    if args.allow_incomplete:
        busy = [row for row in reconcile.task_rows(table, entries, snapshot)
                if row["state"] in ("pending", "running", "unknown")]
        if busy:
            print("--allow-incomplete needs every task to be settled first:",
                  file=sys.stderr)
            for row in busy:
                print(f"  {row['index']} {row['id']} {row['state']}", file=sys.stderr)
            return 1

    raw: list[int] = []
    code = task_execution.run_compare(
        args.output_root, args.allow_incomplete, getattr(args, "record", None),
        _compare_executor(raw))
    if not raw:
        return code
    outcome = tasks.comparison_outcome(plan)["state"]
    line = _OUTCOME_LINES.get((outcome, raw[0]), f"{outcome} (exit {raw[0]})")
    print(f"{line}; raw exit code: {raw[0]}")
    return code


def _cmd_compare(args):
    scheduled = getattr(args, "scheduled_job", None)
    if scheduled:
        import os
        if scheduled != os.environ.get("SLURM_JOB_ID"):
            raise ValueError("--scheduled-job must match this SLURM_JOB_ID")
    with receipts.operation_lock(args.output_root, wait_s=30 if scheduled else 0) as entries:
        if scheduled:
            from scripts.rl.cluster.recovery import _recover_intents
            entries = _recover_intents(args.output_root, entries)
        return _compare_locked(args, entries)
