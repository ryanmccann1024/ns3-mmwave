#!/usr/bin/env python3
"""CLI for one initial placement followed by a standalone simulator run."""

import argparse
import sys

from scripts.baselines import config
from scripts.baselines.execution import RunSettings, execute


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Plan a placement baseline once, then run the simulator on the plan"
    )
    p.add_argument("--sim-binary", required=True, help="Path to the mesh-sim executable")
    p.add_argument("--run-config", required=True, help="Scenario run.ini (never modified)")
    p.add_argument(
        "--seeds",
        default=None,
        help="Comma-separated simulation seeds, A-B inclusive ranges allowed; "
        "omitted -> [scenario] seed",
    )
    p.add_argument(
        "--algorithm",
        choices=list(config.ALGORITHMS),
        default=None,
        help="Override [baseline] algorithm",
    )
    p.add_argument(
        "--output-dir",
        default=None,
        help="Empty or absent run directory; omitted -> " "outputs/YYYY-MM/DD/HH-MM-SS-baseline",
    )
    p.add_argument(
        "--band",
        choices=["mmwave", "sub-6"],
        default=None,
        help="Override the scenario band; omitted -> scenario decides",
    )
    p.add_argument(
        "--planning-seed",
        type=int,
        default=None,
        help="Channel-planning seed; overrides [baseline] planning_seed",
    )
    p.add_argument(
        "--allow-seed-overlap",
        action="store_true",
        help="Allow planning/evaluation overlap as an adaptation diagnostic",
    )
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    return execute(RunSettings(**vars(args)))


if __name__ == "__main__":
    sys.exit(main())
