"""Mapping-file validation and rectangle geofence resolution."""

import configparser
import json
import math
from dataclasses import dataclass
from pathlib import Path
from scripts.baselines.config import ConfigError, RECT_KEYS, PLATFORMS, explicit_rl_bounds

MAPPING_VERSION = 2
GEOFENCE_SOURCES = ("rl_bounds", "rectangle_xy_m")
_MAPPING_KEYS = {"baseline_mapping_version", "geofence", "platforms"}
_MAPPING_REQUIRED = {"baseline_mapping_version", "geofence"}
_MAPPING_REMOVED = {"origin", "ground_datum", "radios"}
MAPPING_V1_MIGRATION = (
    "baseline_mapping_version 1 is no longer read; migrate to version 2: delete "
    "origin, ground_datum and radios (baselines are gateway-free and scored by the "
    "simulator channel), keep geofence and platforms, and set baseline_mapping_version "
    "to 2"
)
_POLYGON_KEYS = {"vertices", "polygon", "polygons", "points", "coordinates", "rings",
                 "holes", "geojson", "exterior", "interiors"}
POLYGON_TODO = ("only axis-aligned rectangle geofences are supported "
                "(geofence.source 'rl_bounds' or 'rectangle_xy_m'); polygon geofences "
                "are a documented TODO, and a bounding rectangle is never substituted")


@dataclass(frozen=True)
class Mapping:
    """Validated mapping file (or the defaults) with its geofence as a scenario-metre rectangle."""

    path: Path | None
    geofence_source: str
    rectangle: dict
    platforms: dict

    @property
    def geofence(self) -> dict:
        return {"source": self.geofence_source, **self.rectangle}


def _object(where: str, value, allowed: set, required: set) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a JSON object")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ConfigError(f"{where} has unknown key(s): {', '.join(unknown)}")
    missing = sorted(required - set(value))
    if missing:
        raise ConfigError(f"{where} is missing key(s): {', '.join(missing)}")
    return value


def _number(where: str, value, low: float | None = None, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{where} must be a number")
    value = float(value)
    if not math.isfinite(value):
        raise ConfigError(f"{where} must be finite")
    if (low is not None and value < low) or (high is not None and value > high):
        raise ConfigError(f"{where} must be within [{low}, {high}], got {value}")
    return value


def _rectangle(where: str, source: dict) -> dict:
    rect = {key: _number(f"{where}.{key}", source[key]) for key in RECT_KEYS}
    if rect["x_min"] >= rect["x_max"] or rect["y_min"] >= rect["y_max"]:
        raise ConfigError(f"{where} must have x_min < x_max and y_min < y_max")
    return rect


def _geofence(where: str, value, ini: configparser.ConfigParser) -> tuple[str, dict]:
    if isinstance(value, list):
        raise ConfigError(f"{where} is a point list: {POLYGON_TODO}")
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a JSON object")
    source = value.get("source")
    polygonal = sorted(set(value) & _POLYGON_KEYS)
    if polygonal or (isinstance(source, str) and source not in GEOFENCE_SOURCES
                     and any(word in source.lower()
                             for word in ("poly", "geojson", "vert", "point"))):
        raise ConfigError(f"{where} requests a polygon "
                          f"({', '.join(polygonal) or repr(source)}): {POLYGON_TODO}")
    if source not in GEOFENCE_SOURCES:
        raise ConfigError(f"{where}.source must be one of {', '.join(GEOFENCE_SOURCES)}, "
                          f"got {source!r}")
    if source == "rl_bounds":
        _object(where, value, {"source"}, {"source"})
        bounds = explicit_rl_bounds(ini)
        missing = [key for key in RECT_KEYS if key not in bounds]
        if missing:
            raise ConfigError(f"{where}.source 'rl_bounds' needs [rl] "
                              f"{', '.join(missing)} written in the INI; loader defaults "
                              "are not used")
        return source, _rectangle("[rl] bounds", bounds)
    _object(where, value, {"source", *RECT_KEYS}, {"source", *RECT_KEYS})
    return source, _rectangle(where, value)


def default_mapping(ini: configparser.ConfigParser) -> Mapping:
    """No mapping file: the [rl] bounds geofence and platforms by node_type."""
    source, rectangle = _geofence("default geofence", {"source": "rl_bounds"}, ini)
    return Mapping(path=None, geofence_source=source, rectangle=rectangle, platforms={})


def load_mapping(path: str | Path | None, ini: configparser.ConfigParser) -> Mapping:
    """Parse a baseline_mapping_version 2 file; None gives default_mapping()."""
    if path is None:
        return default_mapping(ini)
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"mapping file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"mapping file {path} is not valid JSON: {exc}") from exc
    where = f"mapping file {path}"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a JSON object")
    version = raw.get("baseline_mapping_version")
    if not isinstance(version, bool) and version == 1:
        raise ConfigError(f"{where}: {MAPPING_V1_MIGRATION}")
    if isinstance(version, bool) or version != MAPPING_VERSION:
        raise ConfigError(
            f"{where}: baseline_mapping_version must be {MAPPING_VERSION}, " f"got {version!r}"
        )
    removed = sorted(set(raw) & _MAPPING_REMOVED)
    if removed:
        raise ConfigError(
            f"{where}: {', '.join(removed)} removed in mapping version 2; "
            "baselines are gateway-free and scored by the simulator channel, "
            "so delete them"
        )
    _object(where, raw, _MAPPING_KEYS, _MAPPING_REQUIRED)
    source, rectangle = _geofence(f"{where}: geofence", raw["geofence"], ini)
    platforms_raw = _object(f"{where}: platforms", raw.get("platforms", {}), {"nodes"}, set())
    platform_nodes = platforms_raw.get("nodes", {})
    if not isinstance(platform_nodes, dict):
        raise ConfigError(f"{where}: platforms.nodes must be an object of node id -> platform")
    for node, platform in platform_nodes.items():
        if platform not in PLATFORMS:
            raise ConfigError(
                f"{where}: platforms.nodes.{node} must be one of "
                f"{', '.join(PLATFORMS)}, got {platform!r}"
            )
    return Mapping(
        path=path, geofence_source=source, rectangle=rectangle, platforms=dict(platform_nodes)
    )
