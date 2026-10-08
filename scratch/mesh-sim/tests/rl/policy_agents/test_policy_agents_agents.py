"""agents/mask_ppo.py, agents/callbacks.py, agents/q_learning.py on a tiny in-process env.

Contract sources: scripts/rl/agents/CLAUDE.md and README.md: only seed, n_steps, gamma,
ent_coef (plus verbose / tensorboard_log for logging) reach MaskablePPO, everything
else is SB3 default; load forces device=cpu; BoundedCheckpointCallback keeps the newest
keep_last (>= 1) `checkpoints/checkpoint_<N>_steps.zip`; list_checkpoints returns
(steps, path) ascending and ignores names it cannot parse; policy/bundle.py depends on
that naming. TabularQLearning discretizes (x_bin, y_bin, sinr_bin) with epsilon-greedy
predict(). No simulator is used; training budgets are a few dozen timesteps.
"""

import inspect
import json
from pathlib import Path

import numpy as np
import pytest

sb3_contrib = pytest.importorskip("sb3_contrib")
gym = pytest.importorskip("gymnasium")
torch = pytest.importorskip("torch")

from sb3_contrib import MaskablePPO  # noqa: E402
from sb3_contrib.common.maskable.callbacks import MaskableEvalCallback  # noqa: E402
from sb3_contrib.common.wrappers import ActionMasker  # noqa: E402

from scripts.rl.agents import callbacks as cb  # noqa: E402
from scripts.rl.agents.mask_ppo import MaskablePPOConfig, MaskablePpoTrainer  # noqa: E402
# agents/__init__.py imports sb3_contrib eagerly, so this import must follow the skip guard.
from scripts.rl.agents.q_learning import TabularQLearning  # noqa: E402

HOLD = 4


class TinyMaskEnv(gym.Env):
    """MultiDiscrete([5, 5]) env, 4 decisions per episode, logs every action it receives."""

    def __init__(self, hold_only=False):
        super().__init__()
        self.observation_space = gym.spaces.Box(-1.0, 1.0, shape=(4,), dtype=np.float32)
        self.action_space = gym.spaces.MultiDiscrete([5, 5])
        self.hold_only = hold_only
        self.seen = []
        self._t = 0

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._t = 0
        return self._obs(), {}

    def _obs(self):
        return self.np_random.uniform(-1, 1, size=4).astype(np.float32)

    def step(self, action):
        self.seen.append([int(a) for a in action])
        self._t += 1
        reward = float(sum(1 for a in action if int(a) == 0))
        return self._obs(), reward, self._t >= 4, False, {}

    def action_masks(self):
        if not self.hold_only:
            return np.ones(10, dtype=bool)
        mask = np.zeros(10, dtype=bool)
        mask[[HOLD, 5 + HOLD]] = True
        return mask


def mask_fn(env):
    return env.unwrapped.action_masks()


def _cfg(**overrides):
    values = dict(total_timesteps=16, n_steps=8, gamma=0.9, ent_coef=0.02, seed=3,
                  verbose=0)
    values.update(overrides)
    return MaskablePPOConfig(**values)


def _params(model):
    return [p.detach().cpu().clone() for p in model.policy.parameters()]


# 1. MaskablePPOConfig / MaskablePpoTrainer -------------------------------------------

def test_config_defaults_match_the_documented_table():
    cfg = MaskablePPOConfig()
    assert (cfg.total_timesteps, cfg.n_steps, cfg.gamma, cfg.ent_coef, cfg.seed,
            cfg.verbose, cfg.tensorboard_log) == (100_000, 1024, 0.95, 0.01, 42, 1, None)


def test_only_the_documented_hyperparameters_reach_maskable_ppo():
    trainer = MaskablePpoTrainer(_cfg(), TinyMaskEnv(), mask_fn)
    model = trainer.model
    assert isinstance(trainer.env, ActionMasker)
    assert (model.n_steps, model.gamma, model.ent_coef, model.seed) == (8, 0.9, 0.02, 3)
    assert model.verbose == 0 and model.tensorboard_log is None
    defaults = {name: p.default for name, p in inspect.signature(MaskablePPO).parameters.items()}
    for name in ("learning_rate", "batch_size", "n_epochs", "gae_lambda", "vf_coef",
                 "max_grad_norm", "normalize_advantage", "target_kl"):
        assert getattr(model, name) == defaults[name], name
    assert model.clip_range(1.0) == defaults["clip_range"]


def test_train_spends_exactly_the_budget_and_respects_the_mask():
    env = TinyMaskEnv(hold_only=True)
    trainer = MaskablePpoTrainer(_cfg(total_timesteps=16, n_steps=8), env, mask_fn)
    model = trainer.train()
    assert model is trainer.model
    assert model.num_timesteps == 16
    assert len(env.seen) == 16
    assert all(action == [HOLD, HOLD] for action in env.seen)


def test_same_seed_gives_the_same_initial_policy_and_different_seed_does_not():
    first = _params(MaskablePpoTrainer(_cfg(seed=7), TinyMaskEnv(), mask_fn).model)
    again = _params(MaskablePpoTrainer(_cfg(seed=7), TinyMaskEnv(), mask_fn).model)
    other = _params(MaskablePpoTrainer(_cfg(seed=8), TinyMaskEnv(), mask_fn).model)
    assert all(torch.equal(a, b) for a, b in zip(first, again))
    assert not all(torch.equal(a, b) for a, b in zip(first, other))


def test_same_seed_training_is_reproducible():
    def run():
        trainer = MaskablePpoTrainer(_cfg(seed=11), TinyMaskEnv(), mask_fn)
        trainer.train()
        return _params(trainer.model)

    assert all(torch.equal(a, b) for a, b in zip(run(), run()))


def test_save_and_load_on_cpu_reproduces_deterministic_predictions(tmp_path):
    trainer = MaskablePpoTrainer(_cfg(), TinyMaskEnv(), mask_fn)
    trainer.train()
    trainer.save(str(tmp_path / "model"))
    assert (tmp_path / "model.zip").is_file()

    loaded = MaskablePpoTrainer.load(str(tmp_path / "model.zip"), TinyMaskEnv(), mask_fn)
    assert loaded.device.type == "cpu"
    obs = np.linspace(-1, 1, 4).astype(np.float32)
    mask = np.ones(10, dtype=bool)
    expected, _ = trainer.model.predict(obs, action_masks=mask, deterministic=True)
    actual, _ = loaded.predict(obs, action_masks=mask, deterministic=True)
    assert actual.tolist() == expected.tolist()
    # A restrictive live mask is honored by the reloaded model.
    hold_only = TinyMaskEnv(hold_only=True).action_masks()
    action, _ = loaded.predict(obs, action_masks=hold_only, deterministic=True)
    assert action.tolist() == [HOLD, HOLD]


def test_model_policy_with_preference_capture_on_a_real_model():
    from scripts.rl.policy.evaluate import ModelPolicy
    from scripts.rl.policy.preferences import PreferenceCapture

    trainer = MaskablePpoTrainer(_cfg(), TinyMaskEnv(), mask_fn)
    capture = PreferenceCapture()
    policy = ModelPolicy(trainer.model, capture)
    assert capture.registered
    obs = np.zeros(4, dtype=np.float32)
    mask = TinyMaskEnv(hold_only=True).action_masks()
    first = policy.act(obs, mask, {})
    logits = capture.take()
    assert first.tolist() == [HOLD, HOLD]
    assert logits.shape == (10,)                 # one logit per (slot, action)
    assert policy.act(obs, mask, {}).tolist() == first.tolist()


# 2. list_checkpoints -----------------------------------------------------------------

def _touch(directory: Path, *names):
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_bytes(b"x")


def test_list_checkpoints_sorts_by_step_number_not_by_name(tmp_path):
    _touch(tmp_path, "checkpoint_100_steps.zip", "checkpoint_20_steps.zip",
           "checkpoint_9_steps.zip", "checkpoint_1000_steps.zip")
    assert [steps for steps, _ in cb.list_checkpoints(tmp_path)] == [9, 20, 100, 1000]
    assert all(path.parent == tmp_path for _, path in cb.list_checkpoints(tmp_path))


def test_list_checkpoints_ignores_names_it_cannot_parse(tmp_path):
    _touch(tmp_path, "checkpoint_16_steps.zip", "checkpoint_abc_steps.zip",
           "checkpoint__steps.zip", "checkpoint_-4_steps.zip", "checkpoint_1_2_steps.zip",
           "checkpoint_8_steps.zip.bak", "checkpoint_8_steps.pkl", "other_8_steps.zip",
           "checkpoint_ 8_steps.zip", "notes.txt")
    assert [steps for steps, _ in cb.list_checkpoints(tmp_path)] == [16]


def test_list_checkpoints_of_a_missing_dir_is_empty(tmp_path):
    assert cb.list_checkpoints(tmp_path / "absent") == []


def test_list_checkpoints_honors_a_custom_prefix(tmp_path):
    _touch(tmp_path, "snap_5_steps.zip", "checkpoint_6_steps.zip")
    assert [s for s, _ in cb.list_checkpoints(tmp_path, "snap")] == [5]


# 3. BoundedCheckpointCallback / build_callbacks --------------------------------------

@pytest.mark.parametrize("keep_last", [0, -1, "0"])
def test_keep_last_below_one_is_refused(tmp_path, keep_last):
    with pytest.raises(ValueError, match="keep_last must be >= 1"):
        cb.BoundedCheckpointCallback(save_freq=1, save_path=str(tmp_path),
                                     keep_last=keep_last)


def _train_with_checkpoints(tmp_path, save_freq, keep_last, total, n_steps, extra=()):
    out = tmp_path / "run"
    if extra:
        _touch(out / cb.CHECKPOINT_DIR, *extra)
    callbacks, eval_callback = cb.build_callbacks(str(out), save_freq, keep_last, None, 0, 1, 0)
    assert eval_callback is None and len(callbacks) == 1
    trainer = MaskablePpoTrainer(_cfg(total_timesteps=total, n_steps=n_steps),
                                 TinyMaskEnv(), mask_fn)
    trainer.train(callback=callbacks)
    return out / cb.CHECKPOINT_DIR


def test_pruning_keeps_the_numerically_newest_checkpoints(tmp_path):
    # Saves at 5, 10, 15, 20; a lexicographic sort would keep 20 and 5.
    directory = _train_with_checkpoints(tmp_path, save_freq=5, keep_last=2, total=20,
                                        n_steps=10)
    assert sorted(p.name for p in directory.iterdir()) == [
        "checkpoint_15_steps.zip", "checkpoint_20_steps.zip"]


def test_keep_last_one_keeps_only_the_final_checkpoint(tmp_path):
    directory = _train_with_checkpoints(tmp_path, save_freq=4, keep_last=1, total=16,
                                        n_steps=8)
    assert [s for s, _ in cb.list_checkpoints(directory)] == [16]


def test_keep_last_above_the_count_keeps_everything(tmp_path):
    directory = _train_with_checkpoints(tmp_path, save_freq=8, keep_last=10, total=16,
                                        n_steps=8)
    assert [s for s, _ in cb.list_checkpoints(directory)] == [8, 16]


def test_pruning_leaves_unrelated_files_alone(tmp_path):
    directory = _train_with_checkpoints(tmp_path, save_freq=8, keep_last=1, total=16,
                                        n_steps=8,
                                        extra=("notes.txt", "checkpoint_abc_steps.zip"))
    assert sorted(p.name for p in directory.iterdir()) == [
        "checkpoint_16_steps.zip", "checkpoint_abc_steps.zip", "notes.txt"]


@pytest.mark.parametrize("checkpoint_every, eval_every, with_env, kinds", [
    (0, 0, True, []),
    (-1, -1, True, []),
    (0, 5, False, []),
    (3, 0, True, ["checkpoint"]),
    (0, 5, True, ["eval"]),
    (3, 5, True, ["checkpoint", "eval"]),
])
def test_build_callbacks_enables_only_requested_cadences(tmp_path, checkpoint_every,
                                                         eval_every, with_env, kinds):
    eval_env = TinyMaskEnv() if with_env else None
    callbacks, eval_callback = cb.build_callbacks(str(tmp_path), checkpoint_every, 2,
                                                  eval_env, eval_every, 1, 0)
    found = ["checkpoint" if isinstance(c, cb.BoundedCheckpointCallback) else "eval"
             for c in callbacks]
    assert found == kinds
    assert (eval_callback is not None) == ("eval" in kinds)


def test_build_callbacks_wiring(tmp_path):
    callbacks, eval_callback = cb.build_callbacks(str(tmp_path), 3, 2, TinyMaskEnv(), 5, 2, 0)
    checkpoint = callbacks[0]
    assert checkpoint.save_freq == 3 and checkpoint.keep_last == 2
    assert Path(checkpoint.save_path) == tmp_path / "checkpoints"
    assert checkpoint.name_prefix == "checkpoint"
    assert isinstance(eval_callback, MaskableEvalCallback) and callbacks[1] is eval_callback
    assert (eval_callback.eval_freq, eval_callback.n_eval_episodes) == (5, 2)
    assert eval_callback.deterministic is True and eval_callback.use_masking is True
    assert Path(eval_callback.best_model_save_path) == tmp_path
    assert Path(eval_callback.log_path).parent == tmp_path


def test_eval_callback_writes_the_best_model_into_out_dir(tmp_path):
    callbacks, eval_callback = cb.build_callbacks(str(tmp_path), 0, 1, TinyMaskEnv(), 8, 1, 0)
    trainer = MaskablePpoTrainer(_cfg(total_timesteps=16, n_steps=8), TinyMaskEnv(), mask_fn)
    trainer.train(callback=callbacks)
    assert (tmp_path / "best_model.zip").is_file()
    assert (tmp_path / "evaluations.npz").is_file()
    assert np.isfinite(eval_callback.best_mean_reward)


def test_retained_checkpoints_are_selectable_through_read_bundle(tmp_path):
    from scripts.rl import train
    from scripts.rl.cli_common import sha256_file
    from scripts.rl.policy.bundle import read_bundle

    directory = _train_with_checkpoints(tmp_path, save_freq=4, keep_last=2, total=16,
                                        n_steps=8)
    run_dir = directory.parent
    model = run_dir / "maskable_ppo_mesh.zip"
    model.write_bytes(b"final")
    manifest = {"manifest_version": train.MANIFEST_VERSION, "status": "completed",
                "control_mode": "centralized", "model_path": str(model),
                "model_sha256": sha256_file(model),
                "checkpoints": train._checkpoint_entries(str(run_dir))}
    (run_dir / "train_manifest.json").write_text(json.dumps(manifest))
    assert [entry["num_timesteps"] for entry in manifest["checkpoints"]] == [12, 16]
    loaded = read_bundle(run_dir, "checkpoints/checkpoint_12_steps.zip")
    assert loaded.num_timesteps == 12 and loaded.selection == "checkpoint"
    with pytest.raises(Exception, match="not listed"):
        read_bundle(run_dir, "checkpoints/checkpoint_8_steps.zip")   # pruned


# 4. TabularQLearning -----------------------------------------------------------------

def test_discretize_bins_position_and_mean_sinr():
    agent = TabularQLearning()
    # x 15 -> bin 1; y -245 -> bin 0; sinrs (5, 15) mean 10 -> searchsorted left -> 2
    assert agent._discretize(np.array([15.0, -245.0, 5.0, 99.0, 15.0, 99.0])) == (1, 0, 2)


@pytest.mark.parametrize("obs, expected", [
    ([-50.0, -999.0], (0, 0, 1)),                 # below range clips to 0; no links -> 0 dB
    ([1000.0, 999.0], (49, 49, 1)),               # above range clips to the last bin
    ([500.0, 250.0], (49, 49, 1)),                # upper edge itself is the last bin
    ([0.0, 0.0, 100.0, 1.0], (0, 25, 5)),         # SINR above every edge
    ([0.0, 0.0, -100.0, 1.0], (0, 25, 0)),        # SINR below every edge
])
def test_discretize_clips_to_the_grid(obs, expected):
    assert TabularQLearning()._discretize(np.array(obs)) == expected


def test_custom_sinr_edges():
    agent = TabularQLearning(sinr_edges=[0.0])
    assert agent._discretize(np.array([0.0, 0.0, -1.0, 0.0]))[2] == 0
    assert agent._discretize(np.array([0.0, 0.0, 1.0, 0.0]))[2] == 1


def test_greedy_predict_takes_the_argmax_and_breaks_ties_low():
    agent = TabularQLearning(epsilon=0.0)
    obs = np.array([10.0, 10.0, 5.0, 1.0])
    action, state = agent.predict(obs)
    assert (action, state) == (0, None)
    agent.q_table[agent._discretize(obs)][3] = 1.0
    assert agent.predict(obs)[0] == 3


def test_deterministic_predict_ignores_epsilon():
    agent = TabularQLearning(epsilon=1.0)
    obs = np.array([10.0, 10.0, 5.0, 1.0])
    agent.q_table[agent._discretize(obs)][2] = 1.0
    assert {agent.predict(obs, deterministic=True)[0] for _ in range(50)} == {2}


def test_exploration_stays_within_the_action_space():
    state = np.random.get_state()
    try:
        np.random.seed(0)
        agent = TabularQLearning(n_actions=3, epsilon=1.0)
        actions = {agent.predict(np.array([10.0, 10.0]))[0] for _ in range(200)}
    finally:
        np.random.set_state(state)
    assert actions == {0, 1, 2}


def test_update_applies_the_q_learning_rule():
    agent = TabularQLearning(lr=0.5, gamma=0.9)
    s0 = np.array([5.0, 5.0, 5.0, 0.0])
    s1 = np.array([25.0, 5.0, 5.0, 0.0])
    agent.update(s0, 1, 2.0, None)                 # terminal: Q = 0 + 0.5 * (2 - 0)
    assert agent.q_table[agent._discretize(s0)][1] == pytest.approx(1.0)
    agent.q_table[agent._discretize(s1)][:] = [0.0, 4.0, 1.0, 0.0, 0.0]
    agent.update(s0, 1, 1.0, s1)                   # 1 + 0.5 * (1 + 0.9 * 4 - 1)
    assert agent.q_table[agent._discretize(s0)][1] == pytest.approx(2.8)
    assert agent.visit_counts[agent._discretize(s0)].tolist() == [0, 2, 0, 0, 0]


def test_epsilon_decay_floors_at_the_minimum():
    agent = TabularQLearning(epsilon=0.1, epsilon_decay=0.5, epsilon_min=0.03)
    agent.decay_epsilon()
    assert agent.epsilon == pytest.approx(0.05)
    agent.decay_epsilon()
    assert agent.epsilon == pytest.approx(0.03)
    agent.decay_epsilon()
    assert agent.epsilon == pytest.approx(0.03)
