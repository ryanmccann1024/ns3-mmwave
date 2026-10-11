#!/usr/bin/env python3
"""Plan, run, or report the status of an explicit experiment matrix."""

import argparse
import sys

from scripts.rl.cli_common import automatic_output_root
from scripts.rl.policy.experiment import (PLAN_NAME, automatic_run_label, build_plan, load_matrix, load_plan,
                                          parse_rows, print_states, run_plan,
                                          step_state, write_plan)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Expand and run an RL experiment matrix")
    sub = p.add_subparsers(dest="command", required=True)
    for name, help_text in (("plan", "Write experiment_plan.json"),
                            ("run", "Write the plan, then run its pending steps")):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--matrix", required=True, help="Matrix JSON file")
        cmd.add_argument("--output-root", default=None,
                         help="Directory holding the plan, runs, and comparison")
        cmd.add_argument("--sim-binary", required=True, help="Path to mesh-sim executable")
        cmd.add_argument("--rows", default=None,
                         help="Comma-separated row names; omitted -> every row")
    status = sub.add_parser("status", help="Print the state of every planned step")
    status.add_argument("--output-root", required=True)
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "status":
            plan = load_plan(args.output_root)
        else:
            matrix = load_matrix(args.matrix)
            if args.output_root is None:
                args.output_root = str(automatic_output_root(automatic_run_label(matrix, parse_rows(args.rows))))
                print(f"Experiment output: {args.output_root}", flush=True)
            plan = build_plan(matrix, args.output_root, args.sim_binary,
                              parse_rows(args.rows))
            write_plan(plan, args.output_root)
    except (ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.command == "run":
        return run_plan(plan)
    print_states({step["id"]: step_state(step) for step in plan["steps"]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
