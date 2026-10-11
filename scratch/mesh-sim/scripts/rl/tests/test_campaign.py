"""Local campaign scheduling: concurrency, prerequisites, locks, and cleanup."""

from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from scripts.rl import campaign, experiment
from scripts.sim_support import find_mesh_root


def _config(tmp_path):
    return {
        "inputs": str(tmp_path), "pilot": "pilot.json", "main_matrices": ["main.json"],
        "execution": {"sim_binary": sys.executable, "output_root": str(tmp_path / "output"),
                      "max_workers": 2, "threads_per_worker": 1,
                      "stages": ["preflight", "pilot", "main"]},
    }


@pytest.mark.parametrize("field,value", [("max_workers", 0), ("threads_per_worker", True),
                                         ("stages", ["main", "pilot"]),
                                         ("stages", [["main"]])])
def test_bad_scheduling_is_rejected(tmp_path, field, value):
    config = _config(tmp_path)
    config["execution"][field] = value
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        campaign.load_config(path)


def test_campaign_lock_prevents_duplicate_writers(tmp_path):
    with campaign.campaign_lock(tmp_path):
        with pytest.raises(RuntimeError, match="another campaign"):
            with campaign.campaign_lock(tmp_path):
                pass
    with campaign.campaign_lock(tmp_path):
        pass


class ConcurrentRunner:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self.commands = []

    def execute(self, command, log):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.commands.append((command, log))
        time.sleep(.04)
        with self.lock:
            self.active -= 1
        return 1 if command[command.index("--task-index") + 1] == "3" else 0

    def stop(self):
        pass


def test_jobs_overlap_with_worker_limit_and_isolated_logs(tmp_path):
    runner = ConcurrentRunner()
    jobs = [{"id": f"row-{i}", "root": str(tmp_path / f"plan-{i}"), "index": i}
            for i in range(5)]
    record = {"jobs": {}}
    path = tmp_path / "status.json"
    failed = campaign.run_jobs(jobs, 2, runner, record, path)
    assert runner.peak == 2 and runner.active == 0
    assert failed == {str(tmp_path / "plan-3")}
    assert len({str(log) for _, log in runner.commands}) == 5
    assert json.loads(path.read_text())["jobs"]["row-3"]["status"] == "failed"
    assert sum(j["status"] == "completed" for j in record["jobs"].values()) == 4
    for command, log in runner.commands:
        assert command[1:3] == ["-m", "scripts.rl.ops.run_task"]
        assert command[-1] == str(log.with_suffix(".json"))


def test_process_thread_limits_and_stop_reaps_child(tmp_path):
    runner = campaign.ProcessRunner(1)
    before = dict(os.environ)
    log = tmp_path / "process.log"
    code = "import os,time; print(os.environ['OMP_NUM_THREADS'], flush=True); time.sleep(60)"
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runner.execute, [sys.executable, "-c", code], log)
        deadline = time.monotonic() + 5
        while not log.is_file() or not log.read_text().strip():
            assert time.monotonic() < deadline
            time.sleep(.01)
        with runner.lock:
            proc = next(iter(runner.active.values()))
        runner.stop()
        assert future.result(timeout=5) != 0
    assert proc.poll() is not None and not runner.active
    assert log.read_text().strip() == "1" and dict(os.environ) == before
    assert runner.execute([sys.executable, "-c", "raise RuntimeError"], log) == 130


def test_interruption_during_preflight_wait_reaps_child(tmp_path, monkeypatch):
    original = subprocess.Popen.wait
    interrupted = set()

    def wait(proc, *args, **kwargs):
        if not args and not kwargs and proc.pid not in interrupted:
            interrupted.add(proc.pid)
            raise KeyboardInterrupt
        return original(proc, *args, **kwargs)

    monkeypatch.setattr(subprocess.Popen, "wait", wait)
    runner = campaign.ProcessRunner(1)
    with pytest.raises(KeyboardInterrupt):
        runner.execute([sys.executable, "-c", "import time; time.sleep(60)"], tmp_path / "preflight.log")
    assert not runner.active and interrupted


def test_preflight_failure_prevents_all_training(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr(campaign, "prepare_phase", lambda config, phase: ([], [{"id": phase}]))
    monkeypatch.setattr(campaign, "run_preflight", lambda config, runner: 1)
    monkeypatch.setattr(campaign, "run_jobs", lambda *args: pytest.fail("must not train"))
    assert campaign.run_campaign(config) == 1
    record = json.loads((tmp_path / "output/campaign_status.json").read_text())
    assert record["status"] == "failed" and "preflight failed" in record["error"]


def test_failed_pilot_prevents_main_and_comparison(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr(campaign, "prepare_phase", lambda config, phase:
                        ([tmp_path / phase], [{"id": phase}]))
    monkeypatch.setattr(campaign, "run_preflight", lambda config, runner: 0)
    phases = []

    def run_jobs(jobs, *args):
        phases.append(jobs[0]["id"])
        return {str(tmp_path / "pilot")}

    monkeypatch.setattr(campaign, "run_jobs", run_jobs)
    monkeypatch.setattr(campaign.ProcessRunner, "execute", lambda *args: pytest.fail("must not compare"))
    assert campaign.run_campaign(config) == 1
    assert phases == ["pilot"]


def test_actual_campaign_plans_all_33_jobs_without_launching(tmp_path, monkeypatch):
    if not (find_mesh_root()/"inputs/custom/10-09/campaign.json").is_file():
        pytest.skip("private local campaign inputs are not present")
    path = find_mesh_root() / "inputs/custom/10-09/campaign.json"
    if not path.is_file():
        pytest.skip("local October 9 campaign inputs are not present")
    config = copy.deepcopy(json.loads(path.read_text()))
    config["execution"].update(sim_binary=sys.executable, output_root=str(tmp_path / "output"))
    config["pilot"] = str(path.parent / config["pilot"])
    config["main_matrices"] = [str(path.parent / name) for name in config["main_matrices"]]
    config_path = tmp_path / "campaign.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(campaign.ProcessRunner, "execute", lambda *args: pytest.fail("must not launch"))
    assert campaign.main(["--config", str(config_path), "--plan-only"]) == 0
    plans = list((tmp_path / "output").rglob(experiment.PLAN_NAME))
    assert len(plans) == 9
    tables = [campaign.build_tasks(json.loads(plan.read_text())) for plan in plans]
    assert sum(map(len, tables)) == 33
    assert len({task["train"]["output_dir"] for table in tables for task in table}) == 33
    assert len({task["evaluate"]["output_dir"] for table in tables for task in table}) == 33


def test_two_real_worker_processes_train_evaluate_and_compare(tmp_path, sim_binary,
                                                             multi_run_config, monkeypatch):
    """Fake radio peer, real PPO and worker processes; preflight tested separately."""
    pytest.importorskip("sb3_contrib")
    matrix = {
        "matrix_version": 1, "name": "concurrent-smoke", "run_config": multi_run_config,
        "band": None,
        "seeds": {"training": [11, 12], "model_selection": [21, 22], "held_out": [31, 32]},
        "training": {"total_timesteps": 16, "n_steps": 8, "eval_every_steps": 8},
        "evaluation": {"model": "best", "policies": ["model", "hold", "random_valid"]},
        "rows": [{"name": "smoke", "observation_preset": "full_facts_v1",
                  "action_profile": "move_2d", "reward_components": ["delivery_ratio"],
                  "reward_weights": [1.0]}],
    }
    (tmp_path / "main.json").write_text(json.dumps(matrix))
    config = _config(tmp_path)
    config["execution"].update(sim_binary=sim_binary, stages=["main"])
    monkeypatch.setattr(campaign, "run_preflight", lambda *args: 0)
    result = campaign.run_campaign(config)
    root = tmp_path / "output"
    logs = "\n".join(p.read_text() for p in root.rglob("*.log"))
    assert result == 0, logs
    record = json.loads((root / "campaign_status.json").read_text())
    assert record["status"] == "completed" and len(record["jobs"]) == 2
    assert len(list(root.rglob("train_manifest.json"))) == 2
    assert len(list(root.rglob("eval_manifest.json"))) == 2
    assert len(list(root.rglob("comparison.json"))) == 1
    assert len(list(root.rglob("task-*.log"))) == 2
    assert len(list(root.rglob("reward_matrix.json"))) >= 6
    # A second launch reuses complete training/evaluation steps.
    assert campaign.run_campaign(config) == 0
    assert len(list(root.rglob("train_manifest.json"))) == 2
