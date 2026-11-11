"""Opt-in checkpoint and validation scheduling after completed PPO optimization."""

from pathlib import Path
from stable_baselines3.common.callbacks import BaseCallback
from scripts.artifact_io import write_json

POST_UPDATE_CHECKPOINTS_NAME = "post_update_checkpoints.json"
POST_UPDATE_CHECKPOINTS_VERSION = 1
AFTER_UPDATE_TIMING = "after optimizer update"
CHECKPOINT_TIMINGS = ("standard", "after-update")


def validate_schedule(cfg, cadence, resume=None):
    """Reject an ambiguous schedule before opening any simulator environment."""
    if (
        resume is not None
        or cadence.eval_every <= 0
        or cadence.eval_every != cadence.checkpoint_every
        or cadence.eval_every % cfg.n_steps
        or cfg.total_timesteps % cadence.eval_every
    ):
        raise ValueError(
            "post-update validation requires fresh training, equal positive checkpoint/eval cadence aligned to rollouts, and an aligned total budget"
        )


class PostUpdateValidation(BaseCallback):
    """Drive existing callbacks after optimization, including the final update.

    SB3's per-step and rollout-end hooks precede optimization. The next rollout
    start (and training end for the last rollout) observes completed weights.
    The first optimized policy is also retained to avoid losing early winners.
    """

    def __init__(self, callbacks, out_dir, cadence):
        super().__init__()
        self.children = callbacks
        self.out_dir = Path(out_dir)
        self.cadence = cadence
        self.last_steps = 0
        self.last_updates = 0
        self.events = []

    def _init_callback(self):
        for child in self.children:
            child.init_callback(self.model)

    def _on_training_start(self):
        for child in self.children:
            child.on_training_start(self.locals, self.globals)

    def _on_step(self):
        return True

    def _validate(self):
        steps = int(self.model.num_timesteps)
        if steps <= self.last_steps or self.model._n_updates <= self.last_updates:
            return
        if self.events and steps % self.cadence:
            return
        for child in self.children:
            # Preserve the callbacks' public on_step bookkeeping and exact
            # checkpoint names while invoking them only at chosen boundaries.
            child.n_calls = steps - 1
            child.update_locals(self.locals)
            if not child.on_step():
                raise RuntimeError(
                    "post-update callback requested an unsupported early stop"
                )
        self.last_steps = steps
        self.last_updates = int(self.model._n_updates)
        self.events.append(
            {"steps": steps, "optimizer_updates": int(self.model._n_updates)}
        )
        write_json(
            self.out_dir / "post_update_validation.json",
            {
                "post_update_validation_version": 1,
                "timing": "after optimizer update",
                "first_update_retained": True,
                "events": self.events,
            },
        )

    def _on_rollout_start(self):
        self._validate()

    def _on_training_end(self):
        self._validate()
        for child in self.children:
            child.on_training_end()


def validate_after_update_schedule(
    cfg, cadence, restored_steps=0, decisions_per_episode=None
):
    """Reject an after-update checkpoint budget that cannot land on its milestones.

    Milestones are cumulative multiples of the checkpoint cadence observed at
    rollout boundaries, so the cadence, the restored count and the terminal
    budget must align with rollouts and, once known, with complete episodes.
    Nothing is extended to fit. ``decisions_per_episode`` None defers the
    episode check until the native contract is known.
    """
    every = cadence.checkpoint_every
    if cadence.eval_every:
        raise ValueError(
            "after-update checkpoints run without in-training validation; "
            "set eval_every_steps to 0"
        )
    if every <= 0:
        raise ValueError(
            "after-update checkpoints require a positive checkpoint cadence"
        )
    if every % cfg.n_steps or restored_steps % cfg.n_steps:
        raise ValueError(
            f"checkpoint cadence {every} and restored steps {restored_steps} "
            f"must be multiples of n_steps {cfg.n_steps}"
        )
    if cfg.total_timesteps % every or cfg.total_timesteps <= restored_steps:
        raise ValueError(
            f"total_timesteps {cfg.total_timesteps} must be a multiple of the "
            f"checkpoint cadence {every} beyond the restored {restored_steps}"
        )
    if decisions_per_episode is not None and (
        every % decisions_per_episode or restored_steps % decisions_per_episode
    ):
        raise ValueError(
            f"checkpoint cadence {every} and restored steps {restored_steps} "
            f"must be whole episodes of {decisions_per_episode} decisions"
        )


class PostUpdateCheckpoints(BaseCallback):
    """Save retained checkpoints only after an optimizer update, without validation.

    At rollout start and training end, observe the optimization completed
    before the hook. Initial parent weights are not a new update. Milestones
    use cumulative decisions, so continuation and fresh curves share an x-axis.
    Writes ``post_update_checkpoints.json`` (version 1) in the legacy format.
    """

    def __init__(self, artifacts, every, keep, decisions_per_episode):
        super().__init__()
        if every <= 0 or keep < 1 or decisions_per_episode < 1:
            raise ValueError(
                "post-update checkpoints need positive cadence, retention and episode length"
            )
        self.artifacts, self.every, self.keep = artifacts, every, keep
        self.decisions_per_episode = decisions_per_episode
        self.events = []

    def _on_training_start(self):
        self.start_steps = self.last_steps = int(self.model.num_timesteps)
        self.last_updates = int(self.model._n_updates)

    def _on_step(self):
        return True

    def _capture(self):
        steps, updates = int(self.model.num_timesteps), int(self.model._n_updates)
        if (
            steps <= self.last_steps
            or updates <= self.last_updates
            or steps % self.every
        ):
            return
        directory = self.artifacts.out_dir / "checkpoints"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"checkpoint_{steps}_steps.zip"
        temporary = directory / f"checkpoint_{steps}_steps.tmp.zip"
        self.model.save(str(temporary))
        temporary.replace(target)
        self.artifacts.record_checkpoint(target, steps, self.keep)
        episodes = steps // self.decisions_per_episode
        self.events.append(
            dict(
                steps=steps,
                total_episodes=episodes,
                optimizer_epoch_counter=updates,
                timing=AFTER_UPDATE_TIMING,
            )
        )
        self.last_steps, self.last_updates = steps, updates
        write_json(
            self.artifacts.out_dir / POST_UPDATE_CHECKPOINTS_NAME,
            dict(
                post_update_checkpoints_version=POST_UPDATE_CHECKPOINTS_VERSION,
                restored_steps=self.start_steps,
                validation_during_training=False,
                events=self.events,
            ),
        )
        print(
            f"Optimized checkpoint: {episodes} total episodes; {steps} decisions; "
            f"optimizer epoch counter {updates}",
            flush=True,
        )

    def _on_rollout_start(self):
        self._capture()

    def _on_training_end(self):
        self._capture()
