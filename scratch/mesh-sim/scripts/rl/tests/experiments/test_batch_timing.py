"""Check batch planning against native cadence and saved replay gates."""

import json
import shutil
from pathlib import Path

import pytest

from scripts.rl.experiments.config import load_matrix_v2, native_decisions
from scripts.rl.experiments.plan import build_batch_plan
from scripts.rl.policy.operation_inputs import resolve_gates
from scripts.sim_support import find_mesh_root

EXAMPLE = find_mesh_root() / "inputs/experiments/examples/coordination-smoke"
SCENARIO = "rural-coverage-3-peers"


@pytest.fixture
def example(tmp_path):
    folder = tmp_path / "smoke"
    shutil.copytree(EXAMPLE, folder)
    path = folder / "batch.json"
    return path, json.loads(path.read_text())


def _checks_only(matrix):
    matrix.update(kind="checks", rows=[])
    matrix.pop("training")
    matrix.pop("evaluation")
    matrix["seeds"].pop("training")


@pytest.mark.parametrize("consumer", ["baseline", "operation"])
def test_deployment_gate_must_match_the_selected_ini(example, consumer):
    path, matrix = example
    scenario = matrix["scenarios"][SCENARIO]
    scenario["case"]["seeds"]["201"]["gate_s"] = 1.0
    matrix["checks"] = []
    if consumer == "baseline":
        _checks_only(matrix)
    else:
        scenario.pop("baselines")
    path.write_text(json.dumps(matrix))
    with pytest.raises(
        ValueError,
        match="declared gate 1.0 s differs from native control_start_s 0.0 s",
    ):
        load_matrix_v2(path)

    source = path.with_name("run.ini").read_text()
    path.with_name("delayed.ini").write_text(
        source.replace("control_start_s = 0.0", "control_start_s = 1.0")
    )
    owner = scenario if consumer == "baseline" else matrix["rows"][0]
    owner["configs"] = {"diagnostic": {"201": "delayed.ini"}}
    path.write_text(json.dumps(matrix))
    plan = build_batch_plan(load_matrix_v2(path))
    kind = "baseline" if consumer == "baseline" else "operate"
    tasks = [
        task
        for task in plan["tasks"]
        if task["kind"] == kind and task["identity"]["seed"] == 201
    ]
    assert tasks
    for task in tasks:
        args = task["args"]
        assert Path(args[args.index("--run-config") + 1]).name == "delayed.ini"
        assert args[args.index("--gate-s") + 1] == "1.0"


@pytest.mark.parametrize("use_check_override", [False, True])
def test_replay_preserves_a_reference_gate_earlier_than_native(
    example, use_check_override
):
    path, matrix = example
    scenario = matrix["scenarios"][SCENARIO]
    case = scenario["case"]
    case["seeds"]["201"]["gate_s"] = 1.0
    scenario.pop("baselines")
    _checks_only(matrix)
    check = matrix["checks"][0]
    check["source"] = {"path": "."}
    if use_check_override:
        check["case"] = scenario.pop("case")

    ini = path.with_name("run.ini")
    ini.write_text(
        ini.read_text().replace("control_start_s = 0.0", "control_start_s = 2.0")
    )
    path.write_text(json.dumps(matrix))
    task = next(
        t
        for t in build_batch_plan(load_matrix_v2(path))["tasks"]
        if t["kind"] == "replay_gate"
    )
    args = task["args"]
    config = json.loads(args[args.index("--seed-configs-json") + 1])
    case = json.loads(args[args.index("--case-json") + 1])
    assert resolve_gates(config, case, replay=True)["seeds"]["201"]["gate_s"] == 1.0
    assert resolve_gates(config, None)["seeds"]["201"]["gate_s"] == 2.0


@pytest.mark.parametrize("interval", ["65.0", "nan", "inf", "-1.0"])
def test_batch_cadence_rejects_invalid_native_intervals(example, interval):
    path, _ = example
    ini = path.with_name("run.ini")
    assert native_decisions(ini) == 64
    ini.write_text(
        ini.read_text().replace(
            "decision_interval_s = 1.0", f"decision_interval_s = {interval}"
        )
    )
    with pytest.raises(ValueError, match="decision_interval_s"):
        load_matrix_v2(path)
