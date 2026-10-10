"""PPO and callback settings, validated before a plan or simulator is started."""

import math
from dataclasses import dataclass


PPO_SEARCH_PARAMETERS = {"n_steps": ("int", "categorical"),
                         "gamma": ("float",), "ent_coef": ("float",)}


def validate_training_settings(settings: dict) -> None:
    """Validate supplied settings; omitted values use the dataclass defaults."""
    minima = {"total_timesteps": 1, "n_steps": 2, "checkpoint_every_steps": 0,
              "keep_checkpoints": 1, "eval_every_steps": 0, "eval_episodes": 1}
    for key, minimum in minima.items():
        if key not in settings:
            continue
        value = settings[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"{key} must be an integer >= {minimum}, got {value!r}")
    for key in ("gamma", "ent_coef"):
        if key not in settings:
            continue
        value = settings[key]
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0
                or (key == "gamma" and value > 1)):
            bounds = "between 0 and 1" if key == "gamma" else ">= 0"
            raise ValueError(f"{key} must be a finite number {bounds}, got {value!r}")


@dataclass
class MaskablePPOConfig:
    total_timesteps: int = 100_000   # budget for .learn(); mesh env is slow -> start low
    n_steps: int = 1024              # SB3 default 2048; smaller = more frequent updates
    gamma: float = 0.95              # SB3 default 0.99
    ent_coef: float = 0.01           # SB3 default 0.0; keeps exploring under masking
    seed: int = 42
    verbose: int = 1
    tensorboard_log: str | None = None

    def __post_init__(self):
        validate_training_settings({key: getattr(self, key) for key in
                                    ("total_timesteps", "n_steps", "gamma", "ent_coef")})


@dataclass
class Cadence:
    """Checkpoint/evaluation knobs; units are SB3 timesteps."""
    checkpoint_every: int = 0
    keep_checkpoints: int = 3
    eval_every: int = 0
    eval_episodes: int = 1
    eval_seed: int = 0

    def __post_init__(self):
        validate_training_settings({"checkpoint_every_steps": self.checkpoint_every,
                                    "keep_checkpoints": self.keep_checkpoints,
                                    "eval_every_steps": self.eval_every,
                                    "eval_episodes": self.eval_episodes})
