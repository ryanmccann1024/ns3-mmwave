"""Validate selection rules and dependencies between batch stages."""

from scripts.rl.experiments.matrix_fields import (
    _check_keys,
    _distinct_names,
    _name,
    _positive_int,
)
from scripts.rl.experiments.model_config import (
    model_selector,
)
from scripts.rl.experiments.operation_config import (
    ONLINE_MODES,
)
from scripts.rl.experiments.scenario_timing import (
    native_decisions as native_decisions,
)

SELECTION_RULES = (
    "legacy-validation-profile-v1",
    "legacy-mission-profile-v1",
    "legacy-online-profile-v1",
    "replay",
)


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
