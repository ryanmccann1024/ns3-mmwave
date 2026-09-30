"""baseline_manifest.json and baseline-plan.json schemas, status transitions, and I/O helpers."""

import hashlib
import importlib.metadata
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_NAME = "baseline_manifest.json"
PLAN_NAME = "baseline-plan.json"
PLANNER_LOG_NAME = "planner.log"
SIM_LOG_NAME = "sim.log"
MANIFEST_VERSION = 1
PLAN_VERSION = 1

STATUSES = ("preparing", "prepared", "running", "complete", "failed", "interrupted")
TERMINAL_STATUSES = ("complete", "failed", "interrupted")
_TRANSITIONS = {
    "preparing": {"prepared", "failed", "interrupted"},
    "prepared": {"running", "failed", "interrupted"},
    "running": {"complete", "failed", "interrupted"},
}
SEED_STATUSES = ("complete", "missing", "failed")
PACKAGE_DISTRIBUTIONS = ("numpy", "pydantic", "shapely", "pyproj", "PyYAML")
IDENTITY_HASH_KEYS = ("run_ini_sha256", "nodes_json_sha256", "buildings_json_sha256",
                      "jammers_json_sha256")


def now_iso() -> str:
    """UTC timestamp in the same format as the RL manifests."""
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path: str | Path, payload) -> None:
    """Write JSON atomically so a reader never sees a half-written file."""
    path = Path(path)
    temp = path.with_name(path.name + ".tmp")
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, allow_nan=False)
            handle.write("\n")
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    os.replace(temp, path)


def read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def canonical_sha256(payload) -> str:
    """SHA-256 of sorted-key, whitespace-free JSON."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def package_versions() -> dict:
    """Installed versions of the planner dependencies; None when absent."""
    versions = {}
    for name in PACKAGE_DISTRIBUTIONS:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def run_relative(path: str | Path, root: str | Path) -> str:
    """POSIX path of `path` relative to the run directory `root`."""
    return Path(os.path.relpath(Path(path).resolve(), Path(root).resolve())).as_posix()


def new_manifest(mode: str, executor: str, method: str | None,
                 requested_algorithm: str | None) -> dict:
    """Initial manifest in status preparing; later fields are filled as preparation runs."""
    return {
        "baseline_manifest_version": MANIFEST_VERSION,
        "run_id": str(uuid.uuid4()),
        "mode": mode,
        "requested_algorithm": requested_algorithm,
        "method": method,
        "objective": None,
        "application": None,
        "executor": executor,
        "started_at": now_iso(),
        "ended_at": None,
        "status": "preparing",
        "error": None,
        "planner_seed": None,
        "planner_seed_status": None,
        "max_iterations": None,
        "max_iterations_status": None,
        "planner_source": None,
        "package_versions": package_versions(),
        "rf": None,
        "mapping_sha256": None,
        "sim_binary_sha256": None,
        "source_run_config_abs": None,
        "source_scenario_identity": None,
        "effective_scenario_identity": None,
        "simulation_seeds": None,
        "fingerprint": None,
        "origin": None,
        "ground_datum": None,
        "geofence": None,
        "waypoint_policy": None,
        "initial_displacement_m_total": None,
        "planner_wall_s": None,
        "plan": None,
        "planner_log": None,
        "sim_log": None,
        "source_inputs": None,
        "effective_inputs": None,
        "eval_manifest": None,
        "seeds": [],
    }


def update_manifest(path: str | Path, **fields) -> dict:
    """Merge top-level fields into an existing manifest; status changes go through set_status."""
    if "status" in fields:
        raise ValueError("use set_status to change the manifest status")
    manifest = read_json(path)
    manifest.update(fields)
    write_json(path, manifest)
    return manifest


def set_status(path: str | Path, status: str, error: str | None = None,
               final: bool | None = None, **fields) -> dict:
    """Apply one legal status transition; terminal statuses and `final=True` set ended_at."""
    manifest = read_json(path)
    current = manifest.get("status")
    if status not in _TRANSITIONS.get(current, set()):
        raise ValueError(f"illegal baseline manifest transition {current!r} -> {status!r}")
    manifest.update(fields)
    manifest["status"] = status
    if error is not None:
        manifest["error"] = error
    if (status in TERMINAL_STATUSES) if final is None else final:
        manifest["ended_at"] = now_iso()
    write_json(path, manifest)
    return manifest


def seed_record(seed: int, status: str, summary: str | None) -> dict:
    """One per-seed entry; `summary` is a run-relative path or None."""
    if status not in SEED_STATUSES:
        raise ValueError(f"seed status must be one of {SEED_STATUSES}, got {status!r}")
    return {"seed": int(seed), "status": status, "summary": summary}


def set_seed_records(path: str | Path, records: list[dict]) -> dict:
    return update_manifest(path, seeds=list(records))


def fingerprint(manifest: dict) -> str:
    """Hash of the fields that define one reusable plan and its effective inputs."""
    identity = manifest.get("effective_scenario_identity") or {}
    source = manifest.get("planner_source") or {}
    rf = manifest.get("rf") or {}
    return canonical_sha256({
        "method": manifest.get("method"),
        "objective": manifest.get("objective"),
        "planner_seed": manifest.get("planner_seed"),
        "max_iterations": manifest.get("max_iterations"),
        "waypoint_policy": manifest.get("waypoint_policy"),
        "mapping_sha256": manifest.get("mapping_sha256"),
        "rf_sha256": rf.get("sha256"),
        "planner_source_aggregate_sha256": source.get("aggregate_sha256"),
        **{key: identity.get(key) for key in IDENTITY_HASH_KEYS},
    })


def build_plan(method: str, objective: str | None, nodes: list[dict],
               predictions) -> dict:
    """baseline-plan.json payload; node entries come from the adapter."""
    total = sum(float(node["displacement_m"]) for node in nodes)
    return {
        "baseline_plan_version": PLAN_VERSION,
        "method": method,
        "objective": objective,
        "nodes": nodes,
        "initial_displacement_m_total": total,
        "planner_predictions": predictions,
    }


def write_plan(path: str | Path, plan: dict) -> None:
    """Write the plan once; an existing plan is never replaced."""
    if Path(path).exists():
        raise FileExistsError(f"baseline plan already exists: {path}")
    write_json(path, plan)


def eval_metadata(manifest: dict, manifest_rel: str, plan_rel: str) -> dict:
    """The per-policy `baseline` block stored in eval_manifest.json."""
    identity = manifest.get("effective_scenario_identity") or {}
    return {
        "method": manifest["method"],
        "requested_algorithm": manifest["requested_algorithm"],
        "objective": manifest["objective"],
        "executor": manifest["executor"],
        "planner_seed": manifest["planner_seed"],
        "max_iterations": manifest["max_iterations"],
        "fingerprint": manifest["fingerprint"],
        "initial_displacement_m_total": manifest["initial_displacement_m_total"],
        "effective_scenario_identity": {key: identity.get(key) for key in IDENTITY_HASH_KEYS},
        "planner_source_sha256": (manifest.get("planner_source") or {}).get("aggregate_sha256"),
        "rf_config_sha256": (manifest.get("rf") or {}).get("sha256"),
        "mapping_sha256": manifest["mapping_sha256"],
        "manifest": manifest_rel,
        "plan": plan_rel,
    }
