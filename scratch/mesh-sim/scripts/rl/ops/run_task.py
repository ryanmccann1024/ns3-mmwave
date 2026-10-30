#!/usr/bin/env python3
"""CLI for one experiment task or comparison, or one scheduled plan v3 step."""

import argparse
import sys
from scripts.rl.ops.task_execution import run_task, run_compare, run_step

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run one experiment array task, or the plan's compare step")
    p.add_argument("--output-root", required=True,
                   help="Directory holding experiment_plan.json")
    p.add_argument("--task-index", type=int, default=None,
                   help="0-based position among the plan's train steps")
    p.add_argument("--compare", action="store_true",
                   help="Run the compare step instead of a task")
    p.add_argument("--allow-incomplete", action="store_true",
                   help="Compare even when an evaluation is missing or partial")
    p.add_argument("--record", default=None,
                   help="Write a JSON record of this run to PATH")
    p.add_argument("--step", default=None,
                   help="Plan v3: run one scheduled task attempt (used by the batch scheduler)")
    p.add_argument("--attempt", type=int, default=None,
                   help="Plan v3: the attempt number recorded in the task's receipt")
    return p


def _dispatch(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    if args.step is not None or args.attempt is not None:
        if args.step is None or args.attempt is None or args.compare or args.task_index is not None \
                or args.allow_incomplete or args.record:
            print("--step needs --attempt and no legacy option", file=sys.stderr)
            return 1
        return run_step(args.output_root, args.step, args.attempt)
    if args.compare == (args.task_index is not None):
        print("pass exactly one of --task-index or --compare", file=sys.stderr)
        return 1
    if args.allow_incomplete and not args.compare:
        print("--allow-incomplete applies to --compare only", file=sys.stderr)
        return 1
    if args.compare:
        return run_compare(args.output_root, args.allow_incomplete, args.record)
    return run_task(args.output_root, args.task_index, args.record)


def main(argv=None) -> int:
    from scripts.rl.ops.process import ProcessInterrupted
    try:
        return _dispatch(argv)
    except ProcessInterrupted as exc:
        print(f"Interrupted by {exc}", file=sys.stderr)
        return 128 + exc.signum
    except (ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
