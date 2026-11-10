"""Parse user launch options; importing this module never starts a simulator."""

import argparse
import json
from pathlib import Path

from scripts.sim_support import find_mesh_root, find_sim_binary
from scripts.rl.scenario_check.execution import run
from scripts.rl.scenario_check.execution import validate_inputs


def main():
    mesh = find_mesh_root()
    parser = argparse.ArgumentParser(
        description="October 23 scenario checks only; no training stage."
    )
    parser.add_argument(
        "--inputs", type=Path, default=mesh / "inputs/custom/10-23/scenario-check"
    )
    parser.add_argument(
        "--output", type=Path, default=mesh / "outputs/custom/10-23/scenario-check"
    )
    parser.add_argument("--sim-binary", default=find_sim_binary(mesh))
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=4)
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Validate fingerprints and print workload; no process creation.",
    )
    args = parser.parse_args()
    try:
        campaign = validate_inputs(args.inputs)
        if args.plan_only:
            print(
                json.dumps(
                    dict(
                        cases=len(campaign["cases"]),
                        episodes=campaign["episodes_expected"],
                        training=False,
                        workers=args.workers,
                        output=str(args.output),
                    ),
                    indent=2,
                )
            )
            return 0
        if not args.sim_binary:
            raise ValueError(
                "no built simulator found; build first or pass --sim-binary"
            )
        return run(args.inputs, args.output, args.sim_binary, args.workers)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
