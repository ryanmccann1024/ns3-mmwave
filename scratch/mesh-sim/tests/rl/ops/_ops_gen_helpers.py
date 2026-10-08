"""Shared builders for the generated ops tests: plans, receipts, snapshots, fake cluster.

Everything is written under pytest's tmp_path. The scheduler is always
``scripts/rl/tests/fake_slurm.py``; no real SLURM or rsync is ever invoked.
"""

import json
import os
from pathlib import Path
from types import SimpleNamespace

from scripts.rl import experiment
from scripts.rl.cli_common import write_json
from scripts.rl.ops import cluster, receipts, reconcile, slurm, tasks
from scripts.rl.tests import fake_slurm


def leaf(index: int) -> str:
    """Task id of task `index` in a generated plan."""
    return f"row-{index:02d}/train-seed-1"


def make_plan(root: Path, n_tasks: int = 3, binary: Path | None = None,
              run_config: Path | None = None) -> dict:
    """Plan with the shape build_plan produces: n train/evaluate pairs plus compare."""
    steps = []
    for index in range(n_tasks):
        name = leaf(index)
        steps.append({"id": f"train/{name}", "kind": "train", "module": "stub.train",
                      "args": [], "output_dir": str(root / "train" / name),
                      "manifest": "train_manifest.json", "needs": []})
        steps.append({"id": f"evaluate/{name}", "kind": "evaluate",
                      "module": "stub.evaluate", "args": [],
                      "output_dir": str(root / "eval" / name),
                      "manifest": "eval_manifest.json", "needs": [f"train/{name}"]})
    steps.append({"id": "compare", "kind": "compare", "module": "stub.compare",
                  "args": ["--plan", str(root / experiment.PLAN_NAME),
                           "--output-dir", str(root / "comparison")],
                  "output_dir": str(root / "comparison"),
                  "manifest": "comparison.json", "needs": []})
    plan = {"experiment_plan_version": 1, "steps": steps}
    if binary is not None:
        plan["sim_binary"] = str(binary)
    if run_config is not None:
        plan["rows"] = [{"name": f"row-{index:02d}", "run_config": str(run_config)}
                        for index in range(n_tasks)]
    return plan


def written_plan(tmp_path: Path, n_tasks: int = 3) -> Path:
    """Write a plan under tmp_path/root and return the root."""
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / experiment.PLAN_NAME, make_plan(root, n_tasks))
    return root


def table(root: Path) -> list[dict]:
    return tasks.build_tasks(experiment.load_plan(root))


def write_manifest(root: Path, step_id: str, payload) -> Path:
    """Create a step dir; payload None leaves it without a manifest (blocked)."""
    plan = experiment.load_plan(root)
    step = next(item for item in plan["steps"] if item["id"] == step_id)
    out_dir = Path(step["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    if payload is not None:
        (out_dir / step["manifest"]).write_text(json.dumps(payload))
    return out_dir


def complete(root: Path, index: int, evaluate: str = "completed") -> None:
    write_manifest(root, f"train/{leaf(index)}", {"status": "completed"})
    write_manifest(root, f"evaluate/{leaf(index)}", {"status": evaluate})


def snap(queue=None, accounting=None, queue_ok=True, accounting_ok=True) -> dict:
    """Scheduler snapshot in the shape slurm.snapshot returns."""
    return {"queue": {"ok": queue_ok, "jobs": dict(queue or {}),
                      "error": "" if queue_ok else "squeue is unavailable"},
            "accounting": {"ok": accounting_ok, "jobs": dict(accounting or {}),
                           "error": "" if accounting_ok else "accounting is disabled"}}


def q(state: str, reason: str = "None", start: str = "N/A") -> dict:
    """One queue row."""
    return {"state": state, "reason": reason, "start": start}


def a(state: str, exit_code: str = "0:0") -> dict:
    """One accounting row."""
    return {"state": state, "exit": exit_code}


def receipt(submission: str = "0001", job_id: str | None = "1000", indices=(0,),
            **extra) -> dict:
    body = {"receipt_version": 1, "submission": submission, "state": "submitted",
            "job_name": f"meshops-{submission}-tasks", "indices": list(indices),
            "job_id": job_id, "compare": None, "cancel_requests": [],
            "human_assertions": []}
    body.update(extra)
    return body


def intent(submission: str = "0001", indices=(0,), state: str = "submitting",
           **extra) -> dict:
    return receipt(submission, None, indices, state=state, **extra)


def compare_element(job_id: str | None = "2000", state: str = "submitted",
                    name: str = "meshops-c-compare") -> dict:
    return {"job_name": name, "job_id": job_id, "state": state,
            "created_at": "2026-01-01T00:00:00+00:00", "script": "/s.sh",
            "argv": [], "depends_on": []}


def config_body(venv: Path, **top) -> dict:
    body = {"cluster_config_version": 1, "name": "gen-site", "venv": str(venv),
            "setup_lines": [],
            "task": {"partition": None, "account": None, "qos": None,
                     "constraint": None, "time": "01:00:00", "mem": "2G",
                     "cpus_per_task": 2},
            "compare": {"time": "00:10:00", "mem": "1G", "cpus_per_task": 1},
            "max_array_size": 1000, "max_concurrent_tasks": None}
    body.update(top)
    return body


def make_venv(tmp_path: Path) -> Path:
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True, exist_ok=True)
    (venv / "bin" / "python").write_text("#!/bin/sh\nexit 0\n")
    (venv / "bin" / "python").chmod(0o755)
    return venv


def cluster_env(tmp_path: Path, monkeypatch, n_tasks: int = 4,
                **config_top) -> SimpleNamespace:
    """Plan, cluster config, and the fake scheduler first on PATH."""
    fake = fake_slurm.install(tmp_path)
    monkeypatch.setenv("PATH", f"{fake.bin}{os.pathsep}{os.environ['PATH']}")
    root = tmp_path / "run"
    root.mkdir()
    binary = tmp_path / "mesh-sim"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    run_config = tmp_path / "run.ini"
    run_config.write_text("[scenario]\nname = fake\n")
    write_json(root / experiment.PLAN_NAME,
               make_plan(root, n_tasks, binary, run_config))
    config = tmp_path / "cluster.json"
    write_json(config, config_body(make_venv(tmp_path), **config_top))
    return SimpleNamespace(fake=fake, root=root, config=config, binary=binary,
                           tmp=tmp_path, n=n_tasks)


def run_cluster(env: SimpleNamespace, command: str, *extra: str) -> int:
    argv = [command, "--output-root", str(env.root)]
    if command in ("plan", "submit", "resume"):
        argv += ["--cluster-config", str(env.config)]
    return cluster.main([*argv, *extra])


def read_receipt(env: SimpleNamespace, submission: str) -> dict:
    return json.loads((env.root / "cluster" / "receipts" / f"{submission}.json")
                      .read_text())


def live_states(env: SimpleNamespace) -> dict[int, str]:
    """Reconciled states against the fake scheduler, as `status` computes them."""
    entries = receipts.load(env.root)
    snapshot = slurm.snapshot(receipts.job_ids(entries), receipts.user())
    return {row["index"]: row["state"]
            for row in reconcile.task_rows(table(env.root), entries, snapshot)}


def array_of(argv: list[str]) -> str | None:
    return next((token.split("=", 1)[1] for token in argv
                 if token.startswith("--array=")), None)


def flag(argv: list[str], name: str) -> str | None:
    return next((token.split("=", 1)[1] for token in argv
                 if token.startswith(f"--{name}=")), None)


def tree(path: Path) -> dict:
    return {str(item.relative_to(path)): item.read_bytes() if item.is_file() else None
            for item in sorted(path.rglob("*"))}
