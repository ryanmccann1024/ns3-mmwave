"""Run a local RL campaign from one configuration with bounded concurrent jobs."""

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

from scripts.rl import experiment
from scripts.rl.cli_common import now_iso, write_json
from scripts.rl.ops.tasks import build_tasks
from scripts.sim_support import find_mesh_root, stop_process

THREAD_VARIABLES = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS")


def load_config(path):
    """Resolve execution paths against the mesh root and validate scheduling fields."""
    path = Path(path).resolve()
    data = json.loads(path.read_text())
    execution = dict(data.get("execution") or {})
    allowed = {"sim_binary", "output_root", "max_workers", "threads_per_worker", "stages"}
    if set(execution) != allowed:
        raise ValueError(f"execution requires exactly {sorted(allowed)}")
    for name in ("max_workers", "threads_per_worker"):
        value = execution[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"execution.{name} must be a positive integer")
    stages = execution["stages"]
    if (not isinstance(stages, list) or not stages or any(not isinstance(stage, str) for stage in stages)
            or len(stages) != len(set(stages))
            or any(stage not in ("preflight", "pilot", "main") for stage in stages)):
        raise ValueError("execution.stages must be distinct preflight/pilot/main names")
    if "preflight" in stages and stages[0] != "preflight":
        raise ValueError("preflight must be the first stage")
    if "pilot" in stages and "main" in stages and stages.index("pilot") > stages.index("main"):
        raise ValueError("pilot must precede main")
    mesh = find_mesh_root()
    for name in ("sim_binary", "output_root"):
        value = Path(execution[name]).expanduser()
        execution[name] = str((mesh/value).resolve() if not value.is_absolute() else value.resolve())
    if not Path(execution["sim_binary"]).is_file():
        raise ValueError(f"simulator binary does not exist: {execution['sim_binary']}")
    return {**data, "execution": execution, "path": str(path), "inputs": str(path.parent)}


@contextmanager
def campaign_lock(root):
    """Prevent two launchers from writing into the same campaign output tree."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root/"campaign.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"another campaign launcher is using {root}") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class ProcessRunner:
    """Own local process groups and constrain numeric-library threads per job."""

    def __init__(self, threads):
        self.env = dict(os.environ)
        self.env.update({name: str(threads) for name in THREAD_VARIABLES})
        self.env["PYTHONUNBUFFERED"] = "1"
        self.lock = threading.Lock()
        self.active = {}
        self.stopped = threading.Event()

    def execute(self, command, log):
        log = Path(log)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as handle:
            with self.lock:
                if self.stopped.is_set():
                    return 130
                proc = subprocess.Popen(command, cwd=str(find_mesh_root()), env=self.env,
                                        stdout=handle, stderr=subprocess.STDOUT,
                                        start_new_session=True)
                self.active[proc.pid] = proc
            try:
                return proc.wait()
            except BaseException:
                stop_process(proc, 3, process_group=True)
                raise
            finally:
                with self.lock:
                    self.active.pop(proc.pid, None)

    def stop(self):
        self.stopped.set()
        with self.lock:
            active = list(self.active.values())
        for proc in active:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for proc in active:
            stop_process(proc, 3, process_group=True)



def prepare_phase(config, phase):
    """Write immutable experiment plans and flatten their row/seed tasks into local jobs."""
    base = Path(config["inputs"])
    root = Path(config["execution"]["output_root"])/phase
    matrices = [config["pilot"]] if phase == "pilot" else config["main_matrices"]
    plans, jobs = [], []
    for relative in matrices:
        matrix_path = base/relative
        destination = root/matrix_path.stem
        code = experiment.main(["plan", "--matrix", str(matrix_path), "--output-root", str(destination),
                                "--sim-binary", config["execution"]["sim_binary"]])
        if code:
            raise ValueError(f"could not prepare {matrix_path}")
        plan = experiment.load_plan(destination)
        plans.append(destination)
        for task in build_tasks(plan):
            jobs.append({"id": f"{phase}/{matrix_path.stem}/{task['id']}", "root": str(destination),
                         "index": task["index"]})
    # Interleave scenarios so the first worker slots do not all go to one scene.
    jobs.sort(key=lambda job: job["index"])
    return plans, jobs


def run_jobs(jobs, workers, runner, record, record_path):
    """Run independent train/evaluate pairs concurrently and report each terminal state."""
    pool = ThreadPoolExecutor(max_workers=workers)
    pending = {}
    plans = sorted({Path(job["root"]) for job in jobs
                    if (Path(job["root"])/experiment.PLAN_NAME).is_file()})
    try:
        for job in jobs:
            log = Path(job["root"])/"local"/f"task-{job['index']}.log"
            command = [sys.executable, "-m", "scripts.rl.ops.run_task", "--output-root", job["root"],
                       "--task-index", str(job["index"]), "--record", str(log.with_suffix(".json"))]
            pending[pool.submit(runner.execute, command, log)] = job
        failures = set()
        while pending:
            done, _ = wait(pending, timeout=30, return_when=FIRST_COMPLETED)
            if not done:
                report_progress([job for future, job in pending.items() if future.running()])
            for future in done:
                job = pending.pop(future)
                try:
                    code = future.result()
                    detail = None
                except Exception as exc:
                    code, detail = 1, f"{type(exc).__name__}: {exc}"
                if code:
                    failures.add(job["root"])
                record["jobs"][job["id"]] = {"status": "completed" if code == 0 else "failed",
                                              "exit_code": code, "error": detail}
                write_json(record_path, record)
                if plans:
                    write_reward_summary(plans, Path(record_path).parent)
                print(f"{job['id']}: {'completed' if code == 0 else 'failed'} ({code})", flush=True)
        return failures
    except BaseException:
        runner.stop()
        for future in pending:
            future.cancel()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def report_progress(jobs):
    """Print active workers' saved training progress without changing their outputs."""
    for job in jobs:
        try:
            task = build_tasks(experiment.load_plan(job["root"]))[job["index"]]
            training = Path(task["train"]["output_dir"])
            manifest = training/"train_manifest.json"
            state = json.loads(manifest.read_text())["status"] if manifest.is_file() else "starting"
            if state == "completed":
                detail = "training complete; evaluating"
            else:
                progress = training/"ppo/progress.csv"
                rows = []
                if progress.is_file():
                    with progress.open() as handle:
                        rows = list(csv.DictReader(handle))
                steps = int(float(rows[-1]["time/total_timesteps"])) if rows else 0
                args = task["train"]["args"]
                budget = int(args[args.index("--total-timesteps")+1]) if "--total-timesteps" in args else 100000
                detail = f"{steps:,}/{budget:,} training decisions ({100*steps/budget:.0f}%)"
            print(f"{job['id']}: {detail}", flush=True)
        except (OSError, ValueError, KeyError, IndexError):
            print(f"{job['id']}: running; progress not yet available", flush=True)


def write_reward_summary(plans, output):
    """Compare common domain metrics across reward rows without ranking unlike returns."""
    rows = []
    metrics = ("delivery_ratio", "worst_node_delivery_fraction", "post_jammer_delivery_ratio", "recovery_time_s", "coverage_fraction_mean", "unsafe_proximity_fraction",
               "travel_m_total", "displacement_m_final")
    for root in plans:
        plan = experiment.load_plan(root)
        for evaluation in plan["evaluations"]:
            path = Path(evaluation["eval_dir"])/"eval_manifest.json"
            if not path.is_file():
                continue
            manifest = json.loads(path.read_text())
            for policy, result in manifest["policies"].items():
                episodes = [episode for episode in result["episodes"] if episode["status"] == "completed"]
                row = {"scenario": Path(root).name, "reward": evaluation["label"],
                       "training_seed": evaluation["training_seed"], "policy": policy,
                       "completed_episodes": len(episodes)}
                for metric in metrics:
                    values = [episode["metrics"].get(metric) for episode in episodes]
                    values = [value for value in values if value is not None]
                    row[metric] = sum(values)/len(values) if values else None
                rows.append(row)
    fields = ("scenario", "reward", "training_seed", "policy", "completed_episodes", *metrics)
    with (Path(output)/"reward_comparison.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_preflight(config, runner):
    """Reuse a matching successful preflight, otherwise run it before any training."""
    root = Path(config["execution"]["output_root"])/"preflight"
    command = [sys.executable, "-m", "scripts.rl.preflight_campaign", "--inputs", config["inputs"],
               "--sim-binary", config["execution"]["sim_binary"], "--output-root", str(root)]
    if (root/"preflight.json").is_file() or "preflight" not in config["execution"]["stages"]:
        command += ["--check"]
    print("Checking simulator and scenario preflight…", flush=True)
    return runner.execute(command, root/"preflight.log")


def run_campaign(config, plan_only=False):
    root = Path(config["execution"]["output_root"])
    runner = ProcessRunner(config["execution"]["threads_per_worker"])
    record = {"campaign_version": 1, "status": "running", "started_at": now_iso(), "jobs": {}}
    record_path = root/"campaign_status.json"
    with campaign_lock(root):
        phases = [phase for phase in config["execution"]["stages"] if phase != "preflight"]
        prepared = {phase: prepare_phase(config, phase) for phase in phases}
        write_json(root/"campaign_resolved.json", config)
        count = sum(len(jobs) for _, jobs in prepared.values())
        print(f"{count} jobs; {config['execution']['max_workers']} concurrent workers; logs: {root}", flush=True)
        if plan_only:
            return 0
        write_json(record_path, record)
        try:
            if "preflight" in config["execution"]["stages"] and run_preflight(config, runner):
                raise RuntimeError(f"preflight failed; read {root/'preflight/preflight.log'}")
            from scripts.rl.campaign_diagnostics import run_diagnostics
            run_diagnostics(config, runner, record, record_path)
            for phase, (plans, jobs) in prepared.items():
                print(f"Starting {phase}: {len(jobs)} train/evaluate jobs", flush=True)
                initial = set(config.get("initial_scenarios", [])) if phase == "main" else set()
                first = [job for job in jobs if Path(job["root"]).name in initial] if initial else []
                remaining = [job for job in jobs if job not in first]
                failed = set()
                for group in ([first, remaining] if first else [jobs]):
                    if not group: continue
                    print(f"Running {len(group)} {phase} jobs", flush=True)
                    failed |= run_jobs(group, config["execution"]["max_workers"], runner, record, record_path)
                    if failed: break
                if failed:
                    raise RuntimeError(f"{phase} failed in {len(failed)} plan(s); inspect their local logs")
                for plan in plans:
                    if str(plan) in failed:
                        continue
                    command = [sys.executable, "-m", "scripts.rl.ops.run_task", "--output-root", str(plan), "--compare"]
                    if runner.execute(command, plan/"local/compare.log"):
                        failed.add(str(plan))
                write_reward_summary(plans, root)
                if failed:
                    raise RuntimeError(f"{phase} failed in {len(failed)} plan(s); inspect their local logs")
            record["status"] = "completed"
            return 0
        except KeyboardInterrupt:
            runner.stop()
            record["status"] = "interrupted"
            return 130
        except Exception as exc:
            runner.stop()
            record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            print(record["error"], file=sys.stderr, flush=True)
            return 1
        finally:
            record["ended_at"] = now_iso()
            write_json(record_path, record)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--plan-only", action="store_true", help="Validate and write plans without launching processes")
    args = parser.parse_args(argv)
    previous = signal.getsignal(signal.SIGTERM)

    def terminate(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    try:
        return run_campaign(load_config(args.config), args.plan_only)
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
