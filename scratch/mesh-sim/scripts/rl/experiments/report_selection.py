"""Read the declared evidence from accepted attempts for policy selection."""

from pathlib import Path

from scripts.artifact_io import sha256_file
from scripts.rl.experiments.plan import EVAL_MANIFEST, ONLINE_MANIFEST
from scripts.rl.experiments.report_artifacts import (
    _Batch,
    _episode_dir,
    _load,
    _split_task,
)


def _validation_item(batch: _Batch, task: dict, directory: Path) -> dict:
    """Best validation reward and per-evaluation means of one accepted training attempt."""
    import numpy as np

    from scripts.rl.policy.training_artifacts import EVAL_LOG_NAME

    path = directory / "train_manifest.json"
    manifest = _load(path)
    if manifest is None or manifest.get("status") != "completed":
        raise ValueError(
            f"selection blocked: {task['id']} has no completed training manifest"
        )
    seeds = set((manifest.get("evaluation") or {}).get("seeds") or [])
    if seeds & set(batch.plan["seeds"].get("held_out") or []):
        raise ValueError(
            f"selection never consumes held-out evidence: {task['id']} validated on "
            f"{sorted(seeds)}"
        )
    log = directory / EVAL_LOG_NAME
    if not log.is_file() or manifest.get("best_mean_reward") is None:
        raise ValueError(f"selection blocked: {task['id']} has no validation results")
    with np.load(log) as evaluations:
        means = [float(v) for v in evaluations["results"].mean(axis=1)]
    return {
        "best_mean_reward": manifest["best_mean_reward"],
        "checkpoint_means": means,
        "evaluations": batch.rel(log),
        "evaluations_sha256": sha256_file(log),
        "samples": len(means),
    }, path


def _score_item(task: dict, directory: Path, online: bool) -> tuple:
    """Mission scores of an accepted operation leaf, from ``policy.mission_metrics``."""
    from scripts.rl.policy import mission_metrics

    path = directory / (
        ONLINE_MANIFEST
        if online or not (directory / EVAL_MANIFEST).is_file()
        else EVAL_MANIFEST
    )
    record = _load(path)
    if record is None or record.get("status") != "completed":
        raise ValueError(
            f"selection blocked: {task['id']} has no completed {path.name}"
        )
    if path.name == EVAL_MANIFEST:
        entries = ((record.get("policies") or {}).get("model") or {}).get(
            "episodes"
        ) or []
    else:
        entries = [
            e
            for e in record.get("episodes") or []
            if e.get("mode") == task["identity"]["protocol"]
        ]
    seed = task["identity"]["seed"]
    if len(entries) != 1 or entries[0].get("seed") != seed:
        raise ValueError(
            f"selection blocked: {task['id']} needs one episode for seed {seed} in {path.name}"
        )
    entry = entries[0]
    episode = _episode_dir(entry.get("episode_dir"), directory)
    if episode is None or not episode.is_relative_to(directory.resolve()):
        raise ValueError(
            f"selection blocked: {task['id']} episode is outside its accepted attempt"
        )
    score = mission_metrics.mission_episode_metrics(episode)["mission_score"]
    return {
        "values": [score],
        "telemetry_sha256": [sha256_file(episode / "steps.jsonl")],
        "samples": 1,
    }, path


def selection_evidence(task: dict, plan: dict, root, accepted: dict) -> dict:
    """Evidence for ``selection.select``: {candidate: [item, ...]} from the declared sources only.

    Each item names its source ``task``, accepted ``attempt`` (relative), the
    ``path``/``sha256`` of the manifest it read, ``seed_role``, ``case``
    (scenario) and ``samples``. The validation rule adds ``best_mean_reward``
    and ``checkpoint_means`` (per-evaluation means, as the retired
    ``adaptive_campaign.select_profile`` read them); the mission and online
    rules add ``values`` (episode mission scores) plus the source ``row``,
    ``operation`` and ``checkpoint``. ``source_kind`` picks the inputs: train
    attempts (``training_validation``) or operate leaves at exactly the select
    task's checkpoint (``operation``, for row or ``{row, operation}``
    candidates). A missing or undeclared source or a held-out seed role raises;
    ``none`` (replay) needs no evidence.
    """
    task, _ = _split_task(task, None)
    batch = _Batch(plan, root, accepted)
    if batch.by_id.get(task.get("id")) != task or task.get("handler") != "select":
        raise ValueError(f"{task.get('id')} is not a select task of this plan")
    rule = task["selection_rule"]
    kind = rule.get("source_kind")
    if kind == "none":
        return {}
    if kind not in ("training_validation", "operation"):
        raise ValueError(f"{task['id']}: unknown selection source kind {kind!r}")
    online = rule["rule"] == "legacy-online-profile-v1"
    checkpoint = task["identity"]["checkpoint"]
    evidence = {}
    for candidate, entries in rule["candidates"].items():
        # Declared inputs: rows (with source_operation) or explicit {row, operation} entries.
        declared = {
            (e, rule["source_operation"])
            if isinstance(e, str)
            else (e["row"], e["operation"])
            for e in entries
        }
        ids = rule["sources"].get(candidate) or []
        if not ids:
            raise ValueError(
                f"selection blocked: candidate {candidate} declares no source tasks"
            )
        items = []
        for source_id in ids:
            source = batch.by_id[source_id]
            if kind == "training_validation":
                if source["kind"] != "train" or source["row"] not in {
                    row for row, _ in declared
                }:
                    raise ValueError(
                        f"selection blocked: {source_id} is not a declared input of {candidate}"
                    )
            elif (
                source["kind"] != "operate"
                or (source["row"], source["identity"]["operation"]) not in declared
                or source["identity"]["checkpoint"] != checkpoint
            ):
                raise ValueError(
                    f"selection blocked: {source_id} is not a declared input of {candidate} "
                    f"at checkpoint {checkpoint}"
                )
            directory = batch.dir_of(source_id)
            if directory is None:
                raise ValueError(
                    f"selection blocked: {source_id} has no accepted result"
                )
            if kind == "training_validation":
                role = "model_selection"
                item, path = _validation_item(batch, source, directory)
            else:
                role = source["identity"]["seed_role"]
                if role == "held_out" or role != rule["seed_role"]:
                    raise ValueError(
                        f"selection never consumes {role!r} evidence ({source_id})"
                    )
                item, path = _score_item(source, directory, online)
                item = {
                    "row": source["row"],
                    "operation": source["identity"]["operation"],
                    "checkpoint": checkpoint,
                    **item,
                }
            items.append(
                {
                    "task": source_id,
                    "attempt": batch.rel(directory),
                    "path": batch.rel(path),
                    "sha256": sha256_file(path),
                    "seed_role": role,
                    "case": source["scenario"],
                    **item,
                }
            )
        evidence[candidate] = items
    return evidence
