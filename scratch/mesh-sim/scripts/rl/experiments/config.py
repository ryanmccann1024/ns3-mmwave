"""Read and validate version 2 batch matrices.

Validation reads only configuration, assets and saved training manifests. It
starts no simulator, writes nothing and imports no scheduler or CLI.
"""

import json
from pathlib import Path

from scripts.artifact_io import sha256_file
from scripts.rl.experiments.check_config import (
    _checks,
    check_dependents as check_dependents,
    CHECK_KINDS as CHECK_KINDS,
)
from scripts.rl.experiments.matrix_fields import (
    _check_disjoint,
    _check_keys,
    _distinct_names,
    _int,
    _name,
    _output_path,
    _positive_int,
    _seed_list,
    OPERATION_SEED_ROLES as OPERATION_SEED_ROLES,
    SEED_ROLES as SEED_ROLES,
)
from scripts.rl.experiments.model_config import (
    model_selector as model_selector,
    retained_checkpoints as retained_checkpoints,
)
from scripts.rl.experiments.operation_config import (
    _evaluation,
    _validate_operation_fit,
    FROZEN_MODES as FROZEN_MODES,
    MODES as MODES,
    ONLINE_MODES as ONLINE_MODES,
    schedule_for as schedule_for,
)
from scripts.rl.experiments.row_config import (
    _row,
    _training,
)
from scripts.rl.experiments.scenario_config import (
    _scenario,
    _validate_baseline_gates,
    _validate_placement,
    baseline_config_owners as baseline_config_owners,
    BASELINE_CONFIG_SCOPES as BASELINE_CONFIG_SCOPES,
    BASELINE_POLICIES as BASELINE_POLICIES,
    config_for as config_for,
    placement_identity as placement_identity,
    REFERENCE_KINDS as REFERENCE_KINDS,
)
from scripts.rl.experiments.scenario_timing import (
    native_decisions as native_decisions,
)
from scripts.rl.policy.evaluate import PLACEMENT_POLICIES as PLACEMENT_POLICIES
from scripts.rl.experiments.stage_config import (
    _filter_rows,
    _stages,
    SELECTION_RULES as SELECTION_RULES,
)

MATRIX_V2_VERSION = 2


KINDS = ("train", "checks", "evaluate")


FAILURE_POLICIES = ("continue", "stop")


RECOVERY_MODES = ("none", "checkpoint")


EXECUTION_DEFAULTS = {
    "workers": 1,
    "threads_per_worker": 1,
    "failure_policy": "continue",
    "nice": 0,
}


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


_EXECUTION_KEYS = (
    "workers",
    "threads_per_worker",
    "failure_policy",
    "nice",
    "recovery",
    "resource_pool",
)


def _seeds(raw) -> dict:
    _check_keys(raw, SEED_ROLES, "seeds")
    seeds = {
        role: _seed_list(raw.get(role, []), f"seeds.{role}") for role in SEED_ROLES
    }
    _check_disjoint({f"seeds.{role}": set(values) for role, values in seeds.items()})
    return seeds


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
