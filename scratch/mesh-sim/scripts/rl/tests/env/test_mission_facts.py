"""Behavior checks preserved from the experiment pilots; no native simulation."""

import pytest

from scripts.rl.env.state.mission import MissionState
from scripts.rl.env.mission_protocol import validate_mission_facts
from scripts.rl.env.rewards import RewardComposer
from scripts.sim_support import find_mesh_root

ROOT = find_mesh_root()
INPUTS = ROOT / "inputs/custom/10-16"


def state_inputs(kind="investigation"):
    contract = {
        "mission": {
            "kind": kind,
            "investigator_id": "drone-1",
            "goal_x": 0,
            "goal_y": 0,
            "arrival_radius_m": 15,
            "coverage_radius_m": 50,
            "dwell_s": 2,
            "goal_coverage_target": 0.8,
            "recovery_delivery_target": 0.9,
            "recovery_coverage_ratio": 0.9,
            "recovery_worst_target": 0.8,
            "progress_distance_scale_m": 100,
            "shaping_gamma": 0.995,
        },
        "node_ids": ["drone-1", "ground-1", "vehicle-1"],
    }
    facts = {
        "nodes": [[0, 0, 20], [20, 0, 1.5], [40, 0, 1.5]],
        "links": [[10, 5, 1]] * 3,
        "coverage": {"fraction": 1},
        "node_available": [True] * 3,
        "mission": {
            "goal_coverage_fraction": 1,
            "survivor_demand_mbps_sum": 12,
            "survivor_delivered_mbps_sum": 12,
            "survivor_node_service": [[8, 8]] * 3,
        },
    }
    return facts, contract


def test_connected_investigation_requires_dwell_and_completion_is_one_time():
    facts, c = state_inputs()
    tracker = MissionState()
    tracker.advance(facts, c, 0)
    s = tracker.advance(facts, c, 1)
    assert s["investigation_completed_at_s"] is None
    s = tracker.advance(facts, c, 2)
    assert s["investigation_completed_at_s"] == 2
    composer = RewardComposer(["investigation_complete"], [10])
    window = {"scored_ticks": 2}
    context = {"mission_state": s, "mission": facts["mission"]}
    assert composer.compose(window, 0, c, context).total == 10
    s = tracker.advance(facts, c, 3)
    assert composer.compose(window, 0, c, context).total == 10  # snapshot remains unchanged
    assert (
        composer.compose(window, 0, c, {"mission_state": s, "mission": facts["mission"]}).total == 0
    )
    facts["links"] = [[-999, 0, 0]] * 3
    assert not MissionState().advance(facts, c, 1)["connected_arrival"]


def test_dwell_resets_if_local_service_or_connection_is_lost():
    f, c = state_inputs()
    s = MissionState()
    s.advance(f, c, 0)
    s.advance(f, c, 1)
    f["mission"]["goal_coverage_fraction"] = 0.5
    assert s.advance(f, c, 2)["arrival_streak_s"] == 0
    f["mission"]["goal_coverage_fraction"] = 1
    assert s.advance(f, c, 3)["investigation_completed_at_s"] is None
    assert s.advance(f, c, 4)["investigation_completed_at_s"] == 4


def test_recovery_uses_survivors_and_sustained_thresholds_after_failure():
    f, c = state_inputs("recovery")
    s = MissionState()
    s.advance(f, c, 0)
    s.advance(f, c, 1)
    f["node_available"] = [True, False, True]
    f["mission"]["survivor_node_service"] = [[4, 4], [0, 0], [4, 4]]
    f["mission"].update(survivor_demand_mbps_sum=4, survivor_delivered_mbps_sum=4)
    assert s.advance(f, c, 2)["recovery_completed_at_s"] is None
    assert s.advance(f, c, 3)["recovery_completed_at_s"] is None
    result = s.advance(f, c, 4)
    assert result["recovery_completed_at_s"] == 4
    assert result["coverage_target"] == pytest.approx(0.9)
    assert result["survivor_worst_service"] == 1
    assert MissionState().advance(f, c, 0)["recovery_completed_at_s"] is None
    f["node_available"] = [True, True, True]
    with pytest.raises(ValueError, match="cannot become available"):
        s.advance(f, c, 5)


def test_potential_progress_telescopes_with_matching_discount():
    f, c = state_inputs()
    gamma = 0.99
    reward = RewardComposer(["goal_progress"], [0.5], {"goal_progress": {"gamma": gamma}})
    total = 0
    for i, (old, new) in enumerate([(100, 50), (50, 80), (80, 0)]):
        s = {"previous_distance_m": old, "distance_m": new, "done": i == 2}
        total += (
            gamma**i
            * reward.compose(
                {"scored_ticks": 1}, 0, c, {"mission_state": s, "mission": f["mission"]}
            ).total
        )
    assert total == pytest.approx(0.5)


def test_offline_mask_and_accounting_validation():
    f, c = state_inputs("recovery")
    c.update(num_mesh_nodes=3, slot_node_ids=c["node_ids"])
    f["node_available"][1] = False
    with pytest.raises(ValueError, match="hold-only"):
        validate_mission_facts(f, c, [1, 1, 1, 1, 1] * 3)
    f["mission"]["survivor_delivered_mbps_sum"] = 13
    with pytest.raises(ValueError, match="out of range"):
        validate_mission_facts(f, c, [0, 0, 0, 0, 1] * 3)
