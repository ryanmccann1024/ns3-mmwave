"""Batch identity, task receipts, model bindings and checkpoint recovery proposals.

Owns the plan v3 records under an output root: `runtime_identity.json`,
`state/steps/<task-key>.json` receipts, write-once `state/bindings/*.json` and
`state/recovery/<proposal-id>.json` proposals. Only the scheduler
(`ops/local.py`) writes receipts; children write their own artifacts, which the
kind-specific validators here read. Phase 9's recovery records are never read.
"""

import json
import sys
from pathlib import Path

from scripts.artifact_io import canonical_sha256, now_iso, sha256_file, write_json
from scripts.rl.cli_common import MANIFEST_NAME, MODEL_BASENAME, package_versions
from scripts.rl.experiments.plan import (CHECK_RESULT, COMPARISON_NAME, EVAL_MANIFEST,
                                         ONLINE_MANIFEST, PLAN_NAME, POST_UPDATE_CHECKPOINTS,
                                         SELECTION_RECEIPT, load_batch_plan)
from scripts.rl.ops.tasks import arg_value, resume_train_args
from scripts.sim_support import find_mesh_root

RUNTIME_IDENTITY_VERSION = 1
BATCH_STEP_VERSION = 1
BATCH_RECOVERY_VERSION = 1
RUNTIME_IDENTITY_NAME = "runtime_identity.json"
STEPS_DIR = "state/steps"
RECOVERY_DIR = "state/recovery"
STATES = ("pending", "running", "completed", "partial", "failed", "interrupted", "blocked",
          "skipped_dependency", "skipped_selection")
ACTIVE = ("pending", "running")
CHECK_KINDS = ("preflight", "replay_gate", "reward_audit")
HANDLER_KINDS = ("select", "curves", "review", "index")
EPISODE_MANIFEST = "rl_episode.json"
_MAX_LISTED = 20
_RECEIPT_FIELDS = ("batch_step_version", "task_id", "task_key", "kind", "identity", "inputs",
                   "state", "attempts", "accepted_attempt", "warnings", "created_at", "updated_at")


class IdentityChanged(ValueError):
    """A pinned code, input, binary, dependency or registry identity changed."""


class MalformedReceipt(ValueError):
    """A receipt exists but cannot be trusted; it is never overwritten."""


def _source_root() -> Path:
    return find_mesh_root()


def python_sources(mesh: Path | None = None) -> dict:
    """SHA-256 of every non-test `scripts/**/*.py`, keyed by mesh-relative path."""
    mesh = Path(mesh or _source_root())
    return {str(p.relative_to(mesh)): sha256_file(p) for p in sorted((mesh / "scripts").rglob("*.py"))
            if "tests" not in p.parts and "__pycache__" not in p.parts}


def registry_identity() -> dict:
    """Contract-independent descriptor digest of every registered reward and preset, in order."""
    from scripts.rl.env import observations, rewards
    reward_items = []
    for name in rewards.COMPONENTS:
        c = rewards.get_component(name)
        reward_items.append({"id": name, "sha256": canonical_sha256({
            "range": list(c.range), "required_facts": list(c.required_facts),
            "contract_fields": list(c.contract_fields),
            "tunable": {k: list(v) for k, v in c.tunable.items()},
            "default_parameters": c.resolve({}), "formula": c.formula,
            "zero_demand_rule": c.zero_demand_rule, "context_fields": list(c.context_fields),
            "fact_extensions": list(c.fact_extensions),
            "has_context_builder": c.context_builder is not None})})
    preset_items = []
    for name in observations.PRESETS:
        p = observations.get_preset(name)
        preset_items.append({"id": name, "sha256": canonical_sha256({
            "dtype": p.dtype, "normalization_fields": list(p.normalization_fields),
            "default_parameters": dict(p.parameters), "required_facts": list(p.required_facts),
            "compatibility_fields": list(p.compatibility_fields),
            "fact_extensions": list(p.fact_extensions)})})
    return {"reward_components": reward_items, "observation_presets": preset_items,
            "default_preset": observations.DEFAULT_PRESET}


def _file_sha(path) -> str | None:
    try:
        return sha256_file(path)
    except OSError:
        return None


def runtime_identity(root, plan: dict) -> dict:
    """The identity pinned at first run; plan inputs must still match their plan hashes."""
    root = Path(root)
    changed = [path for path, entry in plan["inputs"].items() if _file_sha(path) != entry["sha256"]]
    if changed:
        raise IdentityChanged(_bounded("inputs changed since the plan was written", changed)
                              + "; use a new --output-root")
    binary = plan["sim_binary"]
    if binary is None or _file_sha(binary["path"]) != binary["sha256"]:
        raise IdentityChanged("simulator binary differs from the plan; use a new --output-root")
    return {"runtime_identity_version": RUNTIME_IDENTITY_VERSION, "created_at": now_iso(),
            "plan": {"path": str(root / PLAN_NAME), "sha256": sha256_file(root / PLAN_NAME)},
            "matrix": {k: plan["matrix"][k] for k in ("path", "reference", "sha256")},
            "inputs": plan["inputs"],
            "parent_models": {p: e["sha256"] for p, e in plan["inputs"].items()
                              if e["kind"] in ("model", "train_manifest")},
            "sim_binary": dict(binary),
            "python_sources": python_sources(),
            "package_versions": package_versions(),
            "registry": registry_identity()}


def identity_path(root) -> Path:
    return Path(root) / RUNTIME_IDENTITY_NAME


def ensure_identity(root, plan: dict, sim_binary: str | None = None) -> dict:
    """Write the identity once at first run; afterwards only compare against it."""
    path = identity_path(root)
    if not path.exists():
        identity = runtime_identity(root, plan)
        write_json(path, identity)
        return identity
    return check_identity(root, sim_binary)


def _bounded(title: str, items: list[str]) -> str:
    shown = items[:_MAX_LISTED]
    more = f" ... and {len(items) - len(shown)} more" if len(items) > len(shown) else ""
    return f"{title}: " + ", ".join(shown) + more


def check_identity(root, sim_binary: str | None = None) -> dict:
    """Refuse any change from the pinned identity; returns the recorded identity.

    `sim_binary` is the same binary at another path (resume); its SHA-256 must
    equal the recorded one. Nothing is replaced and there is no warning mode.
    """
    root = Path(root)
    try:
        before = json.loads(identity_path(root).read_text())
    except (OSError, ValueError) as exc:
        raise IdentityChanged(f"{identity_path(root)} is missing or unreadable: {exc}") from exc
    if not isinstance(before, dict) or before.get("runtime_identity_version") != RUNTIME_IDENTITY_VERSION:
        raise IdentityChanged(f"{identity_path(root)} is not runtime identity version "
                              f"{RUNTIME_IDENTITY_VERSION}")
    changes = []
    if _file_sha(root / PLAN_NAME) != before["plan"]["sha256"]:
        changes.append(f"plan {PLAN_NAME}")
    for path, entry in before["inputs"].items():
        if _file_sha(path) != entry["sha256"]:
            changes.append(f"input {path}")
    binary_path = sim_binary or before["sim_binary"]["path"]
    if _file_sha(binary_path) != before["sim_binary"]["sha256"]:
        changes.append(f"simulator binary {binary_path}")
    now = python_sources()
    old = before["python_sources"]
    for path in sorted(set(now) | set(old)):
        if path not in old:
            changes.append(f"source added {path}")
        elif path not in now:
            changes.append(f"source removed {path}")
        elif now[path] != old[path]:
            changes.append(f"source changed {path}")
    versions = package_versions()
    for name in sorted(set(versions) | set(before["package_versions"])):
        if versions.get(name) != before["package_versions"].get(name):
            changes.append(f"dependency {name} {before['package_versions'].get(name)} -> "
                           f"{versions.get(name)}")
    if registry_identity() != before["registry"]:
        changes.append("reward/observation registry")
    if changes:
        raise IdentityChanged(_bounded("batch identity changed", changes)
                              + ". Restore the pinned code/inputs/binary/dependencies, or start "
                                "a new --output-root for a deliberate change")
    return before


def receipt_path(root, task: dict) -> Path:
    return Path(root) / STEPS_DIR / f"{task['key']}.json"


def new_receipt(task: dict, plan: dict) -> dict:
    stamp = now_iso()
    return {"batch_step_version": BATCH_STEP_VERSION, "task_id": task["id"], "task_key": task["key"],
            "kind": task["kind"], "identity": task["identity"],
            "inputs": {"files": {p: plan["inputs"][p]["sha256"] for p in task.get("inputs") or []
                                 if p in plan["inputs"]},
                       "binding": None, "selection": task.get("selection")},
            "state": "pending", "detail": None, "exit_code": None, "warnings": [], "logs": [],
            "attempts": [], "accepted_attempt": None, "outputs": [], "invalidated": [],
            "created_at": stamp, "updated_at": stamp}


def read_receipt(root, task: dict) -> dict | None:
    """The task's receipt, None when absent; any defect raises MalformedReceipt."""
    path = receipt_path(root, task)
    if not path.exists():
        return None
    try:
        receipt = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise MalformedReceipt(f"{path} is unreadable: {exc}") from exc
    if not isinstance(receipt, dict):
        raise MalformedReceipt(f"{path} is not a JSON object")
    missing = [f for f in _RECEIPT_FIELDS if f not in receipt]
    if missing:
        raise MalformedReceipt(f"{path} lacks {missing}")
    if receipt["batch_step_version"] != BATCH_STEP_VERSION:
        raise MalformedReceipt(f"{path} is not batch step version {BATCH_STEP_VERSION}")
    if receipt["task_key"] != task["key"] or receipt["task_id"] != task["id"]:
        raise MalformedReceipt(f"{path} belongs to another task")
    if receipt["state"] not in STATES or not isinstance(receipt["attempts"], list):
        raise MalformedReceipt(f"{path} has an unknown state or attempt list")
    accepted = receipt["accepted_attempt"]
    if accepted is not None and not any(a.get("attempt") == accepted for a in receipt["attempts"]):
        raise MalformedReceipt(f"{path} points at a missing accepted attempt {accepted}")
    return receipt


def write_receipt(root, receipt: dict) -> None:
    receipt["updated_at"] = now_iso()
    path = Path(root) / STEPS_DIR / f"{receipt['task_key']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, receipt)


def attempt_record(receipt: dict, number) -> dict | None:
    return next((a for a in receipt["attempts"] if a.get("attempt") == number), None)


def accepted_dir(receipt: dict | None) -> str | None:
    if not receipt or receipt.get("state") != "completed":
        return None
    attempt = attempt_record(receipt, receipt["accepted_attempt"])
    return attempt["attempt_dir"] if attempt else None


def _read(path) -> dict | None:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _outputs(attempt_dir: Path, names) -> list[dict]:
    return [{"path": str(attempt_dir / n), "sha256": sha256_file(attempt_dir / n)}
            for n in names if (attempt_dir / n).is_file()]


def _result(state, detail=None, outputs=None, warnings=None) -> dict:
    return {"state": state, "detail": detail, "outputs": outputs or [], "warnings": warnings or []}


def _validate_train(task: dict, attempt_dir: Path) -> dict:
    from scripts.rl.policy.bundle import checkpoint_counters
    manifest = _read(attempt_dir / MANIFEST_NAME)
    if manifest is None:
        return _result("failed", f"no readable {MANIFEST_NAME}")
    if manifest.get("status") != "completed":
        return _result("failed", f"train manifest status {manifest.get('status')!r}")
    model = attempt_dir / f"{MODEL_BASENAME}.zip"
    if not model.is_file() or Path(manifest.get("model_path") or "").resolve() != model.resolve():
        return _result("failed", f"expected model {model} is not the manifest's final model")
    if sha256_file(model) != manifest.get("model_sha256"):
        return _result("failed", "final model digest differs from the manifest")
    total = int(arg_value(task["args"], "--total-timesteps"))
    try:
        counters = checkpoint_counters(model)
    except Exception as exc:  # BundleError, kept local to avoid importing it at module scope
        return _result("failed", str(exc))
    if not (manifest.get("num_timesteps") == counters["num_timesteps"] == total
            and (manifest.get("hyperparameters") or {}).get("total_timesteps") == total):
        return _result("failed", f"budget/counters differ: requested {total}, manifest "
                                 f"{manifest.get('num_timesteps')}, ZIP {counters['num_timesteps']}")
    missing = [n for n in task["expected_outputs"] if not (attempt_dir / n).is_file()]
    if missing:
        return _result("failed", f"missing outputs {missing}")
    return _result("completed", outputs=_outputs(attempt_dir, task["expected_outputs"]))


def _episode_dirs_local(record, attempt_dir: Path) -> bool:
    """Every referenced episode directory exists inside the attempt (local assets)."""
    dirs = []
    for block in (record.get("policies") or {}).values():
        dirs += [e.get("episode_dir") for e in block.get("episodes") or [] if e.get("episode_dir")]
    dirs += [e.get("episode_dir") for e in record.get("episodes") or [] if isinstance(e, dict)
             and e.get("episode_dir")]
    for raw in dirs:
        path = Path(raw) if Path(raw).is_absolute() else attempt_dir / raw
        try:
            path.resolve().relative_to(attempt_dir.resolve())
        except ValueError:
            return False
        if not path.is_dir():
            return False
    return True


def _validate_operation(task: dict, attempt_dir: Path) -> dict:
    from scripts.rl.policy.operation import ONLINE_MANIFEST_VERSION
    seed = task["identity"].get("seed")
    found, partial = [], False
    for name in task["expected_outputs"]:
        record = _read(attempt_dir / name)
        if record is None:
            return _result("partial" if found else "failed", f"missing {name}")
        status = record.get("status")
        if name == EVAL_MANIFEST:
            if seed is not None and int(seed) not in [int(s) for s in record.get("seeds") or []]:
                return _result("failed", f"{name} does not cover seed {seed}")
            complete = status == "completed" and record.get("episodes_completed") == record.get(
                "episodes_expected")
        else:
            if record.get("online_experiment_version") != ONLINE_MANIFEST_VERSION:
                return _result("failed", f"{name} is not version {ONLINE_MANIFEST_VERSION}")
            if seed is not None and record.get("seed") != seed:
                return _result("failed", f"{name} is for seed {record.get('seed')}, not {seed}")
            protocol = task["identity"].get("protocol")
            if protocol is not None and record.get("protocol") != protocol:
                return _result("failed", f"{name} protocol {record.get('protocol')!r} != {protocol}")
            complete = status == "completed"
        if not complete:
            partial = partial or status == "partial" or bool(found)
            return _result("partial" if partial else "failed", f"{name} status {status!r}")
        if not _episode_dirs_local(record, attempt_dir):
            return _result("partial", f"{name} references episode assets outside the attempt")
        found.append(name)
    extra = [ONLINE_MANIFEST] if (ONLINE_MANIFEST not in found
                                  and (attempt_dir / ONLINE_MANIFEST).is_file()) else []
    for name in extra:
        record = _read(attempt_dir / name) or {}
        if record.get("status") != "completed":
            return _result("partial", f"{name} status {record.get('status')!r}")
    return _result("completed", outputs=_outputs(attempt_dir, found + extra))


def _validate_check(task: dict, attempt_dir: Path) -> dict:
    if not (attempt_dir / CHECK_RESULT).is_file():
        return _result("failed", f"missing {CHECK_RESULT}")
    try:
        from scripts.rl.policy.operation import check_result_passed
    except ImportError as exc:
        return _result("failed", f"check-result reader unavailable "
                                 f"(policy.operation.check_result_passed): {exc}")
    if not check_result_passed(attempt_dir):
        return _result("failed", f"{CHECK_RESULT} does not record a pass")
    return _result("completed", outputs=_outputs(attempt_dir, [CHECK_RESULT]))


def _validate_compare(task: dict, attempt_dir: Path) -> dict:
    from scripts.rl.ops.tasks import _OUTCOMES
    record = _read(attempt_dir / COMPARISON_NAME)
    if record is None:
        return _result("failed", f"no readable {COMPARISON_NAME}")
    status = record.get("status")
    if status not in _OUTCOMES:
        return _result("failed", f"{COMPARISON_NAME} status {status!r}")
    outputs = _outputs(attempt_dir, [COMPARISON_NAME])
    if status == "incomplete":
        return _result("partial", "comparison is incomplete (explicit incomplete view)", outputs)
    return _result("completed", outputs=outputs)


def _validate_report(task: dict, attempt_dir: Path) -> dict:
    missing = [n for n in task["expected_outputs"] if _read(attempt_dir / n) is None]
    if missing:
        return _result("failed", f"missing or unreadable {missing}")
    if task["kind"] == "select":
        receipt = _read(attempt_dir / SELECTION_RECEIPT)
        if not isinstance(receipt.get("selected"), list) or "selection_receipt_version" not in receipt:
            return _result("failed", f"{SELECTION_RECEIPT} lacks selected candidates")
    return _result("completed", outputs=_outputs(attempt_dir, task["expected_outputs"]))


def validate_attempt(task: dict, attempt_dir) -> dict:
    """Kind-specific completion evidence: {state completed|partial|failed, detail, outputs, warnings}.

    Never exit-code-only: the caller combines this with the raw exit code.
    """
    attempt_dir = Path(attempt_dir)
    kind = task["kind"]
    if kind == "train":
        return _validate_train(task, attempt_dir)
    if kind in ("operate", "baseline"):
        return _validate_operation(task, attempt_dir)
    if kind in CHECK_KINDS:
        return _validate_check(task, attempt_dir)
    if kind == "compare":
        return _validate_compare(task, attempt_dir)
    if kind in HANDLER_KINDS:
        return _validate_report(task, attempt_dir)
    return _result("failed", f"no validator for task kind {kind!r}")


def verify_accepted(root, task: dict, receipt: dict) -> list[str]:
    """Problems with a completed receipt's accepted outputs or its pinned binding."""
    problems = []
    attempt = attempt_record(receipt, receipt["accepted_attempt"])
    if attempt is None:
        return ["completed receipt has no accepted attempt"]
    for output in receipt.get("outputs") or []:
        if task.get("attempts") == "projection":
            continue
        if _file_sha(output["path"]) != output["sha256"]:
            problems.append(f"accepted output changed: {output['path']}")
    binding = (receipt.get("inputs") or {}).get("binding")
    if binding and _file_sha(binding["path"]) != binding["sha256"]:
        problems.append(f"model binding changed: {binding['path']}")
    return problems


def lineage(receipt: dict) -> list[dict]:
    """Accepted training history: the accepted attempt, then each recovery parent.

    Each entry is {attempt, attempt_dir, accepted_until}: steps after
    `accepted_until` in a parent are its abandoned tail.
    """
    chain, number, limit = [], receipt["accepted_attempt"], None
    seen = set()
    while number is not None and number not in seen:
        seen.add(number)
        attempt = attempt_record(receipt, number)
        if attempt is None:
            break
        chain.append({"attempt": number, "attempt_dir": attempt["attempt_dir"], "accepted_until": limit})
        resume = attempt.get("resume")
        if not resume:
            break
        number, limit = resume["parent_attempt"], resume["restored_steps"]
    return chain


def _model_for_selector(receipt: dict, checkpoint: str) -> tuple[Path, Path]:
    """(run_dir, model_path) of a checkpoint selector through the accepted lineage."""
    chain = lineage(receipt)
    final = Path(chain[0]["attempt_dir"])
    manifest = _read(final / MANIFEST_NAME) or {}
    if checkpoint == "final":
        return final, final / f"{MODEL_BASENAME}.zip"
    if checkpoint == "best":
        if not manifest.get("best_model_path"):
            raise ValueError("accepted training has no best model")
        return final, Path(manifest["best_model_path"])
    steps = int(checkpoint)
    for entry in chain:
        directory = Path(entry["attempt_dir"])
        if entry["accepted_until"] is not None and steps > entry["accepted_until"]:
            continue
        for item in (_read(directory / MANIFEST_NAME) or {}).get("checkpoints") or []:
            if int(item.get("num_timesteps", -1)) == steps:
                return directory, Path(item["path"])
    raise ValueError(f"checkpoint {steps} is not retained in the accepted training history")


def binding_specs(plan: dict, producer_id: str) -> dict:
    """Distinct binding specs (by file) that consumers declare for one producer."""
    specs = {}
    for task in plan["tasks"]:
        binding = task.get("binding")
        if binding and binding.get("producer") == producer_id:
            specs.setdefault(binding["path"], binding)
    return specs


def write_bindings(root, plan: dict, task: dict, receipt: dict) -> list[str]:
    """Write-once bindings for a completed producer; returns problems, never overwrites."""
    from scripts.rl.policy.bundle import bind_model
    problems = []
    for relative, spec in binding_specs(plan, task["id"]).items():
        path = Path(root) / relative
        try:
            run_dir, model = _model_for_selector(receipt, spec["checkpoint"])
            record = bind_model(run_dir, model)
        except Exception as exc:  # BundleError/ValueError/OSError: the consumer stays unbound
            problems.append(f"binding {relative}: {type(exc).__name__}: {exc}")
            continue
        if path.exists():
            if _read(path) != record:
                problems.append(f"binding {relative} already exists with different content")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, record)
    return problems


def load_binding(root, spec: dict) -> dict:
    """Verified binding record + file hash for a consumer; raises on any defect."""
    from scripts.rl.policy.bundle import read_bound_checkpoint
    path = Path(root) / spec["path"]
    record = _read(path)
    if record is None:
        raise ValueError(f"model binding {path} is missing or unreadable")
    read_bound_checkpoint(record)
    return {"path": str(path), "sha256": sha256_file(path), "record": record}


def _complete_episodes(directory: Path, decisions: int) -> int:
    count = 0
    for path in sorted(directory.glob(f"episode-*/{EPISODE_MANIFEST}")):
        record = _read(path) or {}
        if record.get("status") == "completed" and record.get("steps") == decisions:
            count += 1
    return count


def _int_arg(args, flag):
    value = arg_value(args, flag)
    return None if value is None else int(value)


def _train_settings(plan: dict, task: dict) -> dict:
    args = task["args"]
    decisions = _int_arg(args, "--decisions-per-episode")
    if decisions is None:
        row = next((r for r in plan["rows"] if r["name"] == task["row"]), {})
        decisions = row.get("decisions_per_episode")
    return {"cadence": _int_arg(args, "--checkpoint-every-steps") or 0,
            "total": _int_arg(args, "--total-timesteps"), "n_steps": _int_arg(args, "--n-steps"),
            "seed": _int_arg(args, "--seed"), "decisions": decisions,
            "ini_sha256": plan["inputs"].get((task.get("config_lookup") or {}).get("ini"), {}).get("sha256")}


def verify_checkpoint(task: dict, plan: dict, attempt_dir, entry: dict, restored: int = 0,
                      parent_schema: dict | None = None) -> dict:
    """Verify one retained checkpoint as a safe post-update restart point (task's own cadence)."""
    from scripts.rl.agents.post_update import AFTER_UPDATE_TIMING
    from scripts.rl.policy.bundle import checkpoint_counters
    attempt_dir = Path(attempt_dir)
    settings = _train_settings(plan, task)
    steps = int(entry["num_timesteps"])
    cadence, total, decisions = settings["cadence"], settings["total"], settings["decisions"]
    if cadence <= 0 or steps % cadence:
        raise ValueError(f"{steps} is not on the task's checkpoint cadence {cadence}")
    if not decisions or steps % decisions:
        raise ValueError(f"{steps} is not a complete-episode boundary ({decisions} decisions)")
    if not restored < steps < total:
        raise ValueError(f"{steps} is outside the restorable range ({restored}, {total})")
    path = Path(entry["path"])
    if path.parent.resolve() != (attempt_dir / "checkpoints").resolve() or not path.is_file():
        raise ValueError(f"checkpoint {path} is not a retained file of {attempt_dir}")
    if sha256_file(path) != entry.get("sha256"):
        raise ValueError(f"checkpoint {path} digest differs from the manifest")
    events = (_read(attempt_dir / POST_UPDATE_CHECKPOINTS) or {}).get("events") or []
    event = next((e for e in events if e.get("steps") == steps), None)
    if event is None or event.get("timing") != AFTER_UPDATE_TIMING:
        raise ValueError(f"no '{AFTER_UPDATE_TIMING}' event for {steps} steps")
    counters = checkpoint_counters(path)
    if counters["num_timesteps"] != steps or counters["n_updates"] != event.get("optimizer_epoch_counter"):
        raise ValueError("checkpoint counters disagree with the saved update event")
    if not (counters["optimizer_state_present"] and counters["policy_state_present"]):
        raise ValueError("checkpoint lacks policy or optimizer state")
    manifest = _read(attempt_dir / MANIFEST_NAME) or {}
    hyper = manifest.get("hyperparameters") or {}
    if hyper.get("total_timesteps") != total or (settings["n_steps"] is not None
                                                 and hyper.get("n_steps") != settings["n_steps"]):
        raise ValueError("attempt budget/rollout differ from the task")
    if settings["seed"] is not None and manifest.get("seed") != settings["seed"]:
        raise ValueError("attempt seed differs from the task")
    if settings["ini_sha256"] and (manifest.get("scenario_identity") or {}).get(
            "run_ini_sha256") != settings["ini_sha256"]:
        raise ValueError("attempt run.ini differs from the planned input")
    schema = {k: (manifest.get(k) or {}).get("sha256") for k in ("observation_schema", "reward_schema")}
    if not all(schema.values()):
        raise ValueError("attempt manifest records no model observation/reward schema")
    if parent_schema is not None and schema != parent_schema:
        raise ValueError("attempt model schema differs from its recovery parent")
    episodes = _complete_episodes(attempt_dir, decisions)
    needed = (steps - restored) // decisions
    if episodes < needed:
        raise ValueError(f"only {episodes} complete episodes before checkpoint {steps}; need {needed}")
    return {"path": str(path), "relative": f"checkpoints/{path.name}", "sha256": entry["sha256"],
            "num_timesteps": steps, "n_updates": counters["n_updates"], "event": event,
            "optimizer_state_present": True, "complete_episodes_in_attempt": episodes,
            "episodes_after_checkpoint": episodes - needed, "schema": schema}


def _schema_of(directory) -> dict | None:
    manifest = _read(Path(directory) / MANIFEST_NAME) or {}
    schema = {k: (manifest.get(k) or {}).get("sha256") for k in ("observation_schema", "reward_schema")}
    return schema if all(schema.values()) else None


def train_recovery(plan: dict, task: dict, receipt: dict, execution: dict) -> dict:
    """Proposal entry for interrupted training: resume_checkpoint, accept or blocked."""
    last = receipt["attempts"][-1] if receipt["attempts"] else None
    if last is None:
        return {"action": "pending", "detail": "no attempt was started"}
    attempt_dir = Path(last["attempt_dir"])
    if validate_attempt(task, attempt_dir)["state"] == "completed":
        return {"action": "accept", "attempt": last["attempt"],
                "detail": "the interrupted attempt finished with a valid final manifest"}
    if execution.get("recovery") != "checkpoint":
        return {"action": "blocked", "detail": "execution.recovery is 'none'; restart review needed"}
    if "--curriculum-schedule" in task["args"]:
        return {"action": "blocked", "detail": "curriculum training has no checkpoint recovery"}
    settings = _train_settings(plan, task)
    manifest = _read(attempt_dir / MANIFEST_NAME) or {}
    resume = last.get("resume")
    if (int(manifest.get("num_timesteps") or 0) >= settings["total"]
            or (attempt_dir / f"{MODEL_BASENAME}.zip").exists()):
        return {"action": "blocked", "detail": "terminal budget reached without a completed final "
                                               "manifest; review finalization before any restart"}
    parent_schema = _schema_of(resume["parent_dir"]) if resume else None
    restored = resume["restored_steps"] if resume else 0
    errors = []
    entries = sorted(manifest.get("checkpoints") or [], key=lambda e: -int(e.get("num_timesteps", 0)))
    for entry in entries:
        try:
            chosen = verify_checkpoint(task, plan, attempt_dir, entry, restored, parent_schema)
        except Exception as exc:  # each defect disqualifies only this checkpoint
            errors.append(f"{entry.get('num_timesteps')}: {exc}")
            continue
        return resume_entry(plan, task, receipt, chosen, last["attempt"], attempt_dir, last, manifest)
    if resume:
        # Interrupted before its own first checkpoint: the recovery parent remains the restart point.
        parent = attempt_record(receipt, resume["parent_attempt"])
        parent_restored = (parent.get("resume") or {}).get("restored_steps", 0) if parent else 0
        grand = (parent.get("resume") or {}).get("parent_dir") if parent else None
        checkpoint = resume["checkpoint"]
        try:
            chosen = verify_checkpoint(task, plan, resume["parent_dir"], checkpoint, parent_restored,
                                       _schema_of(grand) if grand else None)
        except Exception as exc:
            return {"action": "blocked", "detail": f"recovery parent checkpoint no longer verifies: {exc}"}
        entry = resume_entry(plan, task, receipt, chosen, resume["parent_attempt"],
                             resume["parent_dir"], last, manifest)
        return {**entry, "detail": "no newer verified checkpoint; reusing the previous recovery parent"}
    return {"action": "blocked", "detail": "no verified post-update checkpoint"
            + (f" ({'; '.join(errors)})" if errors else "") + "; never restarted from zero"}


def resume_entry(plan, task, receipt, checkpoint, parent_attempt, parent_dir, last, manifest) -> dict:
    """Restored/remaining decisions, accepted episode ranges along the lineage, excluded tail."""
    settings = _train_settings(plan, task)
    decisions, steps = settings["decisions"], checkpoint["num_timesteps"]
    ranges, number, upto = [], parent_attempt, steps
    while number is not None:
        record = attempt_record(receipt, number)
        start = ((record or {}).get("resume") or {}).get("restored_steps", 0)
        ranges.insert(0, {"attempt": number, "first_episode": start // decisions + 1,
                          "last_episode": upto // decisions})
        parent = (record or {}).get("resume")
        number, upto = (parent["parent_attempt"], start) if parent else (None, None)
    own = last["attempt"] == parent_attempt
    return {"action": "resume_checkpoint", "parent_attempt": parent_attempt,
            "parent_dir": str(parent_dir), "checkpoint": checkpoint, "restored_steps": steps,
            "restored_decisions": steps, "remaining_decisions": settings["total"] - steps,
            "accepted_episode_ranges": ranges,
            "excluded_tail": {"attempt": last["attempt"],
                              "after_steps": steps if own else (last.get("resume") or {}).get(
                                  "restored_steps", steps),
                              "last_recorded_steps": int(manifest.get("num_timesteps") or 0),
                              "complete_episodes_excluded": checkpoint["episodes_after_checkpoint"]
                              if own else _complete_episodes(Path(last["attempt_dir"]), decisions)},
            "args": resume_train_args(task["args"], parent_dir, checkpoint["relative"])}


def _has_content(directory) -> bool:
    path = Path(directory)
    return path.is_dir() and any(path.iterdir())


def build_proposal(root, plan: dict, execution: dict, sim_binary: str | None,
                   live: dict | None = None) -> dict:
    """The entire recovery proposal, computed read-only before anything changes.

    `live` maps task ids to descriptions of still-running owned processes.
    """
    root = Path(root)
    live = live or {}
    tasks, blockers = {}, []
    for task in plan["tasks"]:
        try:
            receipt = read_receipt(root, task)
        except MalformedReceipt as exc:
            tasks[task["id"]] = {"action": "blocked", "state_before": None, "detail": str(exc)}
            blockers.append(f"{task['id']}: {exc}")
            continue
        if receipt is None:
            if _has_content(task["output_dir"]):
                tasks[task["id"]] = {"action": "blocked", "state_before": None,
                                     "detail": f"{task['output_dir']} exists without a receipt"}
            else:
                tasks[task["id"]] = {"action": "pending", "state_before": None}
            continue
        state = receipt["state"]
        entry = {"state_before": state}
        if task["id"] in live:
            entry.update(action="blocked", detail=f"owned processes still running: {live[task['id']]}")
            blockers.append(f"{task['id']}: still running")
        elif state == "completed":
            problems = verify_accepted(root, task, receipt)
            entry.update(action="blocked", detail="; ".join(problems)) if problems else \
                entry.update(action="keep", accepted_attempt=receipt["accepted_attempt"])
        elif state in ("interrupted", "running"):
            if task["kind"] == "train":
                entry.update(train_recovery(plan, task, receipt, execution))
            else:
                entry.update(action="retry", detail="interrupted; a new attempt of this task only")
        elif state in ("pending", "skipped_dependency"):
            entry.update(action="pending")
        else:
            entry.update(action="keep", detail=receipt.get("detail"))
        tasks[task["id"]] = entry
    identity = _file_sha(identity_path(root))
    content = {"batch_recovery_version": BATCH_RECOVERY_VERSION,
               "plan_sha256": _file_sha(root / PLAN_NAME), "runtime_identity_sha256": identity,
               "recovery": execution.get("recovery"),
               "sim_binary": {"path": sim_binary, "recorded": json.loads(
                   identity_path(root).read_text())["sim_binary"] if identity else None},
               "receipts": {t["id"]: _file_sha(receipt_path(root, t)) for t in plan["tasks"]},
               "tasks": tasks, "blockers": blockers}
    summary = {}
    for entry in tasks.values():
        summary[entry["action"]] = summary.get(entry["action"], 0) + 1
    return {**content, "proposal_id": canonical_sha256(content)[:16], "summary": summary}


def save_proposal(root, proposal: dict) -> Path:
    """Write a proposal once; an identical repeat keeps the existing file untouched."""
    path = Path(root) / RECOVERY_DIR / f"{proposal['proposal_id']}.json"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {**proposal, "created_at": now_iso()})
    return path


def apply_proposal(root, plan: dict, proposal: dict) -> None:
    """Turn proposal actions into receipt states; attempts and old directories are untouched."""
    by_id = {t["id"]: t for t in plan["tasks"]}
    for task_id, entry in proposal["tasks"].items():
        task = by_id[task_id]
        try:
            receipt = read_receipt(root, task)
        except MalformedReceipt:
            continue
        if receipt is None:
            continue
        action = entry["action"]
        if action == "retry" or (action == "pending" and receipt["state"] != "pending"):
            receipt.update(state="pending", detail=f"recovery {proposal['proposal_id']}: {action}")
            receipt.pop("next_resume", None)
        elif action == "resume_checkpoint":
            receipt.update(state="pending", detail=f"recovery {proposal['proposal_id']}: resume from "
                                                   f"{entry['checkpoint']['path']}")
            receipt["next_resume"] = {k: entry[k] for k in (
                "parent_attempt", "parent_dir", "checkpoint", "restored_steps", "restored_decisions",
                "remaining_decisions", "accepted_episode_ranges", "excluded_tail", "args")}
            receipt["next_resume"]["proposal"] = proposal["proposal_id"]
        elif action == "accept":
            attempt = attempt_record(receipt, entry["attempt"])
            result = validate_attempt(task, attempt["attempt_dir"])
            attempt.update(state="completed", outputs=result["outputs"],
                           detail="accepted at recovery: valid final manifest")
            receipt.update(state="completed", accepted_attempt=entry["attempt"], outputs=result["outputs"],
                           detail=attempt["detail"])
            write_receipt(root, receipt)
            problems = write_bindings(root, plan, task, receipt)
            if problems:
                receipt["warnings"] = receipt["warnings"] + problems
        elif action == "blocked" and receipt["state"] != "blocked":
            if receipt["state"] == "completed":
                receipt["invalidated"] = receipt.get("invalidated", []) + [
                    {"attempt": receipt["accepted_attempt"], "problems": [entry.get("detail")],
                     "at": now_iso()}]
                receipt["accepted_attempt"] = None
            receipt.update(state="blocked", detail=entry.get("detail"))
        else:
            continue
        write_receipt(root, receipt)


def _print_proposal(path: Path, proposal: dict) -> None:
    print(f"Recovery proposal {proposal['proposal_id']}: {path}", flush=True)
    for action, count in sorted(proposal["summary"].items()):
        print(f"  {action}  {count}")
    for task_id, entry in proposal["tasks"].items():
        if entry["action"] in ("resume_checkpoint", "blocked", "retry", "accept"):
            detail = entry.get("detail") or ""
            if entry["action"] == "resume_checkpoint":
                detail = (f"from {entry['checkpoint']['relative']} of attempt {entry['parent_attempt']}; "
                          f"restored {entry['restored_decisions']}, remaining {entry['remaining_decisions']}")
            print(f"  {task_id}: {entry['action']} {detail}".rstrip())
    for blocker in proposal["blockers"]:
        print(f"  blocker: {blocker}", file=sys.stderr)


def prepare_resume(output_root: str, sim_binary: str | None, execution: dict, prepare_only: bool,
                   *, worker_command=None) -> int:
    """Plan section 6.2: lock, verify, propose the whole recovery, then (unless prepare-only) run."""
    from scripts.rl.ops import local
    root = Path(output_root).resolve()
    try:
        with local.root_lock(root):
            plan = load_batch_plan(root)
            check_identity(root, sim_binary)
            live = local.live_owned(root, plan)
            if live and not prepare_only:
                local.reap_owned(root, plan)
                live = local.live_owned(root, plan)
            proposal = build_proposal(root, plan, execution, sim_binary, live)
            path = save_proposal(root, proposal)
            _print_proposal(path, proposal)
            if prepare_only:
                return 0
            if live:
                print("owned processes are still running; nothing was resumed", file=sys.stderr)
                return 1
            apply_proposal(root, plan, proposal)
            return local.run_locked(root, plan, execution, command="resume", sim_binary=sim_binary,
                                    proposal=str(path.relative_to(root)),
                                    worker_command=worker_command)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


__all__ = ["RUNTIME_IDENTITY_VERSION", "BATCH_STEP_VERSION", "BATCH_RECOVERY_VERSION", "STATES",
           "IdentityChanged", "MalformedReceipt", "runtime_identity", "ensure_identity",
           "check_identity", "read_receipt", "write_receipt", "new_receipt", "validate_attempt",
           "verify_accepted", "lineage", "write_bindings", "load_binding", "verify_checkpoint",
           "train_recovery", "build_proposal", "save_proposal", "apply_proposal", "prepare_resume"]
