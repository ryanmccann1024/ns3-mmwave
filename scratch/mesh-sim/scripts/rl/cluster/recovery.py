"""Recover scheduler intents and record checked human assertions."""

import sys
from datetime import datetime, timedelta

from scripts.rl.cluster import receipts, reconcile, slurm


def _history_start(element):
    created = element.get("created_at")
    if not created:
        return "1970-01-01"
    # Include the prior date so UTC/local midnight cannot hide a submission.
    return (datetime.fromisoformat(created) - timedelta(days=1)).date().isoformat()


def _recover_intents(output_root, entries: list[dict]) -> list[dict]:
    """Look no-ID intents up by exact job name; write an ID back only when unambiguous."""
    receipts.require_owner(entries)
    for intent in reconcile.unresolved_intents(entries):
        receipt = next(entry for entry in entries
                       if entry["submission"] == intent["submission"])
        path = receipts.path_for(output_root, intent["submission"])
        element = reconcile.element_of(receipt, intent["role"])
        found = slurm.find_jobs_by_name(intent["job_name"], receipt["user"],
                                       _history_start(element))
        label = f"submission {intent['submission']} {intent['role']}"
        # One exact match is a positive observation even when the other query failed.
        if len(found["job_ids"]) == 1:
            receipts.mark_recovered(path, receipt, intent["role"], found["job_ids"][0])
            print(f"{label}: recovered job id {found['job_ids'][0]} by job name")
        elif found["job_ids"]:
            print(f"{label}: job name matches {found['job_ids']}; too ambiguous to "
                  "record an id", file=sys.stderr)
        elif not found["ok"]:
            print(f"{label}: the job-name query failed ({found['error']}); the intent "
                  "stays unresolved and blocks resubmission", file=sys.stderr)
        else:
            print(f"{label}: no job carries job name {intent['job_name']}; an empty "
                  "query is not proof that sbatch failed, so the intent stays "
                  "unresolved", file=sys.stderr)
    return receipts.load(output_root)


def _assert_inactive_job(output_root, entries: list[dict], snapshot: dict,
                         job_id: str) -> None:
    receipts.require_owner(entries)
    holders = [entry for entry in entries
               if str(entry.get("job_id")) == job_id
               or str((entry.get("compare") or {}).get("job_id")) == job_id]
    if not holders:
        raise ValueError(f"--inactive-job {job_id}: no receipt holds that job id")
    for receipt in holders:
        active = (reconcile.active_elements(receipt, snapshot)
                  if str(receipt.get("job_id")) == job_id else
                  reconcile.active_compare(receipt, snapshot))
        if active:
            raise ValueError(f"--inactive-job {job_id}: the scheduler still shows this "
                          "job as active")
        entry = receipts.add_assertion(
            receipts.path_for(output_root, receipt["submission"]), receipt,
            {"kind": "inactive_job", "job_id": job_id})
        print(f"recorded: {receipt['submission']} job {job_id} asserted inactive by "
              f"{entry['user']} at {entry['asserted_at']}")


def _abandon_intent(output_root, entries: list[dict], token: str) -> None:
    receipts.require_owner(entries)
    submission, _, role = token.partition(":")
    if role not in ("tasks", "compare"):
        raise ValueError(f"--abandon-intent {token}: expected NNNN:tasks or NNNN:compare")
    receipt = next((entry for entry in entries if entry["submission"] == submission),
                   None)
    if receipt is None:
        raise ValueError(f"--abandon-intent {token}: no receipt {submission}")
    element = reconcile.element_of(receipt, role)
    if element is None or element.get("state") not in reconcile.UNRESOLVED_STATES \
            or element.get("job_id"):
        raise ValueError(f"--abandon-intent {token}: that submission is not an "
                      "unresolved no-ID intent")
    found = slurm.find_jobs_by_name(element["job_name"], receipt["user"],
                                   _history_start(element))
    if found["job_ids"]:
        raise ValueError(f"--abandon-intent {token}: job name {element['job_name']} "
                      f"matches {found['job_ids']}; it did reach the scheduler")
    path = receipts.path_for(output_root, submission)
    entry = receipts.add_assertion(path, receipt,
                                   {"kind": "abandon_intent", "role": role,
                                    "job_name": element["job_name"],
                                    "queried": found["ok"]})
    receipts.mark_abandoned(path, receipt, role)
    print(f"recorded: {submission} {role} intent abandoned by {entry['user']} at "
          f"{entry['asserted_at']} (searched job name {element['job_name']})")
