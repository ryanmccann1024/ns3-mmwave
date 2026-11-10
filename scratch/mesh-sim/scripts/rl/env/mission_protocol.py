"""Validation for the native mission extension."""

import math


def validate_mission_facts(facts, contract, mask):
    """Validate availability, survivor accounting and the failed slots' hold-only masks."""
    active = facts.get("node_available")
    if (
        not isinstance(active, list)
        or len(active) != contract["num_mesh_nodes"]
        or any(type(v) is not bool for v in active)
    ):
        raise ValueError("mission facts require a boolean availability flag per peer")
    raw = facts.get("mission")
    if not isinstance(raw, dict):
        raise ValueError("mission facts missing; rebuild mesh-sim")
    for key in (
        "goal_coverage_fraction",
        "survivor_demand_mbps_sum",
        "survivor_delivered_mbps_sum",
    ):
        value = raw.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"invalid mission fact {key}")
    if (
        raw["goal_coverage_fraction"] > 1
        or raw["survivor_delivered_mbps_sum"] > raw["survivor_demand_mbps_sum"] + 1e-6
    ):
        raise ValueError("mission fractions or survivor delivery out of range")
    rows = raw.get("survivor_node_service")
    if not isinstance(rows, list) or len(rows) != len(active):
        raise ValueError("mission survivor service requires one row per peer")
    for row in rows:
        if (
            not isinstance(row, list)
            or len(row) != 2
            or any(
                not isinstance(v, (int, float))
                or isinstance(v, bool)
                or not math.isfinite(v)
                or v < 0
                for v in row
            )
            or row[1] > row[0] + 1e-6
        ):
            raise ValueError("invalid survivor node service")
    for column, key in enumerate(("survivor_demand_mbps_sum", "survivor_delivered_mbps_sum")):
        if not math.isclose(
            sum(row[column] for row in rows), 2 * raw[key], abs_tol=1e-6, rel_tol=1e-6
        ):
            raise ValueError("survivor endpoint accounting must equal twice the flow sums")
    for slot, node in enumerate(contract["slot_node_ids"]):
        if (
            node is not None
            and not active[contract["node_ids"].index(node)]
            and list(mask[5 * slot : 5 * slot + 5]) != [0, 0, 0, 0, 1]
        ):
            raise ValueError("offline peer must have a hold-only action mask")


def validate_mission_contract(contract):
    spec = contract["mission"]
    if (
        not isinstance(spec, dict)
        or type(spec.get("version")) is not int
        or spec["version"] not in (1, 2)
    ):
        raise ValueError("unsupported mission extension; expected version 1 or 2")
    if spec.get("kind") not in ("coverage", "investigation", "recovery"):
        raise ValueError("invalid mission kind")
    for key in (
        "goal_x",
        "goal_y",
        "arrival_radius_m",
        "coverage_radius_m",
        "dwell_s",
        "goal_coverage_target",
        "recovery_delivery_target",
        "recovery_coverage_ratio",
        "recovery_worst_target",
        "progress_distance_scale_m",
    ):
        value = spec.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(f"mission.{key} must be finite")
        zero_allowed = key == "recovery_coverage_ratio" or (
            spec["kind"] == "investigation" and key == "goal_coverage_target"
        )
        if key not in ("goal_x", "goal_y") and (value < 0 or (value == 0 and not zero_allowed)):
            raise ValueError(f"mission.{key} must be positive")
        if (
            key
            in (
                "goal_coverage_target",
                "recovery_delivery_target",
                "recovery_coverage_ratio",
                "recovery_worst_target",
            )
            and value > 1
        ):
            raise ValueError(f"mission.{key} must be at most one")
    if spec["version"] == 2:
        if spec.get("team_investigation") is not True or spec["kind"] != "investigation":
            raise ValueError("mission version 2 requires team investigation")
        for key in ("team_radius_m", "team_delivery_target"):
            value = spec.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
                or (value == 0 and key != "team_delivery_target")
            ):
                raise ValueError(f"invalid mission.{key}")
        if spec["team_delivery_target"] > 1:
            raise ValueError("team delivery target must be at most one")
    if spec.get("coverage_domain") != "outdoor_probe_cells":
        raise ValueError("unsupported mission coverage domain")
    if (
        spec["kind"] == "investigation"
        and spec.get("investigator_id") not in contract["slot_node_ids"]
    ):
        raise ValueError("investigator must be a controlled peer")
