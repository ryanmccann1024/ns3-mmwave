"""Frozen-weight execution schedules: when a saved policy samples, acts greedily or holds.

A schedule never performs an optimizer update or resets the policy; it is not
online learning and cannot be combined with an online protocol. Each schedule
is an optional ``{kind, settings}`` value. Settings are validated against the
kind and never filled with research defaults; every switch is logged with its
time/decision and reason.

- ``initial-sampling``: sample for the first ``initial_sample_decisions``
  eligible decisions, then act deterministically.
- ``stall-burst``: act deterministically; sample a burst when a slot keeps being
  rejected without moving, or when mission progress stalls over
  ``progress_window`` eligible decisions; then cool down; at most ``max_bursts``.
- ``sample-then-deterministic`` / ``sample-then-hold``: sample until coverage
  service qualifies for ``QUALIFICATION_S``, then act deterministically or hold;
  fall back to sampling after a ``RELAPSE_S`` relapse or a severe service loss.
"""
from collections import deque
import math
from pathlib import Path

import numpy as np

from scripts.artifact_io import write_json
from scripts.rl.policy.evaluate import ModelPolicy

SAMPLING_SCHEDULE_VERSION = 1
SAMPLING_KINDS = ("initial-sampling", "stall-burst")
SAMPLING_REQUIRED = {
    "initial-sampling": ("initial_sample_decisions",),
    "stall-burst": ("progress_window", "rejected_window", "rejected_threshold", "movement_threshold_m",
                    "progress_threshold", "burst_decisions", "cooldown_decisions", "max_bursts"),
}
_INTEGER_SETTINGS = {"initial_sample_decisions": 1, "progress_window": 1, "rejected_window": 1,
                     "rejected_threshold": 1, "burst_decisions": 1, "cooldown_decisions": 0, "max_bursts": 0}

# coverage_execution.json version 1 was written with exactly these service rules.
COVERAGE_SCHEDULE_VERSION = 1
COVERAGE_KINDS = ("sample-then-deterministic", "sample-then-hold")
COVERAGE_RULES = dict(
    measurement_s=1.,
    qualification_s=30.,
    qualify_delivery_min=.9,
    qualify_worst_peer_min=.8,
    relapse_s=5.,
    relapse_coverage_margin=.02,
    relapse_delivery_below=.85,
    relapse_worst_peer_below=.7,
    severe_delivery_below=.5,
    severe_worst_peer_below=.2,
)
QUALIFICATION_S = COVERAGE_RULES["qualification_s"]
RELAPSE_S = COVERAGE_RULES["relapse_s"]

SCHEDULE_KINDS = SAMPLING_KINDS + COVERAGE_KINDS
HOLD_ACTION = 4


def validate_schedule(schedule):
    """Resolve ``{kind, settings}``; reject unknown kinds, missing, extra or inconsistent settings."""
    if schedule is None:
        return None
    if not isinstance(schedule, dict) or set(schedule) - {"kind", "settings"} or "kind" not in schedule:
        raise ValueError("schedule must be {kind, settings}")
    kind, settings = schedule["kind"], schedule.get("settings")
    if kind not in SCHEDULE_KINDS:
        raise ValueError(f"unknown schedule kind {kind!r}; expected one of {SCHEDULE_KINDS}")
    if not isinstance(settings, dict):
        raise ValueError(f"schedule {kind} requires a settings object")
    required = SAMPLING_REQUIRED[kind] if kind in SAMPLING_KINDS else ("coverage_target",)
    missing = [key for key in required if key not in settings]
    extra = sorted(set(settings) - set(required))
    if missing or extra:
        raise ValueError(f"schedule {kind}: missing settings {missing}, unexpected settings {extra}")
    for key in required:
        value = settings[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"schedule {kind}: {key} must be a finite number, got {value!r}")
        if key in _INTEGER_SETTINGS and (not isinstance(value, int) or value < _INTEGER_SETTINGS[key]):
            raise ValueError(f"schedule {kind}: {key} must be an integer >= {_INTEGER_SETTINGS[key]}")
    if kind == "stall-burst":
        if settings["rejected_window"] > settings["progress_window"] + 1:
            raise ValueError("stall-burst: rejected_window cannot exceed the retained progress_window + 1 history")
        if settings["rejected_threshold"] > settings["rejected_window"]:
            raise ValueError("stall-burst: rejected_threshold cannot exceed rejected_window")
        if settings["movement_threshold_m"] < 0:
            raise ValueError("stall-burst: movement_threshold_m must be >= 0")
    if kind in COVERAGE_KINDS and not 0 < settings["coverage_target"] <= 1:
        raise ValueError("coverage schedule: coverage_target must be in (0, 1]")
    return {"kind": kind, "settings": dict(settings)}


def schedule_metadata(schedule):
    """Versioned description recorded with an operation that used ``schedule``."""
    if schedule is None:
        return None
    resolved = validate_schedule(schedule)
    if resolved["kind"] in SAMPLING_KINDS:
        return {**resolved, "schedule_version": SAMPLING_SCHEDULE_VERSION, "log_file": "exploration_schedule.json",
                "optimizer_updates": 0, "policy_reset": False}
    return {**resolved, "schedule_version": COVERAGE_SCHEDULE_VERSION, "rules": dict(COVERAGE_RULES),
            "log_file": "coverage_execution.json", "optimizer_updates": 0, "policy_reset": False}


class SamplingSchedule:
    """Pure schedule state; the eligible decision clock starts after event release."""

    def __init__(self, kind, settings):
        resolved = validate_schedule({"kind": kind, "settings": settings})
        self.kind, self.s = kind, resolved["settings"]
        self.count = self.left = self.next_allowed = self.bursts = 0
        window = self.s["progress_window"] + 1 if kind == "stall-burst" else 1
        self.history = deque(maxlen=window)
        self.events = []
        self.last_reason = None

    def sampled(self):
        if self.kind == "initial-sampling":
            return self.count < self.s["initial_sample_decisions"]
        if self.left:
            self.left -= 1
            return True
        if self.count < self.next_allowed or self.bursts >= self.s["max_bursts"] or not self.history:
            return False
        last = self.history[-1]
        if last["success"]:
            return False
        reason = None
        recent = list(self.history)[-self.s["rejected_window"]:]
        if len(recent) == self.s["rejected_window"]:
            for i in range(len(last["moves"])):
                if (sum(h["blocked"][i] for h in recent) >= self.s["rejected_threshold"] and
                        sum(h["moves"][i] for h in recent) < self.s["movement_threshold_m"]):
                    reason = f"blocked-slot-{i}"
                    break
        if reason is None and len(self.history) > self.s["progress_window"]:
            if last["score"] - self.history[0]["score"] < self.s["progress_threshold"]:
                reason = "mission-progress-stall"
        if reason is None:
            return False
        self.bursts += 1
        self.left = self.s["burst_decisions"] - 1
        self.next_allowed = self.count + self.s["burst_decisions"] + self.s["cooldown_decisions"]
        self.events.append(dict(after_eligible_decision=self.count, reason=reason, burst=self.bursts,
                                score_before=last["score"], sample_decisions=self.s["burst_decisions"]))
        self.last_reason = reason
        return True

    def observe(self, score, done, blocked, moves):
        self.count += 1
        self.history.append(dict(score=score, success=done, blocked=blocked, moves=moves))
        for event in self.events:
            if self.count == event["after_eligible_decision"] + event["sample_decisions"]:
                event["score_after"] = score


class SamplingSchedulePolicy(ModelPolicy):
    """Frozen model whose sampling is switched by a :class:`SamplingSchedule`.

    ``case`` needs ``mission`` and, for coverage, ``coverage_target`` (strict success).
    """

    def __init__(self, model, case, kind, settings, output, contract, facts):
        from scripts.rl.env.rewards.objectives import COMPONENT_NAMES
        from scripts.rl.env.rewards import RewardComposer
        super().__init__(model)
        self.case = case
        self.schedule = SamplingSchedule(kind, settings)
        self.output, self.contract = Path(output), contract
        self.previous = [list(p) for p in facts["nodes"]]
        self.composer = RewardComposer([COMPONENT_NAMES[case["mission"]]], [1])
        self.log = []
        self.next_eligible = _eligible(case["mission"], facts)

    def act(self, obs, mask, contract):
        # Reset has zero scored ticks, but coverage/investigation are immediately free.
        free = self.case["mission"] not in ("recovery", "jamming") or self.next_eligible
        self.deterministic = not (free and self.schedule.sampled())
        action = super().act(obs, mask, contract)
        self.pending = action.copy()
        self.sampled_last = not self.deterministic
        return action

    def observe(self, obs, reward, terminated, truncated, info, facts):
        from scripts.rl.policy.mission_metrics import strict_success
        is_eligible = _eligible(self.case["mission"], facts)
        moves, blocked = [], []
        safety = facts["safety"]
        rejected = set(safety["building_rejected_slots"]) | set(safety["peer_rejected_slots"])
        for slot, node in enumerate(self.contract["slot_node_ids"]):
            if node is None:
                moves.append(0.)
                blocked.append(False)
                continue
            i = self.contract["node_ids"].index(node)
            active = facts["node_available"][i]
            moves.append(math.dist(self.previous[i][:2], facts["nodes"][i][:2]) if active else 0.)
            blocked.append(active and self.pending[slot] != HOLD_ACTION and slot in rejected)
        if is_eligible:
            score = self.composer.compose(facts["window"], 0, self.contract,
                                          self.composer.context(facts, self.contract)).total
            ok = strict_success(self.case, dict(facts=facts))
            self.schedule.observe(score, ok, blocked, moves)
            self.log.append(dict(time_s=info["time_s"], eligible_decision=self.schedule.count,
                                 sampled=self.sampled_last, score=score, strict_success=ok, travel_m=sum(moves),
                                 boundary_contacts=len(safety["boundary_contacted_slots"]),
                                 blocked_slots=[i for i, v in enumerate(blocked) if v]))
        self.previous = [list(p) for p in facts["nodes"]]
        # The gate transition is seen at the boundary, one action before a fully eligible window.
        self.next_eligible = (facts.get("deployment") or {}).get("active", True)
        if terminated or truncated:
            self.output.mkdir(parents=True, exist_ok=True)
            write_json(self.output / "exploration_schedule.json", dict(
                kind=self.schedule.kind, settings=self.schedule.s, updates=0, policy_reset=False,
                eligible_decisions=self.schedule.count, events=self.schedule.events, decisions=self.log))


def _eligible(mission, facts):
    from scripts.rl.policy.online_adaptation import eligible
    return eligible(mission, facts)


class CoverageSchedule:
    """One-second measurements; no future outcome or optimizer controls switching."""

    def __init__(self, kind, target):
        validate_schedule({"kind": kind, "settings": {"coverage_target": target}})
        self.kind, self.target = kind, target
        self.state = "sampled"
        self.qualified = self.relapse = 0.
        self.events = []

    def observe(self, time_s, area, delivery, worst, dt=COVERAGE_RULES["measurement_s"]):
        r = COVERAGE_RULES
        if self.state == "sampled":
            good = area >= self.target and delivery >= r["qualify_delivery_min"] and worst >= r["qualify_worst_peer_min"]
            self.qualified = self.qualified + dt if good else 0.
            if self.qualified >= r["qualification_s"]:
                self.state = "hold" if self.kind.endswith("hold") else "deterministic"
                self.relapse = 0.
                self.events.append(dict(time_s=time_s, state=self.state, reason="30 s qualification"))
        else:
            severe = delivery < r["severe_delivery_below"] or worst < r["severe_worst_peer_below"]
            poor = (area < self.target - r["relapse_coverage_margin"] or delivery < r["relapse_delivery_below"]
                    or worst < r["relapse_worst_peer_below"])
            self.relapse = self.relapse + dt if poor else 0.
            if severe or self.relapse >= r["relapse_s"]:
                self.state = "sampled"
                self.qualified = self.relapse = 0.
                self.events.append(dict(time_s=time_s, state=self.state,
                                        reason="severe service loss" if severe else "5 s relapse"))


class CoverageSchedulePolicy(ModelPolicy):
    def __init__(self, model, kind, target, output):
        super().__init__(model, deterministic=False)
        self.schedule = CoverageSchedule(kind, target)
        self.output, self.decisions = Path(output), []

    def act(self, obs, mask, contract):
        self.executed_state = self.schedule.state
        self.deterministic = self.executed_state == "deterministic"
        if self.executed_state == "hold":
            return np.full(len(mask) // 5, HOLD_ACTION, dtype=np.int64)
        return super().act(obs, mask, contract)

    def observe(self, obs, reward, terminated, truncated, info, facts):
        window = facts["window"]
        demand, delivered = window["demand_mbps_sum"], window["delivered_mbps_sum"]
        service = [min(1., v / d) for (d, v), alive in zip(facts["node_service"], facts["node_available"])
                   if alive and d > 1e-9]
        delivery = delivered / demand if demand > 1e-9 else 0.
        worst = min(service) if service else 0.
        area = facts["coverage"]["fraction"]
        if window["scored_ticks"]:
            self.schedule.observe(info["time_s"], area, delivery, worst)
        self.decisions.append(dict(time_s=info["time_s"], executed_state=self.executed_state,
                                   next_state=self.schedule.state, area=area, delivery=delivery, worst_peer=worst,
                                   qualification_s=self.schedule.qualified, relapse_s=self.schedule.relapse))
        if terminated or truncated:
            self.output.mkdir(parents=True, exist_ok=True)
            write_json(self.output / "coverage_execution.json", dict(
                coverage_execution_version=COVERAGE_SCHEDULE_VERSION, kind=self.schedule.kind,
                target=self.schedule.target, optimizer_updates=0, hand_designed_hold=self.schedule.kind.endswith("hold"),
                events=self.schedule.events, decisions=self.decisions))


def schedule_policy(model, schedule, case, output, contract, facts):
    """Build the frozen schedule policy for a validated ``schedule``."""
    resolved = validate_schedule(schedule)
    if resolved["kind"] in SAMPLING_KINDS:
        return SamplingSchedulePolicy(model, case, resolved["kind"], resolved["settings"], output, contract, facts)
    return CoverageSchedulePolicy(model, resolved["kind"], resolved["settings"]["coverage_target"], output)
