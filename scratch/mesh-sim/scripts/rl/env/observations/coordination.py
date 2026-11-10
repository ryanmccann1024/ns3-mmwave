"""Compact inputs with explicit target closeness and completed-action feedback."""

import math
import numpy as np
from gymnasium import spaces
from scripts.rl.env.observations.compact import build as compact
from scripts.rl.env.observations.compact import features as compact_features
from scripts.rl.env.observations.compact import space as compact_space
from scripts.rl.env.normalization import LINK_FIELDS


EXTRA = (
    "target_distance",
    "target_excess",
    "target_closeness",
    "inside_target",
    "achieved_move",
    "peer_blocked",
    "wall_contact",
    "last_west",
    "last_east",
    "last_south",
    "last_north",
    "last_hold",
)
GLOBAL = (
    "phase.approach_restore_expand",
    "phase.assemble_dwell",
    "phase.settle",
    "phase.good_dwell",
    "mission.relevant_delivery",
    "team.lower_tail_service",
    "team.path_support",
    "coverage.target",
    "target.team_closeness",
)


def features(contract):
    per_node = [f"node.{node}.{name}" for node in contract["node_ids"] for name in EXTRA]
    return compact_features(contract) + per_node + list(GLOBAL)


def build(facts, contract, scales):
    state = facts["coordination_v1"]
    values = list(compact(facts, contract, scales))
    mission = contract["mission"]
    target = (mission["goal_x"], mission["goal_y"])
    radius = mission.get("team_radius_m", 50.0)
    slots = {node: slot for slot, node in enumerate(contract["slot_node_ids"]) if node is not None}
    blocked = set(facts["safety"]["peer_rejected_slots"])
    wall_contacts = set(facts["safety"].get("boundary_contacted_slots", []))
    for index, node in enumerate(contract["node_ids"]):
        slot = slots.get(node)
        distance = math.dist(facts["nodes"][index][:2], target)
        excess = max(0.0, distance - radius)
        values.extend(
            [
                distance / (100.0 + distance),
                excess / (100.0 + excess),
                math.exp(-excess / 100.0),
                float(distance <= radius),
                state["moved_fraction"][index],
                float(slot in blocked),
                float(slot in wall_contacts),
                *(float(state["previous_action"][index] == action) for action in range(5)),
            ]
        )
    terms = state["terms"]
    values.extend(float(state["stage"] == stage) for stage in range(3))
    values.extend(
        [
            min(1.0, state["good_s"] / 30.0),
            terms["D"],
            terms["F"],
            terms["L"],
            state["coverage_goal"],
            terms["Q"],
        ]
    )
    return np.asarray(values, dtype=np.float32)


def space(c):
    base = compact_space(c)
    extra = 12 * len(c["node_ids"]) + 9
    return spaces.Box(
        low=np.concatenate((base.low, np.zeros(extra, dtype=np.float32))),
        high=np.concatenate((base.high, np.ones(extra, dtype=np.float32))),
        dtype=np.float32,
    )


def register(T, registry):
    registry["mission_coordination_v1"] = T(
        "mission_coordination_v1",
        "float32",
        build,
        space,
        features,
        lambda p: {
            **p,
            "base": "mission_compact_v1",
            "target_distance": "d/(100+d)",
            "target_closeness": "exp(-max(d-target_radius,0)/100 m)",
            "completed_action": "one-hot last requested cardinal action; actual/permitted movement; native rejection/contact flags",
            "phase": "measured 30 s success dwell; 5 s relapse hysteresis, immediate severe fallback; no future events",
        },
        normalization_fields=LINK_FIELDS,
        required_facts=(
            "nodes",
            "links",
            "window",
            "node_service",
            "mission",
            "mission_state",
            "coordination_v1",
        ),
        compatibility_fields=("bounds", "mission", "navigation", "node_types"),
        fact_extensions=("coordination_v1",),
    )
