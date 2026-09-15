"""Read RL seed and movement bounds using the simulator's INI conventions."""

import configparser

from scripts.sim_support import strip_inline_comment

# Fallbacks mirror RlConfig; explicit endpoints override them independently.
_BOUND_DEFAULTS = ((-1000.0, 2000.0), (-1000.0, 1000.0), (0.0, 100.0))


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
