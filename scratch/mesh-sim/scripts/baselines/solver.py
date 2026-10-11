"""Run one gateway-free placement planner with a channel-query scorer and package its result."""

import importlib
import time
from dataclasses import dataclass, field, replace, asdict
from pathlib import Path
from typing import TextIO

from scripts.baselines.config import PLACEMENT_METHODS
from scripts.baselines import planner_config, adapter, config
from scripts.artifact_io import canonical_sha256
from scripts.baselines.planners.channel import ChannelScorer, PlannerError

__all__ = ["PlannerNode", "PlanRequest", "PlanResult", "PlannerError", "solve"]

POSITION_AXES = 3
STRATEGIES = {name: f"scripts.baselines.planners.{name}" for name in PLACEMENT_METHODS}


@dataclass(frozen=True)
class PlannerNode:
    """Roster-ordered physical inputs for the query engine, independent of RF mapping."""

    id: str
    roster_index: int
    mobility: str
    platform: str
    x: float
    y: float
    z: float
    role: str = "fixed"
    random_walk_bounds: dict | None = None

    @property
    def selected(self):
        return self.role == "movable"


@dataclass(frozen=True)
class PlanRequest:
    """Everything a planner needs in scenario metres; nodes are PlannerNodes in roster order."""

    method: str
    objective: str
    nodes: tuple[PlannerNode, ...]
    rectangle: dict
    rl_bounds: dict | None
    mode: str
    penalties: dict
    grid: object
    probe: object
    planner_seed: int | None
    max_iterations: int | None
    balanced_core_fraction: float
    waypoint_policy: str
    planning_seed: int
    run_id: int
    band: str | None
    query_run_config: Path
    sim_binary: Path
    objective_settings: planner_config.ObjectiveSettings | None = None
    optimizer_settings: planner_config.OptimizerSettings | None = None
    query_settings: planner_config.QuerySettings | None = None
    cache_bytes: int = 32 * 1024 * 1024


@dataclass(frozen=True)
class PlanResult:
    """Planner output: node id -> (x, y, z), diagnostics, query statistics and channel facts."""

    positions: dict
    predictions: dict | None = None
    planner_wall_s: float = 0.0
    query_stats: dict = field(default_factory=dict)
    planner_settings: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    channel: dict = field(default_factory=dict)


def _strategy(method: str):
    if method not in STRATEGIES:
        raise PlannerError(f"unknown placement method {method!r}; expected {tuple(STRATEGIES)}")
    strategy = STRATEGIES[method]
    strategy = importlib.import_module(strategy) if isinstance(strategy, str) else strategy
    if not callable(getattr(strategy, "solve", None)) or not callable(
        getattr(strategy, "settings", None)
    ):
        raise PlannerError("a placement strategy must provide solve and settings")
    return strategy


def _objective():
    return importlib.import_module("scripts.baselines.planners.objective")


def _channel_facts(scorer: ChannelScorer) -> dict:
    init = scorer.init
    return {
        "contract": init.get("contract"),
        "isolation": init.get("isolation"),
        "band": init.get("band"),
        "band_source": init.get("band_source"),
        "seed": init.get("seed"),
        "run_id": init.get("run_id"),
        "jammer_seed": init.get("jammer_seed"),
        "sinr_threshold_db": init.get("sinr_threshold_db"),
        "probe_rx_gain_dbi": scorer.probe_rx_gain_dbi,
        "channel": scorer.channel,
    }


def _positions(request: PlanRequest, raw) -> dict:
    rows = [list(map(float, row)) for row in raw]
    if len(rows) != len(request.nodes) or any(len(row) != POSITION_AXES for row in rows):
        raise PlannerError(
            f"{request.method} planner returned {len(rows)} positions for "
            f"{len(request.nodes)} nodes"
        )
    return {record.id: tuple(row) for record, row in zip(request.nodes, rows)}


def solve(request: PlanRequest, log: TextIO) -> PlanResult:
    """Score candidates through one channel-query worker and return the planned layout."""
    adapter.check_gateway_ownership(config.read_ini(request.query_run_config), request.nodes, None)
    configured = planner_config.load_settings(request.query_run_config)
    request = replace(
        request,
        objective_settings=request.objective_settings or configured[0],
        optimizer_settings=request.optimizer_settings or configured[1],
        query_settings=request.query_settings or configured[2],
    )
    request = replace(request, cache_bytes=request.query_settings.cache_bytes)
    strategy = _strategy(request.method)
    objective = _objective()
    request.objective_settings.resolved(request.objective)
    if callable(getattr(strategy, "validate_request", None)):
        strategy.validate_request(request)
    started = time.perf_counter()
    with ChannelScorer(
        request.sim_binary,
        request.query_run_config,
        request.planning_seed,
        request.run_id,
        request.band,
        request.mode,
        [record.id for record in request.nodes],
        [(record.x, record.y, record.z) for record in request.nodes],
        jammer_seed=request.planning_seed,
        log=log,
        **{k: v for k, v in asdict(request.query_settings).items() if k != "cache_bytes"},
    ) as scorer:
        objective.prepare_scorer(request, scorer)
        raw, diagnostics, notes = strategy.solve(request, scorer, log)
        stats = scorer.stats
        channel = _channel_facts(scorer)
    wall_s = time.perf_counter() - started
    settings = {
        **strategy.settings(request),
        "engine_settings_version": 1,
        "objective": request.objective,
        "objective_settings": request.objective_settings.resolved(request.objective),
        "query_client": asdict(request.query_settings),
        "grid": asdict(request.grid),
        "probe": {**asdict(request.probe), "rx_gain_dbi": scorer.probe_rx_gain_dbi},
        "movement_costs": {platform: asdict(cost) for platform, cost in request.penalties.items()},
        "rectangle": dict(request.rectangle),
        "rl_bounds": (
            dict(request.rl_bounds) if request.mode == "evaluation" and request.rl_bounds else None
        ),
        "mode": request.mode,
        "worker_limits": scorer.limits,
        "objective_components": {
            name: {
                "unit": objective.SCORE_COMPONENTS[name].unit,
                "parameter": objective.SCORE_COMPONENTS[name].parameter,
                "version": objective.SCORE_COMPONENTS[name].version,
            }
            for name in objective.objective_preset(request.objective).components
        },
    }
    settings["sha256"] = canonical_sha256(settings)
    return PlanResult(
        positions=_positions(request, raw),
        predictions=diagnostics,
        planner_wall_s=wall_s,
        query_stats=stats,
        planner_settings=settings,
        notes=list(notes),
        channel=channel,
    )
