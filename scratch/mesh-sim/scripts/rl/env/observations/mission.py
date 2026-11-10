"""Policy features derived from mission state and current building geometry."""

import math

import numpy as np


_OBSTACLE_NAMES = ("obstacle_west", "obstacle_east", "obstacle_south", "obstacle_north")
_NAVIGATION_NAMES = (*_OBSTACLE_NAMES, "goal_dx", "goal_dy")


def _unit_interval(value):
    return 0.0 if value < 0.0 else min(1.0, value)


def mission_features(facts, contract, base):
    """Append target and measured mission state without future failure schedules."""
    mission = contract["mission"]
    state = facts["mission_state"]
    bounds = contract["bounds"]
    width = bounds["x_max"] - bounds["x_min"]
    height = bounds["y_max"] - bounds["y_min"]
    values = [float(available) for available in facts["node_available"]]
    values.extend(
        float(mission["kind"] == kind) for kind in ("coverage", "investigation", "recovery")
    )
    values.extend(
        [
            _unit_interval((mission["goal_x"] - bounds["x_min"]) / width),
            _unit_interval((mission["goal_y"] - bounds["y_min"]) / height),
            min(1.0, state["distance_m"] / math.hypot(width, height)),
            float(state["investigator_connected"]),
            float(state["connected_arrival"]),
            facts["mission"]["goal_coverage_fraction"],
            min(1.0, state["arrival_streak_s"] / mission["dwell_s"]),
            float(state["investigation_completed_at_s"] is not None),
            float(state["failure_at_s"] is not None),
            state["survivor_delivery"],
            state["survivor_fair_service"],
            state["survivor_worst_service"],
            state["coverage_target"],
            min(1.0, state["recovery_streak_s"] / mission["dwell_s"]),
            float(state["recovery_completed_at_s"] is not None),
        ]
    )
    return np.concatenate((base, np.asarray(values, dtype=np.float32)))


def mission_feature_names(contract):
    return [f"node.{node}.available" for node in contract["node_ids"]] + [
        "mission.coverage",
        "mission.investigation",
        "mission.recovery",
        "mission.goal_x",
        "mission.goal_y",
        "mission.distance",
        "mission.connected",
        "mission.arrived",
        "mission.goal_coverage",
        "mission.dwell",
        "mission.completed",
        "mission.failure",
        "mission.survivor_delivery",
        "mission.survivor_fair",
        "mission.survivor_worst",
        "mission.coverage_target",
        "mission.recovery_dwell",
        "mission.recovered",
    ]


def node_navigation_features(position, contract):
    """Measure four obstacle ranges and two goal offsets at a peer's position."""
    x, y, z = position[:3]
    navigation = contract["navigation"]
    range_m = navigation["obstacle_sensing_range_m"]
    clearance = navigation["building_clearance_m"]
    distances = [range_m] * 4
    for building in navigation["buildings"]:
        if not building["z_min"] - clearance <= z <= building["z_max"] + clearance:
            continue
        xmin = building["x_min"] - clearance
        xmax = building["x_max"] + clearance
        ymin = building["y_min"] - clearance
        ymax = building["y_max"] + clearance
        if ymin <= y <= ymax:
            if x >= xmax:
                distances[0] = min(distances[0], x - xmax)
            if x <= xmin:
                distances[1] = min(distances[1], xmin - x)
        if xmin <= x <= xmax:
            if y >= ymax:
                distances[2] = min(distances[2], y - ymax)
            if y <= ymin:
                distances[3] = min(distances[3], ymin - y)

    mission = contract["mission"]
    bounds = contract["bounds"]
    width = bounds["x_max"] - bounds["x_min"]
    height = bounds["y_max"] - bounds["y_min"]
    return [
        *(distance / range_m for distance in distances),
        _unit_interval(0.5 + 0.5 * (mission["goal_x"] - x) / width),
        _unit_interval(0.5 + 0.5 * (mission["goal_y"] - y) / height),
    ]


def navigation_features(facts, contract):
    positions = dict(zip(contract["node_ids"], facts["nodes"]))
    values = []
    for node in contract["slot_node_ids"]:
        if node is None:
            values.extend([0.0] * len(_NAVIGATION_NAMES))
        else:
            values.extend(node_navigation_features(positions[node], contract))
    state = facts["mission_state"]
    values.extend([state["team_arrival_fraction"], float(state["team_connected"])])
    return values


def navigation_feature_names(contract):
    return [
        f"node.{node}.{name}" for node in contract["slot_node_ids"] for name in _NAVIGATION_NAMES
    ] + ["mission.team_arrivals", "mission.team_connected"]
