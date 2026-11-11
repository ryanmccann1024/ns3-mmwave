"""Validate experiment matrices: shared v1 field helpers and the version 2 batch schema.

Validation reads only configuration, assets and saved training manifests. It
starts no simulator, writes nothing and imports no scheduler or CLI.
"""

import json
import math
import re
from pathlib import Path

from scripts.artifact_io import canonical_sha256, sha256_file
from scripts.rl.agents.config import PPO_FIELDS, validate_training_settings
from scripts.rl.env.config import read_action_profile, read_explicit_rl_bounds
from scripts.rl.env.selection import resolve_selection
from scripts.rl.experiments.scenario_timing import (
    native_decisions as native_decisions,
    validate_deployment_gate,
)
from scripts.rl.policy.bundle import checkpoint_counters
from scripts.rl.policy.evaluate import PLACEMENT_POLICIES
from scripts.rl.policy.training_artifacts import CHECKPOINT_DIR
from scripts.rl.policy.schedules import COVERAGE_KINDS, validate_schedule
from scripts.sim_support import parse_ini, parse_seed_spec

MATRIX_V2_VERSION = 2
KINDS = ("train", "checks", "evaluate")
SEED_ROLES = ("training", "model_selection", "diagnostic", "held_out")
OPERATION_SEED_ROLES = ("model_selection", "diagnostic", "held_out")
MODES = ("frozen_deterministic", "frozen_sampled", "online_gated_v1", "online_sb3_v1")
FROZEN_MODES = MODES[:2]
ONLINE_MODES = MODES[2:]
CHECKPOINT_TIMINGS = ("standard", "after_update")
FAILURE_POLICIES = ("continue", "stop")
RECOVERY_MODES = ("none", "checkpoint")
BASELINE_POLICIES = ("hold", "random_valid", "scripted", *PLACEMENT_POLICIES)
REFERENCE_KINDS = ("scenario_routes_v1", "mission_waypoints_v1")
CHECK_KINDS = ("preflight", "replay_gate", "reward_audit")
SELECTION_RULES = (
    "legacy-validation-profile-v1",
    "legacy-mission-profile-v1",
    "legacy-online-profile-v1",
    "replay",
)
EXECUTION_DEFAULTS = {
    "workers": 1,
    "threads_per_worker": 1,
    "failure_policy": "continue",
    "nice": 0,
}

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_EXPLICIT = "rows are explicit; no product expansion"
_BANDS = ("mmwave", "sub-6")
_CHECKPOINT_RE = re.compile(r"^checkpoint_(\d+)_steps\.zip$")

_TOP_KEYS = (
    "matrix_version",
    "name",
    "description",
    "kind",
    "scenarios",
    "seeds",
    "training",
    "evaluation",
    "checks",
    "stages",
    "execution",
    "rows",
)
_SCENARIO_KEYS = (
    "run_config",
    "band",
    "configs",
    "case",
    "baselines",
    "reference",
    "history_sources",
)
_CASE_KEYS = (
    "mission",
    "environment",
    "peers",
    "coverage_target",
    "reviewed_exception",
    "exception_reason",
    "seeds",
)
BASELINE_CONFIG_SCOPES = ("rows", "scenario")
_BASELINE_KEYS = (
    "policies",
    "seed_role",
    "decision_records",
    "import_from",
    "planning_seed",
    "configs_scope",
    "decision_record_seeds",
    "allow_seed_overlap",
)
_TRAINING_KEYS = (
    *PPO_FIELDS,
    "eval_every_steps",
    "checkpoint_every_steps",
    "keep_checkpoints",
    "checkpoint_timing",
    "decisions_per_episode",
    "total_episodes",
)
_OPERATION_KEYS = (
    "id",
    "mode",
    "seed_role",
    "at_steps",
    "schedule",
    "online",
    "decision_record_seeds",
    "decision_records",
)
_GATED_KEYS = ("n_steps", "batch_size", "target_kl")
_SB3_KEYS = ("n_steps", "batch_size", "learning_rate", "ent_coef", "target_kl")
_COMPARISON_KEYS = ("operation", "allow_incomplete")
_EXECUTION_KEYS = (
    "workers",
    "threads_per_worker",
    "failure_policy",
    "nice",
    "recovery",
    "resource_pool",
)
_ROW_SELECTION_KEYS = (
    "observation_preset",
    "action_profile",
    "reward_components",
    "reward_weights",
    "observation_parameters",
    "reward_parameters",
)
_ROW_KEYS = {
    "train": (
        "name",
        "scenario",
        "profile",
        *_ROW_SELECTION_KEYS,
        "training",
        "seeds",
        "configs",
        "operations",
        "training_config_key",
        "continue_from",
        "curriculum",
        "labels",
    ),
    "evaluate": (
        "name",
        "scenario",
        "profile",
        *_ROW_SELECTION_KEYS,
        "operations",
        "configs",
        "model_source",
        "labels",
    ),
    "checks": ("name", "scenario", "profile", *_ROW_SELECTION_KEYS, "labels"),
}
_LABEL_KEYS = ("reward_label", "ppo_label", "comparison", "source_phase", "tags")
_STAGE_KEYS = ("name", "rows", "needs", "selection")
_SELECTION_KEYS = (
    "rule",
    "candidates",
    "source_operation",
    "source_checkpoint",
    "normalization_decisions",
    "retain",
    "branches",
    "winners",
    "provenance",
)


def _check_keys(mapping, allowed: tuple[str, ...], where: str) -> None:
    if not isinstance(mapping, dict):
        raise ValueError(f"{where} must be a JSON object")
    unknown = sorted(key for key in mapping if key not in allowed)
    if unknown:
        raise ValueError(
            f"{where} has unknown keys {unknown}; " f"valid keys: {list(allowed)}"
        )


def _scalar(value, where: str):
    if isinstance(value, list):
        raise ValueError(f"{where} must be a single value: {_EXPLICIT}")
    return value


def _name(value, where: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.match(value):
        raise ValueError(f"{where} must match [a-z0-9][a-z0-9-]*, got {value!r}")
    return value


def _int(value, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{where} must be an integer, got {value!r}")
    return value


def _seed_list(value, where: str) -> list[int]:
    if isinstance(value, str):
        return parse_seed_spec(value)
    if not isinstance(value, list):
        raise ValueError(f"{where} must be a seed spec string or an array of integers")
    seeds = [_int(seed, where) for seed in value]
    if len(set(seeds)) != len(seeds):
        raise ValueError(f"{where} must be distinct, got {seeds}")
    return seeds


def _string_array(value, where: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{where} must be a non-empty JSON array")
    if not all(isinstance(entry, str) for entry in value):
        raise ValueError(f"{where} must contain strings")
    return list(value)


def _weight_array(value, where: str) -> list[float]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{where} must be a non-empty JSON array")
    if any(isinstance(w, bool) or not isinstance(w, (int, float)) for w in value):
        raise ValueError(f"{where} must contain numbers")
    return [float(w) for w in value]


def _band(value, where: str) -> str | None:
    value = _scalar(value, where)
    if value is None:
        return None
    if value not in _BANDS:
        raise ValueError(f"{where} must be one of {list(_BANDS)}, got {value!r}")
    return value


def _positive_int(value, where: str, minimum: int = 1) -> int:
    value = _int(value, where)
    if value < minimum:
        raise ValueError(f"{where} must be an integer >= {minimum}, got {value}")
    return value


def _number(value, where: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{where} must be a finite number, got {value!r}")
    return float(value)


def _bool(value, where: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{where} must be a boolean, got {value!r}")
    return value


def _distinct_names(values, where: str) -> list[str]:
    if not isinstance(values, list):
        raise ValueError(f"{where} must be a JSON array")
    names = [_name(value, where) for value in values]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise ValueError(f"{where} must be distinct, repeated: {repeated}")
    return names


def _input_path(raw, base: Path, where: str, kind: str = "file") -> dict:
    """Resolve an input reference against the matrix directory; keep the original text."""
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{where} must be a nonempty path")
    path = Path(raw).expanduser()
    path = (path if path.is_absolute() else base / path).resolve()
    exists = path.is_file() if kind == "file" else path.is_dir()
    if not exists:
        raise ValueError(f"{where}: {kind} not found: {path} (from {raw!r})")
    return {"path": str(path), "reference": raw}


def _output_path(raw, base: Path, where: str) -> dict:
    """An output location must not climb out of the matrix tree through '..'."""
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{where} must be a nonempty path")
    path = Path(raw).expanduser()
    if not path.is_absolute() and ".." in path.parts:
        raise ValueError(
            f"{where}: unsafe relative output path {raw!r}; "
            "use an absolute path or one inside the matrix directory"
        )
    return {
        "path": str((path if path.is_absolute() else base / path).resolve()),
        "reference": raw,
    }


def _seeds(raw) -> dict:
    _check_keys(raw, SEED_ROLES, "seeds")
    seeds = {
        role: _seed_list(raw.get(role, []), f"seeds.{role}") for role in SEED_ROLES
    }
    _check_disjoint({f"seeds.{role}": set(values) for role, values in seeds.items()})
    return seeds


def _check_disjoint(roles: dict[str, set]) -> None:
    names = sorted(roles)
    for first, second in ((a, b) for i, a in enumerate(names) for b in names[i + 1 :]):
        shared = sorted(roles[first] & roles[second])
        if shared:
            raise ValueError(
                f"{first} and {second} share seeds {shared}; "
                "seed roles must be disjoint"
            )


def _training(raw, where: str, override: bool = False) -> dict:
    _check_keys(raw, _TRAINING_KEYS, where)
    settings = {
        key: value if key == "net_arch" else _scalar(value, f"{where}.{key}")
        for key, value in raw.items()
    }
    ppo = {
        key: value
        for key, value in settings.items()
        if key not in ("checkpoint_timing", "decisions_per_episode", "total_episodes")
    }
    try:
        validate_training_settings(ppo)
    except ValueError as exc:
        raise ValueError(f"{where}: {exc}") from exc
    timing = settings.get("checkpoint_timing", "standard")
    if timing not in CHECKPOINT_TIMINGS:
        raise ValueError(
            f"{where}.checkpoint_timing must be one of {list(CHECKPOINT_TIMINGS)}"
        )
    if not override:
        settings["checkpoint_timing"] = timing
    for key in ("decisions_per_episode", "total_episodes"):
        if key in settings:
            _positive_int(settings[key], f"{where}.{key}")
    return settings


def _schedule(raw, where: str) -> dict:
    """Validate a declared schedule with its owner, `policy.schedules.validate_schedule`.

    A coverage kind may omit coverage_target here; schedule_for resolves it per
    scenario (settings > case) and validates the resolved schedule again.
    """
    try:
        if (
            isinstance(raw, dict)
            and raw.get("kind") in COVERAGE_KINDS
            and isinstance(raw.get("settings"), dict)
            and "coverage_target" not in raw["settings"]
        ):
            # Structural check only; the placeholder target is discarded.
            validate_schedule(
                {**raw, "settings": {**raw["settings"], "coverage_target": 1.0}}
            )
            return {"kind": raw["kind"], "settings": dict(raw["settings"])}
        return validate_schedule(raw)
    except ValueError as exc:
        raise ValueError(f"{where}: {exc}; schedules have no defaults") from exc


def schedule_for(schedule: dict | None, case: dict | None, where: str) -> dict | None:
    """Resolve a declared schedule for one scenario; a coverage target is never guessed."""
    if schedule is None or schedule["kind"] not in COVERAGE_KINDS:
        return schedule
    declared = (case or {}).get("coverage_target")
    given = schedule["settings"].get("coverage_target")
    if given is None and declared is None:
        raise ValueError(
            f"{where}: {schedule['kind']} needs settings.coverage_target or the "
            "scenario case coverage_target"
        )
    if given is not None and declared is not None and float(declared) != float(given):
        raise ValueError(
            f"{where}: coverage_target {given} differs from the scenario case's "
            f"{declared}"
        )
    target = given if given is not None else float(declared)
    try:
        return validate_schedule(
            {
                "kind": schedule["kind"],
                "settings": {**schedule["settings"], "coverage_target": target},
            }
        )
    except ValueError as exc:
        raise ValueError(f"{where}: {exc}") from exc


def _online(raw, mode: str, where: str) -> dict:
    allowed = _GATED_KEYS if mode == "online_gated_v1" else _SB3_KEYS
    _check_keys(raw, allowed, where)
    for key in ("n_steps", "batch_size"):
        if key not in raw:
            raise ValueError(f"{where}.{key} is required for {mode}")
    settings = dict(raw)
    try:
        validate_training_settings({k: v for k, v in settings.items() if v is not None})
    except ValueError as exc:
        raise ValueError(f"{where}: {exc}") from exc
    if settings["batch_size"] > settings["n_steps"]:
        raise ValueError(f"{where}.batch_size must not exceed n_steps")
    if mode == "online_gated_v1":
        if settings.get("target_kl") is not None:
            raise ValueError(f"{where}.target_kl must be null for online_gated_v1")
        settings.pop("target_kl", None)
    elif settings["n_steps"] % settings["batch_size"]:
        raise ValueError(f"{where}: online batch size must divide its rollout")
    # SB3 keys left out keep the online protocol's existing defaults; record the gap.
    return {
        key: settings.get(key)
        for key in allowed
        if key in settings or mode == "online_sb3_v1"
    }


def _operations(raw, kind: str, scenarios: dict) -> list[dict]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("evaluation.operations must be a non-empty JSON array")
    operations = []
    for index, entry in enumerate(raw):
        where = f"evaluation.operations[{index}]"
        _check_keys(entry, _OPERATION_KEYS, where)
        op_id = _name(entry.get("id"), f"{where}.id")
        where = f"operation {op_id}"
        mode = entry.get("mode")
        if mode not in MODES:
            raise ValueError(f"{where}.mode must be one of {list(MODES)}, got {mode!r}")
        role = entry.get("seed_role")
        if role not in OPERATION_SEED_ROLES:
            raise ValueError(
                f"{where}.seed_role must be one of {list(OPERATION_SEED_ROLES)}"
            )
        if kind == "evaluate":
            if "at_steps" in entry:
                raise ValueError(
                    f"{where}.at_steps is not used by kind 'evaluate'; "
                    "the row's model_source names the model"
                )
            at_steps = None
        else:
            at_steps = entry.get("at_steps")
            if not isinstance(at_steps, list) or not at_steps:
                raise ValueError(
                    f"{where}.at_steps must list final, best or retained "
                    "cumulative timesteps"
                )
            for value in at_steps:
                if value not in ("final", "best"):
                    _positive_int(value, f"{where}.at_steps")
            if len({json.dumps(v) for v in at_steps}) != len(at_steps):
                raise ValueError(f"{where}.at_steps must be distinct")
        schedule = None
        if entry.get("schedule") is not None:
            if mode in ONLINE_MODES:
                raise ValueError(
                    f"{where}: a schedule cannot be combined with online mode "
                    f"{mode}; no existing protocol supports that composition"
                )
            schedule = _schedule(entry["schedule"], f"{where}.schedule")
        online = None
        if mode in ONLINE_MODES:
            if entry.get("online") is None:
                raise ValueError(f"{where}.online settings are required for {mode}")
            online = _online(entry["online"], mode, f"{where}.online")
        elif entry.get("online") is not None:
            raise ValueError(f"{where}.online is only valid for online modes")
        records = _bool(
            entry.get("decision_records", False), f"{where}.decision_records"
        )
        record_seeds = None
        if entry.get("decision_record_seeds") is not None:
            if not records:
                raise ValueError(
                    f"{where}.decision_record_seeds requires decision_records: true"
                )
            record_seeds = _seed_list(
                entry["decision_record_seeds"], f"{where}.decision_record_seeds"
            )
            if not record_seeds:
                raise ValueError(
                    f"{where}.decision_record_seeds must name at least one seed"
                )
        config = {
            "mode": mode,
            "schedule": schedule,
            "online": online,
            "decision_records": records,
        }
        if record_seeds is not None:
            # Hashed only when declared, so existing operation digests are unchanged.
            config["decision_record_seeds"] = record_seeds
        operations.append(
            {
                "id": op_id,
                "seed_role": role,
                "at_steps": at_steps,
                "decision_record_seeds": record_seeds,
                **config,
                "config_digest": canonical_sha256(config),
            }
        )
    _distinct_names([op["id"] for op in operations], "evaluation.operations ids")
    return operations


def _evaluation(raw, kind: str, scenarios: dict) -> dict:
    _check_keys(raw, ("operations", "comparison"), "evaluation")
    operations = _operations(raw.get("operations"), kind, scenarios)
    comparison = None
    if raw.get("comparison") is not None:
        _check_keys(raw["comparison"], _COMPARISON_KEYS, "evaluation.comparison")
        op_id = raw["comparison"].get("operation")
        target = next((op for op in operations if op["id"] == op_id), None)
        if target is None:
            raise ValueError(
                f"evaluation.comparison.operation {op_id!r} is not declared"
            )
        if target["mode"] not in FROZEN_MODES or target["schedule"] is not None:
            raise ValueError(
                "evaluation.comparison needs an unscheduled frozen operation"
            )
        comparison = {
            "operation": op_id,
            "allow_incomplete": _bool(
                raw["comparison"].get("allow_incomplete", False),
                "evaluation.comparison.allow_incomplete",
            ),
        }
    return {"operations": operations, "comparison": comparison}


def _ini_nodes(run_config: str) -> list[str]:
    ini = parse_ini(run_config)
    raw = ini.get("scenario", {}).get("nodes_file", "") or "nodes.json"
    path = Path(raw) if Path(raw).is_absolute() else Path(run_config).parent / raw
    try:
        nodes = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"{run_config}: nodes file unreadable: {path}: {exc}") from exc
    if not isinstance(nodes, list) or not all(
        isinstance(n, dict) and "id" in n for n in nodes
    ):
        raise ValueError(f"{path}: nodes file must be a JSON array of nodes with ids")
    return [str(node["id"]) for node in nodes]


def _point(point, bounds: dict, where: str, sizes: tuple[int, ...]) -> None:
    if (
        not isinstance(point, list)
        or len(point) not in sizes
        or any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            for v in point
        )
    ):
        raise ValueError(
            f"{where} has an invalid point {point!r}; expected {sizes} coordinates"
        )
    for axis, coordinate in zip("xyz", point):
        low, high = bounds.get(f"{axis}_min"), bounds.get(f"{axis}_max")
        if (low is not None and coordinate < low) or (
            high is not None and coordinate > high
        ):
            raise ValueError(
                f"{where} point {point} leaves the explicit [rl] {axis} bounds"
            )


def _points(value, bounds: dict, where: str, sizes: tuple[int, ...] = (3,)) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{where} must be an array of points")
    for point in value:
        _point(point, bounds, where, sizes)


# Fields each reader consumes: scenario_check ReferencePolicy reads `routes`
# (v2 adds the correction's `targets` record); policy.scripted.ScriptedMissionPolicy
# reads waypoints/node_order/start_after_failure/start_after_s/start_below_delivery/parallel.
_ROUTE_KEYS = {
    1: ("reference_version", "routes", "description"),
    2: (
        "reference_version",
        "routes",
        "targets",
        "description",
        "reference_only",
        "radio_feasibility",
    ),
}
_WAYPOINT_KEYS = (
    "reference_version",
    "description",
    "waypoints",
    "node_order",
    "start_after_failure",
    "start_after_s",
    "start_below_delivery",
    "parallel",
)
_WAYPOINT_VERSIONS = (1, 2, 3)


def _reference(raw, base: Path, run_config: str, where: str) -> dict:
    _check_keys(raw, ("kind", "path"), where)
    kind = raw.get("kind")
    if kind not in REFERENCE_KINDS:
        raise ValueError(
            f"{where}.kind must be one of {list(REFERENCE_KINDS)}, got {kind!r}"
        )
    resolved = _input_path(raw.get("path"), base, f"{where}.path")
    try:
        data = json.loads(Path(resolved["path"]).read_text())
    except ValueError as exc:
        raise ValueError(f"{where}: reference is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{where}: {kind} must be a JSON object")
    nodes = set(_ini_nodes(run_config))
    bounds = read_explicit_rl_bounds(run_config)
    if not isinstance(data.get("description", ""), str):
        raise ValueError(f"{where}: description must be a string")
    if kind == "scenario_routes_v1":
        version = data.get("reference_version")
        if version not in _ROUTE_KEYS:
            raise ValueError(
                f"{where}: scenario_routes_v1 requires reference_version 1 or 2, "
                f"got {version!r}"
            )
        _check_keys(data, _ROUTE_KEYS[version], where)
        routes = data.get("routes")
        if not isinstance(routes, dict) or not routes:
            raise ValueError(f"{where}: routes must map node ids to point lists")
        named = set(routes)
        for node, points in routes.items():
            _points(points, bounds, f"{where}.routes[{node!r}]")
        if version == 2:
            targets = data.get("targets")
            if targets is not None:
                if not isinstance(targets, dict):
                    raise ValueError(
                        f"{where}: targets must map node ids to [x, y] points"
                    )
                for node, point in targets.items():
                    _point(point, bounds, f"{where}.targets[{node!r}]", (2, 3))
                named |= set(targets)
            if "reference_only" in data:
                _bool(data["reference_only"], f"{where}.reference_only")
            if not isinstance(data.get("radio_feasibility", ""), str):
                raise ValueError(f"{where}: radio_feasibility must be a string")
    else:
        _check_keys(data, _WAYPOINT_KEYS, where)
        version = data.get("reference_version")
        if version is not None and version not in _WAYPOINT_VERSIONS:
            raise ValueError(
                f"{where}: mission_waypoints_v1 reference_version must be one of "
                f"{list(_WAYPOINT_VERSIONS)}, got {version!r}"
            )
        waypoints, order = data.get("waypoints"), data.get("node_order")
        if not isinstance(waypoints, dict) or not waypoints:
            raise ValueError(f"{where}: waypoints must map node ids to point lists")
        if (
            not isinstance(order, list)
            or len(order) != len(set(order))
            or not set(order) <= set(waypoints)
        ):
            raise ValueError(
                f"{where}: node_order must list distinct waypoint node ids"
            )
        _bool(data.get("start_after_failure"), f"{where}.start_after_failure")
        if "parallel" in data:
            _bool(data["parallel"], f"{where}.parallel")
        if (
            "start_after_s" in data
            and _number(data["start_after_s"], f"{where}.start_after_s") < 0
        ):
            raise ValueError(f"{where}.start_after_s must be >= 0")
        if (
            "start_below_delivery" in data
            and not 0
            <= _number(data["start_below_delivery"], f"{where}.start_below_delivery")
            <= 1
        ):
            raise ValueError(f"{where}.start_below_delivery must be in [0,1]")
        named = set(waypoints)
        for node, points in waypoints.items():
            _points(points, bounds, f"{where}.waypoints[{node!r}]", (2, 3))
    unknown = sorted(named - nodes)
    if unknown:
        raise ValueError(
            f"{where}: node ids {unknown} are not in the scenario's nodes file"
        )
    return {"kind": kind, "version": version, **resolved}


def _case(raw, where: str) -> dict:
    _check_keys(raw, _CASE_KEYS, where)
    for key in ("mission", "environment"):
        _name(raw.get(key), f"{where}.{key}")
    case = {
        "mission": raw["mission"],
        "environment": raw["environment"],
        "peers": _positive_int(raw.get("peers"), f"{where}.peers"),
        "coverage_target": None,
        "reviewed_exception": False,
        "exception_reason": None,
        "seeds": {},
    }
    if raw.get("coverage_target") is not None:
        target = _number(raw["coverage_target"], f"{where}.coverage_target")
        if not 0 < target <= 1:
            raise ValueError(f"{where}.coverage_target must be in (0,1]")
        case["coverage_target"] = target
    case["reviewed_exception"] = _bool(
        raw.get("reviewed_exception", False), f"{where}.reviewed_exception"
    )
    reason = raw.get("exception_reason")
    if case["reviewed_exception"] != (isinstance(reason, str) and bool(reason)):
        raise ValueError(
            f"{where}: a reviewed_exception needs an exception_reason, and only then"
        )
    case["exception_reason"] = reason
    seeds = raw.get("seeds", {})
    if not isinstance(seeds, dict):
        raise ValueError(f"{where}.seeds must map seed strings to {{gate_s}}")
    for seed, entry in seeds.items():
        if not str(seed).isdigit():
            raise ValueError(
                f"{where}.seeds key {seed!r} must be a seed integer string"
            )
        _check_keys(entry, ("gate_s",), f"{where}.seeds[{seed}]")
        gate = _number(entry.get("gate_s"), f"{where}.seeds[{seed}].gate_s")
        case["seeds"][str(seed)] = {"gate_s": gate}
    return case


def _baselines(raw, scenario: str, base: Path, has_reference: bool) -> dict:
    where = f"scenarios.{scenario}.baselines"
    _check_keys(raw, _BASELINE_KEYS, where)
    policies = raw.get("policies")
    if (
        not isinstance(policies, list)
        or not policies
        or any(p not in BASELINE_POLICIES for p in policies)
    ):
        raise ValueError(
            f"{where}.policies must list entries from {list(BASELINE_POLICIES)}"
        )
    if len(set(policies)) != len(policies):
        raise ValueError(f"{where}.policies must be distinct")
    if "scripted" in policies and not has_reference:
        raise ValueError(f"{where}: scripted baseline requires a scenario reference")
    role = raw.get("seed_role")
    if role not in OPERATION_SEED_ROLES:
        raise ValueError(
            f"{where}.seed_role must be one of {list(OPERATION_SEED_ROLES)}"
        )
    imported = None
    if raw.get("import_from") is not None:
        imported = _input_path(raw["import_from"], base, f"{where}.import_from")
    planning_seed = raw.get("planning_seed")
    if planning_seed is not None:
        if not any(p in PLACEMENT_POLICIES for p in policies):
            raise ValueError(
                f"{where}.planning_seed requires a placement policy "
                f"{list(PLACEMENT_POLICIES)}"
            )
        _int(planning_seed, f"{where}.planning_seed")
    overlap = _bool(raw.get("allow_seed_overlap", False), f"{where}.allow_seed_overlap")
    records = _bool(raw.get("decision_records", False), f"{where}.decision_records")
    record_seeds = None
    if raw.get("decision_record_seeds") is not None:
        if not records:
            raise ValueError(
                f"{where}.decision_record_seeds requires decision_records: true"
            )
        record_seeds = _seed_list(
            raw["decision_record_seeds"], f"{where}.decision_record_seeds"
        )
        if not record_seeds:
            raise ValueError(
                f"{where}.decision_record_seeds must name at least one seed"
            )
    scope = raw.get("configs_scope", "rows")
    if scope not in BASELINE_CONFIG_SCOPES:
        raise ValueError(
            f"{where}.configs_scope must be one of {list(BASELINE_CONFIG_SCOPES)}"
        )
    if overlap and not any(p in PLACEMENT_POLICIES for p in policies):
        raise ValueError(
            f"{where}.allow_seed_overlap applies only to placement policies"
        )
    if imported is not None and all(p in PLACEMENT_POLICIES for p in policies):
        raise ValueError(f"{where}.import_from cannot supply placement baselines")
    return {
        "policies": list(policies),
        "seed_role": role,
        "decision_records": records,
        "decision_record_seeds": record_seeds,
        "import_from": imported,
        "planning_seed": planning_seed,
        "allow_seed_overlap": overlap,
        "configs_scope": scope,
    }


def placement_identity(run_config: str, override: int | None) -> dict:
    """Channel-planning seed and planner settings hash, resolved as `evaluate` resolves them.

    Delegates to scripts/baselines (load_baseline, resolve_planning_seed,
    planner_config.load_settings); the hash covers the validated [baseline] and
    engine sections plus the mapping file bytes.
    """
    import dataclasses
    from scripts.baselines.config import load_baseline, resolve_planning_seed
    from scripts.baselines.planner_config import load_settings

    def plain(value):
        return json.loads(
            json.dumps(dataclasses.asdict(value), default=str, sort_keys=True)
        )

    baseline = load_baseline(run_config)
    seed, source = resolve_planning_seed(baseline, override)
    mapping = getattr(baseline, "mapping_file", None)
    mapping_sha = (
        sha256_file(mapping)
        if mapping is not None and Path(mapping).is_file()
        else None
    )
    if mapping is not None and mapping_sha is None:
        raise ValueError(f"{run_config}: [baseline] mapping_file not found: {mapping}")
    settings = {
        "baseline": {k: v for k, v in plain(baseline).items() if k != "planning_seed"},
        "engine": [plain(section) for section in load_settings(run_config)],
        "mapping_sha256": mapping_sha,
    }
    return {
        "planning_seed": seed,
        "planning_seed_source": source,
        "planner_settings_sha256": canonical_sha256(settings),
        "mapping_file": None if mapping is None else str(mapping),
    }


def _scenario(slug: str, raw, base: Path) -> dict:
    where = f"scenarios.{slug}"
    _check_keys(raw, _SCENARIO_KEYS, where)
    run_config = _input_path(raw.get("run_config"), base, f"{where}.run_config")
    configs = {}
    raw_configs = raw.get("configs", {})
    _check_keys(raw_configs, SEED_ROLES, f"{where}.configs")
    for role, entries in raw_configs.items():
        if not isinstance(entries, dict):
            raise ValueError(
                f"{where}.configs.{role} must map seed strings to INI paths"
            )
        configs[role] = {}
        for seed, path in entries.items():
            if not str(seed).isdigit():
                raise ValueError(
                    f"{where}.configs.{role} key {seed!r} must be a seed integer string"
                )
            configs[role][str(seed)] = _input_path(
                path, base, f"{where}.configs.{role}[{seed}]"
            )
    case = _case(raw["case"], f"{where}.case") if raw.get("case") is not None else None
    reference = (
        _reference(raw["reference"], base, run_config["path"], f"{where}.reference")
        if raw.get("reference") is not None
        else None
    )
    baselines = (
        _baselines(raw["baselines"], slug, base, reference is not None)
        if raw.get("baselines") is not None
        else None
    )
    history = raw.get("history_sources", [])
    if not isinstance(history, list):
        raise ValueError(f"{where}.history_sources must be a JSON array of paths")
    history = [
        _input_path(item, base, f"{where}.history_sources[{i}]", "dir")
        for i, item in enumerate(history)
    ]
    return {
        "run_config": run_config,
        "band": _band(raw.get("band"), f"{where}.band"),
        "configs": configs,
        "case": case,
        "reference": reference,
        "baselines": baselines,
        "history_sources": history,
    }


def config_for(scenario: dict, role: str, key: str, row: dict | None = None) -> dict:
    """INI for one seed role and lookup key: row override > scenario configs > run_config.

    `config_source` records which one applied; the run_config fallback is explicit.
    """
    lookup = {"role": role, "key": str(key)}
    entry = ((row or {}).get("configs") or {}).get(role, {}).get(str(key))
    if entry is not None:
        return {**entry, "lookup": lookup, "fallback": False, "config_source": "row"}
    entry = scenario["configs"].get(role, {}).get(str(key))
    if entry is not None:
        return {
            **entry,
            "lookup": lookup,
            "fallback": False,
            "config_source": "scenario",
        }
    return {
        **scenario["run_config"],
        "lookup": lookup,
        "fallback": True,
        "config_source": "run_config",
    }


def _row_configs(raw, base: Path, where: str, roles: tuple[str, ...]) -> dict:
    """Per-row INIs {role: {seed or training lookup key: ini}}."""
    _check_keys(raw, roles, where)
    configs = {}
    for role, entries in raw.items():
        if not isinstance(entries, dict) or not entries:
            raise ValueError(f"{where}.{role} must map seed strings to INI paths")
        configs[role] = {}
        for seed, path in entries.items():
            if not str(seed).isdigit():
                raise ValueError(
                    f"{where}.{role} key {seed!r} must be a seed integer string"
                )
            configs[role][str(seed)] = _input_path(
                path, base, f"{where}.{role}[{seed}]"
            )
    return configs


def _labels(raw, where: str) -> dict:
    _check_keys(raw, _LABEL_KEYS, where)
    labels = {}
    for key in ("reward_label", "ppo_label", "comparison"):
        if key in raw:
            if not isinstance(raw[key], str):
                raise ValueError(f"{where}.{key} must be a string")
            labels[key] = raw[key]
    if "source_phase" in raw:
        if raw["source_phase"] is not None:
            _int(raw["source_phase"], f"{where}.source_phase")
        labels["source_phase"] = raw["source_phase"]
    if "tags" in raw:
        if not isinstance(raw["tags"], list) or not all(
            isinstance(t, str) for t in raw["tags"]
        ):
            raise ValueError(f"{where}.tags must be an array of strings")
        labels["tags"] = list(raw["tags"])
    return labels


def _model_source(raw, base: Path, where: str) -> dict:
    """Verify a completed parent run and its selected model without loading it."""
    _check_keys(raw, ("run_dir", "model"), where)
    run_dir = _input_path(raw.get("run_dir"), base, f"{where}.run_dir", "dir")
    model = raw.get("model", "final")
    manifest_path = Path(run_dir["path"]) / "train_manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"{where}: no train_manifest.json in {run_dir['path']}")
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict) or manifest.get("status") != "completed":
        raise ValueError(f"{where}: parent run is not a completed training run")
    if model == "final":
        path, digest = manifest.get("model_path"), manifest.get("model_sha256")
    elif model == "best":
        path, digest = (
            manifest.get("best_model_path"),
            manifest.get("best_model_sha256"),
        )
        if not path:
            raise ValueError(
                f"{where}: 'best' needs a verified best model; the parent has none"
            )
    else:
        relative = Path(str(model))
        if (
            relative.is_absolute()
            or len(relative.parts) != 2
            or relative.parts[0] != CHECKPOINT_DIR
            or not _CHECKPOINT_RE.match(relative.name)
        ):
            raise ValueError(
                f"{where}.model must be final, best or {CHECKPOINT_DIR}/<file>.zip"
            )
        target = (Path(run_dir["path"]) / relative).resolve()
        entry = next(
            (
                e
                for e in manifest.get("checkpoints") or []
                if Path(e.get("path", "")).resolve() == target
            ),
            None,
        )
        if entry is None:
            raise ValueError(
                f"{where}: {model} is not a retained checkpoint of the parent"
            )
        path, digest = entry.get("path"), entry.get("sha256")
    if not path or not digest or not Path(path).is_file():
        raise ValueError(f"{where}: model file for {model!r} is missing")
    actual = sha256_file(path)
    if actual != digest:
        raise ValueError(f"{where}: model digest mismatch for {path}")
    counters = checkpoint_counters(path, require_updates=False)
    source = {
        "run_dir": run_dir["path"],
        "reference": run_dir["reference"],
        "model": model,
        "model_path": str(Path(path).resolve()),
        "model_sha256": digest,
        "manifest_sha256": sha256_file(manifest_path),
        "num_timesteps": counters["num_timesteps"],
        "n_updates": counters["n_updates"],
        "seed": manifest.get("seed"),
        "selection": manifest.get("selection"),
        "run_ini_sha256": (manifest.get("scenario_identity") or {}).get(
            "run_ini_sha256"
        ),
        "hyperparameters": manifest.get("hyperparameters") or {},
    }
    source["digest"] = canonical_sha256(
        {k: source[k] for k in ("manifest_sha256", "model", "model_sha256")}
    )
    return source


def retained_checkpoints(start: int, total: int, every: int, keep: int) -> list[int]:
    """Cumulative steps of the checkpoints a completed run retains (newest `keep`)."""
    if every <= 0:
        return []
    first = (start // every + 1) * every
    return list(range(first, total + 1, every))[-keep:]


def _selection_fields(
    raw: dict, run_config: str, where: str, required: bool
) -> dict | None:
    present = [key for key in _ROW_SELECTION_KEYS if key in raw]
    if not present and not required:
        return None
    preset = _scalar(raw.get("observation_preset"), f"{where}.observation_preset")
    if not isinstance(preset, str) or not preset:
        raise ValueError(f"{where}.observation_preset must be a string")
    profile = _scalar(raw.get("action_profile"), f"{where}.action_profile")
    components = _string_array(
        raw.get("reward_components"), f"{where}.reward_components"
    )
    weights = _weight_array(raw.get("reward_weights"), f"{where}.reward_weights")
    configured = read_action_profile(run_config)
    if profile != configured:
        raise ValueError(
            f"{where}.action_profile is {profile!r} but {run_config} "
            f"configures {configured!r}"
        )
    try:
        selection = resolve_selection(
            run_config,
            observation_preset=preset,
            reward_components=",".join(components),
            reward_weights=",".join(str(w) for w in weights),
            observation_parameters=raw.get("observation_parameters"),
            reward_parameters=raw.get("reward_parameters"),
        )
    except ValueError as exc:
        raise ValueError(f"{where}: {exc}") from exc
    return {
        "observation_preset": preset,
        "action_profile": profile,
        "reward_components": components,
        "reward_weights": weights,
        "observation_parameters": selection.observation_parameters,
        "reward_parameters": selection.reward_parameters,
    }


def _check_parent_selection(selection: dict | None, parent: dict, where: str) -> None:
    saved = parent.get("selection") or {}
    if selection is None:
        return
    for key in (
        "observation_preset",
        "reward_components",
        "reward_weights",
        "observation_parameters",
        "reward_parameters",
    ):
        if key in saved and saved[key] != selection[key]:
            raise ValueError(
                f"{where}: {key} differs from the parent model's selection"
            )


def _row(raw, index: int, kind: str, context: dict) -> dict:
    where = f"rows[{index}]"
    _check_keys(raw, _ROW_KEYS[kind], where)
    name = _name(_scalar(raw.get("name"), f"{where}.name"), f"{where}.name")
    where = f"row {name}"
    scenario_name = raw.get("scenario")
    if scenario_name not in context["scenarios"]:
        raise ValueError(
            f"{where}.scenario {scenario_name!r} is not declared in scenarios"
        )
    scenario = context["scenarios"][scenario_name]
    profile = raw.get("profile")
    if kind == "train" or profile is not None:
        profile = _name(profile, f"{where}.profile")
    base = context["base"]
    row = {
        "name": name,
        "scenario": scenario_name,
        "profile": profile,
        "labels": _labels(raw.get("labels", {}), f"{where}.labels"),
        "training": None,
        "training_seeds": [],
        "training_config_key": None,
        "continue_from": None,
        "model_source": None,
        "curriculum": None,
        "operations": [],
        "selection": None,
        "configs": {},
    }
    if raw.get("configs") is not None:
        roles = SEED_ROLES if kind == "train" else OPERATION_SEED_ROLES
        row["configs"] = _row_configs(raw["configs"], base, f"{where}.configs", roles)
        for role, entries in row["configs"].items():
            if role == "training":
                continue  # lookup keys, checked against training_config_key/seeds below
            unused = sorted(
                int(seed) for seed in entries if int(seed) not in context["seeds"][role]
            )
            if unused:
                raise ValueError(
                    f"{where}.configs.{role} names seeds {unused} that are not "
                    f"declared {role} seeds"
                )
    operation_ids = [op["id"] for op in context["operations"]]
    if "operations" in raw:
        row["operations"] = _distinct_names(raw["operations"], f"{where}.operations")
        unknown = [op for op in row["operations"] if op not in operation_ids]
        if unknown:
            raise ValueError(f"{where}.operations {unknown} are not declared")
    else:
        row["operations"] = operation_ids

    if kind == "train":
        overrides = _training(
            raw.get("training", {}), f"{where}.training", override=True
        )
        merged = {**context["training"], **overrides}
        row["training"] = _training(merged, f"{where} effective training")
        seeds = raw.get("seeds")
        if seeds is not None:
            _check_keys(seeds, ("training",), f"{where}.seeds")
            row["training_seeds"] = _seed_list(
                seeds.get("training", []), f"{where}.seeds.training"
            )
        else:
            row["training_seeds"] = list(context["seeds"]["training"])
        if not row["training_seeds"]:
            raise ValueError(
                f"{where} has no training seed; kind 'train' needs at least one"
            )
        _check_disjoint(
            {
                "row training": set(row["training_seeds"]),
                **{
                    f"seeds.{r}": set(context["seeds"][r]) for r in OPERATION_SEED_ROLES
                },
            }
        )
        key = raw.get("training_config_key")
        if key is not None:
            if isinstance(key, bool) or not str(key).isdigit():
                raise ValueError(
                    f"{where}.training_config_key must be a seed integer or string"
                )
            if str(key) not in row["configs"].get("training", {}) and str(
                key
            ) not in scenario["configs"].get("training", {}):
                raise ValueError(
                    f"{where}.training_config_key {key} has no rows[].configs.training "
                    f"or scenarios.{scenario_name}.configs.training entry"
                )
            row["training_config_key"] = str(key)
        used = (
            {row["training_config_key"]}
            if row["training_config_key"]
            else {str(seed) for seed in row["training_seeds"]}
        )
        unused = sorted(set(row["configs"].get("training", {})) - used)
        if unused:
            raise ValueError(
                f"{where}.configs.training keys {unused} match neither "
                "training_config_key nor the row's training seeds"
            )
        if raw.get("curriculum") is not None:
            row["curriculum"] = _input_path(
                raw["curriculum"], base, f"{where}.curriculum"
            )
        configs = [
            config_for(scenario, "training", row["training_config_key"] or seed, row)
            for seed in row["training_seeds"]
        ]
        selections = [
            _selection_fields(raw, c["path"], where, required=True) for c in configs
        ]
        if any(s != selections[0] for s in selections[1:]):
            raise ValueError(
                f"{where}: the selection resolves differently across training configs"
            )
        row["selection"] = selections[0]
        config = configs[0]
        if raw.get("continue_from") is not None:
            parent = _model_source(raw["continue_from"], base, f"{where}.continue_from")
            if len(row["training_seeds"]) != 1:
                raise ValueError(
                    f"{where}: a continuation names exactly one training seed"
                )
            if parent["seed"] != row["training_seeds"][0]:
                raise ValueError(
                    f"{where}: continuation seed {row['training_seeds'][0]} differs "
                    f"from the parent's seed {parent['seed']}"
                )
            if row["training"]["total_timesteps"] <= parent["num_timesteps"]:
                raise ValueError(
                    f"{where}: total_timesteps {row['training']['total_timesteps']} "
                    f"must exceed the parent's {parent['num_timesteps']} "
                    "(it includes the parent's steps)"
                )
            if parent["run_ini_sha256"] and parent["run_ini_sha256"] != sha256_file(
                config["path"]
            ):
                raise ValueError(
                    f"{where}: training INI bytes differ from the parent's "
                    "strict resume identity"
                )
            for key_name, value in parent["hyperparameters"].items():
                if (
                    key_name in PPO_FIELDS
                    and key_name != "total_timesteps"
                    and key_name in row["training"]
                ):
                    declared = row["training"][key_name]
                    if key_name == "net_arch":
                        declared, value = list(declared), list(value)
                    if declared != value:
                        raise ValueError(
                            f"{where}: {key_name} differs from the parent's PPO settings"
                        )
            _check_parent_selection(row["selection"], parent, where)
            row["continue_from"] = parent
        decisions = {native_decisions(c["path"]) for c in configs}
        if len(decisions) != 1:
            raise ValueError(
                f"{where}: training configs differ in decisions per episode {sorted(decisions)}"
            )
        _check_training_budget(row, config["path"], context, where)
    elif kind == "evaluate":
        if raw.get("model_source") is None:
            raise ValueError(f"{where}.model_source is required for kind 'evaluate'")
        row["model_source"] = _model_source(
            raw["model_source"], base, f"{where}.model_source"
        )
        row["selection"] = _selection_fields(
            raw, scenario["run_config"]["path"], where, required=False
        )
        _check_parent_selection(row["selection"], row["model_source"], where)
    else:
        row["selection"] = _selection_fields(
            raw, scenario["run_config"]["path"], where, required=True
        )
    return row


def _check_training_budget(
    row: dict, run_config: str, context: dict, where: str
) -> None:
    training = row["training"]
    total = training.get("total_timesteps")
    if total is None:
        raise ValueError(
            f"{where}: training.total_timesteps is required for kind 'train'"
        )
    decisions = native_decisions(run_config)
    row["decisions_per_episode"] = decisions
    if training.get("decisions_per_episode") not in (None, decisions):
        raise ValueError(
            f"{where}: decisions_per_episode {training['decisions_per_episode']} "
            f"disagrees with the native timing ({decisions}) of {run_config}"
        )
    if "total_episodes" in training and training["total_episodes"] * decisions != total:
        raise ValueError(
            f"{where}: total_episodes {training['total_episodes']} x {decisions} "
            f"decisions != total_timesteps {total}"
        )
    every = training.get("eval_every_steps", 0)
    timing = training["checkpoint_timing"]
    cadence = training.get("checkpoint_every_steps", 0)
    keep = training.get("keep_checkpoints", 3)
    n_steps = training.get("n_steps", 1024)
    start = row["continue_from"]["num_timesteps"] if row["continue_from"] else 0
    if timing == "standard":
        mission = (
            parse_ini(run_config).get("mission", {}).get("kind", "none").lower()
            != "none"
        )
        if (not mission or total % n_steps == 0) and (total - start) % n_steps:
            raise ValueError(
                f"{where}: standard training without an active exact-budget callback needs a remaining budget "
                f"divisible by n_steps ({total - start} % {n_steps} != 0); "
                "SB3 otherwise overshoots the requested budget"
            )
    if timing == "after_update":
        if every:
            raise ValueError(
                f"{where}: after_update checkpoints run without in-training "
                "validation; set eval_every_steps to 0"
            )
        problems = []
        if cadence <= 0:
            problems.append("checkpoint_every_steps must be positive")
        else:
            if cadence % n_steps:
                problems.append(
                    f"cadence {cadence} is not a multiple of the rollout {n_steps}"
                )
            if cadence % decisions:
                problems.append(
                    f"cadence {cadence} does not end complete {decisions}-decision episodes"
                )
            if total % cadence:
                problems.append(
                    f"total_timesteps {total} is not a multiple of the cadence {cadence}"
                )
            if start % n_steps:
                problems.append(f"parent steps {start} are not on a rollout boundary")
        if problems:
            raise ValueError(
                f"{where}: impossible after_update schedule ({'; '.join(problems)}); "
                "the budget is never extended automatically"
            )
    if every > 0 and not context["seeds"]["model_selection"]:
        raise ValueError(f"{where}: training validation needs seeds.model_selection")
    if (
        timing != "after_update"
        and context["execution"].get("recovery") == "checkpoint"
    ):
        raise ValueError(
            f"{where}: execution.recovery 'checkpoint' needs after_update checkpoints"
        )
    retained = retained_checkpoints(start, total, cadence, keep)
    row["retained_checkpoints"] = retained
    for op in context["operations"]:
        if op["id"] not in row["operations"]:
            continue
        for selector in op["at_steps"]:
            if selector == "best" and every <= 0:
                raise ValueError(
                    f"{where}: operation {op['id']} selects 'best' but training "
                    "validation (eval_every_steps > 0) is off"
                )
            if isinstance(selector, int) and selector not in retained:
                raise ValueError(
                    f"{where}: operation {op['id']} needs checkpoint {selector}, "
                    f"which is not retained until consumers finish "
                    f"(retained: {retained})"
                )


def _execution(raw, base: Path) -> dict:
    _check_keys(raw, _EXECUTION_KEYS, "execution")
    execution = {}
    for key in ("workers", "threads_per_worker"):
        if key in raw:
            execution[key] = _positive_int(raw[key], f"execution.{key}")
    if "nice" in raw:
        execution["nice"] = _int(raw["nice"], "execution.nice")
        if not 0 <= execution["nice"] <= 19:
            raise ValueError("execution.nice must be in [0,19]")
    if "failure_policy" in raw:
        if raw["failure_policy"] not in FAILURE_POLICIES:
            raise ValueError(
                f"execution.failure_policy must be one of {list(FAILURE_POLICIES)}"
            )
        execution["failure_policy"] = raw["failure_policy"]
    recovery = raw.get("recovery", "none")
    if recovery not in RECOVERY_MODES:
        raise ValueError(f"execution.recovery must be one of {list(RECOVERY_MODES)}")
    execution["recovery"] = recovery
    execution["resource_pool"] = None
    if raw.get("resource_pool") is not None:
        pool = raw["resource_pool"]
        _check_keys(pool, ("directory", "capacity"), "execution.resource_pool")
        execution["resource_pool"] = {
            **_output_path(
                pool.get("directory"), base, "execution.resource_pool.directory"
            ),
            "capacity": _positive_int(
                pool.get("capacity"), "execution.resource_pool.capacity"
            ),
        }
    return execution


def _checks(raw, matrix: dict) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("checks must be a JSON array")
    checks = []
    declared = {seed for values in matrix["seeds"].values() for seed in values}
    for index, entry in enumerate(raw):
        where = f"checks[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} must be a JSON object")
        kind = entry.get("kind")
        if kind not in CHECK_KINDS:
            raise ValueError(
                f"{where}.kind must be one of {list(CHECK_KINDS)}, got {kind!r}"
            )
        if kind == "preflight":
            raise ValueError(
                f"{where}: preflight is reserved in batch matrices; "
                "run python -m scripts.rl.operate preflight separately"
            )
        allowed = {
            "preflight": (
                "id",
                "kind",
                "scenario",
                "seeds",
                "requirements",
                "applies_to",
            ),
            "replay_gate": (
                "id",
                "kind",
                "scenario",
                "seeds",
                "source",
                "applies_to",
                "comparison",
                "parent",
                "case",
                "contact_audit",
            ),
            "reward_audit": (
                "id",
                "kind",
                "scenario",
                "method",
                "row",
                "source",
                "applies_to",
            ),
        }[kind]
        _check_keys(entry, allowed, where)
        check_id = _name(entry.get("id"), f"{where}.id")
        where = f"check {check_id}"
        scenario = entry.get("scenario")
        if scenario not in matrix["scenarios"]:
            raise ValueError(f"{where}.scenario {scenario!r} is not declared")
        check = {
            "id": check_id,
            "kind": kind,
            "scenario": scenario,
            "applies_to": _applies_to(entry.get("applies_to"), matrix, where),
        }
        if kind in ("preflight", "replay_gate"):
            seeds = _seed_list(entry.get("seeds"), f"{where}.seeds")
            if not seeds:
                raise ValueError(f"{where}.seeds must name the seeds to check")
            unknown = [s for s in seeds if s not in declared]
            if unknown:
                raise ValueError(
                    f"{where}.seeds {unknown} are not declared in any seed role"
                )
            check["seeds"] = seeds
        if kind == "preflight":
            requirements = entry.get("requirements", [])
            check["requirements"] = _distinct_names(
                requirements, f"{where}.requirements"
            )
        if kind == "replay_gate":
            check["sources"] = _check_source(
                entry.get("source"), matrix, scenario, where, check["seeds"]
            )
            from scripts.rl.policy.replay_gate import COMPARISONS

            comparison = entry.get("comparison", "strict_v1")
            if comparison not in COMPARISONS:
                raise ValueError(
                    f"{where}.comparison must be one of {sorted(COMPARISONS)}"
                )
            check["comparison"] = comparison
            check["parent"] = (
                _model_source(
                    entry["parent"], Path(matrix["path"]).parent, f"{where}.parent"
                )
                if entry.get("parent") is not None
                else None
            )
            check["case"] = (
                _case(entry["case"], f"{where}.case")
                if entry.get("case") is not None
                else matrix["scenarios"][scenario]["case"]
            )
            check["contact_audit"] = _bool(
                entry.get("contact_audit", False), f"{where}.contact_audit"
            )
        if kind == "reward_audit":
            check["source"] = _check_source(
                entry.get("source"), matrix, scenario, where
            )
        if kind == "reward_audit":
            check["method"] = _name(entry.get("method"), f"{where}.method")
            row = next(
                (r for r in matrix["rows"] if r["name"] == entry.get("row")), None
            )
            if row is None or row["scenario"] != scenario or row["selection"] is None:
                raise ValueError(
                    f"{where}.row must name a row of scenario {scenario} with a "
                    "reward selection"
                )
            check["row"] = row["name"]
        checks.append(check)
    _distinct_names([c["id"] for c in checks], "check ids")
    return checks


def _applies_to(raw, matrix: dict, where: str) -> dict | None:
    """Rows/scenarios whose train/operate tasks depend on a check; None = the check's scenario."""
    if raw is None:
        return None
    _check_keys(raw, ("rows", "scenarios"), f"{where}.applies_to")
    rows = _distinct_names(raw.get("rows", []), f"{where}.applies_to.rows")
    scenarios = _distinct_names(
        raw.get("scenarios", []), f"{where}.applies_to.scenarios"
    )
    if not rows and not scenarios:
        raise ValueError(f"{where}.applies_to must name rows and/or scenarios")
    known_rows = {row["name"] for row in matrix["rows"]}
    unknown = [r for r in rows if r not in known_rows] + [
        s for s in scenarios if s not in matrix["scenarios"]
    ]
    if unknown:
        raise ValueError(f"{where}.applies_to names unknown rows/scenarios {unknown}")
    return {"rows": rows, "scenarios": scenarios}


def check_dependents(check: dict, rows: list[dict]) -> list[str]:
    """Row names whose train/operate tasks need this check, in row order."""
    applies = check["applies_to"]
    if applies is None:
        return [row["name"] for row in rows if row["scenario"] == check["scenario"]]
    return [
        row["name"]
        for row in rows
        if row["name"] in applies["rows"] or row["scenario"] in applies["scenarios"]
    ]


def baseline_config_owners(matrix: dict, slug: str) -> list[dict | None]:
    """Rows providing baseline INIs, with None denoting the scenario INI."""
    if matrix["scenarios"][slug]["baselines"]["configs_scope"] == "scenario":
        return [None]
    rows = [row for row in matrix["rows"] if row["scenario"] == slug]
    for check in matrix["checks"]:
        if check["scenario"] != slug:
            continue
        if check["kind"] == "replay_gate" and any(
            source["kind"] == "baseline" for source in check["sources"].values()
        ):
            return [None, *rows]
        if check["kind"] == "reward_audit" and check["source"]["kind"] == "baseline":
            return [None, *rows]
    return rows or [None]


def _validate_placement(matrix: dict) -> None:
    """Placement baselines resolve a dedicated planning seed outside every seed role."""
    declared = {
        seed: role for role, values in matrix["seeds"].items() for seed in values
    }
    for slug, scenario in matrix["scenarios"].items():
        baselines = scenario["baselines"]
        if baselines is None or not any(
            p in PLACEMENT_POLICIES for p in baselines["policies"]
        ):
            continue
        owners = [None] + (
            [row for row in matrix["rows"] if row["scenario"] == slug]
            if baselines["configs_scope"] == "rows"
            else []
        )
        for seed in matrix["seeds"][baselines["seed_role"]]:
            for owner in owners:
                path = config_for(scenario, baselines["seed_role"], seed, owner)["path"]
                try:
                    planning = placement_identity(path, baselines["planning_seed"])
                except ValueError as exc:
                    raise ValueError(f"scenarios.{slug}.baselines: {exc}") from exc
                if (
                    planning["planning_seed"] in declared
                    and not baselines["allow_seed_overlap"]
                ):
                    raise ValueError(
                        f"scenarios.{slug}.baselines: planning seed "
                        f"{planning['planning_seed']} overlaps seeds."
                        f"{declared[planning['planning_seed']]}; use a dedicated seed"
                    )


def _check_source(
    raw, matrix: dict, scenario: str, where: str, seeds: list[int] | None = None
):
    """One source episode per seed: a batch baseline policy (its seed-matched episode) or a path.

    With `seeds` (replay gate) the result maps each seed to its own source; a
    path names one recorded episode and therefore serves exactly one seed.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"{where}.source must be {{baseline[, seed]}} or {{path}}")
    if "path" in raw:
        _check_keys(raw, ("path",), f"{where}.source")
        resolved = {
            "kind": "path",
            **_input_path(raw["path"], matrix["base"], f"{where}.source.path", "dir"),
        }
        if seeds is None:
            return resolved
        if len(seeds) != 1:
            raise ValueError(
                f"{where}: a source path is one episode for one seed; "
                f"split the check per seed (got seeds {seeds})"
            )
        return {seeds[0]: resolved}
    _check_keys(raw, ("baseline", "seed"), f"{where}.source")
    baselines = matrix["scenarios"][scenario]["baselines"]
    policy = raw.get("baseline")
    if baselines is None or policy not in baselines["policies"]:
        raise ValueError(
            f"{where}.source.baseline {policy!r} is not a baseline of {scenario}"
        )
    allowed = matrix["seeds"][baselines["seed_role"]]
    if seeds is None:
        seed = raw.get("seed")
        if seed not in allowed:
            raise ValueError(
                f"{where}.source.seed {seed!r} is not a {baselines['seed_role']} seed"
            )
        return {"kind": "baseline", "policy": policy, "seed": seed}
    if "seed" in raw and [raw["seed"]] != seeds:
        raise ValueError(
            f"{where}.source.seed must be omitted or equal the check's single seed; "
            "each seed replays its own baseline episode"
        )
    missing = [seed for seed in seeds if seed not in allowed]
    if missing:
        raise ValueError(
            f"{where}: seeds {missing} have no {policy} baseline episode "
            f"(baseline seed role {baselines['seed_role']})"
        )
    return {
        seed: {"kind": "baseline", "policy": policy, "seed": seed} for seed in seeds
    }


def _stages(raw, matrix: dict) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("stages must be a JSON array")
    row_names = [row["name"] for row in matrix["rows"]]
    stages, membership = [], {}
    for index, entry in enumerate(raw):
        _check_keys(entry, _STAGE_KEYS, f"stages[{index}]")
        name = _name(entry.get("name"), f"stages[{index}].name")
        rows = _distinct_names(entry.get("rows"), f"stage {name}.rows")
        needs = _distinct_names(entry.get("needs", []), f"stage {name}.needs")
        known = [s["name"] for s in stages]
        if any(need not in known for need in needs):
            raise ValueError(
                f"stage {name}.needs must name earlier stages, got {needs}"
            )
        for row in rows:
            if row not in row_names:
                raise ValueError(f"stage {name} lists unknown row {row!r}")
            if row in membership:
                raise ValueError(
                    f"row {row} belongs to stages {membership[row]} and {name}"
                )
            membership[row] = name
        stage = {"name": name, "rows": rows, "needs": needs, "selection": None}
        if entry.get("selection") is not None:
            stage["selection"] = _stage_selection(entry["selection"], stage, matrix)
        stages.append(stage)
    if stages:
        missing = [row for row in row_names if row not in membership]
        if missing:
            raise ValueError(f"rows {missing} belong to no stage")
    _distinct_names([s["name"] for s in stages], "stage names")
    claimed = {}
    for stage in stages:
        selection = stage["selection"]
        if selection is None:
            continue
        candidate_entries = {
            _entry_key(e) for es in selection["candidates"].values() for e in es
        }
        for candidate, entries in selection["branches"].items():
            for entry in entries:
                row = entry if isinstance(entry, str) else entry["row"]
                owner = membership.get(row)
                later = owner is not None and stage["name"] in _stage_ancestors(
                    stages, owner
                )
                if isinstance(entry, str) and not later:
                    raise ValueError(
                        f"stage {stage['name']} branch row {row} must be in a later "
                        "stage that needs it"
                    )
                if not isinstance(entry, str):
                    if not (later or owner == stage["name"]):
                        raise ValueError(
                            f"stage {stage['name']} branch {row}/{entry['operation']} "
                            "must be a row of this stage or of a later stage that needs it"
                        )
                    if _entry_key(entry) in candidate_entries:
                        raise ValueError(
                            f"stage {stage['name']} branch {row}/{entry['operation']} "
                            "is also a candidate source"
                        )
                key = _entry_key(entry)
                if (
                    key in claimed
                    or row in claimed
                    or (
                        isinstance(entry, str)
                        and any(isinstance(k, tuple) and k[0] == row for k in claimed)
                    )
                ):
                    raise ValueError(
                        f"{key if isinstance(key, str) else '/'.join(key)} is a branch "
                        "of two selections"
                    )
                claimed[key] = (stage["name"], candidate)
    return stages


def _entry_key(entry):
    return entry if isinstance(entry, str) else (entry["row"], entry["operation"])


def _selection_entries(raw, where: str, rows: dict, allowed_rows: list[str] | None):
    """A selection list holds row names or {row, operation} entries, never both."""
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{where} must be a non-empty JSON array")
    if all(isinstance(e, str) for e in raw):
        names = _distinct_names(raw, where)
        if allowed_rows is not None and any(n not in allowed_rows for n in names):
            raise ValueError(f"{where} must list rows of this stage")
        if any(n not in rows for n in names):
            raise ValueError(f"{where} lists unknown rows")
        return "rows", names
    if not all(isinstance(e, dict) for e in raw):
        raise ValueError(f"{where} mixes row names and {{row, operation}} entries")
    entries = []
    for entry in raw:
        _check_keys(entry, ("row", "operation"), where)
        row, op = entry.get("row"), entry.get("operation")
        if row not in rows or (allowed_rows is not None and row not in allowed_rows):
            raise ValueError(f"{where}: {row!r} is not a row of this stage")
        if op not in rows[row]["operations"]:
            raise ValueError(f"{where}: row {row} does not declare operation {op!r}")
        entries.append({"row": row, "operation": op})
    if len({_entry_key(e) for e in entries}) != len(entries):
        raise ValueError(f"{where} must be distinct")
    return "operations", entries


def _selector(value, where: str):
    if value in ("final", "best"):
        return value
    return _positive_int(value, where)


def model_selector(model) -> object:
    """Checkpoint selector of an imported model: final, best or its cumulative steps."""
    if model in ("final", "best"):
        return model
    match = _CHECKPOINT_RE.match(Path(str(model)).name)
    return int(match.group(1)) if match else str(model)


def _stage_ancestors(stages: list[dict], name: str) -> set[str]:
    by_name = {s["name"]: s for s in stages}
    seen, todo = set(), list(by_name[name]["needs"])
    while todo:
        current = todo.pop()
        if current not in seen:
            seen.add(current)
            todo.extend(by_name[current]["needs"])
    return seen


def _stage_selection(raw, stage: dict, matrix: dict) -> dict:
    where = f"stage {stage['name']}.selection"
    _check_keys(raw, _SELECTION_KEYS, where)
    rule = raw.get("rule")
    if rule not in SELECTION_RULES:
        raise ValueError(
            f"{where}.rule must be one of {list(SELECTION_RULES)}, got {rule!r}"
        )
    rows = {r["name"]: r for r in matrix["rows"]}
    candidates = raw.get("candidates")
    if not isinstance(candidates, dict) or len(candidates) < 2:
        raise ValueError(
            f"{where}.candidates must map at least two candidate names to rows "
            "or {row, operation} entries"
        )
    forms, resolved_candidates = set(), {}
    for candidate, entries in candidates.items():
        _name(candidate, f"{where}.candidates key")
        form, resolved = _selection_entries(
            entries, f"{where}.candidates.{candidate}", rows, stage["rows"]
        )
        forms.add(form)
        resolved_candidates[candidate] = resolved
    if len(forms) != 1:
        raise ValueError(f"{where}.candidates mix rows and {{row, operation}} entries")
    form = forms.pop()
    branches = raw.get("branches", {})
    if not isinstance(branches, dict) or set(branches) - set(resolved_candidates):
        raise ValueError(
            f"{where}.branches must map candidate names to rows or "
            "{row, operation} entries"
        )
    resolved_branches = {}
    for candidate, entries in branches.items():
        branch_form, resolved = _selection_entries(
            entries, f"{where}.branches.{candidate}", rows, None
        )
        if branch_form != form:
            raise ValueError(f"{where}.branches must use the candidates' form ({form})")
        resolved_branches[candidate] = resolved
    selection = {
        "rule": rule,
        "form": form,
        "candidates": resolved_candidates,
        "branches": resolved_branches,
        "source_operation": None,
        "source_checkpoint": None,
        "seed_role": None,
        "settings": {},
    }
    if rule == "replay":
        winners = _distinct_names(raw.get("winners"), f"{where}.winners")
        if not winners or any(w not in resolved_candidates for w in winners):
            raise ValueError(f"{where}.winners must name declared candidates")
        provenance = raw.get("provenance")
        if not isinstance(provenance, str) or not provenance:
            raise ValueError(f"{where}.provenance must describe the recorded selection")
        if "source_checkpoint" in raw or "source_operation" in raw:
            raise ValueError(f"{where}: rule 'replay' takes no sources")
        selection["settings"] = {"winners": winners, "provenance": provenance}
        return selection
    for key in ("winners", "provenance"):
        if key in raw:
            raise ValueError(f"{where}.{key} is only valid for rule 'replay'")
    if rule == "legacy-validation-profile-v1":
        if form != "rows":
            raise ValueError(
                f"{where}: {rule} ranks training validation of row candidates"
            )
        decisions = _positive_int(
            raw.get("normalization_decisions"), f"{where}.normalization_decisions"
        )
        selection["settings"] = {"normalization_decisions": decisions}
        selection["seed_role"] = "model_selection"
        for candidate_rows in resolved_candidates.values():
            for name in candidate_rows:
                if (
                    rows[name]["training"] is None
                    or rows[name]["training"].get("eval_every_steps", 0) <= 0
                ):
                    raise ValueError(
                        f"{where}: row {name} has no training validation to rank"
                    )
        for key in ("source_operation", "source_checkpoint"):
            if key in raw:
                raise ValueError(
                    f"{where}: {rule} ranks training validation; remove {key}"
                )
        return selection
    ops = {o["id"]: o for o in (matrix["evaluation"] or {}).get("operations", [])}
    if form == "rows":
        if raw.get("source_operation") not in ops:
            raise ValueError(f"{where}.source_operation must name a declared operation")
        pairs = [
            (row, raw["source_operation"])
            for rs in resolved_candidates.values()
            for row in rs
        ]
        for row, op_id in pairs:
            if op_id not in rows[row]["operations"]:
                raise ValueError(f"{where}: candidate row {row} does not run {op_id}")
    else:
        if "source_operation" in raw:
            raise ValueError(
                f"{where}: operation candidates use their own operation; "
                "remove source_operation"
            )
        # Each entry operates its own row's model; no training task is added.
        pairs = [
            (e["row"], e["operation"])
            for es in resolved_candidates.values()
            for e in es
        ]
    roles = {ops[op_id]["seed_role"] for _, op_id in pairs}
    if "held_out" in roles:
        raise ValueError(f"{where}: selection never consumes held-out operations")
    if len(roles) != 1:
        raise ValueError(
            f"{where}: candidate operations mix seed roles {sorted(roles)}"
        )
    if rule == "legacy-online-profile-v1":
        offline = sorted(
            {op_id for _, op_id in pairs if ops[op_id]["mode"] not in ONLINE_MODES}
        )
        if offline:
            raise ValueError(f"{where}: {rule} ranks online operations, got {offline}")
    checkpoint = _selector(
        raw.get("source_checkpoint", "final"), f"{where}.source_checkpoint"
    )
    for row, op_id in pairs:
        source = rows[row]["model_source"]
        available = (
            [model_selector(source["model"])]
            if source is not None
            else ops[op_id]["at_steps"]
        )
        if checkpoint not in available:
            raise ValueError(
                f"{where}: source_checkpoint {checkpoint!r} is not an operated "
                f"checkpoint of {row}/{op_id} ({available})"
            )
    retain = _distinct_names(raw.get("retain", []), f"{where}.retain")
    if rule == "legacy-mission-profile-v1":
        if any(r not in resolved_candidates for r in retain):
            raise ValueError(f"{where}.retain must name declared candidates")
        if len(retain) >= len(resolved_candidates):
            raise ValueError(
                f"{where}: at least one candidate must compete for selection"
            )
    elif retain:
        raise ValueError(f"{where}.retain is only valid for legacy-mission-profile-v1")
    if "normalization_decisions" in raw:
        raise ValueError(
            f"{where}.normalization_decisions belongs to legacy-validation-profile-v1"
        )
    selection.update(
        source_operation=raw.get("source_operation"),
        source_checkpoint=checkpoint,
        seed_role=roles.pop(),
        settings={"retain": retain},
    )
    return selection


def read_matrix_version(path) -> int:
    """matrix_version of a matrix file, read before choosing its validator."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read matrix {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("matrix must be a JSON object")
    return data.get("matrix_version")


def load_matrix_v2(path, rows: list[str] | None = None) -> dict:
    """Validate a version 2 batch matrix; relative paths resolve from its directory."""
    matrix_path = Path(path).resolve()
    data = json.loads(matrix_path.read_text())
    _check_keys(data, _TOP_KEYS, "matrix")
    if data.get("matrix_version") != MATRIX_V2_VERSION:
        raise ValueError(
            f"matrix_version must be {MATRIX_V2_VERSION}, got "
            f"{data.get('matrix_version')!r}"
        )
    base = matrix_path.parent
    name = _name(data.get("name"), "name")
    description = data.get("description", "")
    if not isinstance(description, str):
        raise ValueError("description must be a string")
    kind = data.get("kind")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {list(KINDS)}, got {kind!r}")
    raw_scenarios = data.get("scenarios")
    if not isinstance(raw_scenarios, dict) or not raw_scenarios:
        raise ValueError("scenarios must map at least one slug to a scenario")
    scenarios = {
        _name(slug, "scenarios key"): _scenario(slug, raw, base)
        for slug, raw in raw_scenarios.items()
    }
    seeds = _seeds(data.get("seeds", {}))
    if kind != "train":
        if "training" in data:
            raise ValueError(
                f"kind {kind!r} has no training settings; remove 'training'"
            )
        if seeds["training"]:
            raise ValueError(
                f"kind {kind!r} takes no training seeds; remove seeds.training"
            )
    if kind == "checks" and "evaluation" in data:
        raise ValueError("kind 'checks' has no model operations; remove 'evaluation'")
    if kind in ("train", "evaluate") and "evaluation" not in data:
        raise ValueError(f"kind {kind!r} needs evaluation.operations")
    training = (
        _training(data.get("training", {}), "training") if kind == "train" else None
    )
    if kind == "train" and "total_timesteps" not in training:
        raise ValueError("training.total_timesteps is required for kind 'train'")
    evaluation = (
        _evaluation(data["evaluation"], kind, scenarios)
        if "evaluation" in data
        else None
    )
    operations = evaluation["operations"] if evaluation else []
    for op in operations:
        if not seeds[op["seed_role"]]:
            raise ValueError(
                f"operation {op['id']} uses seed role {op['seed_role']!r}, "
                "which has no seeds"
            )
        outside = [
            s
            for s in op["decision_record_seeds"] or []
            if s not in seeds[op["seed_role"]]
        ]
        if outside:
            raise ValueError(
                f"operation {op['id']}.decision_record_seeds {outside} are not "
                f"{op['seed_role']} seeds"
            )
    for slug, scenario in scenarios.items():
        if scenario["baselines"] and not seeds[scenario["baselines"]["seed_role"]]:
            raise ValueError(f"scenarios.{slug}.baselines seed role has no seeds")
        if scenario["baselines"]:
            role = scenario["baselines"]["seed_role"]
            outside = [
                s
                for s in scenario["baselines"]["decision_record_seeds"] or []
                if s not in seeds[role]
            ]
            if outside:
                raise ValueError(
                    f"scenarios.{slug}.baselines.decision_record_seeds {outside} are "
                    f"not {role} seeds"
                )
    execution = _execution(data.get("execution", {}), base)
    context = {
        "scenarios": scenarios,
        "seeds": seeds,
        "training": training or {},
        "operations": operations,
        "base": base,
        "execution": execution,
    }
    raw_rows = data.get("rows", [])
    if not isinstance(raw_rows, list):
        raise ValueError("rows must be a JSON array")
    if kind != "checks" and not raw_rows:
        raise ValueError(f"kind {kind!r} needs at least one row")
    all_rows = [
        _row(entry, index, kind, context) for index, entry in enumerate(raw_rows)
    ]
    _distinct_names([row["name"] for row in all_rows], "row names")
    matrix = {
        "matrix_version": MATRIX_V2_VERSION,
        "path": str(matrix_path),
        "reference": str(path),
        "directory": str(base),
        "base": base,
        "sha256": sha256_file(matrix_path),
        "name": name,
        "description": description,
        "kind": kind,
        "scenarios": scenarios,
        "seeds": seeds,
        "training": training,
        "evaluation": evaluation,
        "execution": execution,
        "rows": all_rows,
    }
    matrix["checks"] = _checks(data.get("checks", []), matrix)
    if (
        kind == "checks"
        and not matrix["checks"]
        and not any(s["baselines"] for s in scenarios.values())
    ):
        raise ValueError(
            "kind 'checks' needs at least one registered check or baseline policy"
        )
    matrix["stages"] = _stages(data.get("stages", []), matrix)
    _validate_baseline_gates(matrix)
    _validate_operation_fit(matrix)
    _validate_placement(matrix)
    matrix["rows_filter"] = _filter_rows(matrix, rows)
    return matrix


def _validate_baseline_gates(matrix: dict) -> None:
    for slug, scenario in matrix["scenarios"].items():
        baselines = scenario["baselines"]
        if baselines is None:
            continue
        role = baselines["seed_role"]
        owners = baseline_config_owners(matrix, slug)
        for seed in matrix["seeds"][role]:
            for owner in owners:
                ini = config_for(scenario, role, seed, owner)
                validate_deployment_gate(ini["path"], scenario["case"], seed)


def _validate_operation_fit(matrix: dict) -> None:
    """Schedules resolve per scenario; an online rollout must fit every native episode."""
    if not matrix["evaluation"]:
        return
    for op in matrix["evaluation"]["operations"]:
        for row in matrix["rows"]:
            if op["id"] not in row["operations"]:
                continue
            scenario = matrix["scenarios"][row["scenario"]]
            where = f"operation {op['id']} for row {row['name']}"
            if (op["mode"] == "online_gated_v1" or op["schedule"] is not None) and not (
                scenario["case"] or {}
            ).get("mission"):
                raise ValueError(
                    f"{where}: {'online_gated_v1' if op['schedule'] is None else 'a schedule'} "
                    f"needs scenarios.{row['scenario']}.case.mission; eligibility is "
                    "mission-based and is never inferred from the INI"
                )
            schedule_for(op["schedule"], scenario["case"], where)
            for seed in matrix["seeds"][op["seed_role"]]:
                config = config_for(scenario, op["seed_role"], seed, row)
                validate_deployment_gate(config["path"], scenario["case"], seed)
                if op["online"] is None:
                    continue
                decisions = native_decisions(config["path"])
                if op["online"]["n_steps"] > decisions:
                    raise ValueError(
                        f"operation {op['id']}: online n_steps {op['online']['n_steps']} "
                        f"exceeds the {decisions}-decision episode of {config['path']}"
                    )


def _filter_rows(matrix: dict, rows: list[str] | None) -> list[str] | None:
    if rows is None:
        return None
    known = {row["name"] for row in matrix["rows"]}
    unknown = [name for name in rows if name not in known]
    if unknown:
        raise ValueError(
            f"--rows names not in the matrix: {unknown}; available: {sorted(known)}"
        )
    for stage in matrix["stages"]:
        selection = stage["selection"]
        if selection is None:
            continue
        involved = {
            e if isinstance(e, str) else e["row"]
            for es in selection["candidates"].values()
            for e in es
        }
        if involved & set(rows) and not involved <= set(rows):
            raise ValueError(
                f"--rows splits the candidates of stage {stage['name']}; "
                "a selection needs every declared candidate"
            )
        gated = {
            e if isinstance(e, str) else e["row"]
            for es in selection["branches"].values()
            for e in es
        }
        if gated & set(rows) and not involved <= set(rows):
            raise ValueError(
                f"--rows keeps branches of stage {stage['name']} without its candidates"
            )
    matrix["rows"] = [row for row in matrix["rows"] if row["name"] in set(rows)]
    for stage in matrix["stages"]:
        stage["rows"] = [row for row in stage["rows"] if row in set(rows)]
    matrix["checks"] = [
        c
        for c in matrix["checks"]
        if c["kind"] != "reward_audit" or c["row"] in set(rows)
    ]
    return list(rows)


def resolve_execution(declared: dict, overrides: dict) -> dict:
    """Execution settings: CLI > matrix > defaults, with the source of each value."""
    resolved, source = {}, {}
    for key, default in EXECUTION_DEFAULTS.items():
        if overrides.get(key) is not None:
            resolved[key], source[key] = overrides[key], "cli"
        elif key in declared:
            resolved[key], source[key] = declared[key], "matrix"
        else:
            resolved[key], source[key] = default, "default"
    for key in ("workers", "threads_per_worker"):
        _positive_int(resolved[key], key)
    if resolved["failure_policy"] not in FAILURE_POLICIES:
        raise ValueError(f"failure_policy must be one of {list(FAILURE_POLICIES)}")
    if not 0 <= _int(resolved["nice"], "nice") <= 19:
        raise ValueError("nice must be in [0,19]")
    resolved["recovery"] = declared.get("recovery", "none")
    resolved["resource_pool"] = declared.get("resource_pool")
    resolved["source"] = source
    return resolved
