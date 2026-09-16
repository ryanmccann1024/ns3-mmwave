"""Read RL seed and movement bounds using the simulator's INI conventions."""

import configparser
import hashlib
from pathlib import Path

from scripts.sim_support import strip_inline_comment

# Fallbacks mirror RlConfig; explicit endpoints override them independently.
_BOUND_DEFAULTS = ((-1000.0, 2000.0), (-1000.0, 1000.0), (0.0, 100.0))

# Matches the C++ loader's scenario.nodes_file default.
_DEFAULT_NODES_FILE = "nodes.json"


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


def read_rl_bounds(run_config: str) -> tuple[tuple[float, float], ...]:
    """Read each configured bound independently, just like the C++ loader."""
    ini = _read_ini(run_config)
    ranges = []
    for axis, defaults in zip("xyz", _BOUND_DEFAULTS):
        endpoints = []
        for suffix, default in zip(("min", "max"), defaults):
            raw = ini.get("rl", f"{axis}_{suffix}", fallback=str(default))
            endpoints.append(float(strip_inline_comment(raw)))
        ranges.append(tuple(endpoints))
    return tuple(ranges)


def read_scenario_identity(run_config: str) -> dict:
    """Absolute run.ini path plus SHA-256 of the run.ini and nodes.json bytes."""
    ini_path = Path(run_config).resolve()
    if not ini_path.is_file():
        raise FileNotFoundError(f"run config not found: {run_config}")

    ini = _read_ini(str(ini_path))
    raw_nodes = strip_inline_comment(
        ini.get("scenario", "nodes_file", fallback="")) or _DEFAULT_NODES_FILE
    nodes_path = Path(raw_nodes)
    if not nodes_path.is_absolute():
        nodes_path = ini_path.parent / nodes_path
    if not nodes_path.is_file():
        raise FileNotFoundError(
            f"nodes file not found: {nodes_path} "
            f"(scenario.nodes_file = '{raw_nodes}' in {ini_path})"
        )

    return {
        "run_config": str(ini_path),
        "run_ini_sha256": _sha256(ini_path),
        "nodes_json_sha256": _sha256(nodes_path),
    }
