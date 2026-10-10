"""Scored telemetry reductions at warmup boundaries."""

import pytest

from scripts.rl.policy.metrics import episode_metrics


def test_metrics_use_scored_ticks_instead_of_elapsed_ticks():
    records = [{"decision": 1, "facts": {"window": {
        "ticks": 7, "scored_ticks": 3, "demand_mbps_sum": 30,
        "delivered_mbps_sum": 15, "connected_pairs_sum": 3,
        "los_pairs_sum": 6, "flow_ticks_with_demand": 3,
        "unroutable_flow_ticks": 1}}}]
    result = episode_metrics(records, num_links=2)
    assert result == {"delivery_ratio": 0.5, "connectivity": 0.5,
                      "los_fraction": 1.0, "unroutable_fraction": pytest.approx(1 / 3),
                      "first_all_los_decision": 1}


@pytest.mark.parametrize("num_links", [0, 2])
def test_empty_scoring_window_has_no_network_metrics(num_links):
    records = [{"decision": 1, "facts": {"window": {
        "ticks": 7, "scored_ticks": 0, "demand_mbps_sum": 0,
        "delivered_mbps_sum": 0, "connected_pairs_sum": 0,
        "los_pairs_sum": 0, "flow_ticks_with_demand": 0,
        "unroutable_flow_ticks": 0}}}]
    assert all(value is None for value in episode_metrics(records, num_links).values())
