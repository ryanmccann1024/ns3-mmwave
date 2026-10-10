"""Adapt scenario nodes and validate results at the foreign-planner boundary."""

import json
import math
from dataclasses import dataclass
from pathlib import Path

from scripts.baselines import config, effective_inputs
from scripts.baselines.config import ConfigError

ROUND_TRIP_TOL_M = 0.01
Z_TOL_M = 1e-6
PLATFORM_BY_NODE_TYPE = {"drone": "aerial", "vehicle": "ground", "pedestrian": "ground"}
MOBILITIES = ("fixed", "constant_velocity", "random_walk", "waypoint")
# Mirrors RandomWalkParams defaults in src/domain/node-spec.h.
RANDOM_WALK_DEFAULTS = {"x_min": -100.0, "x_max": 100.0, "y_min": -100.0, "y_max": 100.0}


@dataclass(frozen=True)
class NodeRecord:
    """One nodes.json entry mapped to its planner role, platform, and radios."""

    id: str
    roster_index: int
    node_type: str
    mobility: str
    role: str
    platform: str
    platform_source: str
    radios: tuple
    x: float
    y: float
    z: float
    slot: int | None = None

    @property
    def selected(self) -> bool:
        return self.role == "movable"


@dataclass(frozen=True)
class PlanRequest:
    """Everything the solver needs, in scenario metres plus the projection origin."""

    method: str
    objective: str
    nodes: tuple
    origin_lat: float
    origin_lon: float
    rectangle: dict
    rf_config: Path
    planner_seed: int | None
    max_iterations: int | None
    source_dir: Path


@dataclass(frozen=True)
class PlanResult:
    """Solver output: node id -> (x, y, z) in scenario metres, plus planner diagnostics."""

    positions: dict
    predictions: dict | None = None
    planner_wall_s: float = 0.0


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
    if controlled == ("all",):
        return index
    return controlled.index(node_id) if node_id in controlled else None


def build_records(nodes: list, cfg: config.BaselineConfig, mapping: config.Mapping,
                  controlled: tuple | None = None) -> tuple:
    """Map every node to a role, platform, radio list, start position, and RL slot."""
    known = {n["id"] for n in nodes}
    _require_ids("baseline.gateway_node_id", [cfg.gateway_node_id], known)
    _require_ids("baseline.movable_nodes", cfg.movable_nodes, known)
    _require_ids("mapping radios.nodes", mapping.radios_nodes, known)
    _require_ids("mapping platforms.nodes", mapping.platforms, known)
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
            raise ConfigError(f"node '{node_id}' has node_type {node_type!r}; set its "
                              "platform in the mapping file")
        radios = mapping.radios_nodes.get(node_id, mapping.radios_default)
        if not radios:
            raise ConfigError(f"node '{node_id}' has no radio type; add radios.default or "
                              f"radios.nodes['{node_id}'] to the mapping file")
        x, y, z = effective_inputs.start_position(entry)
        if not all(math.isfinite(v) for v in (x, y, z)):
            raise ConfigError(f"node '{node_id}' has a non-finite start position")
        role = ("gateway" if node_id == cfg.gateway_node_id
                else "movable" if node_id in cfg.movable_nodes else "fixed")
        records.append(NodeRecord(id=node_id, roster_index=index, node_type=node_type,
                                  mobility=mobility, role=role, platform=platform,
                                  platform_source=platform_source, radios=tuple(radios),
                                  x=x, y=y, z=z, slot=_slot(node_id, index, controlled)))
    return tuple(records)


def check_datum(records: tuple) -> None:
    """Accept only z as height above flat ground at z = 0."""
    for record in records:
        if record.z < 0:
            raise ConfigError(f"node '{record.id}' has z={record.z} below the declared "
                              "ground datum; only z_is_agl_m with z >= 0 is supported")


def check_radios(records: tuple, rf_summary: dict) -> None:
    """Every radio type must exist in the RF file and must not be a blos backhaul."""
    radios = rf_summary["radios"]
    for record in records:
        for radio in record.radios:
            if radio not in radios:
                raise ConfigError(f"node '{record.id}' uses radio type '{radio}', which "
                                  f"the RF file does not define ({', '.join(sorted(radios))})")
            if radios[radio].get("blos"):
                raise ConfigError(f"node '{record.id}' uses radio type '{radio}', marked "
                                  "blos in the RF file; the simulator has no backhaul "
                                  "equivalent")


def check_gateway_ownership(ini, records: tuple, controlled: tuple | None) -> None:
    """Keep the active traffic gateway out of placement and RL control."""
    if config.ini_value(ini, "traffic", "flow_topology") != "gateway":
        return
    gateway = config.ini_value(ini, "traffic", "gateway_node_id")
    if any(record.id == gateway and record.selected for record in records):
        raise ConfigError(f"active traffic gateway '{gateway}' cannot be baseline-movable")
    if controlled is not None and (controlled == ("all",) or gateway in controlled):
        raise ConfigError(f"active traffic gateway '{gateway}' cannot be RL-controlled")


def check_hold_contract(cfg: config.BaselineConfig, controlled: tuple | None) -> None:
    """Evaluation needs centralized control with every movable node RL-controlled."""
    if controlled is None:
        raise ConfigError("placement evaluation needs [rl] controlled_nodes (centralized "
                          "control); legacy single-node control is not supported")
    if controlled == ("all",):
        return
    outside = [node for node in cfg.movable_nodes if node not in controlled]
    if outside:
        raise ConfigError("baseline.movable_nodes must be RL-controlled for the hold "
                          f"executor; not in [rl] controlled_nodes: {', '.join(outside)}")


def _inside(x: float, y: float, rect: dict) -> bool:
    return rect["x_min"] <= x <= rect["x_max"] and rect["y_min"] <= y <= rect["y_max"]


def _random_walk_bounds(entry: dict) -> dict:
    bounds = (entry.get("random_walk") or {}).get("bounds") or {}
    return {key: float(bounds.get(key, default))
            for key, default in RANDOM_WALK_DEFAULTS.items()}


def validate_result(records: tuple, result: PlanResult, rectangle: dict,
                    rf_summary: dict, nodes: list, rl_bounds: dict | None = None) -> dict:
    """Check the plan and return id -> final (x, y, z); fails on any violation, never clamps."""
    positions = result.positions
    expected = {record.id for record in records}
    missing = sorted(expected - set(positions))
    extra = sorted(set(positions) - expected)
    if missing or extra:
        raise ValueError(f"planner result ids do not match the scenario (missing: "
                         f"{', '.join(missing) or '-'}; unexpected: {', '.join(extra) or '-'})")
    entries = {entry["id"]: entry for entry in nodes}
    caps = rf_summary.get("movement_cost", {})
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
                raise ValueError(f"planner moved {record.role} node '{record.id}' by "
                                 f"{moved:.6f} m; only movable_nodes may move")
            final[record.id] = (record.x, record.y, record.z)
            continue
        if moved <= ROUND_TRIP_TOL_M:
            x, y, moved = record.x, record.y, 0.0
        if not _inside(x, y, rectangle):
            raise ValueError(f"planned position of '{record.id}' ({x}, {y}) is outside the "
                             f"declared geofence rectangle {rectangle}")
        cap = (caps.get(record.platform) or {}).get("max_displacement_m")
        if cap is not None and moved > cap + ROUND_TRIP_TOL_M:
            raise ValueError(f"'{record.id}' moved {moved:.3f} m, beyond the RF file's "
                             f"max_displacement_m {cap} for {record.platform} nodes")
        if rl_bounds is not None and not _inside(x, y, rl_bounds):
            raise ValueError(f"planned position of '{record.id}' ({x}, {y}) is outside the "
                             f"[rl] x/y bounds {rl_bounds}")
        if record.mobility == "random_walk":
            walk = _random_walk_bounds(entries[record.id])
            if not _inside(x, y, walk):
                raise ValueError(f"planned position of '{record.id}' ({x}, {y}) is outside "
                                 f"its random_walk bounds {walk}")
        final[record.id] = (x, y, record.z)
    return final


def _xyz(values) -> dict:
    return {"x": values[0], "y": values[1], "z": values[2]}


def plan_nodes(records: tuple, final: dict) -> list:
    """baseline-plan.json node entries."""
    entries = []
    for record in records:
        planned = final[record.id]
        entries.append({
            "id": record.id, "roster_index": record.roster_index, "slot": record.slot,
            "role": record.role, "platform": record.platform, "radios": list(record.radios),
            "selected": record.selected, "original": _xyz((record.x, record.y, record.z)),
            "planned": _xyz(planned),
            "displacement_m": math.hypot(planned[0] - record.x, planned[1] - record.y),
        })
    return entries


def __getattr__(name: str):
    """Preserve preparation imports for existing downstream callers."""
    if name in ("prepare", "PreparedBaseline", "BaselinePreparationError"):
        from scripts.baselines import preparation
        return getattr(preparation, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
