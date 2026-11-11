"""Read task receipts, verify accepted outputs, and bind checkpoints."""

import json
from pathlib import Path

from scripts.artifact_io import now_iso, sha256_file, write_json
from scripts.rl.cli_common import MANIFEST_NAME, MODEL_BASENAME
from scripts.rl.experiments.plan import (
    CHECK_RESULT,
    COMPARISON_NAME,
    EVAL_MANIFEST,
    ONLINE_MANIFEST,
    SELECTION_RECEIPT,
)
from scripts.rl.ops.batch_identity import (
    _file_sha,
)
from scripts.rl.ops.tasks import arg_value

BATCH_STEP_VERSION = 1


STEPS_DIR = "state/steps"


STATES = (
    "pending",
    "running",
    "completed",
    "partial",
    "failed",
    "interrupted",
    "blocked",
    "skipped_dependency",
    "skipped_selection",
)


ACTIVE = ("pending", "running")


CHECK_KINDS = ("preflight", "replay_gate", "reward_audit")


HANDLER_KINDS = ("select", "curves", "review", "index")


_RECEIPT_FIELDS = (
    "batch_step_version",
    "task_id",
    "task_key",
    "kind",
    "identity",
    "inputs",
    "state",
    "attempts",
    "accepted_attempt",
    "warnings",
    "created_at",
    "updated_at",
)


class MalformedReceipt(ValueError):
    """A receipt exists but cannot be trusted; it is never overwritten."""


def receipt_path(root, task: dict) -> Path:
    return Path(root) / STEPS_DIR / f"{task['key']}.json"


def new_receipt(task: dict, plan: dict) -> dict:
    stamp = now_iso()
    return {
        "batch_step_version": BATCH_STEP_VERSION,
        "task_id": task["id"],
        "task_key": task["key"],
        "kind": task["kind"],
        "identity": task["identity"],
        "inputs": {
            "files": {
                p: plan["inputs"][p]["sha256"]
                for p in task.get("inputs") or []
                if p in plan["inputs"]
            },
            "binding": None,
            "selection": task.get("selection"),
        },
        "state": "pending",
        "detail": None,
        "exit_code": None,
        "warnings": [],
        "logs": [],
        "attempts": [],
        "accepted_attempt": None,
        "outputs": [],
        "invalidated": [],
        "created_at": stamp,
        "updated_at": stamp,
    }


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
    if accepted is not None and not any(
        a.get("attempt") == accepted for a in receipt["attempts"]
    ):
        raise MalformedReceipt(
            f"{path} points at a missing accepted attempt {accepted}"
        )
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
    return [
        {"path": str(attempt_dir / n), "sha256": sha256_file(attempt_dir / n)}
        for n in names
        if (attempt_dir / n).is_file()
    ]


def _result(state, detail=None, outputs=None, warnings=None) -> dict:
    return {
        "state": state,
        "detail": detail,
        "outputs": outputs or [],
        "warnings": warnings or [],
    }


def _validate_train(task: dict, attempt_dir: Path) -> dict:
    from scripts.rl.policy.bundle import checkpoint_counters

    manifest = _read(attempt_dir / MANIFEST_NAME)
    if manifest is None:
        return _result("failed", f"no readable {MANIFEST_NAME}")
    if manifest.get("status") != "completed":
        return _result("failed", f"train manifest status {manifest.get('status')!r}")
    model = attempt_dir / f"{MODEL_BASENAME}.zip"
    if (
        not model.is_file()
        or Path(manifest.get("model_path") or "").resolve() != model.resolve()
    ):
        return _result(
            "failed", f"expected model {model} is not the manifest's final model"
        )
    if sha256_file(model) != manifest.get("model_sha256"):
        return _result("failed", "final model digest differs from the manifest")
    total = int(arg_value(task["args"], "--total-timesteps"))
    try:
        counters = checkpoint_counters(model)
    except (
        Exception
    ) as exc:  # BundleError, kept local to avoid importing it at module scope
        return _result("failed", str(exc))
    if not (
        manifest.get("num_timesteps") == counters["num_timesteps"] == total
        and (manifest.get("hyperparameters") or {}).get("total_timesteps") == total
    ):
        return _result(
            "failed",
            f"budget/counters differ: requested {total}, manifest "
            f"{manifest.get('num_timesteps')}, ZIP {counters['num_timesteps']}",
        )
    missing = [n for n in task["expected_outputs"] if not (attempt_dir / n).is_file()]
    if missing:
        return _result("failed", f"missing outputs {missing}")
    return _result("completed", outputs=_outputs(attempt_dir, task["expected_outputs"]))


def _episode_dirs_local(record, attempt_dir: Path) -> bool:
    """Every referenced episode directory exists inside the attempt (local assets)."""
    dirs = []
    for block in (record.get("policies") or {}).values():
        dirs += [
            e.get("episode_dir")
            for e in block.get("episodes") or []
            if e.get("episode_dir")
        ]
    dirs += [
        e.get("episode_dir")
        for e in record.get("episodes") or []
        if isinstance(e, dict) and e.get("episode_dir")
    ]
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
            if seed is not None and int(seed) not in [
                int(s) for s in record.get("seeds") or []
            ]:
                return _result("failed", f"{name} does not cover seed {seed}")
            complete = status == "completed" and record.get(
                "episodes_completed"
            ) == record.get("episodes_expected")
        else:
            if record.get("online_experiment_version") != ONLINE_MANIFEST_VERSION:
                return _result(
                    "failed", f"{name} is not version {ONLINE_MANIFEST_VERSION}"
                )
            if seed is not None and record.get("seed") != seed:
                return _result(
                    "failed", f"{name} is for seed {record.get('seed')}, not {seed}"
                )
            protocol = task["identity"].get("protocol")
            if protocol is not None and record.get("protocol") != protocol:
                return _result(
                    "failed",
                    f"{name} protocol {record.get('protocol')!r} != {protocol}",
                )
            complete = status == "completed"
        if not complete:
            partial = partial or status == "partial" or bool(found)
            return _result(
                "partial" if partial else "failed", f"{name} status {status!r}"
            )
        if not _episode_dirs_local(record, attempt_dir):
            return _result(
                "partial", f"{name} references episode assets outside the attempt"
            )
        found.append(name)
    extra = (
        [ONLINE_MANIFEST]
        if (ONLINE_MANIFEST not in found and (attempt_dir / ONLINE_MANIFEST).is_file())
        else []
    )
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
        return _result(
            "failed",
            f"check-result reader unavailable "
            f"(policy.operation.check_result_passed): {exc}",
        )
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
        return _result(
            "partial", "comparison is incomplete (explicit incomplete view)", outputs
        )
    return _result("completed", outputs=outputs)


def _validate_report(task: dict, attempt_dir: Path) -> dict:
    missing = [n for n in task["expected_outputs"] if _read(attempt_dir / n) is None]
    if missing:
        return _result("failed", f"missing or unreadable {missing}")
    if task["kind"] == "select":
        receipt = _read(attempt_dir / SELECTION_RECEIPT)
        if (
            not isinstance(receipt.get("selected"), list)
            or "selection_receipt_version" not in receipt
        ):
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
        chain.append(
            {
                "attempt": number,
                "attempt_dir": attempt["attempt_dir"],
                "accepted_until": limit,
            }
        )
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
    raise ValueError(
        f"checkpoint {steps} is not retained in the accepted training history"
    )


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
        except (
            Exception
        ) as exc:  # BundleError/ValueError/OSError: the consumer stays unbound
            problems.append(f"binding {relative}: {type(exc).__name__}: {exc}")
            continue
        if path.exists():
            if _read(path) != record:
                problems.append(
                    f"binding {relative} already exists with different content"
                )
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


def _has_content(directory) -> bool:
    path = Path(directory)
    return path.is_dir() and any(path.iterdir())
