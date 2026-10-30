"""Execute experiment tasks and comparisons and own their operational records."""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

from scripts.artifact_io import now_iso, sha256_file, write_json
from scripts.rl.ops import tasks
from scripts.rl.ops.process import execute_step as _subprocess_execute, managed_step
from scripts.sim_support import find_mesh_root

RECORD_VERSION = 1

_ALLOW = "pass --allow-incomplete to compare the finished evaluations anyway"


def _entry(step: dict, action: str, code: int | None = None) -> dict:
    return {"id": step["id"], "kind": step["kind"], "action": action,
            "exit_code": code,
            "tolerated": None if code is None else tasks.tolerated(step["kind"], code)}


def _write_record(record_path, mode: str, task: dict | None, steps: list[dict],
                  started_at: str, exit_code: int) -> None:
    if record_path is None:
        return
    path = Path(record_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {"record_version": RECORD_VERSION, "mode": mode,
                      "task_index": None if task is None else task["index"],
                      "task_id": None if task is None else task["id"],
                      "host": socket.gethostname(), "started_at": started_at,
                      "ended_at": now_iso(), "steps": steps, "exit_code": exit_code})


def run_task(output_root, task_index: int, record_path=None, execute=None) -> int:
    """Run one task's train then evaluate step; returns the process exit code."""
    execute = execute or _subprocess_execute
    started_at = now_iso()
    try:
        plan = tasks.load_plan(output_root)
        table = tasks.build_tasks(plan)
    except (ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if not 0 <= task_index < len(table):
        print(f"--task-index {task_index} is outside 0..{len(table) - 1}",
              file=sys.stderr)
        return 1

    task = table[task_index]
    states = tasks.task_fs_state(task)
    records, exit_code = [], 0
    for kind in ("train", "evaluate"):
        step = task[kind]
        state, detail = states[kind]
        if state != "pending":
            records.append(_entry(step, "skipped"))
            if state == "done":
                print(f"{step['id']}  skipped  already done")
                continue
            print(f"{step['id']}  {state}  {detail}".rstrip(), file=sys.stderr)
            exit_code = 1
            break
        code = execute(step)
        ok = tasks.tolerated(step["kind"], code)
        records.append(_entry(step, "executed", code))
        print(f"{step['id']}  exit {code}  {'tolerated' if ok else 'not tolerated'}")
        if not ok:
            exit_code = 1
            break

    _write_record(record_path, "task", task, records, started_at, exit_code)
    return exit_code


def run_compare(output_root, allow_incomplete: bool = False, record_path=None,
                execute=None) -> int:
    """Run the compare step; refuses unfinished evaluations unless allowed."""
    execute = execute or _subprocess_execute
    started_at = now_iso()
    try:
        plan = tasks.load_plan(output_root)
        step = tasks.compare_step(plan)
        prerequisites = tasks.compare_prerequisites(plan)
    except (ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if not prerequisites["ready"] and not allow_incomplete:
        for label in ("missing", "partial"):
            for step_id in prerequisites[label]:
                print(f"{label} evaluation: {step_id}", file=sys.stderr)
        print(f"no comparison was written; {_ALLOW}", file=sys.stderr)
        return 1

    code = execute(step)
    ok = tasks.tolerated(step["kind"], code)
    exit_code = 0 if ok else 1
    print(f"{step['id']}  exit {code}  {tasks.comparison_outcome(plan)['state']}")
    _write_record(record_path, "compare", None, [_entry(step, "executed", code)],
                  started_at, exit_code)
    return exit_code


def _plan_task(output_root, task_id: str) -> tuple[dict, dict]:
    from scripts.rl.experiments.plan import load_batch_plan
    plan = load_batch_plan(output_root)
    task = next((t for t in plan["tasks"] if t["id"] == task_id), None)
    if task is None:
        raise ValueError(f"no task {task_id!r} in the plan")
    return plan, task


def step_command(output_root, task_id: str, attempt: int) -> tuple[dict, dict, dict]:
    """(task, attempt record, launchable step) for one scheduled plan v3 attempt.

    The module comes from the allowlist and the arguments from the immutable
    plan (or the recorded recovery rewrite of them), with placeholders bound to
    the attempt the scheduler recorded in the task's receipt.
    """
    from scripts.rl.ops import recovery
    plan, task = _plan_task(output_root, task_id)
    module = tasks.step_module(task)
    receipt = recovery.read_receipt(output_root, task)
    record = recovery.attempt_record(receipt, attempt) if receipt else None
    if record is None or record.get("state") != "running":
        raise ValueError(f"{task_id} attempt {attempt} is not a running attempt in its receipt")
    inputs = record.get("inputs") or {}
    binding = None
    if inputs.get("binding"):
        path = Path(inputs["binding"]["path"])
        if sha256_file(path) != inputs["binding"]["sha256"]:
            raise ValueError(f"model binding {path} changed after the scheduler pinned it")
        binding = json.loads(path.read_text())
    resume = record.get("resume")
    if resume is not None and task["kind"] != "train":
        raise ValueError(f"{task_id}: only training attempts resume from a checkpoint")
    source = {**task, "args": resume["args"]} if resume else task
    if resume and resume["args"] != tasks.resume_train_args(
            task["args"], resume["parent_dir"], resume["checkpoint"]["relative"]):
        raise ValueError(f"{task_id}: recorded resume arguments do not follow from the plan")
    args = tasks.substitute_args(source, record["attempt_dir"], binding, inputs.get("accepted"),
                                 inputs.get("accepted_dirs"),
                                 inputs["binding"]["path"] if inputs.get("binding") else None)
    recorded = (plan.get("sim_binary") or {}).get("path")
    if record.get("sim_binary") and recorded:
        args = [record["sim_binary"] if a == recorded else a for a in args]
    return task, record, {"id": task_id, "kind": task["kind"], "module": module, "args": args}


def run_step(output_root, task_id: str, attempt: int, child_argv=None) -> int:
    """Worker for one plan v3 attempt; returns the child's raw exit code.

    Holds the shared pool slot (if any) while the child runs and passes the
    slot's lock descriptor to the child, so the slot stays held for as long as
    either process lives. Interruption stops and reaps the child group.
    """
    from scripts.rl.ops import local
    root = Path(output_root).resolve()
    task, record, step = step_command(root, task_id, attempt)
    argv = (child_argv or (lambda s: [sys.executable, "-m", s["module"], *s["args"]]))(step)
    pool = record.get("resource_pool")
    owner = {"root": str(root), "task_id": task_id, "attempt": attempt,
             "attempt_dir": record["attempt_dir"]}
    with local.pool_slot(pool, owner) as slot:
        keep = (slot.fileno(),) if slot is not None else ()

        def launch(_step):
            return subprocess.Popen(argv, cwd=str(find_mesh_root()), stdin=subprocess.DEVNULL,
                                    start_new_session=True, pass_fds=keep)

        def started(process):
            lease = local.lease_path(root, task, attempt)
            lease.parent.mkdir(parents=True, exist_ok=True)
            write_json(lease, {**owner, "worker_pid": os.getpid(), "child_pid": process.pid,
                               "child_pgid": process.pid, "started_at": now_iso()})
            local.record_slot_child(pool, slot, process.pid, record["attempt_dir"])

        print(f"{task_id} attempt {attempt}: {' '.join(argv)}", flush=True)
        with managed_step(step, launch=launch, on_start=started) as process:
            code = process.wait()
    print(f"{task_id} attempt {attempt}: exit {code}", flush=True)
    return code
