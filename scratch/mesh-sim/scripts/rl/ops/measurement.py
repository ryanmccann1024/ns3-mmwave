"""Measure task timing, process-tree memory and completion evidence."""

import json
import math
import os
import platform
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from scripts.artifact_io import now_iso, write_json
from scripts.rl.cli_common import package_versions
from scripts.rl.ops import tasks
from scripts.rl.ops.process import managed_step, launch_step

BENCHMARK_VERSION = 2
BENCHMARK_DIR = "benchmark"
DEFAULT_INTERVAL_S = 0.5
EPISODE_MANIFEST = "rl_episode.json"
SAMPLING_METHOD = "ps-process-tree"
SAMPLING_NOTE = "sampled; spikes shorter than the interval can be missed"

PS_ARGV = ("ps", "-A", "-o", "pid=,ppid=,rss=")




class PsError(RuntimeError):
    """`ps` is missing or returned an error, so memory cannot be measured."""


def read_ps() -> str:
    """Return one `ps -A -o pid=,ppid=,rss=` snapshot as text."""
    try:
        result = subprocess.run(list(PS_ARGV), capture_output=True, text=True)
    except OSError as exc:
        raise PsError(f"could not run {PS_ARGV[0]}: {exc}") from exc
    if result.returncode != 0:
        raise PsError(f"ps exited {result.returncode}: {result.stderr.strip()[:200]}")
    return result.stdout


def parse_ps(text: str) -> dict[int, tuple[int, int]]:
    """Map pid -> (ppid, rss_kb) from a `ps -A -o pid=,ppid=,rss=` snapshot."""
    table: dict[int, tuple[int, int]] = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        try:
            pid, ppid, rss = (int(field) for field in fields[:3])
        except ValueError:
            continue
        table[pid] = (ppid, rss)
    return table


def _in_tree(table: dict[int, tuple[int, int]], pid: int, root_pid: int) -> bool:
    seen: set[int] = set()
    while pid not in seen:
        if pid == root_pid:
            return True
        if pid not in table:
            return False
        seen.add(pid)
        pid = table[pid][0]
    return False


def tree_usage(table: dict[int, tuple[int, int]], root_pid: int) -> dict:
    """Summed RSS, process count, and largest single RSS over root_pid's tree."""
    members = [table[pid][1] for pid in table if _in_tree(table, pid, root_pid)]
    return {"rss_kb": sum(members), "count": len(members),
            "max_rss_kb": max(members, default=0)}


class TreeSampler:
    """Background peak sampler over one process tree; a ps failure is recorded, not raised."""

    def __init__(self, pid: int, interval_s: float, read=None):
        self._pid = pid
        self._interval = max(float(interval_s), 0.0)
        self._read = read or read_ps
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self.samples = 0
        self.peak_rss_kb = 0
        self.peak_count = 0
        self.peak_single_rss_kb = 0
        self.error: str | None = None

    def sample(self) -> None:
        """Take one snapshot and fold it into the peaks."""
        try:
            usage = tree_usage(parse_ps(self._read()), self._pid)
        except PsError as exc:
            if self.error is None:
                self.error = str(exc)
            return
        self.samples += 1
        self.peak_rss_kb = max(self.peak_rss_kb, usage["rss_kb"])
        self.peak_count = max(self.peak_count, usage["count"])
        self.peak_single_rss_kb = max(self.peak_single_rss_kb, usage["max_rss_kb"])

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self.sample()

    def start(self) -> None:
        self.sample()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.ident is not None:
            self._thread.join(timeout=self._interval + 5.0)

    def result(self) -> dict:
        """Memory fields for the step record; all null when sampling failed."""
        if self.samples == 0:
            return {"peak_tree_rss_kb": None, "peak_process_count": None,
                    "peak_single_process_rss_kb": None, "samples": 0,
                    "measurement_error": self.error or "no ps sample was taken"}
        record = {"peak_tree_rss_kb": self.peak_rss_kb,
                  "peak_process_count": self.peak_count,
                  "peak_single_process_rss_kb": self.peak_single_rss_kb,
                  "samples": self.samples}
        if self.error is not None:
            record["measurement_error"] = self.error
        return record


def measure_step(step: dict, interval_s: float = DEFAULT_INTERVAL_S,
                 launch=None, read=None) -> dict:
    """Run one step to completion while sampling its process tree."""
    launch = launch or launch_step
    started = time.monotonic()
    with managed_step(step, launch=launch) as process:
        sampler = TreeSampler(process.pid, interval_s, read)
        try:
            sampler.start()
            code = process.wait()
        finally:
            sampler.stop()
    wall_seconds = time.monotonic() - started
    return {"id": step["id"], "kind": step["kind"], "exit_code": code,
            "tolerated": tasks.tolerated(step["kind"], code),
            "wall_seconds": round(wall_seconds, 3), **sampler.result()}


def effective_timesteps(requested, n_steps) -> int | None:
    """Rollouts run whole, so the budget rounds up to a multiple of n_steps."""
    if not isinstance(requested, int) or not isinstance(n_steps, int):
        return None
    if requested <= 0 or n_steps <= 0:
        return None
    return math.ceil(requested / n_steps) * n_steps


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _span_seconds(start, end) -> float | None:
    try:
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    except (TypeError, ValueError):
        return None


def _episode_times(directory) -> tuple[int, float]:
    """Episode count and summed episode wall seconds under one run directory."""
    count, seconds = 0, 0.0
    for path in sorted(Path(directory).glob(f"episode-*/{EPISODE_MANIFEST}")):
        manifest = _read_json(path)
        if manifest is None:
            continue
        count += 1
        span = _span_seconds(manifest.get("started_at"), manifest.get("ended_at"))
        if span is not None:
            seconds += span
    return count, seconds


def _train_details(step: dict, wall_seconds: float) -> dict:
    manifest = _read_json(Path(step["output_dir"]) / step["manifest"]) or {}
    hyper = manifest.get("hyperparameters") or {}
    effective = effective_timesteps(hyper.get("total_timesteps"), hyper.get("n_steps"))
    run_dir = Path(step["output_dir"])
    training_episodes, training_seconds = _episode_times(run_dir)
    selection_episodes, selection_seconds = _episode_times(run_dir / "eval")
    episode_sum = training_seconds + selection_seconds
    return {
        "requested_timesteps": hyper.get("total_timesteps"),
        "n_steps": hyper.get("n_steps"),
        "effective_timesteps": effective,
        # Covers the model-selection evaluations and the PPO updates as well.
        "seconds_per_timestep": (wall_seconds / effective) if effective else None,
        "scenario_identity": manifest.get("scenario_identity"),
        "selection": manifest.get("selection"),
        "eval_every_steps": hyper.get("eval_every_steps"),
        "eval_episodes": hyper.get("eval_episodes"),
        "manifest_status": manifest.get("status"),
        "training_episodes": training_episodes,
        "selection_episodes": selection_episodes,
        "episode_seconds_sum": round(episode_sum, 3),
        # Python start-up, PPO updates, and gaps between simulator launches together;
        # this is not a launch-overhead figure.
        "non_episode_seconds": round(wall_seconds - episode_sum, 3),
    }


def _evaluate_details(step: dict, wall_seconds: float) -> dict:
    manifest = _read_json(Path(step["output_dir"]) / step["manifest"]) or {}
    completed = manifest.get("episodes_completed")
    usable = isinstance(completed, int) and not isinstance(completed, bool) and completed > 0
    return {"manifest_status": manifest.get("status"), "episodes_expected": manifest.get("episodes_expected"),
            "episodes_completed": completed,
            "seconds_per_episode": (wall_seconds / completed) if usable else None}


def _details(step: dict, wall_seconds: float) -> dict:
    if step["kind"] == "train":
        return _train_details(step, wall_seconds)
    return _evaluate_details(step, wall_seconds)


def _benchmark_payload(plan: dict, task: dict, task_index: int, interval_s: float,
                       steps: list[dict]) -> dict:
    matrix = plan.get("matrix") or {}
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "measured_at": now_iso(),
        "host": {"system": platform.system(), "machine": platform.machine(),
                 "cpu_count": os.cpu_count(),
                 "python_version": platform.python_version()},
        "plan": {"root": str(tasks.plan_root(plan)),
                 "matrix_name": matrix.get("name"),
                 "matrix_sha256": matrix.get("sha256")},
        "task_index": task_index,
        "task_id": task["id"],
        "sampling": {"method": SAMPLING_METHOD, "interval_s": interval_s,
                     "note": SAMPLING_NOTE},
        "package_versions": package_versions(),
        "steps": steps,
    }


def run_benchmark(output_root, task_index: int, interval_s: float = DEFAULT_INTERVAL_S,
                  launch=None, read=None) -> int:
    """Measure one task's train then evaluate step; returns the process exit code."""
    try:
        plan = tasks.load_plan(output_root)
        table = tasks.build_tasks(plan)
        root = tasks.plan_root(plan)
    except (ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if not 0 <= task_index < len(table):
        print(f"--task-index {task_index} is outside 0..{len(table) - 1}",
              file=sys.stderr)
        return 1
    if not math.isfinite(interval_s) or interval_s <= 0:
        print("--sample-interval-s must be > 0", file=sys.stderr)
        return 1

    task = table[task_index]
    out_path = root / BENCHMARK_DIR / f"task-{task_index:04d}.json"
    if out_path.exists():
        print(f"{out_path} already exists; move it aside to measure again",
              file=sys.stderr)
        return 1

    states = tasks.task_fs_state(task)
    dirty = [f"{task[kind]['id']}  {states[kind][0]}  {states[kind][1]}".rstrip()
             for kind in ("train", "evaluate") if states[kind][0] != "pending"]
    if dirty:
        print("benchmark needs both step directories pending:", file=sys.stderr)
        for line in dirty:
            print(line, file=sys.stderr)
        return 1

    steps, exit_code = [], 0
    for kind in ("train", "evaluate"):
        step = task[kind]
        record = measure_step(step, interval_s, launch, read)
        record.update(_details(step, record["wall_seconds"]))
        steps.append(record)
        print(f"{step['id']}  exit {record['exit_code']}  "
              f"{record['wall_seconds']}s  "
              f"{'tolerated' if record['tolerated'] else 'not tolerated'}")
        if record.get("measurement_error"):
            print(f"{step['id']}  memory not measured: {record['measurement_error']}",
                  file=sys.stderr)
        if not record["tolerated"]:
            exit_code = 1
            break

    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(out_path, _benchmark_payload(plan, task, task_index, interval_s, steps))
    print(f"wrote {out_path}")
    return exit_code


