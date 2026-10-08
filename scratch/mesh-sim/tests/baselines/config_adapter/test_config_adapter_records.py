"""nodes.json loading, node records, datum, ownership, evaluation region, identity, band.

Sources: scripts/baselines/README.md ("Mapping file" platform rules, "z is metres above
flat ground", "Hold executor contract", "Channel scoring" planning seed and run_id),
src/domain/node-spec.h (node_type defaults to "drone"; random_walk bounds default to
+-100), and src/config/rl-control.cc tokenize() (controlled_nodes tokens are trimmed and
empty tokens dropped).
"""

import copy
import json

import pytest

from scripts.baselines import adapter, config
from scripts.baselines.config import ConfigError
from scripts.baselines.tests.conftest import AREA, MAPPING, NODES, scenario_ini, write_scenario
from scripts.sim_support import parse_seed_spec

ROSTER = [node["id"] for node in NODES]
CONTROLLED_LINE = "controlled_nodes = uav-a, uav-b, uav-c, walker"


def _records(tmp_path, nodes=None, mapping=None, controlled=None, **overrides):
    ini = write_scenario(tmp_path / "s", overrides=overrides or None, nodes=nodes,
                         mapping=mapping)
    cfg = config.load_baseline(ini)
    loaded = config.load_mapping(cfg.mapping_file, config.read_ini(ini))
    return adapter.build_records(adapter.load_nodes(ini.parent / "nodes.json"), cfg,
                                 loaded, controlled)


def _by_id(records):
    return {r.id: r for r in records}


def _node(node_id, **fields):
    return {"id": node_id, **fields}


# --- load_nodes -------------------------------------------------------------------------

@pytest.mark.parametrize("payload,match", [
    ({}, "must be a JSON array of objects"),
    ([1, 2], "must be a JSON array of objects"),
    ([{"id": "a"}, "b"], "must be a JSON array of objects"),
    ([{"id": 5}], "non-empty string id"),
    ([{"id": ""}], "non-empty string id"),
    ([{"node_type": "drone"}], "non-empty string id"),
    ([{"id": None}], "non-empty string id"),
    ([{"id": "a"}, {"id": "b"}, {"id": "a"}, {"id": "b"}], "repeats node id\\(s\\) a, b"),
])
def test_load_nodes_rejects_malformed_rosters(tmp_path, payload, match):
    path = tmp_path / "nodes.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ConfigError, match=match):
        adapter.load_nodes(path)


def test_load_nodes_accepts_empty_roster_and_rejects_bad_json(tmp_path):
    path = tmp_path / "nodes.json"
    path.write_text("[]")
    assert adapter.load_nodes(path) == []
    path.write_text("[{]")
    with pytest.raises(ConfigError, match="not valid JSON"):
        adapter.load_nodes(path)


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


@pytest.mark.parametrize("node_type", ["Drone", "VEHICLE", "uav", "", "pedestrian "])
def test_unmapped_node_type_is_exact_match_only(tmp_path, node_type):
    nodes = [_node("a", node_type=node_type)]
    with pytest.raises(ConfigError, match="node 'a' has node_type .*platforms.nodes"):
        _records(tmp_path / "a", nodes=nodes, movable_nodes="a")
    mapping = {**copy.deepcopy(MAPPING), "platforms": {"nodes": {"a": "ground"}}}
    record = _records(tmp_path / "b", nodes=nodes, mapping=mapping, movable_nodes="a")[0]
    assert (record.platform, record.platform_source) == ("ground", "mapping")


def test_unmapped_node_type_fails_even_for_a_fixed_node(tmp_path):
    nodes = [_node("a"), _node("boat", node_type="boat")]
    with pytest.raises(ConfigError, match="node 'boat' has node_type 'boat'"):
        _records(tmp_path, nodes=nodes, movable_nodes="a")


@pytest.mark.parametrize("mobility", ["Waypoint", "static", "random-walk", ""])
def test_unsupported_mobility(tmp_path, mobility):
    nodes = [_node("a", mobility=mobility)]
    with pytest.raises(ConfigError, match="unsupported mobility"):
        _records(tmp_path, nodes=nodes, movable_nodes="a")


def test_waypoint_node_without_waypoints_fails(tmp_path):
    nodes = [_node("a", mobility="waypoint", position={"x": 1, "y": 1, "z": 1})]
    with pytest.raises(ValueError, match="'a' has waypoint mobility but no waypoints"):
        _records(tmp_path, nodes=nodes, movable_nodes="a")


def test_non_finite_start_position_fails(tmp_path):
    path = tmp_path / "s"
    write_scenario(path, overrides={"movable_nodes": "a"}, nodes=[_node("a")])
    (path / "nodes.json").write_text(
        '[{"id": "a", "position": {"x": Infinity, "y": 0, "z": 0}}]')
    cfg = config.load_baseline(path / "run.ini")
    mapping = config.load_mapping(cfg.mapping_file, config.read_ini(path / "run.ini"))
    with pytest.raises(ConfigError, match="node 'a' has a non-finite start position"):
        adapter.build_records(adapter.load_nodes(path / "nodes.json"), cfg, mapping)


def test_movable_upper_case_all_is_an_unknown_id(tmp_path):
    with pytest.raises(ConfigError, match="movable_nodes names unknown node id\\(s\\): ALL"):
        _records(tmp_path, movable_nodes="ALL")


def test_movable_all_on_an_empty_roster(tmp_path):
    assert _records(tmp_path, nodes=[], movable_nodes="all") == ()


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


def test_datum_rejects_tiny_negative_z_on_any_node(tmp_path):
    nodes = [_node("a"), _node("b", position={"x": 5, "y": 5, "z": -1e-9})]
    records = _records(tmp_path, nodes=nodes, movable_nodes="a")
    with pytest.raises(ConfigError, match="node 'b' has z=-1e-09 below the ground datum"):
        adapter.check_datum(records)


def test_datum_uses_the_first_waypoint_for_waypoint_nodes(tmp_path):
    ok = [_node("a", mobility="waypoint", position={"z": -5.0},
                waypoints=[{"t": 0, "x": 1, "y": 1, "z": 2.0}])]
    adapter.check_datum(_records(tmp_path / "ok", nodes=ok, movable_nodes="a"))
    bad = [_node("a", mobility="waypoint", position={"z": 5.0},
                 waypoints=[{"t": 0, "x": 1, "y": 1, "z": -2.0}])]
    with pytest.raises(ConfigError, match="below the ground datum"):
        adapter.check_datum(_records(tmp_path / "bad", nodes=bad, movable_nodes="a"))


# --- [rl] controlled_nodes tokens and ownership -----------------------------------------

def _controlled(tmp_path, line):
    text = scenario_ini().replace(CONTROLLED_LINE, line)
    return config.rl_controlled_nodes(config.read_ini(write_scenario(tmp_path,
                                                                     ini_text=text)))


@pytest.mark.parametrize("line,expected", [
    ("controlled_nodes =   uav-c ,uav-a  # two", ("uav-c", "uav-a")),
    ("controlled_nodes = uav-a,,uav-c,", ("uav-a", "uav-c")),
    ("controlled_nodes = ,uav-a", ("uav-a",)),
    ("controlled_nodes = all ; every node", ("all",)),
    ("controlled_nodes =", ()),
    ("controlled_nodes = # none", ()),
])
def test_controlled_tokens_match_cpp_tokenize(tmp_path, line, expected):
    assert _controlled(tmp_path, line) == expected


def test_ownership_through_ini_with_whitespace_and_empty_tokens(tmp_path):
    controlled = _controlled(tmp_path / "c", "controlled_nodes =  uav-c ,, uav-a , ")
    cfg = config.load_baseline(write_scenario(tmp_path / "m", overrides={
        "movable_nodes": "  uav-a,uav-c  # same set"}))
    assert adapter.check_ownership(cfg, controlled, ROSTER) == ["uav-c", "uav-a"]


@pytest.mark.parametrize("controlled,match", [
    (("uav-a", "uav-c", "uav-a"), "controlled_nodes lists uav-a more than once"),
    (("ALL",), "controlled_nodes names unknown node id\\(s\\): ALL"),
    (("all", "uav-a"), "controlled_nodes names unknown node id\\(s\\): all"),
    (("uav-a", "uav-c", "uav-c", "uav-a"), "lists uav-a, uav-c more than once"),
])
def test_ownership_rejects_malformed_controlled_lists(tmp_path, controlled, match):
    cfg = config.load_baseline(write_scenario(tmp_path))
    with pytest.raises(ConfigError, match=match):
        adapter.check_ownership(cfg, controlled, ROSTER)


def test_ownership_with_duplicate_whitespace_ids_from_the_ini(tmp_path):
    controlled = _controlled(tmp_path / "c", "controlled_nodes = uav-a, uav-a ,uav-c")
    cfg = config.load_baseline(write_scenario(tmp_path / "m"))
    with pytest.raises(ConfigError, match="lists uav-a more than once"):
        adapter.check_ownership(cfg, controlled, ROSTER)


def test_blank_controlled_nodes_is_not_accepted(tmp_path):
    # The simulator rejects a present-but-empty key ("set but empty"); evaluation must
    # not accept it either.
    cfg = config.load_baseline(write_scenario(tmp_path))
    with pytest.raises(ConfigError):
        adapter.check_ownership(cfg, (), ROSTER)


def test_ownership_all_against_single_node_roster(tmp_path):
    cfg = config.load_baseline(write_scenario(tmp_path, overrides={"movable_nodes": "all"}))
    assert adapter.check_ownership(cfg, ("solo",), ["solo"]) == ["solo"]
    assert adapter.check_ownership(cfg, ("all",), ["solo"]) == ["solo"]


def test_ownership_mismatch_is_checked_after_unknown_ids(tmp_path):
    cfg = config.load_baseline(write_scenario(tmp_path, overrides={
        "movable_nodes": "uav-a, ghost"}))
    with pytest.raises(ConfigError, match="movable_nodes names unknown node id\\(s\\): ghost"):
        adapter.check_ownership(cfg, ("uav-a",), ROSTER)


# --- evaluation region ------------------------------------------------------------------

@pytest.mark.parametrize("rect,expected", [
    (dict(AREA), dict(AREA)),
    ({"x_min": -10.0, "x_max": 410.0, "y_min": -10.0, "y_max": 410.0}, dict(AREA)),
    ({"x_min": 399.0, "x_max": 500.0, "y_min": 399.0, "y_max": 500.0},
     {"x_min": 399.0, "x_max": 400.0, "y_min": 399.0, "y_max": 400.0}),
])
def test_evaluation_region_intersections(rect, expected):
    assert adapter.evaluation_region(rect, dict(AREA)) == expected


@pytest.mark.parametrize("rect", [
    {"x_min": 400.0, "x_max": 500.0, "y_min": 400.0, "y_max": 500.0},  # corner point
    {"x_min": -100.0, "x_max": 0.0, "y_min": 0.0, "y_max": 400.0},     # shared edge
    {"x_min": 0.0, "x_max": 400.0, "y_min": 500.0, "y_max": 600.0},    # y disjoint only
])
def test_evaluation_region_without_area_fails(rect):
    with pytest.raises(ConfigError, match="do not overlap"):
        adapter.evaluation_region(rect, dict(AREA))


# --- planning identity ------------------------------------------------------------------

def _scenario_ini(tmp_path, seed_line="seed = 1\n", run_id_line=""):
    text = scenario_ini().replace("seed = 1\n", seed_line + run_id_line)
    return config.read_ini(write_scenario(tmp_path, ini_text=text))


@pytest.mark.parametrize("spec,expected", [("5-7", 5), ("7,5-6", 7), ("0", 0),
                                           (" 3 , 1", 3)])
def test_planning_seed_is_the_first_expanded_simulation_seed(tmp_path, spec, expected):
    ini = _scenario_ini(tmp_path)
    assert adapter.planning_identity(ini, parse_seed_spec(spec)) == (expected, 1)


@pytest.mark.parametrize("seeds", [[True], [-1], ["5"], [5.0], [None]])
def test_planning_seed_rejects_non_integer_simulation_seeds(tmp_path, seeds):
    with pytest.raises(ConfigError, match="not a non-negative integer"):
        adapter.planning_identity(_scenario_ini(tmp_path), seeds)


def test_only_the_first_simulation_seed_is_validated(tmp_path):
    assert adapter.planning_identity(_scenario_ini(tmp_path), [4, -1])[0] == 4


@pytest.mark.parametrize("line,expected", [("seed = 9 # c\n", 9), ("seed = 0\n", 0),
                                           ("seed =\n", 42), ("", 42),
                                           ("seed = ; later\n", 42), ("seed = 007\n", 7)])
def test_planning_seed_falls_back_to_scenario_seed(tmp_path, line, expected):
    assert adapter.planning_identity(_scenario_ini(tmp_path, line), None)[0] == expected
    assert adapter.planning_identity(_scenario_ini(tmp_path, line), [])[0] == expected


@pytest.mark.parametrize("line", ["seed = 5-7\n", "seed = 1,2\n", "seed = -1\n",
                                  "seed = 1.0\n", "seed = 1e3\n"])
def test_scenario_seed_must_be_one_integer(tmp_path, line):
    # [scenario] seed is a single simulation seed (run-ini-reference.md); ranges belong
    # to --seeds.
    with pytest.raises(ConfigError, match="\\[scenario\\] seed is not a non-negative"):
        adapter.planning_identity(_scenario_ini(tmp_path, line), None)


@pytest.mark.parametrize("line,expected", [("run_id = 0\n", 0), ("run_id = 12 # r\n", 12),
                                           ("run_id =\n", 1), ("", 1)])
def test_run_id_from_scenario(tmp_path, line, expected):
    ini = _scenario_ini(tmp_path, run_id_line=line)
    assert adapter.planning_identity(ini, [3]) == (3, expected)


@pytest.mark.parametrize("line", ["run_id = -1\n", "run_id = 1.5\n", "run_id = x\n"])
def test_run_id_must_be_a_non_negative_integer(tmp_path, line):
    with pytest.raises(ConfigError, match="\\[scenario\\] run_id"):
        adapter.planning_identity(_scenario_ini(tmp_path, run_id_line=line), [3])


# --- band -------------------------------------------------------------------------------

@pytest.mark.parametrize("extra,cli,expected", [
    ("\n[channel]\nband =   sub-6   # jammers\n", None, ("sub-6", "run.ini")),
    ("\n[channel]\nband =\n", None, ("mmwave", "default")),
    ("\n[channel]\nband = ; none\n", None, ("mmwave", "default")),
    ("\n[channel]\nfrequency_ghz = 28\n", None, ("mmwave", "default")),
    ("\n[channel]\nband = sub-6\n", "", ("sub-6", "run.ini")),
    ("", "", ("mmwave", "default")),
])
def test_band_resolution_edges(tmp_path, extra, cli, expected):
    ini = config.read_ini(write_scenario(tmp_path, ini_text=scenario_ini(extra=extra)))
    assert adapter.resolve_band(ini, cli) == expected


# --- penalties --------------------------------------------------------------------------

def test_penalties_follow_each_platform_independently(tmp_path):
    cfg = config.load_baseline(write_scenario(tmp_path, overrides={
        "aerial_max_displacement_m": "1e-3", "ground_fixed_cost_m2": "0",
        "ground_cost_m2_per_m": "0"}))
    penalties = adapter.resolve_penalties(cfg)
    assert (penalties["aerial"].fixed_cost_m2, penalties["aerial"].cost_m2_per_m,
            penalties["aerial"].max_displacement_m) == (150000.0, 500.0, 1e-3)
    assert (penalties["ground"].fixed_cost_m2, penalties["ground"].cost_m2_per_m,
            penalties["ground"].max_displacement_m) == (0.0, 0.0, None)
    block = adapter.penalties_block(penalties, 100000.0)
    assert block["fixed_cost_over_aoi"] == {"ground": 0.0, "aerial": 1.5}
    assert block["aerial"]["max_displacement_m"] == 1e-3
