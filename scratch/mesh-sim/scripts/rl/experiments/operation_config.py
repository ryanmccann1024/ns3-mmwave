"""Validate batch policy operations, schedules and episode budgets."""

import json

from scripts.artifact_io import canonical_sha256
from scripts.rl.agents.config import validate_training_settings
from scripts.rl.experiments.matrix_fields import (
    OPERATION_SEED_ROLES,
    _bool,
    _check_keys,
    _distinct_names,
    _name,
    _positive_int,
    _seed_list,
)
from scripts.rl.experiments.scenario_config import (
    config_for,
)
from scripts.rl.experiments.scenario_timing import (
    native_decisions as native_decisions,
)
from scripts.rl.experiments.scenario_timing import (
    validate_deployment_gate,
)
from scripts.rl.policy.schedules import COVERAGE_KINDS, validate_schedule

MODES = ("frozen_deterministic", "frozen_sampled", "online_gated_v1", "online_sb3_v1")


FROZEN_MODES = MODES[:2]


ONLINE_MODES = MODES[2:]


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
