"""Read and write the versioned result of a policy operation check."""

import json
from pathlib import Path

from scripts.artifact_io import now_iso, write_json

CHECK_RESULT_NAME = "check_result.json"
CHECK_RESULT_VERSION = 1
CHECK_KINDS = ("preflight", "replay_gate", "reward_audit")


def write_check_result(output_dir, *, check_id, kind, passed, evidence, warnings):
    """Write the versioned ``check_result.json`` that a check task's receipt validates."""
    if kind not in CHECK_KINDS:
        raise ValueError(f"unknown check kind {kind!r}")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    record = dict(
        check_result_version=CHECK_RESULT_VERSION,
        check_id=check_id,
        kind=kind,
        status="passed" if passed else "failed",
        passed=bool(passed),
        evidence=evidence,
        warnings=list(warnings),
        written_at=now_iso(),
    )
    write_json(output / CHECK_RESULT_NAME, record)
    return record


def check_result_passed(attempt_dir):
    """The success test for a check attempt; False for a missing, malformed or unpassed result."""
    path = Path(attempt_dir) / CHECK_RESULT_NAME
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if not (
        isinstance(record, dict)
        and record.get("check_result_version") == CHECK_RESULT_VERSION
        and record.get("kind") in CHECK_KINDS
        and isinstance(record.get("check_id"), str)
        and record.get("passed") is True
        and record.get("status") == "passed"
        and isinstance(record.get("evidence"), dict)
    ):
        return False
    if record["kind"] == "replay_gate":
        from scripts.rl.policy.replay_gate import gate_passed

        return gate_passed(attempt_dir)
    return True
