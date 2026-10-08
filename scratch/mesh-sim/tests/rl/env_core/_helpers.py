"""Hand-built RL protocol messages and a scripted fake-peer launcher for env_core tests.

The builders produce messages that satisfy the centralized contract in
src/rl/README.md (mesh_move_2d_v1 / mesh_facts_v1) for a 3-node scenario with
two controlled slots and one padded slot, so each test can break exactly one
field. ``ScriptedPeer`` writes a shell shim that execs ``_scripted_peer.py``,
which replays a JSON list of ops (emit / read / exit / ...) from a file.
"""

import copy
import json
import sys
import threading
from pathlib import Path

PEER_SCRIPT = Path(__file__).resolve().parent / "_scripted_peer.py"

NODE_IDS = ["node-a", "node-b", "node-c"]
SLOT_IDS = ["node-b", "node-c", None]
NODE_POS = {"node-a": [50.0, 20.0, 10.0], "node-b": [100.0, 0.0, 10.0],
            "node-c": [97.0, 50.0, 10.0]}


def make_init(**overrides) -> dict:
    """A valid centralized init: N=3, M=3, 2 active slots, k=5, 10 ticks."""
    init = {
        "type": "init",
        "contract": "mesh_move_2d_v1",
        "dimensions": 2,
        "action_meanings": ["west", "east", "south", "north", "hold"],
        "max_controlled_nodes": 3,
        "num_controlled": 2,
        "slot_node_ids": list(SLOT_IDS),
        "slot_speed_mps": [10.0, 10.0, None],
        "num_mesh_nodes": 3,
        "obs_dim": 24,
        "mask_dim": 15,
        "tick_s": 0.1,
        "decision_interval_s": 0.5,
        "decision_interval_ticks": 5,
        "num_ticks": 10,
        "num_decisions": 2,
        "reward_type": "all_links_los",
        "reward_window": "mean",
        "wall_policy": "clip",
        "facts_schema": "mesh_facts_v1",
        "facts_columns": {"nodes": ["x", "y", "z", "vx", "vy", "vz", "slot"],
                          "links": ["sinr_db", "capacity_mbps", "is_los"]},
        "node_ids": list(NODE_IDS),
        "num_links": 3,
        "bounds": {"x_min": 0.0, "x_max": 100.0, "y_min": -50.0, "y_max": 100.0,
                   "z_min": 0.0, "z_max": 50.0},
        "band": "mmwave",
        "jammer_path_enabled": False,
        "warmup_s": 0.0,
    }
    init.update(overrides)
    return init


def _slot_of(init: dict) -> dict:
    return {node: slot for slot, node in enumerate(init["slot_node_ids"])
            if node is not None}


def make_facts(init: dict, ticks: int, reward: float = 1.0) -> dict:
    node_ids = init["node_ids"]
    slot_of = _slot_of(init)
    nodes = [[*NODE_POS.get(node, [0.0, 0.0, 0.0]), 0.0, 0.0, 0.0,
              slot_of.get(node, -1)] for node in node_ids]
    n = len(node_ids)
    links = [[10.0, 50.0, 1] for _ in range(n * (n - 1) // 2)]
    flows = len(links)
    return {
        "nodes": nodes,
        "links": links,
        "window": {
            "ticks": ticks,
            "demand_mbps_sum": 10.0 * flows * ticks,
            "delivered_mbps_sum": 5.0 * flows * ticks,
            "flow_ticks_with_demand": flows * ticks,
            "unroutable_flow_ticks": 0,
            "connected_pairs_sum": flows * ticks,
            "los_pairs_sum": flows * ticks,
            "legacy_reward_sum": reward * ticks,
        },
    }


def make_obs(init: dict) -> list:
    n = init["num_mesh_nodes"]
    per_slot = 4 + 2 * (n - 1)
    obs = []
    for slot in range(init["max_controlled_nodes"]):
        node = init["slot_node_ids"][slot]
        if node is None:
            obs.extend([0.0] * per_slot)
            continue
        obs.extend([1.0, *NODE_POS.get(node, [0.0, 0.0, 0.0])])
        obs.extend([10.0, 50.0] * (n - 1))
    return obs


def make_mask(init: dict) -> list:
    mask = []
    for slot in range(init["max_controlled_nodes"]):
        mask.extend([1, 1, 1, 1, 1] if slot < init["num_controlled"]
                    else [0, 0, 0, 0, 1])
    return mask


def make_step(init: dict, tick: int, decision: int, ticks_in_step: int,
              reward: float = 1.0, **overrides) -> dict:
    """A valid centralized step for the given tick/decision/window."""
    msg = {
        "type": "step",
        "tick": tick,
        "time_s": tick * init["tick_s"],
        "decision": decision,
        "ticks_in_step": ticks_in_step,
        "obs": make_obs(init),
        "mask": make_mask(init),
        "reward": reward,
        "done": tick == init["num_ticks"],
        "revalidated_slots": [],
        "facts": make_facts(init, ticks_in_step, reward),
    }
    msg.update(overrides)
    return msg


def episode_steps(init: dict, reward: float = 1.0) -> list[dict]:
    """Every step message of one episode, reset (decision 0) through the terminal one."""
    k, ticks = init["decision_interval_ticks"], init["num_ticks"]
    steps = [make_step(init, 0, 0, 1, reward)]
    tick, decision = 0, 0
    while tick < ticks:
        window = min(k, ticks - tick)
        tick += window
        decision += 1
        steps.append(make_step(init, tick, decision, window, reward))
    return steps


def make_legacy_step(tick: int, pos=(0.0, 0.0, 0.0), links: int = 2,
                     reward: float = 1.0, done: bool = False,
                     action_type: str = "discrete", tick_s: float = 0.1) -> dict:
    return {
        "type": "step",
        "tick": tick,
        "time_s": tick * tick_s,
        "obs": {"controlled_pos": list(pos),
                "link_sinrs": [15.0] * links,
                "link_capacities": [80.0] * links},
        "reward": reward,
        "done": done,
        "action_type": action_type,
    }


def centralized_script(init: dict, steps: list[dict] | None = None) -> list[dict]:
    """Peer ops: emit init, then each step, reading one action between steps."""
    steps = episode_steps(init) if steps is None else steps
    ops: list[dict] = [{"emit": init}]
    for index, step in enumerate(steps):
        if index:
            ops.append({"read": True})
        ops.append({"emit": step})
    return ops


def legacy_script(steps: list[dict]) -> list[dict]:
    ops: list[dict] = []
    for index, step in enumerate(steps):
        if index:
            ops.append({"read": True})
        ops.append({"emit": step})
    return ops


CENTRAL_INI = """[scenario]
name = scripted-central
seed = 1
duration_s = 1.0
tick_s = 0.1

[rl]
enabled = true
controlled_nodes = node-b, node-c
max_controlled_nodes = 3
"""

LEGACY_INI = """[scenario]
name = scripted-legacy
seed = 1
duration_s = 0.4
tick_s = 0.1

[rl]
enabled = true
controlled_node_id = relay
action_type = discrete
"""


class ScriptedPeer:
    """Owns the shim, script file, and logs of one scripted fake simulator."""

    def __init__(self, tmp_path: Path, monkeypatch):
        self.dir = tmp_path / "peer"
        self.dir.mkdir(exist_ok=True)
        self.script_path = self.dir / "script.json"
        self.action_log = self.dir / "actions.jsonl"
        self.argv_log = self.dir / "argv.jsonl"
        self.binary = self.dir / "fake-peer"
        self.binary.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{PEER_SCRIPT}" "$@"\n')
        self.binary.chmod(0o755)
        monkeypatch.setenv("SCRIPTED_PEER_SCRIPT", str(self.script_path))
        monkeypatch.setenv("SCRIPTED_PEER_LOG", str(self.action_log))
        monkeypatch.setenv("SCRIPTED_PEER_ARGV", str(self.argv_log))

    def script(self, ops: list[dict]) -> None:
        self.script_path.write_text(json.dumps(ops))

    def actions(self) -> list:
        if not self.action_log.is_file():
            return []
        return [json.loads(line) for line in self.action_log.read_text().splitlines()]

    def argvs(self) -> list[list[str]]:
        if not self.argv_log.is_file():
            return []
        return [json.loads(line) for line in self.argv_log.read_text().splitlines()]


def write_ini(tmp_path: Path, text: str, name: str = "run.ini") -> str:
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def drain_threads() -> list:
    return [t for t in threading.enumerate() if t.name == "mesh-sim-drain"]


def episode_manifest(out_dir: Path, index: int) -> dict:
    return json.loads((out_dir / f"episode-{index:04d}" / "rl_episode.json").read_text())


def clone(obj):
    return copy.deepcopy(obj)
