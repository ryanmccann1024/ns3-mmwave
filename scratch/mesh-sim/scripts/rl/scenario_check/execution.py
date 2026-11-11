"""Schedule cases in parallel and record campaign progress."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import threading
import time
import traceback

from scripts.artifact_io import write_json, sha256_file, now_iso, canonical_sha256
from scripts.sim_support import find_mesh_root
from scripts.rl.scenario_check.archive import snapshot as snapshot
from scripts.rl.scenario_check.case_execution import SeededEnv as SeededEnv
from scripts.rl.scenario_check.case_execution import run_case
from scripts.rl.scenario_check.reports import write_campaign_report
from scripts.rl.scenario_check.validation import validate_inputs as validate_inputs


class ActiveEnvironments:
    """Track only the environments belonging to this campaign run."""

    def __init__(self):
        self.active = set()
        self.lock = threading.Lock()
        self.cancelled = threading.Event()


def require_binary(binary, mesh):
    binary = Path(binary).resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError(
            f"simulator binary missing or not executable: {binary}; build first"
        )
    sources = [
        mesh / "sim.cc",
        mesh / "CMakeLists.txt",
        *mesh.joinpath("src").rglob("*.cc"),
        *mesh.joinpath("src").rglob("*.h"),
    ]
    newer = [p for p in sources if p.stat().st_mtime > binary.stat().st_mtime]
    if newer:
        raise ValueError(
            "simulator build is older than sources; run ./ns3 build scratch/mesh-sim/sim from the ns3-mmwave root"
        )
    return binary


def run(source, output, binary, workers):
    mesh = find_mesh_root()
    source, output = Path(source).resolve(), Path(output).resolve()
    campaign = validate_inputs(source)
    binary = require_binary(binary, mesh)
    if output.exists():
        raise FileExistsError(
            f"output already exists: {output}; inspect its status, or use --output with a fresh directory. Nothing overwritten."
        )
    environments = ActiveEnvironments()
    output.mkdir(parents=True)
    archived = output / "inputs"
    digests = snapshot(source, archived)
    # Resolve linked libraries only on the user's launch, before simulator work.
    from scripts.baselines.runtime_identity import (
        channel_runtime_identity,
        planner_code_identity,
    )

    identity = dict(
        binary=channel_runtime_identity(binary),
        planners=planner_code_identity(),
        scripts={
            str(p.relative_to(mesh)): sha256_file(p)
            for p in sorted((mesh / "scripts").rglob("*.py"))
            if "__pycache__" not in p.parts and "tests" not in p.parts
        },
        inputs=digests,
    )
    write_json(output / "runtime_identity.json", identity)
    main = output / "Main"
    main.mkdir()
    (main / "README.md").write_text(
        "# October 23 scenario checks\n\n"
        "Open the scenario folder of interest as a standalone evaluation in the GUI.\n\n"
        + "\n".join(f'- {c["name"]}' for c in campaign["cases"])
        + "\n"
    )
    status = dict(
        scenario_check_status_version=1,
        status="running",
        started_at=now_iso(),
        ended_at=None,
        training_launched=False,
        episodes_expected=campaign["episodes_expected"],
        cases_expected=len(campaign["cases"]),
        cases_completed=0,
        identity_sha256=canonical_sha256(identity),
        workers=workers,
        cases={c["name"]: "queued" for c in campaign["cases"]},
    )
    write_json(output / "scenario_check_status.json", status)
    started = time.monotonic()
    outcomes = []
    status_lock = threading.Lock()
    print(
        f'10-23 scenario checks only: {len(campaign["cases"])} cases, {campaign["episodes_expected"]} episodes, {workers} workers. No training, no wall-clock cutoff.',
        flush=True,
    )
    print(
        f"Results: {output}\nCompletion: scenario_check_status.json and RESULTS.md",
        flush=True,
    )

    def job(case):
        with status_lock:
            status["cases"][case["name"]] = "running"
            write_json(output / "scenario_check_status.json", status)
        try:
            return run_case(case, archived, output, binary, environments)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            log = output / "errors"
            log.mkdir(exist_ok=True)
            (log / f'{case["name"]}.log').write_text(traceback.format_exc())
            return {**case, "status": "failed", "error": error, "episodes": []}

    pool = ThreadPoolExecutor(max_workers=workers)
    pending = []
    try:
        for case in campaign["cases"]:
            pending.append(pool.submit(job, case))
        for future in as_completed(pending):
            outcome = future.result()
            outcomes.append(outcome)
            with status_lock:
                status["cases"][outcome["name"]] = outcome["status"]
                status["cases_completed"] = len(outcomes)
                status["wall_s"] = time.monotonic() - started
                write_json(output / "scenario_check_status.json", status)
            print(
                f'{len(outcomes)}/{len(campaign["cases"])} {outcome["name"]}: {outcome["status"]}',
                flush=True,
            )
    except BaseException:
        environments.cancelled.set()
        for future in pending:
            future.cancel()
        with environments.lock:
            active = list(environments.active)
        for env in active:
            env.close()
        status.update(status="interrupted", ended_at=now_iso())
        write_json(output / "scenario_check_status.json", status)
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    outcomes.sort(key=lambda item: item["name"])
    write_campaign_report(output, outcomes)
    failed = sum(o["status"] == "failed" for o in outcomes)
    rejected = sum(o["status"] == "needs_review" for o in outcomes)
    status.update(
        status="failed"
        if failed
        else "completed_with_rejections"
        if rejected
        else "completed",
        ended_at=now_iso(),
        cases_failed=failed,
        cases_rejected=rejected,
        wall_s=time.monotonic() - started,
    )
    write_json(output / "scenario_check_status.json", status)
    print(
        f'DONE: {status["status"]}; {failed} execution errors; {rejected} cases need review. No training launched.',
        flush=True,
    )
    print(f"Read {output}/RESULTS.md", flush=True)
    return 1 if failed else 2 if rejected else 0
