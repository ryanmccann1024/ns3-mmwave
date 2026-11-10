"""Arrival rewards use the current available peers and horizontal target radius."""

import copy
import pytest
from scripts.rl.tests.env.test_proximity_and_compact_inputs import saved_episode, value


def test_arrival_current_available_fraction_and_departure():
    h, rows = saved_episode()
    f = copy.deepcopy(rows[100]["facts"])
    c = h["contract"]
    goal = [c["mission"]["goal_x"], c["mission"]["goal_y"]]
    for n in f["nodes"]:
        n[:2] = goal
    assert value("available_target_arrival_fraction_v1", f, c).total == 1
    f["nodes"][0][0] += 51
    assert value("available_target_arrival_fraction_v1", f, c).total == pytest.approx(2 / 3)
    f["node_available"][0] = False
    assert value("available_target_arrival_fraction_v1", f, c).total == 1
    f["node_available"] = [False] * 3
    assert value("available_target_arrival_fraction_v1", f, c).total == 0


def test_arrival_horizontal_radius_and_gate():
    h, rows = saved_episode()
    f = copy.deepcopy(rows[100]["facts"])
    c = h["contract"]
    for n in f["nodes"]:
        n[:3] = [c["mission"]["goal_x"] + 50, c["mission"]["goal_y"], 999]
    assert value("available_target_arrival_fraction_v1", f, c).total == 1
    f["deployment"] = {"active": False, "eligible_ticks": 0}
    assert value("available_target_arrival_fraction_v1", f, c).total == 0
    c = copy.deepcopy(c)
    c["mission"]["kind"] = "coverage"
    with pytest.raises(ValueError, match="requires investigation"):
        value("available_target_arrival_fraction_v1", f, c)
