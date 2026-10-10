#!/usr/bin/env python3
"""CLI for configured tuning and explicit study recovery."""

import argparse
import os
import sys
from pathlib import Path

from scripts.rl.ops.process import ProcessInterrupted
from scripts.rl.tuning import driver
from scripts.rl.tuning.config import N_STARTUP_TRIALS, load_study
from scripts.rl.tuning.study import PIN_NAME, load_optuna, read_tuning_pin
from scripts.rl.tuning.trainer import build_trial


def _build_parser():
    parser = argparse.ArgumentParser(description="Tune one matrix row with a supported trainer")
    parser.add_argument("--study", required=True, help="Study spec JSON file")
    parser.add_argument("--output-root", required=True, help="Study records and recovery checkpoint")
    parser.add_argument("--sim-binary", required=True, help="Path to mesh-sim executable")
    parser.add_argument("--dry-run", action="store_true", help="Preview startup candidates; create nothing")
    parser.add_argument("--resume", action="store_true", help="Continue this study's persisted state")
    return parser


def main(argv=None, sampler=None, execute=None):
    args = _build_parser().parse_args(argv)
    try:
        if args.resume and args.dry_run:
            raise ValueError("--resume and --dry-run cannot be combined")
        spec = load_study(args.study)
        binary = Path(args.sim_binary).expanduser().resolve()
        if not args.dry_run and not (binary.is_file() and os.access(binary, os.X_OK)):
            raise ValueError(f"--sim-binary {binary} is not an executable file")
        if args.dry_run:
            return driver.dry_run(spec, args.output_root, str(binary), sampler)
        return driver.run(spec, args.output_root, str(binary), resume=args.resume,
                          sampler=sampler, execute=execute)
    except ProcessInterrupted as exc:
        print(f"Study interrupted by {exc}", file=sys.stderr)
        return 128 + exc.signum
    except (ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
