"""Scripted mission policies and scenario-check imports."""

from types import SimpleNamespace
import numpy as np
import pytest
from scripts.rl.env.geometry import (
    route,
    safe_segment,
    swept_distance,
)
from scripts.rl.policy.scripted import ReferencePolicy, ScriptedMissionPolicy


def _facts_env(facts, gate_s=None):
    env = SimpleNamespace(_protocol=SimpleNamespace(facts=facts))
    if gate_s is not None:
        env.gate_s = gate_s
    return env


WAYPOINT_CONTRACT = {
    "max_controlled_nodes": 2,
    "node_ids": ["a", "b"],
    "slot_node_ids": ["a", "b"],
    "slot_speed_mps": [2, 2],
    "decision_interval_s": 1,
}


@pytest.mark.parametrize(
    "reference,expected",
    [
        (
            {
                "node_order": ["a", "b"],
                "waypoints": {"a": [[10, 0]], "b": [[10, 20]]},
                "start_after_failure": False,
            },
            [1, 4],
        ),
        (
            {
                "node_order": ["a", "b"],
                "waypoints": {"a": [[10, 0]], "b": [[10, 20]]},
                "start_after_failure": False,
                "parallel": True,
            },
            [1, 1],
        ),
        (
            {
                "node_order": ["a", "b"],
                "waypoints": {"a": [[0, -9]], "b": [[0, 30]]},
                "start_after_failure": False,
                "parallel": True,
            },
            [2, 3],
        ),
        (
            {
                "node_order": ["a", "b"],
                "waypoints": {"a": [[10, 0]], "b": [[10, 20]]},
                "start_after_failure": True,
            },
            [4, 4],
        ),
        (
            {
                "node_order": ["a", "b"],
                "waypoints": {"a": [[10, 0]], "b": [[10, 20]]},
                "start_after_failure": False,
                "start_after_s": 5,
            },
            [4, 4],
        ),
        (
            {
                "node_order": ["b", "a"],
                "waypoints": {"a": [[0.5, 0], [10, 0]], "b": [[0, 20]]},
                "start_after_failure": False,
            },
            [1, 4],
        ),
    ],
)
def test_scripted_mission_policy_waypoint_format_expected_values(reference, expected):
    facts = {
        "nodes": [[0, 0, 0], [0, 20, 0]],
        "node_available": [True, True],
        "mission_state": {"time_s": 1},
    }
    mask = np.ones(10, dtype=bool)
    actions = []
    for policy_type in (ScriptedMissionPolicy,):
        policy = policy_type(_facts_env(facts), reference)
        policy.start_episode(201)
        actions.append(policy.act(None, mask, WAYPOINT_CONTRACT).tolist())
    assert actions == [expected]


def test_scripted_mission_policy_waits_for_delivery_trigger_and_mask():
    reference = {
        "node_order": ["a"],
        "waypoints": {"a": [[10, 0]], "b": []},
        "start_after_failure": False,
        "start_below_delivery": 0.5,
    }
    facts = {
        "nodes": [[0, 0, 0], [0, 20, 0]],
        "node_available": [True, True],
        "mission_state": {"time_s": 1, "survivor_delivery": 0.9},
    }
    policy = ScriptedMissionPolicy(_facts_env(facts), reference)
    policy.start_episode(1)
    mask = np.ones(10, dtype=bool)
    assert policy.act(None, mask, WAYPOINT_CONTRACT).tolist() == [4, 4]
    facts["mission_state"]["survivor_delivery"] = 0.2
    mask[1] = False
    assert policy.act(None, mask, WAYPOINT_CONTRACT).tolist() == [4, 4]
    facts["mission_state"]["survivor_delivery"] = 0.9  # stays triggered once started
    assert policy.act(None, np.ones(10, dtype=bool), WAYPOINT_CONTRACT).tolist() == [
        1,
        4,
    ]


ROUTE_CONTRACT = {
    "max_controlled_nodes": 3,
    "num_controlled": 2,
    "node_ids": ["a", "b"],
    "slot_node_ids": ["a", "b", None],
    "slot_speed_mps": [2, 2, None],
    "decision_interval_s": 1,
    "unsafe_separation_m": 1,
}


def test_reference_policy_routes_format_gate_and_swept_reservation():
    facts = {
        "nodes": [[0, 0, 1.5], [3, 5, 1.5]],
        "node_available": [True, True],
        "mission_state": {"time_s": 10},
    }
    reference = {"routes": {"a": [[10, 0, 1.5]], "b": [[3, 15, 1.5]]}}
    mask = np.ones(15, dtype=bool)
    policy = ReferencePolicy(_facts_env(facts, gate_s=20), reference)
    policy.start_episode(201)
    assert policy.act(None, mask, ROUTE_CONTRACT).tolist() == [4, 4, 4]
    policy.env.gate_s = 0
    assert policy.act(None, mask, ROUTE_CONTRACT).tolist() == [1, 3, 4]
    # Moving toward a peer that holds inside the separation margin is not proposed.
    facts["nodes"][1] = [2.5, 0, 1.5]
    reference["routes"]["b"] = [[2.5, 0, 1.5]]
    policy = ReferencePolicy(_facts_env(facts, gate_s=0), reference)
    policy.start_episode(201)
    assert policy.act(None, mask, ROUTE_CONTRACT).tolist() == [4, 4, 4]


def test_reference_policy_random_valid_uses_only_masked_actions():
    facts = {
        "nodes": [[0, 0, 1.5], [3, 0, 1.5]],
        "node_available": [True, True],
        "mission_state": {"time_s": 10},
    }
    mask = np.zeros(15, dtype=bool)
    mask[[2, 4, 5 + 0, 10 + 4]] = True
    policy = ReferencePolicy(
        _facts_env(facts, gate_s=0), {"routes": {"a": [], "b": []}}, random_valid=True
    )
    policy.start_episode(7)
    for _ in range(10):
        a, b, c = policy.act(None, mask, ROUTE_CONTRACT).tolist()
        assert a in (2, 4) and b == 0 and c == 4


def test_scenario_check_geometry_reexports_owners():
    from scripts.rl.scenario_check import geometry

    assert geometry.ReferencePolicy is ReferencePolicy
    assert geometry.route is route and geometry.safe_segment is safe_segment
    assert geometry.swept_distance is swept_distance
