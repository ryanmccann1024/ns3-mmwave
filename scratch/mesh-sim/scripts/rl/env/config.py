"""Read scenario seed and provenance using the simulator's INI conventions."""

import hashlib
from pathlib import Path

from scripts.sim_support import parse_ini

_SELECTION_KEYS = ("observation_preset", "reward_components", "reward_weights",
                   "telemetry", "telemetry_every", "observation_parameters", "reward_parameters")

# Matches the C++ loader's scenario.nodes_file default.
_DEFAULT_NODES_FILE = "nodes.json"

# Matches the C++ loader's rl.action_profile default.
_DEFAULT_ACTION_PROFILE = "move_2d"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_ini(run_config: str) -> dict[str, dict[str, str]]:
    """Parse with the simulator's rules; an unreadable file reads as empty."""
    try:
        return parse_ini(run_config)
    except OSError:
        return {}


def _get(ini: dict, section: str, key: str, fallback: str | None = None) -> str | None:
    return ini.get(section, {}).get(key, fallback)


def read_scenario_seed(run_config: str) -> int | None:
    """Return [scenario] seed, or None when missing or invalid."""
    raw = _get(_read_ini(run_config), "scenario", "seed")
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            pass
    return None


def read_explicit_rl_bounds(run_config: str) -> dict[str, float]:
    """Read explicit bounds; simulator defaults are resolved only by a live launch."""
    ini = _read_ini(run_config)
    bounds = {}
    for axis in "xyz":
        for end in ("min", "max"):
            key = f"{axis}_{end}"
            raw = ini.get("rl", {}).get(key)
            if raw is not None:
                if "_" in raw:
                    raise ValueError(f"rl.{key} is not a plain number: {raw!r}")
                bounds[key] = float(raw)
    return bounds


def _scenario_file(ini: dict, ini_path: Path, key: str,
                   label: str, default: str = "") -> Path | None:
    """Resolve a [scenario] file relative to the run.ini; blank or absent means none."""
    raw = _get(ini, "scenario", key, "") or default
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
    rl = _read_ini(run_config).get("rl", {})
    return {key: rl[key] for key in _SELECTION_KEYS if rl.get(key)}


def read_action_profile(run_config: str) -> str:
    """Return [rl] action_profile, or the C++ loader's default when absent."""
    raw = _get(_read_ini(run_config), "rl", "action_profile", _DEFAULT_ACTION_PROFILE)
    return raw or _DEFAULT_ACTION_PROFILE


def read_manifest_every_decisions(run_config: str) -> int:
    """Read the Python episode-progress cadence; final manifests are always saved."""
    ini = _read_ini(run_config)
    raw = _get(ini, "rl", "manifest_every_decisions", "1")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("[rl] manifest_every_decisions must be a positive integer") from exc
    if value < 1:
        raise ValueError("[rl] manifest_every_decisions must be a positive integer")
    return value


def read_episode_output(run_config: str) -> dict:
    ini = _read_ini(run_config)
    raw = _get(ini, "rl", "compact_training", "false").lower()
    states = {"1": True, "yes": True, "true": True, "on": True,
              "0": False, "no": False, "false": False, "off": False}
    if raw not in states:
        raise ValueError(f"Not a boolean: {raw}")
    return {"compact_training": states[raw]}


def read_jammer_onsets(run_config: str) -> tuple[tuple[float, ...], tuple[float, ...]]:
    ini = _read_ini(run_config)
    duration = float(_get(ini, "scenario", "duration_s", "0"))
    result = []
    for name in ("training_jammer_onsets_s", "evaluation_jammer_onsets_s"):
        raw = _get(ini, "rl", name, "")
        values = tuple(float(v.strip()) for v in raw.split(",") if v.strip())
        if any(not 0 <= v < duration for v in values):
            raise ValueError(f"[rl] {name} must contain finite times in [0,duration_s)")
        result.append(values)
    if any(result) and not _get(ini, "scenario", "jammers_file", ""):
        raise ValueError("jammer onset schedules require jammers_file")
    return tuple(result)
