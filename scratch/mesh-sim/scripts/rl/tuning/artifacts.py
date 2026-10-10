"""Versioned study/trial records and atomic sampler recovery checkpoints."""

import fcntl
import hashlib
import json
import os
import pickle
import platform
import tempfile
from contextlib import contextmanager
from pathlib import Path

from scripts.artifact_io import canonical_sha256, now_iso, sha256_file, write_json
from scripts.rl.cli_common import MANIFEST_NAME as TRAIN_MANIFEST_NAME, package_versions
from scripts.rl.env.config import read_scenario_identity
from scripts.rl.tuning.trainer import get_trainer

STUDY_MANIFEST_VERSION = 2
TRIAL_VERSION = 2
STUDY_MANIFEST_NAME = "study_manifest.json"
TRIAL_NAME = "trial.json"
CHECKPOINT_NAME = "study-checkpoint.bin"
CHECKPOINT_VERSION = 1



def identity(spec, binary):
    row = next(row for row in spec["matrix"]["rows"] if row["name"] == spec["row"])
    return canonical_sha256({"spec": spec["sha256"], "matrix": spec["matrix"]["sha256"],
                             "scenario": read_scenario_identity(row["run_config"]),
                             "binary": sha256_file(binary), "trainer": spec["trainer"],
                             "python": platform.python_version(),
                             "packages": package_versions()})


@contextmanager
def study_lock(root):
    """Permit one writer for the study, including its sampler checkpoint."""
    root.mkdir(parents=True, exist_ok=True)
    with open(root / ".study.lock", "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another process is writing this study") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)



def manifest(spec, study, binary):
    matrix = spec["matrix"]
    trainer = get_trainer(spec["trainer"])
    return {"study_manifest_version": STUDY_MANIFEST_VERSION, "status": "running",
            "spec": {"path": spec["path"], "sha256": spec["sha256"], "body": spec["body"]},
            "matrix": {"path": matrix["path"], "sha256": matrix["sha256"], "name": matrix["name"]},
            "row": spec["row"], "trainer": trainer.name,
            "seed_roles": {"training": spec["training_seed"],
                           "model_selection": matrix["seeds"]["model_selection"],
                           "held_out_used": False},
            "objective": {"name": trainer.objective_name, "direction": trainer.direction,
                          "source": TRAIN_MANIFEST_NAME, "seed_role": "model_selection",
                          "episodes_per_evaluation": matrix["training"].get("eval_episodes", 1)},
            "sampler": spec["sampler"],
            "fixed_training": {key: value for key, value in matrix["training"].items()
                               if key not in spec["search_space"]},
            "optuna_version": study.version, "package_versions": package_versions(),
            "python_version": platform.python_version(),
            "platform": {"system": platform.system(), "machine": platform.machine()},
            "sim_binary": binary, "trials": [], "best": None,
            "started_at": now_iso(), "ended_at": None, "resume_events": []}



def best(records, direction):
    completed = [record for record in records if record["state"] == "complete"]
    if not completed:
        return None
    selected = (max if direction == "maximize" else min)(completed,
                                                          key=lambda record: record["objective"])
    return {"number": selected["number"], "objective": selected["objective"],
            "training": selected["training"]}



def publish(root, state):
    """Commit the authoritative snapshot first, then refresh readable JSON mirrors."""
    body = pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL)
    header = {"checkpoint_version": CHECKPOINT_VERSION, "identity": state["identity"],
              "optuna_version": state["study"].version,
              "sha256": hashlib.sha256(body).hexdigest()}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix=".study-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(header).encode() + b"\n" + body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, root / CHECKPOINT_NAME)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    write_json(root / STUDY_MANIFEST_NAME, state["manifest"])
    for record in state["manifest"]["trials"]:
        directory = root / "trials" / f"trial-{record['number']:04d}"
        directory.mkdir(parents=True, exist_ok=True)
        write_json(directory / TRIAL_NAME, record)



def restore(root, expected_identity, version):
    """Load this locally created checkpoint after checking inputs and runtime version."""
    with open(root / CHECKPOINT_NAME, "rb") as handle:
        header = json.loads(handle.readline())
        body = handle.read()
    if header.get("checkpoint_version") != CHECKPOINT_VERSION:
        raise ValueError("unsupported study checkpoint version")
    if header.get("identity") != expected_identity:
        raise ValueError("study inputs, binary or runtime changed; resume refused")
    if header.get("optuna_version") != version:
        raise ValueError("Optuna version changed; resume refused")
    if header.get("sha256") != hashlib.sha256(body).hexdigest():
        raise ValueError("study checkpoint integrity check failed")
    state = pickle.loads(body)
    if state["identity"] != expected_identity:
        raise ValueError("study checkpoint identity mismatch")
    return state
