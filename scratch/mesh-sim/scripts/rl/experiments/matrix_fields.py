"""Common fields and paths in the v1 and v2 matrix formats."""

import math
import re
from pathlib import Path

from scripts.rl.experiments.scenario_timing import (
    native_decisions as native_decisions,
)
from scripts.sim_support import parse_seed_spec

SEED_ROLES = ("training", "model_selection", "diagnostic", "held_out")


OPERATION_SEED_ROLES = ("model_selection", "diagnostic", "held_out")


_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


_EXPLICIT = "rows are explicit; no product expansion"


_BANDS = ("mmwave", "sub-6")


def _check_keys(mapping, allowed: tuple[str, ...], where: str) -> None:
    if not isinstance(mapping, dict):
        raise ValueError(f"{where} must be a JSON object")
    unknown = sorted(key for key in mapping if key not in allowed)
    if unknown:
        raise ValueError(
            f"{where} has unknown keys {unknown}; " f"valid keys: {list(allowed)}"
        )


def _scalar(value, where: str):
    if isinstance(value, list):
        raise ValueError(f"{where} must be a single value: {_EXPLICIT}")
    return value


def _name(value, where: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.match(value):
        raise ValueError(f"{where} must match [a-z0-9][a-z0-9-]*, got {value!r}")
    return value


def _int(value, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{where} must be an integer, got {value!r}")
    return value


def _seed_list(value, where: str) -> list[int]:
    if isinstance(value, str):
        return parse_seed_spec(value)
    if not isinstance(value, list):
        raise ValueError(f"{where} must be a seed spec string or an array of integers")
    seeds = [_int(seed, where) for seed in value]
    if len(set(seeds)) != len(seeds):
        raise ValueError(f"{where} must be distinct, got {seeds}")
    return seeds


def _string_array(value, where: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{where} must be a non-empty JSON array")
    if not all(isinstance(entry, str) for entry in value):
        raise ValueError(f"{where} must contain strings")
    return list(value)


def _weight_array(value, where: str) -> list[float]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{where} must be a non-empty JSON array")
    if any(isinstance(w, bool) or not isinstance(w, (int, float)) for w in value):
        raise ValueError(f"{where} must contain numbers")
    return [float(w) for w in value]


def _band(value, where: str) -> str | None:
    value = _scalar(value, where)
    if value is None:
        return None
    if value not in _BANDS:
        raise ValueError(f"{where} must be one of {list(_BANDS)}, got {value!r}")
    return value


def _positive_int(value, where: str, minimum: int = 1) -> int:
    value = _int(value, where)
    if value < minimum:
        raise ValueError(f"{where} must be an integer >= {minimum}, got {value}")
    return value


def _number(value, where: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{where} must be a finite number, got {value!r}")
    return float(value)


def _bool(value, where: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{where} must be a boolean, got {value!r}")
    return value


def _distinct_names(values, where: str) -> list[str]:
    if not isinstance(values, list):
        raise ValueError(f"{where} must be a JSON array")
    names = [_name(value, where) for value in values]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise ValueError(f"{where} must be distinct, repeated: {repeated}")
    return names


def _input_path(raw, base: Path, where: str, kind: str = "file") -> dict:
    """Resolve an input reference against the matrix directory; keep the original text."""
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{where} must be a nonempty path")
    path = Path(raw).expanduser()
    path = (path if path.is_absolute() else base / path).resolve()
    exists = path.is_file() if kind == "file" else path.is_dir()
    if not exists:
        raise ValueError(f"{where}: {kind} not found: {path} (from {raw!r})")
    return {"path": str(path), "reference": raw}


def _output_path(raw, base: Path, where: str) -> dict:
    """An output location must not climb out of the matrix tree through '..'."""
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{where} must be a nonempty path")
    path = Path(raw).expanduser()
    if not path.is_absolute() and ".." in path.parts:
        raise ValueError(
            f"{where}: unsafe relative output path {raw!r}; "
            "use an absolute path or one inside the matrix directory"
        )
    return {
        "path": str((path if path.is_absolute() else base / path).resolve()),
        "reference": raw,
    }


def _check_disjoint(roles: dict[str, set]) -> None:
    names = sorted(roles)
    for first, second in ((a, b) for i, a in enumerate(names) for b in names[i + 1 :]):
        shared = sorted(roles[first] & roles[second])
        if shared:
            raise ValueError(
                f"{first} and {second} share seeds {shared}; "
                "seed roles must be disjoint"
            )
