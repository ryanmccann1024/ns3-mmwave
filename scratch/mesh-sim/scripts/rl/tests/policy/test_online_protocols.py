"""The two online protocols stay separate: gated accounting and SB3 defaults/tail, plus their records."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.rl.policy import bundle as bundles
from scripts.rl.policy import online_adaptation
from scripts.rl.policy.online_adaptation import (
    OnlinePolicy,
    batch_for,
    eligible,
    gated_settings,
)
from scripts.rl.policy.operation import (
    ONLINE_MANIFEST_VERSION,
    run_online,
    run_operation,
    sb3_settings,
)

pytest.importorskip("sb3_contrib")

LEGACY_RECORD_KEYS = [
    "online_experiment_version",
    "status",
    "started_at",
    "bundle",
    "seeds",
    "episodes",
    "seed_roles",
    "settings",
    "binary_sha256",
    "scenario_identity",
]
LEGACY_EPISODE_KEYS = [
    "mode",
    "seed",
    "episode_dir",
    "return",
    "metrics",
    "initial_parameter_sha256",
    "final_parameter_sha256",
    "update_cycles",
    "untrained_tail_decisions",
]


def train_run(sim_binary, run_config, out_dir, monkeypatch, *extra):
    from scripts.rl import train

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "train",
            "--sim-binary",
            sim_binary,
            "--run-config",
            run_config,
            "--output-dir",
            str(out_dir),
            "--verbose",
            "0",
            "--band",
            "sub-6",
            "m-ppo",
            "--total-timesteps",
            "16",
            "--n-steps",
            "16",
            "--seed",
            "1",
            *extra,
        ],
    )
    assert train.main() == 0
    return out_dir


def three_decision_config(multi_run_config):
    """1.5 s at 0.5 s decisions: a 3-decision episode, so n_steps=2 leaves a one-decision tail."""
    path = Path(multi_run_config)
    path.write_text(
        path.read_text()
        .replace("duration_s = 1.0", "duration_s = 1.5")
        .replace("[rl]", "[rl]\ncoverage_enabled = true")
    )
    return str(path)


@pytest.mark.parametrize(
    "mission", ["coverage", "investigation", "recovery", "jamming"]
)
def test_eligibility_keeps_zero_demand_but_excludes_forced_windows(mission):
    facts = {
        "window": {"scored_ticks": 2, "demand_mbps_sum": 0},
        "deployment": {"active": False, "eligible_ticks": 0},
    }
    assert eligible(mission, facts) == (mission in ("coverage", "investigation"))
    facts["deployment"] = {"active": True, "eligible_ticks": 1}
    assert eligible(mission, facts) == (mission in ("coverage", "investigation"))
    facts["deployment"]["eligible_ticks"] = 2
    assert eligible(mission, facts)
    facts["window"]["scored_ticks"] = 0
    assert not eligible(mission, facts)


@pytest.mark.parametrize(
    "size,expected",
    [(120, 60), (110, 55), (80, 40), (60, 60), (50, 50), (2, 2), (61, 61)],
)
def test_partial_batch_never_has_a_singleton_or_pads(size, expected):
    assert batch_for(size, 60) == expected
    assert size % batch_for(size, 60) == 0
    with pytest.raises(ValueError):
        batch_for(1, 60)


def stub_policy(tmp_path, monkeypatch, n_steps=120):
    """Real rollout/GAE arithmetic with an inert optimizer stand-in."""
    import torch
    from gymnasium import spaces

    calls = []
    policy = SimpleNamespace(
        state_dict=lambda: {},
        optimizer=None,
        predict_values=lambda tensor: torch.tensor([[4.0]]),
        obs_to_tensor=lambda obs: (torch.as_tensor(np.asarray([obs])), False),
    )
    model = SimpleNamespace(
        observation_space=spaces.Box(-1, 1, (2,), dtype=np.float32),
        action_space=spaces.MultiDiscrete([5]),
        device="cpu",
        gamma=0.99,
        gae_lambda=0.95,
        policy=policy,
        _n_updates=0,
        n_epochs=10,
        num_timesteps=0,
        logger=SimpleNamespace(record=lambda *a: None, dump=lambda **k: None),
    )
    obj = OnlinePolicy.__new__(OnlinePolicy)
    obj.model = model
    obj.settings = {"n_steps": n_steps, "batch_size": 60}
    obj.buffer, obj.events, obj.initial = [], [], {}
    obj.collected = obj.trained = obj.skipped_tail = obj.optimizer_steps = (
        obj.decisions
    ) = obj.excluded = 0
    obj.output, obj.initial_digest, obj.start_steps = tmp_path, "initial", 0
    obj._hook = SimpleNamespace(remove=lambda: None)
    monkeypatch.setattr(
        bundles, "parameter_digest", lambda model: "stub-no-weights", raising=False
    )

    def no_optimizer():
        assert model.rollout_buffer.full
        calls.append(
            (
                model.rollout_buffer.buffer_size,
                model.batch_size,
                model.rollout_buffer.returns.copy(),
            )
        )
        obj.optimizer_steps += model.n_epochs * (
            model.rollout_buffer.buffer_size // model.batch_size
        )
        model._n_updates += model.n_epochs

    model.train = no_optimizer
    return obj, calls


def step(obj, decision, last, active=True, mission="recovery"):
    import torch

    obj.pending = (
        np.zeros(2),
        np.asarray([4]),
        torch.tensor([0.0]),
        torch.tensor([0.0]),
        np.ones(5, dtype=bool),
    )
    obj.mission = mission
    facts = {
        "window": {"scored_ticks": 2},
        "deployment": {"active": active, "eligible_ticks": 2 if active else 0},
    }
    obj.observe(np.zeros(2), 1.0, decision == last, False, {"time_s": decision}, facts)


def test_gated_update_accounting_and_final_partial_flush(tmp_path, monkeypatch):
    obj, calls = stub_policy(tmp_path, monkeypatch)
    for decision in range(1, 271):
        step(obj, decision, 270, active=decision > 10)
    assert [c[0] for c in calls] == [120, 120, 20]
    assert (
        obj.trained == obj.collected == 260
        and obj.excluded == 10
        and obj.skipped_tail == 0
    )
    assert [e["time_s"] for e in obj.events] == [130, 250, 270]
    assert [e["affects_later_actions"] for e in obj.events] == [True, True, False]
    assert calls[-1][2][-1, 0] == pytest.approx(1.0)  # terminal bootstrap is zero
    assert calls[0][2][-1, 0] == pytest.approx(1 + 0.99 * 4)  # continuing bootstrap
    saved = json.loads((tmp_path / "weight_updates.json").read_text())
    assert (
        saved["trained_decisions"] == 260 and saved["excluded_prefix_decisions"] == 10
    )


def test_gated_singleton_tail_is_skipped_and_counted(tmp_path, monkeypatch):
    obj, calls = stub_policy(tmp_path, monkeypatch)
    for decision in range(1, 122):
        step(obj, decision, 121)
    assert [c[0] for c in calls] == [120]
    assert obj.skipped_tail == 1 and obj.trained == 120 and obj.collected == 121
    assert obj.trained + obj.skipped_tail == obj.collected and not obj.buffer


def test_gated_ineligible_gap_refused_only_with_unflushed_buffer(tmp_path, monkeypatch):
    obj, _ = stub_policy(tmp_path, monkeypatch)
    for decision in range(1, 6):
        step(obj, decision, 999, active=False)
    assert obj.excluded == 5 and not obj.buffer
    step(obj, 6, 999, active=True)
    with pytest.raises(RuntimeError, match="ineligible gap"):
        step(obj, 7, 999, active=False)


def test_gated_settings_inherit_and_refuse_target_kl():
    parent = dict(
        learning_rate=3e-4,
        gamma=0.99,
        gae_lambda=0.95,
        n_epochs=10,
        ent_coef=0.0,
        clip_range=0.2,
        target_kl=None,
    )
    settings = gated_settings(parent, 120, 60)
    assert settings == {
        **parent,
        "n_steps": 120,
        "batch_size": 60,
        "eligible_only": True,
        "flush_final_partial": True,
    }
    with pytest.raises(ValueError, match="target_kl"):
        gated_settings({**parent, "target_kl": 0.02}, 120, 60)
    with pytest.raises(ValueError, match="clip_range"):
        gated_settings({k: v for k, v in parent.items() if k != "clip_range"}, 120, 60)
    with pytest.raises(ValueError, match="n_steps"):
        gated_settings(parent, None, 60)


def test_sb3_defaults_and_explicit_overrides():
    assert sb3_settings({"learning_rate": 3e-4}, 120, 60) == {
        "n_steps": 120,
        "batch_size": 60,
        "learning_rate": 1e-4,
        "target_kl": 0.02,
        "ent_coef": 0.001,
    }
    assert sb3_settings({"learning_rate": 5e-5}, 120, 60)["learning_rate"] == 5e-5
    assert sb3_settings({}, 120, 60)["learning_rate"] == 1e-4
    explicit = sb3_settings(
        {"learning_rate": 3e-4},
        120,
        40,
        learning_rate=2e-4,
        ent_coef=0.0,
        target_kl=0.05,
    )
    assert (
        explicit["learning_rate"] == 2e-4
        and explicit["ent_coef"] == 0.0
        and explicit["target_kl"] == 0.05
    )
    with pytest.raises(ValueError, match="divide"):
        sb3_settings({}, 120, 50)


def test_sb3_operation_records_tail_and_v5_fields(
    sim_binary, multi_run_config, tmp_path, monkeypatch
):
    config = three_decision_config(multi_run_config)
    run = train_run(sim_binary, config, tmp_path / "train", monkeypatch)
    bundle = bundles.read_bundle(run, "final")
    out = tmp_path / "op"
    record = run_operation(
        bundle,
        {"11": config},
        {"mission": "coverage"},
        "online_sb3_v1",
        11,
        "diagnostic",
        out,
        sim_binary,
        protocol_settings={"n_steps": 2, "batch_size": 2},
    )
    assert record["online_experiment_version"] == ONLINE_MANIFEST_VERSION == 5
    assert record["protocol"] == "online_sb3_v1" and record["status"] == "completed"
    assert record["settings"] == {
        "n_steps": 2,
        "batch_size": 2,
        "learning_rate": 1e-4,
        "target_kl": 0.02,
        "ent_coef": 0.001,
        "band": "sub-6",
        "band_source": "parent",
        "decision_records": None,
    }
    accounting = record["accounting"]
    assert accounting["episode_budget"] == accounting["actual_decisions"] == 3
    assert (
        accounting["untrained_tail_decisions"] == 3 % 2 == 1
        and accounting["update_cycles"] >= 1
    )
    assert (
        record["model"]["initial_parameter_sha256"]
        != record["model"]["final_parameter_sha256"]
    )
    assert (out / record["model"]["adapted_model"]).is_file()
    saved = json.loads((out / "online_manifest.json").read_text())
    for key in (
        "protocol",
        "settings",
        "parent",
        "model",
        "optimizer",
        "seed",
        "seed_role",
        "schedule",
        "accounting",
        "evaluation",
        "binary_sha256",
        "scenario_identity",
    ):
        assert key in saved
    with pytest.raises(ValueError, match="training seed"):
        run_operation(
            bundle,
            {"1": config},
            {"mission": "coverage"},
            "online_sb3_v1",
            1,
            "diagnostic",
            tmp_path / "reuse",
            sim_binary,
            protocol_settings={"n_steps": 2, "batch_size": 2},
        )


def test_gated_operation_reloads_parent_per_seed(
    sim_binary, multi_run_config, tmp_path, monkeypatch
):
    config = three_decision_config(multi_run_config)
    run = train_run(sim_binary, config, tmp_path / "train", monkeypatch)
    bundle = bundles.read_bundle(run, "final")
    configs = {"11": config, "12": config}
    records = [
        run_operation(
            bundle,
            configs,
            {"mission": "coverage"},
            "online_gated_v1",
            seed,
            "diagnostic",
            tmp_path / f"seed-{seed}",
            sim_binary,
            protocol_settings={"n_steps": 2, "batch_size": 2},
            evaluation_seeds=[11, 12],
            allow_different_scenario=True,
        )
        for seed in (11, 12)
    ]
    for record in records:
        assert (
            record["protocol"] == "online_gated_v1"
            and record["settings"]["target_kl"] is None
        )
        assert (
            record["settings"]["eligible_only"]
            and record["settings"]["flush_final_partial"]
        )
        accounting = record["accounting"]
        assert (
            accounting["trained_decisions"] + accounting["untrained_tail_decisions"]
            == accounting["eligible_decisions"]
        )
        assert (
            accounting["untrained_tail_decisions"] == 1
            and accounting["update_cycles"] == 1
        )
    assert (
        records[0]["model"]["initial_parameter_sha256"]
        == records[1]["model"]["initial_parameter_sha256"]
    )
    assert (
        records[0]["optimizer"]["initial_optimizer_sha256"]
        == records[1]["optimizer"]["initial_optimizer_sha256"]
    )


def test_legacy_cli_envelope_v3_default_and_v4_other_orders(
    sim_binary, multi_run_config, tmp_path, monkeypatch
):
    config = Path(multi_run_config)
    config.write_text(
        config.read_text().replace("[rl]", "[rl]\ncoverage_enabled = true")
    )
    run = train_run(
        sim_binary,
        str(config),
        tmp_path / "train",
        monkeypatch,
        "--eval-every-steps",
        "16",
        "--eval-episodes",
        "1",
        "--eval-seed",
        "2",
    )
    record = run_online(run, sim_binary, tmp_path / "v3", [11], n_steps=2, batch_size=2)
    assert (
        record["online_experiment_version"] == 3
        and "protocol" not in record
        and "modes" not in record
    )
    saved = json.loads((tmp_path / "v3/online_manifest.json").read_text())
    assert list(saved) == LEGACY_RECORD_KEYS + ["ended_at"]
    assert [list(e) for e in saved["episodes"]] == [LEGACY_EPISODE_KEYS] * 2
    assert Path(saved["episodes"][0]["episode_dir"]).is_absolute()
    assert [e["mode"] for e in saved["episodes"]] == ["fixed_sampled", "online"]
    reversed_order = run_online(
        run,
        sim_binary,
        tmp_path / "v4",
        [11],
        n_steps=2,
        batch_size=2,
        modes=("online", "fixed_sampled"),
    )
    assert reversed_order["online_experiment_version"] == 4 and reversed_order[
        "modes"
    ] == ["online", "fixed_sampled"]
    sampled = run_online(
        run,
        sim_binary,
        tmp_path / "v4-sampled",
        [11],
        n_steps=2,
        batch_size=2,
        modes=("fixed_sampled",),
    )
    assert (
        sampled["online_experiment_version"] == 4
        and sampled["episodes"][0]["update_cycles"] == 0
    )
    assert (
        run_online(run, sim_binary, tmp_path / "v3", [11], n_steps=2, batch_size=2)
        == saved
    )


def test_online_cli_reexports_existing_helpers():
    from scripts.rl import online
    from scripts.rl.policy import operation

    historical = {
        "ActionMasker",
        "DEFAULT_MODES",
        "MaskablePPO",
        "MeshRlEnv",
        "ModelPolicy",
        "UpdateRecorder",
        "check_compatibility",
        "configure",
        "endpoint_metrics",
        "episode_metrics",
        "eval_selection",
        "main",
        "now_iso",
        "operation_modes",
        "parameter_digest",
        "parse_seed_spec",
        "read_bundle",
        "read_scenario_identity",
        "run_episode",
        "run_online",
        "selection_from_manifest",
        "write_json",
        "write_reward_matrix",
    }
    assert all(
        callable(getattr(online, name)) or name == "DEFAULT_MODES"
        for name in historical
    )
    assert set(online.REEXPORTED) | {"main", "run_online"} == historical
    assert (
        online.parameter_digest is bundles.parameter_digest
        and online.read_bundle is bundles.read_bundle
    )
    assert online.UpdateRecorder is operation.UpdateRecorder
    assert online.DEFAULT_MODES == ("fixed_sampled", "online")
    with pytest.raises(ValueError):
        online.operation_modes(["online", "online"])


def test_online_protocols_refuse_schedules_and_unknown_settings(tmp_path):
    from scripts.rl.policy.operation import _resolve_protocol

    bundle = SimpleNamespace(
        manifest={
            "hyperparameters": dict(
                learning_rate=3e-4,
                gamma=0.99,
                gae_lambda=0.95,
                n_epochs=10,
                ent_coef=0.0,
                clip_range=0.2,
                target_kl=None,
            )
        }
    )
    schedule = {"kind": "initial-sampling", "settings": {"initial_sample_decisions": 5}}
    with pytest.raises(ValueError, match="cannot be combined"):
        _resolve_protocol(
            "online_gated_v1", bundle, {"n_steps": 2, "batch_size": 2}, schedule
        )
    with pytest.raises(ValueError, match="inherited"):
        _resolve_protocol(
            "online_gated_v1",
            bundle,
            {"n_steps": 2, "batch_size": 2, "learning_rate": 1.0},
            None,
        )
    with pytest.raises(ValueError, match="explicit n_steps"):
        _resolve_protocol("online_sb3_v1", bundle, {"batch_size": 2}, None)
    with pytest.raises(ValueError, match="no protocol settings"):
        _resolve_protocol("frozen_sampled", bundle, {"n_steps": 2}, None)
    assert online_adaptation.GATED_PROTOCOL == "online_gated_v1"


def test_gated_loaded_settings_match_before_adaptation():
    from scripts.rl.policy.online_adaptation import (
        INHERITED_PPO_KEYS,
        verify_inherited_settings,
    )

    settings = dict(
        learning_rate=0.0003,
        gamma=0.99,
        gae_lambda=0.95,
        n_epochs=10,
        ent_coef=0.0,
        clip_range=0.2,
        target_kl=None,
    )
    model = SimpleNamespace(**settings)
    model.clip_range = lambda _: 0.2
    verify_inherited_settings(model, settings)
    for key in INHERITED_PPO_KEYS:
        wrong = SimpleNamespace(**settings)
        setattr(wrong, key, "different")
        with pytest.raises(ValueError, match=key):
            verify_inherited_settings(wrong, settings)
