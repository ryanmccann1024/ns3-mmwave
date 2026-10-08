"""run.ini readers and scenario identity (scripts/rl/env/config.py).

Spec: scripts/rl/env/CLAUDE.md ("config.py ... Must follow the C++ INI
conventions, including inline comments and nodes_file resolved relative to
run.ini"), scripts/rl/CLAUDE.md (scenario identity = SHA-256 of run.ini / nodes /
buildings / jammers; last two null when unconfigured; compared by digest, not
path). The C++ truth is src/util/ini-parser.{h,cc}, src/util/string-utils.cc
(resolvePath, dirOf) and src/config/config-loader.cc.
"""

import configparser
import hashlib
import os
import shutil
from pathlib import Path

import pytest

from scripts.rl.env.config import (
    read_action_profile, read_control_mode, read_rl_bounds, read_rl_selection,
    read_scenario_identity, read_scenario_seed,
)

NODES_JSON = '[{"id": "a", "position": {"x": 0, "y": 0, "z": 10}}]\n'
CPP_BOUND_DEFAULTS = {"x_min": -1000.0, "x_max": 2000.0, "y_min": -1000.0,
                      "y_max": 1000.0, "z_min": 0.0, "z_max": 100.0}


def cpp_parse_ini(text: str) -> dict[str, dict[str, str]]:
    """Line-for-line model of mesh_sim::parseIni (src/util/ini-parser.cc)."""
    sections: dict[str, dict[str, str]] = {}
    section = ""
    for line in text.split("\n"):
        for marker in ("#", ";"):
            cut = line.find(marker)
            if cut != -1:
                line = line[:cut]
        line = line.strip(" \t\r\n")
        if not line:
            continue
        if line[0] == "[" and line[-1] == "]":
            section = line[1:-1].strip(" \t\r\n")
            continue
        eq = line.find("=")
        if eq == -1:
            continue
        key, value = line[:eq].strip(" \t\r\n"), line[eq + 1:].strip(" \t\r\n")
        sections.setdefault(section, {})[key] = value
    return sections


def cpp_control_mode(text: str) -> str:
    """config-loader.cc:353-355: presence of [rl] controlled_nodes."""
    return "centralized" if "controlled_nodes" in cpp_parse_ini(text).get("rl", {}) \
        else "legacy"


def cpp_bounds(text: str) -> tuple:
    rl = cpp_parse_ini(text).get("rl", {})
    values = {k: float(rl.get(k, d)) for k, d in CPP_BOUND_DEFAULTS.items()}
    return tuple((values[f"{a}_min"], values[f"{a}_max"]) for a in "xyz")


def write(tmp_path: Path, text: str, name: str = "run.ini") -> str:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, newline="")
    return str(path)


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --- read_scenario_seed --------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("[scenario]\nseed = 7\n", 7),
    ("[scenario]\nseed = 7 ; inline\n", 7),
    ("[scenario]\nseed=7#inline\n", 7),
    ("[scenario]\n\tseed\t=\t7\t\n", 7),
    ("[scenario]\r\nseed = 7\r\n", 7),
    ("[scenario]\nseed = 0\n", 0),
    ("[scenario]\nname = x\n", None),
    ("[rl]\nseed = 7\n", None),          # wrong section
    ("[scenario]\nseed =\n", None),
    ("[scenario]\nseed = ; none\n", None),
    ("[scenario]\nseed = seven\n", None),
    ("[scenario]\nseed = 1.5\n", None),
])
def test_read_scenario_seed(tmp_path, text, expected):
    assert read_scenario_seed(write(tmp_path, text)) == expected


# --- read_rl_bounds ------------------------------------------------------------------

def test_bounds_defaults_without_rl_section(tmp_path):
    assert read_rl_bounds(write(tmp_path, "[scenario]\nseed = 1\n")) == (
        (-1000.0, 2000.0), (-1000.0, 1000.0), (0.0, 100.0))


def test_bounds_all_six_with_mixed_comments_and_spacing(tmp_path):
    text = ("[rl]\nx_min=-5;a\nx_max = 5 # b\ny_min\t=\t-1e2\ny_max = 1E2 ; c\n"
            "z_min = 0.5\nz_max = 30 #\n")
    assert read_rl_bounds(write(tmp_path, text)) == (
        (-5.0, 5.0), (-100.0, 100.0), (0.5, 30.0))


@pytest.mark.parametrize("line", ["x_min =", "x_min = ; nothing", "x_min = ten"])
def test_unparseable_bound_raises_like_cpp_stod(tmp_path, line):
    # C++ std::stod("") / stod("ten") throws, so the run cannot start either.
    with pytest.raises(ValueError):
        read_rl_bounds(write(tmp_path, f"[rl]\n{line}\n"))


# --- read_action_profile / read_control_mode / read_rl_selection ---------------------

@pytest.mark.parametrize("text,expected", [
    ("[scenario]\nseed = 1\n", "move_2d"),
    ("[rl]\naction_profile = move_3d ; reserved\n", "move_3d"),
    ("[rl]\naction_profile=move_2d#x\n", "move_2d"),
])
def test_read_action_profile(tmp_path, text, expected):
    assert read_action_profile(write(tmp_path, text)) == expected


def test_blank_action_profile_matches_cpp_value(tmp_path):
    # QUESTION: C++ iniGet returns "" for a present-but-blank key, and
    # rl-control.cc:139 then rejects action_profile ''. read_action_profile
    # (config.py:115) maps blank to "move_2d", so experiment.py's profile check
    # accepts a scenario the simulator refuses. Docstring says "when absent".
    text = "[rl]\naction_profile = ; blank\n"
    assert read_action_profile(write(tmp_path, text)) == \
        cpp_parse_ini(text)["rl"]["action_profile"]


@pytest.mark.parametrize("text,expected", [
    ("[rl]\ncontrolled_nodes = a, b\n", "centralized"),
    ("[rl]\ncontrolled_nodes =\n", "centralized"),           # presence, not value
    ("[rl]\ncontrolled_nodes = a # trailing\n", "centralized"),
    ("[rl]\n; controlled_nodes = a\n", "legacy"),
    ("[rl]\n   # controlled_nodes = a\n", "legacy"),
    ("[rl]\ncontrolled_node_id = a\n", "legacy"),
    ("[scenario]\ncontrolled_nodes = a\n", "legacy"),         # wrong section
    ("[rl] ; header comment\ncontrolled_nodes = a\n", "centralized"),
    ("[rl]\r\ncontrolled_nodes = a\r\n", "centralized"),
])
def test_control_mode_documented_cases(tmp_path, text, expected):
    assert cpp_control_mode(text) == expected      # the model agrees with the C++ rule
    assert read_control_mode(write(tmp_path, text)) == expected


def _loud(exc: BaseException) -> bool:
    return isinstance(exc, (ValueError, configparser.Error, OSError))


# Inputs the C++ parser accepts. Python must either agree with the C++ result or
# fail loudly (as scripts/baselines/config.py read_ini does); a silently different
# answer is a divergence.
PARITY_CASES = {
    "whitespace_in_header": "[ rl ]\ncontrolled_nodes = a\n",
    "uppercase_key": "[rl]\nControlled_Nodes = a\n",
    "colon_delimiter": "[rl]\ncontrolled_nodes: a\n",
    "default_section": "[DEFAULT]\ncontrolled_nodes = a\n[rl]\nx_min = 0\n",
    "indented_key_after_value": "[rl]\nx_min = 5\n  controlled_nodes = a\n",
    "duplicate_key": "[rl]\ncontrolled_nodes = a\ncontrolled_nodes = b\n",
    "duplicate_section": "[rl]\nx_min = 1\n[rl]\ncontrolled_nodes = a\n",
    "line_without_equals": "[rl]\njunk\ncontrolled_nodes = a\n",
    "key_before_any_section": "name = x\n[rl]\ncontrolled_nodes = a\n",
}


@pytest.mark.parametrize("case", sorted(PARITY_CASES))
def test_control_mode_matches_cpp_or_fails_loudly(tmp_path, case):
    # read_control_mode must agree with the simulator's INI rules (header whitespace,
    # key case, ':' lines, [DEFAULT], indented keys) or fail loudly.
    text = PARITY_CASES[case]
    try:
        mode = read_control_mode(write(tmp_path, text))
    except Exception as exc:  # noqa: BLE001 - loud failure is acceptable
        assert _loud(exc), exc
        return
    assert mode == cpp_control_mode(text)


BOUND_PARITY_CASES = {
    "uppercase_key": "[rl]\nX_MIN = 5\n",
    "colon_delimiter": "[rl]\nx_min: 5\n",
    "default_section": "[DEFAULT]\nx_min = 5\n[rl]\nx_max = 50\n",
    "whitespace_in_header": "[ rl ]\nx_min = 5\n",
    "duplicate_key_last_wins": "[rl]\nx_min = 1\nx_min = 2\n",
    "indented_continuation": "[rl]\nx_min = 5\n  x_max = 50\n",
}


@pytest.mark.parametrize("case", sorted(BOUND_PARITY_CASES))
def test_bounds_match_cpp_or_fail_loudly(tmp_path, case):
    # Legacy-mode action masks are built from these bounds (mesh_env.py), so they
    # must match the simulator's clamping or fail loudly.
    text = BOUND_PARITY_CASES[case]
    try:
        bounds = read_rl_bounds(write(tmp_path, text))
    except Exception as exc:  # noqa: BLE001
        assert _loud(exc), exc
        return
    assert bounds == cpp_bounds(text)


def test_read_rl_selection_omits_blank_and_comment_only_keys(tmp_path):
    text = ("[rl]\nobservation_preset =\nreward_components = ; none\n"
            "telemetry = steps # on\ntelemetry_every = 2\ncontrolled_nodes = a\n"
            "reward_type = throughput\n")
    assert read_rl_selection(write(tmp_path, text)) == {"telemetry": "steps",
                                                        "telemetry_every": "2"}


def test_read_rl_selection_without_rl_section(tmp_path):
    assert read_rl_selection(write(tmp_path, "[scenario]\nseed = 1\n")) == {}


# --- Scenario identity ---------------------------------------------------------------

def scenario(directory: Path, ini_text: str = "[scenario]\nseed = 1\n",
             nodes_name: str = "nodes.json", nodes_text: str = NODES_JSON) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "run.ini").write_text(ini_text)
    if nodes_name:
        nodes = directory / nodes_name
        nodes.parent.mkdir(parents=True, exist_ok=True)
        nodes.write_text(nodes_text)
    return directory / "run.ini"


def test_identity_default_nodes_file_and_null_optional_digests(tmp_path):
    ini = scenario(tmp_path / "s")
    identity = read_scenario_identity(str(ini))
    assert identity == {
        "run_config": str(ini.resolve()),
        "run_ini_sha256": sha(ini),
        "nodes_json_sha256": sha(tmp_path / "s" / "nodes.json"),
        "buildings_json_sha256": None,
        "jammers_json_sha256": None,
    }


@pytest.mark.parametrize("value,location", [
    ("sub/n.json", "s/sub/n.json"),
    ("../shared/n.json", "shared/n.json"),
    ("./n.json ; dot", "s/n.json"),
])
def test_identity_resolves_nodes_relative_to_run_ini(tmp_path, value, location):
    target = tmp_path / location
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('["distinct"]\n')
    ini = scenario(tmp_path / "s", f"[scenario]\nnodes_file = {value}\n", nodes_name="")
    assert read_scenario_identity(str(ini))["nodes_json_sha256"] == sha(target)


def test_identity_is_independent_of_cwd_and_relative_run_config(tmp_path, monkeypatch):
    ini = scenario(tmp_path / "s")
    decoy = tmp_path / "elsewhere"
    decoy.mkdir()
    (decoy / "nodes.json").write_text('["decoy"]\n')
    monkeypatch.chdir(decoy)
    identity = read_scenario_identity(os.path.relpath(ini, decoy))
    assert identity["run_config"] == str(ini.resolve())
    assert Path(identity["run_config"]).is_absolute()
    assert identity["nodes_json_sha256"] == sha(tmp_path / "s" / "nodes.json")


def test_identity_digests_are_path_independent(tmp_path):
    first = scenario(tmp_path / "one")
    second = tmp_path / "two"
    shutil.copytree(tmp_path / "one", second)
    a = read_scenario_identity(str(first))
    b = read_scenario_identity(str(second / "run.ini"))
    assert a["run_config"] != b["run_config"]
    assert {k: v for k, v in a.items() if k != "run_config"} == \
        {k: v for k, v in b.items() if k != "run_config"}


def test_identity_tracks_every_byte_of_run_ini_and_nodes(tmp_path):
    ini = scenario(tmp_path / "s")
    before = read_scenario_identity(str(ini))
    ini.write_text(ini.read_text() + "; comment only\n")
    after_ini = read_scenario_identity(str(ini))
    assert after_ini["run_ini_sha256"] != before["run_ini_sha256"]
    assert after_ini["nodes_json_sha256"] == before["nodes_json_sha256"]
    (tmp_path / "s" / "nodes.json").write_text(NODES_JSON + " ")
    after_nodes = read_scenario_identity(str(ini))
    assert after_nodes["nodes_json_sha256"] != before["nodes_json_sha256"]
    for digest in ("run_ini_sha256", "nodes_json_sha256"):
        assert len(after_nodes[digest]) == 64
        assert after_nodes[digest] == after_nodes[digest].lower()


def test_identity_optional_files_resolved_relative_with_comments(tmp_path):
    ini = scenario(tmp_path / "s", "[scenario]\nbuildings_file = b.json ; blk\n"
                                   "jammers_file = ../j.json # jam\n")
    (tmp_path / "s" / "b.json").write_text("[]\n")
    (tmp_path / "j.json").write_text('[{"id": "j"}]\n')
    identity = read_scenario_identity(str(ini))
    assert identity["buildings_json_sha256"] == sha(tmp_path / "s" / "b.json")
    assert identity["jammers_json_sha256"] == sha(tmp_path / "j.json")


def test_identity_missing_run_config(tmp_path):
    with pytest.raises(FileNotFoundError, match="run config not found"):
        read_scenario_identity(str(tmp_path / "absent.ini"))


def test_identity_nodes_file_that_is_a_directory(tmp_path):
    ini = scenario(tmp_path / "s", "[scenario]\nnodes_file = sub\n", nodes_name="")
    (tmp_path / "s" / "sub").mkdir()
    with pytest.raises(FileNotFoundError, match="nodes file not found"):
        read_scenario_identity(str(ini))


def test_identity_blank_nodes_file_matches_cpp(tmp_path):
    # QUESTION: C++ iniGet returns "" for "nodes_file =", resolvePath(base, "")
    # returns "" and the loader throws "Cannot open nodes file" (config-loader.cc:369-376).
    # _scenario_file (config.py:60) treats blank as the default nodes.json and hashes
    # it, so identity succeeds for a scenario the simulator rejects.
    ini = scenario(tmp_path / "s", "[scenario]\nnodes_file =\n")
    with pytest.raises(FileNotFoundError):
        read_scenario_identity(str(ini))


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="needs symlinks")
def test_identity_through_symlinked_run_ini_uses_cpp_base_dir(tmp_path):
    # BUG/QUESTION: EpisodeSession passes --run-config unchanged and C++ resolves
    # nodes_file against dirOf(<given path>) (string-utils.cc:76, no canonicalization),
    # but read_scenario_identity resolves the symlink first (config.py:76), so it
    # hashes a different nodes.json than the one the simulator loads.
    real = scenario(tmp_path / "real", nodes_text='["real"]\n')
    link_dir = tmp_path / "link"
    link_dir.mkdir()
    (link_dir / "nodes.json").write_text('["used-by-cpp"]\n')
    link = link_dir / "run.ini"
    link.symlink_to(real)
    identity = read_scenario_identity(str(link))
    assert identity["nodes_json_sha256"] == sha(link_dir / "nodes.json")
