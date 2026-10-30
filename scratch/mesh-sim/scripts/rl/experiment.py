#!/usr/bin/env python3
"""Validate, plan, run, report and resume an explicit experiment matrix.

Matrix version 1 keeps its sequential plan-v2 behavior. Matrix version 2
batches produce an immutable plan v3 whose execution, status and recovery are
delegated to the local scheduler (`scripts.rl.ops.local`, `scripts.rl.ops.recovery`).
"""

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

from scripts.rl.cli_common import automatic_output_root
from scripts.rl.experiments.config import (FAILURE_POLICIES, MATRIX_V2_VERSION, load_matrix_v2,
                                           read_matrix_version, resolve_execution)
from scripts.rl.experiments.plan import (EXPERIMENT_PLAN_VERSION, build_batch_plan,
                                         check_binary_fresh, describe_expansion, load_batch_plan,
                                         read_plan_version, write_batch_plan)
from scripts.rl.policy.experiment import (MATRIX_VERSION, PLAN_NAME, PLAN_VERSION,
                                          automatic_run_label, build_plan, load_matrix, load_plan,
                                          parse_rows, print_states, run_plan, step_state,
                                          write_plan)

BINARY_ENV = "MESH_SIM_BIN"
_EXECUTION_FLAGS = ("workers", "threads_per_worker", "failure_policy", "nice")

__all__ = ["main", "PLAN_NAME", "load_matrix", "build_plan", "load_plan", "write_plan",
           "run_plan", "step_state", "print_states", "parse_rows", "automatic_run_label"]


def _add_execution(cmd) -> None:
    group = cmd.add_argument_group("execution (CLI > matrix > defaults)")
    group.add_argument("--workers", type=int, default=None, help="Concurrent tasks; default 1")
    group.add_argument("--threads-per-worker", type=int, default=None,
                       help="Numerical threads per task; default 1")
    group.add_argument("--failure-policy", choices=list(FAILURE_POLICIES), default=None,
                       help="continue (default) finishes independent tasks; stop dispatches no more")
    group.add_argument("--nice", type=int, default=None, help="Child niceness 0-19; default 0")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Validate, plan, run, report and resume an RL experiment matrix",
        epilog=f"--sim-binary falls back to ${BINARY_ENV}. Paths resolve against the current "
               "directory. Exit codes: 0 ok, 1 error, 2 usage error (including a missing "
               "v1 binary argument); run passes through the scheduler's code.")
    sub = p.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="Check a matrix and print its expansion; writes nothing")
    validate.add_argument("--matrix", required=True, help="Matrix JSON file")
    validate.add_argument("--rows", default=None, help="Comma-separated row names")
    for name, help_text in (("plan", "Write the immutable experiment_plan.json"),
                            ("run", "Write the plan, then run its pending work")):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--matrix", required=True, help="Matrix JSON file")
        cmd.add_argument("--output-root", default=None,
                         help="Directory holding the plan and results; omitted -> outputs/<date>/...")
        cmd.add_argument("--sim-binary", default=None,
                         help=f"Existing simulator executable; omitted -> ${BINARY_ENV}")
        cmd.add_argument("--rows", default=None,
                         help="Comma-separated row names; omitted -> every row")
        if name == "run":
            _add_execution(cmd)
    status = sub.add_parser("status", help="Report the state of every planned task")
    status.add_argument("--output-root", required=True)
    status.add_argument("--json", action="store_true", help="Print machine-readable status")
    resume = sub.add_parser("resume", help="Recover an interrupted plan-v3 batch")
    resume.add_argument("--output-root", required=True)
    resume.add_argument("--sim-binary", default=None,
                        help="Same binary identity at a different path; omitted -> recorded binary")
    resume.add_argument("--prepare-only", action="store_true",
                        help="Write the recovery proposal and launch nothing")
    _add_execution(resume)
    return p


def _binary(args) -> str:
    raw = args.sim_binary or os.environ.get(BINARY_ENV)
    if not raw:
        raise ValueError(f"no simulator binary: pass --sim-binary or set {BINARY_ENV}")
    return raw


def _execution_overrides(args) -> dict:
    return {key: getattr(args, key, None) for key in _EXECUTION_FLAGS}


def _scheduler(name: str):
    """Import a scheduler entry point lazily; a missing owner is a clear error."""
    module = "scripts.rl.ops.local" if name != "prepare_resume" else "scripts.rl.ops.recovery"
    try:
        # import_module honours sys.modules (including None entries), unlike a
        # package-attribute import once the submodule has been loaded elsewhere.
        return getattr(importlib.import_module(module), name)
    except (ImportError, AttributeError) as exc:
        raise ImportError(f"batch execution is not available: {module}.{name} "
                          f"could not be imported ({exc})") from exc


def _v1(args) -> int:
    rows = parse_rows(args.rows)
    matrix = load_matrix(args.matrix)
    if args.command == "validate":
        plan = build_plan(matrix, "<output-root>", "<sim-binary>", rows)
        print(f"matrix {matrix['name']} (version {MATRIX_VERSION}): {len(plan['steps'])} steps")
        for step in plan["steps"]:
            print(f"  {step['id']}")
        return 0
    if any(value is not None for value in _execution_overrides(args).values()):
        raise ValueError("execution flags apply to matrix version 2 batches; "
                         "a version 1 plan runs sequentially")
    if not (args.sim_binary or os.environ.get(BINARY_ENV)):
        _build_parser().error(f"no simulator binary: pass --sim-binary or set {BINARY_ENV}")
    binary = _binary(args)
    if args.output_root is None:
        args.output_root = str(automatic_output_root(automatic_run_label(matrix, rows)))
        print(f"Experiment output: {args.output_root}", flush=True)
    plan = build_plan(matrix, args.output_root, binary, rows)
    write_plan(plan, args.output_root)
    if args.command == "run":
        return run_plan(plan)
    print_states({step["id"]: step_state(step) for step in plan["steps"]})
    return 0


def _v2(args) -> int:
    rows = parse_rows(args.rows)
    matrix = load_matrix_v2(args.matrix, rows)
    if args.command == "validate":
        plan = build_batch_plan(matrix)
        for line in describe_expansion(plan):
            print(line)
        return 0
    run_batch = _scheduler("run_batch") if args.command == "run" else None
    binary = _binary(args)
    execution = resolve_execution(matrix["execution"], _execution_overrides(args))
    if args.output_root is None:
        label = matrix["name"] if rows is None or len(rows) != 1 else f"{matrix['name']}-{rows[0]}"
        args.output_root = str(automatic_output_root(label))
        print(f"Experiment output: {args.output_root}", flush=True)
    plan = build_batch_plan(matrix, args.output_root, binary)
    check_binary_fresh(plan["sim_binary"]["path"])
    path = write_batch_plan(plan, args.output_root)
    print(f"Plan: {path} ({len(plan['tasks'])} tasks)", flush=True)
    if run_batch is None:
        return 0
    return int(run_batch(str(Path(args.output_root).resolve()), execution))


def _status(args) -> int:
    version = read_plan_version(args.output_root)
    if version == EXPERIMENT_PLAN_VERSION:
        status = _scheduler("batch_status")(str(Path(args.output_root).resolve()))
        if args.json:
            print(json.dumps(status, indent=2, sort_keys=True))
        else:
            print(f"Batch {status.get('state', 'unknown')}")
            for state, count in sorted((status.get("counts") or {}).items()):
                print(f"  {state}  {count}")
        return 0
    plan = load_plan(args.output_root)
    states = {step["id"]: step_state(step) for step in plan["steps"]}
    if args.json:
        print(json.dumps({"experiment_plan_version": PLAN_VERSION,
                          "steps": {sid: {"state": s, "detail": d} for sid, (s, d) in states.items()}},
                         indent=2))
    else:
        print_states(states)
    return 0


def _resume(args) -> int:
    version = read_plan_version(args.output_root)
    if version != EXPERIMENT_PLAN_VERSION:
        raise ValueError(f"resume needs an experiment plan version {EXPERIMENT_PLAN_VERSION} in "
                         f"{args.output_root}; a legacy plan keeps its 'move or delete <dir> to "
                         "retry' refusal")
    plan = load_batch_plan(args.output_root)
    prepare_resume = _scheduler("prepare_resume")
    execution = resolve_execution(plan["execution_declared"], _execution_overrides(args))
    binary = str(Path(args.sim_binary).expanduser().resolve()) if args.sim_binary else None
    return int(prepare_resume(str(Path(args.output_root).resolve()), binary, execution,
                              args.prepare_only))


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "status":
            return _status(args)
        if args.command == "resume":
            return _resume(args)
        version = read_matrix_version(args.matrix)
        if version == MATRIX_VERSION:
            return _v1(args)
        if version == MATRIX_V2_VERSION:
            return _v2(args)
        raise ValueError(f"matrix_version must be {MATRIX_VERSION} or {MATRIX_V2_VERSION}, "
                         f"got {version!r}")
    except (ValueError, OSError, ImportError, RuntimeError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
