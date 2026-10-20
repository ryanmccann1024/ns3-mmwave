"""nodes.json loading, node records, datum, ownership, evaluation region, identity, band.

Sources: scripts/baselines/README.md ("Mapping file" platform rules, "z is metres above
flat ground", "Hold executor contract", "Channel scoring" planning seed and run_id),
src/domain/node-spec.h (node_type defaults to "drone"; random_walk bounds default to
+-100), and src/config/rl-control.cc tokenize() (controlled_nodes tokens are trimmed and
empty tokens dropped).
"""


import pytest

from scripts.baselines import adapter, config, mapping as mapping_config
from scripts.baselines.config import ConfigError
from scripts.baselines.tests.conftest import NODES, write_scenario

ROSTER = [node["id"] for node in NODES]
CONTROLLED_LINE = "controlled_nodes = uav-a, uav-b, uav-c, walker"


def _records(tmp_path, nodes=None, mapping=None, controlled=None, **overrides):
    ini = write_scenario(tmp_path / "s", overrides=overrides or None, nodes=nodes,
                         mapping=mapping)
    cfg = config.load_baseline(ini)
    loaded = mapping_config.load_mapping(cfg.mapping_file, config.read_ini(ini))
    return adapter.build_records(adapter.load_nodes(ini.parent / "nodes.json"), cfg,
                                 loaded, controlled)


def _by_id(records):
    return {r.id: r for r in records}


def _node(node_id, **fields):
    return {"id": node_id, **fields}


# --- load_nodes -------------------------------------------------------------------------


# --- build_records: platforms, mobility, positions --------------------------------------

def test_absent_node_type_defaults_to_drone_and_aerial(tmp_path):
    nodes = [_node("a", position={"x": 1.0, "y": 2.0, "z": 3.0}),
             _node("b", node_type="vehicle")]
    by_id = _by_id(_records(tmp_path, nodes=nodes, movable_nodes="a"))
    assert (by_id["a"].node_type, by_id["a"].platform, by_id["a"].platform_source) == (
        "drone", "aerial", "node_type")
    assert by_id["a"].mobility == "fixed"
    # Absent position means (0, 0, 0), as start_position documents.
    assert (by_id["b"].x, by_id["b"].y, by_id["b"].z) == (0.0, 0.0, 0.0)


def test_partial_random_walk_bounds_use_simulator_defaults(tmp_path):
    nodes = [_node("a", mobility="random_walk", random_walk={"bounds": {"x_max": 400.0}}),
             _node("b", mobility="random_walk", random_walk={"speed_mps": 1.0}),
             _node("c", mobility="random_walk", random_walk={"bounds": None})]
    by_id = _by_id(_records(tmp_path, nodes=nodes, movable_nodes="a"))
    assert by_id["a"].random_walk_bounds == {"x_min": -100.0, "x_max": 400.0,
                                             "y_min": -100.0, "y_max": 100.0}
    assert by_id["b"].random_walk_bounds == adapter.RANDOM_WALK_DEFAULTS
    assert by_id["c"].random_walk_bounds == adapter.RANDOM_WALK_DEFAULTS


# --- datum ------------------------------------------------------------------------------

def test_datum_accepts_ground_level(tmp_path):
    nodes = [_node("a", position={"x": 0, "y": 0, "z": 0}), _node("b", position={"z": 0.0})]
    adapter.check_datum(_records(tmp_path, nodes=nodes, movable_nodes="a"))


def test_datum_uses_the_first_waypoint_for_waypoint_nodes(tmp_path):
    ok = [_node("a", mobility="waypoint", position={"z": -5.0},
                waypoints=[{"t": 0, "x": 1, "y": 1, "z": 2.0}])]
    adapter.check_datum(_records(tmp_path / "ok", nodes=ok, movable_nodes="a"))
    bad = [_node("a", mobility="waypoint", position={"z": 5.0},
                 waypoints=[{"t": 0, "x": 1, "y": 1, "z": -2.0}])]
    with pytest.raises(ConfigError, match="below the ground datum"):
        adapter.check_datum(_records(tmp_path / "bad", nodes=bad, movable_nodes="a"))


# --- [rl] controlled_nodes tokens and ownership -----------------------------------------


# --- evaluation region ------------------------------------------------------------------


# --- planning identity ------------------------------------------------------------------


# --- band -------------------------------------------------------------------------------


# --- penalties --------------------------------------------------------------------------
