"""The local scheduler for plan v3 batches: root lock, bounded DAG dispatch and status.

One supervisor per output root (`campaign.lock`). Each process task runs as a
worker (`python -m scripts.rl.ops.run_task --step <id> --attempt <A>`) in its
own process group with thread limits and niceness; the worker holds an optional
shared pool slot while its child runs. Handler tasks run in the supervisor.
Receipts are written only here; identity, validators and bindings come from
`ops/recovery.py`.
"""

import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from scripts.artifact_io import now_iso, sha256_file, write_json
from scripts.rl.experiments.plan import PLAN_NAME, SELECTION_RECEIPT, load_batch_plan
from scripts.rl.ops import recovery
from scripts.rl.ops.measurement import PsError, parse_ps, read_ps, tree_usage
from scripts.rl.ops.process import STOP_WAIT_S, stop_group
from scripts.sim_support import find_mesh_root

CAMPAIGN_VERSION = 2
RESOURCE_POOL_VERSION = 1
STATUS_NAME = "campaign_status.json"
LOCK_NAME = "campaign.lock"
RESOURCES_NAME = "resources.jsonl"
LOCAL_DIR = "local"
POOL_RECORD = "pool.json"
PROGRESS_INTERVAL_S = 30.0
POLL_S = 0.2
THREAD_VARIABLES = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS")
BATCH_STATES = ("completed", "completed_with_warnings", "failed", "interrupted", "running")
_SUCCESS = ("completed", "skipped_selection")
_FAILURES = ("failed", "partial", "blocked")


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
            write_json(record_path, {"resource_pool_version": RESOURCE_POOL_VERSION,
                                     "capacity": pool["capacity"], "created_at": now_iso()})
        elif record.get("capacity") != pool["capacity"]:
            raise RuntimeError(f"resource pool {directory} has capacity {record.get('capacity')}, "
                               f"this batch declares {pool['capacity']}; use one capacity")


def _group_members(pgid: int) -> list[tuple[int, str]]:
    try:
        result = subprocess.run(["ps", "-A", "-o", "pid=,pgid=,command="], capture_output=True,
                                text=True)
    except OSError:
        return []
    members = []
    for line in result.stdout.splitlines():
        fields = line.split(None, 2)
        if len(fields) >= 2 and fields[1].isdigit() and int(fields[1]) == pgid:
            members.append((int(fields[0]), fields[2] if len(fields) > 2 else ""))
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
    lease = recovery._read(lease_path(root, task, attempt["attempt"])) or {}
    if lease.get("child_pgid") and owned_group_alive(lease["child_pgid"], attempt["attempt_dir"]):
        found.append((lease["child_pgid"], attempt["attempt_dir"]))
    return found


def live_owned(root, plan: dict) -> dict:
    """Task id -> description of owned processes still alive for its running attempts."""
    live = {}
    for task in plan["tasks"]:
        try:
            receipt = recovery.read_receipt(root, task)
        except recovery.MalformedReceipt:
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
            receipt = recovery.read_receipt(root, task)
        except recovery.MalformedReceipt:
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
                previous = recovery._read(directory / f"slot-{index}.json") or {}
                if previous.get("child_pgid") and previous.get("attempt_dir"):
                    reap_group(previous["child_pgid"], previous["attempt_dir"])
                chosen = (index, handle)
                break
            if chosen is None:
                if time.monotonic() - last > PROGRESS_INTERVAL_S:
                    print(f"{owner.get('task_id')}: waiting for a shared pool slot "
                          f"(capacity {pool['capacity']})", flush=True)
                    last = time.monotonic()
                time.sleep(poll_s)
        index, handle = chosen
        record_path = directory / f"slot-{index}.json"
        write_json(record_path, {**owner, "slot": index, "pid": os.getpid(), "acquired_at": now_iso()})
        yield handle
    finally:
        if chosen is not None:
            (directory / f"slot-{chosen[0]}.json").unlink(missing_ok=True)
            chosen[1].close()


def record_slot_child(pool: dict | None, handle, child_pgid: int, attempt_dir: str) -> None:
    """Note the child group on the held slot so a later holder can reconcile an orphan."""
    if pool is None or handle is None:
        return
    directory = _pool_dir(pool)
    for path in directory.glob("slot-*.json"):
        record = recovery._read(path) or {}
        if record.get("pid") == os.getpid():
            write_json(path, {**record, "child_pgid": child_pgid, "attempt_dir": attempt_dir})


def derive_state(counts: dict, warnings: bool, interrupted: bool) -> str:
    if interrupted or counts.get("interrupted"):
        return "interrupted"
    if sum(counts.values()) == sum(counts.get(s, 0) for s in _SUCCESS):
        return "completed_with_warnings" if warnings else "completed"
    return "failed"


def _worker_command(root: Path, task: dict, attempt: int) -> list[str]:
    return [sys.executable, "-m", "scripts.rl.ops.run_task", "--output-root", str(root),
            "--step", task["id"], "--attempt", str(attempt)]


class _Batch:
    def __init__(self, root: Path, plan: dict, execution: dict, command: str, sim_binary,
                 proposal, worker_command):
        self.root, self.plan, self.execution = root, plan, execution
        self.command, self.sim_binary, self.proposal = command, sim_binary, proposal
        self.worker_command = worker_command or _worker_command
        self.tasks = plan["tasks"]
        self.by_id = {t["id"]: t for t in self.tasks}
        self.receipts, self.states, self.details = {}, {}, {}
        self.running = {}
        self.signal = None
        self.stop_dispatch = False
        self.refusal = None
        self.started = now_iso()
        self.last_progress = time.monotonic()
        self.env = dict(os.environ)
        self.env.update({name: str(execution["threads_per_worker"]) for name in THREAD_VARIABLES})
        self.env["PYTHONUNBUFFERED"] = "1"

    def load(self) -> None:
        for task in self.tasks:
            tid = task["id"]
            try:
                receipt = recovery.read_receipt(self.root, task)
            except recovery.MalformedReceipt as exc:
                self.receipts[tid], self.states[tid], self.details[tid] = None, "blocked", str(exc)
                continue
            if receipt is None:
                receipt = recovery.new_receipt(task, self.plan)
                if recovery._has_content(task["output_dir"]) and task.get("attempts") != "projection":
                    receipt.update(state="blocked",
                                   detail=f"{task['output_dir']} exists without a receipt")
                recovery.write_receipt(self.root, receipt)
            elif receipt["state"] == "running":
                last = receipt["attempts"][-1] if receipt["attempts"] else None
                if last:
                    last.update(state="interrupted", ended_at=last.get("ended_at") or now_iso(),
                                detail="supervisor ended while running")
                receipt.update(state="interrupted", detail="supervisor ended while running")
                recovery.write_receipt(self.root, receipt)
            elif receipt["state"] == "completed":
                problems = recovery.verify_accepted(self.root, task, receipt)
                if problems:
                    receipt["invalidated"] = receipt.get("invalidated", []) + [
                        {"attempt": receipt["accepted_attempt"], "problems": problems, "at": now_iso()}]
                    receipt.update(state="blocked", accepted_attempt=None, detail="; ".join(problems))
                    recovery.write_receipt(self.root, receipt)
            if receipt["state"] == "skipped_dependency":
                receipt["state"] = "pending"
            self.receipts[tid] = receipt
            self.states[tid] = receipt["state"]
            self.details[tid] = receipt.get("detail")

    def _set(self, task, state, detail=None, write=True) -> None:
        tid = task["id"]
        self.states[tid], self.details[tid] = state, detail
        receipt = self.receipts.get(tid)
        if receipt is not None and write:
            receipt.update(state=state, detail=detail)
            recovery.write_receipt(self.root, receipt)

    def counts(self) -> dict:
        counts = {state: 0 for state in recovery.STATES}
        for state in self.states.values():
            counts[state] += 1
        return counts

    def warnings(self) -> bool:
        return any(r and r.get("state") == "completed" and r.get("warnings")
                   for r in self.receipts.values())

    def write_status(self, state: str) -> None:
        path = self.root / STATUS_NAME
        previous = recovery._read(path) or {}
        invocations = previous.get("invocations") or []
        invocation = {"command": self.command, "started_at": self.started, "pid": os.getpid(),
                      "host": socket.gethostname(), "execution": self.execution,
                      "sim_binary": self.sim_binary, "recovery_proposal": self.proposal}
        if not invocations or invocations[-1].get("started_at") != self.started \
                or invocations[-1].get("pid") != os.getpid():
            invocations.append(invocation)
        else:
            invocations[-1] = invocation
        counts = self.counts()
        write_json(path, {
            "campaign_version": CAMPAIGN_VERSION, "state": state, "updated_at": now_iso(),
            "plan": {"path": str(self.root / PLAN_NAME), "sha256": sha256_file(self.root / PLAN_NAME)},
            "runtime_identity": recovery.RUNTIME_IDENTITY_NAME, "counts": counts,
            "incomplete": sorted(t for t, s in self.states.items() if s not in _SUCCESS),
            "blocked": sorted(t for t, s in self.states.items() if s == "blocked"),
            "execution": self.execution, "invocations": invocations,
            "refusal": self.refusal, "recovery_proposal": self.proposal,
            "receipts": {t["id"]: f"{recovery.STEPS_DIR}/{t['key']}.json" for t in self.tasks}})

    def _selected(self, task) -> tuple[str, str | None]:
        """ready|wait|skip for the task's selection branch."""
        selection = task.get("selection")
        if not selection:
            return "ready", None
        state = self.states[selection["task"]]
        if state in recovery.ACTIVE:
            return "wait", None
        if state != "completed":
            return "skip_dep", f"selection {selection['task']} is {state}"
        directory = recovery.accepted_dir(self.receipts[selection["task"]])
        receipt = recovery._read(Path(directory) / SELECTION_RECEIPT) or {}
        if selection["branch"] not in (receipt.get("selected") or []):
            return "skip_sel", f"branch {selection['branch']} was not selected"
        return "ready", None

    def readiness(self, task) -> tuple[str, str | None]:
        verdict = self._selected(task)
        if verdict[0] != "ready":
            return verdict
        states = [self.states[n] for n in task["needs"]]
        if any(s in recovery.ACTIVE for s in states):
            return "wait", None
        if task.get("needs_policy") == "completed":
            bad = [n for n in task["needs"] if self.states[n] != "completed"]
            if bad:
                return "skip_dep", f"needs not completed: {', '.join(bad[:5])}"
        return "ready", None

    def accepted_map(self) -> dict:
        return {tid: recovery.accepted_dir(r) for tid, r in self.receipts.items()}

    def accepted_info(self) -> dict:
        return {t["id"]: {"state": self.states[t["id"]],
                          "attempt_dir": recovery.accepted_dir(self.receipts.get(t["id"])),
                          "receipt": str(recovery.receipt_path(self.root, t)),
                          "warnings": (self.receipts.get(t["id"]) or {}).get("warnings") or []}
                for t in self.tasks}

    def _next_attempt(self, task, receipt) -> int:
        numbers = [a["attempt"] for a in receipt["attempts"]]
        out = Path(task["output_dir"])
        if out.is_dir():
            numbers += [int(p.name.split("-", 1)[1]) for p in out.glob("attempt-*")
                        if p.name.split("-", 1)[1].isdigit()]
        logs = self.root / LOCAL_DIR / task["key"]
        if logs.is_dir():
            numbers += [int(p.stem.split("-", 1)[1].split(".")[0]) for p in logs.glob("attempt-*.log")
                        if p.stem.split("-", 1)[1].split(".")[0].isdigit()]
        return max(numbers, default=0) + 1

    def _prepare_inputs(self, task, receipt) -> dict:
        """Pinned binding and accepted sources; raises ValueError to block the task."""
        inputs = {"binding": None, "accepted": {}, "accepted_dirs": None}
        spec = task.get("binding")
        if spec and spec.get("producer"):
            binding = recovery.load_binding(self.root, spec)
            pinned = receipt["inputs"].get("binding")
            if pinned and pinned["sha256"] != binding["sha256"]:
                raise ValueError(f"model binding {binding['path']} changed after this task pinned it")
            receipt["inputs"]["binding"] = {"path": binding["path"], "sha256": binding["sha256"]}
            inputs["binding"] = {"path": binding["path"], "sha256": binding["sha256"]}
        accepted = self.accepted_map()
        for arg in task.get("args") or []:
            if arg.startswith("{accepted_dir:") and arg.endswith("}"):
                source = arg[len("{accepted_dir:"):-1]
                if not accepted.get(source):
                    raise ValueError(f"source {source} has no accepted attempt")
                inputs["accepted"][source] = accepted[source]
        return inputs

    def dispatch(self, task) -> None:
        tid = task["id"]
        receipt = self.receipts[tid]
        try:
            inputs = self._prepare_inputs(task, receipt)
        except Exception as exc:  # binding/verification errors block only this task
            self._set(task, "blocked", f"{type(exc).__name__}: {exc}")
            return
        number = self._next_attempt(task, receipt)
        projection = task.get("attempts") == "projection"
        attempt_dir = Path(task["output_dir"]) if projection else Path(task["output_dir"]) / f"attempt-{number}"
        try:
            attempt_dir.mkdir(parents=True, exist_ok=projection)
        except OSError as exc:
            self._set(task, "blocked", f"cannot create a new attempt directory: {exc}")
            return
        log = self.root / LOCAL_DIR / task["key"] / f"attempt-{number}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        resume = receipt.pop("next_resume", None)
        attempt = {"attempt": number, "attempt_dir": str(attempt_dir), "log": str(log),
                   "state": "running", "started_at": now_iso(), "ended_at": None, "exit_code": None,
                   "worker": None, "resume": resume, "inputs": inputs,
                   "resource_pool": self.execution.get("resource_pool"),
                   "sim_binary": self.sim_binary, "outputs": [], "warnings": [], "detail": None}
        receipt["attempts"].append(attempt)
        receipt["logs"] = receipt.get("logs", []) + [str(log)]
        self._set(task, "running", None)
        if task.get("handler"):
            self.run_handler(task, receipt, attempt)
            return
        if task["kind"] == "compare":
            try:
                attempt["inputs"]["accepted_dirs"] = self.comparison_view(task, attempt)
            except Exception as exc:  # missing reporting owner or incompatible view
                self.finish(task, attempt, None, failure=f"comparison view: {type(exc).__name__}: {exc}")
                return
            recovery.write_receipt(self.root, receipt)
        nice = int(self.execution.get("nice") or 0)
        try:
            with log.open("ab") as handle:
                process = subprocess.Popen(self.worker_command(self.root, task, number),
                                           cwd=str(find_mesh_root()), env=self.env,
                                           stdin=subprocess.DEVNULL, stdout=handle,
                                           stderr=subprocess.STDOUT, start_new_session=True,
                                           preexec_fn=(lambda: os.nice(nice)) if nice else None)
        except OSError as exc:
            self.finish(task, attempt, None, failure=f"worker launch failed: {exc}")
            return
        attempt["worker"] = {"pid": process.pid, "pgid": process.pid}
        recovery.write_receipt(self.root, receipt)
        self.running[tid] = {"process": process, "attempt": attempt, "started": time.monotonic()}
        print(f"{tid}: started attempt {number}", flush=True)

    def comparison_view(self, task, attempt) -> list[str]:
        from scripts.rl.experiments.reporting import build_comparison_view
        dirs = build_comparison_view({**task, "attempt_dir": attempt["attempt_dir"]}, self.plan,
                                     str(self.root), self.accepted_info())
        if not dirs:
            raise ValueError("no evaluation directories in the comparison view")
        return [str(d) for d in dirs]

    def run_handler(self, task, receipt, attempt) -> None:
        attempt_dir = Path(attempt["attempt_dir"])
        try:
            if task["handler"] == "select":
                from scripts.rl.experiments.selection import select
                rule = task["selection_rule"]
                evidence = {}
                if rule["rule"] != "replay":
                    from scripts.rl.experiments.reporting import selection_evidence
                    evidence = selection_evidence(task, self.plan, str(self.root), self.accepted_info())
                result = select(rule, evidence)
                write_json(attempt_dir / SELECTION_RECEIPT, result)
                summary = {"selected": result["selected"]}
            else:
                from scripts.rl.experiments.reporting import run_report_task
                summary = run_report_task({**task, "attempt_dir": str(attempt_dir)}, self.plan,
                                          str(self.root), self.accepted_info()) or {}
        except Exception as exc:  # a handler failure fails this task only
            with open(attempt["log"], "a") as log:
                log.write(f"{task['id']} handler {task['handler']} failed: {type(exc).__name__}: {exc}\n")
            self.finish(task, attempt, None, failure=f"{task['handler']}: {type(exc).__name__}: {exc}")
            return
        with open(attempt["log"], "a") as log:
            log.write(f"{task['id']} handler {task['handler']}: {json.dumps(summary, default=str)}\n")
        attempt["handler_result"] = summary if isinstance(summary, dict) else {"result": str(summary)}
        attempt["sources"] = {n: {"receipt": str(recovery.receipt_path(self.root, self.by_id[n])),
                                  "sha256": recovery._file_sha(recovery.receipt_path(self.root, self.by_id[n])),
                                  "state": self.states[n]} for n in task["needs"]}
        warnings = list((summary or {}).get("warnings") or []) if isinstance(summary, dict) else []
        if isinstance(summary, dict) and summary.get("incomplete"):
            warnings.append("report labeled incomplete")
        self.finish(task, attempt, 0, extra_warnings=warnings)

    def finish(self, task, attempt, code, interrupted=False, failure=None, extra_warnings=()) -> None:
        receipt = self.receipts[task["id"]]
        attempt.update(exit_code=code, ended_at=now_iso())
        receipt["exit_code"] = code
        warnings = list(extra_warnings)
        if interrupted:
            state, detail = "interrupted", f"stopped by signal (exit {code})"
            outputs = []
        elif failure:
            state, detail, outputs = "failed", failure, []
        else:
            result = recovery.validate_attempt(task, attempt["attempt_dir"])
            outputs = result["outputs"]
            tolerated = code in task["exit_codes"]
            if tolerated and result["state"] == "completed":
                state, detail = "completed", None
                if code:
                    warnings.append(f"exit {code}: warning (health counters, seed overlap or "
                                    "not held out)")
            elif result["state"] == "partial":
                state, detail = "partial", f"exit {code}; {result['detail']}"
            else:
                state = "failed"
                detail = f"exit {code}" + (f"; {result['detail']}" if result["detail"] else "")
            warnings += result["warnings"]
        attempt.update(state=state, detail=detail, outputs=outputs, warnings=warnings)
        if state == "completed":
            receipt.update(accepted_attempt=attempt["attempt"], outputs=outputs,
                           warnings=warnings)
        recovery.write_receipt(self.root, receipt)
        if state == "completed" and task["kind"] == "train":
            problems = recovery.write_bindings(self.root, self.plan, task, receipt)
            if problems:
                receipt["warnings"] = receipt["warnings"] + problems
        self._set(task, state, detail)
        print(f"{task['id']}: {state}" + (f" ({detail})" if detail else ""), flush=True)
        if state in _FAILURES and self.execution["failure_policy"] == "stop":
            self.stop_dispatch = True

    def poll(self) -> None:
        for tid, entry in list(self.running.items()):
            code = entry["process"].poll()
            if code is None:
                continue
            del self.running[tid]
            task = self.by_id[tid]
            self._reap_leftovers(task, entry["attempt"])
            self.finish(task, entry["attempt"], code)

    def _reap_leftovers(self, task, attempt) -> None:
        for pgid, marker in _owned_processes(self.root, task, attempt):
            reap_group(pgid, marker)

    def stop_all(self) -> None:
        for entry in self.running.values():
            try:
                os.killpg(entry["process"].pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        deadline = time.monotonic() + 2 * STOP_WAIT_S + 2
        while time.monotonic() < deadline and any(e["process"].poll() is None for e in self.running.values()):
            time.sleep(0.05)
        for tid, entry in list(self.running.items()):
            stop_group(entry["process"])
            self._reap_leftovers(self.by_id[tid], entry["attempt"])
            self.finish(self.by_id[tid], entry["attempt"], entry["process"].returncode, interrupted=True)
        self.running.clear()

    def progress(self, force=False) -> None:
        if not force and time.monotonic() - self.last_progress < PROGRESS_INTERVAL_S:
            return
        self.last_progress = time.monotonic()
        counts = {k: v for k, v in self.counts().items() if v}
        print(f"[{now_iso()}] " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), flush=True)
        try:
            table = parse_ps(read_ps()) if self.running else {}
            error = None
        except PsError as exc:
            table, error = {}, str(exc)
        lines = []
        for tid, entry in self.running.items():
            elapsed = int(time.monotonic() - entry["started"])
            print(f"  {tid}: running {elapsed}s (attempt {entry['attempt']['attempt']})", flush=True)
            sample = {"time": now_iso(), "task_id": tid, "attempt": entry["attempt"]["attempt"],
                      "pid": entry["process"].pid, "elapsed_s": elapsed}
            sample.update({"error": error} if error else tree_usage(table, entry["process"].pid))
            lines.append(json.dumps(sample, sort_keys=True))
        if lines:
            with (self.root / RESOURCES_NAME).open("a") as handle:
                handle.write("\n".join(lines) + "\n")

    def dispatch_ready(self) -> bool:
        changed = False
        for task in self.tasks:
            tid = task["id"]
            if self.states[tid] != "pending":
                continue
            verdict, detail = self.readiness(task)
            if verdict == "skip_dep":
                self._set(task, "skipped_dependency", detail)
                changed = True
            elif verdict == "skip_sel":
                self._set(task, "skipped_selection", detail)
                changed = True
            elif verdict == "ready" and not self.stop_dispatch and len(self.running) < self.execution["workers"]:
                try:
                    recovery.check_identity(self.root, self.sim_binary)
                except recovery.IdentityChanged as exc:
                    self.refusal = str(exc)
                    self.stop_dispatch = True
                    print(f"refused before dispatching {tid}: {exc}", file=sys.stderr, flush=True)
                    return changed
                self.dispatch(task)
                changed = True
                if self.signal:
                    return changed
        return changed

    def run(self) -> int:
        previous = {sig: signal.signal(sig, self._on_signal) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            self.write_status("running")
            try:
                while True:
                    if self.signal:
                        self.stop_all()
                        break
                    self.poll()
                    changed = self.dispatch_ready()
                    if changed:
                        self.write_status("running")
                    if not self.running and not changed:
                        break
                    self.progress()
                    time.sleep(POLL_S)
            except BaseException:
                # Never leave owned workers behind an unexpected supervisor error.
                self.signal = self.signal or signal.SIGTERM
                self.stop_all()
                self.write_status("interrupted")
                raise
            self.progress(force=True)
            state = derive_state(self.counts(), self.warnings(), self.signal is not None)
            if self.refusal and state.startswith("completed"):
                state = "failed"
            self.write_status(state)
            print(f"Batch {state}", flush=True)
            return 130 if state == "interrupted" else 0 if state.startswith("completed") else 1
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)

    def _on_signal(self, signum, frame) -> None:
        self.signal = signum


def run_locked(root, plan: dict, execution: dict, *, command: str = "run", sim_binary=None,
               proposal=None, worker_command=None) -> int:
    """Run eligible tasks with the root lock already held by the caller."""
    root = Path(root)
    try:
        recovery.ensure_identity(root, plan, sim_binary)
        if execution.get("resource_pool"):
            register_pool(execution["resource_pool"])
    except (recovery.IdentityChanged, RuntimeError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    reap_owned(root, plan)
    batch = _Batch(root, plan, execution, command, sim_binary, proposal, worker_command)
    batch.load()
    return batch.run()


def run_batch(output_root: str, execution: dict, *, worker_command=None) -> int:
    """Run a plan v3 root's pending tasks; 0 completed, 130 interrupted, 1 otherwise."""
    root = Path(output_root).resolve()
    try:
        plan = load_batch_plan(root)
        with root_lock(root):
            return run_locked(root, plan, execution, worker_command=worker_command)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def batch_status(output_root: str) -> dict:
    """Read-only state of a plan v3 root: batch state, counts and every task's receipt state."""
    root = Path(output_root).resolve()
    plan = load_batch_plan(root)
    tasks, counts, warnings = {}, {state: 0 for state in recovery.STATES}, False
    for task in plan["tasks"]:
        try:
            receipt = recovery.read_receipt(root, task)
        except recovery.MalformedReceipt as exc:
            receipt, state, detail = None, "blocked", str(exc)
        else:
            if receipt is None:
                state = "blocked" if (recovery._has_content(task["output_dir"])
                                      and task.get("attempts") != "projection") else "pending"
                detail = f"{task['output_dir']} exists without a receipt" if state == "blocked" else None
            else:
                state, detail = receipt["state"], receipt.get("detail")
                warnings = warnings or bool(state == "completed" and receipt.get("warnings"))
        counts[state] += 1
        tasks[task["id"]] = {"state": state, "detail": detail,
                             "accepted_attempt": receipt.get("accepted_attempt") if receipt else None,
                             "receipt": f"{recovery.STEPS_DIR}/{task['key']}.json"}
    recorded = recovery._read(root / STATUS_NAME) or {}
    if lock_held(root):
        state = "running"
    elif not recorded:
        state = "not_started"
    else:
        state = derive_state(counts, warnings, recorded.get("state") == "interrupted"
                             or recorded.get("state") == "running")
    return {"campaign_version": CAMPAIGN_VERSION, "state": state, "recorded_state": recorded.get("state"),
            "counts": counts, "tasks": tasks, "execution": recorded.get("execution"),
            "refusal": recorded.get("refusal"), "recovery_proposal": recorded.get("recovery_proposal")}
