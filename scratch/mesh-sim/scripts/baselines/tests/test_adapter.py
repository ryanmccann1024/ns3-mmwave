"""Node mapping, result validation, prepare() lifecycle, and the import boundary."""

import copy
import json
import math
import subprocess
import sys
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.baselines import adapter, artifacts, config
from scripts.baselines.adapter import BaselinePreparationError, PlanResult
from scripts.baselines.config import ConfigError
from scripts.baselines.tests.conftest import (AREA, MAPPING, NODES, STUB_RF_SUMMARY,
                                              scenario_ini, stub_positions, write_scenario)

MESH_ROOT = Path(__file__).resolve().parents[3]


def _records(tmp_path, overrides=None, mapping=None, nodes=None, controlled=None):
    ini = write_scenario(tmp_path / "s", overrides=overrides, mapping=mapping, nodes=nodes)
    cfg = config.load_baseline(ini)
    parsed = config.read_ini(ini)
    loaded_mapping = config.load_mapping(cfg.mapping_file, parsed)
    loaded_nodes = adapter.load_nodes(ini.parent / "nodes.json")
    return adapter.build_records(loaded_nodes, cfg, loaded_mapping, controlled), loaded_nodes


def _by_id(records):
    return {record.id: record for record in records}


def test_role_and_platform_mapping(tmp_path):
    records, _ = _records(tmp_path)
    by_id = _by_id(records)
    assert [(r.id, r.role, r.platform, r.platform_source) for r in records] == [
        ("gw", "gateway", "ground", "node_type"),
        ("uav-a", "movable", "aerial", "node_type"),
        ("uav-b", "fixed", "aerial", "node_type"),
        ("uav-c", "movable", "aerial", "node_type"),
        ("walker", "fixed", "ground", "node_type"),
        ("truck", "fixed", "ground", "node_type"),
    ]
    assert [r.roster_index for r in records] == list(range(6))
    assert by_id["uav-a"].selected and not by_id["gw"].selected
    assert all(r.radios == ("meshradio",) for r in records)
    assert all(r.slot is None for r in records)


def test_mapping_overrides_platform_and_radios(tmp_path):
    mapping = copy.deepcopy(MAPPING)
    mapping["platforms"] = {"nodes": {"walker": "aerial"}}
    mapping["radios"] = {"default": ["meshradio"], "nodes": {"gw": ["meshradio", "other"]}}
    by_id = _by_id(_records(tmp_path, mapping=mapping)[0])
    assert (by_id["walker"].platform, by_id["walker"].platform_source) == ("aerial", "mapping")
    assert by_id["gw"].radios == ("meshradio", "other")


def test_slots_follow_controlled_order(tmp_path):
    by_id = _by_id(_records(tmp_path, controlled=("walker", "uav-a"))[0])
    assert (by_id["walker"].slot, by_id["uav-a"].slot, by_id["gw"].slot) == (0, 1, None)
    by_id = _by_id(_records(tmp_path / "all", controlled=("all",))[0])
    assert by_id["truck"].slot == 5


def test_start_position_uses_first_waypoint(tmp_path):
    uav_b = _by_id(_records(tmp_path)[0])["uav-b"]
    assert (uav_b.x, uav_b.y, uav_b.z) == (220.0, 160.0, 30.0)


@pytest.mark.parametrize("overrides,match", [
    ({"gateway_node_id": "nope"}, "gateway_node_id names unknown"),
    ({"movable_nodes": "uav-a, ghost"}, "movable_nodes names unknown.*ghost"),
])
def test_unknown_ids(tmp_path, overrides, match):
    with pytest.raises(ConfigError, match=match):
        _records(tmp_path, overrides=overrides)


def test_missing_radio_and_unknown_node_type(tmp_path):
    mapping = copy.deepcopy(MAPPING)
    mapping["radios"] = {"nodes": {"gw": ["meshradio"]}}
    with pytest.raises(ConfigError, match="node 'uav-a' has no radio type"):
        _records(tmp_path / "a", mapping=mapping)
    nodes = copy.deepcopy(NODES)
    nodes[5]["node_type"] = "boat"
    with pytest.raises(ConfigError, match="node_type 'boat'"):
        _records(tmp_path / "b", nodes=nodes)
    mapping = copy.deepcopy(MAPPING)
    mapping["radios"]["nodes"] = {"ghost": ["meshradio"]}
    with pytest.raises(ConfigError, match="radios.nodes names unknown"):
        _records(tmp_path / "c", mapping=mapping)


def test_duplicate_node_ids(tmp_path):
    nodes = copy.deepcopy(NODES) + [copy.deepcopy(NODES[0])]
    with pytest.raises(ConfigError, match="repeats node id"):
        _records(tmp_path, nodes=nodes)


def test_negative_z_rejected(tmp_path):
    nodes = copy.deepcopy(NODES)
    nodes[5]["position"]["z"] = -0.5
    records, _ = _records(tmp_path, nodes=nodes)
    with pytest.raises(ConfigError) as err:
        adapter.check_datum(records)
    assert str(err.value) == ("node 'truck' has z=-0.5 below the declared ground datum; "
                              "only z_is_agl_m with z >= 0 is supported")


def test_blos_and_unknown_radio_rejected(tmp_path):
    records, _ = _records(tmp_path)
    adapter.check_radios(records, STUB_RF_SUMMARY)
    satellite = tuple(replace(r, radios=("satlink",)) if r.id == "gw" else r for r in records)
    with pytest.raises(ConfigError, match="'satlink', marked blos"):
        adapter.check_radios(satellite, STUB_RF_SUMMARY)
    unknown = tuple(replace(r, radios=("lora",)) if r.id == "gw" else r for r in records)
    with pytest.raises(ConfigError, match="does not define"):
        adapter.check_radios(unknown, STUB_RF_SUMMARY)


def test_hold_contract(tmp_path):
    cfg = config.load_baseline(write_scenario(tmp_path))
    adapter.check_hold_contract(cfg, ("uav-a", "uav-c"))
    adapter.check_hold_contract(cfg, ("all",))
    with pytest.raises(ConfigError, match="not in \\[rl\\] controlled_nodes: uav-c"):
        adapter.check_hold_contract(cfg, ("uav-a", "walker"))
    with pytest.raises(ConfigError, match="legacy single-node control"):
        adapter.check_hold_contract(cfg, None)


class _Request:
    rectangle = dict(AREA)


def _validate(tmp_path, positions, rl_bounds=None, nodes=None):
    records, loaded = _records(tmp_path, nodes=nodes)
    request = _Request()
    request.nodes = records
    base = stub_positions(request)
    base.update(positions)
    return adapter.validate_result(records, PlanResult(positions=base), dict(AREA),
                                   STUB_RF_SUMMARY, loaded, rl_bounds)


def test_valid_result_and_write_back(tmp_path):
    final = _validate(tmp_path, {"uav-c": (170.004, 140.003, 30.0)})
    assert final["uav-c"] == (170.0, 140.0, 30.0)
    assert final["uav-a"] == (400.0 / 3, 100.0, 30.0)
    assert final["gw"] == (200.0, 200.0, 2.0)


def test_inclusive_boundary_accepted(tmp_path):
    final = _validate(tmp_path, {"uav-a": (400.0, 0.0, 30.0), "uav-c": (0.0, 400.0, 30.0)},
                      rl_bounds=dict(AREA))
    assert final["uav-a"][:2] == (400.0, 0.0)


@pytest.mark.parametrize("positions,match", [
    ({"uav-a": (400.001, 100.0, 30.0)}, "outside the declared geofence rectangle"),
    ({"uav-a": (100.0, 100.0, 1.5)}, "changed z of 'uav-a'"),
    ({"gw": (201.0, 200.0, 2.0)}, "moved gateway node 'gw'"),
    ({"truck": (230.0, 230.5, 2.0)}, "moved fixed node 'truck'"),
    ({"uav-a": (math.nan, 100.0, 30.0)}, "non-finite"),
    ({"extra": (1.0, 1.0, 1.0)}, "unexpected: extra"),
])
def test_invalid_results(tmp_path, positions, match):
    with pytest.raises(ValueError, match=match):
        _validate(tmp_path, positions)


def test_missing_node_in_result(tmp_path):
    records, loaded = _records(tmp_path)
    positions = {r.id: (r.x, r.y, r.z) for r in records if r.id != "truck"}
    with pytest.raises(ValueError, match="missing: truck"):
        adapter.validate_result(records, PlanResult(positions=positions), dict(AREA),
                                STUB_RF_SUMMARY, loaded)


def test_displacement_cap(tmp_path):
    summary = copy.deepcopy(STUB_RF_SUMMARY)
    summary["movement_cost"]["aerial"]["max_displacement_m"] = 10.0
    records, loaded = _records(tmp_path)
    positions = {r.id: (r.x, r.y, r.z) for r in records}
    positions["uav-a"] = (150.0, 195.0, 30.0)
    with pytest.raises(ValueError, match="beyond the RF file's max_displacement_m 10.0"):
        adapter.validate_result(records, PlanResult(positions=positions), dict(AREA),
                                summary, loaded)


def test_rl_bounds_and_random_walk_bounds(tmp_path):
    with pytest.raises(ValueError, match="outside the \\[rl\\] x/y bounds"):
        _validate(tmp_path / "a", {}, rl_bounds={**AREA, "y_min": 150.0})
    nodes = copy.deepcopy(NODES)
    nodes[3]["random_walk"]["bounds"] = {"x_min": 0.0, "x_max": 200.0,
                                         "y_min": 0.0, "y_max": 400.0}
    with pytest.raises(ValueError, match="'uav-c'.*random_walk bounds"):
        _validate(tmp_path / "b", {}, nodes=nodes)


def test_random_walk_default_bounds_mirror_simulator(tmp_path):
    nodes = copy.deepcopy(NODES)
    del nodes[3]["random_walk"]
    with pytest.raises(ValueError, match="random_walk bounds"):
        _validate(tmp_path, {}, nodes=nodes)


def _prepare_eval(tmp_path, ini, method="geometric", **kwargs):
    out = tmp_path / "eval"
    return adapter.prepare(ini, method, out / method / "baseline", mode="evaluation", **kwargs)


def test_prepare_evaluation_with_stub(tmp_path, stub_planner):
    ini = write_scenario(tmp_path / "s", overrides={"algorithm": "none"})
    prepared = _prepare_eval(tmp_path, ini, band="sub-6", simulation_seeds=[1, 2])
    manifest = artifacts.read_json(prepared.manifest_path)
    assert manifest["status"] == "prepared"
    assert manifest["ended_at"] is not None
    assert (manifest["mode"], manifest["executor"]) == ("evaluation", "hold")
    assert (manifest["requested_algorithm"], manifest["method"]) == ("none", "geometric")
    assert (manifest["planner_seed"], manifest["planner_seed_status"]) == (None, "unused")
    assert (manifest["max_iterations"], manifest["max_iterations_status"]) == (
        None, "not_applicable")
    assert manifest["simulation_seeds"] == [1, 2]
    assert manifest["rf"]["simulator_channel"]["band"] == "sub-6"
    assert manifest["rf"]["simulator_channel"]["band_source"] == "cli"
    assert set(manifest["rf"]["planner"]["radios"]) == {"meshradio"}
    assert manifest["geofence"] == {"source": "rl_bounds", **AREA}
    assert manifest["origin"] == MAPPING["origin"]
    assert manifest["planner_source"]["origin"] in ("default", "MESH_SIM_ARPO_PATH")
    assert len(manifest["planner_source"]["files"]) == 9
    assert manifest["eval_manifest"] == "../../eval_manifest.json"
    assert manifest["sim_log"] is None
    assert manifest["fingerprint"] == artifacts.fingerprint(manifest)
    for key in ("plan", "planner_log", "source_inputs", "effective_inputs"):
        assert not Path(manifest[key]).is_absolute()
        assert (prepared.prep_dir / manifest[key]).exists()
    assert manifest["source_scenario_identity"]["run_config"] == "source-inputs/run.ini"
    assert manifest["effective_scenario_identity"]["run_config"] == "effective-inputs/run.ini"
    assert manifest["source_run_config_abs"] == str(ini.resolve())

    block = prepared.metadata
    assert block["manifest"] == "geometric/baseline/baseline_manifest.json"
    assert block["plan"] == "geometric/baseline/effective-inputs/baseline-plan.json"
    assert set(block["effective_scenario_identity"]) == set(artifacts.IDENTITY_HASH_KEYS)
    assert block["executor"] == "hold"
    assert block["fingerprint"] == manifest["fingerprint"]

    plan = json.loads(prepared.plan_path.read_text())
    selected = {n["id"]: n for n in plan["nodes"] if n["selected"]}
    assert set(selected) == {"uav-a", "uav-c"}
    assert selected["uav-a"]["slot"] == 0 and selected["uav-c"]["slot"] == 2
    assert plan["planner_predictions"]["stub"] is True
    assert math.isclose(plan["initial_displacement_m_total"],
                        sum(n["displacement_m"] for n in plan["nodes"]))
    log = (prepared.prep_dir / "planner.log").read_text()
    assert "stub planner: geometric/coverage" in log
    effective = config.load_baseline(prepared.effective_run_config)
    assert effective.algorithm == "none"


def test_prepare_standalone_resolves_method(tmp_path, stub_planner):
    ini = write_scenario(tmp_path / "s", overrides={"algorithm": "optimization"})
    binary = tmp_path / "fake-bin"
    binary.write_bytes(b"binary")
    prepared = adapter.prepare(ini, None, tmp_path / "run", mode="standalone",
                               sim_binary=binary)
    manifest = artifacts.read_json(prepared.manifest_path)
    assert (manifest["status"], manifest["ended_at"]) == ("prepared", None)
    assert (manifest["requested_algorithm"], manifest["method"]) == (
        "optimization", "optimization")
    assert (manifest["planner_seed"], manifest["max_iterations"]) == (7, 60)
    assert manifest["planner_seed_status"] == "used"
    assert manifest["executor"] == "none"
    assert manifest["sim_log"] == "sim.log"
    assert manifest["eval_manifest"] is None
    assert manifest["sim_binary_sha256"] == artifacts.sha256_file(binary)
    assert prepared.metadata["manifest"] == "baseline_manifest.json"
    override = adapter.prepare(ini, "geometric", tmp_path / "run2", mode="standalone")
    assert artifacts.read_json(override.manifest_path)["method"] == "geometric"


def test_prepare_none_standalone(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("planner used for method none")
    for name in ("solve", "inspect_rf", "resolve_source_dir", "source_hashes"):
        monkeypatch.setattr(f"scripts.baselines.arpo_solver.{name}", forbidden)
    ini = write_scenario(tmp_path / "s", overrides={"algorithm": "none"})
    prepared = adapter.prepare(ini, None, tmp_path / "run", mode="standalone")
    manifest = artifacts.read_json(prepared.manifest_path)
    assert manifest["method"] == "none"
    assert manifest["planner_source"] is None
    assert manifest["initial_displacement_m_total"] == 0.0
    assert (tmp_path / "run/effective-inputs/nodes.json").read_bytes() == (
        (ini.parent / "nodes.json").read_bytes())


def test_prepare_none_imports_no_planner_module(tmp_path):
    ini = write_scenario(tmp_path / "s", overrides={"algorithm": "none"})
    script = textwrap.dedent(f"""
        import sys
        from scripts.baselines import adapter
        adapter.prepare({str(ini)!r}, None, {str(tmp_path / 'run')!r}, mode="standalone")
        loaded = sorted(m for m in sys.modules if m.split('.')[0] in
                        ('models', 'core', 'planners', 'pydantic', 'shapely', 'pyproj',
                         'yaml') or m == 'scripts.baselines.arpo_solver')
        print(loaded)
    """)
    result = subprocess.run([sys.executable, "-c", script], cwd=MESH_ROOT, text=True,
                            capture_output=True, check=True)
    assert result.stdout.strip() == "[]"


def test_prepare_failure_records_failed(tmp_path, stub_planner):
    ini = write_scenario(tmp_path / "s", overrides={"objective": "fastest"})
    with pytest.raises(BaselinePreparationError, match="baseline.objective"):
        _prepare_eval(tmp_path, ini)
    prep = tmp_path / "eval/geometric/baseline"
    manifest = artifacts.read_json(prep / "baseline_manifest.json")
    assert manifest["status"] == "failed"
    assert "baseline.objective" in manifest["error"]
    assert manifest["ended_at"] is not None
    assert sorted(p.name for p in prep.iterdir()) == ["baseline_manifest.json"]


def test_solver_failure_keeps_log_and_writes_no_inputs(tmp_path, stub_planner, monkeypatch):
    def broken(request, log):
        log.write("about to fail\n")
        raise RuntimeError("solver exploded")
    monkeypatch.setattr("scripts.baselines.arpo_solver.solve", broken)
    ini = write_scenario(tmp_path / "s")
    with pytest.raises(BaselinePreparationError, match="solver exploded"):
        _prepare_eval(tmp_path, ini)
    prep = tmp_path / "eval/geometric/baseline"
    assert not (prep / "effective-inputs").exists()
    assert not (prep / "effective-inputs.partial").exists()
    log = (prep / "planner.log").read_text()
    assert "about to fail" in log and "FAILED: solver exploded" in log
    assert artifacts.read_json(prep / "baseline_manifest.json")["status"] == "failed"


def test_invalid_plan_fails_preparation(tmp_path, stub_planner, monkeypatch):
    def wrong_z(request, log):
        positions = stub_positions(request)
        x, y, _ = positions["uav-a"]
        positions["uav-a"] = (x, y, 1.5)
        return PlanResult(positions=positions)
    monkeypatch.setattr("scripts.baselines.arpo_solver.solve", wrong_z)
    with pytest.raises(BaselinePreparationError, match="changed z of 'uav-a'"):
        _prepare_eval(tmp_path, write_scenario(tmp_path / "s"))


@pytest.mark.parametrize("ini_edit,match", [
    (lambda text: text.replace("controlled_nodes = uav-a, uav-b, uav-c, walker\n", ""),
     "legacy single-node control"),
    (lambda text: text.replace("controlled_nodes = uav-a, uav-b, uav-c, walker",
                               "controlled_nodes = uav-a, walker"),
     "not in \\[rl\\] controlled_nodes: uav-c"),
    (lambda text: text.replace("x_max = 400.0\n", ""),
     "rl_bounds.*x_max.*loader defaults are not used"),
])
def test_evaluation_preparation_rules(tmp_path, stub_planner, ini_edit, match):
    ini = write_scenario(tmp_path / "s", ini_text=ini_edit(scenario_ini()))
    with pytest.raises(BaselinePreparationError, match=match):
        _prepare_eval(tmp_path, ini)


def test_blos_radio_rejected_through_prepare(tmp_path, stub_planner):
    mapping = copy.deepcopy(MAPPING)
    mapping["radios"] = {"default": ["meshradio"], "nodes": {"truck": ["satlink"]}}
    ini = write_scenario(tmp_path / "s", mapping=mapping)
    with pytest.raises(BaselinePreparationError, match="marked blos"):
        _prepare_eval(tmp_path, ini)


def test_negative_z_rejected_through_prepare(tmp_path, stub_planner):
    nodes = copy.deepcopy(NODES)
    nodes[0]["position"]["z"] = -1.0
    ini = write_scenario(tmp_path / "s", nodes=nodes)
    with pytest.raises(BaselinePreparationError, match="z_is_agl_m with z >= 0"):
        _prepare_eval(tmp_path, ini)


def test_prepare_argument_rules(tmp_path, stub_planner):
    ini = write_scenario(tmp_path / "s")
    with pytest.raises(BaselinePreparationError, match="evaluation placement method"):
        _prepare_eval(tmp_path, ini, method="none")
    with pytest.raises(ValueError, match="planner_source is a standalone option"):
        _prepare_eval(tmp_path / "b", ini, planner_source=tmp_path)
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "keep.txt").write_text("x")
    with pytest.raises(BaselinePreparationError, match="not empty"):
        adapter.prepare(ini, "geometric", busy, mode="standalone")
    assert sorted(p.name for p in busy.iterdir()) == ["keep.txt"]


def test_fingerprint_stable_and_sensitive(tmp_path, stub_planner):
    ini = write_scenario(tmp_path / "s")
    first = _prepare_eval(tmp_path / "1", ini).metadata["fingerprint"]
    second = _prepare_eval(tmp_path / "2", ini).metadata["fingerprint"]
    other = write_scenario(tmp_path / "o", overrides={"objective": "balanced"})
    third = _prepare_eval(tmp_path / "3", other).metadata["fingerprint"]
    assert first == second != third


def test_manifest_status_helpers(tmp_path):
    path = tmp_path / "baseline_manifest.json"
    artifacts.write_json(path, artifacts.new_manifest("standalone", "none", "none", "none"))
    assert not list(tmp_path.glob("*.tmp"))
    with pytest.raises(ValueError, match="illegal"):
        artifacts.set_status(path, "running")
    with pytest.raises(ValueError, match="set_status"):
        artifacts.update_manifest(path, status="complete")
    artifacts.set_status(path, "prepared")
    artifacts.set_status(path, "running")
    records = [artifacts.seed_record(1, "complete", "seed-1/summary.json"),
               artifacts.seed_record(2, "missing", None)]
    artifacts.set_seed_records(path, records)
    manifest = artifacts.set_status(path, "failed", error="seed 2 has no summary.json")
    assert manifest["seeds"] == records
    assert manifest["ended_at"] is not None
    with pytest.raises(ValueError, match="illegal"):
        artifacts.set_status(path, "complete")
    with pytest.raises(ValueError, match="seed status"):
        artifacts.seed_record(3, "done", None)


def test_interrupted_transition(tmp_path):
    path = tmp_path / "m.json"
    artifacts.write_json(path, artifacts.new_manifest("standalone", "none", "none", "none"))
    artifacts.set_status(path, "prepared")
    artifacts.set_status(path, "running")
    manifest = artifacts.set_status(path, "interrupted", error="SIGINT")
    assert (manifest["status"], manifest["error"]) == ("interrupted", "SIGINT")


def test_baseline_modules_do_not_import_rl_or_ml_stacks():
    script = textwrap.dedent("""
        import sys
        import scripts.baselines.config, scripts.baselines.adapter
        import scripts.baselines.effective_inputs, scripts.baselines.artifacts
        import scripts.baselines.arpo_solver
        banned = ('gymnasium', 'torch', 'stable_baselines3', 'sb3_contrib')
        print(sorted(m for m in sys.modules
                     if m.split('.')[0] in banned or m.startswith('scripts.rl')))
        heavy = ('pydantic', 'shapely', 'pyproj', 'yaml', 'models', 'core', 'planners')
        print(sorted(m for m in sys.modules if m.split('.')[0] in heavy))
    """)
    result = subprocess.run([sys.executable, "-c", script], cwd=MESH_ROOT, text=True,
                            capture_output=True, check=True)
    assert result.stdout.splitlines() == ["[]", "[]"]
