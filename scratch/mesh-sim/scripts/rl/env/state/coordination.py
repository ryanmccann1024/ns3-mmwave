"""Versioned, opt-in decision history for measured mission phases and motion feedback."""

import math
from scripts.rl.env.state.measurements import measurements


class CoordinationState:
    """Reset per episode; enter settling after 30 s success and fall back on relapse."""

    def __init__(self, parameters=None):
        self.parameters = parameters or {}
        if "mission_code" in self.parameters and self.parameters["mission_code"] not in (
            0,
            1,
            2,
            3,
        ):
            raise ValueError(
                "mission_code must be one of coverage=0, investigation=1, recovery=2, jamming=3"
            )
        self.coverage_goal = self.parameters.get("coverage_goal", 0.9)
        self.previous_time = None
        self.previous_q = None
        self.stage = 0
        self.good_s = self.bad_s = 0.0
        self.previous_nodes = None

    def advance(self, facts, contract, time_s, action=None):
        if self.previous_time is not None and time_s <= self.previous_time:
            raise ValueError("coordination facts require increasing completed-decision time")
        dt = 0.0 if self.previous_time is None else time_s - self.previous_time
        mission = ("coverage", "investigation", "recovery", "jamming")[
            int(
                self.parameters.get(
                    "mission_code",
                    ("coverage", "investigation", "recovery").index(contract["mission"]["kind"]),
                )
            )
        ]
        t = measurements(facts, contract, mission)
        gate = facts.get("deployment")
        w = facts["window"]
        eligible = bool(w["scored_ticks"]) and (
            gate is None or gate["active"] and gate["eligible_ticks"] == w["scored_ticks"]
        )
        if mission == "investigation":
            geometry = t["active_count"] > 0 and t["A"] == 1.0
            good = geometry and bool(t["K"])
            bad = not good
            severe = t["max_target_distance"] > contract["mission"].get("team_radius_m", 50.0) + 10
        else:
            good = t["D"] >= 0.9 and t["W"] >= 0.8
            bad = t["D"] < 0.85 or t["W"] < 0.7
            severe = t["D"] < 0.5 or t["W"] < 0.2
            if mission == "coverage":
                good = good and t["area"] >= self.coverage_goal
                bad = bad or t["area"] < self.coverage_goal - 0.02
        if not eligible or not t["active_count"]:
            self.stage = 0
            self.good_s = self.bad_s = 0.0
        else:
            self.good_s = self.good_s + dt if good else 0.0
            self.bad_s = self.bad_s + dt if bad else 0.0
            if self.stage == 2 and (severe or self.bad_s >= 5.0):
                self.stage = 0
            if self.stage != 2:
                self.stage = 1 if mission == "investigation" and geometry else 0
                if self.good_s >= 30.0:
                    self.stage = 2
        slots = contract["slot_node_ids"]
        moved = []
        previous_action = []
        for i, node in enumerate(contract["node_ids"]):
            slot = slots.index(node) if node in slots else None
            distance = (
                0.0
                if self.previous_nodes is None
                else math.dist(facts["nodes"][i][:2], self.previous_nodes[i][:2])
            )
            cap = contract["slot_speed_mps"][slot] * dt if slot is not None else 0.0
            moved.append(
                min(1.0, distance / cap) if cap > 0 and facts["node_available"][i] else 0.0
            )
            previous_action.append(None if action is None or slot is None else int(action[slot]))
        active_slots = [
            i
            for i, node in enumerate(slots)
            if node is not None and facts["node_available"][contract["node_ids"].index(node)]
        ]
        size = len(active_slots)
        t.update(
            T=sum(moved[i] for i in range(len(moved)) if facts["node_available"][i])
            / t["active_count"]
            if t["active_count"]
            else 0.0,
            B=len(set(facts["safety"].get("boundary_contacted_slots", [])) & set(active_slots))
            / size
            if size
            else 0.0,
            J=len(set(facts["safety"]["peer_rejected_slots"]) & set(active_slots)) / size
            if size
            else 0.0,
        )
        facts["coordination_v1"] = dict(
            version=1,
            mission=mission,
            stage=self.stage,
            good_s=self.good_s,
            bad_s=self.bad_s,
            eligible=eligible,
            coverage_goal=self.coverage_goal,
            terms=t,
            previous_q=t["Q"] if self.previous_q is None else self.previous_q,
            moved_fraction=moved,
            previous_action=previous_action,
        )
        self.previous_nodes = [list(n) for n in facts["nodes"]]
        self.previous_q = t["Q"]
        self.previous_time = time_s
        return facts["coordination_v1"]
