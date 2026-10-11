"""Coordinate planning, input snapshots, and baseline artifact publication."""

import importlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from scripts.baselines import (
    adapter,
    artifacts,
    config,
    effective_inputs,
    runtime_identity,
    mapping as mapping_config,
)
from scripts.baselines.config import PLACEMENT_METHODS, PLATFORMS, ConfigError

MODES = ("standalone", "evaluation")
EXECUTORS = {"standalone": "none", "evaluation": "hold"}
MODE_FLAGS = {"standalone": None, "evaluation": "--rl-mode"}
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
    return importlib.import_module("scripts.baselines.solver")


def _objective():
    return importlib.import_module("scripts.baselines.planners.objective")


def _area(rect: dict) -> float:
    return (rect["x_max"] - rect["x_min"]) * (rect["y_max"] - rect["y_min"])


def _unplanned_nodes(nodes: list) -> list:
    entries = []
    for index, entry in enumerate(nodes):
        start = effective_inputs.start_position(entry)
        entries.append(
            {
                "id": entry["id"],
                "roster_index": index,
                "slot": None,
                "role": "fixed",
                "platform": None,
                "selected": False,
                "original": adapter._xyz(start),
                "planned": adapter._xyz(start),
                "displacement_m": 0.0,
            }
        )
    return entries


def resolve_band(ini, band: str | None) -> tuple[str, str]:
    """Effective band and its source, in the simulator's order: CLI, run.ini, default."""
    ini_band = config.ini_value(ini, "channel", "band") if ini.has_section("channel") else None
    if band:
        return band, "cli"
    if ini_band:
        return ini_band, "run.ini"
    return DEFAULT_BAND, "default"


def _seed_fields(method: str, cfg: config.BaselineConfig) -> dict:
    if method == "optimization":
        return {"planner_seed": cfg.seed, "planner_seed_status": "used",
                "max_iterations": cfg.max_iterations, "max_iterations_status": "used"}
    return {"planner_seed": None,
            "planner_seed_status": "unused" if method == "geometric" else "not_applicable",
            "max_iterations": None, "max_iterations_status": "not_applicable"}


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


def _require_binary(method: str, sim_binary) -> Path:
    if sim_binary is None:
        raise ConfigError(
            f"method '{method}' needs the simulator binary (sim_binary / "
            "--sim-binary): candidates are scored by its --channel-query mode"
        )
    path = Path(sim_binary)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ConfigError(f"simulator binary {path} is not an executable file")
    return path.resolve()


def prepare(
    run_config: str | Path,
    method: str | None,
    prep_dir: str | Path,
    mode: str = "evaluation",
    *,
    band: str | None = None,
    simulation_seeds: list | None = None,
    sim_binary: str | Path | None = None,
    eval_root: str | Path | None = None,
    planning_seed: int | None = None,
    allow_seed_overlap: bool = False,
) -> PreparedBaseline:
    """Validate, plan once, and write the manifest, snapshots, and effective inputs."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    prep_dir = Path(prep_dir)
    if prep_dir.exists() and (not prep_dir.is_dir() or any(prep_dir.iterdir())):
        raise BaselinePreparationError(f"preparation directory {prep_dir} is not empty")
    prep_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = prep_dir / artifacts.MANIFEST_NAME
    artifacts.write_json(manifest_path, artifacts.new_manifest(mode, EXECUTORS[mode], method, None))
    log_path = prep_dir / artifacts.PLANNER_LOG_NAME
    try:
        return _prepare(
            Path(run_config),
            method,
            prep_dir,
            mode,
            manifest_path,
            log_path,
            band,
            simulation_seeds,
            sim_binary,
            eval_root,
            planning_seed,
            allow_seed_overlap,
        )
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


@dataclass(frozen=True)
class _Setup:
    """Validated planning inputs for an active method, before staging."""

    records: tuple[adapter.NodeRecord, ...]
    rectangle: dict
    rl_bounds: dict | None
    region: dict | None
    penalties: dict
    grid: object
    probe: object
    planning_seed: int
    run_id: int
    aoi_m2: float


def _setup(
    cfg: config.BaselineConfig,
    mode: str,
    ini,
    files,
    nodes: list,
    band: str | None,
    planning_seed: int,
    planning_seed_source: str,
    manifest_path: Path,
) -> _Setup:
    mapping = mapping_config.load_mapping(files.mapping, ini)
    controlled = config.rl_controlled_nodes(ini)
    roster = [entry["id"] for entry in nodes]
    rectangle = dict(mapping.rectangle)
    rl_bounds = region = None
    if mode == "evaluation":
        adapter.check_ownership(cfg, controlled, roster)
        rl_bounds = config.effective_rl_bounds(ini)
        region = adapter.evaluation_region(rectangle, rl_bounds)
    records = adapter.build_records(
        nodes, cfg, mapping, controlled if mode == "evaluation" else None
    )
    adapter.check_datum(records)
    adapter.check_gateway_ownership(ini, records, controlled if mode == "evaluation" else None)
    if cfg.waypoint_policy == "reject":
        for record in records:
            if record.selected and record.mobility == "waypoint":
                raise ConfigError(
                    f"node '{record.id}' uses waypoint mobility and is "
                    "selected; set [baseline] waypoint_policy = "
                    "translate or leave it out of movable_nodes"
                )
    objective = _objective()
    penalties = adapter.resolve_penalties(cfg)
    grid = objective.GridSettings(
        candidate_cells=cfg.candidate_grid_cells,
        coverage_cells=cfg.coverage_grid_cells,
        min_resolution_m=cfg.grid_min_resolution_m,
    )
    probe = objective.ProbeSettings(
        height_m=cfg.coverage_probe_height_m,
        rx_gain_dbi=cfg.coverage_probe_rx_gain_dbi,
        sinr_db=cfg.coverage_sinr_db,
    )
    aoi_m2 = _area(rectangle)
    planning_seed, run_id = config.planning_identity(ini, planning_seed)
    band_value, band_source = resolve_band(ini, band)
    probe_points, probe_cell, _ = objective.rectangle_grid(
        rectangle, cfg.coverage_grid_cells, cfg.grid_min_resolution_m
    )
    candidate_points, candidate_cell, _ = objective.rectangle_grid(
        rectangle, cfg.candidate_grid_cells, cfg.grid_min_resolution_m
    )
    artifacts.update_manifest(
        manifest_path,
        geofence=mapping.geofence,
        penalties=artifacts.penalties_block(penalties, aoi_m2),
        ownership={
            "mode": mode,
            "movable_resolved": adapter.resolve_ids(cfg.movable_nodes, roster),
            "controlled_resolved": (
                adapter._controlled_ids(controlled, roster) if mode == "evaluation" else None
            ),
        },
        channel_scoring={
            "contract": None,
            "isolation": None,
            "planning_seed": planning_seed,
            "planning_seed_source": planning_seed_source,
            "planning_run_id": run_id,
            "jammer_seed": planning_seed,
            "mode_flag": MODE_FLAGS[mode],
            "band": band_value,
            "band_source": band_source,
            "sinr_threshold_db": None,
            "coverage_sinr_db": cfg.coverage_sinr_db,
            "probe": {
                "height_m": cfg.coverage_probe_height_m,
                "rx_gain_dbi": cfg.coverage_probe_rx_gain_dbi,
                "grid_cells": cfg.coverage_grid_cells,
                "min_resolution_m": cfg.grid_min_resolution_m,
                "cell_m": float(probe_cell),
                "count": len(probe_points),
            },
            "candidate_grid": {
                "cells": cfg.candidate_grid_cells,
                "min_resolution_m": cfg.grid_min_resolution_m,
                "cell_m": float(candidate_cell),
                "count": len(candidate_points),
            },
            "queries": None,
        },
        planner_code_sha256=runtime_identity.planner_code_identity()["aggregate_sha256"],
    )
    return _Setup(
        records=records,
        rectangle=rectangle,
        rl_bounds=rl_bounds,
        region=region,
        penalties=penalties,
        grid=grid,
        probe=probe,
        planning_seed=planning_seed,
        run_id=run_id,
        aoi_m2=aoi_m2,
    )


def _log_scale(log, setup: _Setup) -> None:
    log.write(f"aoi_m2={setup.aoi_m2:.1f}\n")
    for platform in PLATFORMS:
        fixed = setup.penalties[platform].fixed_cost_m2
        ratio = fixed / setup.aoi_m2
        log.write(f"{platform} fixed_cost_m2/aoi_m2={ratio:.4f}\n")
        if ratio >= 1.0:
            log.write(
                f"WARNING: {platform}_fixed_cost_m2 {fixed} >= aoi_m2 "
                f"{setup.aoi_m2:.1f}; compare this scale with the resolved objective "
                "weights; connectivity, resilience and separation can still favor movement\n"
            )


def _scoring_result(manifest_path: Path, result) -> None:
    manifest = artifacts.read_json(manifest_path)
    scoring = manifest["channel_scoring"]
    facts = result.channel or {}
    if facts.get("band") is not None and facts["band"] != scoring["band"]:
        raise ValueError(
            f"the channel query resolved band {facts['band']!r}, but this run "
            f"resolves {scoring['band']!r}"
        )
    for key, expected in (
        ("planning_seed", scoring["planning_seed"]),
        ("run_id", scoring["planning_run_id"]),
        ("jammer_seed", scoring["jammer_seed"]),
    ):
        if facts.get(key) is not None and facts[key] != expected:
            raise ValueError(f"query {key} {facts[key]} does not match {expected}")
    scoring["resolved_channel"] = facts.get("channel")
    scoring.update(
        contract=facts.get("contract"),
        isolation=facts.get("isolation"),
        sinr_threshold_db=facts.get("sinr_threshold_db"),
        queries=dict(result.query_stats),
    )
    if facts.get("probe_rx_gain_dbi") is not None:
        scoring["probe"]["rx_gain_dbi"] = facts["probe_rx_gain_dbi"]
    artifacts.update_manifest(
        manifest_path, channel_scoring=scoring, planner_settings=result.planner_settings
    )


def _prepare(
    run_config: Path,
    method: str | None,
    prep_dir: Path,
    mode: str,
    manifest_path: Path,
    log_path: Path,
    band,
    simulation_seeds,
    sim_binary,
    eval_root,
    planning_seed,
    allow_seed_overlap,
) -> PreparedBaseline:
    cfg = config.load_baseline(run_config)
    method = _resolve_method(mode, method, cfg)
    config.require_method(cfg, method)
    ini = config.read_ini(cfg.run_config)
    files = effective_inputs.scenario_files(ini, cfg)
    nodes = adapter.load_nodes(files.nodes)
    active = method in PLACEMENT_METHODS
    planning_source = None
    overlap = []
    if active:
        planning_seed, planning_source = config.resolve_planning_seed(cfg, planning_seed)
        overlap = [seed for seed in simulation_seeds or [] if seed == planning_seed]
        if overlap and not allow_seed_overlap:
            raise ConfigError(
                f"planning seed {planning_seed} overlaps evaluation seeds; "
                "choose a different planning seed or explicitly allow seed overlap"
            )
        sim_binary = _require_binary(method, sim_binary)
    elif planning_seed is not None:
        raise ConfigError("planning_seed is unused when the method is none")
    artifacts.update_manifest(
        manifest_path,
        requested_algorithm=cfg.algorithm,
        method=method,
        objective=cfg.objective if active else None,
        application=cfg.application,
        waypoint_policy=cfg.waypoint_policy,
        source_run_config_abs=str(cfg.run_config),
        simulation_seeds=list(simulation_seeds) if simulation_seeds is not None else None,
        sim_binary_sha256=artifacts.sha256_file(sim_binary) if sim_binary else None,
        mapping_sha256=artifacts.sha256_file(files.mapping) if files.mapping else None,
        sim_log=artifacts.SIM_LOG_NAME if mode == "standalone" else None,
        seed_roles={
            "planning_seed": planning_seed if active else None,
            "planning_seed_source": planning_source,
            "evaluation_seeds": list(simulation_seeds or []),
            "planning_overlap": overlap,
            "overlap_allowed": bool(allow_seed_overlap),
            "held_out_from_planning": not overlap if active else None,
        },
        **_seed_fields(method, cfg),
    )

    setup = None
    if active:
        setup = _setup(
            cfg, mode, ini, files, nodes, band, planning_seed, planning_source, manifest_path
        )
        runtime = runtime_identity.channel_runtime_identity(sim_binary)
        artifacts.update_manifest(
            manifest_path,
            channel_runtime_sha256=runtime["sha256"],
            channel_runtime_files=runtime["files"],
        )

    source_identity = effective_inputs.snapshot_sources(files, prep_dir)
    artifacts.update_manifest(
        manifest_path,
        source_scenario_identity=source_identity,
        source_inputs=effective_inputs.SOURCE_DIR,
    )

    staged_ini = effective_inputs.stage_effective_inputs(files, prep_dir, mode)
    try:
        with open(log_path, "w", encoding="utf-8") as log:
            artifacts.update_manifest(manifest_path, planner_log=artifacts.PLANNER_LOG_NAME)
            if not active:
                log.write("method none: no planner was run\n")
                plan_entries, predictions, moved, wall_s = (
                    _unplanned_nodes(nodes),
                    None,
                    None,
                    None,
                )
            else:
                plan_entries, predictions, moved, wall_s = _plan(
                    cfg, method, mode, band, setup, staged_ini, sim_binary, log, manifest_path
                )
        plan = artifacts.build_plan(
            method, cfg.objective if active else None, plan_entries, predictions
        )
        rewritten = (
            effective_inputs.rewrite_nodes(nodes, moved, cfg.waypoint_policy) if moved else None
        )
        effective_identity = effective_inputs.finish_effective_inputs(
            files, prep_dir, rewritten, plan
        )
    except BaseException:
        effective_inputs.discard_staged_inputs(prep_dir)
        raise
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
        fields["eval_manifest"] = Path(
            os.path.relpath(root.resolve() / EVAL_MANIFEST_NAME, prep_dir.resolve())
        ).as_posix()
    manifest = artifacts.read_json(manifest_path)
    manifest.update(fields)
    fields["fingerprint"] = artifacts.fingerprint(manifest)
    manifest = artifacts.set_status(manifest_path, "prepared", final=mode == "evaluation", **fields)
    metadata = artifacts.eval_metadata(
        manifest,
        artifacts.run_relative(manifest_path, root),
        artifacts.run_relative(prep_dir / plan_rel, root),
    )
    return PreparedBaseline(
        prep_dir=prep_dir,
        mode=mode,
        method=method,
        manifest_path=manifest_path,
        plan_path=prep_dir / plan_rel,
        effective_run_config=(prep_dir / effective_inputs.EFFECTIVE_DIR / effective_inputs.RUN_INI),
        metadata=metadata,
    )


def _plan(
    cfg: config.BaselineConfig,
    method: str,
    mode: str,
    band,
    setup: _Setup,
    staged_ini: Path,
    sim_binary: Path,
    log,
    manifest_path: Path,
) -> tuple:
    solver = _solver()
    request = solver.PlanRequest(
        method=method,
        objective=cfg.objective,
        nodes=setup.records,
        rectangle=setup.rectangle,
        rl_bounds=setup.region,
        mode=mode,
        penalties=setup.penalties,
        grid=setup.grid,
        probe=setup.probe,
        planner_seed=cfg.seed if method == "optimization" else None,
        max_iterations=cfg.max_iterations if method == "optimization" else None,
        balanced_core_fraction=cfg.balanced_core_fraction,
        waypoint_policy=cfg.waypoint_policy,
        planning_seed=setup.planning_seed,
        run_id=setup.run_id,
        band=band,
        query_run_config=staged_ini,
        sim_binary=sim_binary,
    )
    log.write(
        f"method={method} objective={cfg.objective} "
        f"planner_seed={request.planner_seed} max_iterations={request.max_iterations} "
        f"planning_seed={request.planning_seed} run_id={request.run_id} mode={mode}\n"
    )
    if setup.region is not None:
        log.write(f"evaluation_region={json.dumps(setup.region, sort_keys=True)}\n")
    _log_scale(log, setup)
    log.flush()
    result = solver.solve(request, log)
    final = adapter.validate_result(
        setup.records, result, setup.rectangle, setup.penalties, setup.rl_bounds
    )
    _scoring_result(manifest_path, result)
    plan_entries = adapter.plan_nodes(setup.records, final)
    moved = {
        entry["id"]: (entry["planned"]["x"], entry["planned"]["y"])
        for entry in plan_entries
        if entry["displacement_m"] > 0.0
    }
    for note in result.notes:
        log.write(f"note: {note}\n")
    log.write(f"queries={json.dumps(result.query_stats, sort_keys=True)}\n")
    log.write(f"planner_wall_s={result.planner_wall_s:.3f}\n")
    return plan_entries, result.predictions, moved, result.planner_wall_s
