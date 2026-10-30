"""Batch reporting: scenario indexes, reviews, accepted training curves and summaries.

The sole writer of shared report destinations in a plan version 3 batch root.
It reads accepted task attempts (``accepted`` maps a task id to the attempt the
scheduler accepted) and never writes into, moves or relocates them.

- ``curves`` -- accepted training history per train task under
  ``analysis/<scenario>/curves/<key>/attempt-A/<row>/train-seed-<S>/``. History
  follows ``resume.parent`` links inside the root, excludes post-checkpoint
  tails and keeps complete-episode counting (status ``completed`` with exactly
  the row's decisions per episode). ``training_curve_sources.json`` keeps its
  version 1 payload; it has no completion-status field.
- ``review`` -- ``mission_review.json`` version 1 from
  ``episode_review.scene_review`` over pooled frozen deterministic views, plus
  the other accepted operation/baseline episodes in the same ``episodes`` map.
- ``index`` -- the atomic ``main/<scenario>/`` projection:
  ``mission_scenario.json`` version 4 with explicit relative references, a copy
  of the accepted review, optional ``phase_comparison.json`` version 1 history
  imports, hashed scenario assets and the reward summaries.
- :func:`build_comparison_view` -- verified per-model evaluation views for
  ``scripts.rl.compare --eval-dirs``.

Paths written to indexes are relative to the batch root and never escape it.
Metric formulas, windows and missing-value rules belong to
``policy.mission_metrics`` / ``policy.episode_review``; a missing value stays
``None``.
"""

import copy
import csv
import fcntl
import json
import os
import shutil
from pathlib import Path, PurePosixPath

from scripts.artifact_io import canonical_sha256, sha256_file, write_json
from scripts.rl.experiments.config import FROZEN_MODES
from scripts.rl.experiments.plan import (COMPARISON_NAME, CURVE_SOURCES, EVAL_MANIFEST, INDEX_NAME,
                                         ONLINE_MANIFEST, REVIEW_NAME)
from scripts.rl.policy import episode_review

MISSION_SCENARIO_VERSION = 4
TRAINING_CURVE_SOURCES_VERSION = 1
PHASE_COMPARISON_VERSION = 1
PHASE_COMPARISON_NAME = "phase_comparison.json"
CURVES_CSV = "training_curves.csv"
REWARD_SUMMARY_VERSION = 1
REWARD_SUMMARY_CSV = "reward_comparison.csv"
REWARD_SUMMARY_JSON = "reward_comparison.json"
# Same metrics and leading CSV columns as the retired campaign summary; the
# identity columns that follow make each row's source explicit.
REWARD_SUMMARY_METRICS = ("delivery_ratio", "worst_node_delivery_fraction", "post_jammer_delivery_ratio",
                          "recovery_time_s", "coverage_fraction_mean", "unsafe_proximity_fraction",
                          "travel_m_total", "displacement_m_final")
REWARD_SUMMARY_FIELDS = ("scenario", "reward", "training_seed", "policy", "completed_episodes",
                         *REWARD_SUMMARY_METRICS, "checkpoint", "operation", "protocol", "seed_role",
                         "evaluation_seeds", "model_sha256")
REWARD_SUMMARY_NOTE = ("Means of common domain metrics over completed episodes, per evaluated "
                       "configuration. Rows with different reward definitions are not ranked "
                       "against each other; missing measurements stay empty.")
REPORT_HANDLERS = ("curves", "review", "index")
VIEW_DIR = "view"
VIEW_SOURCES = "view_sources.json"
CURVE_NOTE = ("Training seed episodes; changing policy and channel draws, not held-out checkpoint "
              "evaluations. PPO logs retain their original timestep counters and are cut at the "
              "accepted history boundary.")
HISTORY_NOTE = ("Imported recorded diagnostics; small source files are copied with their original "
                "hashes. Historical metrics are not rerun or pooled with batch results.")
_PROGRESS_STEPS = "time/total_timesteps"
_RESULT_KINDS = ("train", "operate", "baseline", "curves", "review", "compare")
# Fields every pooled per-seed evaluation must share before seeds are merged.
_POOL_FIELDS = ("scenario_identity", "band", "bundle.model_sha256", "bundle.model_selection",
                "bundle.num_timesteps", "training", "selection", "observation_schema",
                "reward_schema", "seed_roles.role", "seed_roles.held_out", "deterministic",
                "metric_source", "policies.model.baseline")


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
                raise ValueError(f"accepted directory for {task_id} is not inside that task's destination")
            self.accepted[task_id] = path
        self._bindings = {}
        # Set by the index: where config/mapping files referenced by leaves are copied.
        self.assets_dir = None
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
        return [t for t in self.plan["tasks"] if t["scenario"] == scenario and t["kind"] in kinds]

    def _hashed_asset(self, path, sha256, folder: str) -> dict:
        if self.assets_dir is None or sha256 is None:
            return {"path": self.rel(path), "sha256": sha256}
        return _asset(self, {"path": str(path), "sha256": sha256}, self.assets_dir / folder,
                      self.asset_issues, self.asset_outputs)

    def config_ref(self, task: dict) -> dict | None:
        """The INI a leaf used: copied into the root (when indexing), hashed, with its source."""
        config = task.get("config")
        if config is None:
            return None
        asset = self._hashed_asset(config["path"], config["sha256"], config["sha256"][:12])
        return {"path": asset["path"], "sha256": config["sha256"], "config_source": config.get("config_source")}

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
        return {"planning_seed": planning.get("planning_seed"),
                "planning_seed_source": planning.get("planning_seed_source"),
                "planner_settings_sha256": planning.get("planner_settings_sha256"), "mapping_file": mapping}

    def task_dims(self, task: dict) -> tuple:
        ident = task["identity"]
        return (ident["row"], ident["training_seed"], ident["model_source"], ident["checkpoint"])

    def binding(self, task: dict) -> dict:
        """Model identity of an operate task from its write-once binding (or imported source)."""
        spec = task.get("binding")
        if spec is None:
            return {"status": "none", "binding": None, "model_sha256": None}
        if spec.get("producer") is None:
            return {"status": "source", "binding": None, "source_digest": spec["source_digest"],
                    "model_selection": str(spec["model"]), "model_sha256": spec["model_sha256"],
                    "model_path": None}
        path = check_relative(spec["path"])
        if path in self._bindings:
            return self._bindings[path]
        data = _load(self.root / path)
        if data is not None and "model_binding_version" not in data and isinstance(data.get("binding"), dict):
            data = data["binding"]
        if data is None or "model_sha256" not in data:
            identity = {"status": "missing", "binding": path, "model_sha256": None,
                        "checkpoint": spec["checkpoint"]}
        else:
            identity = {"status": "bound", "binding": path, "checkpoint": spec["checkpoint"],
                        "model_selection": data.get("model_selection"),
                        "run_dir": self.rel(data["run_dir"]) if data.get("run_dir") else None,
                        "model_path": self.rel(data["model_path"]) if data.get("model_path") else None,
                        "model_sha256": data.get("model_sha256"),
                        "optimizer_sha256": data.get("optimizer_sha256"),
                        "num_timesteps": data.get("num_timesteps"), "n_updates": data.get("n_updates"),
                        "train_manifest_sha256": data.get("train_manifest_sha256")}
        self._bindings[path] = identity
        return identity


def _seed_segment(identity: dict) -> str:
    if identity["model_source"] is not None:
        return f"model-{identity['model_source'][:12]}"
    return f"train-seed-{identity['training_seed']}"


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
        numbers = [int(p.name[8:]) for p in task_dir.glob("attempt-*") if p.name[8:].isdigit()]
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
    leaf = {"attempt": None, "eval_manifest": None, "eval_manifest_sha256": None,
            "online_manifest": None, "online_manifest_sha256": None, "weight_audit": None,
            "manifest_status": None, "episodes": [], "issues": [], "_eval": None, "_online": None,
            "_dir": directory}
    if directory is None:
        leaf["status"] = "skipped_selection" if task["id"] in batch.skipped else "missing"
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
    primary = leaf["_eval"] if task["expected_outputs"][0] == EVAL_MANIFEST else leaf["_online"]
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
        episodes = [e for e in leaf["_online"].get("episodes") or [] if e.get("seed") == seed]
    if not episodes:
        leaf["issues"].append(f"no {policy} episode for seed {seed}")
    for entry in episodes:
        path = _episode_dir(entry.get("episode_dir"), directory)
        relative = batch.rel(path) if path is not None else None
        inputs = path / "inputs" if path is not None else None
        leaf["episodes"].append({"seed": entry.get("seed"), "episode_dir": relative,
                                 "inputs": batch.rel(inputs) if inputs is not None and inputs.is_dir()
                                 else None})
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
    recorded = [_dig(leaf["_eval"], "bundle.model_sha256"), _dig(leaf["_online"], "parent.model_sha256")]
    expected = model.get("model_sha256")
    if expected is not None and any(v is not None and v != expected for v in recorded):
        leaf["issues"].append("recorded model digest differs from the bound model")
        leaf["status"] = "incomplete"
    if model["status"] == "missing" and leaf["status"] == "complete":
        leaf["issues"].append("model binding is missing")
        leaf["status"] = "incomplete"
    schedule = task.get("schedule")
    config = batch.config_ref(task)
    group = canonical_sha256({"scenario": ident["scenario"], "row": ident["row"],
                              "config_sha256": (config or {}).get("sha256"),
                              "training_seed": ident["training_seed"], "model_source": ident["model_source"],
                              "checkpoint": ident["checkpoint"], "model_sha256": expected,
                              "operation_digest": ident["operation_digest"], "protocol": ident["protocol"],
                              "schedule_digest": ident["schedule_digest"], "seed_role": ident["seed_role"]})
    return {"task": task["id"], "key": task["key"], "operation": ident["operation"],
            "operation_digest": ident["operation_digest"],
            "mode": "frozen" if ident["protocol"] in FROZEN_MODES else "online",
            "protocol": ident["protocol"],
            "schedule": None if schedule is None else {"digest": ident["schedule_digest"],
                                                       "kind": schedule.get("kind")},
            "role": ident["seed_role"], "seed": ident["seed"], "model_sha256": expected,
            "config": config, "group": group, **_public(leaf)}


def _baseline_reference(batch: _Batch, task: dict) -> dict:
    ident = task["identity"]
    leaf = _leaf(batch, task, ident["policy"])
    reference = batch.plan["scenarios"][ident["scenario"]]["reference"]
    config, planning = batch.config_ref(task), batch.planning_ref(task)
    group = canonical_sha256({"scenario": ident["scenario"], "policy": ident["policy"],
                              "seed_role": ident["seed_role"], "config_sha256": (config or {}).get("sha256"),
                              "planning_seed": (planning or {}).get("planning_seed"),
                              "planner_settings_sha256": (planning or {}).get("planner_settings_sha256"),
                              "reference": reference["sha256"] if reference and ident["policy"] == "scripted"
                              else None})
    return {"task": task["id"], "key": task["key"], "policy": ident["policy"], "mode": "baseline",
            "protocol": None, "schedule": None, "role": ident["seed_role"], "seed": ident["seed"],
            "physical_digest": ident["physical_digest"], "config": config,
            **({"planning": planning} if planning is not None else {}), "group": group, **_public(leaf)}



def _episode_result(entry: dict):
    from scripts.rl.policy.evaluate import EpisodeResult
    return EpisodeResult(seed=entry.get("seed"), episode_dir=entry.get("episode_dir"),
                         status=entry.get("status"), exit_code=entry.get("exit_code"),
                         decisions=entry.get("decisions") or 0, total_return=entry.get("return"),
                         reward_components_sum=entry.get("reward_components_sum") or {},
                         revalidated_slots_total=entry.get("revalidated_slots_total"),
                         mask_violations=entry.get("mask_violations"),
                         actions_sha256=entry.get("actions_sha256"), metrics=entry.get("metrics") or {},
                         summary_json=entry.get("summary_json"), error=entry.get("error"))


def _policy_block(entries: list[dict], expected: int, metadata) -> dict:
    from scripts.rl.policy.evaluate import summarize
    entries = sorted(entries, key=lambda e: e["seed"])
    block = {"episodes": entries, "summary": summarize([_episode_result(e) for e in entries], expected)}
    if metadata:
        block["baseline"] = metadata
    return block


def _pool(batch: _Batch, model_tasks: list[dict], baseline_tasks: list[dict], label: str,
          allow_partial: bool):
    """One eval-manifest-v8-shaped record pooling per-seed leaves of one model; refuses mixing."""
    seeds = sorted(t["identity"]["seed"] for t in model_tasks)
    if len(set(seeds)) != len(seeds):
        raise ValueError(f"{label}: a pooled view repeats an evaluation seed")
    configs = {(t.get("config") or {}).get("sha256") for t in model_tasks}
    if len(configs) > 1:
        raise ValueError(f"{label}: refusing to pool leaves run with different INIs (config sha256)")
    config_sha = next(iter(configs))
    present, missing, sources = [], [], []
    for task in model_tasks:
        directory = batch.dir_of(task["id"])
        if directory is None:
            missing.append(task["id"])
            continue
        manifest = _load(directory / EVAL_MANIFEST)
        if manifest is None:
            raise ValueError(f"{task['id']}: protocol {task['identity']['protocol']} wrote no readable "
                             f"{EVAL_MANIFEST}; it cannot join an evaluation view")
        if manifest.get("status") != "completed" or list(manifest.get("seeds") or []) != [task["identity"]["seed"]]:
            missing.append(task["id"])
            continue
        if set(manifest.get("policies") or {}) != {"model"}:
            raise ValueError(f"{task['id']}: an operation leaf must hold only the model policy")
        bound = batch.binding(task).get("model_sha256")
        if bound is not None and _dig(manifest, "bundle.model_sha256") != bound:
            raise ValueError(f"{task['id']}: evaluated model differs from its bound model")
        present.append((task, directory, manifest))
        sources.append({"task": task["id"], "key": task["key"], "role": "model",
                        "eval_manifest": batch.rel(directory / EVAL_MANIFEST),
                        "sha256": sha256_file(directory / EVAL_MANIFEST)})
    if missing and not allow_partial:
        raise ValueError(f"{label}: missing accepted evaluations {missing}")
    if not present:
        return None, sources, missing
    reference = present[0][2]
    for task, _, manifest in present[1:]:
        differing = [f for f in _POOL_FIELDS if _dig(manifest, f) != _dig(reference, f)]
        if differing:
            raise ValueError(f"{label}: refusing to pool {task['id']} with {present[0][0]['id']}; "
                             f"they differ in {differing}")
    model_entries = []
    for _, directory, manifest in present:
        for entry in manifest["policies"]["model"]["episodes"]:
            path = _episode_dir(entry.get("episode_dir"), directory)
            model_entries.append({**entry, "episode_dir": None if path is None else str(path)})
    merged = copy.deepcopy(reference)
    merged["label"] = label
    merged["seeds"] = seeds
    policies = {"model": _policy_block(model_entries, len(seeds),
                                       reference["policies"]["model"].get("baseline"))}
    by_policy = {}
    role = _dig(reference, "seed_roles.role")
    for task in baseline_tasks:
        ident = task["identity"]
        if (ident["seed_role"] != role or ident["seed"] not in seeds
                or (task.get("config") or {}).get("sha256") != config_sha):
            continue
        directory = batch.dir_of(task["id"])
        manifest = None if directory is None else _load(directory / EVAL_MANIFEST)
        if manifest is None or manifest.get("status") != "completed":
            missing.append(task["id"])
            if not allow_partial:
                raise ValueError(f"{label}: missing accepted baseline {task['id']}")
            continue
        for field in ("scenario_identity", "metric_source"):
            if manifest.get(field) != reference.get(field):
                raise ValueError(f"{label}: baseline {task['id']} differs from the model in {field}")
        block = (manifest.get("policies") or {}).get(ident["policy"]) or {}
        group = by_policy.setdefault(ident["policy"], {"entries": [], "metadata": block.get("baseline")})
        for entry in block.get("episodes") or []:
            if entry.get("seed") == ident["seed"]:
                path = _episode_dir(entry.get("episode_dir"), directory)
                group["entries"].append({**entry, "episode_dir": None if path is None else str(path)})
        sources.append({"task": task["id"], "key": task["key"], "role": ident["policy"],
                        "eval_manifest": batch.rel(directory / EVAL_MANIFEST),
                        "sha256": sha256_file(directory / EVAL_MANIFEST),
                        "baseline": block.get("baseline")})
    for policy in sorted(by_policy):
        policies[policy] = _policy_block(by_policy[policy]["entries"], len(seeds), by_policy[policy]["metadata"])
    merged["policies"] = policies
    merged["episodes_expected"] = len(policies) * len(seeds)
    merged["episodes_completed"] = sum(b["summary"]["completed_episodes"] for b in policies.values())
    merged["status"] = ("completed" if merged["episodes_completed"] == merged["episodes_expected"]
                        else "partial" if merged["episodes_completed"] else "failed")
    return merged, sources, missing


def _model_groups(tasks: list[dict], batch: _Batch) -> dict:
    groups = {}
    for task in tasks:
        groups.setdefault(batch.task_dims(task), []).append(task)
    return groups


def _split_task(task: dict, attempt_dir):
    """The plan task plus an attempt directory passed either as a keyword or a task field."""
    if "attempt_dir" in task:
        task = dict(task)
        given = task.pop("attempt_dir")
        attempt_dir = attempt_dir if attempt_dir is not None else given
    return task, attempt_dir


def build_comparison_view(task: dict, plan: dict, root, accepted: dict, *, attempt_dir=None,
                          skipped=()) -> list[str]:
    """Write ``<attempt>/view/<model>/eval_manifest.json`` per model and return the directories.

    Seeds of one model pool only when scenario digests, model identity, seed
    role, protocol and schedule agree; attempts are never pooled and other seed
    roles are left out. A model with no accepted leaf gets an empty directory so
    ``compare`` records it as missing. ``attempt_dir`` is the compare attempt;
    when omitted the next ``attempt-N`` of the task is created. ``accepted`` values
    are attempt directories or the scheduler's ``{state, attempt_dir}`` records.
    """
    task, attempt_dir = _split_task(task, attempt_dir)
    batch = _Batch(plan, root, accepted, skipped)
    if batch.by_id.get(task["id"]) != task or task["kind"] != "compare":
        raise ValueError(f"{task.get('id')} is not a compare task of this plan")
    view = task["view"]
    sources = [batch.by_id[i] for i in view["sources"]]
    baselines = [batch.by_id[i] for i in view["baselines"]]
    if not sources:
        raise ValueError(f"{task['id']}: the view has no operation sources")
    first = sources[0]["identity"]
    for source in sources:
        ident = source["identity"]
        for dim in ("operation", "operation_digest", "protocol", "schedule_digest", "seed_role", "checkpoint"):
            if ident[dim] != first[dim]:
                raise ValueError(f"{task['id']}: sources differ in {dim}; refusing a mixed view")
        if ident["operation"] != view["operation"]:
            raise ValueError(f"{task['id']}: {source['id']} is not operation {view['operation']}")
    if first["protocol"] not in FROZEN_MODES:
        raise ValueError(f"{task['id']}: protocol {first['protocol']} writes no evaluation manifest to compare")
    attempt = _new_attempt(batch, task, attempt_dir)
    directories = []
    for dims, members in _model_groups(sources, batch).items():
        row, _, _, checkpoint = dims
        segment = _seed_segment(members[0]["identity"])
        label = f"{row} checkpoint-{checkpoint} {view['operation']}"
        merged, used, missing = _pool(batch, members, baselines, label, view["allow_incomplete"])
        directory = attempt / VIEW_DIR / f"{row}--{segment}"
        directory.mkdir(parents=True, exist_ok=False)
        if merged is not None:
            _write(directory / EVAL_MANIFEST, merged)
        _write(directory / VIEW_SOURCES, {"view_sources_version": 1, "compare_task": task["id"],
                                          "label": label, "sources": used, "missing": missing})
        directories.append(str(directory))
    return directories



def _complete_episodes(directory: Path, decisions: int) -> list[tuple[Path, dict]]:
    found = []
    for path in sorted(directory.glob("episode-*/rl_episode.json")):
        record = _load(path)
        if record and record.get("status") == "completed" and record.get("steps") == decisions:
            found.append((path.parent, record))
    return found


def _progress(source: Path, target: Path, limit: int) -> str:
    """PPO progress rows up to the accepted boundary, so no optimizer point appears twice."""
    with source.open(newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        rows = [r for r in reader if _PROGRESS_STEPS not in fields or not r.get(_PROGRESS_STEPS)
                or float(r[_PROGRESS_STEPS]) <= limit]
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, target)
    return sha256_file(target)


def _history(batch: _Batch, train_dir: Path, decisions: int, case: dict | None, gate_key) -> tuple:
    """Accepted training history: (rows, sources, warnings), parents first."""
    rows, sources, warnings = [], [], []
    gate = ((case or {}).get("seeds") or {}).get(str(gate_key))
    physical = case is not None and gate is not None and decisions == 600
    if not physical:
        warnings.append("physical curve metrics are defined for 600-decision episodes with a declared "
                        "case gate; rows carry episode totals only")

    def add(directory: Path, expected_total: int, selected: dict | None, source: str):
        manifest = _load(directory / "train_manifest.json")
        if manifest is None:
            raise ValueError(f"{batch.rel(directory)}: no readable train_manifest.json")
        resume = manifest.get("resume")
        start = 0
        if resume:
            restored = int(resume["restored_timesteps"])
            if restored % decisions:
                raise ValueError(f"{batch.rel(directory)}: restored decisions are not whole episodes")
            start = restored // decisions
            parent = resume["parent"]
            parent_dir = Path(parent["run_dir"]).resolve()
            if batch.rel(parent_dir) is not None:
                kind = "recovered" if parent.get("model_selection") == "checkpoint" else "parent"
                add(parent_dir, start, parent, kind)
        episodes = _complete_episodes(directory, decisions)
        checkpoint = bool(selected and selected.get("model_selection") == "checkpoint")
        if checkpoint:
            from scripts.rl.policy.bundle import checkpoint_counters
            model = Path(selected["model_path"])
            if not model.is_file() or sha256_file(model) != selected["model_sha256"]:
                raise ValueError(f"{batch.rel(directory)}: selected checkpoint bytes differ from the link")
            if checkpoint_counters(model)["num_timesteps"] != expected_total * decisions:
                raise ValueError(f"{batch.rel(directory)}: checkpoint counter is not {expected_total} episodes")
        need = expected_total - start
        if len(episodes) < need or (not checkpoint and len(episodes) != need):
            raise ValueError(f"{batch.rel(directory)}: expected {need} complete episodes, found {len(episodes)}")
        entry = {"directory": batch.rel(directory),
                 "manifest_sha256": sha256_file(directory / "train_manifest.json"),
                 "restored_episodes": start, "total_episodes": expected_total,
                 "selected_checkpoint": None if not checkpoint else {
                     **selected, "run_dir": batch.rel(selected["run_dir"]),
                     "model_path": batch.rel(selected["model_path"])},
                 "complete_episodes_after_checkpoint_excluded": len(episodes) - need,
                 "ppo_log_use_only_through_timesteps": expected_total * decisions}
        sources.append(entry)
        for offset, (path, record) in enumerate(episodes[:need], 1):
            row = {"total_episode": start + offset, "training_seed": record.get("seed"), "source": source,
                   "episode_dir": batch.rel(path), "steps": record.get("steps"),
                   "cumulative_reward": record.get("cumulative_reward")}
            if physical:
                from scripts.rl.policy.mission_metrics import physical as reduce_physical
                seed = record.get("seed")
                metrics = reduce_physical(path, {**case, "seeds": {**case["seeds"], str(seed): gate}}, seed)
                row.update({k: v for k, v in metrics.items() if v is None or isinstance(v, (int, float))})
            rows.append(row)

    manifest = _load(train_dir / "train_manifest.json")
    if manifest is None or manifest.get("status") != "completed":
        raise ValueError(f"{batch.rel(train_dir)}: accepted training has no completed train_manifest.json")
    total = int(manifest.get("num_timesteps") or 0)
    if total % decisions:
        raise ValueError(f"{batch.rel(train_dir)}: {total} decisions are not whole episodes")
    add(train_dir, total // decisions, None, "attempt")
    first = sources[0]["restored_episodes"]
    if [r["total_episode"] for r in rows] != list(range(first + 1, total // decisions + 1)):
        raise ValueError(f"{batch.rel(train_dir)}: training curve has gaps or duplicates")
    return rows, sources, warnings


def _write_csv(path: Path, rows: list[dict], fields) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)
    return sha256_file(path)


def _curves(batch: _Batch, task: dict, attempt: Path) -> dict:
    outputs, warnings, incomplete, all_sources = {}, [], False, []
    case = batch.plan["scenarios"][task["scenario"]]["case"]
    for train_id in task["needs"]:
        train = batch.by_id[train_id]
        directory = batch.dir_of(train_id)
        if directory is None:
            warnings.append(f"{train_id}: no accepted training attempt")
            incomplete = True
            continue
        row = batch.rows[train["row"]]
        decisions = row.get("decisions_per_episode") or (row.get("training") or {}).get("decisions_per_episode")
        if not decisions:
            warnings.append(f"{train_id}: decisions per episode are not declared; no curve")
            incomplete = True
            continue
        key = (train.get("config_lookup") or {}).get("key", train["identity"]["training_seed"])
        rows, sources, notes = _history(batch, directory, int(decisions), case, key)
        warnings += [f"{train_id}: {note}" for note in notes]
        target = attempt / train["row"] / f"train-seed-{train['identity']['training_seed']}"
        for index, source in enumerate(sources):
            progress = batch.root / source["directory"] / "ppo" / "progress.csv"
            if progress.is_file():
                copied = target / "curve_sources" / f"{index:02}-ppo-progress.csv"
                outputs[batch.rel(copied)] = _progress(progress, copied, source["ppo_log_use_only_through_timesteps"])
                source["ppo_progress"] = batch.rel(copied)
        fields = list(dict.fromkeys(k for r in rows for k in r))
        outputs[batch.rel(target / CURVES_CSV)] = _write_csv(target / CURVES_CSV, rows, fields)
        payload = {"training_curve_version": TRAINING_CURVE_SOURCES_VERSION, "sources": sources, "note": CURVE_NOTE}
        outputs[batch.rel(target / CURVE_SOURCES)] = _write(target / CURVE_SOURCES, payload)
        all_sources += sources
    outputs[batch.rel(attempt / CURVE_SOURCES)] = _write(attempt / CURVE_SOURCES, {
        "training_curve_version": TRAINING_CURVE_SOURCES_VERSION, "sources": all_sources, "note": CURVE_NOTE})
    return {"outputs": outputs, "warnings": warnings, "incomplete": incomplete}



def _review(batch: _Batch, task: dict, attempt: Path) -> dict:
    slug = task["scenario"]
    case = batch.plan["scenarios"][slug]["case"]
    warnings, outputs = [], {}
    results = [batch.by_id[i] for i in task["needs"]]
    missing = [t["id"] for t in results if batch.dir_of(t["id"]) is None and t["id"] not in batch.skipped]
    ranked = [t for t in results if t["kind"] == "operate" and t["identity"]["protocol"] == "frozen_deterministic"
              and t.get("schedule") is None and t["identity"]["seed_role"] != "held_out"]
    groups = {}
    for t in ranked:
        groups.setdefault((*batch.task_dims(t), t["identity"]["operation"], t["identity"]["seed_role"],
                           (t.get("config") or {}).get("sha256")), []).append(t)
    models = []
    mission = {} if case is None else {"mission": case["mission"]}
    # Leaves run on different INIs rank separately; the label names the INI only when needed.
    shared = {}
    for key in groups:
        shared[key[:6]] = shared.get(key[:6], 0) + 1
    for key, members in groups.items():
        row, training_seed, _, checkpoint, operation, role, config = key
        segment = _seed_segment(members[0]["identity"])
        label = f"{row} {segment} checkpoint-{checkpoint} {operation} {role}"
        name = f"{row}--{segment}--checkpoint-{checkpoint}--{operation}--{role}"
        if shared[key[:6]] > 1:
            label += f" config-{(config or 'none')[:12]}"
            name += f"--{(config or 'none')[:12]}"
        merged, _, _ = _pool(batch, members, [], label, allow_partial=True)
        view = attempt / "views" / name
        view.mkdir(parents=True, exist_ok=False)
        if merged is not None:
            outputs[batch.rel(view / EVAL_MANIFEST)] = _write(view / EVAL_MANIFEST, merged)
        record = batch.rows[row]
        models.append({"scene": slug, **mission, "fixed": str(view), "reward": row, "profile": record["profile"],
                       "training_seed": training_seed, "stage": members[0]["stage"], "label": label})
    if not models:
        # scene_review needs one entry to name the objective; a view without a manifest is skipped.
        models.append({"scene": slug, **mission, "fixed": str(attempt / "views" / "none")})
    payload = episode_review.scene_review(batch.root, slug, models)
    for t in results:
        directory = batch.dir_of(t["id"])
        if directory is None:
            continue
        policy = t["identity"]["policy"] if t["kind"] == "baseline" else None
        for data in (_load(directory / EVAL_MANIFEST), _load(directory / ONLINE_MANIFEST)):
            if data is None:
                continue
            blocks = ([b for name, b in (data.get("policies") or {}).items() if policy in (None, name)]
                      if "policies" in data else [{"episodes": data.get("episodes") or []}])
            for block in blocks:
                for entry in block.get("episodes") or []:
                    path = _episode_dir(entry.get("episode_dir"), directory)
                    relative = batch.rel(path) if path is not None else None
                    if relative is None or relative in payload["episodes"]:
                        continue
                    if not (path / "steps.jsonl").is_file():
                        warnings.append(f"{t['id']}: episode {relative} has no steps.jsonl")
                        continue
                    payload["episodes"][relative] = {"metrics": episode_review.review_metrics(path),
                                                      "telemetry_sha256": sha256_file(path / "steps.jsonl")}
    # scene_review builds metric dicts from sets; sorted keys make the bytes reproducible.
    payload = json.loads(json.dumps(payload, sort_keys=True))
    outputs[batch.rel(attempt / REVIEW_NAME)] = _write(attempt / REVIEW_NAME, payload)
    warnings += [f"{tid}: no accepted result" for tid in missing]
    return {"outputs": outputs, "warnings": warnings, "incomplete": bool(missing)}



def _asset(batch: _Batch, record: dict | None, target_dir: Path, issues: list, outputs: dict) -> dict | None:
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


def _ini_assets(batch, record, assets_dir, issues, outputs) -> dict:
    folder = assets_dir / record["sha256"][:12]
    result = {"run_config": _asset(batch, record, folder, issues, outputs)}
    for name in ("nodes", "buildings", "jammers"):
        result[name] = _asset(batch, record.get(name), folder, issues, outputs)
    result["fallback"] = record.get("fallback", False)
    return result


def _scenario_assets(batch: _Batch, slug: str, main: Path, issues: list, outputs: dict) -> dict:
    scenario = batch.plan["scenarios"][slug]
    assets_dir = main / "assets"
    reference = scenario["reference"]
    return {"run_config": _ini_assets(batch, scenario["run_config"], assets_dir, issues, outputs),
            "configs": {role: {seed: _ini_assets(batch, record, assets_dir, issues, outputs)
                               for seed, record in sorted(entries.items())}
                        for role, entries in sorted(scenario["configs"].items())},
            "reference": None if reference is None else {
                "kind": reference["kind"],
                **_asset(batch, reference, assets_dir / f"reference-{reference['sha256'][:12]}", issues, outputs)}}


def _history_import(batch: _Batch, slug: str, main: Path, issues: list, outputs: dict) -> str | None:
    sources_in = batch.plan["scenarios"][slug].get("history_sources") or []
    target = main / PHASE_COMPARISON_NAME
    if not sources_in:
        target.unlink(missing_ok=True)
        return None
    diagnostics, sources = [], []
    for index, source in enumerate(sources_in):
        directory = Path(source["path"])
        found = directory / PHASE_COMPARISON_NAME
        data = _load(found) if found.is_file() else None
        if data is None or data.get("phase_comparison_version") != PHASE_COMPARISON_VERSION:
            issues.append(f"history source {index} has no {PHASE_COMPARISON_NAME} version "
                          f"{PHASE_COMPARISON_VERSION}")
            continue
        original = sha256_file(found)
        folder = main / "history" / f"{index:02}-{original[:12]}"
        for name in (PHASE_COMPARISON_NAME, INDEX_NAME):
            if (directory / name).is_file():
                outputs[batch.rel(folder / name)] = _copy(directory / name, folder / name)
        diagnostics += data.get("diagnostics") or []
        sources.append({"path": batch.rel(folder / PHASE_COMPARISON_NAME), "sha256": original,
                        "case": data.get("case")})
    outputs[batch.rel(target)] = _write(target, {"phase_comparison_version": PHASE_COMPARISON_VERSION,
                                                 "case": slug, "diagnostics": diagnostics, "sources": sources,
                                                 "note": HISTORY_NOTE})
    return batch.rel(target)


def _mean_row(episodes: list[dict]) -> dict:
    row = {"completed_episodes": len(episodes)}
    for metric in REWARD_SUMMARY_METRICS:
        values = [(e.get("metrics") or {}).get(metric) for e in episodes]
        values = [v for v in values if v is not None]
        row[metric] = sum(values) / len(values) if values else None
    return row


def _completed(leaf: dict, policy: str) -> list[dict]:
    if leaf["_eval"] is not None:
        block = (leaf["_eval"].get("policies") or {}).get(policy) or {}
        return [e for e in block.get("episodes") or [] if e.get("status") == "completed"]
    if leaf["_online"] is not None and leaf["_online"].get("status") == "completed":
        return list(leaf["_online"].get("episodes") or [])
    return []


def _summary_rows(batch: _Batch, slug: str) -> list[dict]:
    """Per evaluated configuration: model per (row, model, checkpoint, operation, role); baseline per policy/role."""
    rows, groups = [], {}
    for task in batch.tasks(slug, "operate"):
        ident = task["identity"]
        groups.setdefault(("model", *batch.task_dims(task), ident["operation"], ident["seed_role"],
                           (task.get("config") or {}).get("sha256")), []).append(task)
    for task in batch.tasks(slug, "baseline"):
        groups.setdefault(("baseline", task["identity"]["policy"], task["identity"]["seed_role"],
                           (task.get("config") or {}).get("sha256")), []).append(task)
    for key, members in groups.items():
        episodes, sources, seeds = [], [], []
        for task in members:
            policy = "model" if key[0] == "model" else key[1]
            leaf = _leaf(batch, task, policy)
            done = [e for e in _completed(leaf, policy) if e.get("seed") == task["identity"]["seed"]]
            if done:
                seeds.append(task["identity"]["seed"])
            episodes += done
            manifest = leaf["eval_manifest"] or leaf["online_manifest"]
            if manifest is not None:
                sources.append({"task": task["id"], "manifest": manifest,
                                "sha256": leaf["eval_manifest_sha256"] or leaf["online_manifest_sha256"]})
        first = members[0]["identity"]
        if key[0] == "model":
            row = {"scenario": slug, "reward": first["row"], "training_seed": first["training_seed"],
                   "policy": "model", **_mean_row(episodes), "checkpoint": first["checkpoint"],
                   "operation": first["operation"], "protocol": first["protocol"], "seed_role": first["seed_role"],
                   "evaluation_seeds": sorted(seeds), "model_sha256": batch.binding(members[0]).get("model_sha256")}
        else:
            row = {"scenario": slug, "reward": None, "training_seed": None, "policy": first["policy"],
                   **_mean_row(episodes), "checkpoint": None, "operation": None, "protocol": None,
                   "seed_role": first["seed_role"], "evaluation_seeds": sorted(seeds), "model_sha256": None}
        rows.append({**row, "config_sha256": key[-1], "sources": sources})
    return rows


def _csv_row(row: dict) -> dict:
    return {**row, "evaluation_seeds": ";".join(map(str, row["evaluation_seeds"]))}


def _summary_payload(scope: str, batch: _Batch, rows: list[dict], extra=None) -> dict:
    return {"reward_summary_version": REWARD_SUMMARY_VERSION, "scope": scope,
            "batch": batch.plan["matrix"]["name"], "metrics": list(REWARD_SUMMARY_METRICS),
            "note": REWARD_SUMMARY_NOTE, **(extra or {}), "rows": rows}


def write_reward_summary(plan: dict, root) -> dict:
    """Rebuild main/reward_comparison.csv and .json from the scenario projections, under a lock."""
    batch = _Batch(plan, root, {})
    main = batch.root / "main"
    main.mkdir(parents=True, exist_ok=True)
    outputs = {}
    with open(main / ".reward_comparison.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows, scenarios = [], []
        for slug in plan["scenarios"]:
            path = main / slug / REWARD_SUMMARY_JSON
            data = _load(path)
            if data is None:
                continue
            scenarios.append({"scenario": slug, "path": batch.rel(path), "sha256": sha256_file(path)})
            rows += data["rows"]
        outputs[f"main/{REWARD_SUMMARY_CSV}"] = _write_csv(main / REWARD_SUMMARY_CSV,
                                                           [_csv_row(r) for r in rows], REWARD_SUMMARY_FIELDS)
        outputs[f"main/{REWARD_SUMMARY_JSON}"] = _write(main / REWARD_SUMMARY_JSON, _summary_payload(
            "batch", batch, rows, {"scenarios": scenarios}))
    return outputs


def _model_entries(batch: _Batch, slug: str) -> list[dict]:
    entries = {}
    for task in batch.tasks(slug, "operate"):
        entries.setdefault(batch.task_dims(task), []).append(task)
    models = []
    for (row_name, training_seed, model_source, checkpoint), members in entries.items():
        row = batch.rows[row_name]
        labels = row.get("labels") or {}
        training = None
        if training_seed is not None:
            train_id = f"train/{slug}/{row_name}/train-seed-{training_seed}"
            train = batch.by_id[train_id]
            directory = batch.dir_of(train_id)
            manifest_path = directory / "train_manifest.json" if directory is not None else None
            present = manifest_path is not None and manifest_path.is_file()
            training = {"task": train_id, "key": train["key"],
                        "status": "complete" if present else
                        ("skipped_selection" if train_id in batch.skipped else "missing"),
                        "attempt": batch.rel(directory) if directory is not None else None,
                        "train_manifest": batch.rel(manifest_path) if present else None,
                        "train_manifest_sha256": sha256_file(manifest_path) if present else None}
            manifest = _load(manifest_path) if present else {}
        else:
            manifest = {}
        source = row.get("model_source")
        references = sorted((_operate_reference(batch, t) for t in members),
                            key=lambda r: (r["operation"], r["role"], r["seed"]))
        selection = row.get("selection") or {}
        models.append({
            "scene": slug, "reward": row_name, "reward_label": labels.get("reward_label"),
            "profile": row["profile"], "ppo_label": labels.get("ppo_label"), "comparison": labels.get("comparison"),
            "training_seed": training_seed, "source_phase": labels.get("source_phase"),
            "tags": labels.get("tags", []), "row": row_name, "stage": members[0]["stage"],
            "checkpoint": checkpoint, "seed_segment": _seed_segment(members[0]["identity"]),
            "training": training,
            "model_source": None if source is None else {
                "digest": source["digest"], "model_sha256": source["model_sha256"],
                "num_timesteps": source.get("num_timesteps"), "n_updates": source.get("n_updates"),
                "seed": source.get("seed")},
            "continue_from": None if row.get("continue_from") is None else {
                "digest": row["continue_from"]["digest"], "model_sha256": row["continue_from"]["model_sha256"]},
            "curriculum_sha256": (row.get("curriculum") or {}).get("sha256"),
            "model": batch.binding(members[0]),
            "selection": {k: selection.get(k) for k in ("observation_preset", "action_profile", "reward_components",
                                                         "reward_weights", "observation_parameters",
                                                         "reward_parameters")},
            "schemas": {"observation_schema_sha256": _dig(manifest, "observation_schema.sha256"),
                        "reward_schema_sha256": _dig(manifest, "reward_schema.sha256")},
            "ppo": row.get("training"),
            "evaluations": references})
    return models


def _baseline_entries(batch: _Batch, slug: str) -> list[dict]:
    entries = {}
    for task in batch.tasks(slug, "baseline"):
        entries.setdefault((task["identity"]["policy"], task["identity"]["seed_role"]), []).append(task)
    result = []
    for (policy, role), members in entries.items():
        refs = sorted((_baseline_reference(batch, t) for t in members), key=lambda r: (r["seed"], r["task"]))
        entry = {"policy": policy, "role": role, "evaluations": refs}
        plannings = [r.get("planning") for r in refs]
        if plannings and plannings[0] is not None and all(p == plannings[0] for p in plannings):
            entry["planning"] = plannings[0]
        result.append(entry)
    return result


def _report_refs(batch: _Batch, slug: str, main: Path, issues: list, outputs: dict) -> dict:
    curves = []
    for task in batch.tasks(slug, "curves"):
        directory = batch.dir_of(task["id"])
        for train_id in task["needs"]:
            train = batch.by_id[train_id]
            folder = None if directory is None else \
                directory / train["row"] / f"train-seed-{train['identity']['training_seed']}"
            present = folder is not None and (folder / CURVES_CSV).is_file()
            curves.append({"task": task["id"], "train_task": train_id,
                           "curves": batch.rel(folder / CURVES_CSV) if present else None,
                           "sources": batch.rel(folder / CURVE_SOURCES) if present else None})
    review = None
    review_target = main / REVIEW_NAME
    for task in batch.tasks(slug, "review"):
        directory = batch.dir_of(task["id"])
        if directory is not None and (directory / REVIEW_NAME).is_file():
            sha = _copy(directory / REVIEW_NAME, review_target)
            outputs[batch.rel(review_target)] = sha
            review = {"task": task["id"], "source": batch.rel(directory / REVIEW_NAME),
                      "path": batch.rel(review_target), "sha256": sha}
    if review is None:
        review_target.unlink(missing_ok=True)
    comparisons = []
    for task in batch.tasks(slug, "compare"):
        directory = batch.dir_of(task["id"])
        data = None if directory is None else _load(directory / COMPARISON_NAME)
        comparisons.append({"task": task["id"], "key": task["key"], "operation": task["identity"]["operation"],
                            "checkpoint": task["identity"]["checkpoint"],
                            "status": data.get("status") if data else "missing",
                            "attempt": batch.rel(directory) if directory is not None else None,
                            "comparison": batch.rel(directory / COMPARISON_NAME) if data else None,
                            "sha256": sha256_file(directory / COMPARISON_NAME) if data else None})
    return {"curves": curves, "mission_review": review, "comparisons": comparisons,
            "phase_comparison": _history_import(batch, slug, main, issues, outputs),
            "reward_summary": f"main/{slug}/{REWARD_SUMMARY_JSON}",
            "batch_reward_summary": f"main/{REWARD_SUMMARY_JSON}"}


def build_index(batch: _Batch, slug: str, main: Path, outputs: dict) -> dict:
    """The version 4 ``mission_scenario.json`` payload; copies assets/review/history as it goes."""
    scenario = batch.plan["scenarios"][slug]
    case = scenario["case"] or {}
    issues = []
    assets = _scenario_assets(batch, slug, main, issues, outputs)
    reports = _report_refs(batch, slug, main, issues, outputs)
    batch.assets_dir = main / "assets"
    models = _model_entries(batch, slug)
    baselines = _baseline_entries(batch, slug)
    issues += sorted(set(batch.asset_issues))
    outputs.update(batch.asset_outputs)
    missing = sorted(t["id"] for t in batch.tasks(slug, *_RESULT_KINDS)
                     if batch.dir_of(t["id"]) is None and t["id"] not in batch.skipped)
    references = [r for m in models for r in m["evaluations"]] + [r for b in baselines for r in b["evaluations"]]
    incomplete = bool(missing or issues or any(r["status"] not in ("complete", "skipped_selection")
                                               for r in references)
                      or any(c["status"] != "complete" for c in reports["comparisons"]))
    validation = sorted({t["identity"]["seed"] for t in batch.tasks(slug, "operate", "baseline")
                         if t["identity"]["seed_role"] != "held_out"})
    return {
        "mission_scenario_version": MISSION_SCENARIO_VERSION,
        "batch": {"name": batch.plan["matrix"]["name"], "kind": batch.plan["matrix"]["kind"],
                  "matrix_sha256": batch.plan["matrix"]["sha256"],
                  "experiment_plan_version": batch.plan["experiment_plan_version"],
                  "plan": "experiment_plan.json"},
        "scene": slug, "objective": case.get("mission"), "environment": case.get("environment"),
        "peers": case.get("peers"), "validation_seeds": validation, "baseline_dir": None,
        "reviewed_exception": case.get("reviewed_exception", False),
        "exception_reason": case.get("exception_reason"),
        "case": scenario["case"], "band": scenario["band"], "seeds": batch.plan["seeds"],
        "assets": assets, "models": models, "baselines": baselines, "reports": reports,
        "incomplete": incomplete, "missing": missing, "issues": issues,
    }


def _index(batch: _Batch, task: dict) -> dict:
    slug = task["scenario"]
    main = batch.task_dir(task)
    main.mkdir(parents=True, exist_ok=True)
    outputs = {}
    index = build_index(batch, slug, main, outputs)
    rows = _summary_rows(batch, slug)
    summary = main / REWARD_SUMMARY_JSON
    outputs[batch.rel(summary)] = _write(summary, _summary_payload("scenario", batch, rows))
    outputs[batch.rel(main / REWARD_SUMMARY_CSV)] = _write_csv(main / REWARD_SUMMARY_CSV,
                                                               [_csv_row(r) for r in rows], REWARD_SUMMARY_FIELDS)
    outputs.update(write_reward_summary(batch.plan, batch.root))
    # The index is written last so a reader never finds it ahead of its projections.
    outputs[batch.rel(main / INDEX_NAME)] = _write(main / INDEX_NAME, index)
    return {"outputs": outputs, "warnings": index["issues"], "incomplete": index["incomplete"]}


def _validation_item(batch: _Batch, task: dict, directory: Path) -> dict:
    """Best validation reward and per-evaluation means of one accepted training attempt."""
    import numpy as np
    from scripts.rl.policy.training_artifacts import EVAL_LOG_NAME
    path = directory / "train_manifest.json"
    manifest = _load(path)
    if manifest is None or manifest.get("status") != "completed":
        raise ValueError(f"selection blocked: {task['id']} has no completed training manifest")
    seeds = set((manifest.get("evaluation") or {}).get("seeds") or [])
    if seeds & set(batch.plan["seeds"].get("held_out") or []):
        raise ValueError(f"selection never consumes held-out evidence: {task['id']} validated on "
                         f"{sorted(seeds)}")
    log = directory / EVAL_LOG_NAME
    if not log.is_file() or manifest.get("best_mean_reward") is None:
        raise ValueError(f"selection blocked: {task['id']} has no validation results")
    with np.load(log) as evaluations:
        means = [float(v) for v in evaluations["results"].mean(axis=1)]
    return {"best_mean_reward": manifest["best_mean_reward"], "checkpoint_means": means,
            "evaluations": batch.rel(log), "evaluations_sha256": sha256_file(log),
            "samples": len(means)}, path


def _score_item(batch: _Batch, task: dict, directory: Path, online: bool) -> tuple:
    """Mission scores of an accepted operation leaf, from ``policy.mission_metrics``."""
    from scripts.rl.policy import mission_metrics
    path = directory / (ONLINE_MANIFEST if online or not (directory / EVAL_MANIFEST).is_file() else EVAL_MANIFEST)
    record = _load(path)
    if record is None or record.get("status") != "completed":
        raise ValueError(f"selection blocked: {task['id']} has no completed {path.name}")
    if path.name == EVAL_MANIFEST:
        entries = ((record.get("policies") or {}).get("model") or {}).get("episodes") or []
    else:
        entries = [e for e in record.get("episodes") or [] if e.get("mode") == task["identity"]["protocol"]]
    if not entries:
        raise ValueError(f"selection blocked: {task['id']} records no episodes in {path.name}")
    values, telemetry = [], []
    for entry in entries:
        episode = _episode_dir(entry.get("episode_dir"), directory)
        if episode is None or batch.rel(episode) is None:
            raise ValueError(f"selection blocked: {task['id']} episode is outside the batch root")
        values.append(mission_metrics.mission_episode_metrics(episode)["mission_score"])
        telemetry.append(sha256_file(episode / "steps.jsonl"))
    return {"values": values, "telemetry_sha256": telemetry, "samples": len(values)}, path


def selection_evidence(task: dict, plan: dict, root, accepted: dict) -> dict:
    """Evidence for ``selection.select``: {candidate: [item, ...]} from the declared sources only.

    Each item names its source ``task``, accepted ``attempt`` (relative), the
    ``path``/``sha256`` of the manifest it read, ``seed_role``, ``case``
    (scenario) and ``samples``. The validation rule adds ``best_mean_reward``
    and ``checkpoint_means`` (per-evaluation means, as the retired
    ``adaptive_campaign.select_profile`` read them); the mission and online
    rules add ``values`` (episode mission scores) plus the source ``row``,
    ``operation`` and ``checkpoint``. ``source_kind`` picks the inputs: train
    attempts (``training_validation``) or operate leaves at exactly the select
    task's checkpoint (``operation``, for row or ``{row, operation}``
    candidates). A missing or undeclared source or a held-out seed role raises;
    ``none`` (replay) needs no evidence.
    """
    task, _ = _split_task(task, None)
    batch = _Batch(plan, root, accepted)
    if batch.by_id.get(task.get("id")) != task or task.get("handler") != "select":
        raise ValueError(f"{task.get('id')} is not a select task of this plan")
    rule = task["selection_rule"]
    kind = rule.get("source_kind")
    if kind == "none":
        return {}
    if kind not in ("training_validation", "operation"):
        raise ValueError(f"{task['id']}: unknown selection source kind {kind!r}")
    online = rule["rule"] == "legacy-online-profile-v1"
    checkpoint = task["identity"]["checkpoint"]
    evidence = {}
    for candidate, entries in rule["candidates"].items():
        # Declared inputs: rows (with source_operation) or explicit {row, operation} entries.
        declared = {(e, rule["source_operation"]) if isinstance(e, str) else (e["row"], e["operation"])
                    for e in entries}
        ids = rule["sources"].get(candidate) or []
        if not ids:
            raise ValueError(f"selection blocked: candidate {candidate} declares no source tasks")
        items = []
        for source_id in ids:
            source = batch.by_id[source_id]
            if kind == "training_validation":
                if source["kind"] != "train" or source["row"] not in {row for row, _ in declared}:
                    raise ValueError(f"selection blocked: {source_id} is not a declared input of {candidate}")
            elif (source["kind"] != "operate"
                  or (source["row"], source["identity"]["operation"]) not in declared
                  or source["identity"]["checkpoint"] != checkpoint):
                raise ValueError(f"selection blocked: {source_id} is not a declared input of {candidate} "
                                 f"at checkpoint {checkpoint}")
            directory = batch.dir_of(source_id)
            if directory is None:
                raise ValueError(f"selection blocked: {source_id} has no accepted result")
            if kind == "training_validation":
                role = "model_selection"
                item, path = _validation_item(batch, source, directory)
            else:
                role = source["identity"]["seed_role"]
                if role == "held_out" or role != rule["seed_role"]:
                    raise ValueError(f"selection never consumes {role!r} evidence ({source_id})")
                item, path = _score_item(batch, source, directory, online)
                item = {"row": source["row"], "operation": source["identity"]["operation"],
                        "checkpoint": checkpoint, **item}
            items.append({"task": source_id, "attempt": batch.rel(directory), "path": batch.rel(path),
                          "sha256": sha256_file(path), "seed_role": role, "case": source["scenario"],
                          **item})
        evidence[candidate] = items
    return evidence


def run_report_task(task: dict, plan: dict, root, accepted: dict, *, attempt_dir=None, skipped=()) -> dict:
    """Run one ``curves``/``review``/``index`` task; returns outputs (relative path -> sha256).

    ``accepted`` maps every completed task id of the batch (not only direct
    dependencies) to its accepted attempt directory; ``skipped`` names tasks in
    ``skipped_selection``. ``curves``/``review`` write a new ``attempt-N`` (or the
    given empty ``attempt_dir``, also accepted as a task field); ``index`` rebuilds
    ``main/<scenario>/``. ``accepted`` values are attempt directories or the
    scheduler's ``{state, attempt_dir}`` records.
    """
    task, attempt_dir = _split_task(task, attempt_dir)
    batch = _Batch(plan, root, accepted, skipped)
    if batch.by_id.get(task.get("id")) != task:
        raise ValueError(f"{task.get('id')} is not a task of this plan")
    handler = task.get("handler")
    if handler not in REPORT_HANDLERS:
        raise ValueError(f"{task['id']}: handler {handler!r} is not one of {REPORT_HANDLERS}")
    if handler == "index":
        result = _index(batch, task)
        result["attempt_dir"] = None
    else:
        attempt = _new_attempt(batch, task, attempt_dir)
        result = (_curves if handler == "curves" else _review)(batch, task, attempt)
        result["attempt_dir"] = batch.rel(attempt)
    result["outputs"] = dict(sorted(result["outputs"].items()))
    return result
