"""Boundary values for every [baseline] key, choices, movable_nodes, and required keys.

Source of every expectation: the key table in scripts/baselines/README.md ("The
[baseline] section") and src/config/run-ini-reference.md: costs >= 0, displacement caps
> 0 (zero invalid), grid cells integer >= 1, grid_min_resolution_m > 0, probe height
>= 0, probe gain finite >= 0, coverage_sinr_db finite, balanced_core_fraction in [0, 1],
seed integer >= 0, max_iterations integer >= 1; unknown values are rejected; a blank
value means the key is absent.
"""

import math

import pytest

from scripts.baselines import config
from scripts.baselines.config import ConfigError
from scripts.baselines.tests.conftest import write_scenario

FLOAT_KEYS = [key for key, spec in config.NUMERIC_KEYS.items() if spec[0] == "float"]
INT_KEYS = ["candidate_grid_cells", "coverage_grid_cells"]


def _load(tmp_path, **overrides):
    return config.load_baseline(write_scenario(tmp_path, overrides=overrides))


def _reject(tmp_path, key, value, match=None):
    with pytest.raises(ConfigError, match=match or f"baseline\\.{key}"):
        _load(tmp_path, **{key: value})


def test_numeric_key_table_matches_readme():
    assert set(FLOAT_KEYS) | set(INT_KEYS) == set(config.NUMERIC_KEYS)
    assert len(config.NUMERIC_KEYS) == 13


# --- strings that are never a finite number, for every float key -----------------------

NOT_A_FINITE_NUMBER = ["nan", "NaN", "inf", "-inf", "Infinity", "1e999", "-1e999",
                       "0x10", "1,5", "1e", "e3", ".", "+", "-", "1.2.3", "1 0", "1_0",
                       "one", "--1", "1e+", "١"]


@pytest.mark.parametrize("key", FLOAT_KEYS)
@pytest.mark.parametrize("value", NOT_A_FINITE_NUMBER)
def test_float_keys_reject_non_numbers(tmp_path, key, value):
    _reject(tmp_path, key, value)


@pytest.mark.parametrize("key,value,expected", [
    ("grid_min_resolution_m", "1e3", 1000.0),
    ("grid_min_resolution_m", "1E-3", 0.001),
    ("grid_min_resolution_m", "1e-300", 1e-300),
    ("coverage_sinr_db", ".5", 0.5),
    ("coverage_sinr_db", "5.", 5.0),
    ("coverage_sinr_db", "+.5", 0.5),
    ("coverage_sinr_db", "-1e3", -1000.0),
    ("coverage_sinr_db", "0", 0.0),
    ("aerial_fixed_cost_m2", "1.5e+5", 150000.0),
    ("aerial_fixed_cost_m2", "0.0", 0.0),
    ("ground_cost_m2_per_m", "  250  # comment", 250.0),
    ("ground_cost_m2_per_m", "250;comment", 250.0),
    ("aerial_max_displacement_m", "1e-300", 1e-300),
    ("ground_max_displacement_m", "1E2", 100.0),
    ("coverage_probe_height_m", "0.0", 0.0),
    ("coverage_probe_rx_gain_dbi", "1e1", 10.0),
    ("balanced_core_fraction", "0.0", 0.0),
    ("balanced_core_fraction", "1.0", 1.0),
    ("balanced_core_fraction", "1e0", 1.0),
    ("balanced_core_fraction", ".25", 0.25),
])
def test_float_keys_accept_decimal_forms(tmp_path, key, value, expected):
    got = getattr(_load(tmp_path, **{key: value}), key)
    assert type(got) is float and got == expected


@pytest.mark.parametrize("key,value", [
    ("aerial_fixed_cost_m2", "-1e-9"), ("ground_fixed_cost_m2", "-0.000001"),
    ("aerial_cost_m2_per_m", "-1e-300"), ("ground_cost_m2_per_m", "-1"),
    ("aerial_max_displacement_m", "0.0"), ("aerial_max_displacement_m", "-0"),
    ("aerial_max_displacement_m", "-0.0"), ("ground_max_displacement_m", "0e5"),
    ("ground_max_displacement_m", "-1e-9"),
    ("grid_min_resolution_m", "0.0"), ("grid_min_resolution_m", "-0"),
    ("grid_min_resolution_m", "-1"),
    ("coverage_probe_height_m", "-1e-9"), ("coverage_probe_rx_gain_dbi", "-1e-9"),
    ("coverage_probe_rx_gain_dbi", "-3"),
    ("balanced_core_fraction", "1.000001"), ("balanced_core_fraction", "-1e-9"),
    ("balanced_core_fraction", "2"),
])
def test_float_keys_reject_out_of_range(tmp_path, key, value):
    _reject(tmp_path, key, value)


@pytest.mark.parametrize("key", ["aerial_max_displacement_m", "ground_max_displacement_m"])
@pytest.mark.parametrize("value", ["0", "0.0", "-0", "0e0"])
def test_zero_cap_in_any_spelling_gives_the_omit_hint(tmp_path, key, value):
    _reject(tmp_path, key, value, match="omit the key for no cap")


@pytest.mark.parametrize("key", FLOAT_KEYS + INT_KEYS)
def test_blank_numeric_value_means_default(tmp_path, key):
    default = config.NUMERIC_KEYS[key][4]
    for value in ("", "# commented out", "; nothing"):
        cfg = _load(tmp_path, **{key: value})
        assert getattr(cfg, key) == default
        assert key not in cfg.present_keys


def test_coverage_sinr_db_has_no_lower_bound(tmp_path):
    assert _load(tmp_path, coverage_sinr_db="-1e300").coverage_sinr_db == -1e300
    assert _load(tmp_path, coverage_sinr_db="1e300").coverage_sinr_db == 1e300


def test_error_names_key_and_raw_value(tmp_path):
    with pytest.raises(ConfigError) as caught:
        _load(tmp_path, balanced_core_fraction="1.5")
    assert "baseline.balanced_core_fraction must be <= 1.0" in str(caught.value)
    assert "'1.5'" in str(caught.value)
    with pytest.raises(ConfigError) as caught:
        _load(tmp_path, ground_cost_m2_per_m="-2")
    assert "baseline.ground_cost_m2_per_m must be >= 0.0" in str(caught.value)


# --- integer keys -----------------------------------------------------------------------

@pytest.mark.parametrize("key", INT_KEYS)
@pytest.mark.parametrize("value,expected", [("1", 1), ("01", 1), (" 7 ", 7),
                                            ("400 # cells", 400), ("12;x", 12),
                                            ("1000000", 1000000)])
def test_grid_cells_accept_plain_integers(tmp_path, key, value, expected):
    got = getattr(_load(tmp_path, **{key: value}), key)
    assert type(got) is int and got == expected


@pytest.mark.parametrize("key", INT_KEYS)
@pytest.mark.parametrize("value", ["0", "00", "-1", "-0", "1.0", "1.", "1e3", "+1",
                                   "1 0", "0x1", "inf", "nan", "four"])
def test_grid_cells_reject_non_integers_and_zero(tmp_path, key, value):
    _reject(tmp_path, key, value)


@pytest.mark.parametrize("value,expected", [("0", 0), ("00", 0), ("007", 7),
                                            ("4294967296", 4294967296), (" 3 # s", 3)])
def test_seed_accepts_non_negative_integers(tmp_path, value, expected):
    assert _load(tmp_path, seed=value).seed == expected


@pytest.mark.parametrize("value", ["-0", "-5", "1e3", "1.0", "+5", "5-7", "1,2", "0x5",
                                   "nan", "seven"])
def test_seed_rejects_other_forms(tmp_path, value):
    _reject(tmp_path, "seed", value, match="baseline\\.seed must be an integer >= 0")


@pytest.mark.parametrize("value,expected", [("1", 1), ("01", 1), ("999999", 999999)])
def test_max_iterations_accepts_positive_integers(tmp_path, value, expected):
    assert _load(tmp_path, max_iterations=value).max_iterations == expected


@pytest.mark.parametrize("value", ["0", "00", "-1", "1.0", "1e2", "+1", "2.5"])
def test_max_iterations_rejects_zero_and_non_integers(tmp_path, value):
    _reject(tmp_path, "max_iterations", value,
            match="baseline\\.max_iterations must be an integer >= 1")


# --- choice keys ------------------------------------------------------------------------

@pytest.mark.parametrize("key,value", [
    ("algorithm", "Geometric"), ("algorithm", "OPTIMIZATION"), ("algorithm", "None"),
    ("algorithm", "geometric optimization"), ("algorithm", "geometric,"),
    ("objective", "Coverage"), ("objective", "coverage,balanced"),
    ("application", "Initial_positions"), ("application", "initial-positions"),
    ("waypoint_policy", "Translate"), ("waypoint_policy", "REJECT"),
])
def test_choice_values_are_case_sensitive_and_exact(tmp_path, key, value):
    _reject(tmp_path, key, value, match=f"baseline\\.{key} must be one of")


@pytest.mark.parametrize("key,value,expected", [
    ("algorithm", "  optimization  ", "optimization"),
    ("objective", "resilience;x", "resilience"),
    ("application", "initial_positions # only one", "initial_positions"),
    ("waypoint_policy", "translate\t; shift path", "translate"),
])
def test_choice_values_trim_and_strip_comments(tmp_path, key, value, expected):
    assert getattr(_load(tmp_path, **{key: value}), key) == expected


def test_invalid_values_are_rejected_even_when_algorithm_is_none(tmp_path):
    # README: config.py rejects unknown values; nothing says `none` relaxes that.
    for key, value in (("objective", "speed"), ("seed", "-1"),
                       ("aerial_max_displacement_m", "0"), ("movable_nodes", "a,,b")):
        with pytest.raises(ConfigError, match=f"baseline\\.{key}"):
            _load(tmp_path / key, algorithm="none", **{key: value})


def test_blank_algorithm_with_other_keys_is_none(tmp_path):
    cfg = _load(tmp_path, algorithm="")
    assert cfg.algorithm == "none"
    assert "algorithm" not in cfg.present_keys
    assert {"objective", "movable_nodes", "seed", "max_iterations"} <= cfg.present_keys
    config.require_method(cfg, "none")


# --- removed and unknown keys -----------------------------------------------------------

def test_removed_and_unknown_keys_are_listed_together(tmp_path):
    with pytest.raises(ConfigError) as caught:
        _load(tmp_path, gateway_node_id="gw", zeta="1", rf_config="rf.yaml")
    message = str(caught.value)
    assert ("unknown [baseline] key(s): gateway_node_id (removed: baselines are "
            "gateway-free; delete the key), rf_config (removed:") in message
    assert ", zeta; allowed: algorithm, objective," in message


def test_removed_key_with_blank_value_is_still_rejected(tmp_path):
    with pytest.raises(ConfigError, match="gateway_node_id \\(removed"):
        _load(tmp_path, gateway_node_id="")


def test_key_names_are_case_sensitive(tmp_path):
    for key in ("Objective", "MOVABLE_NODES", "Seed"):
        with pytest.raises(ConfigError, match=f"unknown \\[baseline\\] key\\(s\\): {key}"):
            _load(tmp_path / key, **{key: "x"})


# --- movable_nodes ----------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("uav-a,uav-c", ("uav-a", "uav-c")),
    ("  uav-a  ,\tuav-c  ", ("uav-a", "uav-c")),
    ("uav-c, uav-a", ("uav-c", "uav-a")),
    ("walker", ("walker",)),
    ("uav a, b", ("uav a", "b")),
    ("ALL", ("ALL",)),
    ("All", ("All",)),
])
def test_movable_lists(tmp_path, value, expected):
    cfg = _load(tmp_path, movable_nodes=value)
    assert cfg.movable_nodes == expected
    assert not cfg.movable_all  # only lower-case `all` means the whole roster


@pytest.mark.parametrize("value", ["uav-a,", ",uav-a", "uav-a, ,uav-c", "uav-a,  uav-a",
                                   "uav-a,uav-a ", "all,all", "all , ", ", all",
                                   "ALL, all", "uav-a, all, uav-c"])
def test_movable_rejects_empty_duplicate_and_mixed_all(tmp_path, value):
    _reject(tmp_path, "movable_nodes", value, match="baseline\\.movable_nodes")


@pytest.mark.parametrize("value", ["", "# nothing yet", " ; none "])
def test_blank_movable_list_is_absent_and_required(tmp_path, value):
    cfg = _load(tmp_path, movable_nodes=value)
    assert cfg.movable_nodes == () and "movable_nodes" not in cfg.present_keys
    with pytest.raises(ConfigError, match="requires \\[baseline\\] movable_nodes"):
        config.require_method(cfg, "geometric")


# --- require_method ---------------------------------------------------------------------

@pytest.mark.parametrize("method", ["Geometric", "", "random", "hold"])
def test_require_method_rejects_unknown_methods(tmp_path, method):
    with pytest.raises(ConfigError, match="unknown placement method"):
        config.require_method(_load(tmp_path), method)


def test_require_method_lists_every_missing_key(tmp_path):
    cfg = config.load_baseline(write_scenario(
        tmp_path, drop=("objective", "movable_nodes", "seed", "max_iterations")))
    with pytest.raises(ConfigError,
                       match="requires \\[baseline\\] objective, movable_nodes, seed, "
                             "max_iterations$"):
        config.require_method(cfg, "optimization")
    with pytest.raises(ConfigError, match="requires \\[baseline\\] objective, movable_nodes$"):
        config.require_method(cfg, "geometric")
    config.require_method(cfg, "none")


def test_geometric_needs_neither_seed_nor_max_iterations(tmp_path):
    cfg = config.load_baseline(write_scenario(tmp_path, drop=("seed", "max_iterations")))
    config.require_method(cfg, "geometric")
    assert (cfg.seed, cfg.max_iterations) == (None, None)


def test_blank_seed_counts_as_missing_for_optimization(tmp_path):
    cfg = _load(tmp_path, seed="# later", max_iterations="")
    with pytest.raises(ConfigError, match="requires \\[baseline\\] seed, max_iterations"):
        config.require_method(cfg, "optimization")


def test_present_keys_only_lists_non_blank_values(tmp_path):
    cfg = _load(tmp_path, mapping_file="", coverage_sinr_db="-3")
    assert cfg.mapping_file is None
    assert cfg.present_keys == frozenset({"algorithm", "objective", "movable_nodes", "seed",
                                          "max_iterations", "coverage_sinr_db"})
    assert math.isclose(cfg.coverage_sinr_db, -3.0)
