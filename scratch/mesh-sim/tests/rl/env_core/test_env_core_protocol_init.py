"""Direct tests of CentralizedProtocol.validate_init against hand-built init messages.

Expectations come from src/rl/README.md ("Centralized contract", "Message
fields", "Per-decision facts") and the "validate, never coerce" rule in
scripts/rl/env/CLAUDE.md.
"""

import math

import pytest

from scripts.rl.env.protocol import CentralizedProtocol, ProtocolError

from ._helpers import make_init


def _accepts(init: dict) -> CentralizedProtocol:
    return CentralizedProtocol(init)


def _rejects(init: dict, pattern: str) -> None:
    with pytest.raises(ProtocolError, match=pattern):
        CentralizedProtocol(init)


def test_valid_init_is_accepted_and_exposes_properties():
    protocol = _accepts(make_init())
    assert protocol.mask is None and protocol.facts is None
    assert protocol.node_ids == ["node-a", "node-b", "node-c"]
    assert protocol.mask_dim == 15
    assert protocol.bounds["x_max"] == 100.0


def test_protocol_error_is_a_value_error():
    # Callers that catch ValueError (e.g. CLI pre-flight) must see protocol errors.
    assert issubclass(ProtocolError, ValueError)


def test_property_copies_do_not_alias_internal_state():
    protocol = _accepts(make_init())
    protocol.node_ids.append("ghost")
    protocol.bounds["x_max"] = -1.0
    assert protocol.node_ids == ["node-a", "node-b", "node-c"]
    assert protocol.bounds["x_max"] == 100.0


# Contract identity -------------------------------------------------------------

@pytest.mark.parametrize("contract", ["mesh_move_3d_v1", "", None, 1, ["mesh_move_2d_v1"]])
def test_unknown_or_non_string_contract_is_rejected(contract):
    _rejects(make_init(contract=contract), "Unknown init contract")


def test_missing_contract_is_rejected():
    init = make_init()
    del init["contract"]
    _rejects(init, "Unknown init contract")


@pytest.mark.parametrize("dimensions", [3, None, "2", True])
def test_wrong_dimensions_are_rejected(dimensions):
    _rejects(make_init(dimensions=dimensions), "dimensions")


def test_float_dimensions_is_not_coerced():
    # QUESTION: protocol.py:105 compares with `!=`, so 2.0 == 2 slips through
    # although every other integer field rejects floats ("never coerce").
    _rejects(make_init(dimensions=2.0), "dimensions")


@pytest.mark.parametrize("meanings", [
    ["east", "west", "south", "north", "hold"],
    ["west", "east", "south", "north"],
    ["west", "east", "south", "north", "hold", "up"],
    ("west", "east", "south", "north", "hold"),
])
def test_action_meanings_must_match_exactly(meanings):
    _rejects(make_init(action_meanings=meanings), "action_meanings")


# Integer / number field types ----------------------------------------------------

_INT_FIELDS = ["max_controlled_nodes", "num_controlled", "num_mesh_nodes", "obs_dim",
               "mask_dim", "decision_interval_ticks", "num_ticks", "num_decisions"]


@pytest.mark.parametrize("field", _INT_FIELDS)
@pytest.mark.parametrize("bad", [None, "3", True, 3.0])
def test_integer_fields_reject_non_integers(field, bad):
    _rejects(make_init(**{field: bad}), f"{field} must be an integer")


@pytest.mark.parametrize("field", _INT_FIELDS)
def test_integer_fields_missing_are_rejected(field):
    init = make_init()
    del init[field]
    _rejects(init, f"{field} must be an integer")


@pytest.mark.parametrize("field", ["tick_s", "decision_interval_s"])
@pytest.mark.parametrize("bad", [0, 0.0, -0.1, math.nan, math.inf, True, "0.1", None])
def test_time_fields_must_be_finite_positive(field, bad):
    _rejects(make_init(**{field: bad}), f"{field} must be finite and > 0")


@pytest.mark.parametrize("field", ["reward_type", "reward_window", "wall_policy"])
@pytest.mark.parametrize("bad", ["", None, 1])
def test_string_fields_must_be_non_empty(field, bad):
    _rejects(make_init(**{field: bad}), f"{field} must be a non-empty string")


# Slot counts ---------------------------------------------------------------------

def test_zero_active_nodes_rejected():
    _rejects(make_init(num_controlled=0), "num_controlled")


def test_more_active_than_slots_rejected():
    _rejects(make_init(num_controlled=4), "num_controlled")


def test_max_slots_boundary_64_accepted_65_rejected():
    def sized(slots: int) -> dict:
        return make_init(max_controlled_nodes=slots, obs_dim=slots * 8,
                         mask_dim=slots * 5,
                         slot_node_ids=["node-b", "node-c"] + [None] * (slots - 2),
                         slot_speed_mps=[1.0, 1.0] + [None] * (slots - 2))
    _accepts(sized(64))
    _rejects(sized(65), "<= 64")


def test_all_slots_active_no_padding_accepted():
    init = make_init(max_controlled_nodes=2, obs_dim=16, mask_dim=10,
                     slot_node_ids=["node-b", "node-c"], slot_speed_mps=[1.0, 2.0])
    _accepts(init)


def test_single_mesh_node_rejected_and_two_nodes_accepted():
    _rejects(make_init(num_mesh_nodes=1, obs_dim=12, num_links=0, node_ids=["node-a"]),
             "num_mesh_nodes must be >= 2")
    two = make_init(num_mesh_nodes=2, obs_dim=3 * 6, num_links=1,
                    node_ids=["node-b", "node-c"])
    _accepts(two)


@pytest.mark.parametrize("field", ["decision_interval_ticks", "num_ticks", "num_decisions"])
def test_cadence_counts_must_be_at_least_one(field):
    _rejects(make_init(**{field: 0}), field)


def test_obs_dim_formula_enforced():
    _rejects(make_init(obs_dim=23), "obs_dim 23")
    _rejects(make_init(obs_dim=25), "obs_dim 25")


def test_mask_dim_formula_enforced():
    _rejects(make_init(mask_dim=14), "mask_dim 14")


def test_interval_longer_than_episode_rejected():
    _rejects(make_init(decision_interval_ticks=11, num_decisions=1),
             "exceeds num_ticks")


def test_interval_equal_to_episode_accepted():
    _accepts(make_init(decision_interval_ticks=10, decision_interval_s=1.0,
                       num_decisions=1))


@pytest.mark.parametrize("ticks,k,decisions", [(10, 5, 2), (7, 5, 2), (11, 5, 3),
                                               (1, 1, 1), (9, 1, 9)])
def test_num_decisions_is_ceil_of_ticks_over_k(ticks, k, decisions):
    init = make_init(num_ticks=ticks, decision_interval_ticks=k, num_decisions=decisions,
                     decision_interval_s=k * 0.1)
    _accepts(init)
    _rejects(dict(init, num_decisions=decisions + 1), "num_decisions")
    if decisions > 1:
        _rejects(dict(init, num_decisions=decisions - 1), "num_decisions")


# Slot ids and speeds -------------------------------------------------------------

@pytest.mark.parametrize("field", ["slot_node_ids", "slot_speed_mps"])
def test_slot_lists_must_have_m_entries(field):
    init = make_init()
    _rejects(dict(init, **{field: init[field][:2]}), f"{field} must be a list of 3")
    _rejects(dict(init, **{field: None}), f"{field} must be a list of 3")


def test_active_slot_ids_must_be_non_empty_strings():
    _rejects(make_init(slot_node_ids=["node-b", "", None]), "non-string active")
    _rejects(make_init(slot_node_ids=["node-b", 7, None]), "non-string active")
    _rejects(make_init(slot_node_ids=["node-b", None, None]), "non-string active")


def test_duplicate_active_slot_ids_rejected():
    _rejects(make_init(slot_node_ids=["node-b", "node-b", None]), "duplicate active")


def test_padding_slot_ids_must_be_null():
    _rejects(make_init(slot_node_ids=["node-b", "node-c", "node-a"]), "padding must be null")
    _rejects(make_init(slot_node_ids=["node-b", "node-c", ""]), "padding must be null")


@pytest.mark.parametrize("speed", [0.0, -1.0, math.nan, math.inf, None, True, "5"])
def test_active_speeds_must_be_finite_positive(speed):
    _rejects(make_init(slot_speed_mps=[10.0, speed, None]), "slot_speed_mps active")


def test_padding_speeds_must_be_null():
    _rejects(make_init(slot_speed_mps=[10.0, 10.0, 0.0]), "slot_speed_mps padding")


# Facts metadata ------------------------------------------------------------------

@pytest.mark.parametrize("schema", [None, "mesh_facts_v2", ""])
def test_facts_schema_must_be_v1(schema):
    init = make_init(facts_schema=schema)
    if schema is None:
        del init["facts_schema"]
    _rejects(init, "facts_schema")


def test_facts_columns_order_and_names_enforced():
    swapped = {"nodes": ["y", "x", "z", "vx", "vy", "vz", "slot"],
               "links": ["sinr_db", "capacity_mbps", "is_los"]}
    _rejects(make_init(facts_columns=swapped), "facts_columns")
    extra = {"nodes": ["x", "y", "z", "vx", "vy", "vz", "slot"],
             "links": ["sinr_db", "capacity_mbps", "is_los", "rssi"]}
    _rejects(make_init(facts_columns=extra), "facts_columns")


@pytest.mark.parametrize("links", [2, 4, None, 3.0, True])
def test_num_links_must_be_n_choose_2(links):
    _rejects(make_init(num_links=links), "num_links")


def test_node_ids_shape_and_uniqueness():
    _rejects(make_init(node_ids=["node-a", "node-b"]), "node_ids must be a list of 3")
    _rejects(make_init(node_ids="node-a,node-b,node-c"), "node_ids must be a list of 3")
    _rejects(make_init(node_ids=["node-a", "", "node-c"]), "empty or non-string")
    _rejects(make_init(node_ids=["node-a", None, "node-c"]), "empty or non-string")
    _rejects(make_init(node_ids=["node-a", "node-a", "node-c"]), "duplicate")


def test_bounds_must_be_an_object():
    _rejects(make_init(bounds=[0, 100, -50, 100, 0, 50]), "bounds must be an object")


@pytest.mark.parametrize("axis", ["x", "y", "z"])
def test_each_bound_axis_requires_min_below_max(axis):
    base = make_init()["bounds"]
    equal = dict(base, **{f"{axis}_min": 5.0, f"{axis}_max": 5.0})
    _rejects(make_init(bounds=equal), f"{axis}_min < {axis}_max")
    inverted = dict(base, **{f"{axis}_min": 6.0, f"{axis}_max": 5.0})
    _rejects(make_init(bounds=inverted), f"{axis}_min < {axis}_max")


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, None, True, "0"])
def test_bound_endpoints_must_be_finite_numbers(bad):
    bounds = dict(make_init()["bounds"], y_min=bad)
    _rejects(make_init(bounds=bounds), "bounds y endpoints must be finite")


def test_missing_bound_axis_rejected():
    bounds = make_init()["bounds"]
    del bounds["z_max"]
    _rejects(make_init(bounds=bounds), "bounds z endpoints")


def test_integer_bounds_accepted():
    bounds = {"x_min": 0, "x_max": 100, "y_min": -50, "y_max": 100, "z_min": 0,
              "z_max": 50}
    _accepts(make_init(bounds=bounds))
