"""MaskablePPO trainer wrapper + its config for the mesh-sim RL agent."""

from typing import Callable
import math

from gymnasium import Env
from sb3_contrib.common.maskable.policies import MaskableActorCriticPolicy
from sb3_contrib.common.wrappers import ActionMasker
from sb3_contrib.ppo_mask import MaskablePPO

from scripts.rl.agents.config import MaskablePPOConfig as MaskablePPOConfig




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

    @classmethod
    def resume(cls, cfg, env, mask_fn, bundle):
        """Restore SB3 policy/optimizer state onto a fresh masked simulator episode."""
        trainer = cls.__new__(cls)
        trainer.cfg = cfg
        trainer.env = ActionMasker(env, mask_fn)
        trainer.model = MaskablePPO.load(str(bundle.model_path), env=trainer.env, device="cpu")
        if trainer.model.num_timesteps != bundle.num_timesteps:
            raise ValueError("checkpoint timestep count differs from its manifest entry")
        for key in ("n_steps", "gamma", "ent_coef", "seed"):
            if getattr(trainer.model, key) != getattr(cfg, key):
                raise ValueError(f"checkpoint {key} differs from the recorded training configuration")
        trainer.model.verbose = cfg.verbose
        trainer.model.tensorboard_log = cfg.tensorboard_log
        return trainer

    def train(self, callback=None, continuing=False):
        remaining = (self.cfg.total_timesteps - self.model.num_timesteps
                     if continuing else self.cfg.total_timesteps)
        callbacks = list(callback or []) if isinstance(callback, (list, tuple)) else ([callback] if callback else [])
        if self.cfg.ent_coef_final is not None:
            from .callbacks import EntropyDecayCallback
            callbacks.insert(0, EntropyDecayCallback(self.cfg.ent_coef, self.cfg.ent_coef_final, remaining))
        self.model.learn(total_timesteps=remaining, callback=callbacks or None,
                         reset_num_timesteps=not continuing)
        return self.model

    @staticmethod
    def load(path: str, env: Env, mask_fn: Callable) -> MaskablePPO:
        """Reload a saved policy onto a fresh masked CPU environment."""
        return MaskablePPO.load(path, env=ActionMasker(env, mask_fn), device="cpu")

    def save(self, path: str) -> None:
        """Save the model zip to path."""
        self.model.save(path)
