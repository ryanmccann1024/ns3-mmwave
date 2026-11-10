"""Measured mission state, reconstructed from current and previous decision facts."""

import math

from scripts.rl.env.mission_protocol import validate_mission_contract as validate_mission_contract
from scripts.rl.env.mission_protocol import validate_mission_facts as validate_mission_facts


def service(rows):
    ratios = [min(1.0, max(0.0, delivered / demand)) for demand, delivered in rows if demand > 1e-9]
    return (sum(math.sqrt(r) for r in ratios) / len(ratios), min(ratios)) if ratios else (0.0, 0.0)


def connected_core(facts):
    active = facts["node_available"]
    neighbors = {i: set() for i, available in enumerate(active) if available}
    link = 0
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            if active[i] and active[j] and facts["links"][link][0] >= -6.7:
                neighbors[i].add(j)
                neighbors[j].add(i)
            link += 1
    seen, core = set(), set()
    for root in neighbors:
        if root in seen:
            continue
        part, todo = set(), [root]
        while todo:
            node = todo.pop()
            if node in part:
                continue
            part.add(node)
            todo.extend(neighbors[node] - part)
        seen.update(part)
        if len(part) > len(core):
            core = part
    return core


class MissionState:
    """Track dwell, permanent failures and pre-failure coverage without future event data."""

    def __init__(self):
        self.previous_distance = None
        self.previous_time = 0.0
        self.previous_health = 0.0
        self.arrival_streak = self.recovery_streak = 0.0
        self.arrival_at = self.investigation_at = self.failure_at = self.recovery_at = None
        self.pre_coverage = []
        self.coverage_reference = 0.0
        self.previous_available = None

    def advance(self, facts, contract, time_s, done=False):
        if self.previous_available is not None and any(
            not old and new for old, new in zip(self.previous_available, facts["node_available"])
        ):
            raise ValueError("permanently dropped peers cannot become available again")
        self.previous_available = list(facts["node_available"])
        spec = contract["mission"]
        interval = max(0.0, time_s - self.previous_time)
        raw = facts["mission"]
        demand, delivered = raw["survivor_demand_mbps_sum"], raw["survivor_delivered_mbps_sum"]
        delivery = min(1.0, delivered / demand) if demand > 1e-9 else 0.0
        fair, worst = service(raw["survivor_node_service"])
        coverage = facts["coverage"]["fraction"]
        failure = not all(facts["node_available"])
        if failure and self.failure_at is None:
            self.failure_at = time_s
            self.coverage_reference = (
                sum(v for _, v in self.pre_coverage) / len(self.pre_coverage)
                if self.pre_coverage
                else coverage
            )
        if not failure:
            self.pre_coverage.append((time_s, coverage))
            self.pre_coverage = [(t, c) for t, c in self.pre_coverage if t > time_s - 60.0]
        distance, connected, arrived = 0.0, False, False
        team_fraction, team_connected = 0.0, False
        if spec["kind"] == "investigation":
            index = contract["node_ids"].index(spec["investigator_id"])
            node = facts["nodes"][index]
            distance = math.hypot(node[0] - spec["goal_x"], node[1] - spec["goal_y"])
            core = connected_core(facts)
            connected = facts["node_available"][index] and index in core and len(core) >= 2
            arrived = connected and distance <= spec["arrival_radius_m"]
            if arrived and self.arrival_at is None and not spec.get("team_investigation", False):
                self.arrival_at = time_s
            if spec.get("team_investigation", False):
                distances = [
                    math.hypot(n[0] - spec["goal_x"], n[1] - spec["goal_y"])
                    for i, n in enumerate(facts["nodes"])
                    if facts["node_available"][i]
                ]
                active = {i for i, v in enumerate(facts["node_available"]) if v}
                team_connected = bool(active) and active <= core and len(active) >= 2
                team_fraction = sum(d <= spec["team_radius_m"] for d in distances) / len(distances)
                distance = sum(max(0, d - spec["team_radius_m"]) for d in distances) / len(
                    distances
                ) + max(0, min(distances) - spec["arrival_radius_m"])
                connected = team_connected
                arrived = (
                    team_connected
                    and team_fraction == 1
                    and min(distances) <= spec["arrival_radius_m"]
                    and delivery >= spec["team_delivery_target"]
                )
                if arrived and self.arrival_at is None:
                    self.arrival_at = time_s
            success = arrived and raw["goal_coverage_fraction"] >= spec["goal_coverage_target"]
            self.arrival_streak = self.arrival_streak + interval if success else 0.0
            if self.arrival_streak >= spec["dwell_s"] and self.investigation_at is None:
                self.investigation_at = time_s
        target_coverage = self.coverage_reference * spec["recovery_coverage_ratio"]
        recovery_ok = (
            failure
            and delivery >= spec["recovery_delivery_target"]
            and coverage >= target_coverage
            and worst >= spec["recovery_worst_target"]
        )
        # The boundary window contains pre-failure ticks; start the recovery dwell afterwards.
        self.recovery_streak = (
            self.recovery_streak + interval if recovery_ok and time_s > self.failure_at else 0.0
        )
        if self.recovery_streak >= spec["dwell_s"] and self.recovery_at is None:
            self.recovery_at = time_s
        state = {
            "time_s": time_s,
            "done": done,
            "distance_m": distance,
            "team_arrival_fraction": team_fraction,
            "team_connected": team_connected,
            "previous_distance_m": distance
            if self.previous_distance is None
            else self.previous_distance,
            "investigator_connected": connected,
            "connected_arrival": arrived,
            "arrival_streak_s": self.arrival_streak,
            "arrival_at_s": self.arrival_at,
            "investigation_completed_at_s": self.investigation_at,
            "failure_at_s": self.failure_at,
            "recovery_completed_at_s": self.recovery_at,
            "recovery_streak_s": self.recovery_streak,
            "coverage_reference": self.coverage_reference,
            "coverage_target": target_coverage,
            "survivor_delivery": delivery,
            "survivor_fair_service": fair,
            "survivor_worst_service": worst,
            "previous_survivor_health": self.previous_health,
            "survivor_demand_mbps_sum": demand,
            "survivor_delivered_mbps_sum": delivered,
        }
        self.previous_distance = distance
        self.previous_time = time_s
        self.previous_health = min(delivery, fair, coverage)
        facts["mission_state"] = state
        return state
