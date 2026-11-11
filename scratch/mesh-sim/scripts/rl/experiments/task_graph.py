"""Plan v3 task identities, output paths and graph validation."""

from pathlib import Path, PurePosixPath

from scripts.artifact_io import canonical_sha256

EXPERIMENT_PLAN_VERSION = 3


PLAN_NAME = "experiment_plan.json"


COMPARISON_NAME = "comparison.json"


EVAL_MANIFEST = "eval_manifest.json"


ONLINE_MANIFEST = "online_manifest.json"


CHECK_RESULT = "check_result.json"


SELECTION_RECEIPT = "selection_receipt.json"


CURVE_SOURCES = "training_curve_sources.json"


REVIEW_NAME = "mission_review.json"


INDEX_NAME = "mission_scenario.json"


POST_UPDATE_CHECKPOINTS = "post_update_checkpoints.json"


OPERATE_MODULE = "scripts.rl.operate"


TRAIN_MODULE = "scripts.rl.train"


COMPARE_MODULE = "scripts.rl.compare"


# Every key hashes all of these; a dimension a task does not use is null.
KEY_DIMENSIONS = (
    "task_kind",
    "scenario",
    "row",
    "profile",
    "training_seed",
    "model_source",
    "checkpoint",
    "operation",
    "operation_digest",
    "protocol",
    "schedule_digest",
    "seed_role",
    "seed",
    "policy",
    "physical_digest",
    "check",
    "stage",
)


SUFFIX_LENGTH = 10


# Argument placeholders the scheduler substitutes at dispatch time.
ATTEMPT_DIR = "{attempt_dir}"


BINDING_RUN_DIR = "{binding_run_dir}"


BINDING_MODEL = "{binding_model}"


BINDING_PATH = "{binding_path}"


ACCEPTED_DIRS = "{accepted_dirs}"


def accepted_dir(task_id: str) -> str:
    """Placeholder for the accepted attempt directory of another task."""
    return "{accepted_dir:" + task_id + "}"


def task_key(identity: dict) -> str:
    """Full SHA-256 of the canonical identity (sorted keys, no whitespace)."""
    unknown = sorted(set(identity) - set(KEY_DIMENSIONS))
    if unknown:
        raise ValueError(f"unknown task identity dimensions {unknown}")
    return canonical_sha256({dim: identity.get(dim) for dim in KEY_DIMENSIONS})


def _join(root, *parts) -> str:
    return (
        str(PurePosixPath(root, *map(str, parts)))
        if isinstance(root, PurePosixPath)
        else str(Path(root, *map(str, parts)))
    )


class _Graph:
    def __init__(self, root):
        self.root = root
        self.tasks: list[dict] = []
        self.by_id: dict[str, dict] = {}

    def add(self, task_id: str, identity: dict, destination: list, **fields) -> dict:
        if task_id in self.by_id:
            raise ValueError(f"task id collision: {task_id}")
        key = task_key(identity)
        suffix = key[:SUFFIX_LENGTH]
        parts = [
            part.replace("{KEY}", key).replace("{K}", suffix)
            for part in map(str, destination)
        ]
        task = {
            "id": task_id,
            "key": key,
            "suffix": suffix,
            "kind": identity["task_kind"],
            "identity": {dim: identity.get(dim) for dim in KEY_DIMENSIONS},
            "needs": [],
            "needs_policy": "completed",
            "module": None,
            "handler": None,
            "args": None,
            "exit_codes": [0],
            "output_dir": _join(self.root, *parts),
            "attempts": "append",
            "expected_outputs": [],
            "inputs": [],
            "binding": None,
            "selection": None,
            "scenario": identity.get("scenario"),
            "row": identity.get("row"),
            "stage": identity.get("stage"),
        }
        task.update(fields)
        task["needs"] = list(dict.fromkeys(task["needs"]))
        missing = [need for need in task["needs"] if need not in self.by_id]
        if missing:
            raise ValueError(f"task {task_id} needs undeclared tasks {missing}")
        self.tasks.append(task)
        self.by_id[task_id] = task
        return task


def check_collisions(tasks: list[dict]) -> None:
    """Distinct keys, ids and non-nested destinations, checked before anything is written."""
    for field in ("id", "key", "output_dir"):
        seen = {}
        for task in tasks:
            if task[field] in seen:
                raise ValueError(
                    f"task {field} collision between {seen[task[field]]} and {task['id']}"
                )
            seen[task[field]] = task["id"]
    ordered = sorted(tasks, key=lambda t: t["output_dir"])
    for first, second in zip(ordered, ordered[1:]):
        if second["output_dir"].startswith(first["output_dir"].rstrip("/") + "/"):
            raise ValueError(
                f"task destination {second['output_dir']} ({second['id']}) is nested "
                f"inside {first['output_dir']} ({first['id']})"
            )
