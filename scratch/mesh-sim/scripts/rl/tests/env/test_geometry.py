"""Geometry and physical route checks."""

import pytest
from scripts.rl.env.geometry import (
    physical_audit,
    route,
    safe_segment,
    segment_hits,
    swept_distance,
)


BOX = {"x_min": 20, "x_max": 40, "y_min": -5, "y_max": 30, "z_min": 0, "z_max": 10}


SEGMENTS = [
    ([5, 20, 1.5], [35, 20, 1.5], BOX, 2),
    ([5, 20, 20], [35, 20, 20], BOX, 2),
    ([5, 20, 9], [35, 20, 9], BOX, 2),
    ([5, 5, 1.5], [10, 35, 1.5], BOX, 0),
    ([30, 10, 5], [30, 10, 5], BOX, 0),
    ([0, 0, 0], [100, 100, 0], BOX, 0),
    ([19, -100, 5], [19, 100, 5], BOX, 0.5),
    ([19, -100, 5], [19, 100, 5], BOX, 1.5),
]


def test_segment_hits_fixed_values():
    assert [segment_hits(a, b, box, c) for a, b, box, c in SEGMENTS] == [
        True,
        False,
        True,
        False,
        True,
        True,
        False,
        True,
    ]
    assert safe_segment([0, 0, 1.5], [10, 0, 1.5], [BOX]) and not safe_segment(
        [0, 20, 1.5], [50, 20, 1.5], [BOX]
    )


def test_physical_audit_expected_values():
    contract = {
        "navigation": {"buildings": [BOX], "building_clearance_m": 2},
        "unsafe_separation_m": 5,
    }
    safe = [
        {
            "facts": {
                "nodes": [[0, 0, 20], [10, 50, 1.5]],
                "node_available": [True, True],
            }
        },
        {
            "facts": {
                "nodes": [[3, 0, 20], [10, 45, 1.5]],
                "node_available": [True, True],
            }
        },
    ]
    assert physical_audit(safe, contract) == {
        "building_penetrations": 0,
        "peer_collisions": 0,
        "min_swept_peer_distance_m": pytest.approx((45**2 + 7**2 + 18.5**2) ** 0.5),
    }
    crossing = [
        {"facts": {"nodes": [[0, 60, 0], [10, 60, 0]], "node_available": [True, True]}},
        {"facts": {"nodes": [[10, 60, 0], [0, 60, 0]], "node_available": [True, True]}},
    ]
    with pytest.raises(ValueError, match="peer collision"):
        physical_audit(crossing, contract)
    through = [
        {"facts": {"nodes": [[0, 10, 1.5]], "node_available": [True]}},
        {"facts": {"nodes": [[60, 10, 1.5]], "node_available": [True]}},
    ]
    with pytest.raises(ValueError, match="crosses a building"):
        physical_audit(through, contract)


def test_route_and_swept_distance_fixed_values():
    # Expected values come from the scenario_check implementation moved verbatim.
    assert route((0, 0, 1.5), (60, 10, 1.5), [BOX]) == [
        [0, 10, 1.5],
        [15, 10, 1.5],
        [15, 35, 1.5],
        [45, 35, 1.5],
        [45, 10, 1.5],
        [60, 10, 1.5],
    ]
    assert route((0, 0, 20), (60, 10, 20), [BOX]) == [[0, 10, 20], [60, 10, 20]]
    assert route((12, 12, 1.5), (12, 12, 1.5), []) == [[12, 12, 1.5]]
    with pytest.raises(ValueError, match="start cannot reach"):
        route((30, 10, 1.5), (60, 10, 1.5), [BOX])
    assert swept_distance((0, 0, 0), (10, 0, 0), (10, 0, 0), (0, 0, 0)) == 0
    assert swept_distance((0, 0, 20), (10, 0, 20), (10, 0, 1.5), (0, 0, 1.5)) == 18.5
