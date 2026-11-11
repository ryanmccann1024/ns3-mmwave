"""Verify post-update checkpoints and propose recovery for interrupted batches."""

import json
import sys
from pathlib import Path

from scripts.artifact_io import canonical_sha256, now_iso, sha256_file, write_json
from scripts.rl.cli_common import MANIFEST_NAME, MODEL_BASENAME
from scripts.rl.experiments.plan import (
    PLAN_NAME,
    POST_UPDATE_CHECKPOINTS,
    load_batch_plan,
)
from scripts.rl.ops.batch_identity import (
    RUNTIME_IDENTITY_NAME as RUNTIME_IDENTITY_NAME,
)
from scripts.rl.ops.batch_identity import (
    RUNTIME_IDENTITY_VERSION as RUNTIME_IDENTITY_VERSION,
)
from scripts.rl.ops.batch_identity import (
    IdentityChanged as IdentityChanged,
)
from scripts.rl.ops.batch_identity import (
    _file_sha as _file_sha,
)
from scripts.rl.ops.batch_identity import (
    check_identity as check_identity,
)
from scripts.rl.ops.batch_identity import (
    ensure_identity as ensure_identity,
)
from scripts.rl.ops.batch_identity import (
    identity_path as identity_path,
)
from scripts.rl.ops.batch_identity import (
    python_sources as python_sources,
)
from scripts.rl.ops.batch_identity import (
    registry_identity as registry_identity,
)
from scripts.rl.ops.batch_identity import (
    runtime_identity as runtime_identity,
)
from scripts.rl.ops.batch_receipts import (
    ACTIVE as ACTIVE,
)
from scripts.rl.ops.batch_receipts import (
    BATCH_STEP_VERSION as BATCH_STEP_VERSION,
)
from scripts.rl.ops.batch_receipts import (
    CHECK_KINDS as CHECK_KINDS,
)
from scripts.rl.ops.batch_receipts import (
    HANDLER_KINDS as HANDLER_KINDS,
)
from scripts.rl.ops.batch_receipts import (
    STATES as STATES,
)
from scripts.rl.ops.batch_receipts import (
    STEPS_DIR as STEPS_DIR,
)
from scripts.rl.ops.batch_receipts import (
    MalformedReceipt as MalformedReceipt,
)
from scripts.rl.ops.batch_receipts import (
    _has_content as _has_content,
)
from scripts.rl.ops.batch_receipts import (
    _read as _read,
)
from scripts.rl.ops.batch_receipts import (
    accepted_dir as accepted_dir,
)
from scripts.rl.ops.batch_receipts import (
    attempt_record as attempt_record,
)
from scripts.rl.ops.batch_receipts import (
    binding_specs as binding_specs,
)
from scripts.rl.ops.batch_receipts import (
    lineage as lineage,
)
from scripts.rl.ops.batch_receipts import (
    load_binding as load_binding,
)
from scripts.rl.ops.batch_receipts import (
    new_receipt as new_receipt,
)
from scripts.rl.ops.batch_receipts import (
    read_receipt as read_receipt,
)
from scripts.rl.ops.batch_receipts import (
    receipt_path as receipt_path,
)
from scripts.rl.ops.batch_receipts import (
    validate_attempt as validate_attempt,
)
from scripts.rl.ops.batch_receipts import (
    verify_accepted as verify_accepted,
)
from scripts.rl.ops.batch_receipts import (
    write_bindings as write_bindings,
)
from scripts.rl.ops.batch_receipts import (
    write_receipt as write_receipt,
)
from scripts.rl.ops.tasks import arg_value, resume_train_args

BATCH_RECOVERY_VERSION = 1


RECOVERY_DIR = "state/recovery"


EPISODE_MANIFEST = "rl_episode.json"


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
    return {
        "cadence": _int_arg(args, "--checkpoint-every-steps") or 0,
        "total": _int_arg(args, "--total-timesteps"),
        "n_steps": _int_arg(args, "--n-steps"),
        "seed": _int_arg(args, "--seed"),
        "decisions": decisions,
        "ini_sha256": plan["inputs"]
        .get((task.get("config_lookup") or {}).get("ini"), {})
        .get("sha256"),
    }


def verify_checkpoint(
    task: dict,
    plan: dict,
    attempt_dir,
    entry: dict,
    restored: int = 0,
    parent_schema: dict | None = None,
) -> dict:
    """Verify one retained checkpoint as a safe post-update restart point (task's own cadence)."""
    from scripts.rl.agents.post_update import AFTER_UPDATE_TIMING
    from scripts.rl.policy.bundle import checkpoint_counters

    attempt_dir = Path(attempt_dir)
    settings = _train_settings(plan, task)
    steps = int(entry["num_timesteps"])
    cadence, total, decisions = (
        settings["cadence"],
        settings["total"],
        settings["decisions"],
    )
    if cadence <= 0 or steps % cadence:
        raise ValueError(f"{steps} is not on the task's checkpoint cadence {cadence}")
    if not decisions or steps % decisions:
        raise ValueError(
            f"{steps} is not a complete-episode boundary ({decisions} decisions)"
        )
    if not restored < steps < total:
        raise ValueError(
            f"{steps} is outside the restorable range ({restored}, {total})"
        )
    path = Path(entry["path"])
    if (
        path.parent.resolve() != (attempt_dir / "checkpoints").resolve()
        or not path.is_file()
    ):
        raise ValueError(f"checkpoint {path} is not a retained file of {attempt_dir}")
    if sha256_file(path) != entry.get("sha256"):
        raise ValueError(f"checkpoint {path} digest differs from the manifest")
    events = (_read(attempt_dir / POST_UPDATE_CHECKPOINTS) or {}).get("events") or []
    event = next((e for e in events if e.get("steps") == steps), None)
    if event is None or event.get("timing") != AFTER_UPDATE_TIMING:
        raise ValueError(f"no '{AFTER_UPDATE_TIMING}' event for {steps} steps")
    counters = checkpoint_counters(path)
    if counters["num_timesteps"] != steps or counters["n_updates"] != event.get(
        "optimizer_epoch_counter"
    ):
        raise ValueError("checkpoint counters disagree with the saved update event")
    if not (counters["optimizer_state_present"] and counters["policy_state_present"]):
        raise ValueError("checkpoint lacks policy or optimizer state")
    manifest = _read(attempt_dir / MANIFEST_NAME) or {}
    hyper = manifest.get("hyperparameters") or {}
    if hyper.get("total_timesteps") != total or (
        settings["n_steps"] is not None and hyper.get("n_steps") != settings["n_steps"]
    ):
        raise ValueError("attempt budget/rollout differ from the task")
    if settings["seed"] is not None and manifest.get("seed") != settings["seed"]:
        raise ValueError("attempt seed differs from the task")
    if (
        settings["ini_sha256"]
        and (manifest.get("scenario_identity") or {}).get("run_ini_sha256")
        != settings["ini_sha256"]
    ):
        raise ValueError("attempt run.ini differs from the planned input")
    schema = {
        k: (manifest.get(k) or {}).get("sha256")
        for k in ("observation_schema", "reward_schema")
    }
    if not all(schema.values()):
        raise ValueError("attempt manifest records no model observation/reward schema")
    if parent_schema is not None and schema != parent_schema:
        raise ValueError("attempt model schema differs from its recovery parent")
    episodes = _complete_episodes(attempt_dir, decisions)
    needed = (steps - restored) // decisions
    if episodes < needed:
        raise ValueError(
            f"only {episodes} complete episodes before checkpoint {steps}; need {needed}"
        )
    return {
        "path": str(path),
        "relative": f"checkpoints/{path.name}",
        "sha256": entry["sha256"],
        "num_timesteps": steps,
        "n_updates": counters["n_updates"],
        "event": event,
        "optimizer_state_present": True,
        "complete_episodes_in_attempt": episodes,
        "episodes_after_checkpoint": episodes - needed,
        "schema": schema,
    }


def _schema_of(directory) -> dict | None:
    manifest = _read(Path(directory) / MANIFEST_NAME) or {}
    schema = {
        k: (manifest.get(k) or {}).get("sha256")
        for k in ("observation_schema", "reward_schema")
    }
    return schema if all(schema.values()) else None


def train_recovery(plan: dict, task: dict, receipt: dict, execution: dict) -> dict:
    """Proposal entry for interrupted training: resume_checkpoint, accept or blocked."""
    last = receipt["attempts"][-1] if receipt["attempts"] else None
    if last is None:
        return {"action": "pending", "detail": "no attempt was started"}
    attempt_dir = Path(last["attempt_dir"])
    if validate_attempt(task, attempt_dir)["state"] == "completed":
        return {
            "action": "accept",
            "attempt": last["attempt"],
            "detail": "the interrupted attempt finished with a valid final manifest",
        }
    if execution.get("recovery") != "checkpoint":
        return {
            "action": "blocked",
            "detail": "execution.recovery is 'none'; restart review needed",
        }
    if "--curriculum-schedule" in task["args"]:
        return {
            "action": "blocked",
            "detail": "curriculum training has no checkpoint recovery",
        }
    settings = _train_settings(plan, task)
    manifest = _read(attempt_dir / MANIFEST_NAME) or {}
    resume = last.get("resume")
    if (
        int(manifest.get("num_timesteps") or 0) >= settings["total"]
        or (attempt_dir / f"{MODEL_BASENAME}.zip").exists()
    ):
        return {
            "action": "blocked",
            "detail": "terminal budget reached without a completed final "
            "manifest; review finalization before any restart",
        }
    parent_schema = _schema_of(resume["parent_dir"]) if resume else None
    restored = resume["restored_steps"] if resume else 0
    errors = []
    entries = sorted(
        manifest.get("checkpoints") or [], key=lambda e: -int(e.get("num_timesteps", 0))
    )
    for entry in entries:
        try:
            chosen = verify_checkpoint(
                task, plan, attempt_dir, entry, restored, parent_schema
            )
        except Exception as exc:  # each defect disqualifies only this checkpoint
            errors.append(f"{entry.get('num_timesteps')}: {exc}")
            continue
        return resume_entry(
            plan, task, receipt, chosen, last["attempt"], attempt_dir, last, manifest
        )
    if resume:
        # Interrupted before its own first checkpoint: the recovery parent remains the restart point.
        parent = attempt_record(receipt, resume["parent_attempt"])
        parent_restored = (
            (parent.get("resume") or {}).get("restored_steps", 0) if parent else 0
        )
        grand = (parent.get("resume") or {}).get("parent_dir") if parent else None
        checkpoint = resume["checkpoint"]
        try:
            chosen = verify_checkpoint(
                task,
                plan,
                resume["parent_dir"],
                checkpoint,
                parent_restored,
                _schema_of(grand) if grand else None,
            )
        except Exception as exc:
            return {
                "action": "blocked",
                "detail": f"recovery parent checkpoint no longer verifies: {exc}",
            }
        entry = resume_entry(
            plan,
            task,
            receipt,
            chosen,
            resume["parent_attempt"],
            resume["parent_dir"],
            last,
            manifest,
        )
        return {
            **entry,
            "detail": "no newer verified checkpoint; reusing the previous recovery parent",
        }
    return {
        "action": "blocked",
        "detail": "no verified post-update checkpoint"
        + (f" ({'; '.join(errors)})" if errors else "")
        + "; never restarted from zero",
    }


def resume_entry(
    plan, task, receipt, checkpoint, parent_attempt, parent_dir, last, manifest
) -> dict:
    """Restored/remaining decisions, accepted episode ranges along the lineage, excluded tail."""
    settings = _train_settings(plan, task)
    decisions, steps = settings["decisions"], checkpoint["num_timesteps"]
    ranges, number, upto = [], parent_attempt, steps
    while number is not None:
        record = attempt_record(receipt, number)
        start = ((record or {}).get("resume") or {}).get("restored_steps", 0)
        ranges.insert(
            0,
            {
                "attempt": number,
                "first_episode": start // decisions + 1,
                "last_episode": upto // decisions,
            },
        )
        parent = (record or {}).get("resume")
        number, upto = (parent["parent_attempt"], start) if parent else (None, None)
    own = last["attempt"] == parent_attempt
    return {
        "action": "resume_checkpoint",
        "parent_attempt": parent_attempt,
        "parent_dir": str(parent_dir),
        "checkpoint": checkpoint,
        "restored_steps": steps,
        "restored_decisions": steps,
        "remaining_decisions": settings["total"] - steps,
        "accepted_episode_ranges": ranges,
        "excluded_tail": {
            "attempt": last["attempt"],
            "after_steps": steps
            if own
            else (last.get("resume") or {}).get("restored_steps", steps),
            "last_recorded_steps": int(manifest.get("num_timesteps") or 0),
            "complete_episodes_excluded": checkpoint["episodes_after_checkpoint"]
            if own
            else _complete_episodes(Path(last["attempt_dir"]), decisions),
        },
        "args": resume_train_args(task["args"], parent_dir, checkpoint["relative"]),
    }


def build_proposal(
    root, plan: dict, execution: dict, sim_binary: str | None, live: dict | None = None
) -> dict:
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
            tasks[task["id"]] = {
                "action": "blocked",
                "state_before": None,
                "detail": str(exc),
            }
            blockers.append(f"{task['id']}: {exc}")
            continue
        if receipt is None:
            if _has_content(task["output_dir"]):
                tasks[task["id"]] = {
                    "action": "blocked",
                    "state_before": None,
                    "detail": f"{task['output_dir']} exists without a receipt",
                }
            else:
                tasks[task["id"]] = {"action": "pending", "state_before": None}
            continue
        state = receipt["state"]
        entry = {"state_before": state}
        if task["id"] in live:
            entry.update(
                action="blocked",
                detail=f"owned processes still running: {live[task['id']]}",
            )
            blockers.append(f"{task['id']}: still running")
        elif state == "completed":
            problems = verify_accepted(root, task, receipt)
            entry.update(
                action="blocked", detail="; ".join(problems)
            ) if problems else entry.update(
                action="keep", accepted_attempt=receipt["accepted_attempt"]
            )
        elif state in ("interrupted", "running"):
            if task["kind"] == "train":
                entry.update(train_recovery(plan, task, receipt, execution))
            else:
                entry.update(
                    action="retry",
                    detail="interrupted; a new attempt of this task only",
                )
        elif state in ("pending", "skipped_dependency"):
            entry.update(action="pending")
        else:
            entry.update(action="keep", detail=receipt.get("detail"))
        tasks[task["id"]] = entry
    identity = _file_sha(identity_path(root))
    content = {
        "batch_recovery_version": BATCH_RECOVERY_VERSION,
        "plan_sha256": _file_sha(root / PLAN_NAME),
        "runtime_identity_sha256": identity,
        "recovery": execution.get("recovery"),
        "sim_binary": {
            "path": sim_binary,
            "recorded": json.loads(identity_path(root).read_text())["sim_binary"]
            if identity
            else None,
        },
        "receipts": {t["id"]: _file_sha(receipt_path(root, t)) for t in plan["tasks"]},
        "tasks": tasks,
        "blockers": blockers,
    }
    summary = {}
    for entry in tasks.values():
        summary[entry["action"]] = summary.get(entry["action"], 0) + 1
    return {
        **content,
        "proposal_id": canonical_sha256(content)[:16],
        "summary": summary,
    }


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
            receipt.update(
                state="pending", detail=f"recovery {proposal['proposal_id']}: {action}"
            )
            receipt.pop("next_resume", None)
        elif action == "resume_checkpoint":
            receipt.update(
                state="pending",
                detail=f"recovery {proposal['proposal_id']}: resume from "
                f"{entry['checkpoint']['path']}",
            )
            receipt["next_resume"] = {
                k: entry[k]
                for k in (
                    "parent_attempt",
                    "parent_dir",
                    "checkpoint",
                    "restored_steps",
                    "restored_decisions",
                    "remaining_decisions",
                    "accepted_episode_ranges",
                    "excluded_tail",
                    "args",
                )
            }
            receipt["next_resume"]["proposal"] = proposal["proposal_id"]
        elif action == "accept":
            attempt = attempt_record(receipt, entry["attempt"])
            result = validate_attempt(task, attempt["attempt_dir"])
            if result["state"] != "completed":
                receipt.update(state="blocked", detail=result["detail"])
                write_receipt(root, receipt)
                continue
            attempt.update(
                state="completed",
                outputs=result["outputs"],
                detail="accepted at recovery: valid final manifest",
            )
            receipt.update(
                state="completed",
                accepted_attempt=entry["attempt"],
                outputs=result["outputs"],
                detail=attempt["detail"],
            )
            # Publish completion after the bindings. A retry can verify any
            # binding written before an interruption without overwriting it.
            problems = write_bindings(root, plan, task, receipt)
            if problems:
                receipt["warnings"] = receipt["warnings"] + problems
        elif action == "blocked" and receipt["state"] != "blocked":
            if receipt["state"] == "completed":
                receipt["invalidated"] = receipt.get("invalidated", []) + [
                    {
                        "attempt": receipt["accepted_attempt"],
                        "problems": [entry.get("detail")],
                        "at": now_iso(),
                    }
                ]
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
                detail = (
                    f"from {entry['checkpoint']['relative']} of attempt {entry['parent_attempt']}; "
                    f"restored {entry['restored_decisions']}, remaining {entry['remaining_decisions']}"
                )
            print(f"  {task_id}: {entry['action']} {detail}".rstrip())
    for blocker in proposal["blockers"]:
        print(f"  blocker: {blocker}", file=sys.stderr)


def prepare_resume(
    output_root: str,
    sim_binary: str | None,
    execution: dict,
    prepare_only: bool,
    *,
    worker_command=None,
) -> int:
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
                print(
                    "owned processes are still running; nothing was resumed",
                    file=sys.stderr,
                )
                return 1
            apply_proposal(root, plan, proposal)
            return local.run_locked(
                root,
                plan,
                execution,
                command="resume",
                sim_binary=sim_binary,
                proposal=str(path.relative_to(root)),
                worker_command=worker_command,
            )
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


__all__ = [
    "RUNTIME_IDENTITY_VERSION",
    "BATCH_STEP_VERSION",
    "BATCH_RECOVERY_VERSION",
    "STATES",
    "IdentityChanged",
    "MalformedReceipt",
    "runtime_identity",
    "ensure_identity",
    "check_identity",
    "read_receipt",
    "write_receipt",
    "new_receipt",
    "validate_attempt",
    "verify_accepted",
    "lineage",
    "write_bindings",
    "load_binding",
    "verify_checkpoint",
    "train_recovery",
    "build_proposal",
    "save_proposal",
    "apply_proposal",
    "prepare_resume",
]
