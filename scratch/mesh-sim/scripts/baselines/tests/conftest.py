"""Hand-written synthetic scenario, mapping, and RF fixtures plus a stub planner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# Axis-aligned area shared by the [rl] bounds and the rl_bounds geofence.
AREA = {"x_min": 0.0, "x_max": 400.0, "y_min": 0.0, "y_max": 400.0}

SCENARIO_SECTIONS = """[scenario]
name = baseline-synthetic
seed = 1
duration_s = 1.0
tick_s = 0.1
nodes_file = nodes.json

[rl]
enabled = true
controlled_nodes = uav-a, uav-b, uav-c, walker
max_controlled_nodes = 4
action_profile = move_2d
decision_interval_s = 0.5
action_type = discrete
reward_type = all_links_los
step_size_m = 1.0
x_min = 0.0
x_max = 400.0
y_min = 0.0
y_max = 400.0
z_min = 0.0
z_max = 100.0
"""

BASELINE_DEFAULTS = {
    "algorithm": "geometric",
    "objective": "coverage",
    "gateway_node_id": "gw",
    "movable_nodes": "uav-a, uav-c",
    "seed": "7",
    "max_iterations": "60",
    "mapping_file": "mapping.json",
    "rf_config": "rf.yaml",
}

# uav-b has both `position` and `waypoints`; they differ on purpose. The default movable
# nodes share z because the supplied optimizer's swap move exchanges altitudes.
NODES = [
    {"id": "gw", "role": "peer", "mobility": "fixed", "node_type": "vehicle",
     "position": {"x": 200.0, "y": 200.0, "z": 2.0}},
    {"id": "uav-a", "role": "peer", "mobility": "fixed", "node_type": "drone",
     "position": {"x": 150.0, "y": 180.0, "z": 30.0}},
    {"id": "uav-b", "role": "peer", "mobility": "waypoint", "node_type": "drone",
     "position": {"x": 210.0, "y": 150.0, "z": 30.0},
     "waypoints": [{"t": 0.0, "x": 220.0, "y": 160.0, "z": 30.0},
                   {"t": 1.0, "x": 240.0, "y": 160.0, "z": 30.0}]},
    {"id": "uav-c", "role": "peer", "mobility": "random_walk", "node_type": "drone",
     "position": {"x": 170.0, "y": 140.0, "z": 30.0},
     "random_walk": {"bounds": {"x_min": 0.0, "x_max": 400.0, "y_min": 0.0,
                                "y_max": 400.0}, "speed_mps": 2.0}},
    {"id": "walker", "role": "peer", "mobility": "random_walk", "node_type": "pedestrian",
     "position": {"x": 180.0, "y": 220.0, "z": 1.5},
     "random_walk": {"bounds": {"x_min": 0.0, "x_max": 400.0, "y_min": 0.0,
                                "y_max": 400.0}, "speed_mps": 1.0}},
    {"id": "truck", "role": "peer", "mobility": "constant_velocity", "node_type": "vehicle",
     "position": {"x": 230.0, "y": 230.0, "z": 2.0},
     "velocity": {"vx": 0.5, "vy": 0.0, "vz": 0.0}},
]

MAPPING = {
    "baseline_mapping_version": 1,
    "origin": {"lat": 10.0, "lon": 20.0, "synthetic": True},
    "ground_datum": "z_is_agl_m",
    "geofence": {"source": "rl_bounds"},
    "radios": {"default": ["meshradio"]},
    "platforms": {"nodes": {}},
}

RF_YAML = """radios:
  meshradio:
    frequency_ghz: 5.8
    tx_power_dbm: 20
    tx_gain_dbi: 3
    rx_gain_dbi: 3
    rx_sensitivity_dbm: -80
  satlink:
    blos: true
fade_margin_db: 10
range_safety_factor: 0.9
reference_receiver:
  radio_type: meshradio
  height_agl_m: 1.5
  antenna_gain_dbi: 0
  rx_sensitivity_dbm: -75
altitude_defaults:
  ground: {min_agl_m: 0, max_agl_m: 3}
  aerial: {min_agl_m: 10, max_agl_m: 60}
terrain_elevation_m: 0
balanced_core_fraction: 0.5
movement_cost:
  aerial: {fixed_cost_m2: 0, cost_m2_per_m: 0, max_displacement_m: 500}
  ground: {fixed_cost_m2: 0, cost_m2_per_m: 0, max_displacement_m: 300}
optimizer:
  budget_s_per_coa: 1.0
coverage_grid: {target_cells: 400, min_resolution_m: 5}
candidate_grid: {target_cells: 400, min_resolution_m: 5}
"""

# What inspect_rf returns for RF_YAML, without loading the planner.
STUB_RF_SUMMARY = {
    "radios": {
        "meshradio": {"radio_type": "meshradio", "frequency_hz": 5.8e9, "tx_power_dbm": 20.0,
                      "tx_gain_dbi": 3.0, "rx_gain_dbi": 3.0, "rx_sensitivity_dbm": -80.0,
                      "blos": False},
        "satlink": {"radio_type": "satlink", "frequency_hz": 0.0, "tx_power_dbm": 0.0,
                    "tx_gain_dbi": 0.0, "rx_gain_dbi": 0.0, "rx_sensitivity_dbm": 0.0,
                    "blos": True},
    },
    "movement_cost": {
        "aerial": {"fixed_cost_m2": 0.0, "cost_m2_per_m": 0.0, "max_displacement_m": 500.0},
        "ground": {"fixed_cost_m2": 0.0, "cost_m2_per_m": 0.0, "max_displacement_m": 300.0},
    },
    "fade_margin_db": 10.0,
    "range_safety_factor": 0.9,
    "reference_receiver": {"radio_type": "meshradio", "height_agl_m": 1.5,
                           "antenna_gain_dbi": 0.0, "rx_sensitivity_dbm": -75.0},
}


def baseline_section(overrides: dict | None = None, drop: tuple = ()) -> str:
    """[baseline] text from BASELINE_DEFAULTS; a None override removes a key."""
    values = {**BASELINE_DEFAULTS, **(overrides or {})}
    lines = ["[baseline]"]
    lines += [f"{key} = {value}" for key, value in values.items()
              if value is not None and key not in drop]
    return "\n".join(lines) + "\n"


def scenario_ini(overrides: dict | None = None, drop: tuple = (), extra: str = "") -> str:
    """Full run.ini text: scenario, centralized [rl], [baseline], then `extra`."""
    return f"{SCENARIO_SECTIONS}\n{baseline_section(overrides, drop)}{extra}"


def write_scenario(root: str | Path, *, overrides: dict | None = None, drop: tuple = (),
                   ini_text: str | None = None, nodes: list | None = None,
                   mapping: dict | None = None, rf_text: str | None = None) -> Path:
    """Write run.ini, nodes.json, mapping.json, and rf.yaml into root; return the INI path."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    run_ini = root / "run.ini"
    run_ini.write_text(ini_text if ini_text is not None else scenario_ini(overrides, drop))
    (root / "nodes.json").write_text(json.dumps(NODES if nodes is None else nodes,
                                                indent=2) + "\n")
    (root / "mapping.json").write_text(json.dumps(MAPPING if mapping is None else mapping,
                                                  indent=2) + "\n")
    (root / "rf.yaml").write_text(RF_YAML if rf_text is None else rf_text)
    return run_ini


def stub_positions(request: PlanRequest) -> dict:
    """Spread selected nodes along y = 1/4 of the rectangle; everything else stays put."""
    rect = request.rectangle
    selected = [record for record in request.nodes if record.selected]
    positions = {record.id: (record.x, record.y, record.z) for record in request.nodes}
    width = rect["x_max"] - rect["x_min"]
    y = rect["y_min"] + 0.25 * (rect["y_max"] - rect["y_min"])
    for index, record in enumerate(selected):
        x = rect["x_min"] + width * (index + 1) / (len(selected) + 1)
        positions[record.id] = (x, y, record.z)
    return positions


def stub_solve(request: PlanRequest, log) -> PlanResult:
    """Deterministic stand-in for arpo_solver.solve."""
    from scripts.baselines.adapter import PlanResult

    log.write(f"stub planner: {request.method}/{request.objective}\n")
    return PlanResult(positions=stub_positions(request),
                      predictions={"stub": True, "method": request.method},
                      planner_wall_s=0.0)


def stub_inspect_rf(rf_path, source_dir) -> dict:
    """Stand-in for arpo_solver.inspect_rf that matches RF_YAML."""
    return json.loads(json.dumps(STUB_RF_SUMMARY))


def install_stub_planner(monkeypatch) -> None:
    """Replace the solver and RF inspection so no planner module is imported."""
    monkeypatch.setattr("scripts.baselines.arpo_solver.solve", stub_solve)
    monkeypatch.setattr("scripts.baselines.arpo_solver.inspect_rf", stub_inspect_rf)


@pytest.fixture
def stub_planner(monkeypatch):
    install_stub_planner(monkeypatch)


@pytest.fixture
def scenario(tmp_path: Path) -> Path:
    """Synthetic scenario with an active geometric [baseline]; returns run.ini."""
    return write_scenario(tmp_path / "scenario")


FAKE_CHILD = Path(__file__).with_name("fake_child.py")


def fake_child_binary(directory: str | Path) -> Path:
    """Executable shim that runs fake_child.py with this interpreter; never a real simulator."""
    import sys

    path = Path(directory) / "fake-mesh-sim"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\nimport runpy\n"
                    f"runpy.run_path({str(FAKE_CHILD)!r}, run_name='__main__')\n")
    path.chmod(0o755)
    return path


@pytest.fixture
def fake_child(tmp_path: Path) -> Path:
    return fake_child_binary(tmp_path / "bin")
