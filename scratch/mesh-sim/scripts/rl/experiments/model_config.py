"""Resolve saved models and checkpoint selectors used by a batch."""

import json
import re
from pathlib import Path

from scripts.artifact_io import canonical_sha256, sha256_file
from scripts.rl.experiments.matrix_fields import (
    _check_keys,
    _input_path,
)
from scripts.rl.experiments.scenario_timing import (
    native_decisions as native_decisions,
)
from scripts.rl.policy.bundle import checkpoint_counters
from scripts.rl.policy.training_artifacts import CHECKPOINT_DIR

_CHECKPOINT_RE = re.compile(r"^checkpoint_(\d+)_steps\.zip$")


def _model_source(raw, base: Path, where: str) -> dict:
    """Verify a completed parent run and its selected model without loading it."""
    _check_keys(raw, ("run_dir", "model"), where)
    run_dir = _input_path(raw.get("run_dir"), base, f"{where}.run_dir", "dir")
    model = raw.get("model", "final")
    manifest_path = Path(run_dir["path"]) / "train_manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"{where}: no train_manifest.json in {run_dir['path']}")
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict) or manifest.get("status") != "completed":
        raise ValueError(f"{where}: parent run is not a completed training run")
    if model == "final":
        path, digest = manifest.get("model_path"), manifest.get("model_sha256")
    elif model == "best":
        path, digest = (
            manifest.get("best_model_path"),
            manifest.get("best_model_sha256"),
        )
        if not path:
            raise ValueError(
                f"{where}: 'best' needs a verified best model; the parent has none"
            )
    else:
        relative = Path(str(model))
        if (
            relative.is_absolute()
            or len(relative.parts) != 2
            or relative.parts[0] != CHECKPOINT_DIR
            or not _CHECKPOINT_RE.match(relative.name)
        ):
            raise ValueError(
                f"{where}.model must be final, best or {CHECKPOINT_DIR}/<file>.zip"
            )
        target = (Path(run_dir["path"]) / relative).resolve()
        entry = next(
            (
                e
                for e in manifest.get("checkpoints") or []
                if Path(e.get("path", "")).resolve() == target
            ),
            None,
        )
        if entry is None:
            raise ValueError(
                f"{where}: {model} is not a retained checkpoint of the parent"
            )
        path, digest = entry.get("path"), entry.get("sha256")
    if not path or not digest or not Path(path).is_file():
        raise ValueError(f"{where}: model file for {model!r} is missing")
    actual = sha256_file(path)
    if actual != digest:
        raise ValueError(f"{where}: model digest mismatch for {path}")
    counters = checkpoint_counters(path, require_updates=False)
    source = {
        "run_dir": run_dir["path"],
        "reference": run_dir["reference"],
        "model": model,
        "model_path": str(Path(path).resolve()),
        "model_sha256": digest,
        "manifest_sha256": sha256_file(manifest_path),
        "num_timesteps": counters["num_timesteps"],
        "n_updates": counters["n_updates"],
        "seed": manifest.get("seed"),
        "selection": manifest.get("selection"),
        "run_ini_sha256": (manifest.get("scenario_identity") or {}).get(
            "run_ini_sha256"
        ),
        "hyperparameters": manifest.get("hyperparameters") or {},
    }
    source["digest"] = canonical_sha256(
        {k: source[k] for k in ("manifest_sha256", "model", "model_sha256")}
    )
    return source


def retained_checkpoints(start: int, total: int, every: int, keep: int) -> list[int]:
    """Cumulative steps of the checkpoints a completed run retains (newest `keep`)."""
    if every <= 0:
        return []
    first = (start // every + 1) * every
    return list(range(first, total + 1, every))[-keep:]


def model_selector(model) -> object:
    """Checkpoint selector of an imported model: final, best or its cumulative steps."""
    if model in ("final", "best"):
        return model
    match = _CHECKPOINT_RE.match(Path(str(model)).name)
    return int(match.group(1)) if match else str(model)
