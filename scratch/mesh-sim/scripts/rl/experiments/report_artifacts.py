"""Read accepted batch attempts and resolve their artifact references."""

import csv
import json
import os
import shutil
from pathlib import Path, PurePosixPath

from scripts.artifact_io import canonical_sha256, sha256_file, write_json
from scripts.rl.experiments.config import FROZEN_MODES
from scripts.rl.experiments.plan import EVAL_MANIFEST, ONLINE_MANIFEST


def _load(path: Path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write(path: Path, payload) -> str:
    """Create the owning parent, write atomically and return the file hash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload)
    return sha256_file(path)


def _copy(source: Path, target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    shutil.copyfile(source, temporary)
    os.replace(temporary, target)
    return sha256_file(target)


def _dig(mapping, dotted: str):
    for part in dotted.split("."):
        if not isinstance(mapping, dict):
            return None
        mapping = mapping.get(part)
    return mapping


def check_relative(text) -> str:
    """A batch-root-relative POSIX path: not absolute, no '..', no URL."""
    if not isinstance(text, str) or not text or "://" in text or "\\" in text:
        raise ValueError(f"not a batch-relative path: {text!r}")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"path escapes the batch root: {text!r}")
    return text


class _Batch:
    """One plan, root and accepted-attempt map; every read is checked against the plan."""

    def __init__(self, plan: dict, root, accepted: dict, skipped=()):
        self.plan = plan
        self.root = Path(root).resolve()
        self.by_id = {task["id"]: task for task in plan["tasks"]}
        self.rows = {row["name"]: row for row in plan["rows"]}
        self.ops = {op["id"]: op for op in plan["operations"]}
        self.skipped = set(skipped)
        self.accepted = {}
        for task_id, raw in (accepted or {}).items():
            if task_id not in self.by_id:
                raise ValueError(f"accepted task {task_id} is not in the plan")
            if isinstance(raw, dict):
                # Scheduler form: {state, attempt_dir, ...} for every task of the batch.
                if raw.get("state") == "skipped_selection":
                    self.skipped.add(task_id)
                if raw.get("state") != "completed" or not raw.get("attempt_dir"):
                    continue
                raw = raw["attempt_dir"]
            path = Path(raw)
            path = (path if path.is_absolute() else self.root / path).resolve()
            task_dir = self.task_dir(self.by_id[task_id])
            if path != task_dir and task_dir not in path.parents:
                raise ValueError(
                    f"accepted directory for {task_id} is not inside that task's destination"
                )
            self.accepted[task_id] = path
        self._bindings = {}
        # Set by the index: where config/mapping files referenced by leaves are copied.
        self.assets_dir = None
        self.config_assets = {}
        self.asset_outputs, self.asset_issues = {}, []

    def task_dir(self, task: dict) -> Path:
        output_root = self.plan.get("output_root")
        if output_root is None:
            raise ValueError("a validate-only plan has no output root to report on")
        relative = Path(task["output_dir"]).relative_to(output_root)
        return self.root / relative

    def rel(self, path) -> str | None:
        """Root-relative POSIX path, or None for anything outside the root."""
        try:
            relative = Path(path).resolve().relative_to(self.root).as_posix()
        except ValueError:
            return None
        return check_relative(relative) if relative != "." else None

    def dir_of(self, task_id: str) -> Path | None:
        path = self.accepted.get(task_id)
        return path if path is not None and path.is_dir() else None

    def tasks(self, scenario: str, *kinds) -> list[dict]:
        return [
            t
            for t in self.plan["tasks"]
            if t["scenario"] == scenario and t["kind"] in kinds
        ]

    def _hashed_asset(self, path, sha256, folder: str) -> dict:
        if self.assets_dir is None or sha256 is None:
            return {"path": self.rel(path), "sha256": sha256}
        return _asset(
            self,
            {"path": str(path), "sha256": sha256},
            self.assets_dir / folder,
            self.asset_issues,
            self.asset_outputs,
        )

    def config_ref(self, task: dict) -> dict | None:
        """The INI a leaf used: copied into the root (when indexing), hashed, with its source."""
        config = task.get("config")
        if config is None:
            return None
        asset = self.config_assets.get(config["path"])
        if asset is None:
            asset = self._hashed_asset(
                config["path"], config["sha256"], config["sha256"][:12]
            )
        return {
            "path": asset["path"],
            "sha256": config["sha256"],
            "config_source": config.get("config_source"),
        }

    def planning_ref(self, task: dict) -> dict | None:
        """Placement baseline planning identity; the mapping file becomes a hashed asset."""
        planning = task.get("planning")
        if planning is None:
            return None
        mapping = None
        if planning.get("mapping_file"):
            source = Path(planning["mapping_file"]).resolve()
            sha = (self.plan.get("inputs") or {}).get(str(source), {}).get("sha256")
            mapping = self._hashed_asset(source, sha, f"mapping-{(sha or '')[:12]}")
        return {
            "planning_seed": planning.get("planning_seed"),
            "planning_seed_source": planning.get("planning_seed_source"),
            "planner_settings_sha256": planning.get("planner_settings_sha256"),
            "mapping_file": mapping,
        }

    def task_dims(self, task: dict) -> tuple:
        ident = task["identity"]
        return (
            ident["row"],
            ident["training_seed"],
            ident["model_source"],
            ident["checkpoint"],
        )

    def binding(self, task: dict) -> dict:
        """Model identity of an operate task from its write-once binding (or imported source)."""
        spec = task.get("binding")
        if spec is None:
            return {"status": "none", "binding": None, "model_sha256": None}
        if spec.get("producer") is None:
            return {
                "status": "source",
                "binding": None,
                "source_digest": spec["source_digest"],
                "model_selection": str(spec["model"]),
                "model_sha256": spec["model_sha256"],
                "model_path": None,
            }
        path = check_relative(spec["path"])
        if path in self._bindings:
            return self._bindings[path]
        data = _load(self.root / path)
        if (
            data is not None
            and "model_binding_version" not in data
            and isinstance(data.get("binding"), dict)
        ):
            data = data["binding"]
        if data is None or "model_sha256" not in data:
            identity = {
                "status": "missing",
                "binding": path,
                "model_sha256": None,
                "checkpoint": spec["checkpoint"],
            }
        else:
            identity = {
                "status": "bound",
                "binding": path,
                "checkpoint": spec["checkpoint"],
                "model_selection": data.get("model_selection"),
                "run_dir": self.rel(data["run_dir"]) if data.get("run_dir") else None,
                "model_path": self.rel(data["model_path"])
                if data.get("model_path")
                else None,
                "model_sha256": data.get("model_sha256"),
                "optimizer_sha256": data.get("optimizer_sha256"),
                "num_timesteps": data.get("num_timesteps"),
                "n_updates": data.get("n_updates"),
                "train_manifest_sha256": data.get("train_manifest_sha256"),
            }
        self._bindings[path] = identity
        return identity


def _new_attempt(batch: _Batch, task: dict, attempt_dir) -> Path:
    task_dir = batch.task_dir(task)
    if attempt_dir is not None:
        path = Path(attempt_dir)
        path = (path if path.is_absolute() else batch.root / path).resolve()
        if path.parent != task_dir or not path.name.startswith("attempt-"):
            raise ValueError(f"{path} is not an attempt directory of {task['id']}")
        if path.exists() and any(path.iterdir()):
            raise ValueError(f"attempt directory {path} is not empty")
        path.mkdir(parents=True, exist_ok=True)
        return path
    task_dir.mkdir(parents=True, exist_ok=True)
    while True:
        numbers = [
            int(p.name[8:]) for p in task_dir.glob("attempt-*") if p.name[8:].isdigit()
        ]
        path = task_dir / f"attempt-{max(numbers, default=0) + 1}"
        try:
            path.mkdir()
            return path
        except FileExistsError:
            continue


def _episode_dir(raw, leaf: Path) -> Path | None:
    if not raw:
        return None
    path = Path(raw)
    return (path if path.is_absolute() else leaf / path).resolve()


def _leaf(batch: _Batch, task: dict, policy: str) -> dict:
    """Evidence from one accepted operate/baseline attempt for its single seed."""
    seed = task["identity"]["seed"]
    directory = batch.dir_of(task["id"])
    leaf = {
        "attempt": None,
        "eval_manifest": None,
        "eval_manifest_sha256": None,
        "online_manifest": None,
        "online_manifest_sha256": None,
        "weight_audit": None,
        "manifest_status": None,
        "episodes": [],
        "issues": [],
        "_eval": None,
        "_online": None,
        "_dir": directory,
    }
    if directory is None:
        leaf["status"] = (
            "skipped_selection" if task["id"] in batch.skipped else "missing"
        )
        return leaf
    leaf["attempt"] = batch.rel(directory)
    for name, key in ((EVAL_MANIFEST, "eval"), (ONLINE_MANIFEST, "online")):
        path = directory / name
        if path.is_file():
            data = _load(path)
            if data is None:
                leaf["issues"].append(f"{name} is not readable JSON")
                continue
            leaf[f"_{key}"] = data
            leaf[f"{key}_manifest"] = batch.rel(path)
            leaf[f"{key}_manifest_sha256"] = sha256_file(path)
    for name in task["expected_outputs"]:
        if not (directory / name).is_file():
            leaf["issues"].append(f"expected {name} is missing")
    primary = (
        leaf["_eval"]
        if task["expected_outputs"][0] == EVAL_MANIFEST
        else leaf["_online"]
    )
    leaf["manifest_status"] = (primary or {}).get("status")
    for data in (leaf["_eval"], leaf["_online"]):
        if data is not None and data.get("status") != "completed":
            leaf["issues"].append(f"manifest status is {data.get('status')!r}")
    audit = (leaf["_online"] or {}).get("evaluation") or {}
    audit_name = audit.get("weight_audit") or "weight_audit.json"
    if (directory / audit_name).is_file():
        leaf["weight_audit"] = batch.rel(directory / audit_name)
    episodes = []
    if leaf["_eval"] is not None:
        block = (leaf["_eval"].get("policies") or {}).get(policy) or {}
        episodes = [e for e in block.get("episodes") or [] if e.get("seed") == seed]
    elif leaf["_online"] is not None:
        episodes = [
            e for e in leaf["_online"].get("episodes") or [] if e.get("seed") == seed
        ]
    if not episodes:
        leaf["issues"].append(f"no {policy} episode for seed {seed}")
    for entry in episodes:
        path = _episode_dir(entry.get("episode_dir"), directory)
        relative = batch.rel(path) if path is not None else None
        inputs = path / "inputs" if path is not None else None
        leaf["episodes"].append(
            {
                "seed": entry.get("seed"),
                "episode_dir": relative,
                "inputs": batch.rel(inputs)
                if inputs is not None and inputs.is_dir()
                else None,
            }
        )
        if relative is None:
            leaf["issues"].append("episode directory is outside the batch root")
    leaf["status"] = "complete" if not leaf["issues"] else "incomplete"
    return leaf


def _public(leaf: dict) -> dict:
    return {k: v for k, v in leaf.items() if not k.startswith("_")}


def _operate_reference(batch: _Batch, task: dict) -> dict:
    ident = task["identity"]
    model = batch.binding(task)
    leaf = _leaf(batch, task, "model")
    recorded = [
        _dig(leaf["_eval"], "bundle.model_sha256"),
        _dig(leaf["_online"], "parent.model_sha256"),
    ]
    expected = model.get("model_sha256")
    if expected is not None and any(v is not None and v != expected for v in recorded):
        leaf["issues"].append("recorded model digest differs from the bound model")
        leaf["status"] = "incomplete"
    if model["status"] == "missing" and leaf["status"] == "complete":
        leaf["issues"].append("model binding is missing")
        leaf["status"] = "incomplete"
    schedule = task.get("schedule")
    config = batch.config_ref(task)
    group = canonical_sha256(
        {
            "scenario": ident["scenario"],
            "row": ident["row"],
            "config_sha256": (config or {}).get("sha256"),
            "training_seed": ident["training_seed"],
            "model_source": ident["model_source"],
            "checkpoint": ident["checkpoint"],
            "model_sha256": expected,
            "operation_digest": ident["operation_digest"],
            "protocol": ident["protocol"],
            "schedule_digest": ident["schedule_digest"],
            "seed_role": ident["seed_role"],
        }
    )
    return {
        "task": task["id"],
        "key": task["key"],
        "operation": ident["operation"],
        "operation_digest": ident["operation_digest"],
        "mode": "frozen" if ident["protocol"] in FROZEN_MODES else "online",
        "protocol": ident["protocol"],
        "schedule": None
        if schedule is None
        else {"digest": ident["schedule_digest"], "kind": schedule.get("kind")},
        "role": ident["seed_role"],
        "seed": ident["seed"],
        "model_sha256": expected,
        "config": config,
        "group": group,
        **_public(leaf),
    }


def _baseline_reference(batch: _Batch, task: dict) -> dict:
    ident = task["identity"]
    leaf = _leaf(batch, task, ident["policy"])
    reference = batch.plan["scenarios"][ident["scenario"]]["reference"]
    config, planning = batch.config_ref(task), batch.planning_ref(task)
    group = canonical_sha256(
        {
            "scenario": ident["scenario"],
            "policy": ident["policy"],
            "seed_role": ident["seed_role"],
            "config_sha256": (config or {}).get("sha256"),
            "planning_seed": (planning or {}).get("planning_seed"),
            "planner_settings_sha256": (planning or {}).get("planner_settings_sha256"),
            "reference": reference["sha256"]
            if reference and ident["policy"] == "scripted"
            else None,
        }
    )
    return {
        "task": task["id"],
        "key": task["key"],
        "policy": ident["policy"],
        "mode": "baseline",
        "protocol": None,
        "schedule": None,
        "role": ident["seed_role"],
        "seed": ident["seed"],
        "physical_digest": ident["physical_digest"],
        "config": config,
        **({"planning": planning} if planning is not None else {}),
        "group": group,
        **_public(leaf),
    }


def _split_task(task: dict, attempt_dir):
    """The plan task plus an attempt directory passed either as a keyword or a task field."""
    if "attempt_dir" in task:
        task = dict(task)
        given = task.pop("attempt_dir")
        attempt_dir = attempt_dir if attempt_dir is not None else given
    return task, attempt_dir


def _write_csv(path: Path, rows: list[dict], fields) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)
    return sha256_file(path)


def _asset(
    batch: _Batch, record: dict | None, target_dir: Path, issues: list, outputs: dict
) -> dict | None:
    if record is None:
        return None
    source = Path(record["path"])
    entry = {"path": None, "sha256": record["sha256"]}
    if not source.is_file():
        issues.append(f"input {source.name} is no longer available")
        return entry
    if sha256_file(source) != record["sha256"]:
        issues.append(f"input {source.name} changed after planning")
        return entry
    target = target_dir / source.name
    if not (target.is_file() and sha256_file(target) == record["sha256"]):
        _copy(source, target)
    entry["path"] = batch.rel(target)
    outputs[entry["path"]] = record["sha256"]
    return entry
