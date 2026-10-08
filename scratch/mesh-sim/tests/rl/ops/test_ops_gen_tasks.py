"""Task table construction, tolerance table, prerequisites, and comparison outcomes.

Expectations come from scripts/rl/ops/README.md "Task unit", "Exit-code
mapping", and "cluster compare versus fetch".
"""

import copy
import json
from pathlib import Path

import pytest

from scripts.rl import experiment
from scripts.rl.ops import tasks

from ._ops_gen_helpers import leaf, make_plan


@pytest.fixture
def plan(tmp_path):
    return make_plan(tmp_path, n_tasks=3)


def _step(plan, step_id):
    return next(step for step in plan["steps"] if step["id"] == step_id)


def _write(step, text):
    out = Path(step["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    (out / step["manifest"]).write_text(text)


def test_gen_indices_follow_train_order_whatever_the_evaluate_order(plan):
    shuffled = copy.deepcopy(plan)
    evaluations = [step for step in shuffled["steps"] if step["kind"] == "evaluate"]
    trains = [step for step in shuffled["steps"] if step["kind"] == "train"]
    compare = tasks.compare_step(shuffled)
    shuffled["steps"] = [compare, *reversed(evaluations), *trains]
    table = tasks.build_tasks(shuffled)
    assert [task["index"] for task in table] == [0, 1, 2]
    assert [task["id"] for task in table] == [leaf(0), leaf(1), leaf(2)]
    for task in table:
        assert task["evaluate"]["needs"] == [task["train"]["id"]]


def test_gen_only_the_train_prefix_is_stripped_from_task_ids(plan):
    _step(plan, f"train/{leaf(0)}")["id"] = "train/train/x"
    _step(plan, f"evaluate/{leaf(0)}")["needs"] = ["train/train/x"]
    assert tasks.build_tasks(plan)[0]["id"] == "train/x"


MALFORMED = [
    ("no step list", lambda plan: plan.pop("steps"), "no step list"),
    ("two compare steps",
     lambda plan: plan["steps"].append(dict(tasks.compare_step(plan), id="c2")),
     "exactly one compare step, found 2"),
    ("no compare step",
     lambda plan: plan["steps"].remove(tasks.compare_step(plan)),
     "found 0"),
    ("two evaluations of one training",
     lambda plan: plan["steps"].append(dict(_step(plan, f"evaluate/{leaf(0)}"),
                                            id="evaluate/extra")),
     "without a train step"),
    ("an evaluation that needs nothing",
     lambda plan: _step(plan, f"evaluate/{leaf(1)}").update(needs=None),
     f"no evaluate step needs train/{leaf(1)}"),
    ("only a compare step",
     lambda plan: plan.update(steps=[tasks.compare_step(plan)]), "no train steps"),
]


@pytest.mark.parametrize("mutate,message", [case[1:] for case in MALFORMED],
                         ids=[case[0] for case in MALFORMED])
def test_gen_malformed_plans_are_refused(plan, mutate, message):
    mutate(plan)
    with pytest.raises(ValueError, match=message):
        tasks.build_tasks(plan)


@pytest.mark.parametrize("args,message", [
    (["--output-dir", "/x", "--plan"], "no --plan argument"),
    ([], "no --plan argument"),
    (["--plan", "/x/other.json"], "not a experiment_plan.json path"),
])
def test_gen_plan_root_needs_a_plan_path_argument(plan, args, message):
    tasks.compare_step(plan)["args"] = args
    with pytest.raises(ValueError, match=message):
        tasks.plan_root(plan)


def test_gen_plan_root_is_the_directory_of_the_plan_argument(plan, tmp_path):
    assert tasks.plan_root(plan) == tmp_path


TOLERANCE = [("train", 0, True), ("train", 2, False), ("train", -9, False),
             ("evaluate", 0, True), ("evaluate", 2, True), ("evaluate", 1, False),
             ("evaluate", -15, False), ("compare", 2, True), ("compare", 3, False),
             ("compare", 1, False)]


@pytest.mark.parametrize("kind,code,expected", TOLERANCE)
def test_gen_tolerance_table(kind, code, expected):
    assert tasks.tolerated(kind, code) is expected


def test_gen_an_unknown_kind_names_the_valid_ones():
    with pytest.raises(ValueError, match="valid: \\['compare', 'evaluate', 'train'\\]"):
        tasks.tolerated("benchmark", 0)


def test_gen_compare_prerequisites_split_missing_and_partial(plan):
    _write(_step(plan, f"evaluate/{leaf(0)}"), json.dumps({"status": "completed"}))
    _write(_step(plan, f"evaluate/{leaf(1)}"), json.dumps({"status": "partial"}))
    _write(_step(plan, f"evaluate/{leaf(2)}"), "{broken")
    assert tasks.compare_prerequisites(plan) == {
        "ready": False, "missing": [f"evaluate/{leaf(2)}"],
        "partial": [f"evaluate/{leaf(1)}"]}


def test_gen_compare_prerequisites_are_ready_only_when_every_evaluation_is_done(plan):
    for index in range(3):
        _write(_step(plan, f"evaluate/{leaf(index)}"),
               json.dumps({"status": "completed"}))
    assert tasks.compare_prerequisites(plan) == {"ready": True, "missing": [],
                                                 "partial": []}


@pytest.mark.parametrize("text,expected", [
    (None, "absent"),
    ('{"status": "complete"}', "complete"),
    ('{"status": "incomplete"}', "incomplete"),
    ('{"status": "completed"}', "unreadable"),
    ('{"status": 1}', "unreadable"),
    ("{trunc", "unreadable"),
    ("", "unreadable"),
])
def test_gen_comparison_outcome_values(plan, text, expected):
    step = tasks.compare_step(plan)
    if text is not None:
        _write(step, text)
    outcome = tasks.comparison_outcome(plan)
    assert outcome == {"state": expected,
                       "path": str(Path(step["output_dir"]) / step["manifest"])}


@pytest.mark.parametrize("text", ["[]", "null", "\"complete\""])
def test_gen_a_non_object_comparison_is_unreadable(plan, text):
    # A comparison.json that is not an object reads as unreadable.
    _write(tasks.compare_step(plan), text)
    assert tasks.comparison_outcome(plan)["state"] == "unreadable"


def test_gen_the_train_manifest_status_is_only_reported_when_a_string(plan):
    table = tasks.build_tasks(plan)
    _write(table[0]["train"], json.dumps({"status": 3}))
    _write(table[1]["train"], "{bad")
    assert tasks.task_fs_state(table[0])["train_manifest_status"] is None
    assert tasks.task_fs_state(table[1])["train_manifest_status"] is None
    assert tasks.task_fs_state(table[2]) == {"train": ("pending", ""),
                                             "evaluate": ("pending", ""),
                                             "train_manifest_status": None}


def test_gen_a_non_object_train_manifest_reads_blocked(plan):
    # A train manifest holding a JSON array reads as a blocked step.
    table = tasks.build_tasks(plan)
    _write(table[0]["train"], "[]")
    state = tasks.task_fs_state(table[0])
    assert state["train"][0] == "blocked" and state["train_manifest_status"] is None


def test_gen_tasks_reexports_the_experiment_names_it_relies_on():
    assert tasks.PLAN_NAME == experiment.PLAN_NAME
    assert tasks.load_plan is experiment.load_plan
    assert tasks.step_state is experiment.step_state
