"""Behavior checks preserved from the experiment pilots; no native simulation."""

import subprocess
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from scripts.rl.env.rewards import RewardComposer
from scripts.rl.env.rewards import reward_schema
from scripts.rl.env.rewards.objectives import COMPONENT_NAMES
from scripts.rl.policy.online_adaptation import eligible
from scripts.rl.policy.online_adaptation import batch_for
from scripts.rl.policy.online_adaptation import OnlinePolicy
from scripts.rl.tests.env.test_observations_rewards import CONTRACT

ROOT = Path(__file__).resolve().parents[4]
INPUT = ROOT / "inputs/custom/10-23-1"


@pytest.fixture(autouse=True)
def forbid_processes(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("no simulator, fake peer or training subprocess")

    monkeypatch.setattr(subprocess, "Popen", forbidden)


def score(mission, context, window=None, contract=None):
    return RewardComposer([COMPONENT_NAMES[mission]], [1]).compose(
        window or {"scored_ticks": 2}, 0, contract or {}, context
    )


@pytest.mark.parametrize("fraction", [0.0, 0.2, 0.49, 0.5, 0.89, 1.0])
def test_coverage_is_continuous_not_thresholded(fraction):
    assert score("coverage", {"coverage": {"fraction": fraction}}).total == fraction


def test_investigation_single_mean_distance_and_availability():
    contract = {
        "mission": {"goal_x": 345, "goal_y": 300, "team_radius_m": 50},
        "bounds": {"x_min": 0, "x_max": 400, "y_min": 0, "y_max": 400},
    }
    context = {"nodes": [[345, 300], [445, 300]], "node_available": [True, True]}
    far = score("investigation", context, contract=contract).total
    assert far == pytest.approx(1 - 25 / np.hypot(400, 400))
    context["nodes"][1] = [395, 300]
    assert score("investigation", context, contract=contract).total == 1
    context["nodes"][1] = [445, 300]
    context["node_available"][1] = False
    assert score("investigation", context, contract=contract).total == 1
    context["node_available"] = [False, False]
    assert score("investigation", context, contract=contract).total == 0


@pytest.mark.parametrize("mission", ["recovery", "jamming"])
@pytest.mark.parametrize("ratio", [0.0, 0.2, 0.89, 0.9, 1.0])
def test_event_reward_delivers_partial_feedback_and_no_free_demand(mission, ratio):
    context = {
        "deployment": {"active": True, "eligible_ticks": 2},
        "mission": {
            "survivor_demand_mbps_sum": 10,
            "survivor_delivered_mbps_sum": 10 * ratio,
        },
    }
    window = {
        "scored_ticks": 2,
        "demand_mbps_sum": 10,
        "delivered_mbps_sum": 10 * ratio,
    }
    assert score(mission, context, window).total == pytest.approx(ratio)
    context["deployment"]["eligible_ticks"] = 1
    assert score(mission, context, window).total == 0
    context["deployment"] = {"active": False, "eligible_ticks": 0}
    assert score(mission, context, window).total == 0
    context["deployment"] = {"active": True, "eligible_ticks": 2}
    context["mission"]["survivor_demand_mbps_sum"] = 0
    window["demand_mbps_sum"] = 0
    assert score(mission, context, window).total == 0


def test_jammer_onset_not_reward_identity_but_geometry_is():
    contract = {
        **CONTRACT,
        "deployment_gate": {"version": 1, "source": "control_start_s"},
        "control_start_s": 160,
    }
    comp = COMPONENT_NAMES["jamming"]
    a = reward_schema([comp], [1], contract=contract)
    contract["control_start_s"] = 180
    assert a == reward_schema([comp], [1], contract=contract)
    comp = COMPONENT_NAMES["investigation"]
    contract["mission"] = {"goal_x": 345, "goal_y": 300, "team_radius_m": 50}
    a = reward_schema([comp], [1], contract=contract)
    contract["bounds"] = {**contract["bounds"], "x_max": 400}
    assert a != reward_schema([comp], [1], contract=contract)


@pytest.mark.parametrize(
    "mission", ["coverage", "investigation", "recovery", "jamming"]
)
def test_online_eligibility_preserves_zero_demand_but_excludes_forced_windows(mission):
    f = {
        "window": {"scored_ticks": 2, "demand_mbps_sum": 0},
        "deployment": {"active": False, "eligible_ticks": 0},
    }
    assert eligible(mission, f) == (mission in ("coverage", "investigation"))
    f["deployment"] = {"active": True, "eligible_ticks": 1}
    assert eligible(mission, f) == (mission in ("coverage", "investigation"))
    f["deployment"]["eligible_ticks"] = 2
    assert eligible(mission, f)
    f["window"]["scored_ticks"] = 0
    assert not eligible(mission, f)


@pytest.mark.parametrize(
    "size,expected",
    [(120, 60), (110, 55), (80, 40), (60, 60), (50, 50), (2, 2), (61, 61)],
)
def test_partial_batch_never_has_a_singleton_or_pads(size, expected):
    assert batch_for(size, 60) == expected
    assert size % batch_for(size, 60) == 0
    with pytest.raises(ValueError):
        batch_for(1, 60)


def test_online_buffer_and_update_accounting_without_an_optimizer(
    tmp_path, monkeypatch
):
    """Real rollout/GAE arithmetic, but train and optimizer remain inert stubs."""
    import torch
    from gymnasium import spaces
    from scripts.rl.policy import online_adaptation as adaptation

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
    obj.settings = {"n_steps": 120, "batch_size": 60}
    obj.buffer = []
    obj.initial = {}
    obj.events = []
    obj.collected = 0
    obj.trained = 0
    obj.skipped_tail = 0
    obj.optimizer_steps = 0
    obj.output = tmp_path
    obj.initial_digest = "initial"
    obj.decisions = 0
    obj.excluded = 0
    obj.start_steps = 0
    obj._hook = SimpleNamespace(remove=lambda: None)
    monkeypatch.setattr(
        adaptation._bundle, "parameter_digest", lambda model: "stub-no-weights"
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
    for decision in range(1, 271):
        obj.pending = (
            np.zeros(2),
            np.asarray([4]),
            torch.tensor([0.0]),
            torch.tensor([0.0]),
            np.ones(5, dtype=bool),
        )
        facts = {
            "window": {"scored_ticks": 2},
            "deployment": {
                "active": decision > 10,
                "eligible_ticks": 2 if decision > 10 else 0,
            },
        }
        obj.mission = "recovery"
        obj.observe(
            np.zeros(2), 1.0, decision == 270, False, {"time_s": decision}, facts
        )
    assert [c[0] for c in calls] == [120, 120, 20]
    assert (
        obj.trained == obj.collected == 260
        and obj.excluded == 10
        and obj.skipped_tail == 0
    )
    assert [e["time_s"] for e in obj.events] == [130, 250, 270]
    assert [e["affects_later_actions"] for e in obj.events] == [True, True, False]
    assert calls[-1][2][-1, 0] == pytest.approx(1.0)  # terminal bootstrap must be zero
    assert calls[0][2][-1, 0] == pytest.approx(1 + 0.99 * 4)  # continuing bootstrap
