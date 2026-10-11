"""Map scenario nodes and validate placement ownership and returned layouts."""

import importlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from scripts.baselines import config, effective_inputs, mapping as mapping_config
from scripts.baselines.config import PLATFORMS, ConfigError

ROUND_TRIP_TOL_M = 0.01
Z_TOL_M = 1e-6
PLATFORM_BY_NODE_TYPE = {"drone": "aerial", "vehicle": "ground", "pedestrian": "ground"}
MOBILITIES = ("fixed", "constant_velocity", "random_walk", "waypoint")
# Checked against the C++ loader by test_simulator_defaults.py.
RANDOM_WALK_DEFAULTS = {"x_min": -100.0, "x_max": 100.0, "y_min": -100.0, "y_max": 100.0}


@dataclass(frozen=True)
class NodeRecord:
    """One nodes.json entry with its planner role (movable or fixed) and movement platform."""

    id: str
    roster_index: int
    node_type: str
    mobility: str
    role: str
    platform: str
    platform_source: str
    x: float
    y: float
    z: float
    random_walk_bounds: dict | None = None
    has_waypoints: bool = False
    slot: int | None = None

    @property
    def selected(self) -> bool:
        return self.role == "movable"


def _objective():
    return importlib.import_module("scripts.baselines.planners.objective")


def load_nodes(path: str | Path) -> list:
    """Read nodes.json as a list of objects with unique string ids."""
    try:
        nodes = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"nodes file {path} is not valid JSON: {exc}") from exc
    if not isinstance(nodes, list) or not all(isinstance(n, dict) for n in nodes):
        raise ConfigError(f"nodes file {path} must be a JSON array of objects")
    ids = [n.get("id") for n in nodes]
    if not all(isinstance(i, str) and i for i in ids):
        raise ConfigError(f"nodes file {path}: every node needs a non-empty string id")
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ConfigError(f"nodes file {path} repeats node id(s) {', '.join(duplicates)}")
    return nodes


def _require_ids(label: str, ids, known: set) -> None:
    unknown = sorted(set(ids) - known)
    if unknown:
        raise ConfigError(f"{label} names unknown node id(s): {', '.join(unknown)}")


def _slot(node_id: str, index: int, controlled: tuple | None) -> int | None:
    if controlled is None:
        return None
    if controlled == (config.ALL_NODES,):
        return index
    return controlled.index(node_id) if node_id in controlled else None


def resolve_ids(ids: tuple, roster: list) -> list:
    """`all` -> the whole roster; otherwise the given ids in roster order."""
    if ids == (config.ALL_NODES,):
        return list(roster)
    return [node_id for node_id in roster if node_id in ids]


def _random_walk_bounds(entry: dict) -> dict:
    bounds = (entry.get("random_walk") or {}).get("bounds") or {}
    return {key: float(bounds.get(key, default)) for key, default in RANDOM_WALK_DEFAULTS.items()}


def build_records(
    nodes: list,
    cfg: config.BaselineConfig,
    mapping: mapping_config.Mapping,
    controlled: tuple | None = None,
) -> tuple:
    """Map every node to a role, platform, start position, bounds, and RL slot."""
    known = {n["id"] for n in nodes}
    if not cfg.movable_all:
        _require_ids("baseline.movable_nodes", cfg.movable_nodes, known)
    _require_ids("mapping platforms.nodes", mapping.platforms, known)
    movable = set(resolve_ids(cfg.movable_nodes, [n["id"] for n in nodes]))
    records = []
    for index, entry in enumerate(nodes):
        node_id = entry["id"]
        mobility = entry.get("mobility", "fixed")
        if mobility not in MOBILITIES:
            raise ConfigError(f"node '{node_id}' has unsupported mobility {mobility!r}")
        node_type = entry.get("node_type", "drone")
        if node_id in mapping.platforms:
            platform, platform_source = mapping.platforms[node_id], "mapping"
        elif node_type in PLATFORM_BY_NODE_TYPE:
            platform, platform_source = PLATFORM_BY_NODE_TYPE[node_type], "node_type"
        else:
            raise ConfigError(
                f"node '{node_id}' has node_type {node_type!r}; set its "
                "platform in a mapping file (platforms.nodes)"
            )
        x, y, z = effective_inputs.start_position(entry)
        if not all(math.isfinite(v) for v in (x, y, z)):
            raise ConfigError(f"node '{node_id}' has a non-finite start position")
        records.append(
            NodeRecord(
                id=node_id,
                roster_index=index,
                node_type=node_type,
                mobility=mobility,
                role="movable" if node_id in movable else "fixed",
                platform=platform,
                platform_source=platform_source,
                x=x,
                y=y,
                z=z,
                random_walk_bounds=(
                    _random_walk_bounds(entry) if mobility == "random_walk" else None
                ),
                has_waypoints=mobility == "waypoint" and bool(entry.get("waypoints")),
                slot=_slot(node_id, index, controlled),
            )
        )
    return tuple(records)


def check_datum(records: tuple) -> None:
    """Accept only z as height above flat ground at z = 0."""
    for record in records:
        if record.z < 0:
            raise ConfigError(
                f"node '{record.id}' has z={record.z} below the ground "
                "datum; z is height above flat ground at z = 0 and must be "
                ">= 0"
            )


def check_ownership(cfg: config.BaselineConfig, controlled: tuple | None, roster: list) -> list:
    """Evaluation: resolved movable_nodes must equal resolved [rl] controlled_nodes."""
    if controlled is None:
        raise ConfigError(
            "placement evaluation needs [rl] controlled_nodes (centralized "
            "control); legacy single-node control is not supported"
        )
    known = set(roster)
    if not cfg.movable_all:
        _require_ids("baseline.movable_nodes", cfg.movable_nodes, known)
    if controlled != (config.ALL_NODES,):
        _require_ids("[rl] controlled_nodes", controlled, known)
        duplicates = sorted({i for i in controlled if controlled.count(i) > 1})
        if duplicates:
            raise ConfigError(
                f"[rl] controlled_nodes lists {', '.join(duplicates)} more " "than once"
            )
    movable = set(resolve_ids(cfg.movable_nodes, roster))
    controlled_ids = _controlled_ids(controlled, roster)
    not_controlled = [node for node in roster if node in movable and node not in controlled_ids]
    not_movable = [node for node in roster if node in controlled_ids and node not in movable]
    if not_controlled or not_movable:
        raise ConfigError(
            "placement evaluation holds every RL slot, so [baseline] movable_nodes must "
            "equal [rl] controlled_nodes; movable but not controlled: "
            f"{', '.join(not_controlled) or '-'}; controlled but not movable: "
            f"{', '.join(not_movable) or '-'}. Set [baseline] movable_nodes and [rl] "
            "controlled_nodes to the same ids, or `all`"
        )
    return controlled_ids


def evaluation_region(rectangle: dict, rl_bounds: dict) -> dict:
    """Evaluation placement area: the geofence rectangle intersected with the [rl] x/y bounds."""
    region = {
        "x_min": max(rectangle["x_min"], rl_bounds["x_min"]),
        "x_max": min(rectangle["x_max"], rl_bounds["x_max"]),
        "y_min": max(rectangle["y_min"], rl_bounds["y_min"]),
        "y_max": min(rectangle["y_max"], rl_bounds["y_max"]),
    }
    if region["x_min"] >= region["x_max"] or region["y_min"] >= region["y_max"]:
        raise ConfigError(
            f"the geofence rectangle {rectangle} and the [rl] x/y bounds "
            f"{rl_bounds} do not overlap; evaluation places nodes only "
            "inside both"
        )
    return region


def resolve_penalties(cfg: config.BaselineConfig) -> dict:
    """Platform -> objective.MovementCost from the [baseline] cost keys."""
    movement_cost = _objective().MovementCost
    return {
        platform: movement_cost(
            fixed_cost_m2=getattr(cfg, f"{platform}_fixed_cost_m2"),
            cost_m2_per_m=getattr(cfg, f"{platform}_cost_m2_per_m"),
            max_displacement_m=getattr(cfg, f"{platform}_max_displacement_m"),
        )
        for platform in PLATFORMS
    }


def _inside(x: float, y: float, rect: dict) -> bool:
    return rect["x_min"] <= x <= rect["x_max"] and rect["y_min"] <= y <= rect["y_max"]


def validate_result(
    records: tuple, result, rectangle: dict, penalties: dict, rl_bounds: dict | None = None
) -> dict:
    """Check the plan and return id -> final (x, y, z); fails on any violation, never clamps."""
    positions = result.positions
    expected = {record.id for record in records}
    missing = sorted(expected - set(positions))
    extra = sorted(set(positions) - expected)
    if missing or extra:
        raise ValueError(
            f"planner result ids do not match the scenario (missing: "
            f"{', '.join(missing) or '-'}; unexpected: {', '.join(extra) or '-'})"
        )
    final = {}
    for record in records:
        values = positions[record.id]
        if len(values) != 3 or not all(math.isfinite(float(v)) for v in values):
            raise ValueError(f"planner returned a non-finite position for '{record.id}'")
        x, y, z = (float(v) for v in values)
        if abs(z - record.z) > Z_TOL_M:
            raise ValueError(f"planner changed z of '{record.id}' from {record.z} to {z}")
        moved = math.hypot(x - record.x, y - record.y)
        if not record.selected:
            if moved > ROUND_TRIP_TOL_M:
                raise ValueError(
                    f"planner moved {record.role} node '{record.id}' by "
                    f"{moved:.6f} m; only movable_nodes may move"
                )
            final[record.id] = (record.x, record.y, record.z)
            continue
        if moved <= ROUND_TRIP_TOL_M:
            x, y, moved = record.x, record.y, 0.0
        if not _inside(x, y, rectangle):
            raise ValueError(
                f"planned position of '{record.id}' ({x}, {y}) is outside the "
                f"declared geofence rectangle {rectangle}"
            )
        cap = penalties[record.platform].max_displacement_m
        if cap is not None and moved > cap + ROUND_TRIP_TOL_M:
            raise ValueError(
                f"'{record.id}' moved {moved:.3f} m, beyond [baseline] "
                f"{record.platform}_max_displacement_m {cap}"
            )
        if rl_bounds is not None and not _inside(x, y, rl_bounds):
            raise ValueError(
                f"planned position of '{record.id}' ({x}, {y}) is outside the "
                f"[rl] x/y bounds {rl_bounds}"
            )
        if record.random_walk_bounds is not None and not _inside(x, y, record.random_walk_bounds):
            raise ValueError(
                f"planned position of '{record.id}' ({x}, {y}) is outside "
                f"its random_walk bounds {record.random_walk_bounds}"
            )
        final[record.id] = (x, y, record.z)
    return final


def _xyz(values) -> dict:
    return {"x": values[0], "y": values[1], "z": values[2]}


def plan_nodes(records: tuple, final: dict) -> list:
    """baseline-plan.json node entries."""
    entries = []
    for record in records:
        planned = final[record.id]
        entries.append(
            {
                "id": record.id,
                "roster_index": record.roster_index,
                "slot": record.slot,
                "role": record.role,
                "platform": record.platform,
                "selected": record.selected,
                "original": _xyz((record.x, record.y, record.z)),
                "planned": _xyz(planned),
                "displacement_m": math.hypot(planned[0] - record.x, planned[1] - record.y),
            }
        )
    return entries


def _controlled_ids(controlled: tuple | None, roster: list) -> list | None:
    if controlled is None:
        return None
    return list(roster) if controlled == (config.ALL_NODES,) else list(controlled)


def check_gateway_ownership(ini, records: tuple, controlled: tuple | None) -> None:
    """Keep the active traffic gateway out of placement and RL control."""
    if config.ini_value(ini, "traffic", "flow_topology") != "gateway":
        return
    gateway = config.ini_value(ini, "traffic", "gateway_node_id")
    if any(record.id == gateway and record.selected for record in records):
        raise ConfigError(f"active traffic gateway '{gateway}' cannot be baseline-movable")
    if controlled is not None and (controlled == ("all",) or gateway in controlled):
        raise ConfigError(f"active traffic gateway '{gateway}' cannot be RL-controlled")
