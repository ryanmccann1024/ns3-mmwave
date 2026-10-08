"""Line-preserving effective-INI edits (effective_inputs.edit_ini_text) at the byte level.

Contract (scripts/baselines/README.md, "What preparation does" step 3): the effective
run.ini sets [baseline] algorithm = none, [scenario] nodes_file = nodes.json, rebases
referenced files to their copied basenames and, standalone only, [rl] enabled = false;
"every other byte is kept". The simulator reads the INI with src/util/ini-parser.cc
(comments cut at the first '#' or ';', section names and keys trimmed of " \\t\\r\\n",
case-sensitive, last assignment wins); `_cpp_view` below mirrors that parser so each
test can check what the binary would see.
"""

import json

import pytest

from scripts.baselines import artifacts, config, effective_inputs, runner
from scripts.baselines.effective_inputs import edit_ini_text
from scripts.baselines.tests.conftest import MAPPING, NODES

STANDALONE_EDITS = {("baseline", "algorithm"): "none",
                    ("scenario", "nodes_file"): "nodes.json",
                    ("rl", "enabled"): "false"}


def _cpp_trim(text: str) -> str:
    return text.strip(" \t\r\n")


def _cpp_view(text: str) -> dict:
    """(section, key) -> value as src/util/ini-parser.cc parses `text`."""
    view, section = {}, ""
    for raw in text.split("\n"):
        line = raw
        for marker in ("#", ";"):
            cut = line.find(marker)
            if cut >= 0:
                line = line[:cut]
        line = _cpp_trim(line)
        if not line:
            continue
        if line[0] == "[" and line[-1] == "]":
            section = _cpp_trim(line[1:-1])
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        view[(section, _cpp_trim(key))] = _cpp_trim(value)
    return view


def _assert_semantics(before: str, after: str, edits: dict) -> None:
    """Every edited key has its new value; every other key the simulator reads is unchanged."""
    old, new = _cpp_view(before), _cpp_view(after)
    for key, value in edits.items():
        assert new[key] == value, key
    assert {k: v for k, v in new.items() if k not in edits} == {
        k: v for k, v in old.items() if k not in edits}


def _changed(before: str, after: str) -> list:
    return [(a, b) for a, b in zip(before.splitlines(keepends=True),
                                   after.splitlines(keepends=True)) if a != b]


# --- in-place edits ------------------------------------------------------------------

def test_crlf_file_keeps_crlf_on_edited_inserted_and_appended_lines():
    text = ("[scenario]\r\nname = crlf\r\n\r\n[rl]\r\nenabled = true   # on\r\n"
            "\r\n[baseline]\r\nalgorithm = geometric\r\n")
    after = edit_ini_text(text, STANDALONE_EDITS)
    assert after == ("[scenario]\r\nname = crlf\r\nnodes_file = nodes.json\r\n\r\n"
                     "[rl]\r\nenabled = false   # on\r\n\r\n"
                     "[baseline]\r\nalgorithm = none\r\n")
    assert "\n" not in after.replace("\r\n", "")
    _assert_semantics(text, after, STANDALONE_EDITS)


def test_crlf_file_appends_a_new_section_with_crlf():
    text = "[scenario]\r\nname = x\r\n"
    after = edit_ini_text(text, {("rl", "enabled"): "false"})
    assert after == "[scenario]\r\nname = x\r\n\r\n[rl]\r\nenabled = false\r\n"


def test_missing_final_newline_after_a_comment_does_not_glue_the_new_header():
    text = "[baseline]\nalgorithm = geometric\n# trailing note"
    after = edit_ini_text(text, {("baseline", "algorithm"): "none",
                                 ("rl", "enabled"): "false"})
    assert after == ("[baseline]\nalgorithm = none\n# trailing note\n\n"
                     "[rl]\nenabled = false\n")
    _assert_semantics(text, after, {("baseline", "algorithm"): "none",
                                    ("rl", "enabled"): "false"})


def test_missing_final_newline_on_the_edited_key_itself():
    text = "[rl]\nenabled = true"
    after = edit_ini_text(text, {("rl", "enabled"): "false"})
    assert after.rstrip("\n") == "[rl]\nenabled = false"
    assert after.count("\n") <= 2


@pytest.mark.parametrize("line,expected", [
    ("enabled = true   # keep this note", "enabled = false   # keep this note"),
    ("enabled = true ; semicolon note", "enabled = false ; semicolon note"),
    ("enabled = true# glued hash", "enabled = false# glued hash"),
    ("enabled = true;glued semicolon", "enabled = false;glued semicolon"),
    ("enabled = true  # a = b ; c", "enabled = false  # a = b ; c"),
    ("enabled   =   true", "enabled   =   false"),
    ("enabled =\ttrue\t# tabbed", "enabled =\tfalse\t# tabbed"),
    ("enabled = some long value with spaces", "enabled = false"),
])
def test_inline_comments_and_spacing_are_kept_around_the_new_value(line, expected):
    text = f"[rl]\n{line}\nx_min = 0.0\n"
    after = edit_ini_text(text, {("rl", "enabled"): "false"})
    assert after == f"[rl]\n{expected}\nx_min = 0.0\n"
    _assert_semantics(text, after, {("rl", "enabled"): "false"})


def test_blank_value_is_filled():
    text = "[baseline]\nalgorithm =\nobjective = coverage\n"
    after = edit_ini_text(text, {("baseline", "algorithm"): "none"})
    assert after == "[baseline]\nalgorithm = none\nobjective = coverage\n"


def test_value_comment_containing_equals_is_not_mistaken_for_the_assignment():
    text = "[scenario]\nnodes_file = data/topo.json # was = old.json\n"
    after = edit_ini_text(text, {("scenario", "nodes_file"): "nodes.json"})
    assert after == "[scenario]\nnodes_file = nodes.json # was = old.json\n"


# --- section and key matching ----------------------------------------------------------

def test_header_whitespace_and_comment_match_the_simulator_section():
    text = "[ rl ]   # policy knobs\nenabled = true\n"
    after = edit_ini_text(text, {("rl", "enabled"): "false"})
    assert after == "[ rl ]   # policy knobs\nenabled = false\n"
    assert _cpp_view(after)[("rl", "enabled")] == "false"


def test_section_names_are_case_sensitive_like_the_simulator():
    text = "[RL]\nenabled = true\n"
    after = edit_ini_text(text, {("rl", "enabled"): "false"})
    assert after == "[RL]\nenabled = true\n\n[rl]\nenabled = false\n"
    assert _cpp_view(after)[("RL", "enabled")] == "true"
    assert _cpp_view(after)[("rl", "enabled")] == "false"


def test_differently_cased_key_is_untouched_and_the_real_key_is_added():
    text = "[rl]\nEnabled = true\nx_min = 0.0\n"
    after = edit_ini_text(text, {("rl", "enabled"): "false"})
    assert after == "[rl]\nEnabled = true\nx_min = 0.0\nenabled = false\n"
    _assert_semantics(text, after, {("rl", "enabled"): "false"})


def test_same_key_names_in_other_sections_are_untouched():
    text = ("[scenario]\nnodes_file = nodes.json\n\n[routing]\nalgorithm = min_hop\n\n"
            "[traffic]\nenabled = true\nnodes_file = other.json\n\n"
            "[rl]\nenabled = true\n\n[baseline]\nalgorithm = geometric\n")
    after = edit_ini_text(text, {**STANDALONE_EDITS,
                                 ("scenario", "nodes_file"): "nodes.json"})
    view = _cpp_view(after)
    assert view[("routing", "algorithm")] == "min_hop"
    assert view[("traffic", "enabled")] == "true"
    assert view[("traffic", "nodes_file")] == "other.json"
    assert _changed(text, after) == [("enabled = true\n", "enabled = false\n"),
                                     ("algorithm = geometric\n", "algorithm = none\n")]


def test_absent_baseline_section_is_appended_and_routing_algorithm_kept():
    text = "[scenario]\nnodes_file = nodes.json\n\n[routing]\nalgorithm = min_hop\n"
    after = edit_ini_text(text, {("baseline", "algorithm"): "none"})
    assert after == text + "\n[baseline]\nalgorithm = none\n"
    assert _cpp_view(after)[("routing", "algorithm")] == "min_hop"


def test_commented_out_key_stays_a_comment_and_the_key_is_inserted_after_the_last_key():
    text = "[rl]\nx_min = 0.0\n# enabled = true\n\n[baseline]\nalgorithm = geometric\n"
    after = edit_ini_text(text, {("rl", "enabled"): "false"})
    assert after == ("[rl]\nx_min = 0.0\nenabled = false\n# enabled = true\n\n"
                     "[baseline]\nalgorithm = geometric\n")


def test_key_added_to_an_empty_section_follows_its_header():
    text = "[rl]\n\n[baseline]\nalgorithm = geometric\n"
    after = edit_ini_text(text, {("rl", "enabled"): "false"})
    assert after == "[rl]\nenabled = false\n\n[baseline]\nalgorithm = geometric\n"


def test_empty_file_gets_every_section_and_parses_strictly(tmp_path):
    after = edit_ini_text("", STANDALONE_EDITS)
    assert _cpp_view(after) == STANDALONE_EDITS
    path = tmp_path / "run.ini"
    path.write_text(after)
    parsed = config.read_ini(path)
    assert config.ini_value(parsed, "baseline", "algorithm") == "none"


# --- whole-file properties ---------------------------------------------------------------

FULL_INI = """# header comment
[scenario]
name = full   ; trailing
seed = 3
nodes_file = topo/layout.json
buildings_file = /abs/b.json   # absolute
jammers_file = j/jam.json

[channel]
band = sub-6

[rl]
enabled = true
controlled_nodes = a, b

[baseline]
algorithm = geometric   # chosen
objective = coverage
mapping_file = maps/m.json

[output]
dir = somewhere
"""

FULL_EDITS = {**STANDALONE_EDITS, ("scenario", "buildings_file"): "b.json",
              ("scenario", "jammers_file"): "jam.json",
              ("baseline", "mapping_file"): "m.json"}


def test_only_edited_lines_change_when_every_key_is_present():
    after = edit_ini_text(FULL_INI, FULL_EDITS)
    assert len(after.splitlines()) == len(FULL_INI.splitlines())
    assert [b for _, b in _changed(FULL_INI, after)] == [
        "nodes_file = nodes.json\n", "buildings_file = b.json   # absolute\n",
        "jammers_file = jam.json\n", "enabled = false\n",
        "algorithm = none   # chosen\n", "mapping_file = m.json\n"]
    _assert_semantics(FULL_INI, after, FULL_EDITS)


@pytest.mark.parametrize("text", [FULL_INI, FULL_INI.replace("\n", "\r\n"),
                                  "[scenario]\nname = x", "",
                                  "[RL]\nEnabled = true\n[ baseline ]\n"])
def test_edits_are_idempotent(text):
    once = edit_ini_text(text, FULL_EDITS)
    assert edit_ini_text(once, FULL_EDITS) == once
    assert {k: _cpp_view(once)[k] for k in FULL_EDITS} == FULL_EDITS


def test_ini_edits_per_mode_and_assets(tmp_path):
    root = tmp_path / "s"
    (root / "maps").mkdir(parents=True)
    (root / "run.ini").write_text("[scenario]\nbuildings_file = /x/b.json\n")
    files = effective_inputs.ScenarioFiles(
        run_config=root / "run.ini", nodes=root / "n.json", buildings=tmp_path / "b.json",
        jammers=None, mapping=root / "maps" / "m.json")
    assert effective_inputs.ini_edits(files, "standalone") == {
        ("baseline", "algorithm"): "none", ("scenario", "nodes_file"): "nodes.json",
        ("rl", "enabled"): "false", ("scenario", "buildings_file"): "b.json",
        ("baseline", "mapping_file"): "m.json"}
    evaluation = effective_inputs.ini_edits(files, "evaluation")
    assert ("rl", "enabled") not in evaluation
    assert evaluation[("scenario", "nodes_file")] == "nodes.json"


# --- line splitting must match the simulator ----------------------------------------------
# edit_ini_text must split lines only at '\n', like the simulator (std::getline) and
# configparser; a form feed inside a comment must not make its tail look like a key line.

FORM_FEED_INI = ("[scenario]\nseed = 1\nnodes_file = nodes.json\n\n"
                 "[baseline]\n# was\x0calgorithm = geometric\nalgorithm = geometric\n")


@pytest.mark.parametrize("separator", ["\x0c", "\x0b", "\x1c", "\x85", " "])
def test_only_newline_separates_lines(separator):
    text = FORM_FEED_INI.replace("\x0c", separator)
    after = edit_ini_text(text, {("baseline", "algorithm"): "none"})
    assert _cpp_view(after)[("baseline", "algorithm")] == "none"


def test_form_feed_comment_keeps_the_effective_ini_active(tmp_path, fake_child, stub_planner):
    root = tmp_path / "s"
    root.mkdir()
    (root / "nodes.json").write_text(json.dumps(NODES))
    (root / "mapping.json").write_text(json.dumps(MAPPING))
    text = FORM_FEED_INI + ("objective = coverage\nmovable_nodes = uav-a\n"
                            "mapping_file = mapping.json\n\n[rl]\nx_min = 0.0\nx_max = 400.0\n"
                            "y_min = 0.0\ny_max = 400.0\n")
    (root / "run.ini").write_text(text)
    out = tmp_path / "run"
    code = runner.main(["--sim-binary", str(fake_child), "--run-config",
                        str(root / "run.ini"), "--output-dir", str(out)])
    effective = (out / "effective-inputs/run.ini").read_text()
    assert _cpp_view(effective)[("baseline", "algorithm")] == "none"
    assert code == 0, artifacts.read_json(out / "baseline_manifest.json")["error"]
