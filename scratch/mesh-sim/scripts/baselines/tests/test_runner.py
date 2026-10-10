"""Standalone runner lifecycle against fake_child.py; no real simulator is started."""

import json
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path

import pytest

from scripts.baselines import artifacts, execution, runner
from scripts.baselines.tests.conftest import fake_child_binary, write_scenario

MESH_ROOT = Path(__file__).resolve().parents[3]
BUILD_LIB = MESH_ROOT.parent.parent / "build" / "lib"
REFERENCE_KEYS = ("plan", "planner_log", "sim_log", "source_inputs", "effective_inputs")


def _main(binary, ini, out, *extra) -> int:
    return runner.main(["--sim-binary", str(binary), "--run-config", str(ini),
                        "--output-dir", str(out), *extra])


def _manifest(out: Path) -> dict:
    return artifacts.read_json(out / artifacts.MANIFEST_NAME)


@pytest.fixture
def record(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "child-record.json"
    monkeypatch.setenv("FAKE_CHILD_RECORD", str(path))
    return path


def test_argv_environment_and_complete_run(tmp_path, fake_child, record, stub_planner,
                                           monkeypatch):
    monkeypatch.setenv("FAKE_CHILD_MARKER", "passed-through")
    ini = write_scenario(tmp_path / "s")
    out = tmp_path / "run"
    assert _main(fake_child, ini, out, "--seeds", "1-2", "--band", "sub-6") == 0

    run = out.resolve()
    seen = json.loads(record.read_text())
    assert seen["argv"] == [f"--run-config={run}/effective-inputs/run.ini",
                            f"--output-dir={run}", "--seeds=1,2", "--band=sub-6"]
    assert seen["env"]["LD_LIBRARY_PATH"].split(os.pathsep)[0] == str(BUILD_LIB)
    assert seen["env"]["FAKE_CHILD_MARKER"] == "passed-through"
    assert seen["stdin_devnull"] is True
    assert (seen["rl_enabled"], seen["nodes_file"]) == ("false", "nodes.json")

    manifest = _manifest(out)
    assert (manifest["status"], manifest["mode"], manifest["executor"]) == (
        "complete", "standalone", "none")
    assert (manifest["method"], manifest["requested_algorithm"]) == ("geometric", "geometric")
    assert manifest["simulation_seeds"] == [1, 2]
    assert manifest["seeds"] == [
        {"seed": 1, "status": "complete", "summary": "seed-1/summary.json"},
        {"seed": 2, "status": "complete", "summary": "seed-2/summary.json"}]
    assert manifest["sim_binary_sha256"] == artifacts.sha256_file(fake_child)
    assert manifest["rf"]["simulator_channel"]["band"] == "sub-6"
    assert manifest["error"] is None and manifest["ended_at"] is not None
    assert "fake_child: mode=ok" in (out / "sim.log").read_text()
    assert {"baseline_manifest.json", "planner.log", "sim.log", "source-inputs",
            "effective-inputs", "inputs", "run.log", "seed-1", "seed-2"} <= {
        p.name for p in out.iterdir()}
    assert not list(out.rglob("rl_episode.json")) and not list(out.rglob("steps.jsonl"))

    plan = artifacts.read_json(out / "effective-inputs/baseline-plan.json")
    nodes = {n["id"]: n for n in json.loads((out / "effective-inputs/nodes.json").read_text())}
    for entry in plan["nodes"]:
        if entry["selected"]:
            assert nodes[entry["id"]]["position"]["x"] == entry["planned"]["x"]
            assert nodes[entry["id"]]["position"]["y"] == entry["planned"]["y"]


def test_ini_seed_and_algorithm_override(tmp_path, fake_child, record):
    ini = write_scenario(tmp_path / "s")
    out = tmp_path / "run"
    assert _main(fake_child, ini, out, "--algorithm", "none") == 0

    run = out.resolve()
    assert json.loads(record.read_text())["argv"] == [
        f"--run-config={run}/effective-inputs/run.ini", f"--output-dir={run}"]
    manifest = _manifest(out)
    assert (manifest["method"], manifest["requested_algorithm"]) == ("none", "geometric")
    assert manifest["planner_source"] is None
    assert manifest["simulation_seeds"] == [1]
    assert manifest["seeds"] == [{"seed": 1, "status": "complete",
                                  "summary": "seed-1/summary.json"}]
    assert (out / "effective-inputs/nodes.json").read_bytes() == (
        (ini.parent / "nodes.json").read_bytes())


def test_simulator_exit_code_is_propagated(tmp_path, fake_child, monkeypatch):
    monkeypatch.setenv("FAKE_CHILD_MODE", "fail")
    ini = write_scenario(tmp_path / "s", overrides={"algorithm": "none"})
    out = tmp_path / "run"
    assert _main(fake_child, ini, out, "--seeds", "1,2") == 7

    manifest = _manifest(out)
    assert manifest["status"] == "failed"
    assert "exited with code 7" in manifest["error"]
    assert "simulated failure" in manifest["error"]
    assert manifest["seeds"] == [
        {"seed": 1, "status": "complete", "summary": "seed-1/summary.json"},
        {"seed": 2, "status": "failed", "summary": None}]


def test_missing_summary_fails_the_run(tmp_path, fake_child, monkeypatch):
    monkeypatch.setenv("FAKE_CHILD_MODE", "missing")
    ini = write_scenario(tmp_path / "s", overrides={"algorithm": "none"})
    out = tmp_path / "run"
    assert _main(fake_child, ini, out, "--seeds", "3,4") == 1

    manifest = _manifest(out)
    assert manifest["status"] == "failed"
    assert "seed(s) 4 have no seed-N/summary.json" in manifest["error"]
    assert manifest["seeds"] == [
        {"seed": 3, "status": "complete", "summary": "seed-3/summary.json"},
        {"seed": 4, "status": "missing", "summary": None}]


def test_refuses_non_empty_output_and_bad_arguments(tmp_path, fake_child, record):
    ini = write_scenario(tmp_path / "s", overrides={"algorithm": "none"})
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "keep.txt").write_text("x")
    assert _main(fake_child, ini, busy) == 1
    assert [p.name for p in busy.iterdir()] == ["keep.txt"]

    as_file = tmp_path / "file-out"
    as_file.write_text("x")
    assert _main(fake_child, ini, as_file) == 1
    assert as_file.read_text() == "x"

    fresh = tmp_path / "fresh"
    assert _main(tmp_path / "no-such-binary", ini, fresh) == 1
    assert _main(fake_child, tmp_path / "missing.ini", fresh) == 1
    assert _main(fake_child, ini, fresh, "--seeds", "2,2") == 1
    assert not fresh.exists()
    assert not record.exists()

    empty = tmp_path / "empty"
    empty.mkdir()
    assert _main(fake_child, ini, empty) == 0
    assert _manifest(empty)["status"] == "complete"


def test_preparation_failure_starts_no_child(tmp_path, fake_child, record, stub_planner):
    ini = write_scenario(tmp_path / "s", overrides={"objective": "fastest"})
    out = tmp_path / "run"
    assert _main(fake_child, ini, out) == 1
    manifest = _manifest(out)
    assert manifest["status"] == "failed" and "baseline.objective" in manifest["error"]
    assert not (out / "sim.log").exists()
    assert not record.exists()


def test_manifest_status_sequence(tmp_path, fake_child, record, stub_planner, monkeypatch):
    transitions = []
    original = artifacts.set_status

    def spy(path, status, *args, **kwargs):
        transitions.append((artifacts.read_json(path)["status"], status))
        return original(path, status, *args, **kwargs)

    monkeypatch.setattr(artifacts, "set_status", spy)
    ini = write_scenario(tmp_path / "s")
    assert _main(fake_child, ini, tmp_path / "run") == 0
    assert transitions == [("preparing", "prepared"), ("prepared", "running"),
                           ("running", "complete")]
    assert json.loads(record.read_text())["manifest_status"] == "running"


def test_relocated_run_remains_readable(tmp_path, fake_child, stub_planner):
    ini = write_scenario(tmp_path / "s")
    out = tmp_path / "run"
    assert _main(fake_child, ini, out, "--seeds", "1,2") == 0
    moved = tmp_path / "elsewhere" / "moved-run"
    moved.parent.mkdir()
    shutil.move(str(out), str(moved))

    manifest = _manifest(moved)
    for key in REFERENCE_KEYS:
        assert (moved / manifest[key]).exists(), key
    for entry in manifest["seeds"]:
        assert (moved / entry["summary"]).is_file()
    for key in ("source_scenario_identity", "effective_scenario_identity"):
        identity = manifest[key]
        assert artifacts.sha256_file(moved / identity["run_config"]) == (
            identity["run_ini_sha256"])
    portable = {k: v for k, v in manifest.items() if k != "source_run_config_abs"}
    assert str(out.resolve()) not in json.dumps(portable)


def _fresh_python(script: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", textwrap.dedent(script)], cwd=MESH_ROOT,
                          text=True, capture_output=True, check=True)


def test_none_imports_no_planner_module(tmp_path):
    ini = write_scenario(tmp_path / "s", overrides={"algorithm": "none"})
    binary = fake_child_binary(tmp_path / "bin")
    result = _fresh_python(f"""
        import sys
        from scripts.baselines import runner
        code = runner.main(["--sim-binary", {str(binary)!r}, "--run-config", {str(ini)!r},
                            "--output-dir", {str(tmp_path / 'run')!r}])
        loaded = sorted(m for m in sys.modules if m.split('.')[0] in
                        ('models', 'core', 'planners', 'pydantic', 'shapely', 'pyproj',
                         'yaml') or m == 'scripts.baselines.arpo_solver')
        print(code, loaded)
    """)
    assert result.stdout.strip().splitlines()[-1] == "0 []"


def test_runner_import_loads_no_rl_or_ml_stack():
    result = _fresh_python("""
        import sys
        import scripts.baselines.runner
        banned = ('gymnasium', 'torch', 'stable_baselines3', 'sb3_contrib')
        print(sorted(m for m in sys.modules
                     if m.split('.')[0] in banned or m.startswith('scripts.rl')))
    """)
    assert result.stdout.strip() == "[]"


def _wait_for(path: Path, timeout_s: float = 30.0) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.is_file() and path.read_text().strip():
            return path.read_text().strip()
        time.sleep(0.05)
    raise AssertionError(f"{path} did not appear within {timeout_s}s")


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_interruption_stops_child_and_records_interrupted(tmp_path, signum):
    ini = write_scenario(tmp_path / "s", overrides={"algorithm": "none"})
    binary = fake_child_binary(tmp_path / "bin")
    out = tmp_path / "run"
    pid_file = tmp_path / "child.pid"
    env = {**os.environ, "FAKE_CHILD_MODE": "hang", "FAKE_CHILD_PID_FILE": str(pid_file)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "scripts.baselines.runner", "--sim-binary", str(binary),
         "--run-config", str(ini), "--output-dir", str(out), "--seeds", "1,2"],
        cwd=MESH_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        child_pid = int(_wait_for(pid_file))
        assert _manifest(out)["status"] == "running"
        proc.send_signal(signum)
        _, stderr = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert proc.returncode == 128 + signum, stderr
    manifest = _manifest(out)
    assert manifest["status"] == "interrupted"
    assert manifest["error"] == f"interrupted by {signal.Signals(signum).name}"
    assert manifest["ended_at"] is not None
    assert [s["status"] for s in manifest["seeds"]] == ["missing", "missing"]
    deadline = time.monotonic() + 10
    while not _gone(child_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert _gone(child_pid)


@pytest.mark.parametrize("mode,expected", [("hang", -signal.SIGTERM),
                                           ("hang-ignore-term", -signal.SIGKILL)])
def test_stop_child_terminates_then_kills_and_reaps(tmp_path, monkeypatch, mode, expected):
    ini = write_scenario(tmp_path / "s", overrides={"algorithm": "none"})
    pid_file = tmp_path / "child.pid"
    monkeypatch.setenv("FAKE_CHILD_MODE", mode)
    monkeypatch.setenv("FAKE_CHILD_PID_FILE", str(pid_file))
    out = tmp_path / "out"
    out.mkdir()
    proc = subprocess.Popen([str(fake_child_binary(tmp_path / "bin")),
                             f"--run-config={ini}", f"--output-dir={out}"],
                            stdin=subprocess.DEVNULL)
    try:
        _wait_for(pid_file)
        started = time.monotonic()
        execution.stop_child(proc, wait_s=0.5)
        assert proc.returncode == expected
        assert time.monotonic() - started < 10
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_automatic_output_root_naming(tmp_path):
    now = datetime(2026, 9, 29, 13, 5, 7)
    first = execution.automatic_output_root(tmp_path, now)
    assert first == tmp_path / "outputs/2026-09/29/13-05-07-baseline"
    first.mkdir(parents=True)
    assert execution.automatic_output_root(tmp_path, now) == first.with_name(
        "13-05-07-baseline-2")


@pytest.mark.parametrize("fault", ("running_write", "wait", "persistent_write"))
def test_ordinary_failure_stops_and_reaps_child(tmp_path, fake_child, monkeypatch, fault, capsys):
    ini = write_scenario(tmp_path / "s", overrides={"algorithm": "none"})
    out = tmp_path / "run"
    pid_file = tmp_path / "child.pid"
    monkeypatch.setenv("FAKE_CHILD_MODE", "hang")
    monkeypatch.setenv("FAKE_CHILD_PID_FILE", str(pid_file))
    real_popen = execution.subprocess.Popen
    real_status = artifacts.set_status
    children = []

    def launch(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        children.append(proc)
        _wait_for(pid_file)
        if fault == "wait":
            real_wait = proc.wait
            raised = False

            def wait(timeout=None):
                nonlocal raised
                if timeout is None and not raised:
                    raised = True
                    raise RuntimeError("injected wait failure")
                return real_wait(timeout=timeout)

            monkeypatch.setattr(proc, "wait", wait)
        return proc

    def set_status(path, status, **fields):
        if status == "running" and fault != "wait":
            raise OSError("injected running write failure")
        if status == "failed" and fault == "persistent_write":
            raise OSError("injected failure write failure")
        return real_status(path, status, **fields)

    monkeypatch.setattr(execution.subprocess, "Popen", launch)
    monkeypatch.setattr(artifacts, "set_status", set_status)
    try:
        assert _main(fake_child, ini, out, "--seeds", "1") == 1
        assert len(children) == 1 and children[0].returncode == -signal.SIGTERM
        assert _gone(int(pid_file.read_text()))
        manifest = _manifest(out)
        if fault == "persistent_write":
            assert manifest["status"] == "prepared"
            assert "Could not record baseline failure" in capsys.readouterr().err
        else:
            assert manifest["status"] == "failed" and manifest["ended_at"]
            assert "injected" in manifest["error"]
            assert manifest["seeds"] == [{"seed": 1, "status": "failed", "summary": None}]
    finally:
        for proc in children:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def test_preparation_imports_remain_available():
    from scripts.baselines import adapter, preparation

    assert adapter.prepare is preparation.prepare
    assert adapter.PreparedBaseline is preparation.PreparedBaseline
    assert adapter.BaselinePreparationError is preparation.BaselinePreparationError
