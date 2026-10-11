"""Adapt supported trainers to a fixed-budget study and model-selection objective."""

import copy
import json
import math
from pathlib import Path

from scripts.rl.agents.config import PPO_SEARCH_PARAMETERS, validate_training_settings
from scripts.rl.cli_common import MANIFEST_NAME as TRAIN_MANIFEST_NAME
from scripts.rl.policy.experiment import build_plan

_SEED_FLAGS = ("--seed", "--eval-seed", "--eval-seeds")



def _seed_values(args: list[str]) -> set[str]:
    """Values that follow a seed-bearing flag; a sampled number is not a seed."""
    from scripts.sim_support import parse_seed_spec
    return {str(seed) for position, token in enumerate(args)
            if token in _SEED_FLAGS and position + 1 < len(args)
            for seed in parse_seed_spec(args[position + 1])}



def _ppo_trial(spec: dict, params: dict, trial_dir, sim_binary: str) -> dict:
    """Build one trial's training command through build_plan; no plan file is written."""
    if set(params) != set(spec["search_space"]):
        raise ValueError("sampled parameters do not match the configured search space")
    matrix = copy.deepcopy(spec["matrix"])
    matrix["training"].update(params)
    validate_training_settings(matrix["training"])
    matrix["seeds"]["training"] = [spec["training_seed"]]
    plan = build_plan(matrix, trial_dir, sim_binary, rows=[spec["row"]])
    step = next(step for step in plan["steps"] if step["kind"] == "train")
    forbidden = {str(seed) for seed in spec["matrix"]["seeds"]["held_out"]}
    if forbidden & _seed_values(step["args"]):
        raise ValueError("refusing a trial command that names a held-out seed")
    return {"module": step["module"], "args": step["args"],
            "train_dir": step["output_dir"], "training": matrix["training"]}


def _objective(train_dir) -> tuple[float | None, str | None]:
    manifest = Path(train_dir) / TRAIN_MANIFEST_NAME
    try:
        body = json.loads(manifest.read_text())
        if body.get("status") != "completed":
            return None, "training manifest is not completed"
        value = body.get("best_mean_reward")
    except (OSError, ValueError) as exc:
        return None, f"unreadable {manifest}: {type(exc).__name__}: {exc}"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, (f"best_mean_reward is {value!r}: no model-selection evaluation "
                      "produced a best model")
    if not math.isfinite(value):
        return None, f"best_mean_reward is {value!r}"
    return float(value), None


class MaskablePpoTrainer:
    """Trainer boundary for the implemented MaskablePPO constructor and command."""

    name = "maskable_ppo"
    display_name = "MaskablePPO"
    search_parameters = PPO_SEARCH_PARAMETERS
    objective_name = "best_mean_reward"
    direction = "maximize"

    def build_trial(self, spec, params, trial_dir, sim_binary):
        return _ppo_trial(spec, params, trial_dir, sim_binary)

    def objective(self, train_dir):
        return _objective(train_dir)

    def validate_bounds(self, key, entry, where):
        low, high = entry["low"], entry["high"]
        if key == "gamma" and not (0 < low and high <= 1):
            raise ValueError(f"{where} must stay inside (0, 1], got low={low}, high={high}")

    def validate_value(self, key, value):
        validate_training_settings({key: value})



_TRAINERS = {MaskablePpoTrainer.name: MaskablePpoTrainer}


def get_trainer(name):
    """Refuse unsupported trainers before a study or training process is created."""
    if not isinstance(name, str) or name not in _TRAINERS:
        raise ValueError(f"unsupported trainer {name!r}; supported: {', '.join(_TRAINERS)}")
    return _TRAINERS[name]()



def build_trial(spec, params, trial_dir, sim_binary):
    return get_trainer(spec["trainer"]).build_trial(spec, params, trial_dir, sim_binary)
