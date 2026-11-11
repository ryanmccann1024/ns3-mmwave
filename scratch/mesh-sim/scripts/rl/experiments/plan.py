"""Expand a validated version 2 matrix into an immutable experiment plan version 3.

The plan is a deterministic task graph with full SHA-256 task keys, fixed
destinations, resolved module/argument lists and hashed inputs. Nothing here
starts a process: the simulator binary is hashed, never launched.
"""

import json
from pathlib import Path, PurePosixPath

from scripts.artifact_io import canonical_sha256, write_json
from scripts.rl.cli_common import MANIFEST_NAME, MODEL_BASENAME
from scripts.rl.experiments.config import (
    check_dependents,
)
from scripts.rl.experiments.plan_inputs import (
    _Inputs,
    _row_record,
    _scenario_records,
    _seed_config,
    binary_identity as binary_identity,
    check_binary_fresh as check_binary_fresh,
)
from scripts.rl.experiments.plan_tasks import (
    _add_baselines,
    _add_check,
    _add_operations,
    _checkpoint_segment,
    _train_args,
    graph_stage as graph_stage,
)
from scripts.rl.experiments.task_graph import (
    _Graph,
    accepted_dir as accepted_dir,
    ACCEPTED_DIRS as ACCEPTED_DIRS,
    ATTEMPT_DIR as ATTEMPT_DIR,
    BINDING_MODEL as BINDING_MODEL,
    BINDING_PATH as BINDING_PATH,
    BINDING_RUN_DIR as BINDING_RUN_DIR,
    check_collisions as check_collisions,
    CHECK_RESULT as CHECK_RESULT,
    COMPARE_MODULE as COMPARE_MODULE,
    COMPARISON_NAME as COMPARISON_NAME,
    CURVE_SOURCES as CURVE_SOURCES,
    EVAL_MANIFEST as EVAL_MANIFEST,
    EXPERIMENT_PLAN_VERSION as EXPERIMENT_PLAN_VERSION,
    INDEX_NAME as INDEX_NAME,
    KEY_DIMENSIONS as KEY_DIMENSIONS,
    ONLINE_MANIFEST as ONLINE_MANIFEST,
    OPERATE_MODULE as OPERATE_MODULE,
    PLAN_NAME as PLAN_NAME,
    POST_UPDATE_CHECKPOINTS as POST_UPDATE_CHECKPOINTS,
    REVIEW_NAME as REVIEW_NAME,
    SELECTION_RECEIPT as SELECTION_RECEIPT,
    SUFFIX_LENGTH as SUFFIX_LENGTH,
    task_key as task_key,
    TRAIN_MODULE as TRAIN_MODULE,
)

_PLAN_DIFFERS = (
    "{path} differs from the plan for this matrix, binary and --rows; "
    "plans are immutable, use a new --output-root"
)


def build_batch_plan(
    matrix: dict, output_root=None, sim_binary: str | None = None
) -> dict:
    """Deterministic plan v3; output_root/sim_binary None gives the validate-only expansion."""
    placeholder = output_root is None
    root = (
        PurePosixPath("<output-root>") if placeholder else Path(output_root).resolve()
    )
    inputs = _Inputs()
    inputs.add(matrix["path"], "matrix", matrix["reference"])
    binary = binary_identity(sim_binary) if sim_binary is not None else None
    binary_arg = binary["path"] if binary else "<sim-binary>"
    records = _scenario_records(matrix, inputs)
    rows = [_row_record(row, inputs) for row in matrix["rows"]]
    row_by_name = {row["name"]: row for row in matrix["rows"]}
    seeds = matrix["seeds"]
    operations = matrix["evaluation"]["operations"] if matrix["evaluation"] else []
    op_by_id = {op["id"]: op for op in operations}
    graph = _Graph(root)
    branch_of, op_branch_of = {}, {}
    for stage in matrix["stages"]:
        if stage["selection"]:
            for candidate, entries in stage["selection"]["branches"].items():
                for entry in entries:
                    target = (stage["name"], candidate)
                    if isinstance(entry, str):
                        if entry in row_by_name:
                            branch_of[entry] = target
                    elif entry["row"] in row_by_name:
                        op_branch_of[(entry["row"], entry["operation"])] = target

    check_task_ids, baseline_ids = {}, {}
    for check in (c for c in matrix["checks"] if c["kind"] == "preflight"):
        check_task_ids[check["id"]] = _add_check(
            graph, matrix, records, check, binary_arg, [], inputs
        )

    def scenario_preflights(slug):
        return [
            tid
            for c in matrix["checks"]
            if c["kind"] == "preflight" and c["scenario"] == slug
            for tid in check_task_ids[c["id"]]
        ]

    _add_baselines(
        graph, matrix, records, inputs, binary_arg, scenario_preflights, baseline_ids
    )
    for check in (c for c in matrix["checks"] if c["kind"] != "preflight"):
        check_task_ids[check["id"]] = _add_check(
            graph,
            matrix,
            records,
            check,
            binary_arg,
            scenario_preflights(check["scenario"]),
            inputs,
            baseline_ids,
        )
    # Declared check order is preserved in every dependent's needs.
    row_checks = {row["name"]: [] for row in matrix["rows"]}
    for check in matrix["checks"]:
        for name in check_dependents(check, matrix["rows"]):
            row_checks[name].extend(check_task_ids[check["id"]])

    train_ids, select_ids = {}, {}
    stage_order = [s["name"] for s in matrix["stages"]] or [None]
    stages = {s["name"]: s for s in matrix["stages"]}
    context = {
        "graph": graph,
        "matrix": matrix,
        "inputs": inputs,
        "op_by_id": op_by_id,
        "train_ids": train_ids,
        "row_checks": row_checks,
        "binary_arg": binary_arg,
        "branch_of": branch_of,
        "op_branch_of": op_branch_of,
        "select_ids": select_ids,
    }
    for stage_name in stage_order:
        stage_rows = (
            stages[stage_name]["rows"]
            if stage_name
            else [r["name"] for r in matrix["rows"]]
        )
        stage_needs = []
        if stage_name:
            for need in stages[stage_name]["needs"]:
                if need in select_ids:
                    stage_needs.append(select_ids[need])
                else:
                    stage_needs += [
                        tid
                        for r in stages[need]["rows"]
                        for tid in train_ids.get(r, [])
                    ]
        for name in stage_rows:
            row = row_by_name[name]
            selection = None
            if name in branch_of:
                selection = {
                    "task": select_ids[branch_of[name][0]],
                    "branch": branch_of[name][1],
                }
            if row["training"] is not None:
                for seed in row["training_seeds"]:
                    key = row["training_config_key"] or seed
                    ini = _seed_config(
                        matrix, inputs, row["scenario"], "training", key, row
                    )
                    identity = {
                        "task_kind": "train",
                        "scenario": row["scenario"],
                        "row": name,
                        "profile": row["profile"],
                        "training_seed": seed,
                        "model_source": row["continue_from"]["digest"]
                        if row["continue_from"]
                        else None,
                        "stage": stage_name,
                    }
                    expected = [MANIFEST_NAME, f"{MODEL_BASENAME}.zip"]
                    if row["training"]["checkpoint_timing"] == "after_update":
                        expected.append(POST_UPDATE_CHECKPOINTS)
                    task_inputs = (
                        [ini["path"]]
                        + ([row["curriculum"]["path"]] if row["curriculum"] else [])
                        + (
                            [row["continue_from"]["model_path"]]
                            if row["continue_from"]
                            else []
                        )
                    )
                    task_id = f"train/{row['scenario']}/{name}/train-seed-{seed}"
                    graph.add(
                        task_id,
                        identity,
                        [
                            "models",
                            row["scenario"],
                            name,
                            "train",
                            f"train-seed-{seed}",
                        ],
                        needs=row_checks[name]
                        + stage_needs
                        + ([selection["task"]] if selection else []),
                        module=TRAIN_MODULE,
                        args=_train_args(
                            binary_arg,
                            matrix["scenarios"][row["scenario"]]["band"],
                            ini,
                            row,
                            seed,
                            seeds,
                        ),
                        expected_outputs=expected,
                        inputs=task_inputs,
                        selection=selection,
                        config_lookup={
                            "key": str(key),
                            "seed": seed,
                            "ini": ini["path"],
                            "fallback": ini["fallback"],
                        },
                        config={
                            "path": ini["path"],
                            "sha256": ini["sha256"],
                            "config_source": ini["config_source"],
                        },
                    )
                    train_ids.setdefault(name, []).append(task_id)
        own = stages[stage_name]["selection"] if stage_name else None
        own_branches = set()
        if own is not None:
            own_branches = {
                (e["row"], e["operation"])
                for es in own["branches"].values()
                for e in es
                if not isinstance(e, str)
            }
        rows_here = [row_by_name[n] for n in stage_rows]
        _add_operations(
            context, rows_here, stage_needs, lambda r, o: (r, o) not in own_branches
        )
        if own is not None:
            select_ids[stage_name] = _add_select(
                graph, stages[stage_name], matrix, train_ids
            )
            _add_operations(
                context, rows_here, stage_needs, lambda r, o: (r, o) in own_branches
            )

    _add_reports(graph, matrix, op_by_id)
    check_collisions(graph.tasks)
    return {
        "experiment_plan_version": EXPERIMENT_PLAN_VERSION,
        "matrix": {
            "path": matrix["path"],
            "reference": matrix["reference"],
            "sha256": matrix["sha256"],
            "name": matrix["name"],
            "kind": matrix["kind"],
            "directory": matrix["directory"],
        },
        "sim_binary": binary,
        "output_root": None if placeholder else str(root),
        "rows_filter": matrix["rows_filter"],
        "seeds": seeds,
        "scenarios": records,
        "rows": rows,
        "operations": operations,
        "comparison": matrix["evaluation"]["comparison"]
        if matrix["evaluation"]
        else None,
        "checks": matrix["checks"],
        "stages": matrix["stages"],
        "execution_declared": matrix["execution"],
        "key_dimensions": list(KEY_DIMENSIONS),
        "placeholders": [
            ATTEMPT_DIR,
            BINDING_RUN_DIR,
            BINDING_MODEL,
            BINDING_PATH,
            ACCEPTED_DIRS,
            "{accepted_dir:<task-id>}",
        ],
        "inputs": inputs.files,
        "tasks": graph.tasks,
    }


def _add_select(graph, stage, matrix, train_ids) -> str:
    """Source exactly the declared operation(s) at `source_checkpoint`, or training validation."""
    selection = stage["selection"]
    needs, sources = [], {}
    checkpoint = (
        None
        if selection["source_checkpoint"] is None
        else _checkpoint_segment(selection["source_checkpoint"])
    )
    for candidate, entries in selection["candidates"].items():
        if selection["rule"] == "replay":
            continue
        for entry in entries:
            row = entry if isinstance(entry, str) else entry["row"]
            op_id = (
                selection["source_operation"]
                if isinstance(entry, str)
                else entry["operation"]
            )
            if selection["rule"] == "legacy-validation-profile-v1":
                ids = train_ids.get(row, [])
            else:
                ids = [
                    t["id"]
                    for t in graph.tasks
                    if t["kind"] == "operate"
                    and t["row"] == row
                    and t["identity"]["operation"] == op_id
                    and t["identity"]["checkpoint"] == checkpoint
                ]
            if not ids:
                raise ValueError(
                    f"stage {stage['name']}: candidate {candidate} ({row}) has no "
                    "source tasks"
                )
            sources.setdefault(candidate, []).extend(ids)
            needs += ids
    identity = {
        "task_kind": "select",
        "stage": stage["name"],
        "operation": selection["source_operation"],
        "seed_role": selection["seed_role"],
        "checkpoint": checkpoint,
        "operation_digest": canonical_sha256(
            {
                k: selection[k]
                for k in ("rule", "form", "candidates", "branches", "settings")
            }
        ),
    }
    source_kind = (
        "none"
        if selection["rule"] == "replay"
        else "training_validation"
        if selection["rule"] == "legacy-validation-profile-v1"
        else "operation"
    )
    task_id = f"select/{stage['name']}"
    graph.add(
        task_id,
        identity,
        ["analysis", "_batch", "selections", "{KEY}"],
        needs=needs,
        handler="select",
        expected_outputs=[SELECTION_RECEIPT],
        selection_rule={**selection, "source_kind": source_kind, "sources": sources},
    )
    return task_id


def _add_reports(graph, matrix, op_by_id) -> None:
    comparison = matrix["evaluation"]["comparison"] if matrix["evaluation"] else None
    for slug in matrix["scenarios"]:
        scenario_tasks = [t for t in graph.tasks if t["scenario"] == slug]
        trains = [t["id"] for t in scenario_tasks if t["kind"] == "train"]
        results = [
            t["id"] for t in scenario_tasks if t["kind"] in ("operate", "baseline")
        ]
        index_needs = []
        if trains:
            index_needs.append(
                _report(graph, "curves", slug, trains, CURVE_SOURCES, "curves")
            )
        if comparison is not None:
            groups = {}
            for task in scenario_tasks:
                if (
                    task["kind"] == "operate"
                    and task["identity"]["operation"] == comparison["operation"]
                ):
                    groups.setdefault(task["identity"]["checkpoint"], []).append(
                        task["id"]
                    )
            for checkpoint, ids in sorted(groups.items()):
                baselines = [t["id"] for t in scenario_tasks if t["kind"] == "baseline"]
                identity = {
                    "task_kind": "compare",
                    "scenario": slug,
                    "checkpoint": checkpoint,
                    "operation": comparison["operation"],
                    "operation_digest": op_by_id[comparison["operation"]][
                        "config_digest"
                    ],
                }
                task = graph.add(
                    f"compare/{slug}/{comparison['operation']}/checkpoint-{checkpoint}",
                    identity,
                    ["analysis", slug, "comparisons", "{KEY}"],
                    needs=ids + baselines,
                    module=COMPARE_MODULE,
                    args=["--eval-dirs", ACCEPTED_DIRS, "--output-dir", ATTEMPT_DIR],
                    exit_codes=[0, 2],
                    expected_outputs=[COMPARISON_NAME],
                    needs_policy="terminal"
                    if comparison["allow_incomplete"]
                    else "completed",
                    view={
                        "operation": comparison["operation"],
                        "sources": ids,
                        "baselines": baselines,
                        "allow_incomplete": comparison["allow_incomplete"],
                    },
                )
                index_needs.append(task["id"])
        if results:
            index_needs.append(
                _report(graph, "review", slug, results, REVIEW_NAME, "reviews")
            )
        if index_needs:
            graph.add(
                f"index/{slug}",
                {"task_kind": "index", "scenario": slug},
                ["main", slug],
                needs=index_needs,
                needs_policy="terminal",
                handler="index",
                attempts="projection",
                expected_outputs=[INDEX_NAME],
            )


def _report(graph, kind, slug, needs, output, folder) -> str:
    task = graph.add(
        f"{kind}/{slug}",
        {"task_kind": kind, "scenario": slug},
        ["analysis", slug, folder, "{KEY}"],
        needs=needs,
        needs_policy="terminal",
        handler=kind,
        expected_outputs=[output],
    )
    return task["id"]


def describe_expansion(plan: dict) -> list[str]:
    """Human-readable expansion printed by `validate`."""
    counts = {}
    for task in plan["tasks"]:
        counts[task["kind"]] = counts.get(task["kind"], 0) + 1
    lines = [
        f"matrix {plan['matrix']['name']} (kind {plan['matrix']['kind']}): "
        f"{len(plan['tasks'])} tasks",
        "  " + ", ".join(f"{kind} {count}" for kind, count in counts.items()),
    ]
    lines += [f"  {task['id']}  [{task['suffix']}]" for task in plan["tasks"]]
    return lines


def write_batch_plan(plan: dict, output_root) -> Path:
    """Write the plan once; an existing different plan is refused, never replaced."""
    root = Path(output_root).resolve()
    path = root / PLAN_NAME
    if path.is_file():
        try:
            existing = json.loads(path.read_text())
        except ValueError as exc:
            raise ValueError(f"{path} is unreadable; use a new --output-root") from exc
        if existing != json.loads(json.dumps(plan)):
            raise ValueError(_PLAN_DIFFERS.format(path=path))
        return path
    root.mkdir(parents=True, exist_ok=True)
    write_json(path, plan)
    return path


def read_plan_version(output_root):
    """experiment_plan_version of the plan in a root, or None when there is no plan."""
    path = Path(output_root).resolve() / PLAN_NAME
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    return data.get("experiment_plan_version") if isinstance(data, dict) else None


def load_batch_plan(output_root) -> dict:
    path = Path(output_root).resolve() / PLAN_NAME
    if not path.is_file():
        raise ValueError(f"no {PLAN_NAME} in {path.parent}; run plan first")
    plan = json.loads(path.read_text())
    if plan.get("experiment_plan_version") != EXPERIMENT_PLAN_VERSION:
        raise ValueError(
            f"{path} is not experiment plan version {EXPERIMENT_PLAN_VERSION}"
        )
    return plan
