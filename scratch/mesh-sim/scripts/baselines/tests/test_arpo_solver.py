"""Planner loader, projection, and solver runs against the committed planner source."""

import dataclasses
import hashlib
import io
import math
import re
import shutil
import sys
import types
from pathlib import Path

import pytest

from scripts.baselines import adapter, arpo_solver, artifacts, config
from scripts.baselines.adapter import BaselinePreparationError, PlanRequest
from scripts.baselines.arpo_solver import PlannerError
from scripts.baselines.tests.conftest import AREA, MAPPING, NODES, RF_YAML, write_scenario

SOURCE = arpo_solver.default_source_dir()
PROVENANCE = SOURCE / "PROVENANCE.md"


@pytest.fixture(autouse=True)
def committed_source(monkeypatch):
    monkeypatch.delenv(arpo_solver.SOURCE_ENV, raising=False)


def _provenance_hashes() -> dict:
    rows = re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", PROVENANCE.read_text(),
                      flags=re.MULTILINE)
    return dict(rows)


def _planner():
    return arpo_solver.load_planner(SOURCE)


def _request(tmp_path, method="geometric", objective="coverage", seed=None,
             iterations=None, overrides=None) -> PlanRequest:
    ini = write_scenario(tmp_path / "scenario", overrides=overrides)
    cfg = config.load_baseline(ini)
    mapping = config.load_mapping(cfg.mapping_file, config.read_ini(ini))
    records = adapter.build_records(adapter.load_nodes(ini.parent / "nodes.json"), cfg,
                                    mapping)
    return PlanRequest(method=method, objective=objective, nodes=records,
                       origin_lat=mapping.origin_lat, origin_lon=mapping.origin_lon,
                       rectangle=dict(mapping.rectangle), rf_config=cfg.rf_config,
                       planner_seed=seed, max_iterations=iterations, source_dir=SOURCE)


def _solve(request):
    return arpo_solver.solve(request, io.StringIO())


def test_committed_files_match_provenance():
    recorded = _provenance_hashes()
    assert tuple(recorded) == arpo_solver.ALLOWLIST
    for name, digest in recorded.items():
        assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == digest, name
    assert arpo_solver.source_hashes(SOURCE)["files"] == recorded
    present = sorted(p.relative_to(SOURCE).as_posix() for p in SOURCE.rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts)
    assert present == sorted([*arpo_solver.ALLOWLIST, "PROVENANCE.md"])


def test_resolve_source_precedence(tmp_path, monkeypatch):
    assert arpo_solver.resolve_source_dir() == (SOURCE, "default")
    monkeypatch.setenv(arpo_solver.SOURCE_ENV, str(tmp_path / "env"))
    assert arpo_solver.resolve_source_dir() == ((tmp_path / "env").resolve(),
                                                arpo_solver.SOURCE_ENV)
    assert arpo_solver.resolve_source_dir(tmp_path / "cli") == (
        (tmp_path / "cli").resolve(), "planner_source")


def test_missing_allowlisted_file(tmp_path, monkeypatch):
    partial = tmp_path / "partial"
    for name in arpo_solver.ALLOWLIST[:-1]:
        (partial / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / name, partial / name)
    monkeypatch.setenv(arpo_solver.SOURCE_ENV, str(partial))
    directory, origin = arpo_solver.resolve_source_dir()
    with pytest.raises(PlannerError, match="MESH_SIM_ARPO_PATH.*planners/optimization.py"):
        arpo_solver.source_hashes(directory, origin)
    with pytest.raises(PlannerError, match="planners/optimization.py"):
        arpo_solver.load_planner(partial)


def test_loader_refuses_module_name_collision(tmp_path, monkeypatch):
    _planner()
    copy = tmp_path / "copy"
    for name in arpo_solver.ALLOWLIST:
        (copy / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / name, copy / name)
    with pytest.raises(PlannerError, match="already imported"):
        arpo_solver.load_planner(copy)
    impostor = types.ModuleType("models")
    impostor.__file__ = str(tmp_path / "models.py")
    monkeypatch.setitem(sys.modules, "models", impostor)
    with pytest.raises(PlannerError, match="module 'models' is already imported"):
        arpo_solver.load_planner(SOURCE)


def test_loader_restores_path_and_writes_no_bytecode():
    before = list(sys.path)
    planner = _planner()
    assert sys.path == before
    assert Path(planner.models.__file__).resolve() == (SOURCE / "models.py").resolve()
    assert not list(SOURCE.rglob("__pycache__"))


def test_missing_dependency_names_package(monkeypatch):
    real = arpo_solver.importlib.util.find_spec
    monkeypatch.setattr(arpo_solver.importlib.util, "find_spec",
                        lambda name, *a: None if name == "pyproj" else real(name, *a))
    with pytest.raises(PlannerError, match="pyproj.*requirements-baselines.txt"):
        arpo_solver.check_dependencies()


def test_projection_round_trip():
    planner = _planner()
    frame = arpo_solver.local_frame(planner, MAPPING["origin"]["lat"],
                                    MAPPING["origin"]["lon"])
    other = planner.geometry.LocalFrame(center_lat=10.0018, center_lon=20.0018)
    worst = 0.0
    for x in (-1500.0, -200.0, 0.0, 137.5, 400.0, 2500.0):
        for y in (-1000.0, 0.0, 263.25, 400.0, 1800.0):
            lat, lon = frame.to_latlon(x, y)
            back = frame.to_xy(lat, lon)
            worst = max(worst, math.hypot(back[0] - x, back[1] - y))
            ox, oy = other.to_xy(lat, lon)
            lat2, lon2 = other.to_latlon(ox, oy)
            via = frame.to_xy(lat2, lon2)
            worst = max(worst, math.hypot(via[0] - x, via[1] - y))
    for lat in (9.99, 10.0, 10.003):
        for lon in (19.99, 20.0, 20.004):
            x, y = frame.to_xy(lat, lon)
            lat2, lon2 = frame.to_latlon(x, y)
            x2, y2 = frame.to_xy(lat2, lon2)
            worst = max(worst, math.hypot(x2 - x, y2 - y))
    assert worst <= adapter.ROUND_TRIP_TOL_M


def test_inspect_rf_reads_synthetic_file(tmp_path):
    rf = tmp_path / "rf.yaml"
    rf.write_text(RF_YAML)
    summary = arpo_solver.inspect_rf(rf, SOURCE)
    assert summary["radios"]["satlink"]["blos"] is True
    assert summary["radios"]["meshradio"]["frequency_hz"] == pytest.approx(5.8e9)
    assert summary["movement_cost"]["aerial"]["max_displacement_m"] == 500.0
    assert summary["reference_receiver"]["radio_type"] == "meshradio"


def test_run_rf_config_never_mutates_loaded(tmp_path):
    rf = tmp_path / "rf.yaml"
    rf.write_text(RF_YAML.replace("  budget_s_per_coa: 1.0\n",
                                  "  budget_s_per_coa: 1.0\n  seed: 99\n"))
    loaded = _planner().rf.RFConfig.load(rf)
    snapshot = dataclasses.asdict(loaded)
    per_run = arpo_solver.run_rf_config(loaded, 5, 40)
    assert dataclasses.asdict(loaded) == snapshot
    assert (per_run.terrain_elevation_m, per_run.optimizer.seed,
            per_run.optimizer.max_iters) == (0.0, 5, 40)
    assert per_run.optimizer.budget_s_per_coa == loaded.optimizer.budget_s_per_coa


def _valid(request, result):
    summary = arpo_solver.inspect_rf(request.rf_config, SOURCE)
    return adapter.validate_result(request.nodes, result, request.rectangle, summary, NODES,
                                   dict(AREA))


@pytest.mark.parametrize("objective", ["coverage", "balanced", "resilience"])
def test_geometric_is_deterministic_and_valid(tmp_path, objective):
    request = _request(tmp_path, objective=objective)
    first, second = _solve(request), _solve(request)
    assert first.positions == second.positions
    final = _valid(request, first)
    assert set(final) == {r.id for r in request.nodes}
    assert first.predictions["coverage_fraction"] is not None


def test_optimization_determinism_and_seeds(tmp_path):
    request = _request(tmp_path, "optimization", "balanced", seed=3, iterations=80)
    first, second = _solve(request), _solve(request)
    assert first.positions == second.positions
    assert "sa iters=80" in first.predictions["notes"]
    _valid(request, first)
    other = _solve(dataclasses.replace(request, planner_seed=4))
    _valid(request, other)


def test_parity_with_direct_planner_call(tmp_path):
    planner = _planner()
    for method, seed, iterations in (("geometric", None, None), ("optimization", 2, 50)):
        request = _request(tmp_path / method, method, "resilience", seed, iterations)
        frame = arpo_solver.local_frame(planner, request.origin_lat, request.origin_lon)
        loaded = planner.rf.RFConfig.load(request.rf_config)
        context = planner.context.PlanningContext(
            arpo_solver.build_input(planner, frame, request),
            arpo_solver.run_rf_config(loaded, seed, iterations))
        model = (planner.geometric.GeometricModel() if method == "geometric"
                 else planner.optimization.OptimizationModel())
        placements = model.to_placements(context, model.solve(context, "resilience"))
        direct = {}
        for node_id, placement in placements.items():
            x, y = frame.to_xy(placement.lat, placement.lon)
            direct[node_id] = (float(x), float(y), float(placement.elevation_m))
        assert _solve(request).positions == direct


def test_unselected_nodes_round_trip_within_tolerance(tmp_path):
    request = _request(tmp_path, objective="coverage")
    result = _solve(request)
    for record in request.nodes:
        if not record.selected:
            x, y, z = result.positions[record.id]
            assert math.hypot(x - record.x, y - record.y) <= adapter.ROUND_TRIP_TOL_M
            assert abs(z - record.z) <= adapter.Z_TOL_M


@pytest.mark.parametrize("method", ["geometric", "optimization"])
@pytest.mark.parametrize("mode", ["standalone", "evaluation"])
def test_prepare_with_real_planner(tmp_path, method, mode):
    ini = write_scenario(tmp_path / "scenario", overrides={"objective": "resilience"})
    prepared = adapter.prepare(ini, method, tmp_path / "out" / method / "baseline", mode=mode)
    manifest = artifacts.read_json(prepared.manifest_path)
    assert manifest["status"] == "prepared"
    assert manifest["planner_source"]["files"] == _provenance_hashes()
    assert manifest["planner_wall_s"] >= 0.0
    assert manifest["rf"]["sha256"] == artifacts.sha256_file(ini.parent / "rf.yaml")
    assert manifest["package_versions"]["pyproj"] is not None
    plan = artifacts.read_json(prepared.plan_path)
    for node in plan["nodes"]:
        assert node["planned"]["z"] == node["original"]["z"]
        if node["selected"]:
            assert AREA["x_min"] <= node["planned"]["x"] <= AREA["x_max"]
            assert AREA["y_min"] <= node["planned"]["y"] <= AREA["y_max"]
        else:
            assert node["planned"] == node["original"]
    assert plan["planner_predictions"]["connected_node_ids"]
    log = (prepared.prep_dir / "planner.log").read_text()
    assert log.startswith(f"method={method} objective=resilience")


def test_blos_radio_rejected_with_real_rf(tmp_path):
    mapping = dict(MAPPING, radios={"default": ["meshradio"], "nodes": {"gw": ["satlink"]}})
    ini = write_scenario(tmp_path / "scenario", mapping=mapping)
    with pytest.raises(BaselinePreparationError, match="'satlink', marked blos"):
        adapter.prepare(ini, "geometric", tmp_path / "run", mode="standalone")
