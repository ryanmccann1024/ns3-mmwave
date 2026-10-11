"""Own selective retrieval, local snapshot inspection, and fetch manifest I/O."""

import copy
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.rl.cli_common import now_iso, sha256_file, write_json
from scripts.rl.ops import tasks
from scripts.sim_support import find_mesh_root

FETCH_MANIFEST_VERSION = 2
FETCH_MANIFEST_NAME = "fetch_manifest.json"

ALWAYS_INCLUDE = ("experiment_plan.json", "cluster/tasks.json",
                  "cluster/receipts/*.json")

CATEGORY_INCLUDES = {
    "comparison": ("comparison/comparison.json", "comparison/episodes.csv"),
    "manifests": ("train/**/train_manifest.json", "eval/**/eval_manifest.json",
                  "train/**/episode-*/rl_episode.json",
                  "eval/**/episode-*/rl_episode.json",
                  "train/**/episode-*/policy_decisions_manifest.json",
                  "eval/**/episode-*/policy_decisions_manifest.json",
                  "eval/**/baseline/baseline_manifest.json",
                  "eval/**/baseline/effective-inputs/baseline-plan.json",
                  "cluster/records/**", "benchmark/**"),
    "models": ("train/**/maskable_ppo_mesh.zip", "train/**/best_model.zip",
               "train/**/checkpoints/*.zip"),
    "selection-logs": ("train/**/evaluations.npz",),
    "inputs": ("train/**/episode-*/inputs/**", "eval/**/episode-*/inputs/**",
               "eval/**/baseline/source-inputs/**", "eval/**/baseline/effective-inputs/**"),
    "telemetry": ("train/**/episode-*/steps.jsonl",
                  "eval/**/episode-*/steps.jsonl"),
    "decision-records": ("train/**/episode-*/policy_decisions.jsonl",
                         "eval/**/episode-*/policy_decisions.jsonl"),
    "episode-data": ("train/**/episode-*/**", "eval/**/episode-*/**"),
    "logs": ("cluster/logs/**", "eval/**/baseline/planner.log"),
}

_HOME_PARENTS = (Path("/Users"), Path("/home"))
_MANIFEST_NAMES = re.compile(r"fetch_manifest(\.\d+)?\.json")
_NO_RSYNC = "rsync was not found on PATH; install it or adjust PATH"


def parse_categories(select: str | None) -> list[str]:
    """Split the --select comma list, keeping order and refusing unknown names."""
    chosen: list[str] = []
    for token in (select or "").split(","):
        name = token.strip()
        if not name or name in chosen:
            continue
        if name not in CATEGORY_INCLUDES:
            raise ValueError(f"unknown --select category {name!r}; valid: "
                             f"{', '.join(sorted(CATEGORY_INCLUDES))}")
        chosen.append(name)
    return chosen


def build_argv(remote: str, dest: Path, categories: list[str]) -> list[str]:
    """rsync argv; --ignore-existing always present so nothing local is overwritten."""
    rules = list(ALWAYS_INCLUDE)
    for category in categories:
        rules.extend(rule for rule in CATEGORY_INCLUDES[category]
                     if rule not in rules)
    return ["rsync", "-a", "--prune-empty-dirs", "--ignore-existing",
            *(f"--include={rule}" for rule in rules),
            "--include=*/", "--exclude=*",
            f"{remote.rstrip('/')}/", f"{dest}/"]


def _local_source(remote: str) -> Path | None:
    """Resolve --remote as a local path, or None when it names a remote host."""
    if remote.startswith("rsync://"):
        return None
    head = remote.split("/", 1)[0]
    if ":" in head:
        return None
    return Path(remote).expanduser().resolve()


def _destination(dest: str) -> tuple[Path, list[Path]]:
    """The destination as written plus its symlink target, so neither is bypassed."""
    path = Path(dest).expanduser()
    literal = path.parent.resolve() / path.name if path.name else path.resolve()
    targets = [literal]
    if path.is_symlink():
        targets.append(path.resolve())
    return literal, targets


def _is_home(path: Path) -> bool:
    return (path == Path.home().resolve() or path == Path("/root")
            or path.parent in _HOME_PARENTS)


def _refusal(literal: Path, targets: list[Path], source: Path | None,
             update: bool) -> str | None:
    mesh_root = find_mesh_root()
    for target in targets:
        if target == Path(target.anchor):
            return f"refusing to fetch into the filesystem root {target}"
        if _is_home(target):
            return f"refusing to fetch into the home directory {target}"
        if target == mesh_root:
            return f"refusing to fetch into the mesh-sim checkout root {target}"
        if source is not None:
            if source == target or target in source.parents:
                return f"local source {source} is inside the destination {target}"
            if source in target.parents:
                return f"destination {target} is inside the local source {source}"
    if literal.exists() and not literal.is_dir():
        return f"{literal} exists and is not a directory"
    if literal.is_dir() and any(literal.iterdir()) and not update:
        return f"{literal} is not empty; pass --update to add only missing files"
    return None


def _rebase(plan: dict, remote_root: Path, dest: Path) -> dict:
    """Copy the plan in memory with each output_dir moved under the destination."""
    plan = copy.deepcopy(plan)
    for step in plan.get("steps") or []:
        relative = Path(step["output_dir"]).relative_to(remote_root)
        if ".." in relative.parts:
            raise ValueError("plan output directory escapes the run root")
        step["output_dir"] = str(dest / relative)
    return plan


def _fetched_plan(dest: Path) -> dict | None:
    """Read the fetched plan and rebase its absolute remote paths onto the dest."""
    try:
        plan = json.loads((dest / tasks.PLAN_NAME).read_text())
        if not isinstance(plan, dict):
            return None
        return _rebase(plan, tasks.plan_root(plan), dest)
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return None


def _manifest_status(step: dict) -> str | None:
    """Read a copied manifest's status without inferring remote scheduler state."""
    try:
        payload = json.loads((Path(step["output_dir"]) / step["manifest"]).read_text())
    except (OSError, ValueError):
        return None
    status = payload.get("status") if isinstance(payload, dict) else None
    return status if isinstance(status, str) else None


def _task_state(task: dict) -> str:
    """Classify copied files; blocked or unreadable is incomplete, not proof of failure."""
    training_status = _manifest_status(task["train"])
    evaluation_status = _manifest_status(task["evaluate"])
    if evaluation_status == "completed":
        return "completed"
    if evaluation_status == "partial":
        return "partial"
    if evaluation_status in ("failed", "interrupted"):
        return "failed"
    if evaluation_status == "running":
        return "running"
    if training_status in ("failed", "interrupted"):
        return "failed"
    if training_status == "running":
        return "running"
    if not any(Path(task[kind]["output_dir"]).exists() for kind in ("train", "evaluate")):
        return "missing"
    return "incomplete"


def _task_rows(plan: dict | None, manifests: bool) -> tuple[list[dict], bool | None]:
    """Task states from fetched files only; not_fetched unless manifests came along."""
    try:
        table = tasks.build_tasks(plan) if plan else []
    except (ValueError, TypeError, AttributeError, KeyError):
        return [], None
    if not manifests:
        return [{"index": task["index"], "id": task["id"], "state": "not_fetched"}
                for task in table], None
    try:
        rows = [{"index": task["index"], "id": task["id"],
                 "state": _task_state(task)} for task in table]
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return [], None
    if not rows:
        return rows, None
    return rows, any(row["state"] != "completed" for row in rows)


def _comparison_state(plan: dict | None, dest: Path, selected: bool) -> str:
    if not selected:
        return "not_fetched"
    if plan is None:
        plan = {"steps": [{"id": "compare", "kind": "compare",
                           "output_dir": str(dest / "comparison"),
                           "manifest": "comparison.json"}]}
    try:
        return tasks.comparison_outcome(plan)["state"]
    except ValueError:
        return "absent"
    except (TypeError, AttributeError, KeyError):
        return "unreadable"


def _files(dest: Path) -> list[dict]:
    entries = []
    for path in sorted(dest.rglob("*")):
        relative = path.relative_to(dest)
        if not path.is_file():
            continue
        if relative.parent == Path(".") and _MANIFEST_NAMES.fullmatch(relative.name):
            continue
        entries.append({"path": relative.as_posix(), "bytes": path.stat().st_size,
                        "sha256": sha256_file(path)})
    return entries


def _rotate_manifest(dest: Path) -> None:
    """Keep an earlier --update manifest as fetch_manifest.<n>.json."""
    current = dest / FETCH_MANIFEST_NAME
    if not current.is_file():
        return
    index = 1
    while (dest / f"fetch_manifest.{index}.json").exists():
        index += 1
    current.rename(dest / f"fetch_manifest.{index}.json")


def write_manifest(dest: Path, remote: str, categories: list[str],
                   argv: list[str], update: bool = False) -> dict:
    """Record selection and destination inventory; existing files may predate this transfer."""
    plan = _fetched_plan(dest)
    rows, incomplete = _task_rows(plan, "manifests" in categories)
    payload = {"fetch_manifest_version": FETCH_MANIFEST_VERSION, "remote": remote,
               "selection": list(categories), "argv": list(argv),
               "transfer_mode": "add_missing" if update else "new_destination",
               "files_may_be_stale": bool(update),
               "inventory_scope": "destination", "state_basis": "local_manifests",
               "fetched_at": now_iso(), "files": _files(dest), "tasks": rows,
               "comparison": _comparison_state(plan, dest,
                                               "comparison" in categories),
               "snapshot_of_incomplete_run": incomplete}
    _rotate_manifest(dest)
    write_json(dest / FETCH_MANIFEST_NAME, payload)
    return payload


def fetch(remote: str, dest: str, select: str | None = None, update: bool = False,
          dry_run: bool = False) -> int:
    """Validate paths, copy selected files, then inspect the resulting local tree."""
    try:
        categories = parse_categories(select)
        literal, targets = _destination(dest)
        source = _local_source(remote)
        refusal = _refusal(literal, targets, source, update)
        if refusal:
            raise ValueError(refusal)
        argv = build_argv(str(source) if source is not None else remote, literal, categories)
        if dry_run:
            print(shlex.join(argv))
            return 0
        if shutil.which(argv[0]) is None:
            raise ValueError(_NO_RSYNC)
        if update and literal.is_dir() and any(literal.iterdir()):
            print("Adding missing files only; existing manifests and traces are not refreshed. "
                  "Use a new --dest for a fresh snapshot.", file=sys.stderr)
        literal.parent.mkdir(parents=True, exist_ok=True)
        code = subprocess.run(argv).returncode
        if code != 0:
            print(f"rsync exited {code}; no fetch manifest was written", file=sys.stderr)
            return 1
        literal.mkdir(parents=True, exist_ok=True)
        payload = write_manifest(literal, remote, categories, argv, update)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"destination contains {len(payload['files'])} files: {literal}")
    return 0
