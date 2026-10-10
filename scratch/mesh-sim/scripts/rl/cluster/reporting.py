"""Render task states and scheduler submission previews."""

from pathlib import Path

from scripts.rl.cluster import receipts, jobs
from scripts.sim_support import find_mesh_root

PROVISIONAL = "NNNN"


def _print_rows(rows: list[dict], compare: dict | None = None) -> None:
    for row in rows:
        line = f"{row['index']:>4}  {row['id']:<40}  {row['state']}"
        print(f"{line}  {row['detail']}".rstrip())
        if row["state"] == "pending" and row["start"]:
            print(f"        scheduler-estimated start: {row['start']} (may change)")
    if compare is not None:
        print(f"{'':>4}  {'compare':<40}  {compare['state']}  "
              f"{compare['detail']}".rstrip())


def _preview(config: dict, output_root, indices: list[int], with_compare: bool) -> None:
    paths = receipts.paths(output_root, PROVISIONAL)
    if indices:
        spec = jobs.array_spec(indices, config["max_concurrent_tasks"])
        argv = jobs.sbatch_argv(config, "tasks", "meshops-<random>-tasks",
                                 paths["logs"] / "slurm-%A_%a.out",
                                 paths["script_tasks"], array=spec)
        print(f"provisional receipt {PROVISIONAL} and job names; the real values are "
              "generated when a receipt is allocated. Nothing was submitted")
        print(" ".join(argv))
        print(jobs.render_task_script(config, find_mesh_root(), Path(output_root).resolve(),
                                       paths["records"]))
    if with_compare:
        compare_argv = jobs.sbatch_argv(
            config, "compare", "meshops-<random>-compare",
            paths["logs"] / "compare-%j.out", paths["script_compare"],
            dependency="afterany:<every active array job id>")
        print(" ".join(compare_argv))
        print(jobs.render_compare_script(config, find_mesh_root(),
                                          Path(output_root).resolve(), paths["records"]))
