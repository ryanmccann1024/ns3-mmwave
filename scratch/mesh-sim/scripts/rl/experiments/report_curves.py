"""Build training curves from the accepted checkpoint history."""

import csv
import os
from pathlib import Path

from scripts.artifact_io import sha256_file
from scripts.rl.experiments.plan import CURVE_SOURCES
from scripts.rl.experiments.report_artifacts import (
    _Batch,
    _load,
    _write,
    _write_csv,
)

TRAINING_CURVE_SOURCES_VERSION = 1


CURVES_CSV = "training_curves.csv"


CURVE_NOTE = (
    "Training seed episodes; changing policy and channel draws, not held-out checkpoint "
    "evaluations. PPO logs retain their original timestep counters and are cut at the "
    "accepted history boundary."
)


_PROGRESS_STEPS = "time/total_timesteps"


def _seed_segment(identity: dict) -> str:
    if identity["model_source"] is not None:
        return f"model-{identity['model_source'][:12]}"
    return f"train-seed-{identity['training_seed']}"


def _complete_episodes(directory: Path, decisions: int) -> list[tuple[Path, dict]]:
    found = []
    for path in sorted(directory.glob("episode-*/rl_episode.json")):
        record = _load(path)
        if (
            record
            and record.get("status") == "completed"
            and record.get("steps") == decisions
        ):
            found.append((path.parent, record))
    return found


def _progress(source: Path, target: Path, limit: int) -> str:
    """PPO progress rows up to the accepted boundary, so no optimizer point appears twice."""
    with source.open(newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        rows = [
            r
            for r in reader
            if _PROGRESS_STEPS not in fields
            or not r.get(_PROGRESS_STEPS)
            or float(r[_PROGRESS_STEPS]) <= limit
        ]
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, target)
    return sha256_file(target)


def _history(
    batch: _Batch, train_dir: Path, decisions: int, case: dict | None, gate_key
) -> tuple:
    """Accepted training history: (rows, sources, warnings), parents first."""
    rows, sources, warnings = [], [], []
    gate = ((case or {}).get("seeds") or {}).get(str(gate_key))
    physical = case is not None and gate is not None and decisions == 600
    if not physical:
        warnings.append(
            "physical curve metrics are defined for 600-decision episodes with a declared "
            "case gate; rows carry episode totals only"
        )

    def add(directory: Path, expected_total: int, selected: dict | None, source: str):
        manifest = _load(directory / "train_manifest.json")
        if manifest is None:
            raise ValueError(f"{batch.rel(directory)}: no readable train_manifest.json")
        resume = manifest.get("resume")
        start = 0
        if resume:
            restored = int(resume["restored_timesteps"])
            if restored % decisions:
                raise ValueError(
                    f"{batch.rel(directory)}: restored decisions are not whole episodes"
                )
            start = restored // decisions
            parent = resume["parent"]
            parent_dir = Path(parent["run_dir"]).resolve()
            if batch.rel(parent_dir) is not None:
                kind = (
                    "recovered"
                    if parent.get("model_selection") == "checkpoint"
                    else "parent"
                )
                add(parent_dir, start, parent, kind)
        episodes = _complete_episodes(directory, decisions)
        checkpoint = bool(selected and selected.get("model_selection") == "checkpoint")
        if checkpoint:
            from scripts.rl.policy.bundle import checkpoint_counters

            model = Path(selected["model_path"])
            if not model.is_file() or sha256_file(model) != selected["model_sha256"]:
                raise ValueError(
                    f"{batch.rel(directory)}: selected checkpoint bytes differ from the link"
                )
            if (
                checkpoint_counters(model)["num_timesteps"]
                != expected_total * decisions
            ):
                raise ValueError(
                    f"{batch.rel(directory)}: checkpoint counter is not {expected_total} episodes"
                )
        need = expected_total - start
        if len(episodes) < need or (not checkpoint and len(episodes) != need):
            raise ValueError(
                f"{batch.rel(directory)}: expected {need} complete episodes, found {len(episodes)}"
            )
        entry = {
            "directory": batch.rel(directory),
            "manifest_sha256": sha256_file(directory / "train_manifest.json"),
            "restored_episodes": start,
            "total_episodes": expected_total,
            "selected_checkpoint": None
            if not checkpoint
            else {
                **selected,
                "run_dir": batch.rel(selected["run_dir"]),
                "model_path": batch.rel(selected["model_path"]),
            },
            "complete_episodes_after_checkpoint_excluded": len(episodes) - need,
            "ppo_log_use_only_through_timesteps": expected_total * decisions,
        }
        sources.append(entry)
        for offset, (path, record) in enumerate(episodes[:need], 1):
            row = {
                "total_episode": start + offset,
                "training_seed": record.get("seed"),
                "source": source,
                "episode_dir": batch.rel(path),
                "steps": record.get("steps"),
                "cumulative_reward": record.get("cumulative_reward"),
            }
            if physical:
                from scripts.rl.policy.mission_metrics import (
                    physical as reduce_physical,
                )

                seed = record.get("seed")
                metrics = reduce_physical(
                    path, {**case, "seeds": {**case["seeds"], str(seed): gate}}, seed
                )
                row.update(
                    {
                        k: v
                        for k, v in metrics.items()
                        if v is None or isinstance(v, (int, float))
                    }
                )
            rows.append(row)

    manifest = _load(train_dir / "train_manifest.json")
    if manifest is None or manifest.get("status") != "completed":
        raise ValueError(
            f"{batch.rel(train_dir)}: accepted training has no completed train_manifest.json"
        )
    total = int(manifest.get("num_timesteps") or 0)
    if total % decisions:
        raise ValueError(
            f"{batch.rel(train_dir)}: {total} decisions are not whole episodes"
        )
    add(train_dir, total // decisions, None, "attempt")
    first = sources[0]["restored_episodes"]
    if [r["total_episode"] for r in rows] != list(
        range(first + 1, total // decisions + 1)
    ):
        raise ValueError(
            f"{batch.rel(train_dir)}: training curve has gaps or duplicates"
        )
    return rows, sources, warnings


def _curves(batch: _Batch, task: dict, attempt: Path) -> dict:
    outputs, warnings, incomplete, all_sources = {}, [], False, []
    case = batch.plan["scenarios"][task["scenario"]]["case"]
    for train_id in task["needs"]:
        train = batch.by_id[train_id]
        directory = batch.dir_of(train_id)
        if directory is None:
            warnings.append(f"{train_id}: no accepted training attempt")
            incomplete = True
            continue
        row = batch.rows[train["row"]]
        decisions = row.get("decisions_per_episode") or (row.get("training") or {}).get(
            "decisions_per_episode"
        )
        if not decisions:
            warnings.append(
                f"{train_id}: decisions per episode are not declared; no curve"
            )
            incomplete = True
            continue
        key = (train.get("config_lookup") or {}).get(
            "key", train["identity"]["training_seed"]
        )
        rows, sources, notes = _history(batch, directory, int(decisions), case, key)
        warnings += [f"{train_id}: {note}" for note in notes]
        target = (
            attempt / train["row"] / f"train-seed-{train['identity']['training_seed']}"
        )
        for index, source in enumerate(sources):
            progress = batch.root / source["directory"] / "ppo" / "progress.csv"
            if progress.is_file():
                copied = target / "curve_sources" / f"{index:02}-ppo-progress.csv"
                outputs[batch.rel(copied)] = _progress(
                    progress, copied, source["ppo_log_use_only_through_timesteps"]
                )
                source["ppo_progress"] = batch.rel(copied)
        fields = list(dict.fromkeys(k for r in rows for k in r))
        outputs[batch.rel(target / CURVES_CSV)] = _write_csv(
            target / CURVES_CSV, rows, fields
        )
        payload = {
            "training_curve_version": TRAINING_CURVE_SOURCES_VERSION,
            "sources": sources,
            "note": CURVE_NOTE,
        }
        outputs[batch.rel(target / CURVE_SOURCES)] = _write(
            target / CURVE_SOURCES, payload
        )
        all_sources += sources
    outputs[batch.rel(attempt / CURVE_SOURCES)] = _write(
        attempt / CURVE_SOURCES,
        {
            "training_curve_version": TRAINING_CURVE_SOURCES_VERSION,
            "sources": all_sources,
            "note": CURVE_NOTE,
        },
    )
    return {"outputs": outputs, "warnings": warnings, "incomplete": incomplete}
