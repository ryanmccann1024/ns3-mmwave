"""Training callbacks: bounded checkpoint retention and mask-aware evaluation."""

from pathlib import Path

from gymnasium import Wrapper

from sb3_contrib.common.maskable.callbacks import MaskableEvalCallback
from stable_baselines3.common.callbacks import BaseCallback, CheckpointCallback
from stable_baselines3.common.monitor import Monitor

CHECKPOINT_DIR = "checkpoints"
CHECKPOINT_PREFIX = "checkpoint"


def list_checkpoints(directory, name_prefix: str = CHECKPOINT_PREFIX
                     ) -> list[tuple[int, Path]]:
    """Saved checkpoints as (num_timesteps, path), ascending; unparsable names ignored."""
    found = []
    for path in Path(directory).glob(f"{name_prefix}_*_steps.zip"):
        steps = path.name[len(name_prefix) + 1:-len("_steps.zip")]
        if steps.isdigit():
            found.append((int(steps), path))
    return sorted(found)


class BoundedCheckpointCallback(CheckpointCallback):
    """CheckpointCallback that keeps only the newest keep_last checkpoint files."""

    def __init__(self, *args, keep_last: int = 3, **kwargs):
        super().__init__(*args, **kwargs)
        if int(keep_last) < 1:
            raise ValueError(f"keep_last must be >= 1, got {keep_last!r}")
        self.keep_last = int(keep_last)

    def _on_step(self) -> bool:
        result = super()._on_step()
        retained = list_checkpoints(self.save_path, self.name_prefix)
        for _, path in retained[:-self.keep_last]:
            path.unlink(missing_ok=True)
        return result


class ValidationSeeds(Wrapper):
    """Cycle a fixed validation set, restarting it at each checkpoint evaluation."""

    def __init__(self, env, seeds):
        super().__init__(env)
        self.seeds = tuple(seeds)
        if not self.seeds or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("validation seeds must be nonempty and distinct")
        self.cursor = 0

    def begin_evaluation(self):
        self.cursor = 0

    def reset(self, *, seed=None, options=None):
        seed = self.seeds[self.cursor % len(self.seeds)]
        self.cursor += 1
        return self.env.reset(seed=seed, options={**(options or {}), "seed_source": "eval"})

    def action_masks(self):
        return self.unwrapped.action_masks()


class SeededEvalCallback(MaskableEvalCallback):
    """Ensure every checkpoint uses the same validation seeds, including auto-resets."""

    def __init__(self, seed_env, matrix_root, **kwargs):
        self.matrix_root = Path(matrix_root)
        self.seed_env = seed_env
        super().__init__(Monitor(seed_env), **kwargs)

    def _on_step(self):
        if self.eval_freq > 0 and self.n_calls % self.eval_freq == 0:
            self.seed_env.begin_evaluation()
        result = super()._on_step()
        if self.eval_freq > 0 and self.n_calls % self.eval_freq == 0:
            import json
            from types import SimpleNamespace
            from scripts.rl.policy.reward_matrix import write_reward_matrix
            completed = []
            for path in self.matrix_root.glob("episode-*/rl_episode.json"):
                episode = json.loads(path.read_text())
                if episode["status"] == "completed":
                    completed.append((episode["episode"], SimpleNamespace(
                        status="completed", seed=episode["seed"],
                        decisions=episode["steps"], episode_dir=str(path.parent))))
            completed.sort(key=lambda item: item[0])
            batch = [item[1] for item in completed[-self.n_eval_episodes:]]
            write_reward_matrix(batch, self.matrix_root/f"checkpoint-{self.num_timesteps}")
        return result


def build_callbacks(out_dir: str, checkpoint_every: int, keep_last: int,
                    eval_env, eval_every: int, eval_episodes: int, verbose: int,
                    eval_seeds: tuple[int, ...] = ()
                    ) -> tuple[list[BaseCallback], MaskableEvalCallback | None]:
    """Wire the cadence options; all units are SB3 timesteps (one env, one decision each)."""
    callbacks: list[BaseCallback] = []
    if checkpoint_every > 0:
        callbacks.append(BoundedCheckpointCallback(
            save_freq=checkpoint_every,
            save_path=str(Path(out_dir) / CHECKPOINT_DIR),
            name_prefix=CHECKPOINT_PREFIX,
            keep_last=keep_last,
            verbose=verbose,
        ))

    eval_callback = None
    if eval_every > 0 and eval_env is not None:
        seeds = eval_seeds or tuple(eval_env.seed_value + i for i in range(eval_episodes))
        if len(seeds) != eval_episodes:
            raise ValueError("validation seed count must match eval_episodes")
        eval_callback = SeededEvalCallback(
            ValidationSeeds(eval_env, seeds), matrix_root=Path(out_dir)/"eval",
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
        callbacks.append(eval_callback)
    return callbacks, eval_callback


class EntropyDecayCallback(BaseCallback):
    """Linearly reduce exploration pressure at each PPO rollout update."""

    def __init__(self, initial, final, budget):
        super().__init__()
        self.initial, self.final, self.budget = initial, final, budget

    def _on_training_start(self):
        self.start = self.model.num_timesteps

    def _on_rollout_start(self):
        progress = min(1.0, (self.model.num_timesteps-self.start)/self.budget)
        self.model.ent_coef = self.initial + progress*(self.final-self.initial)
        self.logger.record("train/entropy_coefficient", self.model.ent_coef)

    def _on_step(self):
        return True

    def _on_training_end(self):
        self.model.ent_coef = self.final
