"""Line-preserving effective-INI edits (effective_inputs.edit_ini_text) at the byte level.

Contract (scripts/baselines/README.md, "What preparation does" step 3): the effective
run.ini sets [baseline] algorithm = none, [scenario] nodes_file = nodes.json, rebases
referenced files to their copied basenames and, standalone only, [rl] enabled = false;
"every other byte is kept". The simulator reads the INI with src/util/ini-parser.cc
(comments cut at the first '#' or ';', section names and keys trimmed of " \\t\\r\\n",
case-sensitive, last assignment wins); a shared fixture invokes the compiled C++ parser so semantic assertions
check what the simulator actually reads.
"""
import pytest
from scripts.baselines.effective_inputs import edit_ini_text
STANDALONE_EDITS = {('baseline', 'algorithm'): 'none', ('scenario', 'nodes_file'): 'nodes.json', ('rl', 'enabled'): 'false'}

def _assert_semantics(before: str, after: str, edits: dict, *, cpp_ini_view) -> None:
    """Every edited key has its new value; every other key the simulator reads is unchanged."""
    old, new = (cpp_ini_view(before), cpp_ini_view(after))
    for key, value in edits.items():
        assert new[key] == value, key
    assert {k: v for k, v in new.items() if k not in edits} == {k: v for k, v in old.items() if k not in edits}

def _changed(before: str, after: str) -> list:
    return [(a, b) for a, b in zip(before.splitlines(keepends=True), after.splitlines(keepends=True)) if a != b]

def test_missing_final_newline_after_a_comment_does_not_glue_the_new_header(*, cpp_ini_view):
    text = '[baseline]\nalgorithm = geometric\n# trailing note'
    after = edit_ini_text(text, {('baseline', 'algorithm'): 'none', ('rl', 'enabled'): 'false'})
    assert after == '[baseline]\nalgorithm = none\n# trailing note\n\n[rl]\nenabled = false\n'
    _assert_semantics(text, after, {('baseline', 'algorithm'): 'none', ('rl', 'enabled'): 'false'}, cpp_ini_view=cpp_ini_view)

def test_missing_final_newline_on_the_edited_key_itself():
    text = '[rl]\nenabled = true'
    after = edit_ini_text(text, {('rl', 'enabled'): 'false'})
    assert after.rstrip('\n') == '[rl]\nenabled = false'
    assert after.count('\n') <= 2

@pytest.mark.parametrize('line,expected', [('enabled = true   # keep this note', 'enabled = false   # keep this note'), ('enabled = true ; semicolon note', 'enabled = false ; semicolon note'), ('enabled = true# glued hash', 'enabled = false# glued hash'), ('enabled = true;glued semicolon', 'enabled = false;glued semicolon'), ('enabled = true  # a = b ; c', 'enabled = false  # a = b ; c'), ('enabled   =   true', 'enabled   =   false'), ('enabled =\ttrue\t# tabbed', 'enabled =\tfalse\t# tabbed'), ('enabled = some long value with spaces', 'enabled = false')])
def test_inline_comments_and_spacing_are_kept_around_the_new_value(line, expected, *, cpp_ini_view):
    text = f'[rl]\n{line}\nx_min = 0.0\n'
    after = edit_ini_text(text, {('rl', 'enabled'): 'false'})
    assert after == f'[rl]\n{expected}\nx_min = 0.0\n'
    _assert_semantics(text, after, {('rl', 'enabled'): 'false'}, cpp_ini_view=cpp_ini_view)

def test_blank_value_is_filled():
    text = '[baseline]\nalgorithm =\nobjective = coverage\n'
    after = edit_ini_text(text, {('baseline', 'algorithm'): 'none'})
    assert after == '[baseline]\nalgorithm = none\nobjective = coverage\n'

def test_same_key_names_in_other_sections_are_untouched(*, cpp_ini_view):
    text = '[scenario]\nnodes_file = nodes.json\n\n[routing]\nalgorithm = min_hop\n\n[traffic]\nenabled = true\nnodes_file = other.json\n\n[rl]\nenabled = true\n\n[baseline]\nalgorithm = geometric\n'
    after = edit_ini_text(text, {**STANDALONE_EDITS, ('scenario', 'nodes_file'): 'nodes.json'})
    view = cpp_ini_view(after)
    assert view['routing', 'algorithm'] == 'min_hop'
    assert view['traffic', 'enabled'] == 'true'
    assert view['traffic', 'nodes_file'] == 'other.json'
    assert _changed(text, after) == [('enabled = true\n', 'enabled = false\n'), ('algorithm = geometric\n', 'algorithm = none\n')]

def test_absent_baseline_section_is_appended_and_routing_algorithm_kept(*, cpp_ini_view):
    text = '[scenario]\nnodes_file = nodes.json\n\n[routing]\nalgorithm = min_hop\n'
    after = edit_ini_text(text, {('baseline', 'algorithm'): 'none'})
    assert after == text + '\n[baseline]\nalgorithm = none\n'
    assert cpp_ini_view(after)['routing', 'algorithm'] == 'min_hop'

def test_commented_out_key_stays_a_comment_and_the_key_is_inserted_after_the_last_key():
    text = '[rl]\nx_min = 0.0\n# enabled = true\n\n[baseline]\nalgorithm = geometric\n'
    after = edit_ini_text(text, {('rl', 'enabled'): 'false'})
    assert after == '[rl]\nx_min = 0.0\nenabled = false\n# enabled = true\n\n[baseline]\nalgorithm = geometric\n'

def test_key_added_to_an_empty_section_follows_its_header():
    text = '[rl]\n\n[baseline]\nalgorithm = geometric\n'
    after = edit_ini_text(text, {('rl', 'enabled'): 'false'})
    assert after == '[rl]\nenabled = false\n\n[baseline]\nalgorithm = geometric\n'
FULL_INI = '# header comment\n[scenario]\nname = full   ; trailing\nseed = 3\nnodes_file = topo/layout.json\nbuildings_file = /abs/b.json   # absolute\njammers_file = j/jam.json\n\n[channel]\nband = sub-6\n\n[rl]\nenabled = true\ncontrolled_nodes = a, b\n\n[baseline]\nalgorithm = geometric   # chosen\nobjective = coverage\nmapping_file = maps/m.json\n\n[output]\ndir = somewhere\n'
FULL_EDITS = {**STANDALONE_EDITS, ('scenario', 'buildings_file'): 'b.json', ('scenario', 'jammers_file'): 'jam.json', ('baseline', 'mapping_file'): 'm.json'}

def test_only_edited_lines_change_when_every_key_is_present(*, cpp_ini_view):
    after = edit_ini_text(FULL_INI, FULL_EDITS)
    assert len(after.splitlines()) == len(FULL_INI.splitlines())
    assert [b for _, b in _changed(FULL_INI, after)] == ['nodes_file = nodes.json\n', 'buildings_file = b.json   # absolute\n', 'jammers_file = jam.json\n', 'enabled = false\n', 'algorithm = none   # chosen\n', 'mapping_file = m.json\n']
    _assert_semantics(FULL_INI, after, FULL_EDITS, cpp_ini_view=cpp_ini_view)
