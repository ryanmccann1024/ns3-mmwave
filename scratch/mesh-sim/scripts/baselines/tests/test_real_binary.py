"""Verification rows R1-R6: baseline guard, standalone runner, and evaluation on the real binary."""

# Set MESH_SIM_BIN to a built simulator; every run uses a synthetic scenario in tmp_path.

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.baselines import artifacts
from scripts.baselines.effective_inputs import start_position
from scripts.baselines.tests.conftest import (NODES, SCENARIO_SECTIONS, scenario_ini,
                                              write_scenario)
from scripts.sim_support import simulator_env

MESH_SIM_BIN = os.environ.get("MESH_SIM_BIN")
pytestmark = pytest.mark.skipif(
    not MESH_SIM_BIN,
    reason="BLOCKED: MESH_SIM_BIN is not set; rows R1-R6 need a human-built mesh-sim binary")

MESH_ROOT = Path(__file__).resolve().parents[3]
RL_ON = "[rl]\nenabled = true\n"
RL_OFF = "[rl]\nenabled = false\n"
SIM_SECTIONS = """
[channel]
band = mmwave
frequency_ghz = 28.0
tx_power_dbm = 30.0
scenario = RMa
channel_model = 3gpp
condition_model = static_los
blockage_enabled = false
bandwidth_mhz = 400.0
noise_figure_db = 5.0

[traffic]
model = constant
demand_mbps = 10.0
flow_topology = all_pairs

[routing]
algorithm = shortest_path
max_hops = 5
"""
GUARD_TEXT = "is active but this is a direct simulator run"
NOTICE_TEXT = "is not applied in RL mode; this run uses the scenario layout"
COMPARED_CSVS = ("positions.csv", "links.csv", "flows.csv", "routes.csv")
TIMING_FIELDS = ("wall_clock_start", "wall_clock_end", "wall_elapsed_s")
WRITER_TOL = 1e-6
SOURCE_START = [start_position(node) for node in NODES]
PLACEMENT_POLICIES = ("geometric", "optimization")
EVAL_POLICIES = ("hold", "random_valid", *PLACEMENT_POLICIES)


def _scenario(root: Path, *, algorithm: str | None = "geometric",
              rl_enabled: bool = True) -> Path:
    if algorithm is None:
        text = f"{SCENARIO_SECTIONS}{SIM_SECTIONS}"
    else:
        text = scenario_ini({"algorithm": algorithm}, extra=SIM_SECTIONS)
    if not rl_enabled:
        assert RL_ON in text
        text = text.replace(RL_ON, RL_OFF)
    return write_scenario(root, ini_text=text)


def _hashes(directory: Path) -> dict:
    return {p.name: artifacts.sha256_file(p) for p in sorted(directory.iterdir())
            if p.is_file()}


def _direct(run_config: Path, out: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [MESH_SIM_BIN, f"--run-config={run_config}", f"--output-dir={out}", *flags],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600,
        env=simulator_env(MESH_ROOT))


def _module(module: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", module, *args], cwd=MESH_ROOT,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=900)


def _runner(run_config: Path, out: Path, *args: str) -> subprocess.CompletedProcess:
    return _module("scripts.baselines.runner", "--sim-binary", MESH_SIM_BIN,
                   "--run-config", str(run_config), "--output-dir", str(out), *args)


def _first_tick_positions(seed_dir: Path) -> dict:
    """Roster index -> (x, y, z) for the first time step in positions.csv."""
    lines = [line for line in (seed_dir / "positions.csv").read_text().splitlines()
             if line and not line.startswith("#")]
    rows = [line.split(",") for line in lines[1:]]
    first = rows[0][0]
    return {int(row[1]): tuple(float(v) for v in row[2:5]) for row in rows if row[0] == first}


def _assert_xyz(actual, expected, label: str) -> None:
    assert all(abs(a - e) <= WRITER_TOL for a, e in zip(actual, expected)), (
        f"{label}: {actual} != {expected}")


def _summary_without_timing(seed_dir: Path) -> dict:
    summary = json.loads((seed_dir / "summary.json").read_text())
    return {k: v for k, v in summary.items() if k not in TIMING_FIELDS}


def _planned(plan: dict) -> list:
    nodes = sorted(plan["nodes"], key=lambda n: n["roster_index"])
    return [(n["planned"]["x"], n["planned"]["y"], n["planned"]["z"]) for n in nodes]


@pytest.mark.parametrize("rl_enabled", [False, True])
def test_r1_direct_run_refuses_active_method(tmp_path, rl_enabled):
    ini = _scenario(tmp_path / "s", rl_enabled=rl_enabled)
    out = tmp_path / "out"
    result = _direct(ini, out, "--seeds=1")
    assert result.returncode == 1, result.stderr[-2000:]
    assert GUARD_TEXT in result.stderr
    assert "python -m scripts.baselines.runner" in result.stderr
    assert not out.exists() or not any(out.iterdir())


def test_r2_none_and_absent_section_match(tmp_path):
    outputs = []
    for name, algorithm in (("none", "none"), ("absent", None)):
        ini = _scenario(tmp_path / name, algorithm=algorithm, rl_enabled=False)
        out = tmp_path / f"out-{name}"
        result = _direct(ini, out, "--seeds=1")
        assert result.returncode == 0, result.stderr[-2000:]
        outputs.append(out / "seed-1")
    first, second = outputs
    for name in sorted(p.name for p in first.glob("*.csv")):
        assert (first / name).read_bytes() == (second / name).read_bytes(), name
    assert _summary_without_timing(first) == _summary_without_timing(second)


def test_r3_rl_mode_notice_and_original_layout(tmp_path):
    ini = _scenario(tmp_path / "s")
    out = tmp_path / "out"
    result = _direct(ini, out, "--rl-mode", "--seed=1")
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stderr.count(NOTICE_TEXT) == 1
    assert GUARD_TEXT not in result.stderr
    positions = _first_tick_positions(out / "seed-1")
    for index, expected in enumerate(SOURCE_START):
        _assert_xyz(positions[index], expected, NODES[index]["id"])


def test_r4_runner_none_matches_direct_run(tmp_path):
    ini = _scenario(tmp_path / "s", algorithm="none", rl_enabled=False)
    direct = tmp_path / "direct"
    result = _direct(ini, direct, "--seeds=1,2")
    assert result.returncode == 0, result.stderr[-2000:]
    run = tmp_path / "runner"
    launched = _runner(ini, run, "--seeds", "1,2")
    assert launched.returncode == 0, launched.stderr[-2000:]
    assert artifacts.read_json(run / artifacts.MANIFEST_NAME)["status"] == "complete"
    for seed in (1, 2):
        ours, theirs = run / f"seed-{seed}", direct / f"seed-{seed}"
        for name in COMPARED_CSVS:
            assert (ours / name).read_bytes() == (theirs / name).read_bytes(), (seed, name)
        assert _summary_without_timing(ours) == _summary_without_timing(theirs)


@pytest.mark.parametrize("method", PLACEMENT_POLICIES)
def test_r5_runner_places_selected_nodes(tmp_path, method):
    ini = _scenario(tmp_path / "s", algorithm=method)
    before = _hashes(ini.parent)
    run = tmp_path / "run"
    launched = _runner(ini, run, "--seeds", "1,2")
    manifest = artifacts.read_json(run / artifacts.MANIFEST_NAME)
    assert launched.returncode == 0, (manifest.get("error"), launched.stderr[-2000:])
    assert (manifest["status"], manifest["method"]) == ("complete", method)
    assert [s["status"] for s in manifest["seeds"]] == ["complete", "complete"]
    assert _hashes(ini.parent) == before

    plan = artifacts.read_json(run / manifest["plan"])
    planned = _planned(plan)
    selected = {n["roster_index"] for n in plan["nodes"] if n["selected"]}
    for seed in (1, 2):
        positions = _first_tick_positions(run / f"seed-{seed}")
        for index, source in enumerate(SOURCE_START):
            expected = planned[index] if index in selected else source
            _assert_xyz(positions[index], expected, f"seed {seed} {NODES[index]['id']}")
    assert (run / "inputs" / artifacts.PLAN_NAME).is_file()
    assert not list(run.rglob("rl_episode.json")) and not list(run.rglob("steps.jsonl"))


def _decision_zero(episode_dir: Path) -> tuple[list, list]:
    """(node ids, facts.nodes rows) of the reset record in steps.jsonl."""
    lines = (episode_dir / "steps.jsonl").read_text().splitlines()
    header, record = json.loads(lines[0]), json.loads(lines[1])
    assert record["decision"] == 0
    return list(header["contract"]["node_ids"]), record["facts"]["nodes"]


def test_r6_evaluation_suite_with_placement_policies(tmp_path):
    ini = _scenario(tmp_path / "s")
    before = _hashes(ini.parent)
    out = tmp_path / "eval"
    result = _module("scripts.rl.evaluate", "--sim-binary", MESH_SIM_BIN,
                     "--run-config", str(ini), "--output-dir", str(out),
                     "--seeds", "1,2", "--policies", ",".join(EVAL_POLICIES),
                     "--telemetry", "steps")
    assert result.returncode == 0, result.stderr[-2000:]
    assert _hashes(ini.parent) == before

    manifest = json.loads((out / "eval_manifest.json").read_text())
    assert set(manifest["policies"]) == set(EVAL_POLICIES)
    assert all((out / name).is_dir() for name in EVAL_POLICIES)
    for name, block in manifest["policies"].items():
        assert ("baseline" in block) == (name in PLACEMENT_POLICIES), name
        assert [e["status"] for e in block["episodes"]] == ["completed", "completed"]

    expected_ids = [node["id"] for node in NODES]
    for name in EVAL_POLICIES:
        block = manifest["policies"][name]
        if name in PLACEMENT_POLICIES:
            baseline = block["baseline"]
            assert baseline["method"] == name and baseline["executor"] == "hold"
            assert artifacts.read_json(out / baseline["manifest"])["status"] == "prepared"
            expected = _planned(artifacts.read_json(out / baseline["plan"]))
        elif name == "hold":
            expected = SOURCE_START
        else:
            continue
        for episode in block["episodes"]:
            ids, rows = _decision_zero(Path(episode["episode_dir"]))
            assert ids == expected_ids
            for index, row in enumerate(rows):
                _assert_xyz(row[:3], expected[index], f"{name} seed {episode['seed']} "
                                                      f"{expected_ids[index]}")
