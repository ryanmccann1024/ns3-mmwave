"""Own local batch locks, process groups and shared worker slots."""

import fcntl
import json
import os
import signal
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from scripts.artifact_io import now_iso, write_json
from scripts.rl.ops import batch_receipts
from scripts.rl.ops.process import STOP_WAIT_S

RESOURCE_POOL_VERSION = 1


LOCK_NAME = "campaign.lock"


LOCAL_DIR = "local"


POOL_RECORD = "pool.json"


POOL_PROGRESS_INTERVAL_S = 30.0


@contextmanager
def root_lock(root):
    """Refuse a second supervisor for the same output root."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / LOCK_NAME).open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"another batch supervisor is using {root}") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def lock_held(root) -> bool:
    """Whether a supervisor holds the root lock; read-only probe."""
    path = Path(root) / LOCK_NAME
    if not path.is_file():
        return False
    with path.open("r") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
    return False


def _pool_dir(pool: dict) -> Path:
    return Path(pool.get("path") or pool["directory"])


def register_pool(pool: dict) -> None:
    """Record the pool capacity under the pool lock; a conflicting capacity is refused."""
    directory = _pool_dir(pool)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "pool.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        record_path = directory / POOL_RECORD
        record = json.loads(record_path.read_text()) if record_path.is_file() else None
        if record is None:
            write_json(
                record_path,
                {
                    "resource_pool_version": RESOURCE_POOL_VERSION,
                    "capacity": pool["capacity"],
                    "created_at": now_iso(),
                },
            )
        elif record.get("capacity") != pool["capacity"]:
            raise RuntimeError(
                f"resource pool {directory} has capacity {record.get('capacity')}, "
                f"this batch declares {pool['capacity']}; use one capacity"
            )


def _group_members(pgid: int) -> list[tuple[int, str]]:
    try:
        # An attempt path can be longer than the default width when ps is piped.
        result = subprocess.run(
            [
                "ps",
                "-ww",
                "-A",
                "-o",
                "pid=",
                "-o",
                "pgid=",
                "-o",
                "stat=",
                "-o",
                "command=",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    members = []
    for line in result.stdout.splitlines():
        fields = line.split(None, 3)
        if len(fields) == 4:
            pid, group, state, command = fields
            # Zombies have already released their inherited pool descriptors.
            if pid.isdigit() and group == str(pgid) and not state.startswith("Z"):
                members.append((int(pid), command))
    return members


def owned_group_alive(pgid: int | None, marker: str) -> bool:
    """A process group that still has a member whose command line names `marker`."""
    if not pgid:
        return False
    return any(marker in command for _, command in _group_members(pgid))


def reap_group(pgid: int, marker: str, timeout: float = STOP_WAIT_S) -> bool:
    """Stop a verified owned group (TERM, then KILL); unverified groups are left alone."""
    if not owned_group_alive(pgid, marker):
        return False
    for signum in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, signum)
        except (ProcessLookupError, PermissionError):
            pass
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and _group_members(pgid):
            time.sleep(0.05)
        if not _group_members(pgid):
            return True
    return not _group_members(pgid)


def lease_path(root, task: dict, attempt: int) -> Path:
    return Path(root) / LOCAL_DIR / task["key"] / f"attempt-{attempt}.lease.json"


def _owned_processes(root, task: dict, attempt: dict) -> list[tuple[int, str]]:
    """Live (pgid, marker) groups recorded for an attempt and verified by command line."""
    found = []
    worker = attempt.get("worker") or {}
    if worker.get("pgid") and owned_group_alive(worker["pgid"], task["id"]):
        found.append((worker["pgid"], task["id"]))
    lease = batch_receipts._read(lease_path(root, task, attempt["attempt"])) or {}
    if lease.get("child_pgid") and owned_group_alive(
        lease["child_pgid"], attempt["attempt_dir"]
    ):
        found.append((lease["child_pgid"], attempt["attempt_dir"]))
    return found


def live_owned(root, plan: dict) -> dict:
    """Task id -> description of owned processes still alive for its running attempts."""
    live = {}
    for task in plan["tasks"]:
        try:
            receipt = batch_receipts.read_receipt(root, task)
        except batch_receipts.MalformedReceipt:
            continue
        if not receipt or receipt["state"] != "running" or not receipt["attempts"]:
            continue
        groups = _owned_processes(root, task, receipt["attempts"][-1])
        if groups:
            live[task["id"]] = ", ".join(f"pgid {g}" for g, _ in groups)
    return live


def reap_owned(root, plan: dict) -> None:
    """Orphan reconciliation: verify and reap descendants of a crashed supervisor's attempts."""
    for task in plan["tasks"]:
        try:
            receipt = batch_receipts.read_receipt(root, task)
        except batch_receipts.MalformedReceipt:
            continue
        if receipt and receipt["state"] == "running" and receipt["attempts"]:
            for pgid, marker in _owned_processes(root, task, receipt["attempts"][-1]):
                reap_group(pgid, marker)


@contextmanager
def pool_slot(pool: dict | None, owner: dict, poll_s: float = 0.25):
    """Hold one slot of a shared pool for this process; yields the slot's open lock file.

    The OS lock lives as long as an open descriptor does: pass it to the child
    so a crashed worker cannot free a slot its child still uses. A previous
    holder's recorded child group, if still alive and verified, is reaped first.
    """
    if pool is None:
        yield None
        return
    register_pool(pool)
    directory = _pool_dir(pool)
    chosen, last = None, 0.0
    try:
        while chosen is None:
            for index in range(pool["capacity"]):
                handle = (directory / f"slot-{index}.lock").open("a+")
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    handle.close()
                    continue
                previous = batch_receipts._read(directory / f"slot-{index}.json") or {}
                if previous.get("child_pgid") and previous.get("attempt_dir"):
                    reap_group(previous["child_pgid"], previous["attempt_dir"])
                chosen = (index, handle)
                break
            if chosen is None:
                if time.monotonic() - last > POOL_PROGRESS_INTERVAL_S:
                    print(
                        f"{owner.get('task_id')}: waiting for a shared pool slot "
                        f"(capacity {pool['capacity']})",
                        flush=True,
                    )
                    last = time.monotonic()
                time.sleep(poll_s)
        index, handle = chosen
        record_path = directory / f"slot-{index}.json"
        write_json(
            record_path,
            {**owner, "slot": index, "pid": os.getpid(), "acquired_at": now_iso()},
        )
        yield handle
    finally:
        if chosen is not None:
            (directory / f"slot-{chosen[0]}.json").unlink(missing_ok=True)
            chosen[1].close()


def record_slot_child(
    pool: dict | None, handle, child_pgid: int, attempt_dir: str
) -> None:
    """Note the child group on the held slot so a later holder can reconcile an orphan."""
    if pool is None or handle is None:
        return
    directory = _pool_dir(pool)
    for path in directory.glob("slot-*.json"):
        record = batch_receipts._read(path) or {}
        if record.get("pid") == os.getpid():
            write_json(
                path, {**record, "child_pgid": child_pgid, "attempt_dir": attempt_dir}
            )
