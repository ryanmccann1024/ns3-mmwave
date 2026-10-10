"""Derive resource estimates only from complete task measurements."""

import json
import math
import sys
from pathlib import Path
from scripts.artifact_io import now_iso, sha256_file, write_json
from scripts.rl.env.config import read_scenario_identity
from scripts.rl.policy.experiment import load_matrix
from scripts.rl.ops.measurement import BENCHMARK_VERSION, effective_timesteps

ESTIMATE_VERSION = 2
_SELECTION_KEYS = ("observation_preset", "reward_components", "reward_weights")
_SELECTION_WARNING = ("observation or reward selection differs from the benchmarked "
                      "row; its Python and agent work was not measured")

def format_hms(seconds: float) -> str:
    """Whole seconds, rounded up, as HH:MM:SS."""
    total = int(math.ceil(max(seconds, 0.0)))
    return f"{total // 3600:02d}:{total // 60 % 60:02d}:{total % 60:02d}"


def _step_of(benchmark: dict, kind: str) -> dict:
    for step in benchmark.get("steps") or []:
        if step.get("kind") == kind:
            return step
    raise ValueError(f"benchmark has no {kind} step")


def _peak_tree_rss_kb(benchmark: dict):
    """The largest measured process-tree peak across the steps; None when none measured."""
    peaks = [step.get("peak_tree_rss_kb") for step in benchmark.get("steps") or []]
    measured = [peak for peak in peaks if peak is not None]
    return max(measured) if measured else None


def _selection_fields(source) -> dict | None:
    if not isinstance(source, dict):
        return None
    return {key: source.get(key) for key in _SELECTION_KEYS}


def _row_selection(row: dict) -> dict:
    return {"observation_preset": row["observation_preset"],
            "reward_components": list(row["reward_components"]),
            "reward_weights": [float(weight) for weight in row["reward_weights"]]}


def _same_scenario(identity, other) -> bool:
    """Compare the scenario file hashes only; run.ini paths differ between machines."""
    if not isinstance(identity, dict) or not isinstance(other, dict):
        return False
    keys = [key for key in other if key.endswith("_sha256")]
    return bool(keys) and all(identity.get(key) == other.get(key) for key in keys)


def _row_estimate(row: dict, train: dict, per_episode: float, matrix: dict) -> dict:
    """Per-task seconds for one target row, or a null with the reason it was skipped."""
    training = matrix["training"]
    entry = {"name": row["name"], "tasks": len(matrix["seeds"]["training"]),
             "per_task_seconds": None, "reason": None, "selection_differs": None,
             "warning": None}
    if not _same_scenario(read_scenario_identity(row["run_config"]),
                          train.get("scenario_identity")):
        entry["reason"] = "different scenario"
        return entry
    cadence = (training.get("n_steps"), training.get("eval_every_steps", 0), training.get("eval_episodes", 1))
    measured = (train.get("n_steps"), train.get("eval_every_steps"),
                train.get("eval_episodes"))
    if cadence != measured:
        entry["reason"] = "different cadence"
        return entry

    target = effective_timesteps(training.get("total_timesteps"),
                                 training.get("n_steps"))
    if target is None:
        entry["reason"] = "different cadence"
        return entry
    episodes = len(matrix["evaluation"]["policies"]) * len(matrix["seeds"]["held_out"])
    entry["per_task_seconds"] = train["seconds_per_timestep"] * target + \
        per_episode * episodes
    entry["selection_differs"] = _selection_fields(train.get("selection")) != \
        _row_selection(row)
    if entry["selection_differs"]:
        entry["warning"] = _SELECTION_WARNING
    return entry


def build_estimate(benchmark: dict, matrix: dict, safety_factor: float) -> dict:
    """Scale the measured seconds and memory onto every row of a target matrix."""
    if not math.isfinite(safety_factor) or safety_factor <= 0:
        raise ValueError("--safety-factor must be > 0")
    if benchmark.get("benchmark_version") != BENCHMARK_VERSION:
        raise ValueError("benchmark_version must be 2; remeasure the task")
    train = _step_of(benchmark, "train")
    evaluate = _step_of(benchmark, "evaluate")
    if any(step.get("tolerated") is not True or step.get("manifest_status") != "completed"
           for step in (train, evaluate)):
        raise ValueError("measure a task whose steps both completed successfully")
    if (not isinstance(evaluate.get("episodes_expected"), int)
            or isinstance(evaluate["episodes_expected"], bool)
            or evaluate["episodes_expected"] <= 0
            or evaluate.get("episodes_completed") != evaluate["episodes_expected"]):
        raise ValueError("benchmark evaluation is incomplete")
    per_timestep = train.get("seconds_per_timestep")
    per_episode = evaluate.get("seconds_per_episode")
    if any(not isinstance(value, (int, float)) or isinstance(value, bool)
           or not math.isfinite(value) or value <= 0
           for value in (per_timestep, per_episode)):
        raise ValueError("benchmark has no seconds_per_timestep or seconds_per_episode; "
                         "measure a task whose steps both completed")

    rows = [_row_estimate(row, train, per_episode, matrix) for row in matrix["rows"]]
    for row in rows:
        seconds = row["per_task_seconds"]
        row["per_task_with_safety_seconds"] = (None if seconds is None
                                               else seconds * safety_factor)
        row["per_task_with_safety_hms"] = (None if seconds is None
                                           else format_hms(seconds * safety_factor))
    estimated = [row for row in rows if row["per_task_seconds"] is not None]
    serial = sum(row["per_task_seconds"] * row["tasks"] for row in estimated)
    memory = _peak_tree_rss_kb(benchmark)
    host = benchmark.get("host") or {}

    return {
        "estimate_version": ESTIMATE_VERSION,
        "created_at": now_iso(),
        "benchmark": {"task_id": benchmark.get("task_id"),
                      "task_index": benchmark.get("task_index"),
                      "measured_at": benchmark.get("measured_at"),
                      "seconds_per_timestep": per_timestep,
                      "seconds_per_episode": per_episode},
        "target_matrix": {"path": matrix["path"], "sha256": matrix["sha256"],
                          "name": matrix["name"]},
        "safety_factor": safety_factor,
        "task_count": sum(row["tasks"] for row in rows),
        "estimated_task_count": sum(row["tasks"] for row in estimated),
        "rows": rows,
        "memory": {"peak_tree_rss_kb": memory,
                   "with_safety_kb": None if memory is None else memory * safety_factor},
        "totals": {"serial_seconds": serial,
                   "serial_with_safety_seconds": serial * safety_factor,
                   "serial_with_safety_hms": format_hms(serial * safety_factor)},
        "assumptions": {"linear_in_timesteps": True,
                        "measured_on": f"{host.get('system')} {host.get('machine')}",
                        "is_cluster_estimate": False},
    }


def run_estimate(benchmark_path, matrix_path, safety_factor: float, output) -> int:
    """Write an arithmetic estimate for a target matrix; runs nothing."""
    try:
        benchmark = json.loads(Path(benchmark_path).read_text())
        matrix = load_matrix(matrix_path)
        estimate = build_estimate(benchmark, matrix, safety_factor)
    except (ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    estimate["benchmark"]["path"] = str(Path(benchmark_path).resolve())
    estimate["benchmark"]["sha256"] = sha256_file(benchmark_path)
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(out_path, estimate)

    for row in estimate["rows"]:
        if row["per_task_seconds"] is None:
            print(f"{row['name']}  no estimate  {row['reason']}")
            continue
        print(f"{row['name']}  {row['tasks']} tasks  "
              f"{row['per_task_with_safety_hms']} per task with safety factor")
        if row["warning"]:
            print(f"{row['name']}  warning: {row['warning']}")
    print(f"serial total {estimate['totals']['serial_with_safety_hms']}; "
          f"not a cluster estimate")
    print(f"wrote {out_path}")
    return 0


