"""Batch scenarios, per-seed INIs, references and baseline settings."""

import json
import math
from pathlib import Path

from scripts.artifact_io import canonical_sha256, sha256_file
from scripts.rl.env.config import read_explicit_rl_bounds
from scripts.rl.experiments.matrix_fields import (
    OPERATION_SEED_ROLES,
    SEED_ROLES,
    _band,
    _bool,
    _check_keys,
    _input_path,
    _int,
    _name,
    _number,
    _positive_int,
    _seed_list,
)
from scripts.rl.experiments.scenario_timing import (
    native_decisions as native_decisions,
)
from scripts.rl.experiments.scenario_timing import (
    validate_deployment_gate,
)
from scripts.rl.policy.evaluate import PLACEMENT_POLICIES
from scripts.sim_support import parse_ini

BASELINE_POLICIES = ("hold", "random_valid", "scripted", *PLACEMENT_POLICIES)


REFERENCE_KINDS = ("scenario_routes_v1", "mission_waypoints_v1")


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
