"""Execute experiment tasks and comparisons and own their operational records."""

import socket
import sys
from pathlib import Path

from scripts.artifact_io import now_iso, write_json
from scripts.rl.ops import tasks
from scripts.rl.ops.process import execute_step as _subprocess_execute

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


