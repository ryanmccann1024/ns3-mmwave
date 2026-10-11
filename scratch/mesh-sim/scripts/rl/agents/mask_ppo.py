"""MaskablePPO trainer wrapper + its config for the mesh-sim RL agent."""

from dataclasses import dataclass
from typing import Callable
import math

from gymnasium import Env
from sb3_contrib.common.maskable.policies import MaskableActorCriticPolicy
from sb3_contrib.common.wrappers import ActionMasker
from sb3_contrib.ppo_mask import MaskablePPO


@dataclass
class MaskablePPOConfig:
    total_timesteps: int = 100_000   # budget for .learn(); mesh env is slow -> start low
    n_steps: int = 1024              # SB3 default 2048; smaller = more frequent updates
    gamma: float = 0.95              # SB3 default 0.99
    ent_coef: float = 0.01           # SB3 default 0.0; keeps exploring under masking
    learning_rate: float = 0.0003
    batch_size: int = 64
    gae_lambda: float = 0.95
    clip_range: float = 0.2
    n_epochs: int = 10
    target_kl: float | None = None
    net_arch: tuple[int, ...] = (64, 64)
    ent_coef_final: float | None = None
    seed: int = 42
    verbose: int = 1
    tensorboard_log: str | None = None


    def __post_init__(self):
        for name in ("total_timesteps", "n_steps", "batch_size", "n_epochs"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.n_steps < 2 or self.batch_size < 2:
            raise ValueError("n_steps and batch_size must be >= 2")
        for name in ("gamma", "gae_lambda", "clip_range"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 < value <= 1:
                raise ValueError(f"{name} must be in (0, 1]")
        if not math.isfinite(self.learning_rate) or self.learning_rate <= 0:
            raise ValueError("learning_rate must be positive and finite")
        for name in ("ent_coef", "ent_coef_final", "target_kl"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or value < 0 or (name == "target_kl" and value == 0)):
                raise ValueError(f"{name} has an invalid coefficient")
        if not self.net_arch or any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in self.net_arch):
            raise ValueError("net_arch must contain positive integer layer widths")


class MaskablePpoTrainer:
    """Wrap the SB3 MaskablePPO policy and its action-mask adapter."""

    def __init__(self, cfg: MaskablePPOConfig, env: Env, mask_fn: Callable):
        self.cfg = cfg
        self.env = ActionMasker(env, mask_fn)   # enable masking
        self.model = MaskablePPO(
            MaskableActorCriticPolicy,          # policy (positional)
            self.env,
            seed=cfg.seed,
            n_steps=cfg.n_steps,
            gamma=cfg.gamma,
            ent_coef=cfg.ent_coef,
            learning_rate=cfg.learning_rate,
            batch_size=cfg.batch_size,
            gae_lambda=cfg.gae_lambda,
            clip_range=cfg.clip_range,
            n_epochs=cfg.n_epochs,
            target_kl=cfg.target_kl,
            policy_kwargs={"net_arch": {"pi": list(cfg.net_arch), "vf": list(cfg.net_arch)}},
            verbose=cfg.verbose,
            tensorboard_log=cfg.tensorboard_log,
        )

    def train(self, callback=None):
        callbacks = list(callback or []) if isinstance(callback, (list, tuple)) else ([callback] if callback else [])
        if self.cfg.ent_coef_final is not None:
            from .callbacks import EntropyDecayCallback
            callbacks.insert(0, EntropyDecayCallback(self.cfg.ent_coef, self.cfg.ent_coef_final,
                                                     self.cfg.total_timesteps))
        self.model.learn(total_timesteps=self.cfg.total_timesteps, callback=callbacks or None)
        return self.model

    @staticmethod
    def load(path: str, env: Env, mask_fn: Callable) -> MaskablePPO:
        """Reload a saved policy onto a fresh masked env; CPU keeps replay deterministic."""
        return MaskablePPO.load(path, env=ActionMasker(env, mask_fn), device="cpu")

    def save(self, path: str) -> None:
        self.model.save(path)
