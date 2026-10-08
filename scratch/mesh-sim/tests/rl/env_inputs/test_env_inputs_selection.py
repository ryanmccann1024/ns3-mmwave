"""Precedence, source attribution, and validation of RlSelection (selection.py).

Spec: src/rl/policy-inputs.md "Selection keys and flags": each key resolves
independently CLI > run.ini > default, both manifests record value and source,
and unknown/mismatched/legacy-mode selections fail before the simulator starts.
"""

import json

import pytest

from scripts.rl.env.selection import (
    RlSelection, resolve_selection, uses_composed_reward, uses_custom_observation,
)

KEYS = ("observation_preset", "reward_components", "reward_weights", "telemetry",
        "telemetry_every")

FULL_INI = """[scenario]
seed = 1

[rl]
controlled_nodes = node-b, node-c
observation_preset = local_links_v1
reward_components = delivery_ratio, connectivity
reward_weights = 1.0, 0.5
telemetry = steps
telemetry_every = 2
"""
CENTRAL_ONLY = "[rl]\ncontrolled_nodes = node-b\n"
LEGACY_ONLY = "[rl]\ncontrolled_node_id = relay\n"


def ini(tmp_path, text, name="run.ini") -> str:
    path = tmp_path / name
    path.write_text(text)
    return str(path)


# --- Precedence and source per key -------------------------------------------------

@pytest.mark.parametrize("key,cli_value,attr,expected", [
    ("observation_preset", "geometry_v1", "observation_preset", "geometry_v1"),
    ("reward_components", "throughput_mbps,legacy", "reward_components",
     ("throughput_mbps", "legacy")),
    ("reward_weights", "2, 3", "reward_weights", (2.0, 3.0)),
    ("telemetry", "steps", "telemetry", "steps"),
    ("telemetry_every", 3, "telemetry_every", 3),
])
def test_cli_overrides_one_key_and_only_that_source_changes(tmp_path, key, cli_value,
                                                            attr, expected):
    selection = resolve_selection(ini(tmp_path, FULL_INI), **{key: cli_value})
    assert getattr(selection, attr) == expected
    sources = selection.describe()["source"]
    assert sources == {k: ("cli" if k == key else "run.ini") for k in KEYS}


@pytest.mark.parametrize("line,key", [
    ("observation_preset = service_v1", "observation_preset"),
    ("reward_components = legacy", "reward_components"),
    ("telemetry = steps", "telemetry"),
    ("telemetry = none", "telemetry"),
])
def test_single_ini_key_is_attributed_to_run_ini(tmp_path, line, key):
    selection = resolve_selection(ini(tmp_path, CENTRAL_ONLY + line + "\n"))
    sources = selection.describe()["source"]
    assert sources == {k: ("run.ini" if k == key else "default") for k in KEYS}


def test_cli_weights_combine_with_ini_components(tmp_path):
    text = CENTRAL_ONLY + "reward_components = delivery_ratio, connectivity\n"
    selection = resolve_selection(ini(tmp_path, text), reward_weights="0.25,4")
    assert selection.reward_weights == (0.25, 4.0)
    sources = selection.describe()["source"]
    assert (sources["reward_components"], sources["reward_weights"]) == ("run.ini", "cli")


def test_cli_components_with_ini_weights_must_still_match_in_count(tmp_path):
    # Each key resolves independently, so ini weights for two components do not
    # silently fit a one-component CLI override.
    with pytest.raises(ValueError, match="reward_weights has 2 entries"):
        resolve_selection(ini(tmp_path, FULL_INI), reward_components="legacy")


def test_cli_telemetry_every_with_ini_steps(tmp_path):
    selection = resolve_selection(ini(tmp_path, CENTRAL_ONLY + "telemetry = steps\n"),
                                  telemetry_every=4)
    assert (selection.telemetry, selection.telemetry_every) == ("steps", 4)


def test_cli_telemetry_none_conflicts_with_ini_every(tmp_path):
    with pytest.raises(ValueError, match="telemetry_every requires telemetry = steps"):
        resolve_selection(ini(tmp_path, FULL_INI), telemetry="none")


def test_default_weights_are_one_per_component(tmp_path):
    selection = resolve_selection(ini(tmp_path, CENTRAL_ONLY),
                                  reward_components="legacy, connectivity,throughput_mbps")
    assert selection.reward_weights == (1.0, 1.0, 1.0)
    assert selection.describe()["source"]["reward_weights"] == "default"


# --- run.ini parsing of selection keys ---------------------------------------------

@pytest.mark.parametrize("line", ["observation_preset =", "observation_preset =   ",
                                  "observation_preset = ; none",
                                  "observation_preset = # none"])
def test_blank_or_comment_only_ini_value_counts_as_absent(tmp_path, line):
    selection = resolve_selection(ini(tmp_path, CENTRAL_ONLY + line + "\n"))
    assert selection.observation_preset == "raw_links_v1"
    assert selection.describe()["source"]["observation_preset"] == "default"


def test_inline_comments_in_list_values(tmp_path):
    text = CENTRAL_ONLY + ("reward_components = delivery_ratio, connectivity ; pair\n"
                           "reward_weights = 1.0, 0.5 # weights\n"
                           "telemetry = steps;inline\n"
                           "telemetry_every = 3 # every third\n")
    selection = resolve_selection(ini(tmp_path, text))
    assert selection.reward_components == ("delivery_ratio", "connectivity")
    assert selection.reward_weights == (1.0, 0.5)
    assert (selection.telemetry, selection.telemetry_every) == ("steps", 3)


def test_cli_whitespace_is_stripped(tmp_path):
    selection = resolve_selection(ini(tmp_path, CENTRAL_ONLY),
                                  observation_preset="  local_links_v1 ",
                                  reward_components=" delivery_ratio ,connectivity ",
                                  reward_weights=" 1 , 2 ", telemetry=" steps ",
                                  telemetry_every=" 5 ")
    assert selection.describe() == {
        "observation_preset": "local_links_v1",
        "reward_components": ["delivery_ratio", "connectivity"],
        "reward_weights": [1.0, 2.0], "telemetry": "steps", "telemetry_every": 5,
        "source": {k: "cli" for k in KEYS},
    }


# --- Invalid values ----------------------------------------------------------------

@pytest.mark.parametrize("kwargs,match", [
    ({"observation_preset": ""}, "observation_preset"),
    ({"observation_preset": "LOCAL_LINKS_V1"}, "observation_preset"),
    ({"reward_components": "Delivery_Ratio"}, "unknown entries"),
    ({"reward_components": " , ,"}, "empty list"),
    ({"reward_components": "connectivity, connectivity"}, "duplicate"),
    ({"reward_components": "connectivity", "reward_weights": "nan"}, "finite"),
    ({"reward_components": "connectivity", "reward_weights": "inf"}, "finite"),
    ({"reward_components": "connectivity", "reward_weights": "-inf"}, "finite"),
    ({"reward_components": "connectivity", "reward_weights": "heavy"}, "floats"),
    ({"reward_components": "connectivity", "reward_weights": ","}, "empty list"),
    ({"reward_components": "connectivity", "reward_weights": "1,2"}, "2 entries"),
    ({"telemetry": "Steps"}, "telemetry"),
    ({"telemetry": "steps", "telemetry_every": "2.5"}, "positive integer"),
    ({"telemetry": "steps", "telemetry_every": -1}, "positive integer"),
    ({"telemetry": "steps", "telemetry_every": 0}, "positive integer"),
    ({"telemetry_every": 1}, "requires telemetry = steps"),
])
def test_invalid_cli_values_fail_and_name_the_cli_source(tmp_path, kwargs, match):
    with pytest.raises(ValueError, match=match) as excinfo:
        resolve_selection(ini(tmp_path, CENTRAL_ONLY), **kwargs)
    assert "cli" in str(excinfo.value)


@pytest.mark.parametrize("line,match", [
    ("observation_preset = nope", "observation_preset"),
    ("reward_weights = 1.0", "reward_weights requires reward_components"),
    ("telemetry = csv", "telemetry"),
    ("telemetry_every = 2", "requires telemetry = steps"),
])
def test_invalid_ini_values_fail_and_name_the_run_ini_source(tmp_path, line, match):
    with pytest.raises(ValueError, match=match) as excinfo:
        resolve_selection(ini(tmp_path, CENTRAL_ONLY + line + "\n"))
    assert "run.ini" in str(excinfo.value)


def test_trailing_comma_in_components_is_tolerated(tmp_path):
    selection = resolve_selection(ini(tmp_path, CENTRAL_ONLY),
                                  reward_components="delivery_ratio,")
    assert selection.reward_components == ("delivery_ratio",)


# --- Legacy mode ---------------------------------------------------------------------

@pytest.mark.parametrize("kwargs", [
    {"observation_preset": "raw_links_v1"},
    {"telemetry": "none"},
    {"observation_preset": "raw_links_v1", "telemetry": "none"},
])
def test_legacy_mode_accepts_explicit_default_values(tmp_path, kwargs):
    selection = resolve_selection(ini(tmp_path, LEGACY_ONLY), **kwargs)
    assert selection.observation_preset == "raw_links_v1"
    assert selection.telemetry == "none"
    for key in kwargs:
        assert selection.describe()["source"][key] == "cli"


def test_legacy_mode_accepts_explicit_default_values_from_ini(tmp_path):
    text = LEGACY_ONLY + "observation_preset = raw_links_v1\ntelemetry = none\n"
    selection = resolve_selection(ini(tmp_path, text))
    assert selection.describe()["source"]["observation_preset"] == "run.ini"


@pytest.mark.parametrize("source,kwargs,line,offending", [
    ("cli", {"reward_components": "legacy"}, "", "reward_components"),
    ("cli", {"telemetry": "steps"}, "", "telemetry"),
    ("cli", {"observation_preset": "service_v1"}, "", "observation_preset"),
    ("run.ini", {}, "observation_preset = local_links_v1\n", "observation_preset"),
    ("run.ini", {}, "telemetry = steps\ntelemetry_every = 2\n", "telemetry_every"),
    ("run.ini", {}, "reward_components = connectivity\nreward_weights = 2\n",
     "reward_weights"),
])
def test_legacy_mode_rejects_non_default_values(tmp_path, source, kwargs, line, offending):
    with pytest.raises(ValueError, match="centralized control mode") as excinfo:
        resolve_selection(ini(tmp_path, LEGACY_ONLY + line), **kwargs)
    assert offending in str(excinfo.value)


def test_blank_controlled_nodes_counts_as_centralized(tmp_path):
    # C++ selects centralized mode on key presence, not value (config-loader.cc:353).
    selection = resolve_selection(ini(tmp_path, "[rl]\ncontrolled_nodes =\n"),
                                  observation_preset="local_links_v1")
    assert selection.observation_preset == "local_links_v1"


def test_missing_run_config_is_reported(tmp_path):
    # QUESTION: configparser.read() silently skips a missing file, so a typo'd
    # run.ini path resolves to an all-default selection in "legacy" mode
    # (config.py:28-31) instead of failing before launch; with a non-default
    # selection the error blames missing controlled_nodes instead of the path.
    # The C++ loader throws "Cannot open config file" (src/util/ini-parser.cc).
    with pytest.raises((FileNotFoundError, ValueError), match="not found|Cannot open"):
        resolve_selection(str(tmp_path / "missing" / "run.ini"),
                          observation_preset="local_links_v1")


# --- Description and helpers --------------------------------------------------------

def test_describe_defaults_and_json_roundtrip():
    described = RlSelection().describe()
    assert described["source"] == {k: "default" for k in KEYS}
    assert json.loads(json.dumps(described)) == described
    assert isinstance(described["reward_components"], list)


def test_helper_predicates(tmp_path):
    default = resolve_selection(ini(tmp_path, CENTRAL_ONLY))
    assert not uses_custom_observation(default) and not uses_composed_reward(default)
    custom = resolve_selection(ini(tmp_path, CENTRAL_ONLY),
                               observation_preset="local_links_v1",
                               reward_components="legacy")
    assert uses_custom_observation(custom) and uses_composed_reward(custom)
    explicit_default = resolve_selection(ini(tmp_path, CENTRAL_ONLY),
                                         observation_preset="raw_links_v1")
    assert not uses_custom_observation(explicit_default)
