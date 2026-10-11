"""Validate study configuration before creating outputs or launching training."""

import json
import math
from pathlib import Path

from scripts.artifact_io import sha256_file
from scripts.rl.policy.experiment import load_matrix
from scripts.rl.tuning.trainer import get_trainer
from scripts.sim_support import find_mesh_root

STUDY_VERSION = 1
N_STARTUP_TRIALS = 10
_TOP_KEYS = ("study_version", "name", "description", "matrix", "row",
             "training_seed", "sampler", "n_trials", "search_space", "trainer")
_SAMPLER_KEYS = ("type", "seed", "n_startup_trials", "n_ei_candidates", "multivariate")
_ENTRY_KEYS = {"categorical": ("type", "choices"),
               "int": ("type", "low", "high", "log"),
               "float": ("type", "low", "high", "log")}



def _check_keys(mapping, allowed: tuple[str, ...], where: str) -> None:
    if not isinstance(mapping, dict):
        raise ValueError(f"{where} must be a JSON object")
    unknown = sorted(key for key in mapping if key not in allowed)
    if unknown:
        raise ValueError(f"{where} has unknown keys {unknown}; "
                         f"valid keys: {list(allowed)}")


def _int(value, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{where} must be an integer, got {value!r}")
    return value


def _number(value, where: str):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} must be a number, got {value!r}")
    if not math.isfinite(value):
        raise ValueError(f"{where} must be finite, got {value!r}")
    return value


def _entry(key: str, raw, trainer) -> dict:
    where = f"search_space.{key}"
    if not isinstance(raw, dict):
        raise ValueError(f"{where} must be a JSON object")
    kind = raw.get("type")
    if kind not in trainer.search_parameters[key]:
        raise ValueError(f"{where}.type must be one of {list(trainer.search_parameters[key])}, "
                         f"got {kind!r}")
    _check_keys(raw, _ENTRY_KEYS[kind], where)
    if kind == "categorical":
        choices = raw.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError(f"{where}.choices must be a non-empty array")
        values = list(choices)
        if any(not isinstance(value, (str, int, float, type(None)))
               or (isinstance(value, float) and not math.isfinite(value)) for value in values):
            raise ValueError(f"{where}.choices must contain scalar values")
        if len(set(values)) != len(values):
            raise ValueError(f"{where}.choices must be distinct, got {values}")
        for value in values:
            trainer.validate_value(key, value)
        return {"type": kind, "choices": values}

    entry = {"type": kind, "low": _number(raw.get("low"), f"{where}.low"),
             "high": _number(raw.get("high"), f"{where}.high"),
             "log": raw.get("log", False)}
    if not isinstance(entry["log"], bool):
        raise ValueError(f"{where}.log must be true or false, got {entry['log']!r}")
    if not entry["low"] < entry["high"]:
        raise ValueError(f"{where} must have low < high, got low={entry['low']}, "
                         f"high={entry['high']}")
    if kind == "int":
        _int(entry["low"], f"{where}.low")
        _int(entry["high"], f"{where}.high")
    if entry["log"] and entry["low"] <= 0:
        raise ValueError(f"{where}.log requires low > 0")
    trainer.validate_bounds(key, entry, where)
    trainer.validate_value(key, entry["low"])
    trainer.validate_value(key, entry["high"])
    return entry


def _search_space(raw, trainer) -> dict:
    if not isinstance(raw, dict) or not raw:
        raise ValueError("search_space must be a non-empty JSON object")
    for key in raw:
        if key == "total_timesteps":
            raise ValueError("search_space.total_timesteps is not searchable: the "
                             "training budget is fixed per study and comes from the "
                             "matrix")
        if key not in trainer.search_parameters:
            raise ValueError(f"search_space.{key} is not wired to {trainer.display_name}; "
                             f"searchable knobs: {sorted(trainer.search_parameters)}; "
                             "see the open TODO-RL-TUNE-1")
    return {key: _entry(key, raw[key], trainer) for key in raw}


def _sampler(raw) -> dict:
    _check_keys(raw, _SAMPLER_KEYS, "sampler")
    if raw.get("type") != "tpe":
        raise ValueError(f"sampler.type must be 'tpe', got {raw.get('type')!r}")
    seed = _int(raw.get("seed"), "sampler.seed")
    if not 0 <= seed < 2**32:
        raise ValueError("sampler.seed must be between 0 and 2**32 - 1")
    startup = _int(raw.get("n_startup_trials", N_STARTUP_TRIALS), "sampler.n_startup_trials")
    candidates = _int(raw.get("n_ei_candidates", 24), "sampler.n_ei_candidates")
    multivariate = raw.get("multivariate", False)
    if startup < 1 or candidates < 1 or not isinstance(multivariate, bool):
        raise ValueError("sampler needs positive startup/candidate counts and boolean multivariate")
    return {"type": "tpe", "seed": seed, "n_startup_trials": startup,
            "n_ei_candidates": candidates, "multivariate": multivariate}


def _matrix(raw) -> dict:
    if not isinstance(raw, str) or not raw:
        raise ValueError("matrix must be a path to a matrix JSON file")
    path = Path(raw)
    if not path.is_absolute():
        path = find_mesh_root() / path
    matrix = load_matrix(path)
    training = matrix["training"]
    if matrix["seeds"]["model_selection"] is None:
        raise ValueError(f"{path}: the objective needs seeds.model_selection")
    budget = training.get("total_timesteps")
    if budget is None:
        raise ValueError(f"{path}: training.total_timesteps is required")
    cadence = training.get("eval_every_steps", 0)
    if not 0 < cadence <= budget:
        raise ValueError(f"{path}: training.eval_every_steps must satisfy "
                         f"0 < {cadence} <= total_timesteps {budget}, or no model "
                         "selection runs and every objective is null")
    return matrix


def load_study(path) -> dict:
    """Load and fully validate a study spec; nothing is launched or created."""
    study_path = Path(path).resolve()
    body = json.loads(study_path.read_text())
    _check_keys(body, _TOP_KEYS, "study")
    if body.get("study_version") != STUDY_VERSION:
        raise ValueError(f"study_version must be {STUDY_VERSION}, got "
                         f"{body.get('study_version')!r}")
    name = body.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"name must be a non-empty string, got {name!r}")
    description = body.get("description", "")
    if not isinstance(description, str):
        raise ValueError("description must be a string")

    matrix = _matrix(body.get("matrix"))
    row = body.get("row")
    known = [entry["name"] for entry in matrix["rows"]]
    if row not in known:
        raise ValueError(f"row {row!r} is not in {matrix['path']}; available: {known}")
    seed = _int(body.get("training_seed"), "training_seed")
    if seed not in matrix["seeds"]["training"]:
        raise ValueError(f"training_seed {seed} is not in seeds.training "
                         f"{matrix['seeds']['training']}")
    n_trials = _int(body.get("n_trials"), "n_trials")
    if n_trials < 1:
        raise ValueError(f"n_trials must be positive, got {n_trials}")
    trainer = get_trainer(body.get("trainer", "maskable_ppo"))

    return {"path": str(study_path), "sha256": sha256_file(study_path), "body": body,
            "name": name, "description": description, "matrix": matrix, "row": row,
            "training_seed": seed, "trainer": trainer.name, "sampler": _sampler(body.get("sampler", {})),
            "n_trials": n_trials,
            "search_space": _search_space(body.get("search_space"), trainer)}
