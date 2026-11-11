"""Validate batch checks and resolve their sources and dependents."""

from pathlib import Path

from scripts.rl.experiments.matrix_fields import (
    _bool,
    _check_keys,
    _distinct_names,
    _input_path,
    _name,
    _seed_list,
)
from scripts.rl.experiments.model_config import (
    _model_source,
)
from scripts.rl.experiments.scenario_config import (
    _case,
)
from scripts.rl.experiments.scenario_timing import (
    native_decisions as native_decisions,
)

CHECK_KINDS = ("preflight", "replay_gate", "reward_audit")


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
