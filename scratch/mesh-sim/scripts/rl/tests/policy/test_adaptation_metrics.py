"""Behavior checks preserved from the experiment pilots; no native simulation."""

import copy
import json
from pathlib import Path

import pytest

from scripts.rl.agents.mask_ppo import MaskablePPOConfig
from scripts.rl.agents.mask_ppo import MaskablePpoTrainer
from scripts.rl.env.mesh_env import MeshRlEnv
from scripts.rl.env.rewards import RewardComposer
from scripts.rl.env.rewards import position_context
from scripts.rl.env.jammer_motion import prepare_motion_config
from scripts.rl.online import run_online
from scripts.rl.tests.policy.test_evaluation_pipeline import _train


def test_adaptive_motion_charges_previous_health_and_resets():
    composer = RewardComposer(["adaptive_movement_cost"], [-1])
    healthy = {"coverage_fraction": 1, "fair_node_service": 1, "travel_fraction": 1}
    window = {"scored_ticks": 1, "demand_mbps_sum": 10, "delivered_mbps_sum": 10}
    assert composer.compose(window, 0, {}, dict(healthy)).total == pytest.approx(-0.02)
    poor = {**healthy, "fair_node_service": 0, "coverage_fraction": 0.2}
    assert composer.compose(
        {**window, "delivered_mbps_sum": 0}, 0, {}, poor
    ).total == pytest.approx(-0.1)
    assert poor["previous_network_health"] == 1
    assert composer.compose(window, 0, {}, dict(healthy)).total == pytest.approx(-0.02)
    composer.reset()
    assert composer.compose(window, 0, {}, dict(healthy)).total == pytest.approx(-0.02)


def test_fair_feedback_rewards_partial_recovery(sim_binary, multi_run_config, tmp_path):
    env = MeshRlEnv(
        sim_binary, multi_run_config, seed=1, output_dir=str(tmp_path / "env")
    )
    try:
        env.reset()
        env.step([4, 4, 4])
        facts = copy.deepcopy(env._protocol.facts)
        facts["node_service"] = [[10, 0], [10, 2.5], [0, 0]]
        context = position_context(facts, facts["nodes"], facts["nodes"], env.contract)
        assert context["worst_node_delivery_fraction"] == 0
        assert context["fair_node_service"] == pytest.approx(0.25)
        composer = RewardComposer(["fair_node_service"], [0.3])
        assert composer.compose(
            facts["window"], 0, env.contract, context
        ).total == pytest.approx(0.075)
        facts["node_service"] = [[0, 0]] * 3
        context = position_context(facts, facts["nodes"], facts["nodes"], env.contract)
        assert (
            composer.compose(facts["window"], 0, env.contract, context).valid[
                "fair_node_service"
            ]
            == 0
        )
    finally:
        env.close()


def test_constructor_receives_network_and_optimizer_settings(
    sim_binary, multi_run_config, tmp_path
):
    env = MeshRlEnv(
        sim_binary, multi_run_config, seed=1, output_dir=str(tmp_path / "env")
    )
    try:
        env.reset()
        cfg = MaskablePPOConfig(
            total_timesteps=4,
            n_steps=4,
            batch_size=2,
            learning_rate=0.0001,
            gae_lambda=0.98,
            target_kl=0.02,
            net_arch=(128, 128, 128),
            ent_coef_final=0.001,
        )
        trainer = MaskablePpoTrainer(cfg, env, lambda e: e.unwrapped.action_masks())
        assert trainer.model.policy_kwargs["net_arch"] == {
            "pi": [128] * 3,
            "vf": [128] * 3,
        }
        assert trainer.model.policy.optimizer.param_groups[0]["lr"] == 0.0001
        assert trainer.model.gae_lambda == 0.98 and trainer.model.target_kl == 0.02
        trainer.train()
        assert trainer.model.ent_coef == 0.001
    finally:
        env.close()


@pytest.mark.parametrize(
    "settings",
    [
        {"net_arch": ()},
        {"learning_rate": 0},
        {"target_kl": 0},
        {"gae_lambda": 2},
        {"ent_coef_final": float("nan")},
    ],
)
def test_bad_ppo_parameters_rejected(settings):
    with pytest.raises(ValueError):
        MaskablePPOConfig(**settings)


def test_routes_vary_without_exposing_coordinates_to_actor(tmp_path):
    source = tmp_path / "scenario/run.ini"
    source.parent.mkdir()
    source.write_text(
        "[scenario]\nduration_s=600\nnodes_file=nodes.json\njammers_file=jammers.json\n[rl]\njammer_motion_profile=sweep_v1\n"
    )
    (source.parent / "nodes.json").write_text("[]")
    (source.parent / "jammers.json").write_text(json.dumps([{}]))
    variants = []
    for index, evaluation in enumerate((False, False, True, True)):
        destination = tmp_path / str(index)
        destination.mkdir()
        path, metadata = prepare_motion_config(
            source, destination, 401 + index, index, evaluation
        )
        variants.append(metadata)
        assert Path(path).is_file()
        assert metadata["waypoints"][0] == {"t": 0, "x": 0, "y": 0, "z": 1.5}
        assert metadata["waypoints"][-1]["t"] == 600
    assert [v["axis"] for v in variants] == ["x", "x", "y", "y"]
    assert variants[0]["reverse"] != variants[1]["reverse"]
    assert variants[2]["reverse"] != variants[3]["reverse"]


def test_online_updates_and_fixed_control_are_distinct(
    sim_binary, multi_run_config, tmp_path, monkeypatch
):
    ini = Path(multi_run_config)
    ini.write_text(ini.read_text().replace("[rl]", "[rl]\ncoverage_enabled = true"))
    run = tmp_path / "training"
    assert (
        _train(
            sim_binary,
            multi_run_config,
            run,
            monkeypatch,
            "--eval-every-steps",
            "16",
            "--eval-episodes",
            "1",
            "--eval-seed",
            "2",
        )
        == 0
    )
    record = run_online(
        run, sim_binary, tmp_path / "online", [11, 12], n_steps=2, batch_size=2
    )
    assert record["status"] == "completed"
    fixed = [e for e in record["episodes"] if e["mode"] == "fixed_sampled"]
    online = [e for e in record["episodes"] if e["mode"] == "online"]
    assert len(fixed) == len(online) == 2
    for control, adapted in zip(fixed, online):
        assert (
            control["initial_parameter_sha256"] == adapted["initial_parameter_sha256"]
        )
        assert control["initial_parameter_sha256"] == control["final_parameter_sha256"]
        assert adapted["initial_parameter_sha256"] != adapted["final_parameter_sha256"]
        assert adapted["update_cycles"] == 1
    assert len({e["initial_parameter_sha256"] for e in online}) == 1
