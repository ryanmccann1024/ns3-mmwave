#!/usr/bin/env python3
"""CLI for measuring an experiment task or estimating a matrix."""

import argparse
import sys
from scripts.rl.ops.measurement import (DEFAULT_INTERVAL_S, EPISODE_MANIFEST, PsError,
                                      parse_ps, tree_usage, measure_step,
                                      effective_timesteps, run_benchmark)
from scripts.rl.ops.estimation import format_hms, build_estimate, run_estimate

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Benchmark one experiment array task and estimate another matrix")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Measure one task's steps with a ps sampler")
    run.add_argument("--output-root", required=True,
                     help="Directory holding experiment_plan.json")
    run.add_argument("--task-index", type=int, required=True,
                     help="0-based position among the plan's train steps")
    run.add_argument("--sample-interval-s", type=float, default=DEFAULT_INTERVAL_S,
                     help="Seconds between ps samples")

    estimate = sub.add_parser("estimate",
                              help="Scale a benchmark onto another matrix; runs nothing")
    estimate.add_argument("--benchmark", required=True, help="benchmark/task-NNNN.json")
    estimate.add_argument("--target-matrix", required=True, help="Matrix JSON file")
    estimate.add_argument("--safety-factor", type=float, required=True,
                          help="Multiplier applied to measured seconds and memory")
    estimate.add_argument("--output", required=True, help="Estimate JSON to write")
    return p


def _dispatch(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "run":
        return run_benchmark(args.output_root, args.task_index, args.sample_interval_s)
    return run_estimate(args.benchmark, args.target_matrix, args.safety_factor,
                        args.output)


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
