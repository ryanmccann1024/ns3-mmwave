"""Planner parameter identity, bounded work, and owned extension contracts."""

import io
import json
import math
from dataclasses import fields, replace
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.artifact_io import canonical_sha256
from scripts.baselines import planner_config, solver
from scripts.baselines.planners import geometric, objective, optimization
from scripts.baselines.planners.cache import LayoutCache
from scripts.baselines.planners.channel import ChannelScorer, QuerySettings, PlannerError
from scripts.baselines.planners.components import SCORE_COMPONENTS, ScoreComponent
from scripts.baselines.planners.objective import ObjectiveSettings, ObjectivePreset
from scripts.baselines.planners.optimization import OptimizerSettings
from scripts.baselines.tests.test_channel import env, _scorer, STARTS
from scripts.baselines.tests.test_objective import (
    entry,
    make_request,
    planning_scorer,
    StubScorer,
    table,
    prepare_scorer,
)

NODES = [entry("A", 50, 50, 10), entry("B", 100, 50, 10)]


def context(settings, name="coverage"):
    request = make_request(NODES, {"A", "B"}, objective=name)
    request.objective_settings = settings
    scorer = StubScorer()
    prepare_scorer(request, scorer)
    return objective.ScoringContext.build(request, scorer)


@pytest.mark.parametrize(
    "settings",
    [
        {"coverage_weight": -1},
        {"separation_frac": True},
        {"disconnected_aoi_factor": math.nan},
        {"vulnerability_aoi_factor": math.inf},
        {"component_parameters": []},
        {"component_parameters": {"unknown": {}}},
        {"component_parameters": {"coverage": {"unknown": 1}}},
        {"component_parameters": {"coverage": {"coverage_weight": False}}},
    ],
)
def test_objective_rejects_bad_parameters(settings):
    with pytest.raises(ValueError):
        ObjectiveSettings(**settings)


def test_resolved_component_parameters_drive_actual_score():
    ctx = context(
        ObjectiveSettings(
            separation_frac=0,
            coverage_weight=1,
            component_parameters={"coverage": {"coverage_weight": 2}},
        )
    )
    result = table(2, [(0, 1)], [list(range(len(ctx.coverage_points))), []])
    value = objective.score(ctx, result, ctx.starts)
    assert value.total == pytest.approx(2 * ctx.aoi_m2)
    assert value.components["coverage"] == pytest.approx(2 * ctx.aoi_m2)
    assert ctx.settings["coverage_weight"] == 2
    assert ctx.settings["component_parameters"]["coverage"]["coverage_weight"] == 2


def test_new_objective_and_component_use_registry_without_composer_edits(monkeypatch):
    component = ScoreComponent(
        lambda ctx, facts, p: facts["result"].capacity_mbps[0, 1] * p["scale"],
        defaults={"scale": 2},
        version=3,
    )
    monkeypatch.setitem(SCORE_COMPONENTS, "capacity", component)
    monkeypatch.setitem(
        objective.OBJECTIVE_PRESETS,
        "capacity_only",
        ObjectivePreset(0, lambda n, f: [0] * n, ("capacity",)),
    )
    ctx = context(
        ObjectiveSettings(component_parameters={"capacity": {"scale": 4}}), "capacity_only"
    )
    result = table(2, [(0, 1)], [[], []])
    result.capacity_mbps[0, 1] = 5
    assert objective.score(ctx, result, ctx.starts).total == 20
    assert geometric.needs("capacity_only", 2, 0.5) == [0, 0]
    with pytest.raises(ValueError, match="does not use"):
        ObjectiveSettings(component_parameters={"coverage": {}}).resolved("capacity_only")


@pytest.mark.parametrize(
    "settings",
    [
        {"t0_area_frac": 0},
        {"tf_area_frac": 1},
        {"nudge_sigma_frac": math.inf},
        {"sigma_final_ratio": 2},
        {"cap_pullback": -1},
        {"warm_start": "unknown"},
        {"move_weights": {"nudge": 0, "teleport": 0, "swap": 0}},
        {"move_weights": {"nudge": 1, "teleport": True, "swap": 0}},
        {"move_weights": {"nudge": 1e308, "teleport": 1e308, "swap": 1e308}},
    ],
)
def test_optimizer_rejects_bad_parameters(settings):
    with pytest.raises(ValueError):
        OptimizerSettings(**settings)


@pytest.mark.parametrize(
    "settings",
    [
        {"request_timeout_s": math.nan},
        {"init_timeout_s": math.inf},
        {"max_layouts": False},
        {"cache_bytes": -1},
        {"response_budget_bytes": 0},
    ],
)
def test_query_rejects_bad_parameters(settings):
    with pytest.raises(ValueError):
        QuerySettings(**settings)


def test_ini_resolution_and_unknown_fields(tmp_path):
    path = tmp_path / "run.ini"
    path.write_text(
        "[placement_objective]\ncoverage_weight = 2\n"
        'component_parameters = {"connectivity":{"disconnected_aoi_factor":4}}\n'
        "[placement_optimizer]\nwarm_start = current\n"
        'move_weights = {"nudge":1,"teleport":0,"swap":0}\n'
        "[channel_query_client]\nmax_layouts = 2\ncache_bytes = 0\n"
    )
    score, optimizer, query = planner_config.load_settings(path)
    assert score.resolved("balanced")["disconnected_aoi_factor"] == 4
    assert optimizer.warm_start == "current" and optimizer.move_weights["nudge"] == 1
    assert query.max_layouts == 2 and query.cache_bytes == 0
    path.write_text("[placement_optimizer]\nmisspelled = 2\n")
    with pytest.raises(ValueError, match="unknown"):
        planner_config.load_settings(path)


def test_cache_budget_and_eviction_preserve_batch_hits():
    a = np.array([[1.0, 1.0, 1.0], [2.0, 2.0, 2.0]])
    b = a + 1
    result_a, result_b = table(2, [], [[], []]), table(2, [(0, 1)], [[], []])
    scorer = StubScorer({a.tobytes(): result_a, b.tobytes(): result_b})
    size = LayoutCache._size(a.tobytes(), result_a)
    cache = LayoutCache(scorer, size)
    assert cache.evaluate([a]) == [result_a]
    assert cache.evaluate([b, a]) == [result_b, result_a]
    assert cache.bytes_used <= cache.max_bytes
    assert len(cache._results) == 1
    uncached = LayoutCache(scorer, 0)
    assert uncached.evaluate([a, b]) == [result_a, result_b]
    assert uncached.bytes_used == 0


def test_cache_consumes_candidates_in_bounded_chunks():
    class Scorer:
        max_layouts = 2

        def __init__(self):
            self.counts = []

        def evaluate(self, layouts):
            rows = list(layouts)
            self.counts.append(len(rows))
            return [table(2, [], [[], []]) for _ in rows]

    produced = []

    def layouts():
        for k in range(101):
            produced.append(k)
            yield np.full((2, 3), k, dtype=float)

    scorer = Scorer()
    cache = LayoutCache(scorer, 0)
    results = cache.iter_evaluate(layouts())
    next(results)
    assert len(produced) == 2
    assert len(list(results)) == 100
    assert max(scorer.counts) == 2 and cache.bytes_used == 0


def test_channel_streams_and_uses_serial_worker_deadlines(env, monkeypatch):
    monkeypatch.setenv(
        "FAKE_QUERY_INIT_PATCH",
        json.dumps({"limits": {"child_deadline_s": 12.0, "terminate_grace_s": 2.0}}),
    )
    produced, deadlines = [], []
    with _scorer(env, max_layouts=2, request_margin_s=3) as scorer:
        original = scorer._read_line
        import time

        def capture(deadline, limit, what):
            deadlines.append(deadline - time.monotonic())
            return original(deadline, limit, what)

        scorer._read_line = capture

        def layouts():
            for k in range(10):
                produced.append(k)
                yield STARTS

        results = scorer.iter_evaluate(layouts())
        next(results)
        assert len(produced) == 2
        assert 30 < deadlines[0] <= 31
        assert len(list(results)) == 9


def test_response_budget_controls_batch_limit(env, monkeypatch):
    monkeypatch.setenv(
        "FAKE_QUERY_INIT_PATCH",
        json.dumps({"limits": {"max_child_response_bytes": 1024, "max_response_bytes": 80000}}),
    )
    with _scorer(env, max_layouts=32, response_budget_bytes=80000) as scorer:
        assert scorer.max_layouts == 2
    with pytest.raises(PlannerError, match="one maximum child"):
        _scorer(env, response_budget_bytes=1024)


def test_grid_resource_guard_precedes_allocation():
    with pytest.raises(PlannerError, match="grid requires"):
        objective.rectangle_grid({"x_min": 0, "x_max": 1e9, "y_min": 0, "y_max": 1}, 100, 0.001)


def test_optimizer_current_warm_start_has_honest_provenance(tmp_path, monkeypatch):
    request = make_request(NODES, {"A"}, max_iterations=3, method="optimization")
    request.optimizer_settings = OptimizerSettings(warm_start="current")
    with planning_scorer(tmp_path, monkeypatch, NODES, request) as (scorer, log):
        _, report, _ = optimization.solve(request, scorer, log)
    assert report["optimization"]["seed_layout"] == "current"
    assert report["optimization"]["geometric_total"] is None
    assert "geometric" not in report


def test_engine_records_resolved_settings_hash_and_explicit_precedence(tmp_path, monkeypatch):
    request = make_request(NODES, {"A"})
    with planning_scorer(tmp_path, monkeypatch, NODES, request):
        monkeypatch.setenv(
            "FAKE_QUERY_DIAGNOSTICS", json.dumps(["height outside model assumptions"])
        )
        path = tmp_path / "scenario" / "run.ini"
        path.write_text(
            path.read_text() + "\n[placement_objective]\ncoverage_weight = 2\n"
            "[channel_query_client]\nmax_layouts = 2\ncache_bytes = 0\n"
        )
        values = {
            field.name: getattr(request, field.name)
            for field in fields(solver.PlanRequest)
            if hasattr(request, field.name)
        }
        values.update(
            planning_seed=5,
            run_id=1,
            band=None,
            query_run_config=path,
            sim_binary=tmp_path / "bin" / "fake-mesh-sim",
        )
        values["nodes"] = tuple(
            solver.PlannerNode(
                id=node.id,
                roster_index=node.roster_index,
                mobility=node.mobility,
                platform=node.platform,
                x=node.x,
                y=node.y,
                z=node.z,
                role=node.role,
                random_walk_bounds=node.random_walk_bounds,
            )
            for node in request.nodes
        )
        plan_request = solver.PlanRequest(**values)
        first = solver.solve(plan_request, io.StringIO())
        changed_costs = {
            "aerial": objective.MovementCost(100, 1),
            "ground": objective.MovementCost(0, 0),
        }
        third = solver.solve(replace(plan_request, penalties=changed_costs), io.StringIO())
        second = solver.solve(
            replace(plan_request, objective_settings=ObjectiveSettings(coverage_weight=3)),
            io.StringIO(),
        )
    for result in (first, second, third):
        assert result.predictions["channel_diagnostics"] == ["height outside model assumptions"]
        settings = dict(result.planner_settings)
        digest = settings.pop("sha256")
        assert digest == canonical_sha256(settings)
        assert settings["query_client"]["cache_bytes"] == 0
        assert settings["objective_components"]["coverage"]["version"] == 1
    assert first.planner_settings["objective_settings"]["coverage_weight"] == 2
    assert second.planner_settings["objective_settings"]["coverage_weight"] == 3
    assert first.planner_settings["sha256"] != second.planner_settings["sha256"]
    assert first.planner_settings["sha256"] != third.planner_settings["sha256"]
    assert first.planner_settings["probe"]["rx_gain_dbi"] == 0


def test_bad_objective_configuration_fails_before_worker_launch(tmp_path, monkeypatch):
    path = tmp_path / "run.ini"
    path.write_text("[placement_objective]\ncoverage_weight = nan\n")
    request = make_request(NODES, {"A"})
    values = {
        field.name: getattr(request, field.name)
        for field in fields(solver.PlanRequest)
        if hasattr(request, field.name)
    }
    values.update(planning_seed=5, run_id=1, band=None, query_run_config=path, sim_binary=path)
    monkeypatch.setattr(
        solver, "ChannelScorer", lambda *args, **kwargs: pytest.fail("worker launched")
    )
    with pytest.raises(ValueError, match="finite"):
        solver.solve(solver.PlanRequest(**values), io.StringIO())


def test_strategy_registry_accepts_additional_optimizers(monkeypatch):
    strategy = SimpleNamespace(solve=lambda *args: None, settings=lambda request: {})
    monkeypatch.setitem(solver.STRATEGIES, "custom", strategy)
    assert solver._strategy("custom") is strategy


def test_active_gateway_rejected_before_worker_launch(tmp_path, monkeypatch):
    path = tmp_path / "run.ini"
    path.write_text("[traffic]\nflow_topology = gateway\ngateway_node_id = A\n")
    request = make_request(NODES, {"A"})
    values = {
        field.name: getattr(request, field.name)
        for field in fields(solver.PlanRequest)
        if hasattr(request, field.name)
    }
    values["nodes"] = tuple(
        solver.PlannerNode(
            node.id,
            node.roster_index,
            node.mobility,
            node.platform,
            node.x,
            node.y,
            node.z,
            node.role,
        )
        for node in request.nodes
    )
    values.update(planning_seed=5, run_id=1, band=None, query_run_config=path, sim_binary=path)
    monkeypatch.setattr(solver, "ChannelScorer", lambda *a, **kw: pytest.fail("worker launched"))
    with pytest.raises(ValueError, match="gateway.*cannot be baseline-movable"):
        solver.solve(solver.PlanRequest(**values), io.StringIO())


def test_worker_settings_are_advertised_from_ini(env):
    env["ini"].write_text(
        env["ini"].read_text()
        + "\n[channel_query]\nchild_deadline_s = 9\nterminate_grace_s = 0.5\nmax_child_response_bytes = 1024\nmax_response_bytes = 80000\n"
    )
    with _scorer(env) as scorer:
        assert scorer.limits["child_deadline_s"] == 9
        assert scorer.limits["terminate_grace_s"] == 0.5
        assert scorer.max_layouts == 2


@pytest.mark.parametrize("values", [(-1, 0), (0, True), (math.inf, 0)])
def test_movement_costs_validate_with_their_owner(values):
    with pytest.raises(ValueError):
        objective.MovementCost(*values)
