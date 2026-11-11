"""Pool comparable evaluation results and write mission reviews."""

import copy
import json
from pathlib import Path

from scripts.artifact_io import sha256_file
from scripts.rl.experiments.config import FROZEN_MODES
from scripts.rl.experiments.plan import EVAL_MANIFEST, ONLINE_MANIFEST, REVIEW_NAME
from scripts.rl.experiments.report_artifacts import (
    _Batch,
    _dig,
    _episode_dir,
    _load,
    _new_attempt,
    _split_task,
    _write,
)
from scripts.rl.experiments.report_curves import (
    _seed_segment,
)
from scripts.rl.policy import episode_review

VIEW_DIR = "view"


VIEW_SOURCES = "view_sources.json"


# Fields every pooled per-seed evaluation must share before seeds are merged.
_POOL_FIELDS = (
    "scenario_identity",
    "band",
    "bundle.model_sha256",
    "bundle.model_selection",
    "bundle.num_timesteps",
    "training",
    "selection",
    "observation_schema",
    "reward_schema",
    "seed_roles.role",
    "seed_roles.held_out",
    "deterministic",
    "metric_source",
    "policies.model.baseline",
)


def _episode_result(entry: dict):
    from scripts.rl.policy.evaluate import EpisodeResult

    return EpisodeResult(
        seed=entry.get("seed"),
        episode_dir=entry.get("episode_dir"),
        status=entry.get("status"),
        exit_code=entry.get("exit_code"),
        decisions=entry.get("decisions") or 0,
        total_return=entry.get("return"),
        reward_components_sum=entry.get("reward_components_sum") or {},
        revalidated_slots_total=entry.get("revalidated_slots_total"),
        mask_violations=entry.get("mask_violations"),
        actions_sha256=entry.get("actions_sha256"),
        metrics=entry.get("metrics") or {},
        summary_json=entry.get("summary_json"),
        error=entry.get("error"),
    )


def _policy_block(entries: list[dict], expected: int, metadata) -> dict:
    from scripts.rl.policy.evaluate import summarize

    entries = sorted(entries, key=lambda e: e["seed"])
    block = {
        "episodes": entries,
        "summary": summarize([_episode_result(e) for e in entries], expected),
    }
    if metadata:
        block["baseline"] = metadata
    return block


def _pool(
    batch: _Batch,
    model_tasks: list[dict],
    baseline_tasks: list[dict],
    label: str,
    allow_partial: bool,
):
    """One eval-manifest-v8-shaped record pooling per-seed leaves of one model; refuses mixing."""
    seeds = sorted(t["identity"]["seed"] for t in model_tasks)
    if len(set(seeds)) != len(seeds):
        raise ValueError(f"{label}: a pooled view repeats an evaluation seed")
    configs = {(t.get("config") or {}).get("sha256") for t in model_tasks}
    if len(configs) > 1:
        raise ValueError(
            f"{label}: refusing to pool leaves run with different INIs (config sha256)"
        )
    config_sha = next(iter(configs))
    present, missing, sources = [], [], []
    for task in model_tasks:
        directory = batch.dir_of(task["id"])
        if directory is None:
            missing.append(task["id"])
            continue
        manifest = _load(directory / EVAL_MANIFEST)
        if manifest is None:
            raise ValueError(
                f"{task['id']}: protocol {task['identity']['protocol']} wrote no readable "
                f"{EVAL_MANIFEST}; it cannot join an evaluation view"
            )
        if manifest.get("status") != "completed" or list(
            manifest.get("seeds") or []
        ) != [task["identity"]["seed"]]:
            missing.append(task["id"])
            continue
        if set(manifest.get("policies") or {}) != {"model"}:
            raise ValueError(
                f"{task['id']}: an operation leaf must hold only the model policy"
            )
        bound = batch.binding(task).get("model_sha256")
        if bound is not None and _dig(manifest, "bundle.model_sha256") != bound:
            raise ValueError(
                f"{task['id']}: evaluated model differs from its bound model"
            )
        present.append((task, directory, manifest))
        sources.append(
            {
                "task": task["id"],
                "key": task["key"],
                "role": "model",
                "eval_manifest": batch.rel(directory / EVAL_MANIFEST),
                "sha256": sha256_file(directory / EVAL_MANIFEST),
            }
        )
    if missing and not allow_partial:
        raise ValueError(f"{label}: missing accepted evaluations {missing}")
    if not present:
        return None, sources, missing
    reference = present[0][2]
    for task, _, manifest in present[1:]:
        differing = [f for f in _POOL_FIELDS if _dig(manifest, f) != _dig(reference, f)]
        if differing:
            raise ValueError(
                f"{label}: refusing to pool {task['id']} with {present[0][0]['id']}; "
                f"they differ in {differing}"
            )
    model_entries = []
    for _, directory, manifest in present:
        for entry in manifest["policies"]["model"]["episodes"]:
            path = _episode_dir(entry.get("episode_dir"), directory)
            model_entries.append(
                {**entry, "episode_dir": None if path is None else str(path)}
            )
    merged = copy.deepcopy(reference)
    merged["label"] = label
    merged["seeds"] = seeds
    policies = {
        "model": _policy_block(
            model_entries, len(seeds), reference["policies"]["model"].get("baseline")
        )
    }
    by_policy = {}
    role = _dig(reference, "seed_roles.role")
    for task in baseline_tasks:
        ident = task["identity"]
        if (
            ident["seed_role"] != role
            or ident["seed"] not in seeds
            or (task.get("config") or {}).get("sha256") != config_sha
        ):
            continue
        directory = batch.dir_of(task["id"])
        manifest = None if directory is None else _load(directory / EVAL_MANIFEST)
        if manifest is None or manifest.get("status") != "completed":
            missing.append(task["id"])
            if not allow_partial:
                raise ValueError(f"{label}: missing accepted baseline {task['id']}")
            continue
        for field in ("scenario_identity", "metric_source"):
            if manifest.get(field) != reference.get(field):
                raise ValueError(
                    f"{label}: baseline {task['id']} differs from the model in {field}"
                )
        block = (manifest.get("policies") or {}).get(ident["policy"]) or {}
        group = by_policy.setdefault(
            ident["policy"], {"entries": [], "metadata": block.get("baseline")}
        )
        for entry in block.get("episodes") or []:
            if entry.get("seed") == ident["seed"]:
                path = _episode_dir(entry.get("episode_dir"), directory)
                group["entries"].append(
                    {**entry, "episode_dir": None if path is None else str(path)}
                )
        sources.append(
            {
                "task": task["id"],
                "key": task["key"],
                "role": ident["policy"],
                "eval_manifest": batch.rel(directory / EVAL_MANIFEST),
                "sha256": sha256_file(directory / EVAL_MANIFEST),
                "baseline": block.get("baseline"),
            }
        )
    for policy in sorted(by_policy):
        policies[policy] = _policy_block(
            by_policy[policy]["entries"], len(seeds), by_policy[policy]["metadata"]
        )
    merged["policies"] = policies
    merged["episodes_expected"] = len(policies) * len(seeds)
    merged["episodes_completed"] = sum(
        b["summary"]["completed_episodes"] for b in policies.values()
    )
    merged["status"] = (
        "completed"
        if merged["episodes_completed"] == merged["episodes_expected"]
        else "partial"
        if merged["episodes_completed"]
        else "failed"
    )
    return merged, sources, missing


def _model_groups(tasks: list[dict], batch: _Batch) -> dict:
    groups = {}
    for task in tasks:
        groups.setdefault(batch.task_dims(task), []).append(task)
    return groups


def build_comparison_view(
    task: dict, plan: dict, root, accepted: dict, *, attempt_dir=None, skipped=()
) -> list[str]:
    """Write ``<attempt>/view/<model>/eval_manifest.json`` per model and return the directories.

    Seeds of one model pool only when scenario digests, model identity, seed
    role, protocol and schedule agree; attempts are never pooled and other seed
    roles are left out. A model with no accepted leaf gets an empty directory so
    ``compare`` records it as missing. ``attempt_dir`` is the compare attempt;
    when omitted the next ``attempt-N`` of the task is created. ``accepted`` values
    are attempt directories or the scheduler's ``{state, attempt_dir}`` records.
    """
    task, attempt_dir = _split_task(task, attempt_dir)
    batch = _Batch(plan, root, accepted, skipped)
    if batch.by_id.get(task["id"]) != task or task["kind"] != "compare":
        raise ValueError(f"{task.get('id')} is not a compare task of this plan")
    view = task["view"]
    sources = [batch.by_id[i] for i in view["sources"]]
    baselines = [batch.by_id[i] for i in view["baselines"]]
    if not sources:
        raise ValueError(f"{task['id']}: the view has no operation sources")
    first = sources[0]["identity"]
    for source in sources:
        ident = source["identity"]
        for dim in (
            "operation",
            "operation_digest",
            "protocol",
            "schedule_digest",
            "seed_role",
            "checkpoint",
        ):
            if ident[dim] != first[dim]:
                raise ValueError(
                    f"{task['id']}: sources differ in {dim}; refusing a mixed view"
                )
        if ident["operation"] != view["operation"]:
            raise ValueError(
                f"{task['id']}: {source['id']} is not operation {view['operation']}"
            )
    if first["protocol"] not in FROZEN_MODES:
        raise ValueError(
            f"{task['id']}: protocol {first['protocol']} writes no evaluation manifest to compare"
        )
    attempt = _new_attempt(batch, task, attempt_dir)
    directories = []
    for dims, members in _model_groups(sources, batch).items():
        row, _, _, checkpoint = dims
        segment = _seed_segment(members[0]["identity"])
        label = f"{row} checkpoint-{checkpoint} {view['operation']}"
        merged, used, missing = _pool(
            batch, members, baselines, label, view["allow_incomplete"]
        )
        directory = attempt / VIEW_DIR / f"{row}--{segment}"
        directory.mkdir(parents=True, exist_ok=False)
        if merged is not None:
            _write(directory / EVAL_MANIFEST, merged)
        _write(
            directory / VIEW_SOURCES,
            {
                "view_sources_version": 1,
                "compare_task": task["id"],
                "label": label,
                "sources": used,
                "missing": missing,
            },
        )
        directories.append(str(directory))
    return directories


def _review(batch: _Batch, task: dict, attempt: Path) -> dict:
    slug = task["scenario"]
    case = batch.plan["scenarios"][slug]["case"]
    warnings, outputs = [], {}
    results = [batch.by_id[i] for i in task["needs"]]
    missing = [
        t["id"]
        for t in results
        if batch.dir_of(t["id"]) is None and t["id"] not in batch.skipped
    ]
    ranked = [
        t
        for t in results
        if t["kind"] == "operate"
        and t["identity"]["protocol"] == "frozen_deterministic"
        and t.get("schedule") is None
        and t["identity"]["seed_role"] != "held_out"
    ]
    groups = {}
    for t in ranked:
        groups.setdefault(
            (
                *batch.task_dims(t),
                t["identity"]["operation"],
                t["identity"]["seed_role"],
                (t.get("config") or {}).get("sha256"),
            ),
            [],
        ).append(t)
    models = []
    mission = {} if case is None else {"mission": case["mission"]}
    # Leaves run on different INIs rank separately; the label names the INI only when needed.
    shared = {}
    for key in groups:
        shared[key[:6]] = shared.get(key[:6], 0) + 1
    for key, members in groups.items():
        row, training_seed, _, checkpoint, operation, role, config = key
        segment = _seed_segment(members[0]["identity"])
        label = f"{row} {segment} checkpoint-{checkpoint} {operation} {role}"
        name = f"{row}--{segment}--checkpoint-{checkpoint}--{operation}--{role}"
        if shared[key[:6]] > 1:
            label += f" config-{(config or 'none')[:12]}"
            name += f"--{(config or 'none')[:12]}"
        merged, _, _ = _pool(batch, members, [], label, allow_partial=True)
        view = attempt / "views" / name
        view.mkdir(parents=True, exist_ok=False)
        if merged is not None:
            outputs[batch.rel(view / EVAL_MANIFEST)] = _write(
                view / EVAL_MANIFEST, merged
            )
        record = batch.rows[row]
        models.append(
            {
                "scene": slug,
                **mission,
                "fixed": str(view),
                "reward": row,
                "profile": record["profile"],
                "training_seed": training_seed,
                "stage": members[0]["stage"],
                "label": label,
            }
        )
    if not models:
        # scene_review needs one entry to name the objective; a view without a manifest is skipped.
        models.append(
            {"scene": slug, **mission, "fixed": str(attempt / "views" / "none")}
        )
    payload = episode_review.scene_review(batch.root, slug, models)
    for t in results:
        directory = batch.dir_of(t["id"])
        if directory is None:
            continue
        policy = t["identity"]["policy"] if t["kind"] == "baseline" else None
        for data in (
            _load(directory / EVAL_MANIFEST),
            _load(directory / ONLINE_MANIFEST),
        ):
            if data is None:
                continue
            blocks = (
                [
                    b
                    for name, b in (data.get("policies") or {}).items()
                    if policy in (None, name)
                ]
                if "policies" in data
                else [{"episodes": data.get("episodes") or []}]
            )
            for block in blocks:
                for entry in block.get("episodes") or []:
                    path = _episode_dir(entry.get("episode_dir"), directory)
                    relative = batch.rel(path) if path is not None else None
                    if relative is None or relative in payload["episodes"]:
                        continue
                    if not (path / "steps.jsonl").is_file():
                        warnings.append(
                            f"{t['id']}: episode {relative} has no steps.jsonl"
                        )
                        continue
                    payload["episodes"][relative] = {
                        "metrics": episode_review.review_metrics(path),
                        "telemetry_sha256": sha256_file(path / "steps.jsonl"),
                    }
    # scene_review builds metric dicts from sets; sorted keys make the bytes reproducible.
    payload = json.loads(json.dumps(payload, sort_keys=True))
    outputs[batch.rel(attempt / REVIEW_NAME)] = _write(attempt / REVIEW_NAME, payload)
    warnings += [f"{tid}: no accepted result" for tid in missing]
    return {"outputs": outputs, "warnings": warnings, "incomplete": bool(missing)}
