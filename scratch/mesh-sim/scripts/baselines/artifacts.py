"""Baseline schemas, status transitions, and persisted plan identity."""

import importlib.metadata
import os
import uuid
from pathlib import Path
from scripts.artifact_io import canonical_sha256, now_iso, read_json, sha256_file, write_json
from scripts.baselines.config import PLATFORMS

MANIFEST_NAME = "baseline_manifest.json"
PLAN_NAME = "baseline-plan.json"
PLANNER_LOG_NAME = "planner.log"
SIM_LOG_NAME = "sim.log"
MANIFEST_VERSION = 3
PLAN_VERSION = 3
FINGERPRINT_VERSION = 3

STATUSES = ("preparing", "prepared", "running", "complete", "failed", "interrupted")
TERMINAL_STATUSES = ("complete", "failed", "interrupted")
_TRANSITIONS = {
    "preparing": {"prepared", "failed", "interrupted"},
    "prepared": {"running", "failed", "interrupted"},
    "running": {"complete", "failed", "interrupted"},
}
SEED_STATUSES = ("complete", "missing", "failed")
PACKAGE_DISTRIBUTIONS = ("numpy",)
IDENTITY_HASH_KEYS = (
    "run_ini_sha256",
    "nodes_json_sha256",
    "buildings_json_sha256",
    "jammers_json_sha256",
)


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


def new_manifest(
    mode: str, executor: str, method: str | None, requested_algorithm: str | None
) -> dict:
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
        "package_versions": package_versions(),
        "mapping_sha256": None,
        "geofence": None,
        "sim_binary_sha256": None,
        "channel_runtime_sha256": None,
        "channel_runtime_files": None,
        "planner_code_sha256": None,
        "channel_scoring": None,
        "penalties": None,
        "planner_settings": None,
        "ownership": None,
        "source_run_config_abs": None,
        "source_scenario_identity": None,
        "effective_scenario_identity": None,
        "simulation_seeds": None,
        "seed_roles": None,
        "fingerprint": None,
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


def set_status(
    path: str | Path, status: str, error: str | None = None, final: bool | None = None, **fields
) -> dict:
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
    """Hash of everything that defines one reusable plan; no timing or paths."""
    identity = manifest.get("effective_scenario_identity") or {}
    scoring = manifest.get("channel_scoring") or {}
    probe = scoring.get("probe") or {}
    grid = scoring.get("candidate_grid") or {}
    penalties = manifest.get("penalties") or {}
    return canonical_sha256(
        {
            "fingerprint_version": FINGERPRINT_VERSION,
            "method": manifest.get("method"),
            "objective": manifest.get("objective"),
            "planner_seed": manifest.get("planner_seed"),
            "max_iterations": manifest.get("max_iterations"),
            "waypoint_policy": manifest.get("waypoint_policy"),
            "mapping_sha256": manifest.get("mapping_sha256"),
            "penalties": {platform: penalties.get(platform) for platform in ("aerial", "ground")},
            "grid": {
                key: grid.get(key) for key in ("cells", "min_resolution_m", "cell_m", "count")
            },
            "probe": {
                key: probe.get(key)
                for key in (
                    "height_m",
                    "rx_gain_dbi",
                    "grid_cells",
                    "min_resolution_m",
                    "cell_m",
                    "count",
                )
            },
            "sinr_threshold_db": scoring.get("sinr_threshold_db"),
            "coverage_sinr_db": scoring.get("coverage_sinr_db"),
            "planning_seed": scoring.get("planning_seed"),
            "planning_run_id": scoring.get("planning_run_id"),
            "jammer_seed": scoring.get("jammer_seed"),
            "mode_flag": scoring.get("mode_flag"),
            "band": scoring.get("band"),
            **{key: identity.get(key) for key in IDENTITY_HASH_KEYS},
            "sim_binary_sha256": manifest.get("sim_binary_sha256"),
            "channel_runtime_sha256": manifest.get("channel_runtime_sha256"),
            "planner_code_sha256": manifest.get("planner_code_sha256"),
            "planner_settings": manifest.get("planner_settings"),
            "ownership": manifest.get("ownership"),
        }
    )


def build_plan(method: str, objective: str | None, nodes: list[dict], predictions) -> dict:
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
        "baseline_manifest_version": manifest["baseline_manifest_version"],
        "method": manifest["method"],
        "requested_algorithm": manifest["requested_algorithm"],
        "objective": manifest["objective"],
        "executor": manifest["executor"],
        "planner_seed": manifest["planner_seed"],
        "max_iterations": manifest["max_iterations"],
        "planning_seed": (manifest.get("channel_scoring") or {}).get("planning_seed"),
        "ownership": manifest.get("ownership"),
        "seed_roles": manifest.get("seed_roles"),
        "fingerprint": manifest["fingerprint"],
        "initial_displacement_m_total": manifest["initial_displacement_m_total"],
        "effective_scenario_identity": {key: identity.get(key) for key in IDENTITY_HASH_KEYS},
        "mapping_sha256": manifest["mapping_sha256"],
        "manifest": manifest_rel,
        "plan": plan_rel,
    }


def penalties_block(penalties: dict, aoi_m2: float) -> dict:
    """Manifest `penalties`: per-platform costs plus the AOI scale check."""
    block = {
        platform: {
            "fixed_cost_m2": cost.fixed_cost_m2,
            "cost_m2_per_m": cost.cost_m2_per_m,
            "max_displacement_m": cost.max_displacement_m,
        }
        for platform, cost in penalties.items()
    }
    block["aoi_m2"] = aoi_m2
    block["fixed_cost_over_aoi"] = {
        platform: penalties[platform].fixed_cost_m2 / aoi_m2 for platform in PLATFORMS
    }
    return block
