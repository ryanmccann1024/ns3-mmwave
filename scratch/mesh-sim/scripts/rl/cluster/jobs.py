"""Build scheduler arguments and render experiment job scripts."""

import secrets
import shlex
from pathlib import Path
from scripts.rl.cluster.config import JOB_ROLES, PLACEMENT_KEYS, resources

JOB_NAME_PREFIX = "meshops"


def job_name(role: str) -> str:
    """Random per-submission job name so an interrupted sbatch can be searched."""
    if role not in JOB_ROLES:
        raise ValueError(f"unknown job role {role!r}; valid: {list(JOB_ROLES)}")
    return f"{JOB_NAME_PREFIX}-{secrets.token_hex(16)}-{role}"


def array_spec(indices, max_concurrent: int | None = None) -> str:
    """Compress sorted task indices into an sbatch array spec, with %N when capped."""
    ordered = sorted(set(indices))
    if not ordered:
        raise ValueError("array spec needs at least one task index")
    parts, start, previous = [], ordered[0], ordered[0]
    for index in ordered[1:]:
        if index == previous + 1:
            previous = index
            continue
        parts.append(f"{start}-{previous}" if previous > start else str(start))
        start = previous = index
    parts.append(f"{start}-{previous}" if previous > start else str(start))
    spec = ",".join(parts)
    return f"{spec}%{max_concurrent}" if max_concurrent else spec


def sbatch_argv(config: dict, role: str, name: str, log_pattern, script,
                array: str | None = None, dependency: str | None = None) -> list[str]:
    """Build the sbatch command; flags whose config value is null are omitted."""
    values = resources(config, role)
    argv = ["sbatch", "--parsable", "--no-requeue", f"--job-name={name}"]
    if array is not None:
        argv.append(f"--array={array}")
    argv.append(f"--output={log_pattern}")
    if dependency is not None:
        argv.append(f"--dependency={dependency}")
    for flag in PLACEMENT_KEYS:
        if values[flag] is not None:
            argv.append(f"--{flag}={values[flag]}")
    argv += [f"--time={values['time']}", f"--mem={values['mem']}",
             f"--cpus-per-task={values['cpus_per_task']}", str(script)]
    return argv


def _preamble(config: dict, role: str, mesh_root) -> list[str]:
    cpus = resources(config, role)["cpus_per_task"]
    python = shlex.quote(str(Path(config["venv"]) / "bin" / "python"))
    venv = shlex.quote(config["venv"])
    return ["#!/bin/bash", "set -euo pipefail", *config["setup_lines"],
            f"export OMP_NUM_THREADS={cpus} MKL_NUM_THREADS={cpus} "
            "CUDA_VISIBLE_DEVICES=",
            f"cd {shlex.quote(str(mesh_root))}",
            f"{python} scripts/rl/bootstrap_venv.py --venv {venv} --check"]


def render_task_script(config: dict, mesh_root, output_root, records_dir) -> str:
    """Job script for one array element: bootstrap check, then run_task."""
    python = shlex.quote(str(Path(config["venv"]) / "bin" / "python"))
    lines = _preamble(config, "tasks", mesh_root)
    lines.append(f"RECORD_DIR={shlex.quote(str(records_dir))}")
    lines.append(
        f"exec {python} -m scripts.rl.ops.run_task "
        f"--output-root {shlex.quote(str(output_root))} "
        '--task-index "$SLURM_ARRAY_TASK_ID" '
        '--record "$RECORD_DIR/task-$(printf \'%04d\' "$SLURM_ARRAY_TASK_ID").json"')
    return "\n".join(lines) + "\n"


def render_compare_script(config: dict, mesh_root, output_root, records_dir) -> str:
    """Job script for the compare step; strict prerequisites, no --allow-incomplete."""
    python = shlex.quote(str(Path(config["venv"]) / "bin" / "python"))
    record = shlex.quote(str(Path(records_dir) / "compare.json"))
    lines = _preamble(config, "compare", mesh_root)
    lines.append(f"exec {python} -m scripts.rl.ops.cluster compare "
                 f"--output-root {shlex.quote(str(output_root))} "
                 f'--record {record} --scheduled-job "$SLURM_JOB_ID"')
    return "\n".join(lines) + "\n"
