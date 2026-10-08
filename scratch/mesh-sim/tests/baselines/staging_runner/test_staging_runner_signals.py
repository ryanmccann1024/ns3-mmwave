"""SIGINT / SIGTERM to the standalone runner: exit 128+signal, manifest interrupted, no leftovers.

Contract: scripts/baselines/README.md "Commands" (128 + signal: 130 SIGINT, 143 SIGTERM),
the manifest `status` row ("failed / interrupted at any step") and "Any failure removes
the staging directory". The runner runs as a real subprocess so signals reach it. One
composite executable dispatches to fake_query.py for `--channel-query` and to
fake_child.py otherwise, so an active method plans through the real solver.
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.baselines import artifacts
from scripts.baselines.tests.conftest import FAKE_CHILD, FAKE_QUERY, write_scenario

MESH_ROOT = Path(__file__).resolve().parents[3]
SMALL_GRID = {"candidate_grid_cells": "16", "coverage_grid_cells": "16"}


def _composite(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "mesh-sim-composite"
    path.write_text(
        f"#!{sys.executable}\nimport runpy, sys\n"
        f"target = {str(FAKE_QUERY)!r} if '--channel-query' in sys.argv[1:] "
        f"else {str(FAKE_CHILD)!r}\nsys.argv[0] = target\n"
        "runpy.run_path(target, run_name='__main__')\n")
    path.chmod(0o755)
    return path


def _wait_for(predicate, what: str, timeout_s: float = 30.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(f"{what} did not happen within {timeout_s}s")


def _read(path: Path) -> str | None:
    return path.read_text().strip() if path.is_file() and path.read_text().strip() else None


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def _wait_gone(pid: int, timeout_s: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while not _gone(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return _gone(pid)


def _start_runner(binary: Path, ini: Path, out: Path, env: dict, *extra) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "scripts.baselines.runner", "--sim-binary", str(binary),
         "--run-config", str(ini), "--output-dir", str(out), *extra],
        cwd=MESH_ROOT, env={**os.environ, **env}, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True)


def _finish(proc: subprocess.Popen, timeout_s: float = 60.0) -> str:
    try:
        _, stderr = proc.communicate(timeout=timeout_s)
        return stderr
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_sigterm_with_a_child_that_ignores_sigterm_kills_it_and_ignores_a_second_signal(
        tmp_path):
    ini = write_scenario(tmp_path / "s", overrides={"algorithm": "none"})
    out = tmp_path / "run"
    pid_file = tmp_path / "child.pid"
    proc = _start_runner(_composite(tmp_path / "bin"), ini, out,
                         {"FAKE_CHILD_MODE": "hang-ignore-term",
                          "FAKE_CHILD_PID_FILE": str(pid_file)}, "--seeds", "1,2")
    child = None
    try:
        child = int(_wait_for(lambda: _read(pid_file), "child start"))
        assert artifacts.read_json(out / "baseline_manifest.json")["status"] == "running"
        started = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        time.sleep(1.0)
        proc.send_signal(signal.SIGINT)  # ignored while the child is being stopped
        stderr = _finish(proc)
        elapsed = time.monotonic() - started
    finally:
        if child is not None and not _gone(child):
            os.kill(child, signal.SIGKILL)
    assert proc.returncode == 143, stderr
    assert "Interrupted by SIGTERM" in stderr
    assert elapsed < 30
    assert _wait_gone(child)
    manifest = artifacts.read_json(out / "baseline_manifest.json")
    assert manifest["status"] == "interrupted"
    assert manifest["error"] == "interrupted by SIGTERM"
    assert manifest["ended_at"] is not None
    assert manifest["seeds"] == [{"seed": 1, "status": "missing", "summary": None},
                                 {"seed": 2, "status": "missing", "summary": None}]


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_signal_during_planning_stops_the_query_worker_and_leaves_no_staging(tmp_path,
                                                                             signum):
    ini = write_scenario(tmp_path / "s", overrides=SMALL_GRID)
    out = tmp_path / "run"
    pid_file = tmp_path / "query.pid"
    query_record = tmp_path / "query.jsonl"
    child_record = tmp_path / "child.json"
    proc = _start_runner(_composite(tmp_path / "bin"), ini, out,
                         {"FAKE_QUERY_FAULT": "hang", "FAKE_QUERY_PID_FILE": str(pid_file),
                          "FAKE_QUERY_RECORD": str(query_record),
                          "FAKE_CHILD_RECORD": str(child_record)})
    worker = None
    try:
        worker = json.loads(_wait_for(lambda: _read(pid_file), "query start"))["worker"]
        _wait_for(lambda: '"evaluate"' in (_read(query_record) or ""), "first request")
        assert artifacts.read_json(out / "baseline_manifest.json")["status"] == "preparing"
        assert (out / "effective-inputs.partial").is_dir()
        proc.send_signal(signum)
        stderr = _finish(proc)
    finally:
        if worker is not None and not _gone(worker):
            os.kill(worker, signal.SIGKILL)
    assert proc.returncode == 128 + signum, stderr
    assert _wait_gone(worker)
    manifest = artifacts.read_json(out / "baseline_manifest.json")
    assert manifest["status"] == "interrupted"
    assert manifest["ended_at"] is not None
    assert manifest["seeds"] == []
    assert not (out / "effective-inputs.partial").exists()
    assert not (out / "effective-inputs").exists()
    assert not (out / "sim.log").exists()
    assert not child_record.exists()


PARTIAL_CHILD = """
import os, sys, time
from pathlib import Path
flags = dict(arg.split("=", 1) for arg in sys.argv[1:])
out = Path(flags["--output-dir"])
first = flags["--seeds"].split(",")[0]
(out / f"seed-{first}").mkdir(parents=True)
(out / f"seed-{first}" / "summary.json").write_text("{}\\n")
Path(os.environ["PARTIAL_PID_FILE"]).write_text(str(os.getpid()))
while True:
    time.sleep(0.1)
"""


def test_interruption_after_some_seeds_records_them_complete(tmp_path):
    ini = write_scenario(tmp_path / "s", overrides={"algorithm": "none"})
    binary = tmp_path / "bin" / "partial-sim"
    binary.parent.mkdir()
    binary.write_text(f"#!{sys.executable}\n{PARTIAL_CHILD}")
    binary.chmod(0o755)
    out = tmp_path / "run"
    pid_file = tmp_path / "partial.pid"
    proc = _start_runner(binary, ini, out, {"PARTIAL_PID_FILE": str(pid_file)},
                         "--seeds", "5,6,7")
    child = None
    try:
        child = int(_wait_for(lambda: _read(pid_file), "child start"))
        proc.send_signal(signal.SIGINT)
        stderr = _finish(proc)
    finally:
        if child is not None and not _gone(child):
            os.kill(child, signal.SIGKILL)
    assert proc.returncode == 130, stderr
    assert _wait_gone(child)
    manifest = artifacts.read_json(out / "baseline_manifest.json")
    assert (manifest["status"], manifest["error"]) == ("interrupted", "interrupted by SIGINT")
    assert manifest["seeds"] == [
        {"seed": 5, "status": "complete", "summary": "seed-5/summary.json"},
        {"seed": 6, "status": "missing", "summary": None},
        {"seed": 7, "status": "missing", "summary": None}]
