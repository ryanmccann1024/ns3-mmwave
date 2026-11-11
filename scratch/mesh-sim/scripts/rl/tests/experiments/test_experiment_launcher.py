"""Test the experiment CLI, Bash launcher and v1 compatibility."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.rl import experiment
from scripts.rl.experiments.plan import EXPERIMENT_PLAN_VERSION, PLAN_NAME
from scripts.rl.policy import experiment as legacy
from scripts.rl.tests.experiments.test_matrix_v2 import (
    EXAMPLE,
    MESH,
    _matrix,
    _no_children,
    _write,
)

TRACKED_V1 = MESH / "inputs/experiments/bypass-smoke-matrix.json"
LAUNCHER = MESH / "scripts/rl/run-experiments.sh"


def test_v1_facade_names_constants_and_golden_argv(tmp_path):
    for name in (
        "load_matrix",
        "build_plan",
        "step_state",
        "run_plan",
        "write_plan",
        "load_plan",
        "parse_rows",
        "automatic_run_label",
        "print_states",
        "_subprocess_execute",
        "_train_args",
        "_seeds",
    ):
        assert callable(getattr(legacy, name))
    assert (legacy.MATRIX_VERSION, legacy.PLAN_VERSION) == (1, 2)
    assert (legacy.PLAN_NAME, legacy.COMPARISON_NAME) == (
        "experiment_plan.json",
        "comparison.json",
    )
    assert (
        experiment.load_matrix is legacy.load_matrix
        and experiment.build_plan is legacy.build_plan
    )

    matrix = legacy.load_matrix(TRACKED_V1)
    root = tmp_path / "root"
    plan = legacy.build_plan(matrix, root, "/sim")
    assert list(plan) == [
        "experiment_plan_version",
        "matrix",
        "sim_binary",
        "rows_filter",
        "seeds",
        "rows",
        "steps",
        "evaluations",
    ]
    assert plan["experiment_plan_version"] == 2 and len(plan["steps"]) == 17
    row = matrix["rows"][0]
    train = plan["steps"][0]
    assert train["args"] == [
        "--sim-binary",
        "/sim",
        "--run-config",
        str(MESH / "inputs/baselines/building-bypass-smoke/run.ini"),
        "--output-dir",
        str(root.resolve() / "train/local-delivery/train-seed-101"),
        "--verbose",
        "0",
        "--observation-preset",
        "local_links_v1",
        "--reward-components",
        "delivery_ratio",
        "--reward-weights",
        "1.0",
        "--observation-parameters",
        json.dumps(row["observation_parameters"], sort_keys=True),
        "--reward-parameters",
        json.dumps(row["reward_parameters"], sort_keys=True),
        "m-ppo",
        "--total-timesteps",
        "256",
        "--n-steps",
        "64",
        "--eval-every-steps",
        "128",
        "--seed",
        "101",
        "--eval-episodes",
        "1",
        "--eval-seed",
        "201",
        "--eval-seeds",
        "201",
    ]
    assert plan["steps"][-1]["args"] == [
        "--plan",
        str(root.resolve() / PLAN_NAME),
        "--output-dir",
        str(root.resolve() / "comparison"),
    ]


def test_v1_cli_plan_keeps_plan_v2_and_takes_the_environment_binary(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("MESH_SIM_BIN", "/env/sim")
    root = tmp_path / "root"
    assert (
        experiment.main(
            ["plan", "--matrix", str(TRACKED_V1), "--output-root", str(root)]
        )
        == 0
    )
    plan = json.loads((root / PLAN_NAME).read_text())
    assert plan["experiment_plan_version"] == 2 and plan["sim_binary"] == "/env/sim"
    assert (
        experiment.main(
            [
                "run",
                "--matrix",
                str(TRACKED_V1),
                "--output-root",
                str(root),
                "--workers",
                "2",
            ]
        )
        == 1
    )
    assert "matrix version 2" in capsys.readouterr().err


def test_validate_writes_nothing_and_resolves_paths_with_spaces(
    tmp_path, multi_run_config, monkeypatch, capsys, sim_binary
):
    folder = tmp_path / "my batches"
    _write(folder, _matrix(multi_run_config))
    monkeypatch.chdir(tmp_path)
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    assert experiment.main(["validate", "--matrix", "my batches/batch.json"]) == 0
    assert "tasks" in capsys.readouterr().out
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before

    monkeypatch.delenv("MESH_SIM_BIN", raising=False)
    assert (
        experiment.main(
            ["plan", "--matrix", "my batches/batch.json", "--output-root", "out root"]
        )
        == 1
    )
    assert "MESH_SIM_BIN" in capsys.readouterr().err
    assert not (tmp_path / "out root").exists()

    monkeypatch.setenv("MESH_SIM_BIN", "/nonexistent/env-binary")
    assert (
        experiment.main(
            [
                "plan",
                "--matrix",
                "my batches/batch.json",
                "--output-root",
                "out root",
                "--sim-binary",
                sim_binary,
            ]
        )
        == 0
    )
    plan = json.loads((tmp_path / "out root" / PLAN_NAME).read_text())
    assert plan["experiment_plan_version"] == EXPERIMENT_PLAN_VERSION
    assert plan["sim_binary"]["path"] == str(Path(sim_binary).resolve())
    assert plan["matrix"]["path"] == str(folder / "batch.json")
    assert plan["inputs"][str(folder / "batch.json")]["kind"] == "matrix"
    assert all(
        t["output_dir"].startswith(str(tmp_path / "out root")) for t in plan["tasks"]
    )

    shutil_root = tmp_path / "env root"
    monkeypatch.setenv("MESH_SIM_BIN", sim_binary)
    assert (
        experiment.main(
            [
                "plan",
                "--matrix",
                "my batches/batch.json",
                "--output-root",
                str(shutil_root),
            ]
        )
        == 0
    )
    assert (
        json.loads((shutil_root / PLAN_NAME).read_text())["sim_binary"]["reference"]
        == sim_binary
    )
    assert (
        experiment.main(
            [
                "plan",
                "--matrix",
                "my batches/batch.json",
                "--output-root",
                "out root",
                "--sim-binary",
                "/nonexistent/sim",
            ]
        )
        == 1
    )
    assert "not an executable file" in capsys.readouterr().err


def test_run_and_status_fail_cleanly_without_the_scheduler(
    tmp_path, multi_run_config, sim_binary, monkeypatch, capsys
):
    import scripts.rl.ops as ops_package

    _no_children(monkeypatch)
    monkeypatch.setitem(sys.modules, "scripts.rl.ops.local", None)
    monkeypatch.setitem(sys.modules, "scripts.rl.ops.recovery", None)
    for name in ("local", "recovery"):
        if hasattr(ops_package, name):
            monkeypatch.delattr(ops_package, name)
    matrix = _write(tmp_path / "m", _matrix(multi_run_config))
    root = tmp_path / "root"
    assert (
        experiment.main(
            [
                "run",
                "--matrix",
                matrix,
                "--output-root",
                str(root),
                "--sim-binary",
                sim_binary,
            ]
        )
        == 1
    )
    assert "batch execution is not available" in capsys.readouterr().err
    assert not root.exists()
    assert (
        experiment.main(
            [
                "plan",
                "--matrix",
                matrix,
                "--output-root",
                str(root),
                "--sim-binary",
                sim_binary,
            ]
        )
        == 0
    )
    for argv in (
        ["status", "--output-root", str(root)],
        ["resume", "--output-root", str(root)],
    ):
        assert experiment.main(argv) == 1
        assert "ImportError" in capsys.readouterr().err


def test_run_delegates_with_resolved_execution(
    tmp_path, multi_run_config, sim_binary, monkeypatch
):
    import importlib
    import scripts.rl.ops as ops_package

    _no_children(monkeypatch)
    calls = []

    def run_batch(root, execution):
        calls.append((root, execution))
        return 0

    try:
        real = importlib.import_module("scripts.rl.ops.local")
    except ImportError:
        real = None
    if real is not None:
        monkeypatch.setattr(real, "run_batch", run_batch)
    fake = type(sys)("scripts.rl.ops.local")
    fake.run_batch = run_batch
    monkeypatch.setitem(sys.modules, "scripts.rl.ops.local", fake)
    monkeypatch.setattr(ops_package, "local", fake, raising=False)
    data = _matrix(multi_run_config, execution={"workers": 3, "nice": 5})
    matrix = _write(tmp_path / "m", data)
    root = tmp_path / "root"
    assert (
        experiment.main(
            [
                "run",
                "--matrix",
                matrix,
                "--output-root",
                str(root),
                "--sim-binary",
                sim_binary,
                "--workers",
                "2",
            ]
        )
        == 0
    )
    assert len(calls) == 1
    _, execution = calls[0]
    assert execution["workers"] == 2 and execution["nice"] == 5
    assert (
        execution["threads_per_worker"] == 1
        and execution["failure_policy"] == "continue"
    )
    assert execution["source"] == {
        "workers": "cli",
        "threads_per_worker": "default",
        "failure_policy": "default",
        "nice": "matrix",
    }
    assert "workers" not in json.loads((root / PLAN_NAME).read_text())["tasks"][0]


def _fake_root(tmp_path: Path) -> tuple[Path, Path]:
    """Mesh-shaped root whose .venv python only records its argv and cwd."""
    root = tmp_path / "fake mesh"
    (root / "scripts/rl").mkdir(parents=True)
    (root / "sim.cc").write_text("")
    record = tmp_path / "argv.json"
    python = root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        f"#!{sys.executable}\nimport json, os, sys\n"
        f'json.dump({{"argv": sys.argv[1:], "cwd": os.getcwd(), '
        f'"bin": os.environ.get("MESH_SIM_BIN")}}, open({str(record)!r}, "w"))\n'
        "sys.exit(7)\n"
    )
    python.chmod(0o755)
    return root, record


def test_launcher_syntax_dry_run_and_path_normalization(tmp_path):
    assert subprocess.run(["bash", "-n", str(LAUNCHER)]).returncode == 0
    root, record = _fake_root(tmp_path)
    caller = tmp_path / "caller dir"
    caller.mkdir()
    env = {**os.environ, "MESH_SIM_ROOT": str(root), "MESH_SIM_BIN": "bins/sim one"}
    args = [
        "plan",
        "--matrix",
        "my batch.json",
        "--output-root=out root",
        "--rows",
        "a,b",
        "--sim-binary",
        "/abs/sim",
    ]
    dry = subprocess.run(
        ["bash", str(LAUNCHER), "--dry-run", *args],
        cwd=caller,
        env=env,
        capture_output=True,
        text=True,
    )
    assert dry.returncode == 0 and not record.exists()
    assert "Preview only" in dry.stdout and "my\\ batch.json" in dry.stdout

    run = subprocess.run(["bash", str(LAUNCHER), *args], cwd=caller, env=env)
    assert run.returncode == 7
    seen = json.loads(record.read_text())
    assert seen["cwd"] == str(root.resolve())
    assert seen["argv"] == [
        "-u",
        "-m",
        "scripts.rl.experiment",
        "plan",
        "--matrix",
        f"{caller}/my batch.json",
        f"--output-root={caller}/out root",
        "--rows",
        "a,b",
        "--sim-binary",
        "/abs/sim",
    ]
    assert seen["bin"] == f"{caller}/bins/sim one"

    help_run = subprocess.run(
        ["bash", str(LAUNCHER), "--help"],
        cwd=caller,
        env={**env, "MESH_SIM_ROOT": str(tmp_path / "missing")},
        capture_output=True,
        text=True,
    )
    assert help_run.returncode == 0 and "validate --matrix" in help_run.stdout
    bad = subprocess.run(
        ["bash", str(LAUNCHER), "status", "--output-root", "x"],
        cwd=caller,
        env={**env, "MESH_SIM_ROOT": str(caller)},
        capture_output=True,
        text=True,
    )
    assert bad.returncode == 1 and "not a mesh-sim root" in bad.stderr


def test_launcher_runs_real_validate_from_another_directory(tmp_path):
    result = subprocess.run(
        ["bash", str(LAUNCHER), "validate", "--matrix", str(EXAMPLE / "batch.json")],
        cwd=tmp_path,
        env={k: v for k, v in os.environ.items() if k != "MESH_SIM_ROOT"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "27 tasks" in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_v1_missing_binary_keeps_argparse_exit_two(tmp_path, monkeypatch):
    monkeypatch.delenv("MESH_SIM_BIN", raising=False)
    with pytest.raises(SystemExit) as exc:
        experiment.main(
            [
                "plan",
                "--matrix",
                str(TRACKED_V1),
                "--output-root",
                str(tmp_path / "no-output"),
            ]
        )
    assert exc.value.code == 2 and not (tmp_path / "no-output").exists()
