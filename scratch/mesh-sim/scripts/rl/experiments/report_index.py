"""Produce scenario indexes, hashed input copies, and reward summaries."""

import fcntl
from pathlib import Path

from scripts.artifact_io import canonical_sha256, sha256_file
from scripts.rl.experiments.plan import (
    COMPARISON_NAME,
    CURVE_SOURCES,
    INDEX_NAME,
    REVIEW_NAME,
)
from scripts.rl.experiments.report_artifacts import (
    _asset,
    _baseline_reference,
    _Batch,
    _copy,
    _dig,
    _leaf,
    _load,
    _operate_reference,
    _write,
    _write_csv,
)
from scripts.rl.experiments.report_curves import (
    CURVES_CSV,
    _seed_segment,
)

MISSION_SCENARIO_VERSION = 4


PHASE_COMPARISON_VERSION = 1


PHASE_COMPARISON_NAME = "phase_comparison.json"


REWARD_SUMMARY_VERSION = 1


REWARD_SUMMARY_CSV = "reward_comparison.csv"


REWARD_SUMMARY_JSON = "reward_comparison.json"


# Same metrics and leading CSV columns as the retired campaign summary; the
# identity columns that follow make each row's source explicit.
REWARD_SUMMARY_METRICS = (
    "delivery_ratio",
    "worst_node_delivery_fraction",
    "post_jammer_delivery_ratio",
    "recovery_time_s",
    "coverage_fraction_mean",
    "unsafe_proximity_fraction",
    "travel_m_total",
    "displacement_m_final",
)


REWARD_SUMMARY_FIELDS = (
    "scenario",
    "reward",
    "training_seed",
    "policy",
    "completed_episodes",
    *REWARD_SUMMARY_METRICS,
    "checkpoint",
    "operation",
    "protocol",
    "seed_role",
    "evaluation_seeds",
    "model_sha256",
)


REWARD_SUMMARY_NOTE = (
    "Means of common domain metrics over completed episodes, per evaluated "
    "configuration. Rows with different reward definitions are not ranked "
    "against each other; missing measurements stay empty."
)


HISTORY_NOTE = (
    "Imported recorded diagnostics; small source files are copied with their original "
    "hashes. Historical metrics are not rerun or pooled with batch results."
)


_RESULT_KINDS = ("train", "operate", "baseline", "curves", "review", "compare")


def _ini_assets(batch, record, assets_dir, issues, outputs) -> dict:
    assets = {name: record.get(name) for name in ("nodes", "buildings", "jammers")}
    digest = canonical_sha256(
        {
            "run_config": [Path(record["path"]).name, record["sha256"]],
            **{
                name: [Path(asset["path"]).name, asset["sha256"]] if asset else None
                for name, asset in assets.items()
            },
        }
    )
    folder = assets_dir / f"scenario-{digest}"
    result = {"run_config": _asset(batch, record, folder, issues, outputs)}
    batch.config_assets[record["path"]] = result["run_config"]
    for name, asset in assets.items():
        result[name] = _asset(batch, asset, folder, issues, outputs)
    result["fallback"] = record.get("fallback", False)
    return result


def _scenario_assets(
    batch: _Batch, slug: str, main: Path, issues: list, outputs: dict
) -> dict:
    scenario = batch.plan["scenarios"][slug]
    assets_dir = main / "assets"
    reference = scenario["reference"]
    return {
        "run_config": _ini_assets(
            batch, scenario["run_config"], assets_dir, issues, outputs
        ),
        "configs": {
            role: {
                seed: _ini_assets(batch, record, assets_dir, issues, outputs)
                for seed, record in sorted(entries.items())
            }
            for role, entries in sorted(scenario["configs"].items())
        },
        "reference": None
        if reference is None
        else {
            "kind": reference["kind"],
            **_asset(
                batch,
                reference,
                assets_dir / f"reference-{reference['sha256'][:12]}",
                issues,
                outputs,
            ),
        },
    }


def _history_import(
    batch: _Batch, slug: str, main: Path, issues: list, outputs: dict
) -> str | None:
    sources_in = batch.plan["scenarios"][slug].get("history_sources") or []
    target = main / PHASE_COMPARISON_NAME
    if not sources_in:
        target.unlink(missing_ok=True)
        return None
    diagnostics, sources = [], []
    for index, source in enumerate(sources_in):
        directory = Path(source["path"])
        found = directory / PHASE_COMPARISON_NAME
        data = _load(found) if found.is_file() else None
        if (
            data is None
            or data.get("phase_comparison_version") != PHASE_COMPARISON_VERSION
        ):
            issues.append(
                f"history source {index} has no {PHASE_COMPARISON_NAME} version "
                f"{PHASE_COMPARISON_VERSION}"
            )
            continue
        original = sha256_file(found)
        folder = main / "history" / f"{index:02}-{original[:12]}"
        for name in (PHASE_COMPARISON_NAME, INDEX_NAME):
            if (directory / name).is_file():
                outputs[batch.rel(folder / name)] = _copy(
                    directory / name, folder / name
                )
        diagnostics += data.get("diagnostics") or []
        sources.append(
            {
                "path": batch.rel(folder / PHASE_COMPARISON_NAME),
                "sha256": original,
                "case": data.get("case"),
            }
        )
    outputs[batch.rel(target)] = _write(
        target,
        {
            "phase_comparison_version": PHASE_COMPARISON_VERSION,
            "case": slug,
            "diagnostics": diagnostics,
            "sources": sources,
            "note": HISTORY_NOTE,
        },
    )
    return batch.rel(target)


def _mean_row(episodes: list[dict]) -> dict:
    row = {"completed_episodes": len(episodes)}
    for metric in REWARD_SUMMARY_METRICS:
        values = [(e.get("metrics") or {}).get(metric) for e in episodes]
        values = [v for v in values if v is not None]
        row[metric] = sum(values) / len(values) if values else None
    return row


def _completed(leaf: dict, policy: str) -> list[dict]:
    if leaf["_eval"] is not None:
        block = (leaf["_eval"].get("policies") or {}).get(policy) or {}
        return [
            e for e in block.get("episodes") or [] if e.get("status") == "completed"
        ]
    if leaf["_online"] is not None and leaf["_online"].get("status") == "completed":
        return list(leaf["_online"].get("episodes") or [])
    return []


def _summary_rows(batch: _Batch, slug: str) -> list[dict]:
    """Per evaluated configuration: model per (row, model, checkpoint, operation, role); baseline per policy/role."""
    rows, groups = [], {}
    for task in batch.tasks(slug, "operate"):
        ident = task["identity"]
        groups.setdefault(
            (
                "model",
                *batch.task_dims(task),
                ident["operation"],
                ident["seed_role"],
                (task.get("config") or {}).get("sha256"),
            ),
            [],
        ).append(task)
    for task in batch.tasks(slug, "baseline"):
        groups.setdefault(
            (
                "baseline",
                task["identity"]["policy"],
                task["identity"]["seed_role"],
                (task.get("config") or {}).get("sha256"),
            ),
            [],
        ).append(task)
    for key, members in groups.items():
        episodes, sources, seeds = [], [], []
        for task in members:
            policy = "model" if key[0] == "model" else key[1]
            leaf = _leaf(batch, task, policy)
            done = [
                e
                for e in _completed(leaf, policy)
                if e.get("seed") == task["identity"]["seed"]
            ]
            if done:
                seeds.append(task["identity"]["seed"])
            episodes += done
            manifest = leaf["eval_manifest"] or leaf["online_manifest"]
            if manifest is not None:
                sources.append(
                    {
                        "task": task["id"],
                        "manifest": manifest,
                        "sha256": leaf["eval_manifest_sha256"]
                        or leaf["online_manifest_sha256"],
                    }
                )
        first = members[0]["identity"]
        if key[0] == "model":
            row = {
                "scenario": slug,
                "reward": first["row"],
                "training_seed": first["training_seed"],
                "policy": "model",
                **_mean_row(episodes),
                "checkpoint": first["checkpoint"],
                "operation": first["operation"],
                "protocol": first["protocol"],
                "seed_role": first["seed_role"],
                "evaluation_seeds": sorted(seeds),
                "model_sha256": batch.binding(members[0]).get("model_sha256"),
            }
        else:
            row = {
                "scenario": slug,
                "reward": None,
                "training_seed": None,
                "policy": first["policy"],
                **_mean_row(episodes),
                "checkpoint": None,
                "operation": None,
                "protocol": None,
                "seed_role": first["seed_role"],
                "evaluation_seeds": sorted(seeds),
                "model_sha256": None,
            }
        rows.append({**row, "config_sha256": key[-1], "sources": sources})
    return rows


def _csv_row(row: dict) -> dict:
    return {**row, "evaluation_seeds": ";".join(map(str, row["evaluation_seeds"]))}


def _summary_payload(scope: str, batch: _Batch, rows: list[dict], extra=None) -> dict:
    return {
        "reward_summary_version": REWARD_SUMMARY_VERSION,
        "scope": scope,
        "batch": batch.plan["matrix"]["name"],
        "metrics": list(REWARD_SUMMARY_METRICS),
        "note": REWARD_SUMMARY_NOTE,
        **(extra or {}),
        "rows": rows,
    }


def write_reward_summary(plan: dict, root) -> dict:
    """Rebuild main/reward_comparison.csv and .json from the scenario projections, under a lock."""
    batch = _Batch(plan, root, {})
    main = batch.root / "main"
    main.mkdir(parents=True, exist_ok=True)
    outputs = {}
    with open(main / ".reward_comparison.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows, scenarios = [], []
        for slug in plan["scenarios"]:
            path = main / slug / REWARD_SUMMARY_JSON
            data = _load(path)
            if data is None:
                continue
            scenarios.append(
                {"scenario": slug, "path": batch.rel(path), "sha256": sha256_file(path)}
            )
            rows += data["rows"]
        outputs[f"main/{REWARD_SUMMARY_CSV}"] = _write_csv(
            main / REWARD_SUMMARY_CSV,
            [_csv_row(r) for r in rows],
            REWARD_SUMMARY_FIELDS,
        )
        outputs[f"main/{REWARD_SUMMARY_JSON}"] = _write(
            main / REWARD_SUMMARY_JSON,
            _summary_payload("batch", batch, rows, {"scenarios": scenarios}),
        )
    return outputs


def _model_entries(batch: _Batch, slug: str) -> list[dict]:
    entries = {}
    for task in batch.tasks(slug, "operate"):
        entries.setdefault(batch.task_dims(task), []).append(task)
    models = []
    for (row_name, training_seed, model_source, checkpoint), members in entries.items():
        row = batch.rows[row_name]
        labels = row.get("labels") or {}
        training = None
        if training_seed is not None:
            train_id = f"train/{slug}/{row_name}/train-seed-{training_seed}"
            train = batch.by_id[train_id]
            directory = batch.dir_of(train_id)
            manifest_path = (
                directory / "train_manifest.json" if directory is not None else None
            )
            present = manifest_path is not None and manifest_path.is_file()
            training = {
                "task": train_id,
                "key": train["key"],
                "status": "complete"
                if present
                else ("skipped_selection" if train_id in batch.skipped else "missing"),
                "attempt": batch.rel(directory) if directory is not None else None,
                "train_manifest": batch.rel(manifest_path) if present else None,
                "train_manifest_sha256": sha256_file(manifest_path)
                if present
                else None,
            }
            manifest = _load(manifest_path) if present else {}
        else:
            manifest = {}
        source = row.get("model_source")
        references = sorted(
            (_operate_reference(batch, t) for t in members),
            key=lambda r: (r["operation"], r["role"], r["seed"]),
        )
        selection = row.get("selection") or {}
        models.append(
            {
                "scene": slug,
                "reward": row_name,
                "reward_label": labels.get("reward_label"),
                "profile": row["profile"],
                "ppo_label": labels.get("ppo_label"),
                "comparison": labels.get("comparison"),
                "training_seed": training_seed,
                "source_phase": labels.get("source_phase"),
                "tags": labels.get("tags", []),
                "row": row_name,
                "stage": members[0]["stage"],
                "checkpoint": checkpoint,
                "seed_segment": _seed_segment(members[0]["identity"]),
                "training": training,
                "model_source": None
                if source is None
                else {
                    "digest": source["digest"],
                    "model_sha256": source["model_sha256"],
                    "num_timesteps": source.get("num_timesteps"),
                    "n_updates": source.get("n_updates"),
                    "seed": source.get("seed"),
                },
                "continue_from": None
                if row.get("continue_from") is None
                else {
                    "digest": row["continue_from"]["digest"],
                    "model_sha256": row["continue_from"]["model_sha256"],
                },
                "curriculum_sha256": (row.get("curriculum") or {}).get("sha256"),
                "model": batch.binding(members[0]),
                "selection": {
                    k: selection.get(k)
                    for k in (
                        "observation_preset",
                        "action_profile",
                        "reward_components",
                        "reward_weights",
                        "observation_parameters",
                        "reward_parameters",
                    )
                },
                "schemas": {
                    "observation_schema_sha256": _dig(
                        manifest, "observation_schema.sha256"
                    ),
                    "reward_schema_sha256": _dig(manifest, "reward_schema.sha256"),
                },
                "ppo": row.get("training"),
                "evaluations": references,
            }
        )
    return models


def _baseline_entries(batch: _Batch, slug: str) -> list[dict]:
    entries = {}
    for task in batch.tasks(slug, "baseline"):
        entries.setdefault(
            (task["identity"]["policy"], task["identity"]["seed_role"]), []
        ).append(task)
    result = []
    for (policy, role), members in entries.items():
        refs = sorted(
            (_baseline_reference(batch, t) for t in members),
            key=lambda r: (r["seed"], r["task"]),
        )
        entry = {"policy": policy, "role": role, "evaluations": refs}
        plannings = [r.get("planning") for r in refs]
        if (
            plannings
            and plannings[0] is not None
            and all(p == plannings[0] for p in plannings)
        ):
            entry["planning"] = plannings[0]
        result.append(entry)
    return result


def _report_refs(
    batch: _Batch, slug: str, main: Path, issues: list, outputs: dict
) -> dict:
    curves = []
    for task in batch.tasks(slug, "curves"):
        directory = batch.dir_of(task["id"])
        for train_id in task["needs"]:
            train = batch.by_id[train_id]
            folder = (
                None
                if directory is None
                else directory
                / train["row"]
                / f"train-seed-{train['identity']['training_seed']}"
            )
            present = folder is not None and (folder / CURVES_CSV).is_file()
            curves.append(
                {
                    "task": task["id"],
                    "train_task": train_id,
                    "curves": batch.rel(folder / CURVES_CSV) if present else None,
                    "sources": batch.rel(folder / CURVE_SOURCES) if present else None,
                }
            )
    review = None
    review_target = main / REVIEW_NAME
    for task in batch.tasks(slug, "review"):
        directory = batch.dir_of(task["id"])
        if directory is not None and (directory / REVIEW_NAME).is_file():
            sha = _copy(directory / REVIEW_NAME, review_target)
            outputs[batch.rel(review_target)] = sha
            review = {
                "task": task["id"],
                "source": batch.rel(directory / REVIEW_NAME),
                "path": batch.rel(review_target),
                "sha256": sha,
            }
    if review is None:
        review_target.unlink(missing_ok=True)
    comparisons = []
    for task in batch.tasks(slug, "compare"):
        directory = batch.dir_of(task["id"])
        data = None if directory is None else _load(directory / COMPARISON_NAME)
        comparisons.append(
            {
                "task": task["id"],
                "key": task["key"],
                "operation": task["identity"]["operation"],
                "checkpoint": task["identity"]["checkpoint"],
                "status": data.get("status") if data else "missing",
                "attempt": batch.rel(directory) if directory is not None else None,
                "comparison": batch.rel(directory / COMPARISON_NAME) if data else None,
                "sha256": sha256_file(directory / COMPARISON_NAME) if data else None,
            }
        )
    return {
        "curves": curves,
        "mission_review": review,
        "comparisons": comparisons,
        "phase_comparison": _history_import(batch, slug, main, issues, outputs),
        "reward_summary": f"main/{slug}/{REWARD_SUMMARY_JSON}",
        "batch_reward_summary": f"main/{REWARD_SUMMARY_JSON}",
    }


def build_index(batch: _Batch, slug: str, main: Path, outputs: dict) -> dict:
    """The version 4 ``mission_scenario.json`` payload; copies assets/review/history as it goes."""
    scenario = batch.plan["scenarios"][slug]
    case = scenario["case"] or {}
    issues = []
    assets = _scenario_assets(batch, slug, main, issues, outputs)
    reports = _report_refs(batch, slug, main, issues, outputs)
    batch.assets_dir = main / "assets"
    models = _model_entries(batch, slug)
    baselines = _baseline_entries(batch, slug)
    issues += sorted(set(batch.asset_issues))
    outputs.update(batch.asset_outputs)
    missing = sorted(
        t["id"]
        for t in batch.tasks(slug, *_RESULT_KINDS)
        if batch.dir_of(t["id"]) is None and t["id"] not in batch.skipped
    )
    references = [r for m in models for r in m["evaluations"]] + [
        r for b in baselines for r in b["evaluations"]
    ]
    incomplete = bool(
        missing
        or issues
        or any(r["status"] not in ("complete", "skipped_selection") for r in references)
        or any(c["status"] != "complete" for c in reports["comparisons"])
    )
    validation = sorted(
        {
            t["identity"]["seed"]
            for t in batch.tasks(slug, "operate", "baseline")
            if t["identity"]["seed_role"] != "held_out"
        }
    )
    return {
        "mission_scenario_version": MISSION_SCENARIO_VERSION,
        "batch": {
            "name": batch.plan["matrix"]["name"],
            "kind": batch.plan["matrix"]["kind"],
            "matrix_sha256": batch.plan["matrix"]["sha256"],
            "experiment_plan_version": batch.plan["experiment_plan_version"],
            "plan": "experiment_plan.json",
        },
        "scene": slug,
        "objective": case.get("mission"),
        "environment": case.get("environment"),
        "peers": case.get("peers"),
        "validation_seeds": validation,
        "baseline_dir": None,
        "reviewed_exception": case.get("reviewed_exception", False),
        "exception_reason": case.get("exception_reason"),
        "case": scenario["case"],
        "band": scenario["band"],
        "seeds": batch.plan["seeds"],
        "assets": assets,
        "models": models,
        "baselines": baselines,
        "reports": reports,
        "incomplete": incomplete,
        "missing": missing,
        "issues": issues,
    }


def _index(batch: _Batch, task: dict) -> dict:
    slug = task["scenario"]
    main = batch.task_dir(task)
    main.mkdir(parents=True, exist_ok=True)
    outputs = {}
    index = build_index(batch, slug, main, outputs)
    rows = _summary_rows(batch, slug)
    summary = main / REWARD_SUMMARY_JSON
    outputs[batch.rel(summary)] = _write(
        summary, _summary_payload("scenario", batch, rows)
    )
    outputs[batch.rel(main / REWARD_SUMMARY_CSV)] = _write_csv(
        main / REWARD_SUMMARY_CSV, [_csv_row(r) for r in rows], REWARD_SUMMARY_FIELDS
    )
    outputs.update(write_reward_summary(batch.plan, batch.root))
    # The index is written last so a reader never finds it ahead of its projections.
    outputs[batch.rel(main / INDEX_NAME)] = _write(main / INDEX_NAME, index)
    return {
        "outputs": outputs,
        "warnings": index["issues"],
        "incomplete": index["incomplete"],
    }
