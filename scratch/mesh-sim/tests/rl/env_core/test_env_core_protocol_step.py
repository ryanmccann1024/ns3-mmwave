"""Direct tests of step/facts/window validation, joint actions, and LegacyProtocol.

Expectations come from src/rl/README.md (step fields, mask order, cadence,
partial windows, facts tables, window invariants, "Python replies with exactly
M integers in [0,4]") and the "raise ProtocolError, never coerce" rule in
scripts/rl/env/CLAUDE.md.
"""

import math

import numpy as np
import pytest

from scripts.rl.env.protocol import CentralizedProtocol, LegacyProtocol, ProtocolError

from ._helpers import clone, episode_steps, make_init, make_legacy_step, make_step


@pytest.fixture
def init() -> dict:
    return make_init()


@pytest.fixture
def protocol(init) -> CentralizedProtocol:
    return CentralizedProtocol(init)


def _reset(protocol, init):
    return protocol.validate_step(make_step(init, 0, 0, 1), first=True)


def _bad_first(protocol, msg, pattern):
    with pytest.raises(ProtocolError, match=pattern):
        protocol.validate_step(msg, first=True)


# Happy path ----------------------------------------------------------------------

def test_full_episode_validates_and_exposes_mask_and_facts(protocol, init):
    steps = episode_steps(init)
    obs = protocol.validate_step(steps[0], first=True)
    assert obs.dtype == np.float64 and obs.shape == (24,)
    assert protocol.mask.dtype == np.int8 and protocol.mask.shape == (15,)
    assert protocol.facts is steps[0]["facts"]
    for step in steps[1:]:
        protocol.validate_step(step)
    assert steps[-1]["done"] and steps[-1]["tick"] == 10


def test_partial_final_window_is_required():
    # num_ticks 7, k 5 -> windows of 5 then 2 ticks (README "Partial windows").
    init = make_init(num_ticks=7, num_decisions=2)
    protocol = CentralizedProtocol(init)
    steps = episode_steps(init)
    assert [s["ticks_in_step"] for s in steps] == [1, 5, 2]
    for index, step in enumerate(steps):
        protocol.validate_step(step, first=index == 0)


def test_partial_window_with_full_length_rejected():
    init = make_init(num_ticks=7, num_decisions=2)
    protocol = CentralizedProtocol(init)
    protocol.validate_step(make_step(init, 0, 0, 1), first=True)
    protocol.validate_step(make_step(init, 5, 1, 5))
    # The final window covers ticks 6-7, so claiming 5 ticks is a violation.
    with pytest.raises(ProtocolError):
        protocol.validate_step(make_step(init, 10, 2, 5, done=True))


def test_single_tick_cadence_episode():
    init = make_init(num_ticks=3, decision_interval_ticks=1, decision_interval_s=0.1,
                     num_decisions=3)
    protocol = CentralizedProtocol(init)
    for index, step in enumerate(episode_steps(init)):
        protocol.validate_step(step, first=index == 0)


def test_extra_message_keys_are_tolerated(protocol, init):
    # The fake simulator already sends `last_action`; unknown keys are not a violation.
    protocol.validate_step(make_step(init, 0, 0, 1, last_action=None, extra=1),
                           first=True)


# Type, obs, and mask checks ------------------------------------------------------

@pytest.mark.parametrize("kind", ["init", "STEP", None])
def test_message_type_must_be_step(protocol, init, kind):
    _bad_first(protocol, make_step(init, 0, 0, 1, type=kind), "Expected a 'step'")


@pytest.mark.parametrize("length", [0, 23, 25])
def test_obs_length_must_equal_obs_dim(protocol, init, length):
    _bad_first(protocol, make_step(init, 0, 0, 1, obs=[0.0] * length), "obs length")


def test_obs_must_be_a_list(protocol, init):
    _bad_first(protocol, make_step(init, 0, 0, 1, obs={"x": 1}), "obs length None")


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True, "1.0", None])
def test_obs_values_must_be_finite_numbers(protocol, init, value):
    msg = make_step(init, 0, 0, 1)
    msg["obs"][3] = value
    _bad_first(protocol, msg, r"obs\[3\] is not a finite number")


def test_sinr_sentinel_passes_through_obs(protocol, init):
    msg = make_step(init, 0, 0, 1)
    msg["obs"][4] = -999.0
    obs = protocol.validate_step(msg, first=True)
    assert obs[4] == -999.0


def test_padded_slot_obs_must_be_zero(protocol, init):
    msg = make_step(init, 0, 0, 1)
    msg["obs"][16] = 1.0           # first value of padded slot 2
    _bad_first(protocol, msg, "padded slot 2 observation must be all zero")


@pytest.mark.parametrize("length", [10, 14, 16])
def test_mask_length_must_equal_mask_dim(protocol, init, length):
    _bad_first(protocol, make_step(init, 0, 0, 1, mask=[1] * length), "mask length")


@pytest.mark.parametrize("value", [2, -1, True, 1.0, "1", None])
def test_mask_entries_must_be_integer_zero_or_one(protocol, init, value):
    msg = make_step(init, 0, 0, 1)
    msg["mask"][2] = value
    _bad_first(protocol, msg, r"mask\[2\] is not 0 or 1")


def test_hold_masked_out_in_active_slot_rejected(protocol, init):
    msg = make_step(init, 0, 0, 1)
    msg["mask"][9] = 0                 # slot 1 hold
    _bad_first(protocol, msg, "hold is masked out in slot 1")


def test_all_zero_active_mask_rejected(protocol, init):
    msg = make_step(init, 0, 0, 1)
    msg["mask"][0:5] = [0, 0, 0, 0, 0]
    _bad_first(protocol, msg, "hold is masked out in slot 0")


def test_active_slot_with_only_hold_accepted(protocol, init):
    msg = make_step(init, 0, 0, 1)
    msg["mask"][0:5] = [0, 0, 0, 0, 1]
    protocol.validate_step(msg, first=True)
    assert list(protocol.mask[0:5]) == [0, 0, 0, 0, 1]


def test_padded_slot_mask_must_be_hold_only(protocol, init):
    msg = make_step(init, 0, 0, 1)
    msg["mask"][10:15] = [1, 0, 0, 0, 1]
    _bad_first(protocol, msg, "padded slot 2 mask")


# Reward / done / counters --------------------------------------------------------

@pytest.mark.parametrize("reward", [math.nan, math.inf, True, "1", None])
def test_reward_must_be_finite_number(protocol, init, reward):
    msg = make_step(init, 0, 0, 1)
    msg["reward"] = reward
    _bad_first(protocol, msg, "reward is not a finite")


@pytest.mark.parametrize("done", [0, 1, "false", None])
def test_done_must_be_boolean(protocol, init, done):
    _bad_first(protocol, make_step(init, 0, 0, 1, done=done), "done must be a boolean")


@pytest.mark.parametrize("field", ["tick", "decision", "ticks_in_step"])
@pytest.mark.parametrize("bad", [-1, 0.0, True, None, "0"])
def test_counters_must_be_non_negative_integers(protocol, init, field, bad):
    msg = make_step(init, 0, 0, 1)
    msg[field] = bad
    _bad_first(protocol, msg, f"{field} must be a non-negative integer")


@pytest.mark.parametrize("bad", [math.nan, math.inf, None, "0.0", True])
def test_time_s_must_be_finite(protocol, init, bad):
    _bad_first(protocol, make_step(init, 0, 0, 1, time_s=bad), "time_s is not a finite")


@pytest.mark.parametrize("bad", [[3], [-1], [True], [0.0], "0", None, [None]])
def test_revalidated_slots_must_be_slot_indices(protocol, init, bad):
    _bad_first(protocol, make_step(init, 0, 0, 1, revalidated_slots=bad),
               "revalidated_slots")


def test_revalidated_padded_slot_index_accepted(protocol, init):
    # README example: padding action 0 is revalidated and reported as slot 2.
    _reset(protocol, init)
    protocol.validate_step(make_step(init, 5, 1, 5, revalidated_slots=[2]))


@pytest.mark.parametrize("tick,decision,window", [(1, 0, 1), (0, 1, 1), (0, 0, 0),
                                                  (0, 0, 5)])
def test_reset_message_must_be_tick0_decision0_window1(protocol, init, tick, decision,
                                                       window):
    msg = make_step(init, 0, 0, 1)
    msg.update(tick=tick, decision=decision, ticks_in_step=window, time_s=tick * 0.1)
    msg["facts"]["window"]["ticks"] = window
    msg["facts"]["window"]["legacy_reward_sum"] = float(window)
    _bad_first(protocol, msg, "reset message must be tick 0")


# Monotonicity and cadence ----------------------------------------------------------

def test_tick_must_advance(protocol, init):
    _reset(protocol, init)
    msg = make_step(init, 0, 1, 1)
    with pytest.raises(ProtocolError, match="tick 0 does not advance past 0"):
        protocol.validate_step(msg)


def test_tick_going_backward_rejected(protocol, init):
    _reset(protocol, init)
    protocol.validate_step(make_step(init, 5, 1, 5))
    with pytest.raises(ProtocolError, match="does not advance"):
        protocol.validate_step(make_step(init, 4, 2, 5))


@pytest.mark.parametrize("decision", [0, 2, 3])
def test_decision_must_increase_by_one(protocol, init, decision):
    _reset(protocol, init)
    with pytest.raises(ProtocolError, match=f"decision {decision} does not follow 0"):
        protocol.validate_step(make_step(init, 5, decision, 5))


def test_time_s_must_advance(protocol, init):
    _reset(protocol, init)
    with pytest.raises(ProtocolError, match="time_s 0.0 does not advance"):
        protocol.validate_step(make_step(init, 5, 1, 5, time_s=0.0))


def test_window_length_must_match_cadence(protocol, init):
    _reset(protocol, init)
    msg = make_step(init, 4, 1, 4)
    with pytest.raises(ProtocolError, match="ticks_in_step 4 is not the expected window 5"):
        protocol.validate_step(msg)


def test_window_length_must_match_tick_delta(protocol, init):
    _reset(protocol, init)
    # Claims a 5-tick window but tick jumped by 6.
    msg = make_step(init, 6, 1, 5)
    with pytest.raises(ProtocolError, match="ticks_in_step"):
        protocol.validate_step(msg)


def test_tick_past_num_ticks_rejected():
    init = make_init(num_ticks=10, decision_interval_ticks=5, num_decisions=2)
    protocol = CentralizedProtocol(init)
    protocol.validate_step(make_step(init, 0, 0, 1), first=True)
    protocol.validate_step(make_step(init, 5, 1, 5))
    protocol.validate_step(make_step(init, 10, 2, 5))
    # A message after the terminal one must not be accepted.
    with pytest.raises(ProtocolError):
        protocol.validate_step(make_step(init, 15, 3, 5, done=True))


def test_time_s_must_equal_tick_times_tick_s(protocol, init):
    _reset(protocol, init)
    with pytest.raises(ProtocolError, match="tick\\*tick_s"):
        protocol.validate_step(make_step(init, 5, 1, 5, time_s=0.5 + 1e-5))


def test_time_s_within_tolerance_accepted(protocol, init):
    _reset(protocol, init)
    protocol.validate_step(make_step(init, 5, 1, 5, time_s=0.5 + 1e-7))


def test_done_must_match_final_tick(protocol, init):
    _reset(protocol, init)
    with pytest.raises(ProtocolError, match="done True disagrees with tick 5"):
        protocol.validate_step(make_step(init, 5, 1, 5, done=True))
    protocol.validate_step(make_step(init, 5, 1, 5))
    with pytest.raises(ProtocolError, match="done False disagrees with tick 10"):
        protocol.validate_step(make_step(init, 10, 2, 5, done=False))


def test_rejected_message_leaves_state_unchanged(protocol, init):
    _reset(protocol, init)
    mask_before = protocol.mask.copy()
    facts_before = protocol.facts
    bad = make_step(init, 5, 1, 5)
    bad["facts"]["window"]["ticks"] = 4
    bad["mask"][0] = 0
    with pytest.raises(ProtocolError):
        protocol.validate_step(bad)
    assert np.array_equal(protocol.mask, mask_before)
    assert protocol.facts is facts_before
    # The correct next message still validates: nothing advanced.
    protocol.validate_step(make_step(init, 5, 1, 5))


def test_returned_mask_is_independent_of_message(protocol, init):
    msg = make_step(init, 0, 0, 1)
    protocol.validate_step(msg, first=True)
    msg["mask"][0] = 0
    assert protocol.mask[0] == 1


# Facts: nodes ----------------------------------------------------------------------

def _with_facts(init, mutate):
    msg = make_step(init, 0, 0, 1)
    mutate(msg["facts"])
    return msg


@pytest.mark.parametrize("facts", [None, [], "x"])
def test_facts_must_be_object(protocol, init, facts):
    _bad_first(protocol, make_step(init, 0, 0, 1, facts=facts), "facts must be an object")


def test_facts_missing_rejected(protocol, init):
    msg = make_step(init, 0, 0, 1)
    del msg["facts"]
    _bad_first(protocol, msg, "facts must be an object")


def test_fact_nodes_row_count(protocol, init):
    _bad_first(protocol, _with_facts(init, lambda f: f["nodes"].pop()),
               "facts.nodes must have 3 rows")
    _bad_first(protocol, _with_facts(init, lambda f: f.update(nodes=None)),
               "facts.nodes must have 3 rows")


def test_fact_node_column_count(protocol, init):
    _bad_first(protocol, _with_facts(init, lambda f: f["nodes"][0].pop()),
               r"facts.nodes\[0\] must have 7 columns")


@pytest.mark.parametrize("value", [math.nan, math.inf, True, None, "1"])
def test_fact_node_values_must_be_finite(protocol, init, value):
    def mutate(facts):
        facts["nodes"][1][3] = value
    _bad_first(protocol, _with_facts(init, mutate), r"facts.nodes\[1\]\[3\] is not finite")


@pytest.mark.parametrize("slot", [3, -2, 1.0])
def test_fact_slot_must_be_in_range_integer(protocol, init, slot):
    def mutate(facts):
        facts["nodes"][1][6] = slot
    _bad_first(protocol, _with_facts(init, mutate), "slot must be an integer")


def test_fact_slot_duplicate_rejected(protocol, init):
    def mutate(facts):
        facts["nodes"][2][6] = 0       # node-c claims node-b's slot
    _bad_first(protocol, _with_facts(init, mutate), "slot 0 appears on nodes 1 and 2")


def test_fact_slot_mismatching_init_rejected(protocol, init):
    def mutate(facts):
        facts["nodes"][0][6] = 0       # node-a claims slot 0 (node-b)
        facts["nodes"][1][6] = -1
    _bad_first(protocol, _with_facts(init, mutate), "which init assigns to 'node-b'")


def test_fact_padded_slot_claim_rejected(protocol, init):
    def mutate(facts):
        facts["nodes"][0][6] = 2       # slot 2 is padding
    _bad_first(protocol, _with_facts(init, mutate), "init assigns to None")


def test_fact_missing_active_slot_rejected(protocol, init):
    def mutate(facts):
        facts["nodes"][2][6] = -1
    _bad_first(protocol, _with_facts(init, mutate), r"missing the active slots \[1\]")


def test_ghost_slot_id_in_init_fails_on_first_step():
    init = make_init(slot_node_ids=["node-b", "ghost", None])
    protocol = CentralizedProtocol(init)
    with pytest.raises(ProtocolError):
        protocol.validate_step(make_step(make_init(), 0, 0, 1), first=True)


# Facts: links ----------------------------------------------------------------------

def test_fact_links_row_count(protocol, init):
    _bad_first(protocol, _with_facts(init, lambda f: f["links"].pop()),
               "facts.links must have 3 rows")


def test_fact_link_column_count(protocol, init):
    _bad_first(protocol, _with_facts(init, lambda f: f["links"][0].append(0)),
               r"facts.links\[0\] must have 3 columns")


@pytest.mark.parametrize("sinr", [math.nan, math.inf, None, True])
def test_fact_link_sinr_must_be_finite(protocol, init, sinr):
    def mutate(facts):
        facts["links"][2][0] = sinr
    _bad_first(protocol, _with_facts(init, mutate), "sinr_db is not finite")


def test_fact_link_sinr_sentinel_accepted(protocol, init):
    def mutate(facts):
        facts["links"][2][0] = -999.0
    protocol.validate_step(_with_facts(init, mutate), first=True)


@pytest.mark.parametrize("capacity", [-0.1, math.nan, math.inf, None])
def test_fact_link_capacity_non_negative_finite(protocol, init, capacity):
    def mutate(facts):
        facts["links"][1][1] = capacity
    _bad_first(protocol, _with_facts(init, mutate), "capacity_mbps must be finite and >= 0")


def test_fact_link_zero_capacity_accepted(protocol, init):
    def mutate(facts):
        facts["links"][1][1] = 0
    protocol.validate_step(_with_facts(init, mutate), first=True)


@pytest.mark.parametrize("los", [2, -1, True, 1.0, None])
def test_fact_link_is_los_must_be_int_bit(protocol, init, los):
    def mutate(facts):
        facts["links"][0][2] = los
    _bad_first(protocol, _with_facts(init, mutate), "is_los is not 0 or 1")


# Facts: window ---------------------------------------------------------------------

def _window(init, **changes):
    msg = make_step(init, 0, 0, 1)
    msg["facts"]["window"].update(changes)
    return msg


def test_window_must_be_object(protocol, init):
    msg = make_step(init, 0, 0, 1)
    msg["facts"]["window"] = [1]
    _bad_first(protocol, msg, "facts.window must be an object")


def test_window_extra_key_rejected(protocol, init):
    _bad_first(protocol, _window(init, extra=0), "facts.window keys")


@pytest.mark.parametrize("key", ["ticks", "demand_mbps_sum", "legacy_reward_sum",
                                 "los_pairs_sum"])
def test_window_missing_key_rejected(protocol, init, key):
    msg = make_step(init, 0, 0, 1)
    del msg["facts"]["window"][key]
    _bad_first(protocol, msg, "facts.window keys")


@pytest.mark.parametrize("key", ["ticks", "flow_ticks_with_demand", "unroutable_flow_ticks",
                                 "connected_pairs_sum", "los_pairs_sum"])
@pytest.mark.parametrize("bad", [1.0, -1, True, None])
def test_window_counts_must_be_non_negative_ints(protocol, init, key, bad):
    _bad_first(protocol, _window(init, **{key: bad}),
               f"facts.window {key} must be a non-negative integer")


@pytest.mark.parametrize("key", ["demand_mbps_sum", "delivered_mbps_sum"])
@pytest.mark.parametrize("bad", [-0.5, math.nan, math.inf, None, True])
def test_window_mbps_sums_must_be_finite_non_negative(protocol, init, key, bad):
    _bad_first(protocol, _window(init, **{key: bad}), f"facts.window {key} must be finite")


@pytest.mark.parametrize("bad", [math.nan, math.inf, None, True])
def test_window_legacy_sum_must_be_finite(protocol, init, bad):
    _bad_first(protocol, _window(init, legacy_reward_sum=bad), "legacy_reward_sum must be finite")


def test_window_integral_mbps_sums_accepted(protocol, init):
    protocol.validate_step(_window(init, demand_mbps_sum=30, delivered_mbps_sum=15),
                           first=True)


def test_window_ticks_must_equal_ticks_in_step(protocol, init):
    _bad_first(protocol, _window(init, ticks=2, legacy_reward_sum=2.0),
               "facts.window ticks 2 != ticks_in_step 1")


def test_delivered_may_not_exceed_demand(protocol, init):
    _bad_first(protocol, _window(init, demand_mbps_sum=10.0, delivered_mbps_sum=10.1),
               "delivered_mbps_sum 10.1 exceeds")
    # Within the relative tolerance is accepted (float rounding in C++ sums).
    CentralizedProtocol(init).validate_step(
        _window(init, demand_mbps_sum=10.0, delivered_mbps_sum=10.0 + 1e-6), first=True)


def test_zero_demand_window_accepted(protocol, init):
    protocol.validate_step(_window(init, demand_mbps_sum=0.0, delivered_mbps_sum=0.0,
                                   flow_ticks_with_demand=0, unroutable_flow_ticks=0),
                           first=True)


@pytest.mark.parametrize("key", ["connected_pairs_sum", "los_pairs_sum"])
def test_pair_sums_bounded_by_ticks_times_links(protocol, init, key):
    # One tick, three links -> at most 3.
    CentralizedProtocol(init).validate_step(_window(init, **{key: 3}), first=True)
    _bad_first(protocol, _window(init, **{key: 4}), f"{key} 4 exceeds ticks\\*num_links = 3")


def test_unroutable_bounded_by_flow_ticks(protocol, init):
    CentralizedProtocol(init).validate_step(
        _window(init, unroutable_flow_ticks=3, flow_ticks_with_demand=3), first=True)
    _bad_first(protocol, _window(init, unroutable_flow_ticks=4, flow_ticks_with_demand=3),
               "unroutable_flow_ticks 4 exceeds")


def test_reward_must_equal_legacy_sum_over_ticks(protocol, init):
    _bad_first(protocol, _window(init, legacy_reward_sum=0.5), "legacy_reward_sum/ticks")


def test_window_mean_reward_over_five_ticks(protocol, init):
    # README: three tick rewards +1,-1,+1 average; here five ticks summing to 1 -> 0.2.
    _reset(protocol, init)
    msg = make_step(init, 5, 1, 5, reward=0.2)
    msg["facts"]["window"]["legacy_reward_sum"] = 1.0
    protocol.validate_step(msg)
    bad = CentralizedProtocol(init)
    _reset(bad, init)
    msg = make_step(init, 5, 1, 5, reward=1.0)
    msg["facts"]["window"]["legacy_reward_sum"] = 1.0     # mean would be 0.2, not 1.0
    with pytest.raises(ProtocolError, match="legacy_reward_sum/ticks"):
        bad.validate_step(msg)


def test_negative_reward_window_accepted(protocol, init):
    protocol.validate_step(make_step(init, 0, 0, 1, reward=-1.0), first=True)


# Joint action ----------------------------------------------------------------------

@pytest.mark.parametrize("action", [[0, 1, 4], (4, 4, 4), np.array([3, 2, 4]),
                                    np.array([4, 4, 4], dtype=np.int64),
                                    np.array([1, 0, 4], dtype=np.uint8)])
def test_joint_action_accepts_m_integers(protocol, action):
    joint = protocol.joint_action(action)
    assert joint == [int(a) for a in np.asarray(action)]
    assert all(type(a) is int for a in joint)


@pytest.mark.parametrize("action", [4, np.int64(4), np.array(4)])
def test_joint_action_rejects_scalars(protocol, action):
    with pytest.raises(ValueError, match="scalar"):
        protocol.joint_action(action)


@pytest.mark.parametrize("action", [[], [4], [4, 4], [4, 4, 4, 4]])
def test_joint_action_rejects_wrong_length(protocol, action):
    with pytest.raises(ValueError, match="must have 3 entries"):
        protocol.joint_action(action)


@pytest.mark.parametrize("value", [-1, 5, 100])
def test_joint_action_rejects_out_of_range(protocol, value):
    with pytest.raises(ValueError, match=r"outside \[0,4\]"):
        protocol.joint_action([4, value, 4])


@pytest.mark.parametrize("value", [2.5, "2", "west"])
def test_joint_action_rejects_non_integers(protocol, value):
    with pytest.raises(ValueError):
        protocol.joint_action([4, value, 4])


def test_joint_action_rejects_all_bool_array(protocol):
    with pytest.raises(ValueError, match="must be an integer"):
        protocol.joint_action([True, False, True])


def test_joint_action_nan_raises_value_error(protocol):
    with pytest.raises(ValueError):
        protocol.joint_action([4, math.nan, 4])


def test_joint_action_infinity_raises_value_error(protocol):
    # joint_action's docstring promises ValueError for a non-integer slot action.
    with pytest.raises(ValueError):
        protocol.joint_action([4, math.inf, 4])


def test_joint_action_none_raises_value_error(protocol):
    # A None slot action is rejected with ValueError, not TypeError.
    with pytest.raises(ValueError):
        protocol.joint_action([4, None, 4])


def test_joint_action_mixed_bool_is_not_coerced(protocol):
    # QUESTION: np.asarray([True, 4, 4]) silently becomes [1, 4, 4] before the
    # bool check at protocol.py:494, so a bool slot action is coerced to "east".
    with pytest.raises(ValueError):
        protocol.joint_action([True, 4, 4])


def test_joint_action_does_not_mutate_input(protocol):
    action = np.array([1, 2, 4])
    protocol.joint_action(action)
    assert list(action) == [1, 2, 4]


# Legacy protocol -------------------------------------------------------------------

def test_legacy_valid_stream_and_parse_obs():
    protocol = LegacyProtocol(None)
    first = make_legacy_step(0, pos=(1.0, 2.0, 3.0), links=2)
    protocol.validate_step(first, first=True)
    obs = LegacyProtocol.parse_obs(first)
    # [x, y, z, sinr0, cap0, sinr1, cap1]
    assert obs.tolist() == [1.0, 2.0, 3.0, 15.0, 80.0, 15.0, 80.0]
    assert obs.dtype == np.float64
    protocol.validate_step(make_legacy_step(1, links=2))
    protocol.validate_step(make_legacy_step(2, links=2, done=True))


def test_legacy_tick_must_advance():
    protocol = LegacyProtocol(None)
    protocol.validate_step(make_legacy_step(0), first=True)
    protocol.validate_step(make_legacy_step(1))
    with pytest.raises(ProtocolError, match="tick 1 does not advance past 1"):
        protocol.validate_step(make_legacy_step(1))
    with pytest.raises(ProtocolError, match="tick 0 does not advance past 1"):
        protocol.validate_step(make_legacy_step(0))


def test_legacy_width_checked_after_first():
    protocol = LegacyProtocol(7)
    protocol.validate_step(make_legacy_step(0, links=2), first=True)
    with pytest.raises(ProtocolError, match="legacy observation width 9 != 7"):
        protocol.validate_step(make_legacy_step(1, links=3))


@pytest.mark.parametrize("mutate,pattern", [
    (lambda m: m.update(type="init"), "Expected a 'step'"),
    (lambda m: m.update(obs=[0.0]), "legacy obs must be an object"),
    (lambda m: m["obs"].update(controlled_pos=[0.0, math.nan, 0.0]), "controlled_pos"),
    (lambda m: m["obs"].update(controlled_pos=None), "controlled_pos"),
    (lambda m: m["obs"].update(controlled_pos=[True, 0.0, 0.0]), "controlled_pos"),
    (lambda m: m["obs"].pop("link_sinrs"), "link_sinrs and link_capacities"),
    (lambda m: m["obs"].update(link_capacities=[1.0]), "differ in length"),
    (lambda m: m["obs"].update(link_sinrs=[math.inf, 1.0]), "not all finite"),
    (lambda m: m["obs"].update(link_capacities=[1.0, None]), "not all finite"),
    (lambda m: m.update(reward=math.nan), "reward is not a finite"),
    (lambda m: m.update(done=1), "done must be a boolean"),
    (lambda m: m.update(tick=1.0), "tick/time_s invalid"),
    (lambda m: m.update(tick=True), "tick/time_s invalid"),
    (lambda m: m.update(time_s=math.inf), "tick/time_s invalid"),
])
def test_legacy_rejects_malformed_fields(mutate, pattern):
    msg = make_legacy_step(0)
    mutate(msg)
    with pytest.raises(ProtocolError, match=pattern):
        LegacyProtocol(None).validate_step(msg, first=True)


def test_legacy_zero_links_accepted():
    protocol = LegacyProtocol(None)
    protocol.validate_step(make_legacy_step(0, links=0), first=True)
    assert LegacyProtocol.parse_obs(make_legacy_step(0, links=0)).shape == (3,)


def test_legacy_messages_not_mutated_by_validation():
    msg = make_legacy_step(0)
    snapshot = clone(msg)
    LegacyProtocol(None).validate_step(msg, first=True)
    assert msg == snapshot
