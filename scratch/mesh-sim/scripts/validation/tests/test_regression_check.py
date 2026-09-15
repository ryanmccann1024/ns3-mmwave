"""CSV metadata and coordinate comparison contracts for normalized snapshots."""

from copy import deepcopy
import os
import subprocess
import sys

import pytest

from scripts.validation import regression_check
from scripts.validation.regression_check import compare_snapshots, load_table


@pytest.mark.parametrize("prefix", ["", "# scenario=test\n# frequency=28\n"])
def test_positions_header_and_coordinates(tmp_path, prefix):
    path = tmp_path / "positions.csv"
    path.write_text(prefix + "time_s,node_id,x,y,z,node_type,active\n"
                    "0,relay,1,2,3,drone,1\n")
    table = load_table(path)
    assert table["columns"] == ["time_s", "node_id", "x", "y", "z", "node_type", "active"]
    assert len(table["rows"]) == 1
    assert table["rows"][0]["node_id"] == "relay"
    assert [table["rows"][0][axis] for axis in "xyz"] == [1.0, 2.0, 3.0]

    baseline = {"tables": {"positions.csv": table}, "summary": {}}
    assert compare_snapshots(baseline, deepcopy(baseline))["match"]
    for axis in "xyz":
        candidate = deepcopy(baseline)
        candidate["tables"]["positions.csv"]["rows"][0][axis] += 1
        report = compare_snapshots(baseline, candidate)
        assert not report["match"] and report["counts"]["total"] == 1
        assert report["differences"][0]["where"] == f"positions.csv[row 0].{axis}"


@pytest.mark.parametrize("text", ["", "# scenario=test\n"])
def test_no_header_is_empty(tmp_path, text):
    path = tmp_path / "positions.csv"
    path.write_text(text)
    assert load_table(path) == {"columns": [], "rows": []}


@pytest.mark.parametrize("existing", [None, os.pathsep + "approved-lib" + os.pathsep * 2])
def test_unattended_launchers_close_stdin_and_clean_loader_paths(tmp_path, monkeypatch, existing):
    from scripts.sweep.config import SweepConfig
    from scripts.sweep.runner import run_sweep
    from scripts.validation import run_batch

    for var in ("DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH"):
        if existing is None:
            monkeypatch.delenv(var, raising=False)
        else:
            monkeypatch.setenv(var, existing)
    calls = []

    def fake_run(cmd, **kwargs):
        assert kwargs["stdin"] == subprocess.DEVNULL
        for var in ("DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH"):
            parts = kwargs["env"][var].split(os.pathsep)
            assert all(parts)
            assert len(parts) == (1 if existing is None else 2)
            if existing is not None:
                assert parts[-1] == "approved-lib"
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    (tmp_path / "sim.cc").touch()
    scenario = tmp_path / "inputs" / "base"
    scenario.mkdir(parents=True)
    (scenario / "run.ini").write_text("[scenario]\nnodes_file = nodes.json\n")
    (scenario / "nodes.json").write_text("[]\n")
    args = regression_check.build_parser().parse_args([
        "capture", "--sim-binary", sys.executable, "--run-config", str(scenario / "run.ini"),
        "--band", "mmwave", "--seed", "1", "--family", "baseline", "--case", "fake",
        "--out", str(tmp_path / "capture"),
    ])
    assert regression_check.cmd_capture(args) == 0
    assert run_batch.main(["--scenarios-dir", str(scenario.parent), "--seeds", "1",
                           "--sim-binary", sys.executable, "--out", str(tmp_path / "batch")]) == 0
    sweep = tmp_path / "sweep.ini"
    sweep.write_text("[sweep.meta]\n")
    run_sweep(SweepConfig(str(scenario), [1], "none", "", "fake"),
              str(sweep), sim_binary=sys.executable)
    assert len(calls) == 3


def test_missing_reference_explains_cloud_bundle(tmp_path):
    manifest = {"cases": [{"snapshot": "tests/fixtures/regression/p0/missing.json"}]}
    with pytest.raises(ValueError, match="Ask the project team.*cloud baseline bundle"):
        regression_check.verify_manifest_snapshots(manifest, tmp_path)
