"""Scripted reference controllers for scenario checks and mission pilots.

Two route formats exist and keep their own controllers:

- `ReferencePolicy` follows scenario-check `reference.json` routes
  (`routes: {node_id: [[x, y, z], ...]}`) after the env's `gate_s`, with joint
  swept-distance reservation between peers.
- `ScriptedMissionPolicy` follows mission-pilot waypoints
  (`waypoints`, `node_order`, `start_after_failure`, optional `start_after_s`,
  `start_below_delivery` and `parallel`).

Both read live facts from `env._protocol.facts` and only propose actions that the
native mask allows; the simulator owns final validation.
"""

import numpy as np

from scripts.rl.env.geometry import swept_distance

# Retain imports used by the stacked policy-operation change.
from scripts.rl.policy.baseline_execution import import_baseline as import_baseline
from scripts.rl.policy.baseline_execution import run_baseline as run_baseline
from scripts.rl.policy.baseline_execution import run_baselines as run_baselines
from scripts.rl.policy.baseline_execution import validate_outcomes as validate_outcomes


class ScriptedMissionPolicy:
    name = "scripted"

    def __init__(self, env, reference):
        self.env = env
        self.reference = reference
        self.cursor = {}

    def start_episode(self, seed):
        self.cursor = {node: 0 for node in self.reference["waypoints"]}
        self.triggered = False

    def act(self, obs, mask, contract):
        actions = np.full(contract["max_controlled_nodes"], 4, dtype=np.int64)
        facts = self.env._protocol.facts
        if not self.triggered and "start_below_delivery" in self.reference:
            self.triggered = (
                facts["mission_state"]["survivor_delivery"]
                < self.reference["start_below_delivery"]
            )
            if not self.triggered:
                return actions
        if facts["mission_state"]["time_s"] < self.reference.get("start_after_s", 0):
            return actions
        if self.reference["start_after_failure"] and all(facts["node_available"]):
            return actions
        for node in self.reference["node_order"]:
            i = contract["node_ids"].index(node)
            if not facts["node_available"][i]:
                continue
            slot = contract["slot_node_ids"].index(node)
            tolerance = (
                0.51
                * contract["slot_speed_mps"][slot]
                * contract["decision_interval_s"]
            )
            points = self.reference["waypoints"][node]
            while self.cursor[node] < len(points):
                target = points[self.cursor[node]]
                position = facts["nodes"][i]
                if max(abs(target[a] - position[a]) for a in (0, 1)) <= tolerance:
                    self.cursor[node] += 1
                    continue
                axis = 0 if abs(target[0] - position[0]) > tolerance else 1
                action = 2 * axis + int(target[axis] > position[axis])
                if mask[slot * 5 + action]:
                    actions[slot] = action
                # Sequential (legacy) references move only the first unfinished node.
                if not self.reference.get("parallel", False):
                    return actions
                break
        return actions


class ReferencePolicy:
    """Follow precomputed routes after the event, using the live native masks.

    Joint swept-distance reservation selects safe proposals. The simulator owns
    final action validation. A stalled route is reported, never counted as proof
    that the scenario is feasible.
    """

    name = "scripted"

    def __init__(self, env, reference, *, random_valid=False):
        self.env, self.reference, self.random_valid = env, reference, random_valid

    def start_episode(self, seed):
        self.cursor = dict.fromkeys(self.reference["routes"], 0)
        self.rng = np.random.default_rng(seed)

    def act(self, obs, mask, contract):
        facts = self.env._protocol.facts
        actions = np.full(contract["max_controlled_nodes"], 4, dtype=np.int64)
        if facts["mission_state"]["time_s"] < self.env.gate_s:
            return actions
        if self.random_valid:
            for slot in range(len(actions)):
                actions[slot] = self.rng.choice(
                    np.flatnonzero(mask[slot * 5 : (slot + 1) * 5])
                )
            return actions
        nodes = [list(p[:3]) for p in facts["nodes"]]
        proposed = [list(p) for p in nodes]
        by_id = {node: i for i, node in enumerate(contract["node_ids"])}
        # Highest priority rotates, avoiding permanent preference for node zero.
        slots = list(range(contract["num_controlled"]))
        tick = round(facts["mission_state"]["time_s"])
        slots = slots[tick % len(slots) :] + slots[: tick % len(slots)]
        for slot in slots:
            node = contract["slot_node_ids"][slot]
            i = by_id[node]
            if not facts["node_available"][i]:
                continue
            if facts["mission_state"]["time_s"] < self.env.gate_s + 12 * (i // 3):
                continue
            speed = contract["slot_speed_mps"][slot] * contract["decision_interval_s"]
            tolerance = 0.51 * speed
            points = self.reference["routes"][node]
            while self.cursor[node] < len(points):
                target = points[self.cursor[node]]
                if max(abs(target[k] - nodes[i][k]) for k in (0, 1)) <= tolerance:
                    self.cursor[node] += 1
                    continue
                axis = 0 if abs(target[0] - nodes[i][0]) > tolerance else 1
                action = 2 * axis + int(target[axis] > nodes[i][axis])
                if mask[slot * 5 + action]:
                    end = list(nodes[i])
                    end[axis] += speed * (1 if action % 2 else -1)
                    if all(
                        not facts["node_available"][j]
                        or j == i
                        or swept_distance(nodes[i], end, nodes[j], proposed[j])
                        >= contract["unsafe_separation_m"] + 0.05
                        for j in range(len(nodes))
                    ):
                        actions[slot], proposed[i] = action, end
                break
        return actions
