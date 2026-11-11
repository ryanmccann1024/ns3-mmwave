"""Compact centralized mission features."""

import numpy as np
from gymnasium import spaces

from .mission import node_navigation_features
from ..normalization import LINK_FIELDS

_NODE_TYPES = ("pedestrian", "drone", "vehicle")
_NODE_FEATURES = (
    "available",
    "x_n",
    "y_n",
    "z_n",
    *_NODE_TYPES,
    "goal_dx",
    "goal_dy",
    "obstacle_west",
    "obstacle_east",
    "obstacle_south",
    "obstacle_north",
    "delivery",
)
_LINK_FEATURES = ("sinr_n", "capacity_n", "los")
_GLOBAL_FEATURES = (
    "team.arrivals",
    "team.connected",
    "team.delivery",
    "team.coverage",
    "team.dwell",
    "control.active",
)


def features(contract):
    node_ids = contract["node_ids"]
    names = [f"node.{node}.{feature}" for node in node_ids for feature in _NODE_FEATURES]
    for index, node in enumerate(node_ids):
        for peer in node_ids[index + 1 :]:
            names.extend(f"link.{node}.{peer}.{feature}" for feature in _LINK_FEATURES)
    names.extend(_GLOBAL_FEATURES)
    return names


def _delivery_fraction(demand, delivered):
    return min(1.0, max(0.0, delivered / demand)) if demand > 1e-9 else 0.0


def build(facts, contract, scales):
    values = []
    bounds = contract["bounds"]
    for index, row in enumerate(facts["nodes"]):
        position = []
        for coordinate, axis in zip(row, "xyz"):
            minimum = bounds[f"{axis}_min"]
            span = bounds[f"{axis}_max"] - minimum
            position.append(max(-1.0, min(1.0, 2 * (coordinate - minimum) / span - 1)))
        navigation = node_navigation_features(row, contract)
        node_type = contract["node_types"][index]
        demand, delivered = facts["node_service"][index]
        values.extend(
            [
                float(facts["node_available"][index]),
                *position,
                *(float(node_type == kind) for kind in _NODE_TYPES),
                *navigation[4:6],
                *navigation[:4],
                _delivery_fraction(demand, delivered),
            ]
        )

    for sinr, capacity, los in facts["links"]:
        values.extend([scales.sinr_quality(sinr), scales.capacity(capacity), float(los)])

    state = facts["mission_state"]
    window = facts["window"]
    deployment = facts.get("deployment")
    values.extend(
        [
            state["team_arrival_fraction"],
            float(state["team_connected"]),
            _delivery_fraction(window["demand_mbps_sum"], window["delivered_mbps_sum"]),
            facts["coverage"]["fraction"],
            min(1.0, state["arrival_streak_s"] / contract["mission"]["dwell_s"]),
            float(deployment is None or deployment["active"]),
        ]
    )
    return np.asarray(values, dtype=np.float32)


def space(contract):
    node_low = [0.0, -1.0, -1.0, -1.0] + [0.0] * 10
    low = node_low * len(contract["node_ids"])
    low += [0.0] * (len(_LINK_FEATURES) * contract["num_links"] + len(_GLOBAL_FEATURES))
    return spaces.Box(
        low=np.asarray(low, dtype=np.float32),
        high=np.ones(len(low), dtype=np.float32),
        dtype=np.float32,
    )


def register(preset_type, registry):
    registry["mission_compact_v1"] = preset_type(
        "mission_compact_v1",
        "float32",
        build,
        space,
        features,
        lambda parameters: {
            **parameters,
            "positions": "2*(value-min)/(max-min)-1",
            "target_offsets": "0.5+0.5*(target-self)/field span",
            "layout": "one node block, one unordered link block, six global measurements; no repeated pair geometry",
        },
        normalization_fields=LINK_FIELDS,
        required_facts=(
            "nodes",
            "links",
            "node_service",
            "node_available",
            "mission_state",
            "window",
            "coverage",
        ),
        compatibility_fields=("bounds", "mission", "navigation", "node_types"),
    )
