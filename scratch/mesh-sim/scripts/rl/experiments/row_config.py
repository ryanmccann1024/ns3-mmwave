"""Resolve experiment rows, training settings and rollout budgets."""

from scripts.artifact_io import sha256_file
from scripts.rl.agents.config import PPO_FIELDS, validate_training_settings
from scripts.rl.env.config import read_action_profile
from scripts.rl.env.selection import resolve_selection
from scripts.rl.experiments.matrix_fields import (
    OPERATION_SEED_ROLES,
    SEED_ROLES,
    _check_disjoint,
    _check_keys,
    _distinct_names,
    _input_path,
    _int,
    _name,
    _positive_int,
    _scalar,
    _seed_list,
    _string_array,
    _weight_array,
)
from scripts.rl.experiments.model_config import (
    _model_source,
    retained_checkpoints,
)
from scripts.rl.experiments.scenario_config import (
    _row_configs,
    config_for,
)
from scripts.rl.experiments.scenario_timing import (
    native_decisions as native_decisions,
)
from scripts.sim_support import parse_ini

CHECKPOINT_TIMINGS = ("standard", "after_update")


_TRAINING_KEYS = (
    *PPO_FIELDS,
    "eval_every_steps",
    "checkpoint_every_steps",
    "keep_checkpoints",
    "checkpoint_timing",
    "decisions_per_episode",
    "total_episodes",
)


_ROW_SELECTION_KEYS = (
    "observation_preset",
    "action_profile",
    "reward_components",
    "reward_weights",
    "observation_parameters",
    "reward_parameters",
)


_ROW_KEYS = {
    "train": (
        "name",
        "scenario",
        "profile",
        *_ROW_SELECTION_KEYS,
        "training",
        "seeds",
        "configs",
        "operations",
        "training_config_key",
        "continue_from",
        "curriculum",
        "labels",
    ),
    "evaluate": (
        "name",
        "scenario",
        "profile",
        *_ROW_SELECTION_KEYS,
        "operations",
        "configs",
        "model_source",
        "labels",
    ),
    "checks": ("name", "scenario", "profile", *_ROW_SELECTION_KEYS, "labels"),
}


_LABEL_KEYS = ("reward_label", "ppo_label", "comparison", "source_phase", "tags")


def _training(raw, where: str, override: bool = False) -> dict:
    _check_keys(raw, _TRAINING_KEYS, where)
    settings = {
        key: value if key == "net_arch" else _scalar(value, f"{where}.{key}")
        for key, value in raw.items()
    }
    ppo = {
        key: value
        for key, value in settings.items()
        if key not in ("checkpoint_timing", "decisions_per_episode", "total_episodes")
    }
    try:
        validate_training_settings(ppo)
    except ValueError as exc:
        raise ValueError(f"{where}: {exc}") from exc
    timing = settings.get("checkpoint_timing", "standard")
    if timing not in CHECKPOINT_TIMINGS:
        raise ValueError(
            f"{where}.checkpoint_timing must be one of {list(CHECKPOINT_TIMINGS)}"
        )
    if not override:
        settings["checkpoint_timing"] = timing
    for key in ("decisions_per_episode", "total_episodes"):
        if key in settings:
            _positive_int(settings[key], f"{where}.{key}")
    return settings


def _labels(raw, where: str) -> dict:
    _check_keys(raw, _LABEL_KEYS, where)
    labels = {}
    for key in ("reward_label", "ppo_label", "comparison"):
        if key in raw:
            if not isinstance(raw[key], str):
                raise ValueError(f"{where}.{key} must be a string")
            labels[key] = raw[key]
    if "source_phase" in raw:
        if raw["source_phase"] is not None:
            _int(raw["source_phase"], f"{where}.source_phase")
        labels["source_phase"] = raw["source_phase"]
    if "tags" in raw:
        if not isinstance(raw["tags"], list) or not all(
            isinstance(t, str) for t in raw["tags"]
        ):
            raise ValueError(f"{where}.tags must be an array of strings")
        labels["tags"] = list(raw["tags"])
    return labels


def _selection_fields(
    raw: dict, run_config: str, where: str, required: bool
) -> dict | None:
    present = [key for key in _ROW_SELECTION_KEYS if key in raw]
    if not present and not required:
        return None
    preset = _scalar(raw.get("observation_preset"), f"{where}.observation_preset")
    if not isinstance(preset, str) or not preset:
        raise ValueError(f"{where}.observation_preset must be a string")
    profile = _scalar(raw.get("action_profile"), f"{where}.action_profile")
    components = _string_array(
        raw.get("reward_components"), f"{where}.reward_components"
    )
    weights = _weight_array(raw.get("reward_weights"), f"{where}.reward_weights")
    configured = read_action_profile(run_config)
    if profile != configured:
        raise ValueError(
            f"{where}.action_profile is {profile!r} but {run_config} "
            f"configures {configured!r}"
        )
    try:
        selection = resolve_selection(
            run_config,
            observation_preset=preset,
            reward_components=",".join(components),
            reward_weights=",".join(str(w) for w in weights),
            observation_parameters=raw.get("observation_parameters"),
            reward_parameters=raw.get("reward_parameters"),
        )
    except ValueError as exc:
        raise ValueError(f"{where}: {exc}") from exc
    return {
        "observation_preset": preset,
        "action_profile": profile,
        "reward_components": components,
        "reward_weights": weights,
        "observation_parameters": selection.observation_parameters,
        "reward_parameters": selection.reward_parameters,
    }


def _check_parent_selection(selection: dict | None, parent: dict, where: str) -> None:
    saved = parent.get("selection") or {}
    if selection is None:
        return
    for key in (
        "observation_preset",
        "reward_components",
        "reward_weights",
        "observation_parameters",
        "reward_parameters",
    ):
        if key in saved and saved[key] != selection[key]:
            raise ValueError(
                f"{where}: {key} differs from the parent model's selection"
            )


def _row(raw, index: int, kind: str, context: dict) -> dict:
    where = f"rows[{index}]"
    _check_keys(raw, _ROW_KEYS[kind], where)
    name = _name(_scalar(raw.get("name"), f"{where}.name"), f"{where}.name")
    where = f"row {name}"
    scenario_name = raw.get("scenario")
    if scenario_name not in context["scenarios"]:
        raise ValueError(
            f"{where}.scenario {scenario_name!r} is not declared in scenarios"
        )
    scenario = context["scenarios"][scenario_name]
    profile = raw.get("profile")
    if kind == "train" or profile is not None:
        profile = _name(profile, f"{where}.profile")
    base = context["base"]
    row = {
        "name": name,
        "scenario": scenario_name,
        "profile": profile,
        "labels": _labels(raw.get("labels", {}), f"{where}.labels"),
        "training": None,
        "training_seeds": [],
        "training_config_key": None,
        "continue_from": None,
        "model_source": None,
        "curriculum": None,
        "operations": [],
        "selection": None,
        "configs": {},
    }
    if raw.get("configs") is not None:
        roles = SEED_ROLES if kind == "train" else OPERATION_SEED_ROLES
        row["configs"] = _row_configs(raw["configs"], base, f"{where}.configs", roles)
        for role, entries in row["configs"].items():
            if role == "training":
                continue  # lookup keys, checked against training_config_key/seeds below
            unused = sorted(
                int(seed) for seed in entries if int(seed) not in context["seeds"][role]
            )
            if unused:
                raise ValueError(
                    f"{where}.configs.{role} names seeds {unused} that are not "
                    f"declared {role} seeds"
                )
    operation_ids = [op["id"] for op in context["operations"]]
    if "operations" in raw:
        row["operations"] = _distinct_names(raw["operations"], f"{where}.operations")
        unknown = [op for op in row["operations"] if op not in operation_ids]
        if unknown:
            raise ValueError(f"{where}.operations {unknown} are not declared")
    else:
        row["operations"] = operation_ids

    if kind == "train":
        overrides = _training(
            raw.get("training", {}), f"{where}.training", override=True
        )
        merged = {**context["training"], **overrides}
        row["training"] = _training(merged, f"{where} effective training")
        seeds = raw.get("seeds")
        if seeds is not None:
            _check_keys(seeds, ("training",), f"{where}.seeds")
            row["training_seeds"] = _seed_list(
                seeds.get("training", []), f"{where}.seeds.training"
            )
        else:
            row["training_seeds"] = list(context["seeds"]["training"])
        if not row["training_seeds"]:
            raise ValueError(
                f"{where} has no training seed; kind 'train' needs at least one"
            )
        _check_disjoint(
            {
                "row training": set(row["training_seeds"]),
                **{
                    f"seeds.{r}": set(context["seeds"][r]) for r in OPERATION_SEED_ROLES
                },
            }
        )
        key = raw.get("training_config_key")
        if key is not None:
            if isinstance(key, bool) or not str(key).isdigit():
                raise ValueError(
                    f"{where}.training_config_key must be a seed integer or string"
                )
            if str(key) not in row["configs"].get("training", {}) and str(
                key
            ) not in scenario["configs"].get("training", {}):
                raise ValueError(
                    f"{where}.training_config_key {key} has no rows[].configs.training "
                    f"or scenarios.{scenario_name}.configs.training entry"
                )
            row["training_config_key"] = str(key)
        used = (
            {row["training_config_key"]}
            if row["training_config_key"]
            else {str(seed) for seed in row["training_seeds"]}
        )
        unused = sorted(set(row["configs"].get("training", {})) - used)
        if unused:
            raise ValueError(
                f"{where}.configs.training keys {unused} match neither "
                "training_config_key nor the row's training seeds"
            )
        if raw.get("curriculum") is not None:
            row["curriculum"] = _input_path(
                raw["curriculum"], base, f"{where}.curriculum"
            )
        configs = [
            config_for(scenario, "training", row["training_config_key"] or seed, row)
            for seed in row["training_seeds"]
        ]
        selections = [
            _selection_fields(raw, c["path"], where, required=True) for c in configs
        ]
        if any(s != selections[0] for s in selections[1:]):
            raise ValueError(
                f"{where}: the selection resolves differently across training configs"
            )
        row["selection"] = selections[0]
        config = configs[0]
        if raw.get("continue_from") is not None:
            parent = _model_source(raw["continue_from"], base, f"{where}.continue_from")
            if len(row["training_seeds"]) != 1:
                raise ValueError(
                    f"{where}: a continuation names exactly one training seed"
                )
            if parent["seed"] != row["training_seeds"][0]:
                raise ValueError(
                    f"{where}: continuation seed {row['training_seeds'][0]} differs "
                    f"from the parent's seed {parent['seed']}"
                )
            if row["training"]["total_timesteps"] <= parent["num_timesteps"]:
                raise ValueError(
                    f"{where}: total_timesteps {row['training']['total_timesteps']} "
                    f"must exceed the parent's {parent['num_timesteps']} "
                    "(it includes the parent's steps)"
                )
            if parent["run_ini_sha256"] and parent["run_ini_sha256"] != sha256_file(
                config["path"]
            ):
                raise ValueError(
                    f"{where}: training INI bytes differ from the parent's "
                    "strict resume identity"
                )
            for key_name, value in parent["hyperparameters"].items():
                if (
                    key_name in PPO_FIELDS
                    and key_name != "total_timesteps"
                    and key_name in row["training"]
                ):
                    declared = row["training"][key_name]
                    if key_name == "net_arch":
                        declared, value = list(declared), list(value)
                    if declared != value:
                        raise ValueError(
                            f"{where}: {key_name} differs from the parent's PPO settings"
                        )
            _check_parent_selection(row["selection"], parent, where)
            row["continue_from"] = parent
        decisions = {native_decisions(c["path"]) for c in configs}
        if len(decisions) != 1:
            raise ValueError(
                f"{where}: training configs differ in decisions per episode {sorted(decisions)}"
            )
        _check_training_budget(row, config["path"], context, where)
    elif kind == "evaluate":
        if raw.get("model_source") is None:
            raise ValueError(f"{where}.model_source is required for kind 'evaluate'")
        row["model_source"] = _model_source(
            raw["model_source"], base, f"{where}.model_source"
        )
        row["selection"] = _selection_fields(
            raw, scenario["run_config"]["path"], where, required=False
        )
        _check_parent_selection(row["selection"], row["model_source"], where)
    else:
        row["selection"] = _selection_fields(
            raw, scenario["run_config"]["path"], where, required=True
        )
    return row


def _check_training_budget(
    row: dict, run_config: str, context: dict, where: str
) -> None:
    training = row["training"]
    total = training.get("total_timesteps")
    if total is None:
        raise ValueError(
            f"{where}: training.total_timesteps is required for kind 'train'"
        )
    decisions = native_decisions(run_config)
    row["decisions_per_episode"] = decisions
    if training.get("decisions_per_episode") not in (None, decisions):
        raise ValueError(
            f"{where}: decisions_per_episode {training['decisions_per_episode']} "
            f"disagrees with the native timing ({decisions}) of {run_config}"
        )
    if "total_episodes" in training and training["total_episodes"] * decisions != total:
        raise ValueError(
            f"{where}: total_episodes {training['total_episodes']} x {decisions} "
            f"decisions != total_timesteps {total}"
        )
    every = training.get("eval_every_steps", 0)
    timing = training["checkpoint_timing"]
    cadence = training.get("checkpoint_every_steps", 0)
    keep = training.get("keep_checkpoints", 3)
    n_steps = training.get("n_steps", 1024)
    start = row["continue_from"]["num_timesteps"] if row["continue_from"] else 0
    if timing == "standard":
        mission = (
            parse_ini(run_config).get("mission", {}).get("kind", "none").lower()
            != "none"
        )
        if (not mission or total % n_steps == 0) and (total - start) % n_steps:
            raise ValueError(
                f"{where}: standard training without an active exact-budget callback needs a remaining budget "
                f"divisible by n_steps ({total - start} % {n_steps} != 0); "
                "SB3 otherwise overshoots the requested budget"
            )
    if timing == "after_update":
        if every:
            raise ValueError(
                f"{where}: after_update checkpoints run without in-training "
                "validation; set eval_every_steps to 0"
            )
        problems = []
        if cadence <= 0:
            problems.append("checkpoint_every_steps must be positive")
        else:
            if cadence % n_steps:
                problems.append(
                    f"cadence {cadence} is not a multiple of the rollout {n_steps}"
                )
            if cadence % decisions:
                problems.append(
                    f"cadence {cadence} does not end complete {decisions}-decision episodes"
                )
            if total % cadence:
                problems.append(
                    f"total_timesteps {total} is not a multiple of the cadence {cadence}"
                )
            if start % n_steps:
                problems.append(f"parent steps {start} are not on a rollout boundary")
        if problems:
            raise ValueError(
                f"{where}: impossible after_update schedule ({'; '.join(problems)}); "
                "the budget is never extended automatically"
            )
    if every > 0 and not context["seeds"]["model_selection"]:
        raise ValueError(f"{where}: training validation needs seeds.model_selection")
    if (
        timing != "after_update"
        and context["execution"].get("recovery") == "checkpoint"
    ):
        raise ValueError(
            f"{where}: execution.recovery 'checkpoint' needs after_update checkpoints"
        )
    retained = retained_checkpoints(start, total, cadence, keep)
    row["retained_checkpoints"] = retained
    for op in context["operations"]:
        if op["id"] not in row["operations"]:
            continue
        for selector in op["at_steps"]:
            if selector == "best" and every <= 0:
                raise ValueError(
                    f"{where}: operation {op['id']} selects 'best' but training "
                    "validation (eval_every_steps > 0) is off"
                )
            if isinstance(selector, int) and selector not in retained:
                raise ValueError(
                    f"{where}: operation {op['id']} needs checkpoint {selector}, "
                    f"which is not retained until consumers finish "
                    f"(retained: {retained})"
                )
