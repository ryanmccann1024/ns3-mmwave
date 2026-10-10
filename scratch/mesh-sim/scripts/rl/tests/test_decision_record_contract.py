"""Decision-record v1 preservation and v2 extensions; fake bridge and independent schema checks."""

import copy
import hashlib
import json

import pytest

from scripts.rl.env.decisions import DecisionRecorder
from scripts.rl.env.telemetry import replay_record
from scripts.rl.tests.test_decision_records import (
    SCHEMA_PATH, SCHEMA_V1_PATH, SCHEMA_V1_SHA256, SCRIPTED, _assert_documents_valid,
    _join_run, _load_schema, _read_sidecar, _settings, _steps,
)

SCHEMA_V2_SHA256 = "2a150730e842974897ddbb4518d2028be210dc200cc66b3890d9235fe7f4be29"


def test_schema_v2_is_frozen():
    assert hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest() == SCHEMA_V2_SHA256


def test_v1_remains_usable_for_historical_records(sim_binary, multi_run_config, tmp_path):
    episode = _join_run(sim_binary, multi_run_config, tmp_path / "run")
    manifest, lines = _read_sidecar(episode)
    manifest["version"] = 1
    del manifest["scoring"]
    for line in lines[1:]:
        del line["outcome"]["scored_ticks"]
    v1 = json.loads(SCHEMA_V1_PATH.read_text())
    assert hashlib.sha256(SCHEMA_V1_PATH.read_bytes()).hexdigest() == SCHEMA_V1_SHA256
    _assert_documents_valid(v1, manifest, lines)
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(v1)
    validator = jsonschema.Draft202012Validator(v1)
    for document in (manifest, *lines):
        validator.validate(document)


def test_v2_reward_maps_allow_extensions_and_reject_bad_values(
        sim_binary, multi_run_config, tmp_path):
    episode = _join_run(sim_binary, multi_run_config, tmp_path / "run")
    manifest, lines = _read_sidecar(episode)
    document = copy.deepcopy(lines[1])
    document["outcome"]["reward"] = {"total": 0.75,
        "components": {"future_component": 0.75}, "valid": {"future_component": 1}}
    _assert_documents_valid(_load_schema(), manifest, [lines[0], document])
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))
    validator.validate(document)
    for key, value in (("components", "not numeric"), ("valid", True), ("valid", 2)):
        bad = copy.deepcopy(document)
        bad["outcome"]["reward"][key]["future_component"] = value
        assert not validator.is_valid(bad)


@pytest.mark.parametrize("scored_ticks", [None, 0, 2, 5])
def test_scoring_metadata_is_copied_without_inferring_from_elapsed_ticks(
        sim_binary, multi_run_config, tmp_path, scored_ticks):
    source = _join_run(sim_binary, multi_run_config, tmp_path / "source")
    source_manifest, _ = _read_sidecar(source)
    header = json.loads((source / "steps.jsonl").read_text().splitlines()[0])
    steps = _steps(source)
    contract = dict(header["contract"], num_decisions=1)
    if scored_ticks is None:
        contract.pop("reward_warmup", None)
    if scored_ticks is not None:
        contract.update(warmup_s=0.3, reward_warmup="exclude", reward_window="mean")
    directory = tmp_path / "copy" / "episode-0000"
    directory.mkdir(parents=True)
    recorder = DecisionRecorder(directory, _settings(), SCRIPTED,
        episode=source_manifest["episode"], contract=contract,
        selection_describe=header["selection"], observation_schema=header["observation_schema"],
        reward_schema=header["reward_schema"])
    obs, _ = replay_record(header, steps[0])
    recorder.record_reset(steps[0], obs, True)
    outcome = dict(steps[1], reward=0.0, done=True)
    if scored_ticks is None:
        outcome.pop("scored_ticks", None)
    if scored_ticks is not None:
        outcome["scored_ticks"] = scored_ticks
    recorder.record_decision(outcome,
        {"obs": obs, "mask": steps[0]["mask"], "requested": steps[1]["action_sent"]},
        0.0, True)
    recorder.close("completed", "done", None)
    manifest, lines = _read_sidecar(directory)
    assert lines[1]["outcome"]["ticks_in_step"] == 5
    assert lines[1]["outcome"]["scored_ticks"] == scored_ticks
    assert manifest["scoring"] == (None if scored_ticks is None else
        {"warmup_s": 0.3, "reward_warmup": "exclude", "reward_window": "mean"})
    _assert_documents_valid(_load_schema(), manifest, lines)
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft202012Validator(_load_schema())
    for document in (manifest, *lines):
        validator.validate(document)
    bad = copy.deepcopy(lines[1])
    bad["outcome"]["scored_ticks"] = True
    assert not validator.is_valid(bad)
