"""Strict [baseline] configuration and simulator INI access."""

import configparser
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from scripts.sim_support import strip_inline_comment

PLACEMENT_METHODS = ("geometric", "optimization")
ALGORITHMS = ("none", *PLACEMENT_METHODS)
OBJECTIVES = ("coverage", "balanced", "resilience")
APPLICATIONS = ("initial_positions",)
WAYPOINT_POLICIES = ("reject", "translate")
BASELINE_KEYS = ("algorithm", "objective", "application", "gateway_node_id",
                 "movable_nodes", "seed", "max_iterations", "waypoint_policy",
                 "mapping_file", "rf_config")

RECT_KEYS = ("x_min", "x_max", "y_min", "y_max")
# Mirrors the C++ RlConfig fallbacks for bounds that are not written in the INI.
RL_BOUND_DEFAULTS = {"x_min": -1000.0, "x_max": 2000.0, "y_min": -1000.0, "y_max": 1000.0}

# Keeps [DEFAULT] an ordinary section, as in the C++ parser; no header can contain '\n'.
_NO_DEFAULT_SECTION = "\n"
_UNSIGNED = re.compile(r"[0-9]+")


class ConfigError(ValueError):
    """Invalid [baseline] section, mapping file, or INI structure."""


@dataclass(frozen=True)
class BaselineConfig:
    """Validated [baseline] values; paths are absolute and not yet checked for existence."""

    run_config: Path
    algorithm: str = "none"
    objective: str | None = None
    application: str = "initial_positions"
    gateway_node_id: str | None = None
    movable_nodes: tuple[str, ...] = ()
    seed: int | None = None
    max_iterations: int | None = None
    waypoint_policy: str = "reject"
    mapping_file: Path | None = None
    rf_config: Path | None = None
    present_keys: frozenset = field(default_factory=frozenset)


def read_ini(run_config: str | Path) -> configparser.ConfigParser:
    """Parse strictly: duplicates, ':' assignments, and continuation lines fail."""
    path = Path(run_config)
    if not path.is_file():
        raise ConfigError(f"run config not found: {path}")
    ini = configparser.ConfigParser(interpolation=None, strict=True, delimiters=("=",),
                                    default_section=_NO_DEFAULT_SECTION)
    ini.optionxform = str
    try:
        ini.read_string(path.read_text(encoding="utf-8"), source=str(path))
    except configparser.Error as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    for section in ini.sections():
        if section != section.strip():
            raise ConfigError(f"{path}: section header '[{section}]' has surrounding "
                              f"whitespace; use '[{section.strip()}]'")
        for key, raw in ini.items(section, raw=True):
            if "\n" in raw:
                raise ConfigError(f"{path}: [{section}] {key} continues onto an indented "
                                  "line; the simulator reads each line separately")
    return ini


def ini_value(ini: configparser.ConfigParser, section: str, key: str) -> str | None:
    """Return the comment-stripped value, or None when absent or blank."""
    if not ini.has_option(section, key):
        return None
    value = strip_inline_comment(ini.get(section, key))
    return value or None


def _resolve(run_config: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else run_config.parent / path


def _unsigned(where: str, key: str, raw: str, minimum: int) -> int:
    if not _UNSIGNED.fullmatch(raw) or int(raw) < minimum:
        raise ConfigError(f"{where}: baseline.{key} must be an integer >= {minimum}, "
                          f"got {raw!r}")
    return int(raw)


def _choice(where: str, key: str, raw: str, allowed: tuple) -> str:
    if raw not in allowed:
        raise ConfigError(f"{where}: baseline.{key} must be one of {', '.join(allowed)}; "
                          f"got {raw!r}")
    return raw


def _node_id(where: str, key: str, raw: str) -> str:
    if not raw or raw == "all" or "," in raw or raw != raw.strip():
        raise ConfigError(f"{where}: baseline.{key} has an invalid node id {raw!r}")
    return raw


def load_baseline(run_config: str | Path) -> BaselineConfig:
    """Read and validate [baseline]; an absent section or blank algorithm means none."""
    path = Path(run_config).resolve()
    ini = read_ini(path)
    where = str(path)
    if not ini.has_section("baseline"):
        return BaselineConfig(run_config=path)
    unknown = sorted(set(ini.options("baseline")) - set(BASELINE_KEYS))
    if unknown:
        raise ConfigError(f"{where}: unknown [baseline] key(s): {', '.join(unknown)}; "
                          f"allowed: {', '.join(BASELINE_KEYS)}")
    raw = {key: ini_value(ini, "baseline", key) for key in BASELINE_KEYS}
    values: dict = {"present_keys": frozenset(k for k, v in raw.items() if v is not None)}
    values["algorithm"] = _choice(where, "algorithm", raw["algorithm"] or "none", ALGORITHMS)
    if raw["objective"] is not None:
        values["objective"] = _choice(where, "objective", raw["objective"], OBJECTIVES)
    if raw["application"] is not None:
        values["application"] = _choice(where, "application", raw["application"],
                                        APPLICATIONS)
    if raw["waypoint_policy"] is not None:
        values["waypoint_policy"] = _choice(where, "waypoint_policy",
                                            raw["waypoint_policy"], WAYPOINT_POLICIES)
    if raw["gateway_node_id"] is not None:
        values["gateway_node_id"] = _node_id(where, "gateway_node_id",
                                             raw["gateway_node_id"])
    if raw["movable_nodes"] is not None:
        tokens = [token.strip() for token in raw["movable_nodes"].split(",")]
        ids = tuple(_node_id(where, "movable_nodes", token) for token in tokens)
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ConfigError(f"{where}: baseline.movable_nodes lists "
                              f"{', '.join(duplicates)} more than once")
        values["movable_nodes"] = ids
    if raw["seed"] is not None:
        values["seed"] = _unsigned(where, "seed", raw["seed"], 0)
    if raw["max_iterations"] is not None:
        values["max_iterations"] = _unsigned(where, "max_iterations",
                                             raw["max_iterations"], 1)
    for key in ("mapping_file", "rf_config"):
        if raw[key] is not None:
            values[key] = _resolve(path, raw[key])
    gateway = values.get("gateway_node_id")
    if gateway is not None and gateway in values.get("movable_nodes", ()):
        raise ConfigError(f"{where}: baseline.gateway_node_id '{gateway}' must not appear "
                          "in baseline.movable_nodes")
    return BaselineConfig(run_config=path, **values)


def require_method(cfg: BaselineConfig, method: str) -> None:
    """Check that every key the effective method needs is present."""
    if method not in ALGORITHMS:
        raise ConfigError(f"unknown placement method {method!r}; expected one of "
                          f"{', '.join(ALGORITHMS)}")
    if method == "none":
        return
    required = ["objective", "gateway_node_id", "movable_nodes", "mapping_file", "rf_config"]
    if method == "optimization":
        required += ["seed", "max_iterations"]
    missing = [key for key in required if key not in cfg.present_keys]
    if missing:
        raise ConfigError(f"{cfg.run_config}: method '{method}' requires [baseline] "
                          f"{', '.join(missing)}")


def scenario_file(ini: configparser.ConfigParser, run_config: str | Path, key: str,
                  default: str | None = None) -> Path | None:
    """Resolve a [scenario] file key against the INI directory; blank or absent means none."""
    raw = ini_value(ini, "scenario", key) or default
    return _resolve(Path(run_config).resolve(), raw) if raw else None


def explicit_rl_bounds(ini: configparser.ConfigParser) -> dict:
    """Return only the [rl] x/y bounds written in the INI, as floats."""
    bounds = {}
    for key in RECT_KEYS:
        raw = ini_value(ini, "rl", key)
        if raw is None:
            continue
        try:
            value = float(raw)
        except ValueError as exc:
            raise ConfigError(f"rl.{key} is not a number: {raw!r}") from exc
        if not math.isfinite(value):
            raise ConfigError(f"rl.{key} must be finite, got {raw!r}")
        bounds[key] = value
    return bounds


def effective_rl_bounds(ini: configparser.ConfigParser) -> dict:
    """Return the x/y bounds the simulator enforces, with its fallbacks for absent keys."""
    return {**RL_BOUND_DEFAULTS, **explicit_rl_bounds(ini)}


def rl_controlled_nodes(ini: configparser.ConfigParser) -> tuple[str, ...] | None:
    """Tokens of [rl] controlled_nodes, or None for legacy single-node control."""
    if not ini.has_option("rl", "controlled_nodes"):
        return None
    raw = strip_inline_comment(ini.get("rl", "controlled_nodes"))
    return tuple(token.strip() for token in raw.split(",") if token.strip())


def __getattr__(name: str):
    """Keep the existing mapping imports available for downstream adapters."""
    if name in ("Mapping", "load_mapping", "PLATFORMS", "MAPPING_VERSION",
                "GROUND_DATUMS", "GEOFENCE_SOURCES", "POLYGON_TODO"):
        from scripts.baselines import mapping
        return getattr(mapping, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
