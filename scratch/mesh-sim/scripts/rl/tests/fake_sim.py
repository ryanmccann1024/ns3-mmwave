#!/usr/bin/env python3
"""Stand-in for the C++ mesh-sim binary: same flags, same RL stdout/stdin protocol.

Legacy single-node mode is used unless [rl] controlled_nodes is set, which selects
the centralized protocol. FAKE_SIM_MODE selects normal (default), exit3, malformed,
or one of the isolated centralized fault modes; it never proves real movement or
reward correctness.
"""

import configparser
import json
import math
import os
import sys
from pathlib import Path

VALUE_FLAGS = ("--run-config", "--seed", "--output-dir", "--band")
BOOL_FLAGS = ("--rl-mode",)
STEP_M = 5.0
STDERR_MARKER = "fake-sim: simulated fatal error"

CONTRACT = "mesh_move_2d_v1"
ACTION_MEANINGS = ["west", "east", "south", "north", "hold"]
HOLD = 4
SPEED_CAP_MPS = 20.0
EPS = 1e-6
BOUND_DEFAULTS = {"x": (-1000.0, 2000.0), "y": (-1000.0, 1000.0), "z": (0.0, 100.0)}
LONG_MODE_TICKS = 3000       # enough valid post-EOF lines to fill a pipe buffer


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


# --------------------------------------------------------------------------
# Centralized mode
# --------------------------------------------------------------------------


def _bounds(ini: configparser.ConfigParser) -> dict:
    ranges = {}
    for axis, (low, high) in BOUND_DEFAULTS.items():
        ranges[axis] = (
            ini.getfloat("rl", f"{axis}_min", fallback=low),
            ini.getfloat("rl", f"{axis}_max", fallback=high),
        )
    return ranges


def _load_nodes(run_config: str, ini: configparser.ConfigParser) -> list[dict]:
    nodes_file = ini.get("scenario", "nodes_file", fallback="") or "nodes.json"
    path = Path(nodes_file)
    if not path.is_absolute():
        path = Path(run_config).resolve().parent / path
    nodes = []
    for entry in json.loads(path.read_text()):
        position = entry.get("position")
        if position is None and entry.get("waypoints"):
            position = entry["waypoints"][0]
        position = position or {}
        nodes.append({
            "id": entry["id"],
            "pos": [float(position.get("x", 0.0)), float(position.get("y", 0.0)),
                    float(position.get("z", 0.0))],
        })
    return nodes


def _resolve_slots(ini: configparser.ConfigParser, nodes: list[dict]) -> list[int]:
    raw = ini.get("rl", "controlled_nodes", fallback="")
    tokens = [token.strip() for token in raw.split(",") if token.strip()]
    if tokens == ["all"]:
        return list(range(len(nodes)))
    ids = [node["id"] for node in nodes]
    return [ids.index(token) for token in tokens]


def _mask(nodes: list[dict], slots: list[int], num_slots: int, bounds: dict) -> list[int]:
    flat = []
    for slot in range(num_slots):
        if slot >= len(slots):
            flat.extend([0, 0, 0, 0, 1])
            continue
        x, y, _ = nodes[slots[slot]]["pos"]
        flat.extend([
            int(x - bounds["x"][0] > EPS),
            int(bounds["x"][1] - x > EPS),
            int(y - bounds["y"][0] > EPS),
            int(bounds["y"][1] - y > EPS),
            1,
        ])
    return flat


def _observation(nodes: list[dict], slots: list[int], num_slots: int) -> list[float]:
    flat = []
    for slot in range(num_slots):
        if slot >= len(slots):
            flat.extend([0.0] * (4 + 2 * (len(nodes) - 1)))
            continue
        index = slots[slot]
        x, y, z = nodes[index]["pos"]
        flat.extend([1.0, x, y, z])
        for peer, node in enumerate(nodes):
            if peer == index:
                continue
            distance = math.dist(nodes[index]["pos"], node["pos"])
            flat.extend([20.0 - 0.01 * distance, 100.0 - 0.1 * distance])
    return flat


def _apply(nodes: list[dict], slots: list[int], num_slots: int, action: list[int],
           mask: list[int]) -> tuple[list[tuple[float, float]], list[int]]:
    """Return per-slot velocity and the slots whose action was replaced by hold."""
    velocities = []
    revalidated = []
    for slot in range(num_slots):
        choice = action[slot] if slot < len(action) else HOLD
        if mask[slot * 5 + choice] != 1:
            revalidated.append(slot)
            choice = HOLD
        if slot >= len(slots):
            continue
        velocities.append({
            0: (-1.0, 0.0), 1: (1.0, 0.0), 2: (0.0, -1.0), 3: (0.0, 1.0),
            HOLD: (0.0, 0.0),
        }[choice])
    return velocities, revalidated


def _advance(nodes: list[dict], slots: list[int], velocities, speed: float,
             tick_s: float, bounds: dict) -> None:
    for slot, index in enumerate(slots):
        vx, vy = velocities[slot]
        pos = nodes[index]["pos"]
        pos[0] = min(max(pos[0] + vx * speed * tick_s, bounds["x"][0]), bounds["x"][1])
        pos[1] = min(max(pos[1] + vy * speed * tick_s, bounds["y"][0]), bounds["y"][1])


def _init_message(mode: str, num_slots: int, count: int, nodes: list[dict],
                  slots: list[int], speed: float, tick_s: float, interval_s: float,
                  k: int, num_ticks: int, ini: configparser.ConfigParser) -> dict:
    ids = [nodes[i]["id"] for i in slots] + [None] * (num_slots - count)
    speeds = [speed] * count + [None] * (num_slots - count)
    init = {
        "type": "init",
        "contract": CONTRACT,
        "dimensions": 2,
        "action_meanings": list(ACTION_MEANINGS),
        "max_controlled_nodes": num_slots,
        "num_controlled": count,
        "slot_node_ids": ids,
        "slot_speed_mps": speeds,
        "num_mesh_nodes": len(nodes),
        "obs_dim": num_slots * (4 + 2 * (len(nodes) - 1)),
        "mask_dim": 5 * num_slots,
        "tick_s": tick_s,
        "decision_interval_s": interval_s,
        "decision_interval_ticks": k,
        "num_ticks": num_ticks,
        "num_decisions": -(-num_ticks // k),
        "reward_type": ini.get("rl", "reward_type", fallback="all_links_los"),
        "reward_window": "mean",
        "wall_policy": "clip",
    }
    if mode == "bad_contract":
        init["contract"] = "mesh_move_9d_v9"
    elif mode == "bad_meanings":
        init["action_meanings"] = ["north", "south", "east", "west", "hold"]
    elif mode == "bad_counts":
        init["num_controlled"] = num_slots + 1
    return init


def run_centralized(args: dict, ini: configparser.ConfigParser, mode: str) -> int:
    nodes = _load_nodes(args["run-config"], ini)
    slots = _resolve_slots(ini, nodes)
    count = len(slots)
    num_slots = max(ini.getint("rl", "max_controlled_nodes", fallback=0), count)
    bounds = _bounds(ini)
    tick_s = ini.getfloat("scenario", "tick_s", fallback=0.1)
    duration_s = ini.getfloat("scenario", "duration_s", fallback=0.4)
    speed = min(ini.getfloat("rl", "step_size_m", fallback=5.0) / tick_s, SPEED_CAP_MPS)
    interval_s = ini.getfloat("rl", "decision_interval_s", fallback=0.0) or tick_s
    k = max(1, int(round(interval_s / tick_s)))
    num_ticks = max(1, int(round(duration_s / tick_s)))
    if mode == "long":
        num_ticks, k, interval_s = LONG_MODE_TICKS, 1, tick_s

    emit(json.dumps(_init_message(mode, num_slots, count, nodes, slots, speed,
                                  tick_s, interval_s, k, num_ticks, ini)))

    tick, decision, revalidated, last_action = 0, 0, [], None
    window_len = 1
    eof = False
    while True:
        if mode == "malformed" and decision == 1:
            emit("this is not json {")
            return 0
        mask = _mask(nodes, slots, num_slots, bounds)
        obs = _observation(nodes, slots, num_slots)
        if mode == "bad_obs_len" and decision == 0:
            obs = obs[:-1]
        if mode == "bad_mask" and decision == 0:
            mask = list(mask)
            mask[0] = 2
        if mode == "non_finite" and decision == 0:
            obs = list(obs)
            obs[1] = float("nan")
        emit(json.dumps({
            "type": "step",
            "tick": tick,
            "time_s": tick * tick_s,
            "decision": decision,
            "ticks_in_step": window_len,
            "obs": obs,
            "mask": mask,
            "reward": 1.0,
            "done": tick >= num_ticks,
            "revalidated_slots": revalidated,
            "last_action": last_action,
        }))
        if tick >= num_ticks:
            return 0
        if mode == "exit3" and decision == 0:
            print(STDERR_MARKER, file=sys.stderr, flush=True)
            return 3
        action = [HOLD] * num_slots
        if not eof:
            line = sys.stdin.readline()
            if not line:
                eof = True
            else:
                action = list(json.loads(line)["action"])
        last_action = list(action)
        velocities, revalidated = _apply(nodes, slots, num_slots, action, mask)

        window_len = min(k, num_ticks - tick)
        for _ in range(window_len):
            _advance(nodes, slots, velocities, speed, tick_s, bounds)
        tick += window_len
        decision += 1


def main() -> int:
    args = parse_args(sys.argv[1:])
    mode = os.environ.get("FAKE_SIM_MODE", "normal")

    ini = configparser.ConfigParser()
    ini.read(args["run-config"])
    duration_s = ini.getfloat("scenario", "duration_s", fallback=0.4)
    tick_s = ini.getfloat("scenario", "tick_s", fallback=0.1)
    seed = int(args["seed"]) if "seed" in args else ini.getint("scenario", "seed", fallback=1)

    write_outputs(Path(args["output-dir"]), seed, args.get("band"))

    if ini.has_option("rl", "controlled_nodes"):
        return run_centralized(args, ini, mode)

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
