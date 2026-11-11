"""Map an experiment plan onto array tasks and read their filesystem state."""

import json
from pathlib import Path

from scripts.rl.policy.experiment import PLAN_NAME, load_plan, step_state

TASKS_VERSION = 1

_TOLERATED = {"train": (0,), "evaluate": (0, 2), "compare": (0, 2)}
_OUTCOMES = ("complete", "incomplete")

# Plan v3 child modules a worker may launch; nothing else named in plan JSON runs.
STEP_MODULES = ("scripts.rl.train", "scripts.rl.operate", "scripts.rl.compare")
_ATTEMPT_DIR = "{attempt_dir}"
_BINDING_RUN_DIR = "{binding_run_dir}"
_BINDING_MODEL = "{binding_model}"
_BINDING_PATH = "{binding_path}"
_ACCEPTED_DIRS = "{accepted_dirs}"
_ACCEPTED_PREFIX = "{accepted_dir:"
_SELECTION_FLAGS = ("--observation-preset", "--reward-components", "--reward-weights",
                    "--observation-parameters", "--reward-parameters")
_CONTINUE_FLAGS = ("--continue-from-run-dir", "--continue-model")

__all__ = ["TASKS_VERSION", "PLAN_NAME", "load_plan", "step_state", "plan_root",
           "build_tasks", "compare_step", "tolerated", "task_fs_state",
           "compare_prerequisites", "comparison_outcome", "STEP_MODULES", "step_module",
           "binding_model_selector", "substitute_args", "resume_train_args", "arg_value"]


def _steps(plan: dict, kind: str) -> list[dict]:
    steps = plan.get("steps")
    if not isinstance(steps, list):
        raise ValueError("plan has no step list")
    return [step for step in steps if step.get("kind") == kind]


def compare_step(plan: dict) -> dict:
    """Return the plan's single compare step."""
    steps = _steps(plan, "compare")
    if len(steps) != 1:
        raise ValueError(f"plan must hold exactly one compare step, found {len(steps)}")
    return steps[0]


def plan_root(plan: dict) -> Path:
    """Output root the plan was written for, taken from the compare step's --plan."""
    args = compare_step(plan).get("args") or []
    if "--plan" not in args or args.index("--plan") + 1 >= len(args):
        raise ValueError("compare step has no --plan argument")
    path = Path(args[args.index("--plan") + 1])
    if path.name != PLAN_NAME:
        raise ValueError(f"compare step --plan is not a {PLAN_NAME} path: {path}")
    return path.parent


def build_tasks(plan: dict) -> list[dict]:
    """Pair every train step with the evaluate step that needs it, in plan order."""
    compare_step(plan)
    evaluations = _steps(plan, "evaluate")
    by_need: dict[str, dict] = {}
    for step in evaluations:
        for need in step.get("needs") or []:
            by_need.setdefault(need, step)

    tasks, paired = [], set()
    for index, train in enumerate(_steps(plan, "train")):
        evaluate = by_need.get(train["id"])
        if evaluate is None:
            raise ValueError(f"no evaluate step needs {train['id']}")
        paired.add(evaluate["id"])
        tasks.append({"index": index, "id": train["id"].removeprefix("train/"),
                      "train": train, "evaluate": evaluate})
    unpaired = [step["id"] for step in evaluations if step["id"] not in paired]
    if unpaired:
        raise ValueError(f"evaluate steps without a train step: {unpaired}")
    if not tasks:
        raise ValueError("plan has no train steps")
    return tasks


def tolerated(kind: str, code: int) -> bool:
    """Whether this exit code counts as success for that kind of step."""
    if kind not in _TOLERATED:
        raise ValueError(f"unknown step kind {kind!r}; valid: {sorted(_TOLERATED)}")
    return code in _TOLERATED[kind]


def _manifest_status(step: dict) -> str | None:
    path = Path(step["output_dir"]) / step["manifest"]
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    status = data.get("status") if isinstance(data, dict) else None
    return status if isinstance(status, str) else None


def task_fs_state(task: dict) -> dict:
    """State of both of a task's steps plus the train manifest's own status field."""
    return {"train": step_state(task["train"]),
            "evaluate": step_state(task["evaluate"]),
            "train_manifest_status": _manifest_status(task["train"])}


def compare_prerequisites(plan: dict) -> dict:
    """Which evaluations are not finished, so a comparison would be incomplete."""
    missing, partial = [], []
    for step in _steps(plan, "evaluate"):
        state = step_state(step)[0]
        if state == "partial":
            partial.append(step["id"])
        elif state != "done":
            missing.append(step["id"])
    return {"ready": not missing and not partial, "missing": missing,
            "partial": partial}


def comparison_outcome(plan: dict) -> dict:
    """Read comparison.json's status, which step_state alone cannot distinguish."""
    step = compare_step(plan)
    path = Path(step["output_dir"]) / step["manifest"]
    if not path.is_file():
        return {"state": "absent", "path": str(path)}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"state": "unreadable", "path": str(path)}
    status = data.get("status") if isinstance(data, dict) else None
    state = status if status in _OUTCOMES else "unreadable"
    return {"state": state, "path": str(path)}


def step_module(task: dict) -> str:
    """The allowlisted module a plan v3 task launches; handlers and others are refused."""
    module = task.get("module")
    if task.get("handler") is not None or module not in STEP_MODULES:
        raise ValueError(f"task {task.get('id')} does not launch an allowlisted module "
                         f"(module {module!r}, handler {task.get('handler')!r})")
    return module


def binding_model_selector(binding: dict) -> str:
    """--model value for a binding record: final, best or checkpoints/NAME.zip of its run."""
    selection = binding["model_selection"]
    if selection in ("final", "best"):
        return selection
    model, run_dir = Path(binding["model_path"]), Path(binding["run_dir"])
    if model.parent != run_dir / "checkpoints":
        raise ValueError(f"bound checkpoint {model} is not in {run_dir}/checkpoints")
    return f"checkpoints/{model.name}"


def substitute_args(task: dict, attempt_dir, binding: dict | None = None,
                    accepted: dict | None = None, accepted_dirs: list | None = None,
                    binding_path=None) -> list[str]:
    """Replace whole-argument placeholders; any placeholder left unresolved is an error.

    `binding` is a write-once model binding record stored at `binding_path`,
    `accepted` maps task ids to their accepted attempt directories and
    `accepted_dirs` expands in place.
    """
    accepted = accepted or {}
    out = []
    for arg in task.get("args") or []:
        if arg == _ATTEMPT_DIR:
            out.append(str(attempt_dir))
        elif arg in (_BINDING_RUN_DIR, _BINDING_MODEL):
            if binding is None:
                raise ValueError(f"task {task['id']} needs a model binding for {arg}")
            out.append(binding["run_dir"] if arg == _BINDING_RUN_DIR else binding_model_selector(binding))
        elif arg == _BINDING_PATH:
            if binding_path is None:
                raise ValueError(f"task {task['id']} needs a model binding file for {arg}")
            out.append(str(binding_path))
        elif arg == _ACCEPTED_DIRS:
            if not accepted_dirs:
                raise ValueError(f"task {task['id']} has no accepted directories for {arg}")
            out.extend(str(d) for d in accepted_dirs)
        elif arg.startswith(_ACCEPTED_PREFIX) and arg.endswith("}"):
            source = arg[len(_ACCEPTED_PREFIX):-1]
            if not accepted.get(source):
                raise ValueError(f"task {task['id']} needs the accepted attempt of {source}")
            out.append(str(accepted[source]))
        else:
            out.append(arg)
    left = [a for a in out if a in (_ATTEMPT_DIR, _BINDING_RUN_DIR, _BINDING_MODEL, _BINDING_PATH,
                                    _ACCEPTED_DIRS)
            or a.startswith(_ACCEPTED_PREFIX)]
    if left:
        raise ValueError(f"task {task['id']} has unresolved placeholders {left}")
    return out


def arg_value(args: list, flag: str):
    """Value following `flag` (or of `flag=value`) in an argument list, else None."""
    for index, arg in enumerate(args):
        if arg == flag and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith(flag + "="):
            return arg.split("=", 1)[1]
    return None


def resume_train_args(args: list, parent_run_dir, checkpoint: str) -> list[str]:
    """A train task's arguments rewritten to continue from a verified retained checkpoint.

    Selection and continuation flags are dropped (train.py takes them from the
    parent manifest when resuming); every PPO setting and budget is unchanged.
    """
    if "--curriculum-schedule" in args:
        raise ValueError("curriculum training cannot resume from a checkpoint")
    out, skip = [], False
    for arg in args:
        if skip:
            skip = False
            continue
        name = arg.split("=", 1)[0]
        if name in _SELECTION_FLAGS + _CONTINUE_FLAGS:
            skip = "=" not in arg
            continue
        out.append(arg)
    return out + ["--resume-run-dir", str(parent_run_dir), "--resume-checkpoint", checkpoint]
