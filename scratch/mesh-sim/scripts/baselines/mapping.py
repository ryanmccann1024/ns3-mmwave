"""Mapping-file validation and rectangle geofence resolution."""

import configparser
import json
import math
from dataclasses import dataclass
from pathlib import Path

from scripts.baselines.config import ConfigError, RECT_KEYS, explicit_rl_bounds

PLATFORMS = ("ground", "aerial")
MAPPING_VERSION = 1
GROUND_DATUMS = ("z_is_agl_m",)
GEOFENCE_SOURCES = ("rl_bounds", "rectangle_xy_m")
_MAPPING_KEYS = {"baseline_mapping_version", "origin", "ground_datum", "geofence",
                 "radios", "platforms"}
_MAPPING_REQUIRED = {"baseline_mapping_version", "origin", "ground_datum", "geofence",
                     "radios"}
_POLYGON_KEYS = {"vertices", "polygon", "polygons", "points", "coordinates", "rings",
                 "holes", "geojson", "exterior", "interiors"}
POLYGON_TODO = ("only axis-aligned rectangle geofences are supported "
                "(geofence.source 'rl_bounds' or 'rectangle_xy_m'); polygon geofences "
                "are a documented TODO, and a bounding rectangle is never substituted")


@dataclass(frozen=True)
class Mapping:
    """Validated mapping file with its geofence resolved to a scenario-metre rectangle."""

    path: Path
    origin_lat: float
    origin_lon: float
    synthetic: bool
    ground_datum: str
    geofence_source: str
    rectangle: dict
    radios_default: tuple[str, ...] | None
    radios_nodes: dict
    platforms: dict

    @property
    def origin(self) -> dict:
        return {"lat": self.origin_lat, "lon": self.origin_lon, "synthetic": self.synthetic}

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


def _radio_list(where: str, value) -> tuple[str, ...]:
    if (not isinstance(value, list) or not value
            or not all(isinstance(item, str) and item for item in value)):
        raise ConfigError(f"{where} must be a non-empty list of radio type names")
    if len(set(value)) != len(value):
        raise ConfigError(f"{where} lists a radio type more than once")
    return tuple(value)


def load_mapping(path: str | Path, ini: configparser.ConfigParser) -> Mapping:
    """Parse and validate a baseline_mapping_version 1 file."""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"mapping file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"mapping file {path} is not valid JSON: {exc}") from exc
    where = f"mapping file {path}"
    _object(where, raw, _MAPPING_KEYS, _MAPPING_REQUIRED)
    version = raw["baseline_mapping_version"]
    if isinstance(version, bool) or version != MAPPING_VERSION:
        raise ConfigError(f"{where}: baseline_mapping_version must be {MAPPING_VERSION}, "
                          f"got {version!r}")
    origin = _object(f"{where}: origin", raw["origin"], {"lat", "lon", "synthetic"},
                     {"lat", "lon", "synthetic"})
    lat = _number(f"{where}: origin.lat", origin["lat"], -80.0, 80.0)
    lon = _number(f"{where}: origin.lon", origin["lon"], -180.0, 180.0)
    if not isinstance(origin["synthetic"], bool):
        raise ConfigError(f"{where}: origin.synthetic must be true or false")
    if raw["ground_datum"] not in GROUND_DATUMS:
        raise ConfigError(f"{where}: ground_datum must be one of {', '.join(GROUND_DATUMS)}, "
                          f"got {raw['ground_datum']!r}")
    source, rectangle = _geofence(f"{where}: geofence", raw["geofence"], ini)
    radios = _object(f"{where}: radios", raw["radios"], {"default", "nodes"}, set())
    default = (_radio_list(f"{where}: radios.default", radios["default"])
               if "default" in radios else None)
    per_node = radios.get("nodes", {})
    if not isinstance(per_node, dict):
        raise ConfigError(f"{where}: radios.nodes must be an object of node id -> list")
    radio_nodes = {node: _radio_list(f"{where}: radios.nodes.{node}", value)
                   for node, value in per_node.items()}
    platforms_raw = _object(f"{where}: platforms", raw.get("platforms", {}), {"nodes"}, set())
    platform_nodes = platforms_raw.get("nodes", {})
    if not isinstance(platform_nodes, dict):
        raise ConfigError(f"{where}: platforms.nodes must be an object of node id -> platform")
    for node, platform in platform_nodes.items():
        if platform not in PLATFORMS:
            raise ConfigError(f"{where}: platforms.nodes.{node} must be one of "
                              f"{', '.join(PLATFORMS)}, got {platform!r}")
    return Mapping(path=path, origin_lat=lat, origin_lon=lon, synthetic=origin["synthetic"],
                   ground_datum=raw["ground_datum"], geofence_source=source,
                   rectangle=rectangle, radios_default=default, radios_nodes=radio_nodes,
                   platforms=dict(platform_nodes))
