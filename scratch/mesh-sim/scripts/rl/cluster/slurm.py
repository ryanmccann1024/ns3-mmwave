"""Execute scheduler commands and parse queue/accounting responses."""

import re
import shutil
import subprocess
from scripts.rl.cluster import receipts

_ELEMENT_RE = re.compile(r"^(\d+)_\[(.+)\]$")
_JOB_ID_RE = re.compile(r"^(\d+)(;.*)?$")
_CANCELLED_RE = re.compile(r"^CANCELLED\b.*")


def available(binary: str = "sbatch") -> bool:
    """Whether a scheduler binary is on PATH right now."""
    return shutil.which(binary) is not None


def _run(argv: list[str]) -> dict:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True)
    except OSError as exc:
        return {"ok": False, "stdout": "", "stderr": f"{type(exc).__name__}: {exc}",
                "returncode": None, "argv": argv}
    return {"ok": proc.returncode == 0, "stdout": proc.stdout, "stderr": proc.stderr,
            "returncode": proc.returncode, "argv": argv}


def parse_job_id(text: str) -> str | None:
    """Read `jobid[;cluster]` from --parsable output; None when unparseable."""
    for line in text.splitlines():
        match = _JOB_ID_RE.match(line.strip())
        if match:
            return match.group(1)
    return None


def submit(argv: list[str]) -> dict:
    """Run sbatch; job_id is set only when the response parsed as a job id."""
    result = _run(argv)
    result["job_id"] = parse_job_id(result["stdout"]) if result["ok"] else None
    return result


def cancel(job_ids) -> dict:
    """Run scancel on exact job or array-element ids."""
    ids = list(job_ids)
    if not ids:
        raise ValueError("scancel needs at least one job id")
    return _run(["scancel", *ids])


def _expand(job_id: str) -> list[str]:
    match = _ELEMENT_RE.match(job_id)
    if not match:
        return [job_id]
    base, body = match.group(1), match.group(2).split("%")[0]
    elements = []
    for token in body.split(","):
        low, separator, high = token.partition("-")
        if not low.strip().isdigit():
            continue
        start = int(low)
        end = int(high) if separator and high.strip().isdigit() else start
        elements.extend(f"{base}_{index}" for index in range(start, end + 1))
    return elements


def parse_squeue(text: str) -> dict:
    """Parse `%i|%T|%r|%S` rows, expanding collapsed array-element ranges."""
    jobs = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.strip().split("|")
        if len(fields) < 4:
            continue
        job_id, state, reason, start = fields[0], fields[1], fields[2], fields[3]
        for element in _expand(job_id.strip()):
            jobs[element] = {"state": state.strip(), "reason": reason.strip(),
                             "start": start.strip()}
    return jobs


def parse_sacct(text: str) -> dict:
    """Parse `JobID|State|ExitCode` rows; step rows are dropped, CANCELLED normalized."""
    jobs = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.strip().split("|")
        if len(fields) < 3:
            continue
        job_id, state, exit_code = (field.strip() for field in fields[:3])
        if "." in job_id:
            continue
        if _CANCELLED_RE.match(state):
            state = "CANCELLED"
        for element in _expand(job_id):
            jobs[element] = {"state": state, "exit": exit_code}
    return jobs


def _base(job_id: str) -> str:
    return job_id.split("_", 1)[0]


def snapshot(job_ids, user: str) -> dict:
    """Queue and accounting view of the receipts' jobs; a failed query sets ok false."""
    ids = sorted({_base(str(job_id)) for job_id in job_ids})
    if not ids:
        return {"queue": {"ok": True, "jobs": {}},
                "accounting": {"ok": True, "jobs": {}}}
    queue = _run(["squeue", "--noheader", "--array", "--states=all",
                  f"--user={user}", "--format=%i|%T|%r|%S"])
    accounting = _run(["sacct", "--noheader", "--parsable2", "--array",
                       f"--jobs={','.join(ids)}", "--format=JobID,State,ExitCode"])
    wanted = set(ids)
    queue_jobs = {key: value for key, value in parse_squeue(queue["stdout"]).items()
                  if _base(key) in wanted} if queue["ok"] else {}
    account_jobs = ({key: value
                     for key, value in parse_sacct(accounting["stdout"]).items()
                     if _base(key) in wanted} if accounting["ok"] else {})
    return {"queue": {"ok": queue["ok"], "jobs": queue_jobs,
                      "error": "" if queue["ok"] else queue["stderr"].strip()},
            "accounting": {"ok": accounting["ok"], "jobs": account_jobs,
                           "error": "" if accounting["ok"]
                                    else accounting["stderr"].strip()}}


def find_jobs_by_name(name: str, user: str, start_time="1970-01-01") -> dict:
    """Look a no-ID submission up by its exact random job name in queue and accounting."""
    queue = _run(["squeue", "--noheader", "--states=all", f"--name={name}",
                  f"--user={user}", "--format=%i|%j|%T"])
    accounting = _run(["sacct", "--noheader", "--parsable2", f"--name={name}",
                       f"--user={user}", f"--starttime={start_time}",
                       "--format=JobID,JobName,State"])
    found: dict[str, str] = {}
    for result in (queue, accounting):
        if not result["ok"]:
            continue
        for line in result["stdout"].splitlines():
            fields = [field.strip() for field in line.strip().split("|")]
            if len(fields) < 3 or fields[1] != name or "." in fields[0]:
                continue
            found.setdefault(_base(fields[0]), fields[2])
    return {"ok": queue["ok"] and accounting["ok"], "job_ids": sorted(found),
            "states": found,
            "error": "; ".join(result["stderr"].strip() for result in (queue, accounting)
                               if not result["ok"])}


def get_snapshot(entries: list[dict]) -> dict:
    views = [snapshot(receipts.job_ids(group), owner)
             for owner in sorted({entry["user"] for entry in entries})
             for group in [[entry for entry in entries if entry["user"] == owner]]]
    result = {key: {"ok": True, "jobs": {}, "error": ""}
              for key in ("queue", "accounting")}
    for view in views:
        for key in result:
            result[key]["ok"] &= view[key]["ok"]
            result[key]["jobs"].update(view[key]["jobs"])
            if view[key].get("error"):
                result[key]["error"] += view[key]["error"] + "; "
    return result
