"""SLURM adapter edge cases: parsers, config schema, argv, job scripts, query shims.

Every scheduler binary here is a canned shim written under tmp_path; no real
SLURM command is run. Expectations come from scripts/rl/ops/README.md
("Cluster config", "Receipts and the submission protocol", "Reported states").
"""

import json
import os
import re
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from scripts.rl.cli_common import write_json
from scripts.rl.ops import slurm

from ._ops_gen_helpers import config_body, make_venv


@pytest.fixture
def venv(tmp_path):
    return make_venv(tmp_path)


def _config(tmp_path, venv, mutate=None) -> dict:
    body = config_body(venv)
    if mutate:
        mutate(body)
    path = tmp_path / "config.json"
    write_json(path, body)
    return slurm.load_cluster_config(path)


def _shim(bin_dir: Path, name: str, stdout: str = "", code: int = 0,
          stderr: str = "") -> Path:
    """Canned scheduler command that logs its argv to <bin>/<name>.argv.json."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    log = bin_dir / f"{name}.argv.json"
    script = bin_dir / name
    script.write_text(textwrap.dedent(f"""\
        #!{sys.executable}
        import json, sys
        from pathlib import Path
        log = Path({str(log)!r})
        calls = json.loads(log.read_text()) if log.exists() else []
        calls.append(sys.argv[1:])
        log.write_text(json.dumps(calls))
        sys.stdout.write({stdout!r})
        sys.stderr.write({stderr!r})
        sys.exit({code})
        """))
    script.chmod(0o755)
    return log


def _calls(log: Path) -> list[list[str]]:
    return json.loads(log.read_text()) if log.exists() else []


# --- parsers -----------------------------------------------------------------


def test_gen_parse_squeue_skips_blank_short_and_whitespace_lines():
    text = ("\n   \n"
            "1000_0|RUNNING\n"                       # too few columns
            "  1000_1 | PENDING | Priority | N/A  \n"
            "1000_2|RUNNING|None|N/A|extra|columns\n")
    jobs = slurm.parse_squeue(text)
    assert jobs == {"1000_1": {"state": "PENDING", "reason": "Priority", "start": "N/A"},
                    "1000_2": {"state": "RUNNING", "reason": "None", "start": "N/A"}}


EXPANSIONS = [
    ("1000_[0-3%2]", ["1000_0", "1000_1", "1000_2", "1000_3"]),
    ("1000_[0,2-3,7%2]", ["1000_0", "1000_2", "1000_3", "1000_7"]),
    ("1000_[5]", ["1000_5"]),
    ("1000_[9-11]", ["1000_9", "1000_10", "1000_11"]),
    ("1000_12", ["1000_12"]),
    ("1000", ["1000"]),
]


@pytest.mark.parametrize("job_id,expected", EXPANSIONS,
                         ids=[case[0] for case in EXPANSIONS])
def test_gen_collapsed_array_ids_expand_to_exact_elements(job_id, expected):
    jobs = slurm.parse_squeue(f"{job_id}|PENDING|JobArrayTaskLimit|N/A\n")
    assert sorted(jobs) == sorted(expected)
    jobs = slurm.parse_sacct(f"{job_id}|PENDING|0:0\n")
    assert sorted(jobs) == sorted(expected)


def test_gen_a_garbled_array_range_yields_no_element():
    assert slurm.parse_squeue("1000_[a-b]|PENDING|None|N/A\n") == {}


def test_gen_heterogeneous_job_ids_are_kept_literally_and_filtered_out():
    # "1234+0" is a het-job component, never one of our array elements.
    assert "1234+0" in slurm.parse_squeue("1234+0|RUNNING|None|N/A\n")
    assert slurm.parse_sacct("1234+0.batch|RUNNING|0:0\n") == {}


def test_gen_parse_sacct_normalizes_every_cancelled_spelling_and_drops_steps():
    text = ("1000_0|CANCELLED+|0:15\n"
            "1000_1|CANCELLED by 0|0:15\n"
            "1000_2| OUT_OF_MEMORY |0:125\n"
            "1000_2.batch|OUT_OF_MEMORY|0:125\n"
            "1000_2.extern|COMPLETED|0:0\n"
            "1000_2.0|OUT_OF_MEMORY|0:125\n"
            "1000_3|NODE_FAIL|0:0|extra\n"
            "1000_4|PREEMPTED\n"
            "\n")
    jobs = slurm.parse_sacct(text)
    assert jobs == {"1000_0": {"state": "CANCELLED", "exit": "0:15"},
                    "1000_1": {"state": "CANCELLED", "exit": "0:15"},
                    "1000_2": {"state": "OUT_OF_MEMORY", "exit": "0:125"},
                    "1000_3": {"state": "NODE_FAIL", "exit": "0:0"}}


def test_gen_a_state_that_merely_starts_like_cancelled_is_not_normalized():
    assert slurm.parse_sacct("1000_0|CANCELLEDX|0:0\n")["1000_0"]["state"] \
        == "CANCELLEDX"


JOB_IDS = [
    ("sbatch: warning: partition default used\n4321\n", "4321"),
    ("  4321  \n", "4321"),
    ("4321;cluster-b\n", "4321"),
    ("Submitted batch job 4321\n", None),
    ("4321a\n", None),
    ("\n\n", None),
]


@pytest.mark.parametrize("text,expected", JOB_IDS)
def test_gen_parse_job_id_accepts_only_a_bare_parsable_id(text, expected):
    assert slurm.parse_job_id(text) == expected


# --- array spec, argv, names -------------------------------------------------


ARRAY_SPECS = [([7, 7, 0, 1, 1], None, "0-1,7"), ([0, 2, 4], None, "0,2,4"),
               ([10, 11, 12, 20], 3, "10-12,20%3"), ([5], 1, "5%1")]


@pytest.mark.parametrize("indices,limit,expected", ARRAY_SPECS)
def test_gen_array_spec_sorts_dedups_and_caps(indices, limit, expected):
    assert slurm.array_spec(indices, limit) == expected


def test_gen_array_spec_refuses_an_empty_selection():
    with pytest.raises(ValueError, match="at least one"):
        slurm.array_spec([])


def test_gen_sbatch_argv_keeps_safety_flags_first_and_the_script_last(tmp_path, venv):
    config = _config(tmp_path, venv,
                     lambda body: body["task"].update(partition="p", qos="q"))
    argv = slurm.sbatch_argv(config, "tasks", "meshops-n-tasks", "/l/%A_%a.out",
                             Path("/s/0001-tasks.sh"), array="0-3%2",
                             dependency="afterany:1")
    assert argv[:4] == ["sbatch", "--parsable", "--no-requeue",
                        "--job-name=meshops-n-tasks"]
    assert argv[-1] == "/s/0001-tasks.sh"
    assert argv.count("--no-requeue") == 1
    assert "--partition=p" in argv and "--qos=q" in argv
    assert not any(token.startswith(("--account", "--constraint")) for token in argv)
    assert all(not token.startswith("--requeue") for token in argv)


def test_gen_compare_inherits_placement_but_not_resources(tmp_path, venv):
    config = _config(tmp_path, venv, lambda body: body["task"].update(
        partition="p", account="acct", qos="q", constraint="c"))
    argv = slurm.sbatch_argv(config, "compare", "meshops-n-compare", "/l/c-%j.out",
                             "/s/c.sh")
    for expected in ("--partition=p", "--account=acct", "--qos=q", "--constraint=c",
                     "--time=00:10:00", "--mem=1G", "--cpus-per-task=1"):
        assert expected in argv
    assert "--time=01:00:00" not in argv and "--array" not in " ".join(argv)


@pytest.mark.parametrize("call", [
    lambda config: slurm.sbatch_argv(config, "array", "n", "/l", "/s"),
    lambda config: slurm.resources(config, "task"),
    lambda config: slurm.job_name("tasks-and-compare")])
def test_gen_an_unknown_job_role_is_refused(tmp_path, venv, call):
    with pytest.raises(ValueError, match="unknown job role"):
        call(_config(tmp_path, venv))


def test_gen_job_names_are_random_128_bit_tokens():
    names = {slurm.job_name("tasks") for _ in range(50)}
    assert len(names) == 50
    assert all(re.fullmatch(r"meshops-[0-9a-f]{32}-tasks", name) for name in names)
    assert re.fullmatch(r"meshops-[0-9a-f]{32}-compare", slurm.job_name("compare"))


# --- cluster config schema ---------------------------------------------------


REFUSALS = [
    ("compare cannot set its own partition",
     lambda body: body["compare"].update(partition="other"), "unknown keys"),
    ("empty partition string", lambda body: body["task"].update(partition=""),
     "non-empty string"),
    ("placeholder partition",
     lambda body: body["task"].update(partition="<site partition>"), "placeholder"),
    ("placeholder venv", lambda body: body.update(venv="<REQUIRED venv>"),
     "placeholder"),
    ("boolean max_array_size", lambda body: body.update(max_array_size=True),
     "integer >= 1"),
    ("float cpus", lambda body: body["task"].update(cpus_per_task=1.5),
     "integer >= 1"),
    ("zero cpus", lambda body: body["compare"].update(cpus_per_task=0),
     "integer >= 1"),
    ("negative max_array_size", lambda body: body.update(max_array_size=-1),
     "integer >= 1"),
    ("minutes past 59", lambda body: body["task"].update(time="04:60:00"), "HH:MM:SS"),
    ("bare minutes", lambda body: body["task"].update(time="90"), "HH:MM:SS"),
    ("lowercase memory suffix", lambda body: body["task"].update(mem="4g"),
     "4G or 4000M"),
    ("two-letter memory suffix", lambda body: body["task"].update(mem="4GB"),
     "4G or 4000M"),
    ("setup_lines not a list", lambda body: body.update(setup_lines="module load x"),
     "setup_lines"),
    ("setup_lines with a non-string", lambda body: body.update(setup_lines=[1]),
     "setup_lines"),
    ("task block not an object", lambda body: body.update(task=[]), "JSON object"),
    ("unknown compare key", lambda body: body["compare"].update(gres="gpu:1"),
     "unknown keys"),
]


@pytest.mark.parametrize("mutate,message", [case[1:] for case in REFUSALS],
                         ids=[case[0] for case in REFUSALS])
def test_gen_cluster_config_refusals(tmp_path, venv, mutate, message):
    with pytest.raises(ValueError, match=message):
        _config(tmp_path, venv, mutate)


def test_gen_a_top_level_array_is_not_a_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="JSON object"):
        slurm.load_cluster_config(path)


ACCEPTED = [
    ("day prefix", lambda body: body["task"].update(time="1-04:00:00")),
    ("one-digit hour", lambda body: body["task"].update(time="4:00:00")),
    ("bare megabytes", lambda body: body["task"].update(mem="4000")),
    ("terabytes", lambda body: body["task"].update(mem="1T")),
    ("concurrency cap", lambda body: body.update(max_concurrent_tasks=5)),
]


@pytest.mark.parametrize("mutate", [case[1] for case in ACCEPTED],
                         ids=[case[0] for case in ACCEPTED])
def test_gen_documented_value_shapes_are_accepted(tmp_path, venv, mutate):
    config = _config(tmp_path, venv, mutate)
    assert set(config) == {"cluster_config_version", "name", "venv", "setup_lines",
                           "task", "compare", "max_array_size",
                           "max_concurrent_tasks"}


def test_gen_the_config_carries_no_defaults_of_its_own(tmp_path, venv):
    config = _config(tmp_path, venv)
    assert slurm.resources(config, "tasks") == {
        "partition": None, "account": None, "qos": None, "constraint": None,
        "time": "01:00:00", "mem": "2G", "cpus_per_task": 2}


# --- rendered job scripts, executed by bash with a recording python ----------


def _recording_python(venv: Path, fail_bootstrap: int = 0) -> None:
    """Replace venv/bin/python with a recorder of argv, cwd, and thread env."""
    code = textwrap.dedent(f"""\
        import json, os, sys
        args = sys.argv[1:]
        with open(os.environ["GEN_LOG"], "a") as fh:
            fh.write(json.dumps({{"argv": args, "cwd": os.getcwd(),
                "omp": os.environ.get("OMP_NUM_THREADS"),
                "mkl": os.environ.get("MKL_NUM_THREADS"),
                "cuda": os.environ.get("CUDA_VISIBLE_DEVICES"),
                "setup": os.environ.get("GEN_SETUP")}}) + "\\n")
        if args and args[0].endswith("bootstrap_venv.py"):
            sys.exit({fail_bootstrap})
        """)
    recorder = venv.parent / "recorder.py"
    recorder.write_text(code)
    python = venv / "bin" / "python"
    python.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} '
                      f'{shlex.quote(str(recorder))} "$@"\n')
    python.chmod(0o755)


@pytest.fixture
def odd_paths(tmp_path):
    base = tmp_path / "it's a $HOME dir"
    venv = make_venv(base)
    mesh_root = base / "mesh root"
    mesh_root.mkdir()
    output_root = base / "out `x`"
    records = output_root / "cluster" / "records" / "0001"
    return venv, mesh_root, output_root, records


def _execute(script: str, tmp_path: Path, task_id: str | None = "7"):
    path = tmp_path / "job.sh"
    path.write_text(script)
    log = tmp_path / "calls.jsonl"
    env = {"PATH": os.environ["PATH"], "GEN_LOG": str(log)}
    if task_id is not None:
        env["SLURM_ARRAY_TASK_ID"] = task_id
    proc = subprocess.run(["bash", str(path)], env=env, capture_output=True, text=True)
    calls = [json.loads(line) for line in log.read_text().splitlines()] \
        if log.exists() else []
    return proc, calls


def test_gen_the_task_script_survives_hostile_paths_end_to_end(tmp_path, odd_paths):
    venv, mesh_root, output_root, records = odd_paths
    _recording_python(venv)
    config = _config(tmp_path, venv,
                     lambda body: body.update(setup_lines=["export GEN_SETUP=on"]))
    script = slurm.render_task_script(config, mesh_root, output_root, records)

    proc, calls = _execute(script, tmp_path)
    assert proc.returncode == 0, proc.stderr
    bootstrap, runner = calls
    assert bootstrap["argv"] == ["scripts/rl/bootstrap_venv.py", "--venv", str(venv),
                                 "--check"]
    assert runner["argv"] == ["-m", "scripts.rl.ops.run_task",
                              "--output-root", str(output_root),
                              "--task-index", "7",
                              "--record", str(records / "task-0007.json")]
    for call in calls:
        assert call["cwd"] == str(mesh_root)
        assert (call["omp"], call["mkl"], call["cuda"]) == ("2", "2", "")
        assert call["setup"] == "on"


def test_gen_the_compare_script_uses_the_compare_cpus_and_strict_mode(tmp_path,
                                                                      odd_paths):
    venv, mesh_root, output_root, records = odd_paths
    _recording_python(venv)
    config = _config(tmp_path, venv)
    script = slurm.render_compare_script(config, mesh_root, output_root, records)

    proc, calls = _execute(script, tmp_path, task_id=None)
    assert proc.returncode == 0, proc.stderr
    assert calls[1]["argv"] == ["-m", "scripts.rl.ops.run_task",
                                "--output-root", str(output_root), "--compare",
                                "--record", str(records / "compare.json")]
    assert calls[1]["omp"] == "1"


def test_gen_a_failed_bootstrap_check_stops_the_job_before_any_step(tmp_path,
                                                                    odd_paths):
    venv, mesh_root, output_root, records = odd_paths
    _recording_python(venv, fail_bootstrap=3)
    script = slurm.render_task_script(_config(tmp_path, venv), mesh_root,
                                      output_root, records)
    proc, calls = _execute(script, tmp_path)
    assert proc.returncode == 3
    assert len(calls) == 1 and calls[0]["argv"][0].endswith("bootstrap_venv.py")


# --- scheduler queries through canned shims ----------------------------------


@pytest.fixture
def shims(tmp_path, monkeypatch):
    bin_dir = tmp_path / "shim-bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))
    return bin_dir


def test_gen_snapshot_without_job_ids_runs_no_command(shims):
    snapshot = slurm.snapshot([], "me")
    assert snapshot == {"queue": {"ok": True, "jobs": {}},
                        "accounting": {"ok": True, "jobs": {}}}
    assert list(shims.iterdir()) == []


def test_gen_snapshot_queries_by_base_id_and_filters_foreign_jobs(shims):
    squeue = _shim(shims, "squeue", "1000_[2-3]|PENDING|Priority|N/A\n"
                                    "1000_0|RUNNING|None|N/A\n"
                                    "1001_0|RUNNING|None|N/A\n"
                                    "999_0|RUNNING|None|N/A\n")
    sacct = _shim(shims, "sacct", "1000|COMPLETED|0:0\n"
                                  "1000_1|TIMEOUT|0:1\n"
                                  "1000_1.batch|CANCELLED|0:15\n"
                                  "4242_0|FAILED|1:0\n")
    snapshot = slurm.snapshot(["1000", "1000_3", "1001", "1000"], "alice")
    assert sorted(snapshot["queue"]["jobs"]) == ["1000_0", "1000_2", "1000_3",
                                                 "1001_0"]
    assert sorted(snapshot["accounting"]["jobs"]) == ["1000", "1000_1"]
    assert snapshot["accounting"]["jobs"]["1000_1"]["state"] == "TIMEOUT"

    (queue_argv,) = _calls(squeue)
    assert {"--noheader", "--array", "--states=all", "--user=alice",
            "--format=%i|%T|%r|%S"} <= set(queue_argv)
    (sacct_argv,) = _calls(sacct)
    assert "--jobs=1000,1001" in sacct_argv
    assert {"--array", "--parsable2", "--noheader"} <= set(sacct_argv)


def test_gen_one_failed_query_does_not_hide_the_other(shims):
    _shim(shims, "squeue", "", code=1, stderr="slurm_load_jobs error: timeout\n")
    _shim(shims, "sacct", "1000_0|FAILED|1:0\n")
    snapshot = slurm.snapshot(["1000"], "alice")
    assert snapshot["queue"] == {"ok": False, "jobs": {},
                                 "error": "slurm_load_jobs error: timeout"}
    assert snapshot["accounting"]["ok"] is True
    assert snapshot["accounting"]["jobs"]["1000_0"]["state"] == "FAILED"


def test_gen_find_jobs_by_name_matches_the_exact_name_only(shims):
    name = "meshops-" + "a" * 32 + "-tasks"
    _shim(shims, "squeue", f"1000_0|{name}|PENDING\n"
                           f"1000_1|{name}|PENDING\n"
                           f"1003_0|{name}x|PENDING\n"
                           f"1004_0|x{name}|PENDING\n"
                           "short|line\n")
    _shim(shims, "sacct", f"1000_0|{name}|PENDING\n"
                          f"1000_0.batch|{name}|PENDING\n"
                          f"1005|{name[:-1]}|COMPLETED\n")
    found = slurm.find_jobs_by_name(name, "alice")
    assert found == {"ok": True, "job_ids": ["1000"], "states": {"1000": "PENDING"},
                     "error": ""}


def test_gen_find_jobs_by_name_merges_a_match_with_a_failed_query(shims):
    name = "meshops-" + "b" * 32 + "-compare"
    _shim(shims, "squeue", "", code=1, stderr="squeue down\n")
    _shim(shims, "sacct", f"2000|{name}|COMPLETED\n")
    found = slurm.find_jobs_by_name(name, "alice")
    assert found["ok"] is False and found["job_ids"] == ["2000"]
    assert found["error"] == "squeue down"


def test_gen_find_jobs_by_name_reports_several_matches(shims):
    name = "meshops-" + "c" * 32 + "-tasks"
    _shim(shims, "squeue", f"1000_0|{name}|PENDING\n")
    _shim(shims, "sacct", f"1001_0|{name}|FAILED\n")
    assert slurm.find_jobs_by_name(name, "alice")["job_ids"] == ["1000", "1001"]


def test_gen_cancel_passes_ids_verbatim_and_refuses_an_empty_list(shims):
    log = _shim(shims, "scancel")
    result = slurm.cancel(["1000_2", "1000_5", "2000"])
    assert result["ok"] is True
    assert _calls(log) == [["1000_2", "1000_5", "2000"]]
    with pytest.raises(ValueError, match="at least one"):
        slurm.cancel([])


def test_gen_submit_sets_no_job_id_on_a_failed_or_unparseable_sbatch(shims):
    _shim(shims, "sbatch", "1234\n", code=1, stderr="error after queueing\n")
    result = slurm.submit(["sbatch", "--parsable", "x.sh"])
    assert result["ok"] is False and result["job_id"] is None
    assert result["stdout"] == "1234\n"


def test_gen_a_missing_binary_is_a_failed_result_not_an_exception(shims):
    result = slurm.cancel(["1000_1"])
    assert result["ok"] is False and result["returncode"] is None
    assert "FileNotFoundError" in result["stderr"]
    assert slurm.available("sbatch") is False
