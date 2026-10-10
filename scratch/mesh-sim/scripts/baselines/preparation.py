"""Coordinate node adaptation, planning, source snapshots, and artifact publication."""

import importlib
import os
from dataclasses import dataclass
from pathlib import Path

from scripts.artifact_io import sha256_file
from scripts.baselines import adapter, artifacts, config, effective_inputs, mapping as mapping_config
from scripts.baselines.adapter import NodeRecord, PlanRequest
from scripts.baselines.config import PLACEMENT_METHODS, ConfigError

MODES = ("standalone", "evaluation")
EXECUTORS = {"standalone": "none", "evaluation": "hold"}
DEFAULT_BAND = "mmwave"
EVAL_MANIFEST_NAME = "eval_manifest.json"


class BaselinePreparationError(RuntimeError):
    """Placement preparation failed; the baseline manifest records status failed."""


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


def _unplanned_nodes(nodes: list) -> list:
    entries = []
    for index, entry in enumerate(nodes):
        start = effective_inputs.start_position(entry)
        entries.append({"id": entry["id"], "roster_index": index, "slot": None,
                        "role": None, "platform": None, "radios": [], "selected": False,
                        "original": adapter._xyz(start), "planned": adapter._xyz(start),
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
    nodes = adapter.load_nodes(files.nodes)
    active = method in PLACEMENT_METHODS
    artifacts.update_manifest(
        manifest_path, requested_algorithm=cfg.algorithm, method=method,
        objective=cfg.objective if active else None, application=cfg.application,
        waypoint_policy=cfg.waypoint_policy, source_run_config_abs=str(cfg.run_config),
        simulation_seeds=list(simulation_seeds) if simulation_seeds is not None else None,
        sim_binary_sha256=sha256_file(sim_binary) if sim_binary else None,
        mapping_sha256=sha256_file(files.mapping) if files.mapping else None,
        rf={"sha256": sha256_file(files.rf) if files.rf else None,
            "planner": None, "simulator_channel": _simulator_channel(ini, band)},
        sim_log=artifacts.SIM_LOG_NAME if mode == "standalone" else None,
        **_seed_fields(method, cfg))

    request = records = rf_summary = rl_bounds = None
    if active:
        mapping = mapping_config.load_mapping(files.mapping, ini)
        controlled = config.rl_controlled_nodes(ini)
        if mode == "evaluation":
            adapter.check_hold_contract(cfg, controlled)
            rl_bounds = config.effective_rl_bounds(ini)
        records = adapter.build_records(nodes, cfg, mapping,
                                controlled if mode == "evaluation" else None)
        adapter.check_gateway_ownership(ini, records,
                                        controlled if mode == "evaluation" else None)
        adapter.check_datum(records)
        if cfg.waypoint_policy == "reject":
            for record in records:
                if record.selected and record.mobility == "waypoint":
                    raise ConfigError(f"node '{record.id}' uses waypoint mobility and is "
                                      "selected; set [baseline] waypoint_policy = "
                                      "translate or leave it out of movable_nodes")
        source_dir, origin = _solver().resolve_source_dir(planner_source)
        source = _solver().source_hashes(source_dir, origin)
        rf_summary = _solver().inspect_rf(files.rf, source_dir)
        adapter.check_radios(records, rf_summary)
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
            final = adapter.validate_result(records, result, request.rectangle, rf_summary, nodes,
                                    rl_bounds)
            plan_entries = adapter.plan_nodes(records, final)
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
