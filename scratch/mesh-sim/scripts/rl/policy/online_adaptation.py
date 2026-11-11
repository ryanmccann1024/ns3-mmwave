"""Gated single-episode PPO adaptation (protocol ``online_gated_v1``).

Manual ``MaskableRolloutBuffer`` + ``model.train()`` updates over eligible
windows only; no auto-reset and no update from a forced deployment prefix.
This is a separate protocol from the SB3 ``learn()`` protocol
(``online_sb3_v1`` in ``operation.py``); the two are never merged.

Accounting rules preserved from the original writer:

- a window is eligible when it has scored ticks; recovery/jamming also need an
  active deployment gate whose eligible ticks equal the scored ticks;
- an ineligible window raises only while an unflushed eligible buffer exists;
- the final partial rollout is flushed, except a singleton, which is skipped
  and counted as an untrained tail decision;
- ``target_kl`` must be ``None``;
- ``weight_updates.json`` is rewritten after every update and ``verify()``
  requires balanced transition accounting and a real actor change.
"""

import math
from pathlib import Path

import numpy as np
import torch
from sb3_contrib.common.maskable.buffers import MaskableRolloutBuffer
from stable_baselines3.common.logger import configure

from scripts.artifact_io import write_json
from scripts.rl.policy import bundle as _bundle
from scripts.rl.policy.evaluate import ModelPolicy

GATED_PROTOCOL = "online_gated_v1"
INHERITED_PPO_KEYS = (
    "learning_rate",
    "gamma",
    "gae_lambda",
    "n_epochs",
    "ent_coef",
    "clip_range",
    "target_kl",
)
_ACTOR = ("mlp_extractor.policy_net", "action_net")
_CRITIC = ("mlp_extractor.value_net", "value_net")


def eligible(mission, facts):
    window = facts["window"]
    if not window["scored_ticks"]:
        return False
    if mission not in ("recovery", "jamming"):
        return True
    gate = facts["deployment"]
    return bool(gate["active"] and gate["eligible_ticks"] == window["scored_ticks"])


def batch_for(size, requested):
    """Avoid one-sample minibatches; never pad or duplicate a transition."""
    if size < 2:
        raise ValueError("PPO update needs at least two transitions")
    candidates = [n for n in range(2, min(size, requested) + 1) if size % n == 0]
    return max(candidates) if candidates else size


def gated_settings(hyperparameters, n_steps, batch_size):
    """Inherited PPO settings plus explicit rollout/minibatch overrides; no defaults."""
    missing = [key for key in INHERITED_PPO_KEYS if key not in hyperparameters]
    if missing:
        raise ValueError(
            f"parent training records no {missing}; gated settings cannot be inherited"
        )
    settings = {key: hyperparameters[key] for key in INHERITED_PPO_KEYS}
    settings.update(
        n_steps=n_steps,
        batch_size=batch_size,
        eligible_only=True,
        flush_final_partial=True,
    )
    for key in ("n_steps", "batch_size"):
        value = settings[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 2:
            raise ValueError(
                f"gated {key} must be an explicit integer >= 2, got {value!r}"
            )
    if settings["target_kl"] is not None:
        raise ValueError(
            "online_gated_v1 requires target_kl = null (no target-KL early stop)"
        )
    from scripts.rl.agents.config import validate_training_settings

    validate_training_settings(
        {
            k: v
            for k, v in settings.items()
            if k not in ("eligible_only", "flush_final_partial")
        }
    )
    return settings


def verify_inherited_settings(model, settings):
    """Refuse a loaded policy whose PPO settings differ from its gated manifest."""
    for key in INHERITED_PPO_KEYS:
        actual = getattr(model, key)
        if key == "clip_range" and callable(actual):
            actual = actual(1.0)
        if actual != settings[key]:
            raise ValueError(
                f"loaded model {key} differs from inherited gated settings"
            )


def _change_from(initial, model):
    return {
        scope + "_change_l2_from_start": sum(
            float(((value.detach().cpu() - initial[key]) ** 2).sum())
            for key, value in model.policy.state_dict().items()
            if key.startswith(prefixes)
        )
        ** 0.5
        for scope, prefixes in (("actor", _ACTOR), ("critic", _CRITIC))
    }


class OnlinePolicy(ModelPolicy):
    def __init__(self, model, mission, settings, output):
        super().__init__(model, deterministic=False)
        self.mission, self.settings, self.output = mission, settings, Path(output)
        self.buffer = []
        self.events = []
        self.excluded = self.collected = self.trained = 0
        self.decisions = self.skipped_tail = self.optimizer_steps = 0
        self.initial_digest = _bundle.parameter_digest(model)
        self.initial = {
            k: v.detach().cpu().clone() for k, v in model.policy.state_dict().items()
        }
        self.start_steps = int(model.num_timesteps)
        self.model = model
        model.set_logger(configure(str(self.output / "ppo"), ["csv"]))
        model.n_steps = settings["n_steps"]
        model.batch_size = settings["batch_size"]
        model._current_progress_remaining = 1.0
        if model.target_kl is not None:
            raise ValueError("gated online protocol expects no target-KL early stop")
        self._hook = model.policy.optimizer.register_step_post_hook(
            self._optimizer_step
        )
        self._write()

    def _optimizer_step(self, *args, **kwargs):
        self.optimizer_steps += 1

    def act(self, obs, mask, contract):
        self.model.policy.set_training_mode(False)
        tensor, _ = self.model.policy.obs_to_tensor(obs)
        with torch.no_grad():
            actions, values, log_prob = self.model.policy(
                tensor, action_masks=np.asarray(mask, dtype=bool)
            )
        action = actions.cpu().numpy().reshape(-1)
        self.pending = (
            np.asarray(obs).copy(),
            action.copy(),
            values.detach(),
            log_prob.detach(),
            np.asarray(mask, dtype=bool).copy(),
        )
        return action

    def observe(self, next_obs, reward, terminated, truncated, info, facts):
        self.decisions += 1
        self.model.num_timesteps = self.start_steps + self.decisions
        if eligible(self.mission, facts):
            self.buffer.append((*self.pending, float(reward), self.collected == 0))
            self.collected += 1
        else:
            self.excluded += 1
            if self.buffer:
                raise RuntimeError(
                    "ineligible gap after adaptation started; cannot join disjoint transitions"
                )
        done = bool(terminated or truncated)
        if len(self.buffer) >= self.settings["n_steps"] or done:
            self._update(next_obs, done, info)
        if done:
            self._hook.remove()
            self._write()

    def _update(self, next_obs, done, info):
        size = len(self.buffer)
        if size == 0:
            return
        if size == 1:
            if not done:
                raise RuntimeError("unexpected singleton rollout")
            self.skipped_tail = 1
            self.buffer.clear()
            return
        model = self.model
        rollout = MaskableRolloutBuffer(
            size,
            model.observation_space,
            model.action_space,
            device=model.device,
            gamma=model.gamma,
            gae_lambda=model.gae_lambda,
            n_envs=1,
        )
        for obs, action, value, log_prob, mask, reward, start in self.buffer:
            rollout.add(
                obs.reshape((1, *obs.shape)),
                action.reshape((1, -1)),
                np.asarray([reward]),
                np.asarray([start]),
                value,
                log_prob,
                action_masks=mask,
            )
        with torch.no_grad():
            tensor, _ = model.policy.obs_to_tensor(next_obs)
            last_values = model.policy.predict_values(tensor)
        rollout.compute_returns_and_advantage(last_values, np.asarray([done]))
        model.rollout_buffer = rollout
        model.batch_size = batch_for(size, self.settings["batch_size"])
        before_updates, before_steps = int(model._n_updates), self.optimizer_steps
        model.train()
        expected = model.n_epochs * (size // model.batch_size)
        if self.optimizer_steps - before_steps != expected:
            raise RuntimeError(
                "online optimizer step count disagrees with complete minibatches"
            )
        self.trained += size
        changes = _change_from(self.initial, model)
        event = dict(
            decision=self.decisions,
            time_s=info["time_s"],
            eligible_decisions=self.collected,
            rollout_decisions=size,
            terminal_update=done,
            affects_later_actions=not done,
            batch_size=model.batch_size,
            optimizer_epochs=int(model._n_updates) - before_updates,
            optimizer_steps=self.optimizer_steps - before_steps,
            optimizer_steps_total=self.optimizer_steps,
            parameter_sha256=_bundle.parameter_digest(model),
            **changes,
        )
        if not all(math.isfinite(v) for v in changes.values()):
            raise RuntimeError("nonfinite online parameters")
        self.events.append(event)
        model.logger.record("time/episode_decisions", self.decisions)
        model.logger.record("time/eligible_decisions", self.collected)
        model.logger.dump(step=model.num_timesteps)
        self.buffer.clear()
        self._write()

    def _write(self):
        write_json(
            self.output / "weight_updates.json",
            dict(
                initial_parameter_sha256=self.initial_digest,
                updates=self.events,
                episode_decisions=self.decisions,
                eligible_decisions=self.collected,
                excluded_prefix_decisions=self.excluded,
                trained_decisions=self.trained,
                untrained_tail_decisions=self.skipped_tail,
                optimizer_steps=self.optimizer_steps,
            ),
        )

    def verify(self):
        if self.trained + self.skipped_tail != self.collected or self.buffer:
            raise RuntimeError("adaptation transition accounting does not balance")
        if (
            not self.events
            or not self.optimizer_steps
            or _bundle.parameter_digest(self.model) == self.initial_digest
        ):
            raise RuntimeError("online mode performed no verified neural update")
        if self.events[-1]["actor_change_l2_from_start"] <= 0:
            raise RuntimeError("online actor weights did not change")
        return dict(
            update_cycles=len(self.events),
            optimizer_steps=self.optimizer_steps,
            eligible_decisions=self.collected,
            trained_decisions=self.trained,
            excluded_prefix_decisions=self.excluded,
            untrained_tail_decisions=self.skipped_tail,
            initial_parameter_sha256=self.initial_digest,
            final_parameter_sha256=_bundle.parameter_digest(self.model),
        )
