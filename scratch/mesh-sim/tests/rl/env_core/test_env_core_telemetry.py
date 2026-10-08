"""steps.jsonl writer, record builders, and replay (scripts/rl/env/telemetry.py).

Expectations: src/rl/policy-inputs.md "Save and inspect decisions" (header line,
reset + every kth + terminal decision, flush every 32 records and on stop,
replay rebuilds observations and Python-composed rewards but does not recheck a
C++-authored reward) and the *_version convention in scripts/rl/CLAUDE.md.
"""

import json
import math

import numpy as np
import pytest

from scripts.rl.env import telemetry
from scripts.rl.env.observations import get_preset, observation_schema
from scripts.rl.env.rewards import RewardBreakdown, RewardComposer, reward_schema
from scripts.rl.env.selection import RlSelection
from scripts.rl.env.telemetry import (TELEMETRY_FILE, TELEMETRY_VERSION, ReplaySummary,
                                      StepRecorder, make_header, make_record, obs_sha256,
                                      replay_file, reward_field)

from ._helpers import episode_steps, make_init


# StepRecorder ----------------------------------------------------------------------

def test_constants():
    assert TELEMETRY_VERSION == 1
    assert TELEMETRY_FILE == "steps.jsonl"


@pytest.mark.parametrize("every", [0, -1, "0"])
def test_every_must_be_positive(tmp_path, every):
    with pytest.raises(ValueError, match="telemetry_every must be >= 1"):
        StepRecorder(tmp_path / "s.jsonl", every)
    assert not (tmp_path / "s.jsonl").exists()


@pytest.mark.parametrize("every,done_at,expected", [
    (1, 5, [0, 1, 2, 3, 4, 5]),
    (2, 5, [0, 2, 4, 5]),
    (3, 7, [0, 3, 6, 7]),
    (3, 6, [0, 3, 6]),
    (10, 4, [0, 4]),
])
def test_should_save_cadence(tmp_path, every, done_at, expected):
    recorder = StepRecorder(tmp_path / "s.jsonl", every)
    saved = [d for d in range(done_at + 1) if recorder.should_save(d, d == done_at)]
    recorder.close()
    assert saved == expected


def test_header_then_records_round_trip_as_sorted_strict_json(tmp_path):
    path = tmp_path / "s.jsonl"
    recorder = StepRecorder(path)
    recorder.write_header({"type": "header", "b": 1, "a": 2})
    recorder.append({"type": "step", "z": 1, "decision": 0})
    assert recorder.records == 1
    recorder.close()
    lines = path.read_text().splitlines()
    assert lines[0] == '{"a": 2, "b": 1, "type": "header"}'
    assert json.loads(lines[1]) == {"type": "step", "z": 1, "decision": 0}
    assert list(json.loads(lines[1])) == ["decision", "type", "z"]


def test_header_is_flushed_immediately(tmp_path):
    path = tmp_path / "s.jsonl"
    recorder = StepRecorder(path)
    recorder.write_header({"type": "header"})
    assert path.read_text().count("\n") == 1
    recorder.close()


def test_flush_every_32_records(tmp_path):
    path = tmp_path / "s.jsonl"
    recorder = StepRecorder(path)
    recorder.write_header({"type": "header"})
    for index in range(32):
        recorder.append({"type": "step", "decision": index})
    # The 32nd append triggers a flush: everything is visible to another reader.
    assert len(path.read_text().splitlines()) == 33
    recorder.close()


def test_close_flushes_and_is_idempotent(tmp_path):
    path = tmp_path / "s.jsonl"
    recorder = StepRecorder(path)
    recorder.write_header({"type": "header"})
    recorder.append({"type": "step"})
    recorder.close()
    recorder.close()
    assert len(path.read_text().splitlines()) == 2
    assert recorder.records == 1


def test_write_after_close_raises(tmp_path):
    recorder = StepRecorder(tmp_path / "s.jsonl")
    recorder.close()
    with pytest.raises(ValueError, match="is closed"):
        recorder.append({"type": "step"})
    with pytest.raises(ValueError, match="is closed"):
        recorder.write_header({"type": "header"})


@pytest.mark.parametrize("value", [math.nan, math.inf])
def test_non_finite_values_are_refused(tmp_path, value):
    path = tmp_path / "s.jsonl"
    recorder = StepRecorder(path)
    with pytest.raises(ValueError):
        recorder.append({"type": "step", "x": value})
    assert recorder.records == 0
    recorder.close()
    assert "NaN" not in path.read_text() and "Infinity" not in path.read_text()


# obs_sha256 / reward_field / make_record -------------------------------------------

def test_obs_sha256_is_dtype_sensitive_and_byte_order_invariant():
    values = [1.0, -2.5, 3.25]
    f64 = np.asarray(values, dtype=np.float64)
    f32 = np.asarray(values, dtype=np.float32)
    assert obs_sha256(f64) != obs_sha256(f32)
    assert obs_sha256(f64, "float32") == obs_sha256(f32)
    assert obs_sha256(f32, "float64") == obs_sha256(f64)
    big = np.asarray(values, dtype=">f8")
    assert obs_sha256(big) == obs_sha256(f64)
    assert obs_sha256(values) == obs_sha256(f64)        # lists hash as float64


def test_obs_sha256_handles_non_contiguous_arrays():
    base = np.arange(12, dtype=np.float64)
    strided = base[::2]
    assert obs_sha256(strided) == obs_sha256(np.ascontiguousarray(strided))


def test_reward_field_variants():
    assert reward_field(None) is None
    assert reward_field(1.5) == {"total": 1.5, "source": "cpp"}
    assert reward_field(np.float32(2.0)) == {"total": 2.0, "source": "cpp"}
    breakdown = RewardBreakdown(1.5, {"a": 1.0}, {"a": 1}, {"a": 1.5}, 0.0)
    assert reward_field(breakdown) == {"total": 1.5, "components": {"a": 1.0},
                                       "valid": {"a": 1}}
    original = {"total": 3.0}
    copy = reward_field(original)
    copy["total"] = 0.0
    assert original == {"total": 3.0}


def test_make_header_fields_and_contract_copy():
    contract = make_init()
    header = make_header(contract, {"telemetry": "steps"}, {"sha256": "o"},
                         {"sha256": "r"})
    assert header["type"] == "header"
    assert header["telemetry_version"] == TELEMETRY_VERSION
    assert header["contract"] == contract and header["contract"] is not contract
    contract["obs_dim"] = -1
    assert header["contract"]["obs_dim"] == 24


def test_make_record_normalizes_types():
    init = make_init()
    step = episode_steps(init)[1]
    obs = np.asarray(step["obs"])
    record = make_record(np.int64(1), np.int64(5), np.float64(0.5), np.int32(5),
                         np.array([4, 0, 4]), np.array(step["mask"], dtype=np.int8),
                         (2,), step["facts"], np.float32(1.0), None, obs)
    assert record["type"] == "step"
    assert record["action_sent"] == [4, 0, 4]
    assert record["revalidated_slots"] == [2]
    assert record["reward"] is None and record["reward_context"] is None
    assert record["obs_sha256"] == obs_sha256(obs)
    # Every field must survive strict JSON (numpy scalars would not).
    json.dumps(record, allow_nan=False)
    assert all(type(record[k]) is int for k in ("decision", "tick", "ticks_in_step"))
    assert type(record["time_s"]) is float and type(record["legacy_reward"]) is float


def test_make_record_reset_has_no_action():
    init = make_init()
    step = episode_steps(init)[0]
    record = make_record(0, 0, 0.0, 1, None, step["mask"], [], step["facts"], 1.0, None,
                         np.asarray(step["obs"]))
    assert record["action_sent"] is None and record["reward"] is None


# Replay ----------------------------------------------------------------------------

def _write_episode(path, preset_name: str, components=(), weights=(),
                   every: int = 1) -> list[dict]:
    """Write a steps.jsonl the way EpisodeSession does, from hand-built messages."""
    init = make_init()
    selection = RlSelection(observation_preset=preset_name,
                            reward_components=tuple(components),
                            reward_weights=tuple(weights), telemetry="steps",
                            telemetry_every=every)
    obs_schema = observation_schema(preset_name, init)
    rew_schema = reward_schema(list(components), list(weights),
                               reward_type=init["reward_type"],
                               reward_window=init["reward_window"])
    preset = get_preset(preset_name)
    composer = RewardComposer(components, weights) if components else None
    recorder = StepRecorder(path, every)
    recorder.write_header(make_header(init, selection.describe(), obs_schema, rew_schema))
    steps = episode_steps(init)
    for step in steps:
        obs = preset.build(step["facts"], init)
        if step["decision"] == 0:
            reward = None
        elif composer is not None:
            reward = composer.compose(step["facts"]["window"], step["reward"], init)
        else:
            reward = step["reward"]
        if recorder.should_save(step["decision"], step["done"]):
            recorder.append(make_record(
                step["decision"], step["tick"], step["time_s"], step["ticks_in_step"],
                None if step["decision"] == 0 else [4, 4, 4], step["mask"],
                step["revalidated_slots"], step["facts"], step["reward"], reward, obs))
    recorder.close()
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.mark.parametrize("preset", ["raw_links_v1", "local_links_v1", "geometry_v1",
                                    "service_v1", "full_facts_v1"])
def test_round_trip_replay_has_no_mismatches(tmp_path, preset):
    path = tmp_path / TELEMETRY_FILE
    lines = _write_episode(path, preset, ("delivery_ratio", "connectivity"), (1.0, 0.5))
    assert lines[0]["telemetry_version"] == TELEMETRY_VERSION
    assert replay_file(path) == ReplaySummary(records=3, obs_mismatches=0,
                                              reward_mismatches=0)


def test_round_trip_with_cpp_reward(tmp_path):
    path = tmp_path / TELEMETRY_FILE
    lines = _write_episode(path, "raw_links_v1")
    assert lines[2]["reward"] == {"total": 1.0, "source": "cpp"}
    assert replay_file(path) == ReplaySummary(3, 0, 0)


def test_round_trip_with_stride(tmp_path):
    path = tmp_path / TELEMETRY_FILE
    lines = _write_episode(path, "local_links_v1", ("connectivity",), (1.0,), every=2)
    assert [line["decision"] for line in lines[1:]] == [0, 2]
    assert replay_file(path) == ReplaySummary(2, 0, 0)


def _rewrite(path, lines) -> None:
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))


def test_tampered_obs_hash_is_counted(tmp_path):
    path = tmp_path / TELEMETRY_FILE
    lines = _write_episode(path, "local_links_v1", ("connectivity",), (1.0,))
    lines[2]["obs_sha256"] = "0" * 64
    _rewrite(path, lines)
    assert replay_file(path) == ReplaySummary(3, 1, 0)


def test_tampered_facts_change_rebuilt_obs(tmp_path):
    path = tmp_path / TELEMETRY_FILE
    lines = _write_episode(path, "raw_links_v1")
    lines[1]["facts"]["nodes"][1][0] += 1.0
    _rewrite(path, lines)
    assert replay_file(path).obs_mismatches == 1


def test_tampered_python_reward_is_counted(tmp_path):
    path = tmp_path / TELEMETRY_FILE
    lines = _write_episode(path, "local_links_v1", ("delivery_ratio", "connectivity"),
                           (1.0, 0.5))
    lines[2]["reward"]["total"] += 0.25
    _rewrite(path, lines)
    assert replay_file(path) == ReplaySummary(3, 0, 1)


def test_reward_within_tolerance_is_not_counted(tmp_path):
    path = tmp_path / TELEMETRY_FILE
    lines = _write_episode(path, "local_links_v1", ("connectivity",), (1.0,))
    lines[2]["reward"]["total"] += 1e-12
    _rewrite(path, lines)
    assert replay_file(path).reward_mismatches == 0


def test_cpp_reward_is_not_rechecked(tmp_path):
    # policy-inputs.md: replay does not recheck a C++-authored reward.
    path = tmp_path / TELEMETRY_FILE
    lines = _write_episode(path, "raw_links_v1")
    lines[2]["reward"]["total"] = 123.0
    _rewrite(path, lines)
    assert replay_file(path).reward_mismatches == 0


def test_reset_record_reward_is_not_rechecked(tmp_path):
    path = tmp_path / TELEMETRY_FILE
    lines = _write_episode(path, "local_links_v1", ("connectivity",), (1.0,))
    lines[1]["reward"] = {"total": 99.0}
    _rewrite(path, lines)
    assert replay_file(path).reward_mismatches == 0


def test_blank_lines_are_ignored(tmp_path):
    path = tmp_path / TELEMETRY_FILE
    _write_episode(path, "raw_links_v1")
    path.write_text("\n" + path.read_text().replace("\n", "\n\n") + "   \n")
    assert replay_file(path) == ReplaySummary(3, 0, 0)


def test_header_only_file_has_zero_records(tmp_path):
    path = tmp_path / TELEMETRY_FILE
    lines = _write_episode(path, "raw_links_v1")
    _rewrite(path, lines[:1])
    assert replay_file(path) == ReplaySummary(0, 0, 0)


@pytest.mark.parametrize("content", ["", "\n\n", "  \n"])
def test_empty_file_is_rejected(tmp_path, content):
    path = tmp_path / TELEMETRY_FILE
    path.write_text(content)
    with pytest.raises(ValueError, match="is empty"):
        replay_file(path)


def test_file_without_header_is_rejected(tmp_path):
    path = tmp_path / TELEMETRY_FILE
    lines = _write_episode(path, "raw_links_v1")
    _rewrite(path, lines[1:])
    with pytest.raises(ValueError, match="does not start with a header"):
        replay_file(path)


@pytest.mark.parametrize("version", [TELEMETRY_VERSION + 1, 0, None, "1"])
def test_unknown_telemetry_version_is_rejected(tmp_path, version):
    # QUESTION: telemetry.py:157-160 never reads header["telemetry_version"], so a
    # file written by a future (or no) schema version is replayed as if it were v1.
    path = tmp_path / TELEMETRY_FILE
    lines = _write_episode(path, "raw_links_v1")
    if version is None:
        del lines[0]["telemetry_version"]
    else:
        lines[0]["telemetry_version"] = version
    _rewrite(path, lines)
    with pytest.raises(ValueError, match="telemetry_version"):
        replay_file(path)


def test_unknown_preset_in_header_is_rejected(tmp_path):
    path = tmp_path / TELEMETRY_FILE
    lines = _write_episode(path, "raw_links_v1")
    lines[0]["observation_schema"]["schema_id"] = "raw_links_v9"
    _rewrite(path, lines)
    with pytest.raises(ValueError, match="Unknown observation_preset"):
        replay_file(path)


def test_dtype_from_header_controls_hash(tmp_path):
    # A float32 preset hashed as float64 would always mismatch; the header dtype wins.
    path = tmp_path / TELEMETRY_FILE
    lines = _write_episode(path, "local_links_v1")
    lines[0]["observation_schema"]["dtype"] = "float64"
    _rewrite(path, lines)
    assert replay_file(path).obs_mismatches == 3


def test_flush_constant_matches_documented_32():
    assert telemetry._FLUSH_EVERY == 32
