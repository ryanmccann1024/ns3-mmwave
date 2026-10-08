"""Standalone runner CLI: defaults, seed specs, output-dir rules, exit codes, manifest outcome.

Contract: scripts/baselines/README.md "Commands" (option defaults, output dir must be absent
or empty, exit codes 0 / 1 / simulator code / 128+signal) and the baseline_manifest.json
table (status sequence, per-seed complete/missing/failed, error with exit code and the
sim.log tail). The child is scripts/baselines/tests/fake_child.py or a tiny script
written into tmp_path; no real simulator runs.
"""

import json
import re
import sys
from pathlib import Path

import pytest

from scripts.baselines import artifacts, runner
from scripts.baselines.tests.conftest import FAKE_CHILD, write_scenario


def _main(binary, ini, out, *extra) -> int:
    return runner.main(["--sim-binary", str(binary), "--run-config", str(ini),
                        "--output-dir", str(out), *extra])


def _manifest(out: Path) -> dict:
    return artifacts.read_json(out / artifacts.MANIFEST_NAME)


def _script(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text)
    path.chmod(0o755)
    return path


@pytest.fixture
def record(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "child-record.json"
    monkeypatch.setenv("FAKE_CHILD_RECORD", str(path))
    return path


def _none_ini(tmp_path, **kwargs) -> Path:
    return write_scenario(tmp_path / "s", overrides={"algorithm": "none"}, **kwargs)


# --- output directory --------------------------------------------------------------------

def test_hidden_file_makes_the_output_dir_non_empty(tmp_path, fake_child, record):
    out = tmp_path / "busy"
    out.mkdir()
    (out / ".keep").write_text("")
    assert _main(fake_child, _none_ini(tmp_path), out) == 1
    assert [p.name for p in out.iterdir()] == [".keep"]
    assert not record.exists()


def test_non_empty_subdirectory_counts_too(tmp_path, fake_child, record):
    out = tmp_path / "busy"
    (out / "empty-subdir").mkdir(parents=True)
    assert _main(fake_child, _none_ini(tmp_path), out) == 1
    assert [p.name for p in out.iterdir()] == ["empty-subdir"]
    assert not record.exists()


def test_absent_nested_output_dir_is_created(tmp_path, fake_child):
    out = tmp_path / "a" / "b" / "c"
    assert _main(fake_child, _none_ini(tmp_path), out) == 0
    assert _manifest(out)["status"] == "complete"


def test_default_output_dir_is_timestamped_under_the_mesh_root(tmp_path, fake_child,
                                                               monkeypatch, capsys):
    mesh = tmp_path / "mesh-root"
    mesh.mkdir()
    monkeypatch.setattr(runner, "find_mesh_root", lambda *args, **kwargs: mesh)
    ini = _none_ini(tmp_path)
    assert runner.main(["--sim-binary", str(fake_child), "--run-config", str(ini)]) == 0
    runs = list((mesh / "outputs").glob("*/*/*"))
    assert len(runs) == 1
    run = runs[0]
    assert re.fullmatch(r"\d{4}-\d{2}/\d{2}/\d{2}-\d{2}-\d{2}-baseline",
                        run.relative_to(mesh / "outputs").as_posix())
    assert f"Baseline output: {run.resolve()}" in capsys.readouterr().out
    assert _manifest(run)["status"] == "complete"


# --- seeds -------------------------------------------------------------------------------

@pytest.mark.parametrize("spec,expected", [
    ("1-3,5", [1, 2, 3, 5]),
    (" 4 , 2 ", [4, 2]),
    ("5-5", [5]),
    ("0", [0]),
    ("7,1-2", [7, 1, 2]),
])
def test_seed_spec_is_expanded_in_order_for_the_simulator(tmp_path, fake_child, record,
                                                          stub_planner, spec, expected):
    ini = write_scenario(tmp_path / "s")
    out = tmp_path / "run"
    assert _main(fake_child, ini, out, "--seeds", spec) == 0
    argv = json.loads(record.read_text())["argv"]
    assert argv[2] == "--seeds=" + ",".join(map(str, expected))
    manifest = _manifest(out)
    assert manifest["simulation_seeds"] == expected
    assert [s["seed"] for s in manifest["seeds"]] == expected
    assert {s["status"] for s in manifest["seeds"]} == {"complete"}
    # The plan is made once, for the first simulation seed.
    assert manifest["channel_scoring"]["planning_seed"] == expected[0]
    assert manifest["channel_scoring"]["jammer_seed"] == expected[0]


@pytest.mark.parametrize("spec", ["3-1", "x", "", ",", "1-3,2", "-1", "1.5", "2,2"])
def test_invalid_seed_specs_exit_1_and_write_nothing(tmp_path, fake_child, record, spec,
                                                     capsys):
    out = tmp_path / "run"
    assert _main(fake_child, _none_ini(tmp_path), out, "--seeds", spec) == 1
    assert not out.exists()
    assert not record.exists()
    assert "ValueError" in capsys.readouterr().err


def test_absent_ini_seed_uses_the_simulator_default(tmp_path, fake_child, record):
    ini = write_scenario(tmp_path / "s", ini_text=(
        "[scenario]\nname = no-seed\nnodes_file = nodes.json\n\n"
        "[baseline]\nalgorithm = none\nmapping_file = mapping.json\n"))
    out = tmp_path / "run"
    assert _main(fake_child, ini, out) == 0
    argv = json.loads(record.read_text())["argv"]
    assert not any(arg.startswith("--seeds=") for arg in argv)
    manifest = _manifest(out)
    assert manifest["simulation_seeds"] == [42]
    assert manifest["seeds"] == [{"seed": 42, "status": "complete",
                                  "summary": "seed-42/summary.json"}]


def test_ini_seed_with_an_inline_comment(tmp_path, fake_child, record):
    ini = _none_ini(tmp_path)
    ini.write_text(ini.read_text().replace("seed = 1\n", "seed = 9   # held out\n"))
    out = tmp_path / "run"
    assert _main(fake_child, ini, out) == 0
    assert _manifest(out)["simulation_seeds"] == [9]
    assert (out / "seed-9/summary.json").is_file()


@pytest.mark.parametrize("value", ["abc", "-3", "1.0"])
def test_invalid_ini_seed_exits_1_and_writes_nothing(tmp_path, fake_child, record, value):
    ini = _none_ini(tmp_path)
    ini.write_text(ini.read_text().replace("seed = 1\n", f"seed = {value}\n"))
    out = tmp_path / "run"
    assert _main(fake_child, ini, out) == 1
    assert not out.exists() and not record.exists()


# --- algorithm resolution ------------------------------------------------------------------

@pytest.mark.parametrize("ini_algorithm,flag,method", [
    ("optimization", None, "optimization"),
    ("", None, "none"),
    (None, None, "none"),
    ("none", "geometric", "geometric"),
    ("optimization", "geometric", "geometric"),
])
def test_algorithm_default_and_override(tmp_path, fake_child, stub_planner, ini_algorithm,
                                        flag, method):
    ini = write_scenario(tmp_path / "s", overrides={"algorithm": ini_algorithm})
    out = tmp_path / "run"
    extra = ("--algorithm", flag) if flag else ()
    assert _main(fake_child, ini, out, *extra) == 0
    manifest = _manifest(out)
    assert manifest["method"] == method
    assert manifest["requested_algorithm"] == (ini_algorithm or "none")
    assert manifest["status"] == "complete"
    if method == "none":
        assert (out / "planner.log").read_text() == "method none: no planner was run\n"
        assert manifest["channel_scoring"] is None
    else:
        assert manifest["channel_scoring"]["mode_flag"] is None
    effective = (out / "effective-inputs/run.ini").read_text()
    assert re.search(r"^algorithm = none\b", effective, re.M)


def test_absent_baseline_section_runs_method_none(tmp_path, fake_child, record):
    ini = write_scenario(tmp_path / "s", ini_text=(
        "[scenario]\nseed = 2\nnodes_file = nodes.json\n"))
    out = tmp_path / "run"
    assert _main(fake_child, ini, out) == 0
    manifest = _manifest(out)
    assert (manifest["method"], manifest["requested_algorithm"]) == ("none", "none")
    seen = json.loads(record.read_text())
    assert seen["rl_enabled"] == "false" and seen["nodes_file"] == "nodes.json"
    assert "[baseline]\nalgorithm = none\n" in (out / "effective-inputs/run.ini").read_text()


def test_unknown_algorithm_is_rejected_without_writing(tmp_path, fake_child, record):
    # QUESTION: README "Exit codes" says 1 for an argument error, but argparse rejects an
    # unknown --algorithm choice with SystemExit(2) (runner.py _build_parser, choices=).
    # Only the absence of output is asserted here.
    out = tmp_path / "run"
    with pytest.raises(SystemExit) as info:
        _main(fake_child, _none_ini(tmp_path), out, "--algorithm", "random")
    assert info.value.code != 0
    assert not out.exists() and not record.exists()


# --- exit codes and manifest outcome ------------------------------------------------------

def test_simulator_killed_by_a_signal(tmp_path):
    binary = _script(tmp_path / "bin", "suicide-sim", "#!/bin/sh\necho dying\nkill -KILL $$\n")
    out = tmp_path / "run"
    code = _main(binary, _none_ini(tmp_path), out, "--seeds", "1,2")
    assert code == 128 + 9
    manifest = _manifest(out)
    assert manifest["status"] == "failed" and manifest["ended_at"] is not None
    assert "exited with code -9" in manifest["error"]
    assert "dying" in manifest["error"]
    assert manifest["seeds"] == [{"seed": 1, "status": "failed", "summary": None},
                                 {"seed": 2, "status": "failed", "summary": None}]


def test_simulator_that_cannot_start(tmp_path, capsys):
    binary = _script(tmp_path / "bin", "broken-sim", "#!/nonexistent/interpreter\n")
    out = tmp_path / "run"
    assert _main(binary, _none_ini(tmp_path), out) == 1
    manifest = _manifest(out)
    assert manifest["status"] == "failed"
    assert "cannot start the simulator" in manifest["error"]
    assert manifest["ended_at"] is not None
    assert "Cannot start the simulator" in capsys.readouterr().err


def test_non_zero_exit_after_every_summary_keeps_the_exit_code(tmp_path):
    wrapper = (f"#!{sys.executable}\nimport runpy, sys\n"
               f"try:\n    runpy.run_path({str(FAKE_CHILD)!r}, run_name='__main__')\n"
               "except SystemExit as exc:\n"
               "    if exc.code not in (0, None):\n        raise\n"
               "print('late failure', file=sys.stderr)\nsys.exit(3)\n")
    binary = _script(tmp_path / "bin", "late-fail-sim", wrapper)
    out = tmp_path / "run"
    assert _main(binary, _none_ini(tmp_path), out, "--seeds", "1,2") == 3
    manifest = _manifest(out)
    assert manifest["status"] == "failed"
    assert "exited with code 3" in manifest["error"] and "late failure" in manifest["error"]
    assert manifest["seeds"] == [
        {"seed": 1, "status": "complete", "summary": "seed-1/summary.json"},
        {"seed": 2, "status": "complete", "summary": "seed-2/summary.json"}]


def test_error_carries_only_the_tail_of_sim_log(tmp_path):
    text = (f"#!{sys.executable}\n"
            "for i in range(100):\n    print(f'log line {i:03d}')\n"
            "raise SystemExit(4)\n")
    binary = _script(tmp_path / "bin", "noisy-sim", text)
    out = tmp_path / "run"
    assert _main(binary, _none_ini(tmp_path), out) == 4
    error = _manifest(out)["error"]
    assert "log line 099" in error and "log line 060" in error
    assert "log line 059" not in error
    assert (out / "sim.log").read_text().count("log line") == 100


def test_zero_exit_without_any_summary(tmp_path):
    binary = _script(tmp_path / "bin", "lazy-sim", "#!/bin/sh\nexit 0\n")
    out = tmp_path / "run"
    assert _main(binary, _none_ini(tmp_path), out, "--seeds", "8-9") == 1
    manifest = _manifest(out)
    assert manifest["status"] == "failed"
    assert "seed(s) 8, 9 have no seed-N/summary.json" in manifest["error"]
    assert manifest["seeds"] == [{"seed": 8, "status": "missing", "summary": None},
                                 {"seed": 9, "status": "missing", "summary": None}]


def test_complete_run_manifest_paths_are_run_relative(tmp_path, fake_child, stub_planner,
                                                      capsys):
    ini = write_scenario(tmp_path / "s")
    out = tmp_path / "run"
    assert _main(fake_child, ini, out, "--seeds", "1,2") == 0
    assert f"Baseline run complete: {out.resolve()}" in capsys.readouterr().out
    manifest = _manifest(out)
    assert manifest["error"] is None and manifest["ended_at"] is not None
    for key in ("plan", "planner_log", "sim_log", "source_inputs", "effective_inputs"):
        assert not Path(manifest[key]).is_absolute(), key
        assert (out / manifest[key]).exists(), key
    absolute = {k for k, v in manifest.items()
                if isinstance(v, str) and str(tmp_path) in v}
    assert absolute == {"source_run_config_abs"}
    assert manifest["eval_manifest"] is None
