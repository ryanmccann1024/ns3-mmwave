"""Mission and physical episode metrics from saved decision telemetry.

One owner for the metrics previously duplicated across the mission and phase
campaigns. Formulas, windows and missing-value rules are unchanged: a missing
measurement stays ``None``; it never becomes zero.

- :func:`compute_mission_metrics` / :class:`MissionTotals` -- mission score and outcomes.
- :func:`mission_episode_metrics` -- the same, read from a complete ``steps.jsonl``.
- :func:`read_episode`, :func:`strict_success` -- raw telemetry and the strict
  per-decision success predicate (``None`` for an ineligible window).
- :func:`connected`, :func:`physical` -- native-SINR team connectivity and the
  scenario-check physical reduction plus final-minute radio unity.
"""

import csv
import json
import statistics
import math
from pathlib import Path

CONNECTED_SINR_THRESHOLD_DB = -6.7
STRICT_DELIVERY_TARGET = 0.9
INVESTIGATION_TARGET_XY = (345, 300)
INVESTIGATION_RADIUS_M = 50

DEFINITIONS = {
    "mission_score": ("score", True),
    "investigation_success": ("fraction", True),
    "connected_arrival_s": ("s", False),
    "investigation_completion_s": ("s", False),
    "goal_coverage_mean": ("fraction", True),
    "goal_coverage_final": ("fraction", True),
    "failure_s": ("s", None),
    "recovery_success": ("fraction", True),
    "recovery_completion_s": ("s", False),
    "recovery_delay_s": ("s", False),
    "post_failure_survivor_delivery": ("ratio", True),
    "post_failure_original_demand_delivery": ("ratio", True),
    "lost_demand_fraction": ("fraction", False),
    "post_failure_worst_survivor": ("ratio", True),
    "final_minute_survivor_delivery": ("ratio", True),
    "final_minute_worst_survivor": ("ratio", True),
    "coverage_mean": ("fraction", True),
    "original_demand_delivery": ("ratio", True),
    "mean_movement_fraction": ("fraction", False),
    "unsafe_fraction": ("fraction", False),
}

DEFINITIONS.update(
    {
        "coverage_gain_final": ("fraction", True),
        "final_minute_coverage": ("fraction", True),
        "final_minute_original_delivery": ("ratio", True),
        "pre_failure_survivor_delivery": ("ratio", True),
        "post_failure_travel_m": ("m", False),
        "survivor_outage_s": ("s", False),
        "survivor_undelivered_mbit": ("Mbit", False),
        "team_arrival_fraction_final": ("fraction", True),
        "building_collision_attempts": ("slot attempts", False),
        "peer_collision_attempts": ("slot attempts", False),
    }
)


class MissionTotals:
    def __init__(self):
        self.steps = []
        self.contract = None
        self.result = None

    def add(self, record, num_links, contract):
        if (
            contract
            and "mission" in contract
            and "mission_state" in record.get("facts", {})
        ):
            self.contract = contract
            self.steps.append(record)

    def value(self, name):
        if self.result is None:
            self.result = (
                compute_mission_metrics(self.steps, self.contract)
                if self.contract
                else {}
            )
        return self.result.get(name)


def compute_mission_metrics(steps, contract):
    records = [{"contract": contract}, *steps]
    rows = [
        r
        for r in steps
        if r.get("decision", 0) > 0 and r["facts"]["window"]["scored_ticks"] > 0
    ]
    if (
        "mission" not in contract
        or not rows
        or rows[-1]["decision"] != contract["num_decisions"]
    ):
        return {name: None for name in DEFINITIONS}

    def mean(key, subset=rows):
        return (
            statistics.mean(r["facts"]["mission_state"][key] for r in subset)
            if subset
            else None
        )

    def ratio(subset, survivors=False):
        if survivors:
            demand = sum(
                r["facts"]["mission"]["survivor_demand_mbps_sum"] for r in subset
            )
            delivered = sum(
                r["facts"]["mission"]["survivor_delivered_mbps_sum"] for r in subset
            )
        else:
            demand = sum(r["facts"]["window"]["demand_mbps_sum"] for r in subset)
            delivered = sum(r["facts"]["window"]["delivered_mbps_sum"] for r in subset)
        return delivered / demand if demand > 1e-9 else None

    last = rows[-1]["facts"]["mission_state"]
    failed = last["failure_at_s"]
    post = [r for r in rows if failed is not None and r["time_s"] > failed]
    tail = [r for r in rows if r["time_s"] > rows[-1]["time_s"] - 60]
    travel = 0.0
    post_travel = 0.0
    for previous, current in zip(records[1:], records[2:]):
        for slot, node in enumerate(contract["slot_node_ids"]):
            if node is None:
                continue
            i = contract["node_ids"].index(node)
            a, b = previous["facts"]["nodes"][i], current["facts"]["nodes"][i]
            moved = math.hypot(b[0] - a[0], b[1] - a[1])
            travel += moved / (
                contract["slot_speed_mps"][slot] * contract["decision_interval_s"]
            )
            if failed is not None and previous["time_s"] >= failed:
                post_travel += moved
    movement = travel / (len(rows) * contract["num_controlled"])
    coverage = statistics.mean(r["facts"]["coverage"]["fraction"] for r in rows)
    whole = ratio(rows)
    worst = mean("survivor_worst_service")
    unsafe = sum(r["facts"]["safety"]["unsafe_ticks"] for r in rows) / sum(
        r["scored_ticks"] for r in rows
    )
    goal = statistics.mean(
        r["facts"]["mission"]["goal_coverage_fraction"] for r in rows
    )
    complete = last["investigation_completed_at_s"] is not None
    recovered = last["recovery_completed_at_s"] is not None
    kind = contract["mission"]["kind"]
    if kind == "coverage":
        score = None if whole is None else 0.5 * coverage + 0.3 * whole + 0.2 * worst
    elif kind == "investigation":
        goal_term = (
            last.get("team_arrival_fraction", 0)
            if contract["mission"].get("team_investigation")
            else goal
        )
        score = (
            None
            if whole is None
            else 0.5 * complete + 0.2 * goal_term + 0.2 * whole + 0.1 * worst
        )
    else:
        postcoverage = (
            statistics.mean(r["facts"]["coverage"]["fraction"] for r in post)
            if post
            else 0.0
        )
        score = (
            0.4 * recovered
            + 0.3 * (ratio(post, True) or 0)
            + 0.2 * postcoverage
            + 0.1 * (mean("survivor_worst_service", post) or 0)
        )
    if score is not None:
        score -= 0.05 * movement + 2 * unsafe
    full_demand = sum(r["facts"]["window"]["demand_mbps_sum"] for r in post)
    survivor_demand = sum(
        r["facts"]["mission"]["survivor_demand_mbps_sum"] for r in post
    )
    return {
        "mission_score": score,
        "coverage_gain_final": rows[-1]["facts"]["coverage"]["fraction"]
        - steps[0]["facts"]["coverage"]["fraction"],
        "final_minute_coverage": statistics.mean(
            r["facts"]["coverage"]["fraction"] for r in tail
        ),
        "final_minute_original_delivery": ratio(tail),
        "pre_failure_survivor_delivery": ratio(
            [r for r in rows if failed is not None and r["time_s"] < failed], True
        ),
        "post_failure_travel_m": post_travel if failed is not None else None,
        "survivor_outage_s": sum(
            r["ticks_in_step"] * contract["tick_s"]
            for r in post
            if r["facts"]["mission_state"]["survivor_delivery"]
            < contract["mission"]["recovery_delivery_target"]
        )
        if failed is not None
        else None,
        "survivor_undelivered_mbit": sum(
            (
                r["facts"]["mission"]["survivor_demand_mbps_sum"]
                - r["facts"]["mission"]["survivor_delivered_mbps_sum"]
            )
            * contract["tick_s"]
            for r in post
        )
        if failed is not None
        else None,
        "team_arrival_fraction_final": last.get("team_arrival_fraction")
        if contract["mission"].get("team_investigation")
        else None,
        "building_collision_attempts": sum(
            len(r["facts"]["safety"]["building_rejected_slots"]) for r in rows
        )
        if "building_rejected_slots" in rows[0]["facts"]["safety"]
        else None,
        "peer_collision_attempts": sum(
            len(r["facts"]["safety"]["peer_rejected_slots"]) for r in rows
        )
        if "peer_rejected_slots" in rows[0]["facts"]["safety"]
        else None,
        "investigation_success": int(complete),
        "connected_arrival_s": last["arrival_at_s"],
        "investigation_completion_s": last["investigation_completed_at_s"],
        "goal_coverage_mean": goal,
        "goal_coverage_final": rows[-1]["facts"]["mission"]["goal_coverage_fraction"],
        "failure_s": failed,
        "recovery_success": int(recovered),
        "recovery_completion_s": last["recovery_completed_at_s"],
        "recovery_delay_s": last["recovery_completed_at_s"] - failed
        if recovered
        else None,
        "post_failure_survivor_delivery": ratio(post, True),
        "post_failure_original_demand_delivery": ratio(post),
        "lost_demand_fraction": 1 - survivor_demand / full_demand
        if full_demand > 0
        else None,
        "post_failure_worst_survivor": mean("survivor_worst_service", post),
        "final_minute_survivor_delivery": ratio(tail, True),
        "final_minute_worst_survivor": mean("survivor_worst_service", tail),
        "coverage_mean": coverage,
        "original_demand_delivery": whole,
        "mean_movement_fraction": movement,
        "unsafe_fraction": unsafe,
    }


def mission_episode_metrics(directory, *, trace=None):
    """Mission metrics from a complete episode; incomplete telemetry is an error."""
    header, steps = read_episode(directory) if trace is None else trace
    contract = header["contract"]
    if not steps or steps[-1].get("decision") != contract["num_decisions"]:
        raise ValueError(f"mission report requires complete telemetry: {directory}")
    return compute_mission_metrics(steps, contract)


def read_episode(directory):
    """``(header, records)`` from an episode's ``steps.jsonl``."""
    with (Path(directory) / "steps.jsonl").open() as handle:
        header = json.loads(next(handle))
        rows = [json.loads(line) for line in handle if line.strip()]
    return header, rows


def strict_success(case, row):
    """Strict per-decision success; ``None`` when the window is not eligible."""
    f = row["facts"]
    w = f["window"]
    mission = case["mission"]
    if not w["scored_ticks"]:
        return None
    if mission in ("recovery", "jamming"):
        deployment = f["deployment"]
        if (
            not deployment["active"]
            or deployment["eligible_ticks"] != w["scored_ticks"]
        ):
            return None
    if mission == "coverage":
        return f["coverage"]["fraction"] >= case["coverage_target"]
    if mission == "investigation":
        active = [n for n, a in zip(f["nodes"], f["node_available"]) if a]
        x, y = INVESTIGATION_TARGET_XY
        return bool(active) and all(
            math.hypot(n[0] - x, n[1] - y) <= INVESTIGATION_RADIUS_M for n in active
        )
    source = f["mission"] if mission == "recovery" else w
    prefix = "survivor_" if mission == "recovery" else ""
    demand = source[prefix + "demand_mbps_sum"]
    return (
        demand > 1e-9
        and source[prefix + "delivered_mbps_sum"] / demand >= STRICT_DELIVERY_TARGET
    )


def connected(facts, threshold=CONNECTED_SINR_THRESHOLD_DB):
    """One SINR-threshold graph over every available peer; failed relays excluded."""
    active = {i for i, v in enumerate(facts["node_available"]) if v}
    if not active:
        return False
    edges = {i: set() for i in active}
    k = 0
    for i in range(len(facts["nodes"])):
        for j in range(i + 1, len(facts["nodes"])):
            if i in active and j in active and facts["links"][k][0] >= threshold:
                edges[i].add(j)
                edges[j].add(i)
            k += 1
    seen, todo = set(), [next(iter(active))]
    while todo:
        node = todo.pop()
        if node not in seen:
            seen.add(node)
            todo.extend(edges[node] - seen)
    return seen == active


def physical(directory, case, seed, write=False):
    """Scenario-check reduction plus final-minute native radio unity (600-decision episodes)."""
    from scripts.artifact_io import write_json
    from scripts.rl.scenario_check.assessment import reduce_records

    header, rows = read_episode(directory)
    metrics, timeline = reduce_records(
        rows, header["contract"], case["mission"], case["seeds"][str(seed)]["gate_s"]
    )
    tail = [r for r in rows if r["decision"] > 0 and r["time_s"] > 540]
    metrics["final_minute_team_connected_fraction"] = statistics.mean(
        float(connected(r["facts"])) for r in tail
    )
    metrics["radio_unity_source"] = (
        "native available-peer SINR graph at -6.7 dB; final 60 s"
    )
    metrics["mean_reward_per_decision"] = (
        sum((r.get("reward") or {}).get("total", 0.0) for r in rows) / 600
    )
    if write:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        write_json(directory / "scenario_check_metrics.json", metrics)
        radio = {
            r["time_s"]: float(connected(r["facts"])) for r in rows if r["decision"] > 0
        }
        for t in timeline:
            t["team_connected"] = radio[t["time_s"]]
        with (directory / "scenario_timeline.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(timeline[0]))
            writer.writeheader()
            writer.writerows(timeline)
    return metrics
