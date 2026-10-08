"""INI structure rules of config.read_ini/load_baseline and parity with the C++ loader.

Expectations come from scripts/baselines/README.md ("The [baseline] section": strict
rejection of duplicates, ':' assignments and continuation lines), scripts/CLAUDE.md
(strip_inline_comment matches the C++ loader), and src/util/ini-parser.{h,cc}: comments
start at the first '#' or ';' anywhere on a line and are stripped *before* the line is
classified as a header or key, so a value can never contain '#' or ';'.
"""

import pytest

from scripts.baselines import config
from scripts.baselines.config import ConfigError
from scripts.baselines.tests.conftest import AREA, SCENARIO_SECTIONS, scenario_ini


def _ini(tmp_path, text, name="run.ini"):
    path = tmp_path / name
    path.write_text(text)
    return path


ACTIVE = "algorithm = geometric\nobjective = coverage\nmovable_nodes = uav-a\n"


@pytest.mark.parametrize("raw,expected", [
    ("geometric#x", "geometric"),
    ("geometric;x", "geometric"),
    ("geometric ; a # b", "geometric"),
    ("\tgeometric\t# tab separated", "geometric"),
    ("geometric # x = optimization", "geometric"),
])
def test_inline_comment_markers_match_cpp(tmp_path, raw, expected):
    # ini-parser.cc truncates at the first '#' then the first ';', then trims " \t\r\n".
    cfg = config.load_baseline(_ini(tmp_path, f"[baseline]\nalgorithm = {raw}\n"))
    assert cfg.algorithm == expected


def test_value_cannot_contain_comment_characters(tmp_path):
    # ini-parser.h: "Because comments are stripped first, a value cannot contain # or ;".
    cfg = config.load_baseline(_ini(tmp_path, "[baseline]\nmapping_file = maps#1.json\n"))
    assert cfg.mapping_file.name == "maps"
    cfg = config.load_baseline(_ini(tmp_path, "[baseline]\nmapping_file = a;b.json\n"))
    assert cfg.mapping_file.name == "a"


def test_value_may_contain_a_colon(tmp_path):
    # Only `key: value` *assignments* are rejected; ':' inside an '=' value is data.
    cfg = config.load_baseline(_ini(tmp_path, "[baseline]\nmapping_file = maps:v2.json\n"))
    assert cfg.mapping_file.name == "maps:v2.json"


def test_full_line_and_indented_comments_are_ignored(tmp_path):
    text = ("[baseline]\n# algorithm = optimization\n; objective = resilience\n"
            "algorithm = geometric\n    # an indented comment is not a continuation\n"
            "objective = coverage\n\t; tab-indented comment\nmovable_nodes = uav-a\n")
    cfg = config.load_baseline(_ini(tmp_path, text))
    assert (cfg.algorithm, cfg.objective, cfg.movable_nodes) == (
        "geometric", "coverage", ("uav-a",))


def test_crlf_line_endings_parse_like_lf(tmp_path):
    path = tmp_path / "run.ini"
    path.write_bytes(("[baseline]\r\n" + ACTIVE.replace("\n", "\r\n")).encode())
    cfg = config.load_baseline(path)
    assert (cfg.algorithm, cfg.objective, cfg.movable_nodes) == (
        "geometric", "coverage", ("uav-a",))


def test_indented_line_after_blank_line_is_a_rejected_continuation(tmp_path):
    text = "[baseline]\nalgorithm = geometric\n\n  objective = coverage\n"
    with pytest.raises(ConfigError, match="indented"):
        config.load_baseline(_ini(tmp_path, text))


def test_continuation_in_another_section_is_rejected(tmp_path):
    text = SCENARIO_SECTIONS.replace("name = baseline-synthetic",
                                     "name = baseline\n  synthetic")
    with pytest.raises(ConfigError, match="indented"):
        config.load_baseline(_ini(tmp_path, text))


def test_colon_assignment_in_another_section_is_rejected(tmp_path):
    text = SCENARIO_SECTIONS.replace("tick_s = 0.1", "tick_s: 0.1")
    with pytest.raises(ConfigError):
        config.load_baseline(_ini(tmp_path, text))


def test_duplicate_other_section_is_rejected(tmp_path):
    text = scenario_ini() + "\n[rl]\nx_min = 5\n"
    with pytest.raises(ConfigError, match="already exists"):
        config.read_ini(_ini(tmp_path, text))


def test_duplicate_key_differing_only_in_whitespace_is_rejected(tmp_path):
    text = "[baseline]\nobjective = coverage\nobjective\t=   balanced\n"
    with pytest.raises(ConfigError, match="already exists"):
        config.load_baseline(_ini(tmp_path, text))


def test_commented_out_duplicate_is_not_a_duplicate(tmp_path):
    text = "[baseline]\nobjective = coverage\n#objective = balanced\n"
    assert config.load_baseline(_ini(tmp_path, text)).objective == "coverage"


def test_section_names_are_case_sensitive_like_cpp(tmp_path):
    # C++ IniMap keys are exact strings; [Baseline] is not [baseline] there either.
    cfg = config.load_baseline(_ini(tmp_path, "[Baseline]\nalgorithm = geometric\n"))
    assert cfg.algorithm == "none"


def test_key_line_without_equals_is_rejected(tmp_path):
    with pytest.raises(ConfigError):
        config.load_baseline(_ini(tmp_path, "[baseline]\nalgorithm\n"))


def test_comment_before_the_equals_sign_is_not_silently_dropped(tmp_path):
    # C++ would read `objective` with no '=' and skip it; Python must not accept a
    # different key silently.
    with pytest.raises(ConfigError, match="unknown \\[baseline\\] key"):
        config.load_baseline(_ini(tmp_path, "[baseline]\nobjective # note = coverage\n"))


def test_missing_run_config(tmp_path):
    with pytest.raises(ConfigError, match="run config not found"):
        config.load_baseline(tmp_path / "absent.ini")
    with pytest.raises(ConfigError, match="run config not found"):
        config.read_ini(tmp_path)


@pytest.mark.parametrize("header", ["[baseline] # note", "[baseline] ; note",
                                    "[baseline]# note"])
def test_header_with_trailing_comment_is_the_baseline_section(tmp_path, header):
    cfg = config.load_baseline(_ini(tmp_path, f"{header}\n{ACTIVE}"))
    assert cfg.algorithm == "geometric"


# A header comment containing ']' must not change the section name: the C++ parser strips
# the comment first and reads [baseline].
@pytest.mark.parametrize("header", ["[baseline] ; see [rl] notes",
                                    "[baseline] # options listed in [docs]"])
def test_header_comment_containing_bracket_matches_cpp(tmp_path, header):
    path = _ini(tmp_path, f"{header}\n{ACTIVE}")
    try:
        cfg = config.load_baseline(path)
    except ConfigError:
        return  # failing loudly is acceptable; silently reading `none` is not
    assert cfg.algorithm == "geometric"


# Same for [rl]: the explicit bounds the rl_bounds geofence needs must still be read.
def test_rl_header_comment_containing_bracket_matches_cpp(tmp_path):
    text = ("[rl] # bounds in [m]\nx_min = 0.0\nx_max = 400.0\n"
            "y_min = 0.0\ny_max = 400.0\n")
    try:
        bounds = config.explicit_rl_bounds(config.read_ini(_ini(tmp_path, text)))
    except ConfigError:
        return
    assert bounds == AREA
