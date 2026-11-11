"""Sampling schedules and coverage qualification."""

import pytest
from scripts.rl.policy.schedules import (
    COVERAGE_RULES,
    COVERAGE_SCHEDULE_VERSION,
    CoverageSchedule,
    CoverageSchedulePolicy,
    SamplingSchedule,
    schedule_metadata,
    validate_schedule,
)
from scripts.rl.tests.support.operation import INITIAL, STALL

pytest.importorskip("sb3_contrib")


def test_initial_sampling_exactly_n_eligible_decisions():
    schedule, flags = SamplingSchedule("initial-sampling", INITIAL), []
    for _ in range(100):
        flags.append(schedule.sampled())
        schedule.observe(0.1, False, [False], [0.0])
    assert flags == [True] * 60 + [False] * 40


def test_stall_trigger_burst_cooldown_and_limit():
    schedule, flags = SamplingSchedule("stall-burst", STALL), []
    for _ in range(260):
        flags.append(schedule.sampled())
        schedule.observe(0.1, False, [True], [0.0])
    assert (
        flags[:20] == [False] * 20
        and flags[20:40] == [True] * 20
        and flags[40:80] == [False] * 40
    )
    assert len(schedule.events) == 3 and sum(flags) == 60
    assert schedule.events[0]["reason"] == "blocked-slot-0" and all(
        "score_after" in e for e in schedule.events
    )
    good = SamplingSchedule("stall-burst", STALL)
    for _ in range(100):
        assert not good.sampled()
        good.observe(1.0, True, [False], [0.0])
    assert not good.events


def test_stall_progress_trigger_when_slots_move():
    schedule = SamplingSchedule("stall-burst", STALL)
    for _ in range(80):
        schedule.sampled()
        schedule.observe(0.1, False, [True], [5.0])
    assert schedule.events[0]["reason"] == "mission-progress-stall"
    assert schedule.events[0]["after_eligible_decision"] == 61


@pytest.mark.parametrize(
    "kind,state",
    [("sample-then-deterministic", "deterministic"), ("sample-then-hold", "hold")],
)
def test_coverage_qualification_relapse_and_severe_loss(kind, state):
    schedule = CoverageSchedule(kind, 0.6)
    for t in range(1, 30):
        schedule.observe(t, 0.65, 0.95, 0.85)
    assert schedule.state == "sampled"
    schedule.observe(30, 0.65, 0.95, 0.85)
    assert (
        schedule.state == state
        and schedule.events[-1]["reason"] == "30 s qualification"
    )
    for t in range(31, 35):
        schedule.observe(t, 0.57, 0.95, 0.85)
    assert schedule.state == state
    schedule.observe(35, 0.57, 0.95, 0.85)
    assert (
        schedule.state == "sampled" and schedule.events[-1]["reason"] == "5 s relapse"
    )
    for t in range(36, 66):
        schedule.observe(t, 0.65, 0.95, 0.85)
    schedule.observe(66, 0.65, 0.95, 0.19)
    assert (
        schedule.state == "sampled"
        and schedule.events[-1]["reason"] == "severe service loss"
    )


def test_coverage_rules_are_the_documented_versioned_constants():
    assert COVERAGE_RULES["qualification_s"] == 30 and COVERAGE_RULES["relapse_s"] == 5
    meta = schedule_metadata(
        {"kind": "sample-then-hold", "settings": {"coverage_target": 0.6}}
    )
    assert (
        meta["schedule_version"] == COVERAGE_SCHEDULE_VERSION
        and meta["rules"] == COVERAGE_RULES
        and meta["optimizer_updates"] == 0
    )


def test_coverage_policy_uses_elapsed_scored_time(tmp_path):
    policy = CoverageSchedulePolicy(
        None, "sample-then-hold", 0.6, tmp_path, tick_s=0.25
    )
    policy.executed_state = "sampled"
    facts = {
        "window": {"scored_ticks": 2, "demand_mbps_sum": 10, "delivered_mbps_sum": 10},
        "node_service": [[10, 10]],
        "node_available": [True],
        "coverage": {"fraction": 0.8},
    }
    for decision in range(1, 60):
        policy.observe(None, 0, False, False, {"time_s": decision * 0.5}, facts)
    assert policy.schedule.state == "sampled"
    policy.observe(None, 0, False, False, {"time_s": 30.0}, facts)
    assert policy.schedule.events[-1]["time_s"] == 30.0
    assert policy.schedule.state == "hold"


@pytest.mark.parametrize(
    "schedule,match",
    [
        ({"kind": "initial-sampling", "settings": {}}, "missing"),
        (
            {"kind": "initial-sampling", "settings": {**INITIAL, "max_bursts": 3}},
            "unexpected",
        ),
        (
            {
                "kind": "stall-burst",
                "settings": {k: v for k, v in STALL.items() if k != "progress_window"},
            },
            "missing",
        ),
        (
            {"kind": "stall-burst", "settings": {**STALL, "rejected_window": 62}},
            "rejected_window",
        ),
        (
            {"kind": "stall-burst", "settings": {**STALL, "rejected_threshold": 21}},
            "rejected_threshold",
        ),
        (
            {"kind": "stall-burst", "settings": {**STALL, "burst_decisions": 0}},
            "burst_decisions",
        ),
        ({"kind": "sample-then-hold", "settings": {}}, "missing"),
        (
            {"kind": "sample-then-hold", "settings": {"coverage_target": 1.5}},
            "coverage_target",
        ),
        ({"kind": "explore", "settings": {}}, "unknown"),
    ],
)
def test_schedule_settings_refused_without_defaults(schedule, match):
    with pytest.raises(ValueError, match=match):
        validate_schedule(schedule)
