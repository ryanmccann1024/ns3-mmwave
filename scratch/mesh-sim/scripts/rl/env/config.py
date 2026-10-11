"""Read scenario seed and provenance using the simulator's INI conventions."""

import configparser
import hashlib
from pathlib import Path

from scripts.sim_support import strip_inline_comment

_SELECTION_KEYS = ("observation_preset", "reward_components", "reward_weights",
                   "telemetry", "telemetry_every", "observation_parameters", "reward_parameters")

# Matches the C++ loader's scenario.nodes_file default.
_DEFAULT_NODES_FILE = "nodes.json"

# Matches the C++ loader's rl.action_profile default.
_DEFAULT_ACTION_PROFILE = "move_2d"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_ini(run_config: str) -> configparser.ConfigParser:
    ini = configparser.ConfigParser(interpolation=None)
    ini.read(run_config)
    return ini


def read_scenario_seed(run_config: str) -> int | None:
    """Return [scenario] seed, or None when missing or invalid."""
    ini = _read_ini(run_config)
    if ini.has_option("scenario", "seed"):
        try:
            return int(strip_inline_comment(ini.get("scenario", "seed")))
        except ValueError:
            pass
    return None


def read_explicit_rl_bounds(run_config: str) -> dict[str, float]:
    """Read explicit bounds; simulator defaults are resolved only by a live launch."""
    ini = _read_ini(run_config)
    return {f"{axis}_{end}": float(strip_inline_comment(ini.get("rl", f"{axis}_{end}")))
            for axis in "xyz" for end in ("min", "max")
            if ini.has_option("rl", f"{axis}_{end}")}


def _scenario_file(ini: configparser.ConfigParser, ini_path: Path, key: str,
                   label: str, default: str = "") -> Path | None:
    """Resolve a [scenario] file relative to the run.ini; blank or absent means none."""
    raw = strip_inline_comment(ini.get("scenario", key, fallback="")) or default
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = ini_path.parent / path
    if not path.is_file():
        raise FileNotFoundError(
            f"{label} not found: {path} "
            f"(scenario.{key} = '{raw}' in {ini_path})"
        )
    return path


def read_scenario_identity(run_config: str) -> dict:
    """Absolute run.ini path plus SHA-256 of the run.ini and its scenario input files."""
    ini_path = Path(run_config).resolve()
    if not ini_path.is_file():
        raise FileNotFoundError(f"run config not found: {run_config}")

    ini = _read_ini(str(ini_path))
    nodes_path = _scenario_file(ini, ini_path, "nodes_file", "nodes file",
                                _DEFAULT_NODES_FILE)
    buildings_path = _scenario_file(ini, ini_path, "buildings_file", "buildings file")
    jammers_path = _scenario_file(ini, ini_path, "jammers_file", "jammers file")

    return {
        "run_config": str(ini_path),
        "run_ini_sha256": _sha256(ini_path),
        "nodes_json_sha256": _sha256(nodes_path),
        "buildings_json_sha256": (_sha256(buildings_path)
                                  if buildings_path is not None else None),
        "jammers_json_sha256": (_sha256(jammers_path)
                                if jammers_path is not None else None),
    }


def read_rl_selection(run_config: str) -> dict[str, str]:
    """Read [rl] policy options, omitting blank or absent keys."""
    ini = _read_ini(run_config)
    raw = {}
    for key in _SELECTION_KEYS:
        if not ini.has_option("rl", key):
            continue
        value = strip_inline_comment(ini.get("rl", key))
        if value:
            raw[key] = value
    return raw


def read_action_profile(run_config: str) -> str:
    """Return [rl] action_profile, or the C++ loader's default when absent."""
    ini = _read_ini(run_config)
    raw = strip_inline_comment(ini.get("rl", "action_profile",
                                       fallback=_DEFAULT_ACTION_PROFILE))
    return raw or _DEFAULT_ACTION_PROFILE


def read_manifest_every_decisions(run_config: str) -> int:
    """Read the Python episode-progress cadence; final manifests are always saved."""
    ini = _read_ini(run_config)
    raw = strip_inline_comment(ini.get("rl", "manifest_every_decisions", fallback="1"))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("[rl] manifest_every_decisions must be a positive integer") from exc
    if value < 1:
        raise ValueError("[rl] manifest_every_decisions must be a positive integer")
    return value


def read_episode_output(run_config: str) -> dict:
    ini = _read_ini(run_config)
    return {"compact_training": ini.getboolean("rl", "compact_training", fallback=False)}


def read_jammer_onsets(run_config: str) -> tuple[tuple[float, ...], tuple[float, ...]]:
    ini = _read_ini(run_config)
    duration = ini.getfloat("scenario", "duration_s", fallback=0.0)
    result = []
    for name in ("training_jammer_onsets_s", "evaluation_jammer_onsets_s"):
        raw = strip_inline_comment(ini.get("rl", name, fallback=""))
        values = tuple(float(v.strip()) for v in raw.split(",") if v.strip())
        if any(not 0 <= v < duration for v in values):
            raise ValueError(f"[rl] {name} must contain finite times in [0,duration_s)")
        result.append(values)
    if any(result) and not strip_inline_comment(ini.get("scenario", "jammers_file", fallback="")):
        raise ValueError("jammer onset schedules require jammers_file")
    return tuple(result)
