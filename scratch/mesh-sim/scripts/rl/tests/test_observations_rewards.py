"""Pure unit tests for the P2 observation presets, rewards, selection, telemetry."""

import json
import math

import numpy as np
import pytest

from scripts.rl.env.observations import (
    SchemaMismatchError, canonical_json, check_schema, get_preset,
    observation_schema,
)
from scripts.rl.env.rewards import RewardComposer, get_component, reward_schema
from scripts.rl.env.selection import resolve_selection
from scripts.rl.env.telemetry import (
    StepRecorder, make_header, make_record, replay_file,
)

# Mirrors inputs/baselines/p1-multi-smoke: N = 3, M = 3, two controlled nodes.
NODE_IDS = ["node-a", "node-b", "node-c"]
BOUNDS = {"x_min": 0.0, "x_max": 100.0, "y_min": -50.0, "y_max": 100.0,
          "z_min": 0.0, "z_max": 50.0}
CONTRACT = {
    "type": "init",
    "contract": "mesh_move_2d_v1",
    "dimensions": 2,
    "action_meanings": ["west", "east", "south", "north", "hold"],
    "max_controlled_nodes": 3,
    "num_controlled": 2,
    "slot_node_ids": ["node-b", "node-c", None],
    "slot_speed_mps": [10.0, 10.0, None],
    "num_mesh_nodes": 3,
    "obs_dim": 24,
    "mask_dim": 15,
    "tick_s": 0.1,
    "decision_interval_s": 0.5,
    "decision_interval_ticks": 5,
    "num_ticks": 10,
    "num_decisions": 2,
    "reward_type": "all_links_los",
    "reward_window": "mean",
    "wall_policy": "clip",
    "facts_schema": "mesh_facts_v1",
    "facts_columns": {"nodes": ["x", "y", "z", "vx", "vy", "vz", "slot"],
                      "links": ["sinr_db", "capacity_mbps", "is_los"]},
    "node_ids": NODE_IDS,
    "num_links": 3,
    "bounds": BOUNDS,
    "band": "mmwave",
    "jammer_path_enabled": False,
    "warmup_s": 0.0,
}
FACTS = {
    "nodes": [[50.0, 20.0, 10.0, 1.2, -0.9, 0.0, -1],
              [100.0, 0.0, 10.0, 0.0, -10.0, 0.0, 0],
              [100.0, 50.0, 10.0, 0.0, 0.0, 0.0, 1]],
    "links": [[31.4, 1650.2, 1], [28.9, 1512.7, 1], [30.1, 1601.0, 1]],
    "window": {"ticks": 5, "demand_mbps_sum": 150.0, "delivered_mbps_sum": 120.0,
               "flow_ticks_with_demand": 15, "unroutable_flow_ticks": 0,
               "connected_pairs_sum": 12, "los_pairs_sum": 15,
               "legacy_reward_sum": 5.0},
}
ZERO_WINDOW = dict(FACTS["window"], demand_mbps_sum=0.0, delivered_mbps_sum=0.0,
                   flow_ticks_with_demand=0, connected_pairs_sum=0, los_pairs_sum=0)


def contract_with(**overrides) -> dict:
    return dict(CONTRACT, **overrides)


def facts_with_link(sinr: float, capacity: float) -> dict:
    """Same geometry with every link forced to one (sinr, capacity) pair."""
    return dict(FACTS, links=[[sinr, capacity, 1]] * 3)


def sinr_n(sinr: float) -> float:
    return min(max((sinr + 20.0) / 60.0, 0.0), 1.0)


def cap_n(capacity: float) -> float:
    return min(max(math.log10(1.0 + capacity) / 4.0, 0.0), 1.0)


def test_local_links_v1_exact_slot_vector():
    preset = get_preset("local_links_v1")
    obs = preset.build(FACTS, CONTRACT)
    assert obs.shape == (36,) and obs.dtype == np.float32
    expected = [1.0, 1.0, -1.0 / 3.0, -0.6,
                1.0, 1.0, sinr_n(31.4), cap_n(1650.2),
                1.0, 1.0, sinr_n(30.1), cap_n(1601.0)]
    np.testing.assert_allclose(obs[:12], np.float32(expected), rtol=0, atol=1e-6)
    assert preset.space(CONTRACT).contains(obs)


def test_local_links_v1_padded_slot_is_zero():
    obs = get_preset("local_links_v1").build(FACTS, CONTRACT)
    assert not obs[24:].any()


@pytest.mark.parametrize("sinr,capacity,valid", [
    (-999.0, 0.0, 0.0),
    (-200.0, 1e6, 1.0),
    (120.0, 0.0, 1.0),
    (120.0, 1e6, 1.0),
])
def test_local_links_v1_clips_extreme_links(sinr, capacity, valid):
    preset = get_preset("local_links_v1")
    obs = preset.build(facts_with_link(sinr, capacity), CONTRACT)
    assert np.isfinite(obs).all()
    assert preset.space(CONTRACT).contains(obs)
    assert obs[5] == pytest.approx(valid)
    assert obs[6] == pytest.approx(sinr_n(sinr) if valid else 0.0, abs=1e-6)
    assert obs[7] == pytest.approx(cap_n(capacity) if valid else 0.0, abs=1e-6)


def test_p1_flat_matches_cpp_layout():
    preset = get_preset("p1_flat")
    obs = preset.build(FACTS, CONTRACT)
    expected = [
        1.0, 100.0, 0.0, 10.0, 31.4, 1650.2, 30.1, 1601.0,
        1.0, 100.0, 50.0, 10.0, 28.9, 1512.7, 30.1, 1601.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
    ]
    assert obs.dtype == np.float64
    np.testing.assert_array_equal(obs, np.asarray(expected))


@pytest.mark.parametrize("preset_name", ["p1_flat", "local_links_v1"])
def test_schema_hash_is_deterministic_and_strict_json(preset_name):
    first = observation_schema(preset_name, CONTRACT)
    second = observation_schema(preset_name, contract_with())
    assert first == second
    text = canonical_json(first)
    assert "NaN" not in text and "Infinity" not in text
    assert json.loads(text)["sha256"] == first["sha256"]


def test_p1_flat_schema_uses_null_bounds_but_infinite_box():
    schema = observation_schema("p1_flat", CONTRACT)
    assert schema["low"] == [None] * 24 and schema["high"] == [None] * 24
    box = get_preset("p1_flat").space(CONTRACT)
    assert box.low.min() == -np.inf and box.high.max() == np.inf


@pytest.mark.parametrize("overrides,fields", [
    ({"num_mesh_nodes": 4, "node_ids": NODE_IDS + ["node-d"], "num_links": 6},
     {"obs_dim", "num_mesh_nodes", "feature_names"}),
    ({"dimensions": 3,
      "action_meanings": ["west", "east", "south", "north", "down", "up", "hold"]},
     {"dimensions", "action_meanings"}),
    ({"bounds": dict(BOUNDS, x_max=200.0)}, {"bounds"}),
])
def test_check_schema_rejects_structural_change(overrides, fields):
    saved = observation_schema("local_links_v1", CONTRACT)
    live = observation_schema("local_links_v1", contract_with(**overrides))
    with pytest.raises(SchemaMismatchError) as excinfo:
        check_schema(saved, live)
    assert set(excinfo.value.fields) == fields


def test_check_schema_reports_identity_change_as_warning():
    saved = observation_schema("local_links_v1", CONTRACT)
    renamed = ["node-a", "node-x", "node-c"]
    live = observation_schema(
        "local_links_v1",
        contract_with(node_ids=renamed, slot_node_ids=["node-x", "node-c", None]),
    )
    warnings = check_schema(saved, live)
    assert len(warnings) == 2
    assert check_schema(saved, saved) == []


def test_delivery_ratio_masks_zero_demand():
    component = get_component("delivery_ratio")
    assert component.value(ZERO_WINDOW, 1.0, CONTRACT) == (0.0, False)
    value, valid = component.value(FACTS["window"], 1.0, CONTRACT)
    assert valid and value == pytest.approx(0.8)


@pytest.mark.parametrize("name,expected", [
    ("connectivity", 12.0 / 15.0),
    ("throughput_mbps", 24.0),
    ("legacy", 1.0),
])
def test_other_components(name, expected):
    value, valid = get_component(name).value(FACTS["window"], 1.0, CONTRACT)
    assert valid and value == pytest.approx(expected)


def test_composer_total_is_weighted_sum_over_valid_components():
    composer = RewardComposer(["delivery_ratio", "connectivity", "throughput_mbps"],
                              [1.0, 0.5, 0.0])
    breakdown = composer.compose(FACTS["window"], 1.0, CONTRACT)
    assert breakdown.total == pytest.approx(0.8 + 0.5 * 12.0 / 15.0)
    assert breakdown.legacy == 1.0
    assert breakdown.valid == {"delivery_ratio": 1, "connectivity": 1,
                               "throughput_mbps": 1}
    masked = composer.compose(ZERO_WINDOW, 1.0, CONTRACT)
    assert masked.valid["delivery_ratio"] == 0
    assert masked.total == pytest.approx(0.0)


def test_legacy_component_reproduces_cpp_reward():
    breakdown = RewardComposer(["legacy"], [1.0]).compose(FACTS["window"], 1.0, CONTRACT)
    assert breakdown.total == pytest.approx(1.0)


@pytest.mark.parametrize("components,weights", [
    (["delivery_ratio", "delivery_ratio"], [1.0, 1.0]),
    (["delivery_ratio"], [1.0, 1.0]),
    (["delivery_ratio"], [float("inf")]),
    (["no_such_component"], [1.0]),
])
def test_composer_rejects_bad_configuration(components, weights):
    with pytest.raises(ValueError):
        RewardComposer(components, weights)


def test_reward_schema_authorities():
    python_schema = reward_schema(["delivery_ratio"], [2.0], reward_type="all_links_los",
                                  reward_window="mean")
    assert python_schema["authority"] == "python"
    assert python_schema["zero_demand_rule"] == "masked"
    assert python_schema["ranges"]["delivery_ratio"] == [0.0, 1.0]
    cpp_schema = reward_schema([], [], reward_type="all_links_los",
                               reward_window="mean")
    assert cpp_schema["authority"] == "cpp" and cpp_schema["reward_type"] == "all_links_los"
    assert "Infinity" not in canonical_json(
        reward_schema(["throughput_mbps"], [1.0], reward_type="x", reward_window="mean"))


CENTRALIZED_INI = """[scenario]
seed = 1

[rl]
controlled_nodes = node-b, node-c
observation_preset = local_links_v1   # inline comment
reward_components = delivery_ratio, connectivity
telemetry = steps
telemetry_every = 2
"""
LEGACY_INI = """[scenario]
seed = 1

[rl]
controlled_node_id = relay
"""


def write_ini(tmp_path, text, name="run.ini") -> str:
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def test_resolve_selection_precedence(tmp_path):
    config = write_ini(tmp_path, CENTRALIZED_INI)
    from_ini = resolve_selection(config)
    assert from_ini.observation_preset == "local_links_v1"
    assert from_ini.reward_components == ("delivery_ratio", "connectivity")
    assert from_ini.reward_weights == (1.0, 1.0)
    assert (from_ini.telemetry, from_ini.telemetry_every) == ("steps", 2)
    assert from_ini.describe()["source"] == {
        "observation_preset": "run.ini", "reward_components": "run.ini",
        "reward_weights": "default", "telemetry": "run.ini",
        "telemetry_every": "run.ini",
    }

    overridden = resolve_selection(config, observation_preset="p1_flat",
                                   reward_components="legacy",
                                   reward_weights="0.25")
    assert overridden.observation_preset == "p1_flat"
    assert overridden.reward_components == ("legacy",)
    assert overridden.reward_weights == (0.25,)
    assert overridden.describe()["source"]["reward_weights"] == "cli"

    defaults = resolve_selection(write_ini(
        tmp_path, "[rl]\ncontrolled_nodes = node-b\n", name="plain.ini"))
    assert defaults.describe() == {
        "observation_preset": "p1_flat", "reward_components": [],
        "reward_weights": [], "telemetry": "none", "telemetry_every": 1,
        "source": {key: "default" for key in
                   ("observation_preset", "reward_components", "reward_weights",
                    "telemetry", "telemetry_every")},
    }


@pytest.mark.parametrize("kwargs,key", [
    ({"observation_preset": "nope"}, "observation_preset"),
    ({"reward_components": "nope"}, "reward_components"),
    ({"reward_components": ""}, "reward_components"),
    ({"reward_weights": "1.0"}, "reward_weights"),
    ({"telemetry": "csv"}, "telemetry"),
    ({"telemetry_every": "0", "telemetry": "steps"}, "telemetry_every"),
    ({"telemetry_every": "2"}, "telemetry_every"),
])
def test_resolve_selection_rejects_invalid_keys(tmp_path, kwargs, key):
    config = write_ini(tmp_path, "[rl]\ncontrolled_nodes = node-b\n")
    with pytest.raises(ValueError, match=key):
        resolve_selection(config, **kwargs)


def test_resolve_selection_rejects_p2_selection_in_legacy_mode(tmp_path):
    config = write_ini(tmp_path, LEGACY_INI)
    with pytest.raises(ValueError, match="observation_preset"):
        resolve_selection(config, observation_preset="local_links_v1")
    assert resolve_selection(config).observation_preset == "p1_flat"


def test_telemetry_records_replay_without_mismatch(tmp_path):
    selection = resolve_selection(write_ini(tmp_path, CENTRALIZED_INI))
    preset = get_preset(selection.observation_preset)
    obs_schema = observation_schema(selection.observation_preset, CONTRACT)
    rwd_schema = reward_schema(selection.reward_components, selection.reward_weights,
                               reward_type=CONTRACT["reward_type"],
                               reward_window=CONTRACT["reward_window"])
    composer = RewardComposer(selection.reward_components, selection.reward_weights)

    recorder = StepRecorder(tmp_path / "steps.jsonl", selection.telemetry_every)
    recorder.write_header(make_header(CONTRACT, selection.describe(), obs_schema,
                                      rwd_schema))
    reset_facts = dict(FACTS, window=dict(FACTS["window"], ticks=1))
    reset = make_record(0, 0, 0.0, 1, None, [1] * 15, [], reset_facts, 1.0, None,
                        preset.build(reset_facts, CONTRACT))
    assert reset["reward"] is None and reset["action_sent"] is None
    recorder.append(reset)

    breakdown = composer.compose(FACTS["window"], 1.0, CONTRACT)
    recorder.append(make_record(2, 10, 1.0, 5, [4, 4, 4], [1] * 15, [1], FACTS, 1.0,
                                breakdown, preset.build(FACTS, CONTRACT)))
    assert recorder.records == 2
    recorder.close()

    lines = (tmp_path / "steps.jsonl").read_text().splitlines()
    assert len(lines) == 3
    summary = replay_file(tmp_path / "steps.jsonl")
    assert (summary.records, summary.obs_mismatches, summary.reward_mismatches) == (2, 0, 0)


@pytest.mark.parametrize("decision,done,saved", [
    (0, False, True), (1, False, False), (2, False, True), (3, True, True),
])
def test_should_save_sampling(tmp_path, decision, done, saved):
    recorder = StepRecorder(tmp_path / "steps.jsonl", 2)
    try:
        assert recorder.should_save(decision, done) is saved
    finally:
        recorder.close()
