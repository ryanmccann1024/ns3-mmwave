#!/usr/bin/env python3
"""Stand-in for the C++ mesh-sim binary: same flags, same RL stdout/stdin protocol.

FAKE_SIM_MODE selects normal (default), exit3, or malformed behaviour.
"""

import configparser
import json
import os
import sys
from pathlib import Path

VALUE_FLAGS = ("--run-config", "--seed", "--output-dir", "--band")
BOOL_FLAGS = ("--rl-mode",)
STEP_M = 5.0
STDERR_MARKER = "fake-sim: simulated fatal error"


## @brief Parse the ns-3 CommandLine spellings the real binary accepts.
def parse_args(argv: list[str]) -> dict:
    args = {"rl-mode": False}
    i = 0
    while i < len(argv):
        token = argv[i]
        name, sep, value = token.partition("=")
        if name in BOOL_FLAGS and not sep:
            args["rl-mode"] = True
        elif name in VALUE_FLAGS:
            if not sep:
                i += 1
                if i >= len(argv):
                    sys.exit(f"fake-sim: missing value for {name}")
                value = argv[i]
            args[name.lstrip("-")] = value
        else:
            sys.exit(f"fake-sim: unknown flag {token}")
        i += 1
    return args


def write_outputs(out_dir: Path, seed: int, band: str | None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "run.log").write_text(
        "fake-sim run log\n"
        f"seeds:               [{seed}]\n"
        f"--band:              {band if band is not None else 'default'}\n"
    )
    seed_dir = out_dir / f"seed-{seed}"
    seed_dir.mkdir(exist_ok=True)
    (seed_dir / "summary.json").write_text(
        json.dumps({"seed": seed, "fake": True}, indent=2) + "\n"
    )
    (seed_dir / "links.csv").write_text("tick,src,dst,sinr_db,capacity_mbps\n")


def message(tick: int, tick_s: float, pos: list[float], done: bool) -> str:
    return json.dumps({
        "type": "step",
        "tick": tick,
        "time_s": tick * tick_s,
        "obs": {
            "controlled_pos": pos,
            "link_sinrs": [20.0 - pos[0] * 0.01, 18.0],
            "link_capacities": [100.0, 90.0],
        },
        "reward": 1.0,
        "done": done,
        "action_type": "discrete",
    })


def emit(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def main() -> int:
    args = parse_args(sys.argv[1:])
    mode = os.environ.get("FAKE_SIM_MODE", "normal")

    ini = configparser.ConfigParser()
    ini.read(args["run-config"])
    duration_s = ini.getfloat("scenario", "duration_s", fallback=0.4)
    tick_s = ini.getfloat("scenario", "tick_s", fallback=0.1)
    seed = int(args["seed"]) if "seed" in args else ini.getint("scenario", "seed", fallback=1)

    write_outputs(Path(args["output-dir"]), seed, args.get("band"))

    n_messages = int(round(duration_s / tick_s)) + 1
    pos = [0.0, 0.0, 0.0]

    emit(message(0, tick_s, list(pos), n_messages == 1))
    if mode == "exit3":
        print(STDERR_MARKER, file=sys.stderr, flush=True)
        return 3

    for tick in range(1, n_messages):
        line = sys.stdin.readline()
        if not line:
            return 0
        action = int(json.loads(line)["action"])
        if action == 0:
            pos[0] -= STEP_M
        elif action == 1:
            pos[0] += STEP_M
        elif action == 2:
            pos[1] -= STEP_M
        elif action == 3:
            pos[1] += STEP_M
        elif action == 4:
            pos[2] = max(0.0, pos[2] - STEP_M)
        elif action == 5:
            pos[2] += STEP_M

        if mode == "malformed" and tick == 1:
            emit("this is not json {")
            return 0
        emit(message(tick, tick_s, list(pos), tick == n_messages - 1))

    return 0


if __name__ == "__main__":
    sys.exit(main())
