"""Construct training, check, baseline and policy operation tasks."""

import json
from pathlib import Path

from scripts.artifact_io import canonical_sha256
from scripts.rl.cli_common import MANIFEST_NAME
from scripts.rl.experiments.config import (
    FROZEN_MODES,
    PLACEMENT_POLICIES,
    baseline_config_owners,
    placement_identity,
    schedule_for,
)
from scripts.rl.experiments.plan_inputs import (
    _seed_config,
)
from scripts.rl.experiments.scenario_timing import case_gate_s
from scripts.rl.experiments.task_graph import (
    ATTEMPT_DIR,
    BINDING_MODEL,
    BINDING_PATH,
    BINDING_RUN_DIR,
    CHECK_RESULT,
    EVAL_MANIFEST,
    ONLINE_MANIFEST,
    OPERATE_MODULE,
    accepted_dir,
)


def _physical(ini: dict, reference: dict | None, band, gate) -> str:
    return canonical_sha256(
        {
            "run_ini": ini["sha256"],
            **{
                k: (ini[k] or {}).get("sha256")
                for k in ("nodes", "buildings", "jammers")
            },
            "reference": reference["sha256"] if reference else None,
            "band": band,
            "gate_s": gate,
        }
    )


def _checkpoint_segment(selector) -> str:
    if selector in ("final", "best"):
        return str(selector)
    if isinstance(selector, int):
        return str(selector)
    return (
        str(selector).rsplit("_", 2)[-2]
        if str(selector).startswith("checkpoints/")
        else str(selector)
    )


def _checkpoint_model(selector) -> str:
    return (
        selector
        if selector in ("final", "best")
        else f"checkpoints/checkpoint_{selector}_steps.zip"
    )


def _weights(weights) -> list[str]:
    text = ",".join(str(w) for w in weights)
    # argparse would read a leading '-' as another option unless attached.
    return (
        ["--reward-weights=" + text]
        if text.startswith("-")
        else ["--reward-weights", text]
    )


def _selection_args(selection: dict) -> list[str]:
    return [
        "--observation-preset",
        selection["observation_preset"],
        "--reward-components",
        ",".join(selection["reward_components"]),
        *_weights(selection["reward_weights"]),
        "--observation-parameters",
        json.dumps(selection["observation_parameters"], sort_keys=True),
        "--reward-parameters",
        json.dumps(selection["reward_parameters"], sort_keys=True),
    ]


_PPO_ORDER = (
    "total_timesteps",
    "n_steps",
    "gamma",
    "ent_coef",
    "learning_rate",
    "batch_size",
    "gae_lambda",
    "clip_range",
    "n_epochs",
    "target_kl",
    "net_arch",
    "ent_coef_final",
    "eval_every_steps",
    "checkpoint_every_steps",
    "keep_checkpoints",
)


def _train_args(
    binary: str, band, ini: dict, row: dict, seed: int, seeds: dict
) -> list[str]:
    training = row["training"]
    args = ["--sim-binary", binary, "--run-config", ini["path"]]
    if band is not None:
        args += ["--band", band]
    args += ["--output-dir", ATTEMPT_DIR, "--verbose", "0"]
    if row["continue_from"] is None:
        args += _selection_args(row["selection"])
    args.append("m-ppo")
    for key in _PPO_ORDER:
        value = training.get(key)
        if value is None:
            continue
        args += [
            f"--{key.replace('_', '-')}",
            ",".join(map(str, value)) if key == "net_arch" else str(value),
        ]
    args += ["--checkpoint-timing", training["checkpoint_timing"].replace("_", "-")]
    if "decisions_per_episode" in training:
        args += ["--decisions-per-episode", str(training["decisions_per_episode"])]
    args += ["--seed", str(seed)]
    selection = (
        seeds["model_selection"] if training.get("eval_every_steps", 0) > 0 else []
    )
    args += ["--eval-episodes", str(len(selection) or 1)]
    if selection:
        args += [
            "--eval-seed",
            str(selection[0]),
            "--eval-seeds",
            ",".join(map(str, selection)),
        ]
    if row["continue_from"] is not None:
        args += [
            "--continue-from-run-dir",
            row["continue_from"]["run_dir"],
            "--continue-model",
            str(row["continue_from"]["model"]),
        ]
    if row["curriculum"] is not None:
        args += ["--curriculum-schedule", row["curriculum"]["path"]]
    return args


def _case_args(case: dict | None, schedule: dict | None) -> list[str]:
    """Mission facts the operation needs; never inferred from the INI."""
    args = []
    if case and case.get("mission"):
        args += ["--mission", case["mission"]]
    target = ((schedule or {}).get("settings") or {}).get("coverage_target")
    if target is None and case:
        target = case.get("coverage_target")
    if target is not None:
        args += ["--coverage-target", repr(float(target))]
    return args


def _source_args(
    source: dict, slug: str, baseline_ids: dict
) -> tuple[list[str], list[str], str | None]:
    if source["kind"] == "path":
        return ["--source", source["path"]], [], source["path"]
    task_id = baseline_ids[(slug, source["policy"], source["seed"])]
    return ["--source", accepted_dir(task_id)], [task_id], None


def _add_check(
    graph, matrix, records, check, binary_arg, needs, inputs, baseline_ids=None
) -> list[str]:
    """One task per checked seed (one source episode is one seed); reward audits are single."""
    slug = check["scenario"]
    scenario = matrix["scenarios"][slug]
    band = scenario["band"]
    prefix = "preflight" if check["kind"] == "preflight" else "check"
    ids = []
    for seed in check.get("seeds") or [None]:
        identity = {
            "task_kind": check["kind"],
            "scenario": slug,
            "check": check["id"],
            "seed": seed,
        }
        args = [check["kind"].replace("_", "-"), "--check-id", check["id"]]
        task_inputs, task_needs = [], list(needs)
        if seed is not None:
            role = next(
                (r for r, values in matrix["seeds"].items() if seed in values), None
            )
            if role is None:
                raise ValueError(
                    f"check {check['id']}: seed {seed} has no declared seed role"
                )
            ini = _seed_config(matrix, inputs, slug, role, seed)
            task_inputs.append(ini["path"])
            identity["seed_role"] = role
            identity["physical_digest"] = canonical_sha256(
                {str(seed): inputs.files[ini["path"]]["sha256"]}
            )
            args += [
                "--sim-binary",
                binary_arg,
                "--seed-configs-json",
                json.dumps({str(seed): ini["path"]}, sort_keys=True),
            ]
            if band is not None:
                args += ["--band", band]
        if check["kind"] == "preflight":
            if check["requirements"]:
                args += ["--requirements", ",".join(check["requirements"])]
            reference = records[slug]["reference"]
            if reference is not None:
                args += [
                    "--reference-kind",
                    reference["kind"],
                    "--reference",
                    reference["path"],
                ]
        if check["kind"] == "replay_gate":
            case = check["case"] or {}
            args += [
                "--comparison",
                check["comparison"],
                "--case-json",
                json.dumps(case, sort_keys=True),
            ]
            parent = check["parent"]
            if parent is not None:
                for path, kind in (
                    (parent["model_path"], "model"),
                    (str(Path(parent["run_dir"]) / MANIFEST_NAME), "train_manifest"),
                ):
                    inputs.add(path, kind)
                    task_inputs.append(path)
                args += [
                    "--parent-run-dir",
                    parent["run_dir"],
                    "--parent-model",
                    parent["model"],
                ]
                identity["model_source"] = parent["digest"]
            if check["contact_audit"]:
                args.append("--contact-audit")
            identity["operation_digest"] = canonical_sha256(
                {
                    "comparison": check["comparison"],
                    "case": case,
                    "contact_audit": check["contact_audit"],
                }
            )
        source = (
            check["sources"][seed]
            if check["kind"] == "replay_gate"
            else check.get("source")
        )
        if source is not None:
            source_args, source_needs, path = _source_args(source, slug, baseline_ids)
            args += source_args
            task_needs += source_needs
            if path is not None:
                identity["physical_digest"] = canonical_sha256(
                    {"source": path, "configs": identity.get("physical_digest")}
                )
        if check["kind"] == "reward_audit":
            row = next(r for r in matrix["rows"] if r["name"] == check["row"])
            identity["row"] = row["name"]
            args += [
                "--method",
                check["method"],
                "--run-config",
                scenario["run_config"]["path"],
                *_selection_args(row["selection"]),
            ]
        args += ["--output-dir", ATTEMPT_DIR]
        task_id = f"{prefix}/{slug}/{check['id']}" + (
            f"/seed-{seed}" if seed is not None else ""
        )
        graph.add(
            task_id,
            identity,
            ["preflight", slug, f"{check['id']}-{{K}}"],
            needs=task_needs,
            module=OPERATE_MODULE,
            args=args,
            expected_outputs=[CHECK_RESULT],
            inputs=task_inputs,
        )
        ids.append(task_id)
    return ids


def _add_baselines(
    graph, matrix, records, inputs, binary_arg, scenario_preflights, baseline_ids
) -> None:
    """One baseline task per physical case, policy and seed; rows share identical INIs only."""
    seeds = matrix["seeds"]
    for slug, scenario in matrix["scenarios"].items():
        baselines = scenario["baselines"]
        if baselines is None:
            continue
        role = baselines["seed_role"]
        reference = records[slug]["reference"]
        imported = records[slug]["baselines"]["import_from"]
        owners = baseline_config_owners(matrix, slug)
        for policy in baselines["policies"]:
            placement = policy in PLACEMENT_POLICIES
            for seed in seeds[role]:
                default = _seed_config(matrix, inputs, slug, role, seed)
                variants = {}
                for owner in owners:
                    ini = (
                        default
                        if owner is None
                        else _seed_config(matrix, inputs, slug, role, seed, owner)
                    )
                    gate = case_gate_s(scenario["case"], seed)
                    planning = (
                        placement_identity(ini["path"], baselines["planning_seed"])
                        if placement
                        else None
                    )
                    physical = _physical(
                        ini,
                        reference if policy == "scripted" else None,
                        scenario["band"],
                        gate,
                    )
                    if baselines["decision_record_seeds"] is not None:
                        # Hashed only when declared, so existing baseline digests are unchanged.
                        physical = canonical_sha256(
                            {
                                "physical": physical,
                                "decision_records": seed
                                in baselines["decision_record_seeds"],
                            }
                        )
                    if planning is not None:
                        physical = canonical_sha256(
                            {
                                "physical": physical,
                                "planning_seed": planning["planning_seed"],
                                "planner_settings": planning["planner_settings_sha256"],
                            }
                        )
                    variants.setdefault(physical, (ini, gate, planning))
                default_physical = None
                for physical, (ini, gate, planning) in variants.items():
                    if ini["path"] == default["path"] and default_physical is None:
                        default_physical = physical
                    identity = {
                        "task_kind": "baseline",
                        "scenario": slug,
                        "policy": policy,
                        "seed_role": role,
                        "seed": seed,
                        "physical_digest": physical,
                    }
                    args = [
                        "baseline",
                        "--sim-binary",
                        binary_arg,
                        "--policy",
                        policy,
                        "--seed",
                        str(seed),
                        "--seed-role",
                        role,
                        "--run-config",
                        ini["path"],
                    ]
                    if scenario["band"] is not None:
                        args += ["--band", scenario["band"]]
                    args += ["--output-dir", ATTEMPT_DIR]
                    if policy == "scripted":
                        args += [
                            "--reference-kind",
                            reference["kind"],
                            "--reference",
                            reference["path"],
                        ]
                        args += _case_args(scenario["case"], None)
                    if planning is not None:
                        args += ["--planning-seed", str(planning["planning_seed"])]
                        if baselines["allow_seed_overlap"]:
                            args.append("--allow-seed-overlap")
                    if gate is not None:
                        args += ["--gate-s", repr(gate)]
                    if baselines["decision_records"] and (
                        baselines["decision_record_seeds"] is None
                        or seed in baselines["decision_record_seeds"]
                    ):
                        args.append("--decision-records")
                    if imported is not None and not placement:
                        args += ["--import-from", imported["path"]]
                    task_id = f"baseline/{slug}/{policy}/{role}/seed-{seed}"
                    if physical != default_physical:
                        task_id += f"/config-{physical[:12]}"
                    task_inputs = [ini["path"]] + (
                        [planning["mapping_file"]]
                        if planning and planning["mapping_file"]
                        else []
                    )
                    if planning and planning["mapping_file"]:
                        inputs.add(planning["mapping_file"], "mapping")
                    graph.add(
                        task_id,
                        identity,
                        ["baselines", slug, f"{policy}-{{K}}", role, f"seed-{seed}"],
                        needs=scenario_preflights(slug),
                        module=OPERATE_MODULE,
                        args=args,
                        expected_outputs=[EVAL_MANIFEST],
                        inputs=task_inputs,
                        config={
                            "path": ini["path"],
                            "sha256": ini["sha256"],
                            "config_source": ini["config_source"],
                        },
                        planning=planning,
                    )
                    if physical == default_physical:
                        baseline_ids[(slug, policy, seed)] = task_id


def _add_operations(
    context: dict, rows: list[dict], stage_needs: list[str], include
) -> None:
    graph, matrix, inputs = context["graph"], context["matrix"], context["inputs"]
    seeds = matrix["seeds"]
    select_ids = context["select_ids"]
    for row in rows:
        scenario = matrix["scenarios"][row["scenario"]]
        row_selection = (
            {
                "task": select_ids[context["branch_of"][row["name"]][0]],
                "branch": context["branch_of"][row["name"]][1],
            }
            if row["name"] in context["branch_of"]
            else None
        )
        if row["model_source"] is not None:
            source = row["model_source"]
            producers = [(None, f"model-{source['digest'][:12]}", source["model"])]
        else:
            producers = []
            for seed, train_id in zip(
                row["training_seeds"], context["train_ids"].get(row["name"], [])
            ):
                producers.append((train_id, f"train-seed-{seed}", None))
        for op_id in row["operations"]:
            if not include(row["name"], op_id):
                continue
            op = context["op_by_id"][op_id]
            selection = row_selection
            if (row["name"], op_id) in context["op_branch_of"]:
                stage, branch = context["op_branch_of"][(row["name"], op_id)]
                selection = {"task": select_ids[stage], "branch": branch}
            schedule = schedule_for(
                op["schedule"], scenario["case"], f"operation {op_id}"
            )
            schedule_digest = canonical_sha256(schedule) if schedule else None
            settings = op["online"] or {}
            for producer, seed_segment, fixed_model in producers:
                selectors = op["at_steps"] if fixed_model is None else [fixed_model]
                for selector in selectors:
                    segment = _checkpoint_segment(selector)
                    if producer is not None:
                        producer_task = graph.by_id[producer]
                        binding = {
                            "producer": producer,
                            "producer_key": producer_task["key"],
                            "checkpoint": segment,
                            "model": _checkpoint_model(selector),
                            "path": f"state/bindings/{producer_task['key']}-{segment}.json",
                        }
                        run_dir, model = BINDING_RUN_DIR, BINDING_MODEL
                        needs = [producer]
                        training_seed, model_source = (
                            int(seed_segment.rsplit("-", 1)[1]),
                            None,
                        )
                    else:
                        source = row["model_source"]
                        binding = {
                            "producer": None,
                            "source_digest": source["digest"],
                            "run_dir": source["run_dir"],
                            "model": source["model"],
                            "model_sha256": source["model_sha256"],
                        }
                        run_dir, model = source["run_dir"], str(source["model"])
                        needs, training_seed, model_source = [], None, source["digest"]
                    for seed in seeds[op["seed_role"]]:
                        ini = _seed_config(
                            matrix, inputs, row["scenario"], op["seed_role"], seed, row
                        )
                        gate = case_gate_s(scenario["case"], seed)
                        identity = {
                            "task_kind": "operate",
                            "scenario": row["scenario"],
                            "row": row["name"],
                            "profile": row["profile"],
                            "training_seed": training_seed,
                            "model_source": model_source,
                            "checkpoint": segment,
                            "operation": op_id,
                            "operation_digest": op["config_digest"],
                            "protocol": op["mode"],
                            "schedule_digest": schedule_digest,
                            "seed_role": op["seed_role"],
                            "seed": seed,
                            "stage": graph_stage(matrix, row["name"]),
                        }
                        args = [
                            "model",
                            "--sim-binary",
                            context["binary_arg"],
                            "--run-dir",
                            run_dir,
                            "--model",
                            model,
                            "--mode",
                            op["mode"],
                            "--operation-id",
                            op_id,
                            "--seed",
                            str(seed),
                            "--seed-role",
                            op["seed_role"],
                            "--run-config",
                            ini["path"],
                        ]
                        if scenario["band"] is not None:
                            args += ["--band", scenario["band"]]
                        args += [
                            "--output-dir",
                            ATTEMPT_DIR,
                            "--protocol-settings-json",
                            json.dumps(settings, sort_keys=True),
                        ]
                        if schedule is not None:
                            args += [
                                "--schedule-json",
                                json.dumps(schedule, sort_keys=True),
                            ]
                        if gate is not None:
                            args += ["--gate-s", repr(gate)]
                        if producer is not None:
                            args += ["--binding", BINDING_PATH]
                        args += _case_args(scenario["case"], schedule)
                        if op["decision_records"] and (
                            op["decision_record_seeds"] is None
                            or seed in op["decision_record_seeds"]
                        ):
                            args.append("--decision-records")
                        task_id = (
                            f"operate/{row['scenario']}/{row['name']}/{seed_segment}/"
                            f"checkpoint-{segment}/{op_id}/{op['seed_role']}/seed-{seed}"
                        )
                        graph.add(
                            task_id,
                            identity,
                            [
                                "operations",
                                row["scenario"],
                                row["name"],
                                seed_segment,
                                f"checkpoint-{segment}",
                                f"{op_id}-{{K}}",
                                op["seed_role"],
                                f"seed-{seed}",
                            ],
                            needs=needs
                            + context["row_checks"][row["name"]]
                            + stage_needs
                            + ([selection["task"]] if selection else []),
                            module=OPERATE_MODULE,
                            args=args,
                            exit_codes=[0, 2],
                            expected_outputs=[
                                EVAL_MANIFEST
                                if op["mode"] in FROZEN_MODES
                                else ONLINE_MANIFEST
                            ],
                            inputs=[ini["path"]],
                            binding=binding,
                            selection=selection,
                            schedule=schedule,
                            config={
                                "path": ini["path"],
                                "sha256": ini["sha256"],
                                "config_source": ini["config_source"],
                            },
                        )


def graph_stage(matrix: dict, row: str) -> str | None:
    return next((s["name"] for s in matrix["stages"] if row in s["rows"]), None)
