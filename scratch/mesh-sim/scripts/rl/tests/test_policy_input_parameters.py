"""Resolved input identities, replay, warmup boundaries, and metric extension owners."""

import copy
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.rl.env.mesh_env import MeshRlEnv
from scripts.rl.env.normalization import Normalization
from scripts.rl.env.observations import SchemaMismatchError, check_schema, get_preset, observation_schema
from scripts.rl.env.rewards import COMPONENTS, RewardComponent, RewardComposer, reward_schema
from scripts.rl.env.selection import RlSelection, resolve_selection
from scripts.rl.env.telemetry import TELEMETRY_FILE, replay_file
from scripts.rl.policy.bundle import eval_selection, selection_from_manifest
from scripts.rl.policy.compat import RewardMismatchError, check_compatibility
from scripts.rl.policy import metrics
from scripts.rl.tests.test_observations_rewards import CONTRACT, FACTS


@pytest.mark.parametrize("preset,parameter,value", [
    ("local_links_v1", "capacity_log10_denominator", 8.0),
    ("service_v1", "sinr_max_db", 80.0),
    ("full_facts_v1", "velocity_scale_mps", 80.0),
])
def test_scale_changes_input_and_identity(preset, parameter, value):
    old = get_preset(preset)
    new = get_preset(preset, {parameter: value})
    assert not np.array_equal(old.build(FACTS, CONTRACT), new.build(FACTS, CONTRACT))
    assert old.schema(CONTRACT)["sha256"] != new.schema(CONTRACT)["sha256"]
    with pytest.raises(SchemaMismatchError):
        check_schema(old.schema(CONTRACT), new.schema(CONTRACT))
    assert new.schema(CONTRACT)["parameters"][parameter] == value


def test_config_precedence_and_manifest_roundtrip(multi_run_config):
    path = Path(multi_run_config)
    with path.open("a") as handle:
        handle.write('\nobservation_preset = service_v1\nreward_components = service_success\n'
                     'observation_parameters = {"capacity_log10_denominator": 6}\n'
                     'reward_parameters = {"service_success": {"delivery_threshold": 0.7}}\n')
    selected = resolve_selection(str(path))
    assert selected.observation_parameters["capacity_log10_denominator"] == 6
    assert selected.reward_parameters["service_success"] == {
        "delivery_threshold": 0.7, "routable_threshold": 0.95}
    overridden = resolve_selection(str(path), observation_parameters='{"capacity_log10_denominator":8}',
                                   reward_parameters='{"service_success":{"delivery_threshold":0.8}}')
    assert overridden.source["observation_parameters"] == "cli"
    assert overridden.observation_parameters["capacity_log10_denominator"] == 8
    restored = selection_from_manifest({"selection": overridden.describe()})
    assert restored.observation_parameters == overridden.observation_parameters
    assert restored.reward_parameters == overridden.reward_parameters
    assert eval_selection(restored).reward_parameters == overridden.reward_parameters


@pytest.mark.parametrize("obs,reward", [
    ({"velocity_scale_mps": 5}, {}),
    ({"capacity_log10_denominator": 0}, {}),
    ({"sinr_min_db": 100}, {}),
    ({"sinr_max_db": float("nan")}, {}),
    ({"capacity_log10_denominator": True}, {}),
    ({}, {"service_success": {"delivery_threshold": 0}}),
    ({}, {"service_success": {"routable_threshold": 1.1}}),
    ({}, {"service_success": {"delivery_threshold": True}}),
    ({}, {"service_success": {"unknown": 1}}),
    ({}, {"unselected": {}}),
    ([], {}),
    ({}, []),
])
def test_invalid_or_unused_parameters_fail_before_launch(obs, reward):
    with pytest.raises(ValueError):
        RlSelection("service_v1", ("service_success",), (1,),
                    observation_parameters=obs, reward_parameters=reward)


def test_reward_threshold_drives_calculation_formula_and_model_check():
    names, weights = ["service_success"], [1]
    old = reward_schema(names, weights, contract=CONTRACT)
    params = {"service_success": {"delivery_threshold": 0.7}}
    new = reward_schema(names, weights, contract=CONTRACT, parameters=params)
    assert RewardComposer(names, weights).compose(FACTS["window"], 0, CONTRACT).total == -1
    assert RewardComposer(names, weights, params).compose(FACTS["window"], 0, CONTRACT).total == 1
    assert "0.7" in new["component_details"]["service_success"]["formula"]
    env = SimpleNamespace(contract=CONTRACT, observation_schema=observation_schema("service_v1", CONTRACT),
                          reward_schema=new)
    saved = {"contract": CONTRACT, "observation_schema": env.observation_schema, "reward_schema": old}
    with pytest.raises(RewardMismatchError):
        check_compatibility(saved, env, live_identity={}, live_band=None,
                            allow_different_scenario=True)


@pytest.mark.parametrize("name", tuple(COMPONENTS))
def test_every_component_masks_zero_scored_windows(name):
    window = {key: 0 for key in FACTS["window"]}
    result = RewardComposer([name], [1]).compose(window, 0, CONTRACT)
    assert result.total == 0 and result.valid[name] == 0


def test_reward_dependencies_skip_unneeded_position_context():
    composer = RewardComposer(["sinr_quality"], [1])
    context = composer.context(FACTS, CONTRACT)
    assert set(context) == {"links"}
    assert composer.compose(FACTS["window"], 0, CONTRACT, context).total > 0
    facts = copy.deepcopy(FACTS)
    facts["window"]["scored_ticks"] = 2
    composer = RewardComposer(["travel_fraction"], [-1])
    inputs = {"previous_nodes": FACTS["nodes"], "initial_nodes": FACTS["nodes"], "elapsed_ticks": 5}
    context = composer.context(facts, CONTRACT, inputs)
    assert composer.compose(facts["window"], 0, CONTRACT, context).valid["travel_fraction"] == 0


def test_registered_component_owns_parameter_and_schema(monkeypatch):
    component = RewardComponent("extra", lambda w, r, c, p, x: (p["amount"] * x["extra_context"], True),
                                (0, 1), (), tunable={"amount": (0.5, 0, 1)}, formula="{amount:g}",
                                context_fields=("extra_context",),
                                context_builder=lambda f, c, i: {"extra_context": len(f["links"]) / 3})
    monkeypatch.setitem(COMPONENTS, "extra", component)
    composer = RewardComposer(["extra"], [2], {"extra": {"amount": 0.8}})
    assert composer.compose(FACTS["window"], 0, CONTRACT, composer.context(FACTS, CONTRACT)).total == 1.6
    assert reward_schema(["extra"], [2], contract=CONTRACT,
                         parameters={"extra": {"amount": 0.8}})["component_details"]["extra"]["formula"] == "0.8"


def test_saved_parameters_replay_after_defaults_change(sim_binary, multi_run_config, tmp_path, monkeypatch):
    selection = RlSelection("full_facts_v1", ("service_success", "sinr_quality", "travel_fraction"),
                            (1, 0.2, -0.01), telemetry="steps",
                            observation_parameters={"capacity_log10_denominator": 8, "velocity_scale_mps": 80},
                            reward_parameters={"service_success": {"delivery_threshold": 0.7},
                                               "sinr_quality": {"sinr_max_db": 80}})
    env = MeshRlEnv(sim_binary, multi_run_config, seed=1, output_dir=str(tmp_path), selection=selection)
    try:
        env.reset()
        while True:
            _, _, done, _, _ = env.step([4] * env.contract["max_controlled_nodes"])
            if done:
                break
        episode = Path(next(x.split("=", 1)[1] for x in env._cmd if x.startswith("--output-dir=")))
    finally:
        env.close()
    original_resolve = Normalization.resolve
    monkeypatch.setattr(Normalization, "resolve", classmethod(
        lambda cls, overrides, fields: original_resolve(
            {**({"capacity_log10_denominator": 12} if "capacity_log10_denominator" in fields else {}),
             **overrides}, fields)))
    service = COMPONENTS["service_success"]
    monkeypatch.setitem(COMPONENTS, service.name, replace(service,
                        tunable={**service.tunable, "delivery_threshold": (0.99, 0, 1)}))
    result = replay_file(episode / TELEMETRY_FILE)
    assert result.obs_mismatches == result.reward_mismatches == 0
    lines = (episode / TELEMETRY_FILE).read_text().splitlines()
    header = json.loads(lines[0])
    header["observation_schema"]["sha256"] = "0" * 64
    lines[0] = json.dumps(header)
    (episode / TELEMETRY_FILE).write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="schema"):
        replay_file(episode / TELEMETRY_FILE)


def _record(decision, scored_ticks, x):
    facts = copy.deepcopy(FACTS)
    facts["nodes"][1][0] = x
    if not scored_ticks:
        facts["window"] = {key: 0 for key in facts["window"]}
    facts["window"]["scored_ticks"] = scored_ticks
    return {"decision": decision, "ticks_in_step": 5, "facts": facts}


def test_movement_accumulator_excludes_warmup_and_uncontrolled_nodes():
    records = [_record(0, 0, 10), _record(1, 0, 20), _record(2, 5, 23)]
    records[-1]["facts"]["nodes"][0][0] += 50
    result = metrics.episode_metrics(iter(records), 3, CONTRACT)
    assert result["travel_m_total"] == 3
    assert result["displacement_m_final"] == 3
    assert result["per_node_travel_m"] == {"node-b": 3, "node-c": 0}
    assert "travel_m_total" in metrics.METRICS and "travel_m_total" in metrics.CSV_METRICS


@pytest.mark.parametrize("records", [
    [_record(0, 0, 10), _record(1, 2, 20), _record(2, 5, 23)],
    [_record(0, 0, 10), _record(2, 5, 23)],
    [_record(0, 0, 10), _record(1, 0, 20)],
])
def test_movement_is_null_when_scored_path_is_unavailable(records):
    result = metrics.episode_metrics(iter(records), 3, CONTRACT)
    assert result["travel_m_total"] is None
    assert result["displacement_m_final"] is None


def test_metric_declares_its_accumulator_without_dispatch_changes(monkeypatch):
    class Count:
        def __init__(self): self.value = 0
        def add(self, record, num_links, contract): self.value += 1
    monkeypatch.setitem(metrics.REGISTRY, "sample_count", metrics.Metric(
        "count", None, True, lambda t: t.value, Count))
    assert metrics.episode_metrics(iter([_record(0, 0, 10)]), 3, CONTRACT)["sample_count"] == 1


def test_benchmark_selection_detects_changed_scales_and_thresholds():
    from scripts.rl.ops.benchmark import _row_selection, _selection_fields
    measured = RlSelection("service_v1", ("service_success",), (1,)).describe()
    assert _selection_fields(measured) == _row_selection(measured)
    changed_scale = copy.deepcopy(measured)
    changed_scale["observation_parameters"]["capacity_log10_denominator"] = 8
    assert _selection_fields(measured) != _row_selection(changed_scale)
    changed_threshold = copy.deepcopy(measured)
    changed_threshold["reward_parameters"]["service_success"]["delivery_threshold"] = 0.8
    assert _selection_fields(measured) != _row_selection(changed_threshold)


def test_experiment_plan_records_resolved_parameters(tmp_path, multi_run_config):
    from scripts.rl.policy.experiment import build_plan, load_matrix, load_plan
    from scripts.rl.tests.test_experiment_matrix import _matrix_data
    data = _matrix_data(multi_run_config)
    data["rows"] = [{"name": "service", "observation_preset": "service_v1",
                     "action_profile": "move_2d", "reward_components": ["service_success"],
                     "reward_weights": [1], "observation_parameters": {"capacity_log10_denominator": 8},
                     "reward_parameters": {"service_success": {"delivery_threshold": 0.8}}}]
    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_text(json.dumps(data))
    matrix = load_matrix(matrix_path)
    plan = build_plan(matrix, tmp_path / "plan", "/not-launched")
    args = next(step["args"] for step in plan["steps"] if step["kind"] == "train")
    scales = json.loads(args[args.index("--observation-parameters") + 1])
    rewards = json.loads(args[args.index("--reward-parameters") + 1])
    assert scales["capacity_log10_denominator"] == 8
    assert rewards["service_success"] == {"delivery_threshold": 0.8, "routable_threshold": 0.95}
    root = tmp_path / "obsolete"
    root.mkdir()
    (root / "experiment_plan.json").write_text(json.dumps({"experiment_plan_version": 1}))
    with pytest.raises(ValueError, match="experiment_plan_version"):
        load_plan(root)


def test_movement_metric_is_compared_and_exported(tmp_path):
    from scripts.rl.tests.test_policy_comparison import write_eval, _run, _outputs, _pick
    def movement(manifest):
        for name, block in manifest["policies"].items():
            for episode in block["episodes"]:
                episode["metrics"]["travel_m_total"] = 3 if name == "model" else 5
    evaluation = write_eval(tmp_path / "eval", model={11: 0.8}, seeds=[11], mutate=movement)
    out = tmp_path / "compare"
    assert _run(out, evaluation) == 0
    payload, rows = _outputs(out)
    paired = _pick(payload["evaluations"][0], metric="travel_m_total")
    assert paired["mean_difference"] == -2
    assert all(row["travel_m_total"] in ("3", "5") for row in rows)
