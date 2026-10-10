"""Training callbacks: bounded checkpoint retention and mask-aware evaluation."""

from dataclasses import dataclass
from pathlib import Path

from sb3_contrib.common.maskable.callbacks import MaskableEvalCallback
from stable_baselines3.common.callbacks import BaseCallback, CheckpointCallback
from stable_baselines3.common.monitor import Monitor

from scripts.rl.policy.training_artifacts import (CHECKPOINT_DIR, CHECKPOINT_PREFIX,
                                                  list_checkpoints)


@dataclass
class Cadence:
    """Checkpoint/evaluation knobs; units are SB3 timesteps."""
    checkpoint_every: int = 0
    keep_checkpoints: int = 3
    eval_every: int = 0
    eval_episodes: int = 1
    eval_seed: int = 0


class BoundedCheckpointCallback(CheckpointCallback):
    """CheckpointCallback that keeps only the newest keep_last checkpoint files."""

    def __init__(self, *args, keep_last: int = 3, artifacts=None, restored_steps=0, **kwargs):
        super().__init__(*args, **kwargs)
        if int(keep_last) < 1:
            raise ValueError(f"keep_last must be >= 1, got {keep_last!r}")
        self.keep_last = int(keep_last)
        self.artifacts = artifacts
        self.n_calls = restored_steps

    def _checkpoint_path(self, checkpoint_type="", extension=""):
        path = Path(super()._checkpoint_path(checkpoint_type, extension))
        return str(path.with_name(path.stem + ".tmp" + path.suffix))

    def _on_step(self) -> bool:
        result = super()._on_step()
        if self.n_calls % self.save_freq != 0:
            return result
        temporary = Path(self._checkpoint_path(extension="zip"))
        path = temporary.with_name(temporary.name.replace(".tmp.zip", ".zip"))
        temporary.replace(path)
        if self.artifacts is not None:
            self.artifacts.record_checkpoint(path, self.num_timesteps, self.keep_last)
        else:
            for _, discarded in list_checkpoints(self.save_path, self.name_prefix)[:-self.keep_last]:
                discarded.unlink(missing_ok=True)
        return result


def build_callbacks(out_dir: str, checkpoint_every: int, keep_last: int,
                    eval_env, eval_every: int, eval_episodes: int, verbose: int,
                    artifacts=None, restored_steps=0
                    ) -> tuple[list[BaseCallback], MaskableEvalCallback | None]:
    """Wire the cadence options; all units are SB3 timesteps (one env, one decision each)."""
    callbacks: list[BaseCallback] = []
    if checkpoint_every > 0:
        callbacks.append(BoundedCheckpointCallback(
            save_freq=checkpoint_every,
            save_path=str(Path(out_dir) / CHECKPOINT_DIR),
            name_prefix=CHECKPOINT_PREFIX,
            keep_last=keep_last, artifacts=artifacts, restored_steps=restored_steps,
            verbose=verbose,
        ))

    eval_callback = None
    if eval_every > 0 and eval_env is not None:
        eval_callback = MaskableEvalCallback(
            Monitor(eval_env),
            n_eval_episodes=eval_episodes,
            eval_freq=eval_every,
            best_model_save_path=str(out_dir),
            log_path=str(out_dir),
            deterministic=True,
            render=False,
            warn=False,
            use_masking=True,
            verbose=verbose,
        )
        eval_callback.n_calls = restored_steps
        callbacks.insert(0, eval_callback)
    return callbacks, eval_callback
