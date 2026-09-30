"""Node mapping, plan validation, and prepare(), the entry point both launchers call."""

import importlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

from scripts.baselines import artifacts, config, effective_inputs
from scripts.baselines.config import PLACEMENT_METHODS, ConfigError

MODES = ("standalone", "evaluation")
EXECUTORS = {"standalone": "none", "evaluation": "hold"}
ROUND_TRIP_TOL_M = 0.01
Z_TOL_M = 1e-6
PLATFORM_BY_NODE_TYPE = {"drone": "aerial", "vehicle": "ground", "pedestrian": "ground"}
MOBILITIES = ("fixed", "constant_velocity", "random_walk", "waypoint")
# Mirrors RandomWalkParams defaults in src/domain/node-spec.h.
RANDOM_WALK_DEFAULTS = {"x_min": -100.0, "x_max": 100.0, "y_min": -100.0, "y_max": 100.0}
DEFAULT_BAND = "mmwave"
EVAL_MANIFEST_NAME = "eval_manifest.json"


class BaselinePreparationError(RuntimeError):
    """Placement preparation failed; the baseline manifest records status failed."""


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


@dataclass(frozen=True)
class PreparedBaseline:
    """Paths and the eval_manifest `baseline` block for one prepared method."""

    prep_dir: Path
    mode: str
    method: str
    manifest_path: Path
    plan_path: Path
    effective_run_config: Path
    metadata: dict


def _solver():
    return importlib.import_module("scripts.baselines.arpo_solver")


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
    """Phase 1 accepts only z as height above flat ground at z = 0."""
    for record in records:
        if record.z < 0:
            raise ConfigError(f"node '{record.id}' has z={record.z} below the declared "
                              "ground datum; Phase 1 supports only z_is_agl_m with z >= 0")


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


def _unplanned_nodes(nodes: list) -> list:
    entries = []
    for index, entry in enumerate(nodes):
        start = effective_inputs.start_position(entry)
        entries.append({"id": entry["id"], "roster_index": index, "slot": None,
                        "role": None, "platform": None, "radios": [], "selected": False,
                        "original": _xyz(start), "planned": _xyz(start),
                        "displacement_m": 0.0})
    return entries


def _simulator_channel(ini, band: str | None) -> dict:
    values = {}
    if ini.has_section("channel"):
        values = {key: config.ini_value(ini, "channel", key)
                  for key in ini.options("channel")}
    ini_band = values.get("band")
    if band:
        effective, source = band, "cli"
    elif ini_band:
        effective, source = ini_band, "run.ini"
    else:
        effective, source = DEFAULT_BAND, "default"
    return {"band": effective, "band_source": source, "values": values}


def _seed_fields(method: str, cfg: config.BaselineConfig) -> dict:
    if method == "optimization":
        return {"planner_seed": cfg.seed, "planner_seed_status": "used",
                "max_iterations": cfg.max_iterations, "max_iterations_status": "used"}
    return {"planner_seed": None,
            "planner_seed_status": "unused" if method == "geometric" else "not_applicable",
            "max_iterations": None, "max_iterations_status": "not_applicable"}


def _rf_planner(records: tuple, rf_summary: dict, request: PlanRequest) -> dict:
    used = sorted({radio for record in records for radio in record.radios})
    platforms = sorted({record.platform for record in records if record.selected})
    return {
        "radios": {radio: rf_summary["radios"][radio] for radio in used},
        "fade_margin_db": rf_summary.get("fade_margin_db"),
        "range_safety_factor": rf_summary.get("range_safety_factor"),
        "reference_receiver": rf_summary.get("reference_receiver"),
        "movement_cost": {p: rf_summary.get("movement_cost", {}).get(p) for p in platforms},
        "terrain_elevation_m": 0.0,
        "optimizer": {"seed": request.planner_seed, "max_iters": request.max_iterations},
    }


def _resolve_method(mode: str, method: str | None, cfg: config.BaselineConfig) -> str:
    if mode == "evaluation":
        if method not in PLACEMENT_METHODS:
            raise ConfigError(f"evaluation placement method must be one of "
                              f"{', '.join(PLACEMENT_METHODS)}, got {method!r}")
        return method
    resolved = method or cfg.algorithm
    if resolved not in config.ALGORITHMS:
        raise ConfigError(f"unknown placement method {resolved!r}; expected one of "
                          f"{', '.join(config.ALGORITHMS)}")
    return resolved


def prepare(run_config: str | Path, method: str | None, prep_dir: str | Path,
            mode: str = "evaluation", *, planner_source: str | Path | None = None,
            band: str | None = None, simulation_seeds: list | None = None,
            sim_binary: str | Path | None = None,
            eval_root: str | Path | None = None) -> PreparedBaseline:
    """Validate, plan once, and write the manifest, snapshots, and effective inputs."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    if mode == "evaluation" and planner_source is not None:
        raise ValueError("planner_source is a standalone option; evaluation uses "
                         "$MESH_SIM_ARPO_PATH or the committed source")
    prep_dir = Path(prep_dir)
    if prep_dir.exists() and (not prep_dir.is_dir() or any(prep_dir.iterdir())):
        raise BaselinePreparationError(f"preparation directory {prep_dir} is not empty")
    prep_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = prep_dir / artifacts.MANIFEST_NAME
    artifacts.write_json(manifest_path, artifacts.new_manifest(
        mode, EXECUTORS[mode], method, None))
    log_path = prep_dir / artifacts.PLANNER_LOG_NAME
    try:
        return _prepare(Path(run_config), method, prep_dir, mode, manifest_path, log_path,
                        planner_source, band, simulation_seeds, sim_binary, eval_root)
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        if log_path.exists():
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"FAILED: {message}\n")
        _record_end(manifest_path, "failed", message)
        raise BaselinePreparationError(message) from exc
    except BaseException:
        _record_end(manifest_path, "interrupted", "interrupted")
        raise


def _record_end(manifest_path: Path, status: str, error: str) -> None:
    if artifacts.read_json(manifest_path).get("status") == "preparing":
        artifacts.set_status(manifest_path, status, error=error)


def _prepare(run_config: Path, method: str | None, prep_dir: Path, mode: str,
             manifest_path: Path, log_path: Path, planner_source, band, simulation_seeds,
             sim_binary, eval_root) -> PreparedBaseline:
    cfg = config.load_baseline(run_config)
    method = _resolve_method(mode, method, cfg)
    config.require_method(cfg, method)
    ini = config.read_ini(cfg.run_config)
    files = effective_inputs.scenario_files(ini, cfg)
    nodes = load_nodes(files.nodes)
    active = method in PLACEMENT_METHODS
    artifacts.update_manifest(
        manifest_path, requested_algorithm=cfg.algorithm, method=method,
        objective=cfg.objective if active else None, application=cfg.application,
        waypoint_policy=cfg.waypoint_policy, source_run_config_abs=str(cfg.run_config),
        simulation_seeds=list(simulation_seeds) if simulation_seeds is not None else None,
        sim_binary_sha256=artifacts.sha256_file(sim_binary) if sim_binary else None,
        mapping_sha256=artifacts.sha256_file(files.mapping) if files.mapping else None,
        rf={"sha256": artifacts.sha256_file(files.rf) if files.rf else None,
            "planner": None, "simulator_channel": _simulator_channel(ini, band)},
        sim_log=artifacts.SIM_LOG_NAME if mode == "standalone" else None,
        **_seed_fields(method, cfg))

    request = records = rf_summary = rl_bounds = None
    if active:
        mapping = config.load_mapping(files.mapping, ini)
        controlled = config.rl_controlled_nodes(ini)
        if mode == "evaluation":
            check_hold_contract(cfg, controlled)
            rl_bounds = config.effective_rl_bounds(ini)
        records = build_records(nodes, cfg, mapping,
                                controlled if mode == "evaluation" else None)
        check_datum(records)
        if cfg.waypoint_policy == "reject":
            for record in records:
                if record.selected and record.mobility == "waypoint":
                    raise ConfigError(f"node '{record.id}' uses waypoint mobility and is "
                                      "selected; set [baseline] waypoint_policy = "
                                      "translate or leave it out of movable_nodes")
        source_dir, origin = _solver().resolve_source_dir(planner_source)
        source = _solver().source_hashes(source_dir, origin)
        rf_summary = _solver().inspect_rf(files.rf, source_dir)
        check_radios(records, rf_summary)
        request = PlanRequest(method=method, objective=cfg.objective, nodes=records,
                              origin_lat=mapping.origin_lat, origin_lon=mapping.origin_lon,
                              rectangle=dict(mapping.rectangle), rf_config=files.rf,
                              planner_seed=cfg.seed if method == "optimization" else None,
                              max_iterations=(cfg.max_iterations
                                              if method == "optimization" else None),
                              source_dir=source_dir)
        manifest = artifacts.read_json(manifest_path)
        manifest["rf"]["planner"] = _rf_planner(records, rf_summary, request)
        artifacts.update_manifest(manifest_path, rf=manifest["rf"], planner_source=source,
                                  origin=mapping.origin, ground_datum=mapping.ground_datum,
                                  geofence=mapping.geofence)

    source_identity = effective_inputs.snapshot_sources(files, prep_dir)
    artifacts.update_manifest(manifest_path, source_scenario_identity=source_identity,
                              source_inputs=effective_inputs.SOURCE_DIR)

    with open(log_path, "w", encoding="utf-8") as log:
        artifacts.update_manifest(manifest_path, planner_log=artifacts.PLANNER_LOG_NAME)
        if not active:
            log.write("method none: no planner was run\n")
            plan_entries, predictions, moved, wall_s = _unplanned_nodes(nodes), None, None, None
        else:
            log.write(f"method={method} objective={cfg.objective} "
                      f"planner_seed={request.planner_seed} "
                      f"max_iterations={request.max_iterations}\n")
            log.flush()
            result = _solver().solve(request, log)
            final = validate_result(records, result, request.rectangle, rf_summary, nodes,
                                    rl_bounds)
            plan_entries = plan_nodes(records, final)
            predictions, wall_s = result.predictions, result.planner_wall_s
            moved = {entry["id"]: (entry["planned"]["x"], entry["planned"]["y"])
                     for entry in plan_entries if entry["displacement_m"] > 0.0}
            log.write(f"planner_wall_s={wall_s:.3f}\n")

    plan = artifacts.build_plan(method, cfg.objective if active else None, plan_entries,
                                predictions)
    rewritten = (effective_inputs.rewrite_nodes(nodes, moved, cfg.waypoint_policy)
                 if moved else None)
    effective_identity = effective_inputs.write_effective_inputs(files, prep_dir, mode,
                                                                 rewritten, plan)
    plan_rel = f"{effective_inputs.EFFECTIVE_DIR}/{artifacts.PLAN_NAME}"
    fields = {
        "effective_scenario_identity": effective_identity,
        "effective_inputs": effective_inputs.EFFECTIVE_DIR,
        "plan": plan_rel,
        "initial_displacement_m_total": plan["initial_displacement_m_total"],
        "planner_wall_s": wall_s,
    }
    root = prep_dir
    if mode == "evaluation":
        root = Path(eval_root) if eval_root is not None else prep_dir.parent.parent
        fields["eval_manifest"] = Path(os.path.relpath(
            root.resolve() / EVAL_MANIFEST_NAME, prep_dir.resolve())).as_posix()
    manifest = artifacts.read_json(manifest_path)
    manifest.update(fields)
    fields["fingerprint"] = artifacts.fingerprint(manifest)
    manifest = artifacts.set_status(manifest_path, "prepared", final=mode == "evaluation",
                                    **fields)
    metadata = artifacts.eval_metadata(
        manifest, artifacts.run_relative(manifest_path, root),
        artifacts.run_relative(prep_dir / plan_rel, root))
    return PreparedBaseline(prep_dir=prep_dir, mode=mode, method=method,
                            manifest_path=manifest_path, plan_path=prep_dir / plan_rel,
                            effective_run_config=(prep_dir / effective_inputs.EFFECTIVE_DIR
                                                  / effective_inputs.RUN_INI),
                            metadata=metadata)
