#!/usr/bin/env python3
"""CLI for cluster experiment operations."""

import argparse
import sys
from scripts.rl.cluster import operations, submission
from scripts.rl.ops.process import ProcessInterrupted


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run an experiment plan as SLURM array tasks plus one compare job")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, help_text, config=True):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--output-root", required=True,
                         help="Directory holding experiment_plan.json")
        if config:
            cmd.add_argument("--cluster-config", required=True,
                             help="Cluster JSON; see cluster-config.example.json")
        return cmd

    add("plan", "Validate, write cluster/tasks.json, and print the sbatch shape")
    submit = add("submit", "Submit tasks that were never submitted")
    submit.add_argument("--tasks", default=None,
                        help="Comma-separated task indices; omitted -> every "
                             "unsubmitted task")
    submit.add_argument("--no-compare", action="store_true",
                        help="Do not queue the dependent comparison job")
    submit.add_argument("--dry-run", action="store_true",
                        help="Print the argv and scripts; touch nothing")

    status = add("status", "Print every task's state", config=False)
    status.add_argument("--json", action="store_true", help="Machine-readable output")

    resume = add("resume", "Submit unsubmitted, failed, or canceled tasks with clean "
                           "step directories")
    resume.add_argument("--inactive-job", action="append", default=[], metavar="ID",
                        help="Assert that this known job id is no longer active")
    resume.add_argument("--abandon-intent", action="append", default=[],
                        metavar="NNNN:tasks|NNNN:compare",
                        help="Assert that this no-ID submission never reached SLURM")
    resume.add_argument("--no-compare", action="store_true",
                        help="Recover tasks without queuing comparison")
    resume.add_argument("--dry-run", action="store_true",
                        help="Print the argv and scripts; touch nothing")

    submit_compare = add("submit-compare", "Queue only comparison, after covered tasks")
    submit_compare.add_argument("--dry-run", action="store_true",
                                help="Preview comparison submission without writing")

    cancel = add("cancel", "Cancel active jobs recorded in the receipts", config=False)
    cancel.add_argument("--submission", default=None,
                        help="Receipt number: cancels its array and compare job")
    cancel.add_argument("--tasks", default=None,
                        help="Comma-separated task indices: cancels exact array elements")
    cancel.add_argument("--dry-run", action="store_true",
                        help="Print the scancel argv; cancel nothing")

    compare = add("compare", "Run the compare step on this host", config=False)
    compare.add_argument("--allow-incomplete", action="store_true",
                         help="Compare even when an evaluation is missing or partial")
    compare.add_argument("--record", default=None, help="Write an execution record")
    compare.add_argument("--scheduled-job", default=None, help=argparse.SUPPRESS)
    return p


_COMMANDS = {
    "plan": operations._cmd_plan,
    "submit": submission._cmd_submit,
    "status": operations._cmd_status,
    "resume": submission._cmd_resume,
    "cancel": operations._cmd_cancel,
    "compare": operations._cmd_compare,
    "submit-compare": submission._cmd_submit_compare,
}


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return _COMMANDS[args.command](args)
    except ProcessInterrupted as exc:
        print(f"Interrupted by {exc}", file=sys.stderr)
        return 128 + exc.signum
    except (ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
