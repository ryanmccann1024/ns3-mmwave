"""Mapping file v2, rectangle/rl_bounds geofences, polygon rejection, explicit [rl] bounds.

Source of every expectation: scripts/baselines/README.md "Mapping file (optional)" and
"TODO: polygon geofences" (including the exact error ending quoted there), and
src/config/config-loader.cc:345-348 (the simulator reads [rl] bounds with std::stod and
falls back to -1000/2000/-1000/1000 when a key is absent).
"""

import copy
import json

import pytest

from scripts.baselines import config
from scripts.baselines.config import ConfigError
from scripts.baselines.tests.conftest import AREA, MAPPING, scenario_ini, write_scenario

# Quoted verbatim from scripts/baselines/README.md ("The error ends with:").
README_POLYGON_ENDING = (
    "only axis-aligned rectangle geofences are supported (geofence.source 'rl_bounds' or "
    "'rectangle_xy_m'); polygon geofences are a documented TODO, and a bounding rectangle "
    "is never substituted")
POLYGON_KEYS = ["vertices", "polygon", "polygons", "points", "coordinates", "rings",
                "holes", "geojson", "exterior", "interiors"]
RECT = {"x_min": 10.0, "x_max": 20.0, "y_min": -5.0, "y_max": 5.0}
RL_LINES = ("x_min = 0.0\n", "x_max = 400.0\n", "y_min = 0.0\n", "y_max = 400.0\n")


def _ini(tmp_path, text=None):
    return config.read_ini(write_scenario(tmp_path / "s", ini_text=text))


def _load(tmp_path, payload, ini_text=None, raw=None):
    ini = _ini(tmp_path, ini_text)
    path = tmp_path / "mapping.json"
    path.write_text(raw if raw is not None else json.dumps(payload))
    return config.load_mapping(path, ini)


def _with_geofence(geofence):
    payload = copy.deepcopy(MAPPING)
    payload["geofence"] = geofence
    return payload


def _rl_text(replacements: dict) -> str:
    text = scenario_ini()
    for key, line in replacements.items():
        original = f"{key} = {AREA[key]}\n"
        assert original in text
        text = text.replace(original, line)
    return text


# --- rl_bounds: all four explicit -------------------------------------------------------

@pytest.mark.parametrize("key", config.RECT_KEYS)
def test_rl_bounds_each_missing_key_is_named(tmp_path, key):
    text = _rl_text({key: ""})
    with pytest.raises(ConfigError) as caught:
        _load(tmp_path, MAPPING, ini_text=text)
    message = str(caught.value)
    assert f"needs [rl] {key} written in the INI; loader defaults are not used" in message
    with pytest.raises(ConfigError, match=f"needs \\[rl\\] {key} written"):
        config.default_mapping(_ini(tmp_path / "d", text))


def test_rl_bounds_without_rl_section_names_all_four(tmp_path):
    text = "[scenario]\nnodes_file = nodes.json\n"
    with pytest.raises(ConfigError,
                       match="needs \\[rl\\] x_min, x_max, y_min, y_max written"):
        config.default_mapping(_ini(tmp_path, text))


@pytest.mark.parametrize("line", ["x_max =\n", "x_max = # 400\n", "x_max = ; 400\n",
                                  "# x_max = 400.0\n"])
def test_blank_or_commented_rl_bound_is_not_written(tmp_path, line):
    with pytest.raises(ConfigError, match="needs \\[rl\\] x_max written"):
        _load(tmp_path, MAPPING, ini_text=_rl_text({"x_max": line}))


def test_rl_bounds_ignore_bounds_written_in_other_sections(tmp_path):
    text = _rl_text({"y_min": ""}) + "\n[channel]\ny_min = 0.0\n"
    with pytest.raises(ConfigError, match="needs \\[rl\\] y_min"):
        _load(tmp_path, MAPPING, ini_text=text)


def test_rl_bounds_parse_comments_and_exponents(tmp_path):
    text = _rl_text({"x_min": "x_min = -1e2 # west\n", "x_max": "x_max = 4E2;east\n",
                     "y_min": "y_min = -0\n", "y_max": "y_max =   .5e3   \n"})
    mapping = _load(tmp_path, MAPPING, ini_text=text)
    assert mapping.rectangle == {"x_min": -100.0, "x_max": 400.0, "y_min": 0.0,
                                 "y_max": 500.0}
    assert mapping.geofence == {"source": "rl_bounds", **mapping.rectangle}


@pytest.mark.parametrize("value,match", [("abc", "rl.x_max is not a number"),
                                         ("nan", "rl.x_max must be finite"),
                                         ("inf", "rl.x_max must be finite"),
                                         ("-Infinity", "rl.x_max must be finite")])
def test_rl_bounds_reject_non_finite_values(tmp_path, value, match):
    with pytest.raises(ConfigError, match=match):
        _load(tmp_path, MAPPING, ini_text=_rl_text({"x_max": f"x_max = {value}\n"}))


# The simulator's std::stod reads "1_000" as 1.0, while float() reads 1000.0, so [rl]
# bounds with digit-group underscores must be rejected, like the [baseline] keys.
def test_rl_bounds_reject_underscored_numbers_like_baseline_keys(tmp_path):
    text = _rl_text({"x_max": "x_max = 1_000\n"})
    with pytest.raises(ConfigError, match="rl.x_max"):
        config.explicit_rl_bounds(_ini(tmp_path, text))


@pytest.mark.parametrize("replacements", [
    {"x_min": "x_min = 400.0\n"},
    {"x_min": "x_min = 500.0\n"},
    {"y_max": "y_max = 0.0\n"},
    {"y_max": "y_max = -1.0\n"},
])
def test_rl_bounds_must_be_a_proper_rectangle(tmp_path, replacements):
    with pytest.raises(ConfigError, match="\\[rl\\] bounds must have x_min < x_max"):
        _load(tmp_path, MAPPING, ini_text=_rl_text(replacements))


def test_effective_rl_bounds_fill_only_absent_keys_with_simulator_defaults(tmp_path):
    ini = _ini(tmp_path, _rl_text({"x_max": "", "y_min": "y_min = # later\n"}))
    assert config.explicit_rl_bounds(ini) == {"x_min": 0.0, "y_max": 400.0}
    assert config.effective_rl_bounds(ini) == {"x_min": 0.0, "x_max": 2000.0,
                                               "y_min": -1000.0, "y_max": 400.0}
    # Mirrors src/domain/sim-config.h RlConfig defaults.
    assert config.RL_BOUND_DEFAULTS == {"x_min": -1000.0, "x_max": 2000.0,
                                        "y_min": -1000.0, "y_max": 1000.0}


# --- rectangle_xy_m ---------------------------------------------------------------------

def test_rectangle_needs_no_rl_section(tmp_path):
    payload = _with_geofence({"source": "rectangle_xy_m", **RECT})
    mapping = _load(tmp_path, payload, ini_text="[scenario]\nnodes_file = nodes.json\n")
    assert mapping.geofence == {"source": "rectangle_xy_m", **RECT}
    assert all(type(v) is float for v in mapping.rectangle.values())


def test_rectangle_accepts_integers_negatives_and_tiny_extent(tmp_path):
    payload = _with_geofence({"source": "rectangle_xy_m", "x_min": -300, "x_max": -299,
                              "y_min": 0, "y_max": 1e-9})
    rect = _load(tmp_path, payload).rectangle
    assert rect == {"x_min": -300.0, "x_max": -299.0, "y_min": 0.0, "y_max": 1e-9}


@pytest.mark.parametrize("override", [
    {"x_min": 20.0}, {"x_min": 21.0}, {"y_max": -5.0}, {"y_min": 6.0},
])
def test_rectangle_rejects_empty_or_inverted_extent(tmp_path, override):
    payload = _with_geofence({"source": "rectangle_xy_m", **RECT, **override})
    with pytest.raises(ConfigError, match="must have x_min < x_max and y_min < y_max"):
        _load(tmp_path, payload)


@pytest.mark.parametrize("value", ["10", None, True, False, [10], {"v": 10}])
def test_rectangle_rejects_non_numbers(tmp_path, value):
    payload = _with_geofence({"source": "rectangle_xy_m", **RECT, "x_min": value})
    with pytest.raises(ConfigError, match="geofence.x_min must be a number"):
        _load(tmp_path, payload)


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_rectangle_rejects_non_finite_json_literals(tmp_path, literal):
    raw = ('{"baseline_mapping_version": 2, "geofence": {"source": "rectangle_xy_m", '
           f'"x_min": 0, "x_max": {literal}, "y_min": 0, "y_max": 1}}}}')
    with pytest.raises(ConfigError, match="geofence.x_max must be finite"):
        _load(tmp_path, None, raw=raw)


@pytest.mark.parametrize("key", config.RECT_KEYS)
def test_rectangle_each_missing_key_is_named(tmp_path, key):
    geofence = {"source": "rectangle_xy_m", **RECT}
    del geofence[key]
    with pytest.raises(ConfigError, match=f"missing key\\(s\\): {key}$"):
        _load(tmp_path, _with_geofence(geofence))


@pytest.mark.parametrize("extra", ["z_min", "crs", "X_MIN", "margin_m"])
def test_rectangle_rejects_extra_keys(tmp_path, extra):
    payload = _with_geofence({"source": "rectangle_xy_m", **RECT, extra: 1})
    with pytest.raises(ConfigError, match=f"unknown key\\(s\\): {extra}"):
        _load(tmp_path, payload)


# --- polygon rejection ------------------------------------------------------------------

def _assert_polygon_error(err):
    message = str(err.value)
    assert message.endswith(README_POLYGON_ENDING), message
    return message


@pytest.mark.parametrize("key", POLYGON_KEYS)
@pytest.mark.parametrize("base", [{"source": "rectangle_xy_m", **RECT},
                                  {"source": "rl_bounds"}, {}])
def test_each_polygon_key_is_rejected_with_readme_text(tmp_path, key, base):
    payload = _with_geofence({**base, key: [[0, 0], [1, 0], [0, 1]]})
    with pytest.raises(ConfigError) as caught:
        _load(tmp_path, payload)
    message = _assert_polygon_error(caught)
    assert f"requests a polygon ({key})" in message


def test_polygon_key_with_empty_value_is_still_rejected(tmp_path):
    payload = _with_geofence({"source": "rectangle_xy_m", **RECT, "holes": []})
    with pytest.raises(ConfigError) as caught:
        _load(tmp_path, payload)
    _assert_polygon_error(caught)


def test_several_polygon_keys_are_all_named(tmp_path):
    payload = _with_geofence({"exterior": [], "interiors": [], "source": "rectangle_xy_m"})
    with pytest.raises(ConfigError) as caught:
        _load(tmp_path, payload)
    assert "(exterior, interiors)" in _assert_polygon_error(caught)


@pytest.mark.parametrize("source", ["polygon", "Polygon", "POLYGON_XY_M", "multipolygon",
                                    "GeoJSON", "geojson_feature", "vertex_list",
                                    "Vertices", "point_list", "Point_cloud",
                                    "rectangle_from_points"])
def test_polygon_like_source_is_rejected_with_readme_text(tmp_path, source):
    with pytest.raises(ConfigError) as caught:
        _load(tmp_path, _with_geofence({"source": source}))
    assert repr(source) in _assert_polygon_error(caught)


@pytest.mark.parametrize("geofence", [[], [[0, 0], [1, 0], [0, 1]],
                                      [{"x": 0, "y": 0}]])
def test_list_geofence_is_rejected_as_a_point_list(tmp_path, geofence):
    with pytest.raises(ConfigError) as caught:
        _load(tmp_path, _with_geofence(geofence))
    assert "is a point list" in _assert_polygon_error(caught)


@pytest.mark.parametrize("geofence", [{"source": "circle"}, {"source": "rl-bounds"},
                                      {"source": "rectangle"}, {"source": ""},
                                      {"source": None}, {"source": 5}, {},
                                      {"source": "RL_BOUNDS"}])
def test_other_unknown_sources_are_not_reported_as_polygons(tmp_path, geofence):
    with pytest.raises(ConfigError) as caught:
        _load(tmp_path, _with_geofence(geofence))
    message = str(caught.value)
    assert "geofence.source must be one of rl_bounds, rectangle_xy_m" in message
    assert README_POLYGON_ENDING not in message


@pytest.mark.parametrize("geofence", ["rl_bounds", None, 3])
def test_non_object_geofence(tmp_path, geofence):
    with pytest.raises(ConfigError, match="geofence must be a JSON object"):
        _load(tmp_path, _with_geofence(geofence))


def test_mixed_case_polygon_key_is_still_rejected(tmp_path):
    # Not one of the README's lower-case keys, but it must not be accepted either.
    payload = _with_geofence({"source": "rectangle_xy_m", **RECT, "Vertices": []})
    with pytest.raises(ConfigError):
        _load(tmp_path, payload)


# --- version, top-level keys, platforms -------------------------------------------------

@pytest.mark.parametrize("version", ["2", 0, -2, None, 2.5, [2], {"v": 2}])
def test_mapping_version_must_be_two(tmp_path, version):
    payload = {**copy.deepcopy(MAPPING), "baseline_mapping_version": version}
    with pytest.raises(ConfigError, match="baseline_mapping_version must be 2"):
        _load(tmp_path, payload)


def test_version_one_gets_migration_text_even_when_otherwise_valid(tmp_path):
    payload = {**copy.deepcopy(MAPPING), "baseline_mapping_version": 1}
    with pytest.raises(ConfigError, match="no longer read; migrate to version 2"):
        _load(tmp_path, payload)


def test_retired_keys_are_listed_together(tmp_path):
    payload = {**copy.deepcopy(MAPPING), "radios": {}, "origin": {}}
    with pytest.raises(ConfigError, match="origin, radios removed in mapping version 2"):
        _load(tmp_path, payload)


@pytest.mark.parametrize("payload", [
    {"baseline_mapping_version": 2},
    {"baseline_mapping_version": 2, "Geofence": {"source": "rl_bounds"}},
])
def test_geofence_is_required(tmp_path, payload):
    with pytest.raises(ConfigError, match="geofence|Geofence"):
        _load(tmp_path, payload)


def test_minimal_mapping_has_no_platforms(tmp_path):
    payload = {"baseline_mapping_version": 2, "geofence": {"source": "rl_bounds"}}
    mapping = _load(tmp_path, payload)
    assert mapping.platforms == {} and mapping.rectangle == AREA
    assert mapping.path == tmp_path / "mapping.json"


@pytest.mark.parametrize("platforms,match", [
    (None, "platforms must be a JSON object"),
    ([], "platforms must be a JSON object"),
    ({"nodes": None}, "platforms.nodes must be an object"),
    ({"nodes": "uav-a"}, "platforms.nodes must be an object"),
    ({"nodes": {"uav-a": "Aerial"}}, "platforms.nodes.uav-a must be one of ground, aerial"),
    ({"nodes": {"uav-a": "air"}}, "platforms.nodes.uav-a must be one of"),
    ({"nodes": {"uav-a": None}}, "platforms.nodes.uav-a must be one of"),
    ({"nodes": {"uav-a": 1}}, "platforms.nodes.uav-a must be one of"),
    ({"nodes": {}, "by_type": {"drone": "aerial"}}, "unknown key\\(s\\): by_type"),
])
def test_invalid_platforms(tmp_path, platforms, match):
    payload = {**copy.deepcopy(MAPPING), "platforms": platforms}
    with pytest.raises(ConfigError, match=match):
        _load(tmp_path, payload)


@pytest.mark.parametrize("platforms,expected", [
    ({}, {}), ({"nodes": {}}, {}),
    ({"nodes": {"gw": "aerial", "uav-a": "ground"}}, {"gw": "aerial", "uav-a": "ground"}),
])
def test_valid_platforms(tmp_path, platforms, expected):
    payload = {**copy.deepcopy(MAPPING), "platforms": platforms}
    assert _load(tmp_path, payload).platforms == expected


def test_mapping_path_that_is_a_directory_is_not_found(tmp_path):
    ini = _ini(tmp_path)
    with pytest.raises(ConfigError, match="mapping file not found"):
        config.load_mapping(tmp_path, ini)


def test_empty_mapping_file_is_invalid_json(tmp_path):
    with pytest.raises(ConfigError, match="not valid JSON"):
        _load(tmp_path, None, raw="")
