"""Benchmark: process-tree sampling edges, run refusals and tolerance, estimate math.

Expectations come from scripts/rl/ops/README.md "Benchmark". No real process
is benchmarked here: launches and ps snapshots are injected.
"""

import copy
import json
import shutil

import pytest

from scripts.rl import experiment
from scripts.rl.cli_common import write_json
from scripts.rl.env.config import read_scenario_identity
from scripts.rl.ops import benchmark
from scripts.sim_support import find_mesh_root

from ._ops_gen_helpers import written_plan

TRACKED_MATRIX = find_mesh_root() / "inputs/experiments/bypass-smoke-matrix.json"


# --- process tree ------------------------------------------------------------


def test_gen_parent_cycles_and_unrelated_processes_never_count():
    table = benchmark.parse_ps("10 1 100\n11 10 200\n12 11 300\n"
                               "50 51 999\n51 50 999\n"   # a cycle, unrelated
                               "60 60 5\n"                # self-parent
                               "70 1 7000\n")             # orphan reparented to init
    assert benchmark.tree_usage(table, 10) == {"rss_kb": 600, "count": 3,
                                               "max_rss_kb": 300}


def test_gen_descendants_still_count_after_the_root_exited():
    table = benchmark.parse_ps("11 10 200\n12 11 300\n")
    assert benchmark.tree_usage(table, 10) == {"rss_kb": 500, "count": 2,
                                               "max_rss_kb": 300}


def test_gen_an_empty_tree_reports_zeroes():
    assert benchmark.tree_usage({}, 10) == {"rss_kb": 0, "count": 0, "max_rss_kb": 0}


def _reader(*outcomes):
    queue = list(outcomes)

    def read():
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item
    return read


def test_gen_a_sampler_that_never_reads_ps_nulls_memory():
    sampler = benchmark.TreeSampler(10, 60.0, _reader(benchmark.PsError("ps: denied")))
    sampler.start()
    sampler.stop()
    assert sampler.result() == {"peak_tree_rss_kb": None, "peak_process_count": None,
                                "peak_single_process_rss_kb": None, "samples": 0,
                                "measurement_error": "ps: denied"}


def test_gen_a_transient_ps_failure_keeps_the_peaks_and_the_error():
    sampler = benchmark.TreeSampler(
        10, 60.0, _reader(benchmark.PsError("ps: busy"), "10 1 100\n11 10 50\n"))
    sampler.sample()
    sampler.sample()
    sampler.sample()
    assert sampler.result() == {"peak_tree_rss_kb": 150, "peak_process_count": 2,
                                "peak_single_process_rss_kb": 100, "samples": 2,
                                "measurement_error": "ps: busy"}


def test_gen_the_first_sample_is_taken_immediately_after_spawn():
    sampler = benchmark.TreeSampler(10, 3600.0, _reader("10 1 42\n"))
    sampler.start()
    sampler.stop()
    assert sampler.result()["samples"] == 1
    assert sampler.result()["peak_tree_rss_kb"] == 42


# --- run ---------------------------------------------------------------------


class _Process:
    def __init__(self, code):
        self.pid, self._code = 10, code

    def wait(self):
        return self._code


class _Launcher:
    def __init__(self, codes):
        self.codes, self.launched = codes, []

    def __call__(self, step):
        self.launched.append(step["kind"])
        return _Process(self.codes.get(step["kind"], 0))


def _run(root, launcher, interval=0.05, index=0):
    return benchmark.run_benchmark(root, index, interval, launch=launcher,
                                   read=lambda: "10 1 1000\n")


@pytest.mark.parametrize("interval", [0, -1.0])
def test_gen_a_non_positive_sample_interval_is_refused_before_launch(tmp_path,
                                                                     interval, capsys):
    root = written_plan(tmp_path, 1)
    launcher = _Launcher({})
    assert _run(root, launcher, interval) == 1
    assert launcher.launched == [] and "must be > 0" in capsys.readouterr().err
    assert not (root / "benchmark").exists()


@pytest.mark.parametrize("index", [-1, 1])
def test_gen_an_out_of_range_task_is_refused(tmp_path, index, capsys):
    root = written_plan(tmp_path, 1)
    assert _run(root, _Launcher({}), index=index) == 1
    assert "outside 0..0" in capsys.readouterr().err


def test_gen_an_evaluation_warning_exit_is_tolerated_like_the_runner(tmp_path):
    root = written_plan(tmp_path, 1)
    launcher = _Launcher({"evaluate": 2})
    assert _run(root, launcher) == 0
    record = json.loads((root / "benchmark" / "task-0000.json").read_text())
    assert [(step["kind"], step["exit_code"], step["tolerated"])
            for step in record["steps"]] == [("train", 0, True), ("evaluate", 2, True)]
    assert record["steps"][0]["peak_tree_rss_kb"] == 1000


def test_gen_a_training_exit_2_stops_the_benchmark(tmp_path):
    root = written_plan(tmp_path, 1)
    launcher = _Launcher({"train": 2})
    assert _run(root, launcher) == 1
    assert launcher.launched == ["train"]
    record = json.loads((root / "benchmark" / "task-0000.json").read_text())
    assert record["steps"][0]["tolerated"] is False
    assert record["sampling"] == {"method": "ps-process-tree", "interval_s": 0.05,
                                  "note": benchmark.SAMPLING_NOTE}
    assert "missed" in record["sampling"]["note"]


# --- estimate ----------------------------------------------------------------


def _record(**train_overrides):
    matrix = experiment.load_matrix(TRACKED_MATRIX)
    row = matrix["rows"][0]
    train = {"kind": "train", "seconds_per_timestep": 0.5, "n_steps": 64,
             "eval_every_steps": 128, "eval_episodes": 1, "peak_tree_rss_kb": 1000,
             "scenario_identity": read_scenario_identity(row["run_config"]),
             "selection": {"observation_preset": row["observation_preset"],
                           "reward_components": row["reward_components"],
                           "reward_weights": row["reward_weights"]}}
    train.update(train_overrides)
    evaluate = {"kind": "evaluate", "seconds_per_episode": 2.0,
                "peak_tree_rss_kb": None}
    return {"task_id": "x", "task_index": 0, "host": {"system": "Linux",
                                                      "machine": "x86_64"},
            "steps": [train, evaluate]}


def _matrix():
    return copy.deepcopy(experiment.load_matrix(TRACKED_MATRIX))


def test_gen_the_target_budget_rounds_up_to_whole_rollouts():
    matrix = _matrix()
    matrix["training"]["total_timesteps"] = 300
    estimate = benchmark.build_estimate(_record(), matrix, 1.5)
    # 0.5 s x ceil(300/64)*64 = 320 timesteps + 2.0 s x 3 policies x 3 held-out seeds.
    row = estimate["rows"][0]
    assert row["per_task_seconds"] == 178.0
    assert row["per_task_with_safety_seconds"] == 267.0
    assert row["per_task_with_safety_hms"] == "00:04:27"
    assert estimate["totals"]["serial_seconds"] == 178.0 * 8
    assert estimate["totals"]["serial_with_safety_hms"] == "00:35:36"
    assert estimate["memory"] == {"peak_tree_rss_kb": 1000, "with_safety_kb": 1500.0}
    assert estimate["assumptions"]["is_cluster_estimate"] is False


def test_gen_scenarios_match_by_file_hashes_not_by_path(tmp_path, multi_run_config):
    matrix = _matrix()
    moved = tmp_path / "copied-scenario"
    shutil.copytree(find_mesh_root() / "inputs/baselines/building-bypass-smoke", moved)
    matrix["rows"][1]["run_config"] = str(moved / "run.ini")
    matrix["rows"][2]["run_config"] = multi_run_config
    estimate = benchmark.build_estimate(_record(), matrix, 1.0)
    reasons = [row["reason"] for row in estimate["rows"]]
    assert reasons == [None, None, "different scenario", None]
    assert estimate["task_count"] == 8 and estimate["estimated_task_count"] == 6
    assert estimate["totals"]["serial_seconds"] == 146.0 * 6


@pytest.mark.parametrize("change", ["no selection cadence", "other n_steps",
                                    "no n_steps"])
def test_gen_a_target_cadence_change_is_not_estimated(change):
    matrix = _matrix()
    if change == "no selection cadence":
        matrix["training"].pop("eval_every_steps")
    elif change == "other n_steps":
        matrix["training"]["n_steps"] = 128
    else:
        matrix["training"].pop("n_steps")
    estimate = benchmark.build_estimate(_record(), matrix, 1.0)
    assert {row["reason"] for row in estimate["rows"]} == {"different cadence"}
    assert estimate["totals"]["serial_with_safety_hms"] == "00:00:00"


def test_gen_a_benchmark_without_an_evaluate_step_is_refused():
    record = _record()
    record["steps"] = record["steps"][:1]
    with pytest.raises(ValueError, match="no evaluate step"):
        benchmark.build_estimate(record, _matrix(), 1.0)


def test_gen_a_negative_safety_factor_is_refused():
    with pytest.raises(ValueError, match="> 0"):
        benchmark.build_estimate(_record(), _matrix(), -2.0)


def test_gen_a_negative_duration_formats_as_zero():
    assert benchmark.format_hms(-5) == "00:00:00"
    assert benchmark.format_hms(0.001) == "00:00:01"


def test_gen_estimate_writes_nothing_when_the_benchmark_is_unreadable(tmp_path,
                                                                     capsys):
    bad = tmp_path / "task-0000.json"
    bad.write_text("{nope")
    out = tmp_path / "out" / "estimate.json"
    assert benchmark.main(["estimate", "--benchmark", str(bad), "--target-matrix",
                           str(TRACKED_MATRIX), "--safety-factor", "2",
                           "--output", str(out)]) == 1
    assert not out.exists() and not out.parent.exists()
    assert capsys.readouterr().err


def test_gen_estimate_output_is_valid_json_with_the_benchmark_digest(tmp_path):
    path = tmp_path / "task-0000.json"
    write_json(path, _record())
    out = tmp_path / "estimate.json"
    assert benchmark.run_estimate(path, TRACKED_MATRIX, 2.0, out) == 0
    payload = json.loads(out.read_text())
    assert payload["estimate_version"] == 1
    assert payload["benchmark"]["sha256"] and payload["target_matrix"]["sha256"]
    assert payload["safety_factor"] == 2.0
