"""preparation.prepare() argument handling, seed/identity recording, ownership and region gates.

No real simulator runs: solver.solve is replaced by the `stub_planner` fixture (or a
local stand-in), and `fake_child` only provides an executable file to hash. Sources:
scripts/baselines/README.md ("What preparation does", "Hold executor contract",
"Channel scoring", "Penalty scale", the manifest field table) and the [baseline] table
("geometric accepts seed and max_iterations ... records them as null with status unused /
not_applicable").
"""

import copy
import json


from scripts.baselines import artifacts, preparation
from scripts.baselines.tests.conftest import MAPPING, NODES, scenario_ini, write_scenario

CONTROLLED_LINE = "controlled_nodes = uav-a, uav-b, uav-c, walker"


def _eval_text(overrides=None, controlled="uav-a, uav-c", edit=None):
    text = scenario_ini(overrides).replace(CONTROLLED_LINE,
                                           f"controlled_nodes = {controlled}")
    return edit(text) if edit else text


def _eval_scenario(root, overrides=None, controlled="uav-a, uav-c", edit=None, **kwargs):
    return write_scenario(root, ini_text=_eval_text(overrides, controlled, edit), **kwargs)


def _prepare_eval(tmp_path, ini, binary, method="geometric", **kwargs):
    return preparation.prepare(ini, method, tmp_path / "eval" / method / "baseline",
                           mode="evaluation", sim_binary=binary, **kwargs)


# --- arguments and the preparation directory --------------------------------------------


# --- recorded optimizer settings --------------------------------------------------------


# --- planning seed and run_id -----------------------------------------------------------


# --- evaluation ownership and region ----------------------------------------------------


def test_rectangle_geofence_with_partial_rl_bounds_uses_simulator_defaults(
        tmp_path, stub_planner, fake_child):
    # With a rectangle geofence the explicit-bounds rule does not apply; the region is the
    # rectangle intersected with the bounds the simulator enforces (absent x_max -> 2000).
    mapping = {**copy.deepcopy(MAPPING),
               "geofence": {"source": "rectangle_xy_m", "x_min": 0.0, "x_max": 500.0,
                            "y_min": 0.0, "y_max": 400.0}}
    ini = _eval_scenario(tmp_path / "s", mapping=mapping,
                         edit=lambda t: t.replace("x_max = 400.0\n", ""))
    prepared = _prepare_eval(tmp_path, ini, fake_child)
    log = (prepared.prep_dir / "planner.log").read_text()
    region = {"x_max": 500.0, "x_min": 0.0, "y_max": 400.0, "y_min": 0.0}
    assert f"evaluation_region={json.dumps(region, sort_keys=True)}" in log
    assert artifacts.read_json(prepared.manifest_path)["geofence"]["x_max"] == 500.0


# --- waypoint policy --------------------------------------------------------------------


def test_unselected_waypoint_node_is_fine_under_reject(tmp_path, stub_planner, fake_child):
    ini = _eval_scenario(tmp_path / "s", overrides={"waypoint_policy": "reject"})
    prepared = _prepare_eval(tmp_path, ini, fake_child)
    plan = json.loads(prepared.plan_path.read_text())
    uav_b = next(n for n in plan["nodes"] if n["id"] == "uav-b")
    assert not uav_b["selected"] and uav_b["displacement_m"] == 0.0


# --- penalty scale ----------------------------------------------------------------------


# --- datum through prepare --------------------------------------------------------------

def test_ground_level_nodes_prepare(tmp_path, stub_planner, fake_child):
    nodes = copy.deepcopy(NODES)
    for node in nodes:
        node.setdefault("position", {})["z"] = 0.0
        for waypoint in node.get("waypoints", []):
            waypoint["z"] = 0.0
    ini = _eval_scenario(tmp_path / "s", nodes=nodes)
    prepared = _prepare_eval(tmp_path, ini, fake_child)
    plan = json.loads(prepared.plan_path.read_text())
    assert {n["planned"]["z"] for n in plan["nodes"]} == {0.0}
