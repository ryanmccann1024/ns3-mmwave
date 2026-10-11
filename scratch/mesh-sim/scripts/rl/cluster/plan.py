"""Load the experiment task mapping and check cluster preflight requirements."""

import os
from pathlib import Path

from scripts.artifact_io import sha256_file
from scripts.rl.ops import tasks
from scripts.rl.cluster import receipts, slurm


def _plan_and_tasks(output_root):
    plan = tasks.load_plan(output_root)
    return plan, tasks.build_tasks(plan)


def _validate(plan: dict, table: list[dict], output_root, config: dict,
              need_sbatch: bool) -> None:
    root = Path(output_root).resolve()
    errors = []
    if tasks.plan_root(plan) != root:
        errors.append(f"the plan was written for {tasks.plan_root(plan)}, not {root}; "
                      "generate the plan on this filesystem instead of copying it")
    binary = Path(plan["sim_binary"])
    if not binary.is_absolute():
        errors.append(f"sim_binary {binary} is not an absolute path")
    elif not binary.is_file():
        errors.append(f"sim_binary {binary} does not exist")
    elif not os.access(binary, os.X_OK):
        errors.append(f"sim_binary {binary} is not executable")
    for row in plan.get("rows", []):
        if not Path(row["run_config"]).is_file():
            errors.append(f"row {row['name']}: run_config {row['run_config']} is missing")
    if len(table) > config["max_array_size"]:
        errors.append(f"{len(table)} tasks exceed max_array_size "
                      f"{config['max_array_size']}; chunking is not implemented")
    if need_sbatch and not slurm.available("sbatch"):
        errors.append("sbatch is not on PATH")
    if errors:
        raise ValueError("\n".join(errors))


def _write_task_table(output_root, table: list[dict]) -> str:
    plan_sha = sha256_file(Path(output_root).resolve() / tasks.PLAN_NAME)
    receipts.write_task_table(output_root, receipts.task_table(plan_sha, table))
    return plan_sha


def _parse_indices(raw: str | None) -> list[int] | None:
    if raw is None:
        return None
    try:
        indices = [int(token) for token in raw.split(",") if token.strip()]
    except ValueError as exc:
        raise ValueError(f"--tasks must be a comma-separated index list: {exc}") from exc
    if not indices:
        raise ValueError("--tasks must name at least one task index")
    return sorted(set(indices))
