"""Expand a validated version 2 matrix into an immutable experiment plan version 3.

The plan is a deterministic task graph with full SHA-256 task keys, fixed
destinations, resolved module/argument lists and hashed inputs. Nothing here
starts a process: the simulator binary is hashed, never launched.
"""

import json
import os
from pathlib import Path, PurePosixPath

from scripts.artifact_io import canonical_sha256, sha256_file, write_json
from scripts.rl.cli_common import MANIFEST_NAME, MODEL_BASENAME
from scripts.rl.experiments.config import (FROZEN_MODES, PLACEMENT_POLICIES, check_dependents,
                                           config_for, placement_identity, schedule_for)
from scripts.sim_support import find_mesh_root, parse_ini

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
KEY_DIMENSIONS = ("task_kind", "scenario", "row", "profile", "training_seed", "model_source",
                  "checkpoint", "operation", "operation_digest", "protocol", "schedule_digest",
                  "seed_role", "seed", "policy", "physical_digest", "check", "stage")
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


_PLAN_DIFFERS = ("{path} differs from the plan for this matrix, binary and --rows; "
                 "plans are immutable, use a new --output-root")


def task_key(identity: dict) -> str:
    """Full SHA-256 of the canonical identity (sorted keys, no whitespace)."""
    unknown = sorted(set(identity) - set(KEY_DIMENSIONS))
    if unknown:
        raise ValueError(f"unknown task identity dimensions {unknown}")
    return canonical_sha256({dim: identity.get(dim) for dim in KEY_DIMENSIONS})


def binary_identity(raw: str) -> dict:
    """An existing executable file, hashed and never launched."""
    path = Path(raw).expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f"simulator binary is not an executable file: {path}")
    return {"path": str(path), "reference": raw, "sha256": sha256_file(path)}


def check_binary_fresh(path: str) -> None:
    """Refuse a binary older than mesh-sim sources (existing preflight rule)."""
    mesh = find_mesh_root()
    built = Path(path).stat().st_mtime
    sources = [mesh / "sim.cc", *(mesh / "src").rglob("*.cc"), *(mesh / "src").rglob("*.h")]
    stale = [p for p in sources if p.is_file() and p.stat().st_mtime > built]
    if stale:
        raise ValueError(f"simulator binary {path} is older than {len(stale)} mesh-sim source "
                         f"file(s), e.g. {stale[0]}; the human rebuilds it from ns3-mmwave with "
                         "./ns3 build scratch/mesh-sim/sim")


def _asset(ini_path: Path, ini: dict, key: str, default: str = "") -> Path | None:
    raw = ini.get("scenario", {}).get(key, "") or default
    if not raw:
        return None
    path = Path(raw) if Path(raw).is_absolute() else ini_path.parent / raw
    if not path.is_file():
        raise ValueError(f"{ini_path}: scenario.{key} not found: {path}")
    return path.resolve()


class _Inputs:
    """Hash each input file once; the plan records path, hash and original reference."""

    def __init__(self):
        self.files: dict[str, dict] = {}

    def add(self, path, kind: str, reference: str | None = None) -> dict:
        path = str(Path(path).resolve())
        if path not in self.files:
            self.files[path] = {"kind": kind, "sha256": sha256_file(path), "reference": reference}
        return {"path": path, "sha256": self.files[path]["sha256"], "reference": reference}

    def ini(self, entry: dict) -> dict:
        """An INI plus the node/building/jammer assets its native loader resolves."""
        ini_path = Path(entry["path"])
        ini = parse_ini(ini_path)
        record = {**self.add(ini_path, "run_config", entry.get("reference")),
                  "fallback": entry.get("fallback", False), "lookup": entry.get("lookup"),
                  "config_source": entry.get("config_source")}
        for name, key, default in (("nodes", "nodes_file", "nodes.json"),
                                   ("buildings", "buildings_file", ""),
                                   ("jammers", "jammers_file", "")):
            asset = _asset(ini_path, ini, key, default)
            record[name] = None if asset is None else self.add(asset, name)
        return record


def _physical(ini: dict, reference: dict | None, band, gate) -> str:
    return canonical_sha256({"run_ini": ini["sha256"],
                             **{k: (ini[k] or {}).get("sha256") for k in ("nodes", "buildings", "jammers")},
                             "reference": reference["sha256"] if reference else None,
                             "band": band, "gate_s": gate})


def _join(root, *parts) -> str:
    return str(PurePosixPath(root, *map(str, parts))) if isinstance(root, PurePosixPath) \
        else str(Path(root, *map(str, parts)))


def _checkpoint_segment(selector) -> str:
    if selector in ("final", "best"):
        return str(selector)
    if isinstance(selector, int):
        return str(selector)
    return str(selector).rsplit("_", 2)[-2] if str(selector).startswith("checkpoints/") else str(selector)


def _checkpoint_model(selector) -> str:
    return selector if selector in ("final", "best") else f"checkpoints/checkpoint_{selector}_steps.zip"


def _weights(weights) -> list[str]:
    text = ",".join(str(w) for w in weights)
    # argparse would read a leading '-' as another option unless attached.
    return ["--reward-weights=" + text] if text.startswith("-") else ["--reward-weights", text]


def _selection_args(selection: dict) -> list[str]:
    return ["--observation-preset", selection["observation_preset"],
            "--reward-components", ",".join(selection["reward_components"]),
            *_weights(selection["reward_weights"]),
            "--observation-parameters", json.dumps(selection["observation_parameters"], sort_keys=True),
            "--reward-parameters", json.dumps(selection["reward_parameters"], sort_keys=True)]


_PPO_ORDER = ("total_timesteps", "n_steps", "gamma", "ent_coef", "learning_rate", "batch_size",
              "gae_lambda", "clip_range", "n_epochs", "target_kl", "net_arch", "ent_coef_final",
              "eval_every_steps", "checkpoint_every_steps", "keep_checkpoints")


def _train_args(binary: str, band, ini: dict, row: dict, seed: int, seeds: dict) -> list[str]:
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
        args += [f"--{key.replace('_', '-')}",
                 ",".join(map(str, value)) if key == "net_arch" else str(value)]
    args += ["--checkpoint-timing", training["checkpoint_timing"].replace("_", "-")]
    if "decisions_per_episode" in training:
        args += ["--decisions-per-episode", str(training["decisions_per_episode"])]
    args += ["--seed", str(seed)]
    selection = seeds["model_selection"] if training.get("eval_every_steps", 0) > 0 else []
    args += ["--eval-episodes", str(len(selection) or 1)]
    if selection:
        args += ["--eval-seed", str(selection[0]), "--eval-seeds", ",".join(map(str, selection))]
    if row["continue_from"] is not None:
        args += ["--continue-from-run-dir", row["continue_from"]["run_dir"],
                 "--continue-model", str(row["continue_from"]["model"])]
    if row["curriculum"] is not None:
        args += ["--curriculum-schedule", row["curriculum"]["path"]]
    return args


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
        parts = [part.replace("{KEY}", key).replace("{K}", suffix) for part in map(str, destination)]
        task = {"id": task_id, "key": key, "suffix": suffix, "kind": identity["task_kind"],
                "identity": {dim: identity.get(dim) for dim in KEY_DIMENSIONS},
                "needs": [], "needs_policy": "completed", "module": None, "handler": None,
                "args": None, "exit_codes": [0], "output_dir": _join(self.root, *parts),
                "attempts": "append", "expected_outputs": [], "inputs": [],
                "binding": None, "selection": None, "scenario": identity.get("scenario"),
                "row": identity.get("row"), "stage": identity.get("stage")}
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
                raise ValueError(f"task {field} collision between {seen[task[field]]} and {task['id']}")
            seen[task[field]] = task["id"]
    ordered = sorted(tasks, key=lambda t: t["output_dir"])
    for first, second in zip(ordered, ordered[1:]):
        if second["output_dir"].startswith(first["output_dir"].rstrip("/") + "/"):
            raise ValueError(f"task destination {second['output_dir']} ({second['id']}) is nested "
                             f"inside {first['output_dir']} ({first['id']})")


def _scenario_records(matrix: dict, inputs: _Inputs) -> dict:
    records = {}
    for slug, scenario in matrix["scenarios"].items():
        reference = scenario["reference"]
        baselines = scenario["baselines"]
        records[slug] = {
            "band": scenario["band"], "case": scenario["case"],
            "run_config": inputs.ini({**scenario["run_config"], "fallback": False, "lookup": None}),
            "configs": {role: {seed: inputs.ini({**entry, "fallback": False,
                                                 "lookup": {"role": role, "key": seed}})
                               for seed, entry in entries.items()}
                        for role, entries in scenario["configs"].items()},
            "reference": None if reference is None else {
                "kind": reference["kind"], "version": reference["version"],
                **inputs.add(reference["path"], "reference", reference["reference"])},
            "baselines": None if baselines is None else {
                **baselines, "import_from": None if baselines["import_from"] is None else
                inputs.add(baselines["import_from"]["path"], "import", baselines["import_from"]["reference"])},
            "history_sources": scenario["history_sources"]}
    return records


def _row_record(row: dict, inputs: _Inputs) -> dict:
    record = {key: row.get(key) for key in (
        "name", "scenario", "profile", "selection", "training", "training_seeds",
        "training_config_key", "decisions_per_episode", "retained_checkpoints", "operations",
        "labels")}
    for key in ("continue_from", "model_source"):
        source = row[key]
        if source is not None:
            inputs.add(source["model_path"], "model")
            inputs.add(Path(source["run_dir"]) / MANIFEST_NAME, "train_manifest")
            record[key] = {k: source[k] for k in (
                "run_dir", "reference", "model", "model_path", "model_sha256", "manifest_sha256",
                "num_timesteps", "n_updates", "seed", "digest")}
        else:
            record[key] = None
    record["configs"] = {role: {seed: {**inputs.add(entry["path"], "run_config", entry["reference"]),
                                       "config_source": "row"}
                                for seed, entry in entries.items()}
                         for role, entries in row["configs"].items()}
    record["curriculum"] = (None if row["curriculum"] is None else
                            inputs.add(row["curriculum"]["path"], "curriculum",
                                       row["curriculum"]["reference"]))
    return record


def _seed_config(matrix: dict, inputs: "_Inputs", scenario: str, role: str, seed,
                 row: dict | None = None) -> dict:
    """Hashed INI for one seed: row override > scenario configs > run_config (marked)."""
    return inputs.ini(config_for(matrix["scenarios"][scenario], role, seed, row))


def _gate(case: dict | None, key) -> float | None:
    return ((case or {}).get("seeds") or {}).get(str(key), {}).get("gate_s")


def build_batch_plan(matrix: dict, output_root=None, sim_binary: str | None = None) -> dict:
    """Deterministic plan v3; output_root/sim_binary None gives the validate-only expansion."""
    placeholder = output_root is None
    root = PurePosixPath("<output-root>") if placeholder else Path(output_root).resolve()
    inputs = _Inputs()
    inputs.add(matrix["path"], "matrix", matrix["reference"])
    binary = binary_identity(sim_binary) if sim_binary is not None else None
    binary_arg = binary["path"] if binary else "<sim-binary>"
    records = _scenario_records(matrix, inputs)
    rows = [_row_record(row, inputs) for row in matrix["rows"]]
    row_by_name = {row["name"]: row for row in matrix["rows"]}
    seeds = matrix["seeds"]
    operations = matrix["evaluation"]["operations"] if matrix["evaluation"] else []
    op_by_id = {op["id"]: op for op in operations}
    graph = _Graph(root)
    branch_of, op_branch_of = {}, {}
    for stage in matrix["stages"]:
        if stage["selection"]:
            for candidate, entries in stage["selection"]["branches"].items():
                for entry in entries:
                    target = (stage["name"], candidate)
                    if isinstance(entry, str):
                        if entry in row_by_name:
                            branch_of[entry] = target
                    elif entry["row"] in row_by_name:
                        op_branch_of[(entry["row"], entry["operation"])] = target

    check_task_ids, baseline_ids = {}, {}
    for check in (c for c in matrix["checks"] if c["kind"] == "preflight"):
        check_task_ids[check["id"]] = _add_check(graph, matrix, records, check, binary_arg, [], inputs)

    def scenario_preflights(slug):
        return [tid for c in matrix["checks"] if c["kind"] == "preflight" and c["scenario"] == slug
                for tid in check_task_ids[c["id"]]]

    _add_baselines(graph, matrix, records, inputs, binary_arg, scenario_preflights, baseline_ids)
    for check in (c for c in matrix["checks"] if c["kind"] != "preflight"):
        check_task_ids[check["id"]] = _add_check(graph, matrix, records, check, binary_arg,
                                                 scenario_preflights(check["scenario"]), inputs,
                                                 baseline_ids)
    # Declared check order is preserved in every dependent's needs.
    row_checks = {row["name"]: [] for row in matrix["rows"]}
    for check in matrix["checks"]:
        for name in check_dependents(check, matrix["rows"]):
            row_checks[name].extend(check_task_ids[check["id"]])

    train_ids, select_ids = {}, {}
    stage_order = [s["name"] for s in matrix["stages"]] or [None]
    stages = {s["name"]: s for s in matrix["stages"]}
    context = {"graph": graph, "matrix": matrix, "inputs": inputs, "op_by_id": op_by_id,
               "train_ids": train_ids, "row_checks": row_checks, "binary_arg": binary_arg,
               "branch_of": branch_of, "op_branch_of": op_branch_of, "select_ids": select_ids}
    for stage_name in stage_order:
        stage_rows = (stages[stage_name]["rows"] if stage_name else [r["name"] for r in matrix["rows"]])
        stage_needs = []
        if stage_name:
            for need in stages[stage_name]["needs"]:
                if need in select_ids:
                    stage_needs.append(select_ids[need])
                else:
                    stage_needs += [tid for r in stages[need]["rows"] for tid in train_ids.get(r, [])]
        for name in stage_rows:
            row = row_by_name[name]
            selection = None
            if name in branch_of:
                selection = {"task": select_ids[branch_of[name][0]], "branch": branch_of[name][1]}
            if row["training"] is not None:
                for seed in row["training_seeds"]:
                    key = row["training_config_key"] or seed
                    ini = _seed_config(matrix, inputs, row["scenario"], "training", key, row)
                    identity = {"task_kind": "train", "scenario": row["scenario"], "row": name,
                                "profile": row["profile"], "training_seed": seed,
                                "model_source": row["continue_from"]["digest"] if row["continue_from"] else None,
                                "stage": stage_name}
                    expected = [MANIFEST_NAME, f"{MODEL_BASENAME}.zip"]
                    if row["training"]["checkpoint_timing"] == "after_update":
                        expected.append(POST_UPDATE_CHECKPOINTS)
                    task_inputs = [ini["path"]] + ([row["curriculum"]["path"]] if row["curriculum"] else []) \
                        + ([row["continue_from"]["model_path"]] if row["continue_from"] else [])
                    task_id = f"train/{row['scenario']}/{name}/train-seed-{seed}"
                    graph.add(task_id, identity,
                              ["models", row["scenario"], name, "train", f"train-seed-{seed}"],
                              needs=row_checks[name] + stage_needs
                              + ([selection["task"]] if selection else []),
                              module=TRAIN_MODULE,
                              args=_train_args(binary_arg, matrix["scenarios"][row["scenario"]]["band"],
                                               ini, row, seed, seeds),
                              expected_outputs=expected, inputs=task_inputs, selection=selection,
                              config_lookup={"key": str(key), "seed": seed, "ini": ini["path"],
                                             "fallback": ini["fallback"]},
                              config={"path": ini["path"], "sha256": ini["sha256"],
                                      "config_source": ini["config_source"]})
                    train_ids.setdefault(name, []).append(task_id)
        own = stages[stage_name]["selection"] if stage_name else None
        own_branches = set()
        if own is not None:
            own_branches = {(e["row"], e["operation"]) for es in own["branches"].values()
                            for e in es if not isinstance(e, str)}
        rows_here = [row_by_name[n] for n in stage_rows]
        _add_operations(context, rows_here, stage_needs, lambda r, o: (r, o) not in own_branches)
        if own is not None:
            select_ids[stage_name] = _add_select(graph, stages[stage_name], matrix, train_ids)
            _add_operations(context, rows_here, stage_needs, lambda r, o: (r, o) in own_branches)

    _add_reports(graph, matrix, op_by_id)
    check_collisions(graph.tasks)
    return {
        "experiment_plan_version": EXPERIMENT_PLAN_VERSION,
        "matrix": {"path": matrix["path"], "reference": matrix["reference"],
                   "sha256": matrix["sha256"], "name": matrix["name"], "kind": matrix["kind"],
                   "directory": matrix["directory"]},
        "sim_binary": binary,
        "output_root": None if placeholder else str(root),
        "rows_filter": matrix["rows_filter"],
        "seeds": seeds,
        "scenarios": records,
        "rows": rows,
        "operations": operations,
        "comparison": matrix["evaluation"]["comparison"] if matrix["evaluation"] else None,
        "checks": matrix["checks"],
        "stages": matrix["stages"],
        "execution_declared": matrix["execution"],
        "key_dimensions": list(KEY_DIMENSIONS),
        "placeholders": [ATTEMPT_DIR, BINDING_RUN_DIR, BINDING_MODEL, BINDING_PATH, ACCEPTED_DIRS,
                         "{accepted_dir:<task-id>}"],
        "inputs": inputs.files,
        "tasks": graph.tasks,
    }


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


def _source_args(source: dict, slug: str, baseline_ids: dict) -> tuple[list[str], list[str], str | None]:
    if source["kind"] == "path":
        return ["--source", source["path"]], [], source["path"]
    task_id = baseline_ids[(slug, source["policy"], source["seed"])]
    return ["--source", accepted_dir(task_id)], [task_id], None


def _add_check(graph, matrix, records, check, binary_arg, needs, inputs, baseline_ids=None) -> list[str]:
    """One task per checked seed (one source episode is one seed); reward audits are single."""
    slug = check["scenario"]
    scenario = matrix["scenarios"][slug]
    band = scenario["band"]
    prefix = "preflight" if check["kind"] == "preflight" else "check"
    ids = []
    for seed in check.get("seeds") or [None]:
        identity = {"task_kind": check["kind"], "scenario": slug, "check": check["id"], "seed": seed}
        args = [check["kind"].replace("_", "-"), "--check-id", check["id"]]
        task_inputs, task_needs = [], list(needs)
        if seed is not None:
            role = next((r for r, values in matrix["seeds"].items() if seed in values), None)
            if role is None:
                raise ValueError(f"check {check['id']}: seed {seed} has no declared seed role")
            ini = _seed_config(matrix, inputs, slug, role, seed)
            task_inputs.append(ini["path"])
            identity["seed_role"] = role
            identity["physical_digest"] = canonical_sha256({str(seed): inputs.files[ini["path"]]["sha256"]})
            args += ["--sim-binary", binary_arg,
                     "--seed-configs-json", json.dumps({str(seed): ini["path"]}, sort_keys=True)]
            if band is not None:
                args += ["--band", band]
        if check["kind"] == "preflight":
            if check["requirements"]:
                args += ["--requirements", ",".join(check["requirements"])]
            reference = records[slug]["reference"]
            if reference is not None:
                args += ["--reference-kind", reference["kind"], "--reference", reference["path"]]
        if check["kind"] == "replay_gate":
            case = check["case"] or {}
            args += ["--comparison", check["comparison"], "--case-json", json.dumps(case, sort_keys=True)]
            parent = check["parent"]
            if parent is not None:
                for path, kind in ((parent["model_path"], "model"),
                                   (str(Path(parent["run_dir"]) / MANIFEST_NAME), "train_manifest")):
                    inputs.add(path, kind)
                    task_inputs.append(path)
                args += ["--parent-run-dir", parent["run_dir"], "--parent-model", parent["model"]]
                identity["model_source"] = parent["digest"]
            if check["contact_audit"]:
                args.append("--contact-audit")
            identity["operation_digest"] = canonical_sha256({
                "comparison": check["comparison"], "case": case, "contact_audit": check["contact_audit"]})
        source = (check["sources"][seed] if check["kind"] == "replay_gate"
                  else check.get("source"))
        if source is not None:
            source_args, source_needs, path = _source_args(source, slug, baseline_ids)
            args += source_args
            task_needs += source_needs
            if path is not None:
                identity["physical_digest"] = canonical_sha256(
                    {"source": path, "configs": identity.get("physical_digest")})
        if check["kind"] == "reward_audit":
            row = next(r for r in matrix["rows"] if r["name"] == check["row"])
            identity["row"] = row["name"]
            args += ["--method", check["method"], "--run-config", scenario["run_config"]["path"],
                     *_selection_args(row["selection"])]
        args += ["--output-dir", ATTEMPT_DIR]
        task_id = f"{prefix}/{slug}/{check['id']}" + (f"/seed-{seed}" if seed is not None else "")
        graph.add(task_id, identity, ["preflight", slug, f"{check['id']}-{{K}}"], needs=task_needs,
                  module=OPERATE_MODULE, args=args, expected_outputs=[CHECK_RESULT],
                  inputs=task_inputs)
        ids.append(task_id)
    return ids


def _add_baselines(graph, matrix, records, inputs, binary_arg, scenario_preflights, baseline_ids) -> None:
    """One baseline task per physical case, policy and seed; rows share identical INIs only."""
    seeds = matrix["seeds"]
    for slug, scenario in matrix["scenarios"].items():
        baselines = scenario["baselines"]
        if baselines is None:
            continue
        role = baselines["seed_role"]
        reference = records[slug]["reference"]
        imported = records[slug]["baselines"]["import_from"]
        scenario_rows = [row for row in matrix["rows"] if row["scenario"] == slug]
        sourced = any(c["kind"] == "replay_gate" and any(src["kind"] == "baseline"
                                                         for src in c["sources"].values())
                      or c["kind"] == "reward_audit" and c["source"]["kind"] == "baseline"
                      for c in matrix["checks"] if c["scenario"] == slug)
        for policy in baselines["policies"]:
            placement = policy in PLACEMENT_POLICIES
            for seed in seeds[role]:
                default = _seed_config(matrix, inputs, slug, role, seed)
                if baselines["configs_scope"] == "scenario":
                    owners = [None]  # one baseline per declared seed on the scenario's own INI
                else:
                    owners = ([None] if not scenario_rows or sourced else []) + scenario_rows
                variants = {}
                for owner in owners:
                    ini = default if owner is None else _seed_config(matrix, inputs, slug, role, seed, owner)
                    gate = _gate(scenario["case"], seed)
                    planning = (placement_identity(ini["path"], baselines["planning_seed"])
                                if placement else None)
                    physical = _physical(ini, reference if policy == "scripted" else None,
                                         scenario["band"], gate)
                    if baselines["decision_record_seeds"] is not None:
                        # Hashed only when declared, so existing baseline digests are unchanged.
                        physical = canonical_sha256({"physical": physical, "decision_records":
                                                     seed in baselines["decision_record_seeds"]})
                    if planning is not None:
                        physical = canonical_sha256({"physical": physical,
                                                     "planning_seed": planning["planning_seed"],
                                                     "planner_settings": planning["planner_settings_sha256"]})
                    variants.setdefault(physical, (ini, gate, planning))
                default_physical = None
                for physical, (ini, gate, planning) in variants.items():
                    if ini["path"] == default["path"] and default_physical is None:
                        default_physical = physical
                    identity = {"task_kind": "baseline", "scenario": slug, "policy": policy,
                                "seed_role": role, "seed": seed, "physical_digest": physical}
                    args = ["baseline", "--sim-binary", binary_arg, "--policy", policy,
                            "--seed", str(seed), "--seed-role", role, "--run-config", ini["path"]]
                    if scenario["band"] is not None:
                        args += ["--band", scenario["band"]]
                    args += ["--output-dir", ATTEMPT_DIR]
                    if policy == "scripted":
                        args += ["--reference-kind", reference["kind"], "--reference", reference["path"]]
                        args += _case_args(scenario["case"], None)
                    if planning is not None:
                        args += ["--planning-seed", str(planning["planning_seed"])]
                        if baselines["allow_seed_overlap"]:
                            args.append("--allow-seed-overlap")
                    if gate is not None:
                        args += ["--gate-s", repr(gate)]
                    if baselines["decision_records"] and (baselines["decision_record_seeds"] is None
                                                          or seed in baselines["decision_record_seeds"]):
                        args.append("--decision-records")
                    if imported is not None and not placement:
                        args += ["--import-from", imported["path"]]
                    task_id = f"baseline/{slug}/{policy}/{role}/seed-{seed}"
                    if physical != default_physical:
                        task_id += f"/config-{physical[:12]}"
                    task_inputs = [ini["path"]] + ([planning["mapping_file"]]
                                                   if planning and planning["mapping_file"] else [])
                    if planning and planning["mapping_file"]:
                        inputs.add(planning["mapping_file"], "mapping")
                    graph.add(task_id, identity,
                              ["baselines", slug, f"{policy}-{{K}}", role, f"seed-{seed}"],
                              needs=scenario_preflights(slug), module=OPERATE_MODULE, args=args,
                              expected_outputs=[EVAL_MANIFEST], inputs=task_inputs,
                              config={"path": ini["path"], "sha256": ini["sha256"],
                                      "config_source": ini["config_source"]},
                              planning=planning)
                    if physical == default_physical:
                        baseline_ids[(slug, policy, seed)] = task_id


def _add_operations(context: dict, rows: list[dict], stage_needs: list[str], include) -> None:
    graph, matrix, inputs = context["graph"], context["matrix"], context["inputs"]
    seeds = matrix["seeds"]
    select_ids = context["select_ids"]
    for row in rows:
        scenario = matrix["scenarios"][row["scenario"]]
        row_selection = ({"task": select_ids[context["branch_of"][row["name"]][0]],
                          "branch": context["branch_of"][row["name"]][1]}
                         if row["name"] in context["branch_of"] else None)
        if row["model_source"] is not None:
            source = row["model_source"]
            producers = [(None, f"model-{source['digest'][:12]}", source["model"])]
        else:
            producers = []
            for seed, train_id in zip(row["training_seeds"], context["train_ids"].get(row["name"], [])):
                producers.append((train_id, f"train-seed-{seed}", None))
        for op_id in row["operations"]:
            if not include(row["name"], op_id):
                continue
            op = context["op_by_id"][op_id]
            selection = row_selection
            if (row["name"], op_id) in context["op_branch_of"]:
                stage, branch = context["op_branch_of"][(row["name"], op_id)]
                selection = {"task": select_ids[stage], "branch": branch}
            schedule = schedule_for(op["schedule"], scenario["case"], f"operation {op_id}")
            schedule_digest = canonical_sha256(schedule) if schedule else None
            settings = op["online"] or {}
            for producer, seed_segment, fixed_model in producers:
                selectors = op["at_steps"] if fixed_model is None else [fixed_model]
                for selector in selectors:
                    segment = _checkpoint_segment(selector)
                    if producer is not None:
                        producer_task = graph.by_id[producer]
                        binding = {"producer": producer, "producer_key": producer_task["key"],
                                   "checkpoint": segment, "model": _checkpoint_model(selector),
                                   "path": f"state/bindings/{producer_task['key']}-{segment}.json"}
                        run_dir, model = BINDING_RUN_DIR, BINDING_MODEL
                        needs = [producer]
                        training_seed, model_source = int(seed_segment.rsplit("-", 1)[1]), None
                    else:
                        source = row["model_source"]
                        binding = {"producer": None, "source_digest": source["digest"],
                                   "run_dir": source["run_dir"], "model": source["model"],
                                   "model_sha256": source["model_sha256"]}
                        run_dir, model = source["run_dir"], str(source["model"])
                        needs, training_seed, model_source = [], None, source["digest"]
                    for seed in seeds[op["seed_role"]]:
                        ini = _seed_config(matrix, inputs, row["scenario"], op["seed_role"], seed, row)
                        gate = _gate(scenario["case"], seed)
                        identity = {"task_kind": "operate", "scenario": row["scenario"],
                                    "row": row["name"], "profile": row["profile"],
                                    "training_seed": training_seed, "model_source": model_source,
                                    "checkpoint": segment, "operation": op_id,
                                    "operation_digest": op["config_digest"], "protocol": op["mode"],
                                    "schedule_digest": schedule_digest, "seed_role": op["seed_role"],
                                    "seed": seed, "stage": graph_stage(matrix, row["name"])}
                        args = ["model", "--sim-binary", context["binary_arg"], "--run-dir", run_dir,
                                "--model", model, "--mode", op["mode"], "--operation-id", op_id,
                                "--seed", str(seed), "--seed-role", op["seed_role"],
                                "--run-config", ini["path"]]
                        if scenario["band"] is not None:
                            args += ["--band", scenario["band"]]
                        args += ["--output-dir", ATTEMPT_DIR,
                                 "--protocol-settings-json", json.dumps(settings, sort_keys=True)]
                        if schedule is not None:
                            args += ["--schedule-json", json.dumps(schedule, sort_keys=True)]
                        if gate is not None:
                            args += ["--gate-s", repr(gate)]
                        if producer is not None:
                            args += ["--binding", BINDING_PATH]
                        args += _case_args(scenario["case"], schedule)
                        if op["decision_records"] and (op["decision_record_seeds"] is None
                                                       or seed in op["decision_record_seeds"]):
                            args.append("--decision-records")
                        task_id = (f"operate/{row['scenario']}/{row['name']}/{seed_segment}/"
                                   f"checkpoint-{segment}/{op_id}/{op['seed_role']}/seed-{seed}")
                        graph.add(task_id, identity,
                                  ["operations", row["scenario"], row["name"], seed_segment,
                                   f"checkpoint-{segment}", f"{op_id}-{{K}}", op["seed_role"], f"seed-{seed}"],
                                  needs=needs + context["row_checks"][row["name"]] + stage_needs
                                  + ([selection["task"]] if selection else []),
                                  module=OPERATE_MODULE, args=args,
                                  exit_codes=[0, 2],
                                  expected_outputs=[EVAL_MANIFEST if op["mode"] in FROZEN_MODES
                                                    else ONLINE_MANIFEST],
                                  inputs=[ini["path"]], binding=binding, selection=selection,
                                  schedule=schedule,
                                  config={"path": ini["path"], "sha256": ini["sha256"],
                                          "config_source": ini["config_source"]})


def graph_stage(matrix: dict, row: str) -> str | None:
    return next((s["name"] for s in matrix["stages"] if row in s["rows"]), None)


def _add_select(graph, stage, matrix, train_ids) -> str:
    """Source exactly the declared operation(s) at `source_checkpoint`, or training validation."""
    selection = stage["selection"]
    needs, sources = [], {}
    checkpoint = (None if selection["source_checkpoint"] is None
                  else _checkpoint_segment(selection["source_checkpoint"]))
    for candidate, entries in selection["candidates"].items():
        if selection["rule"] == "replay":
            continue
        for entry in entries:
            row = entry if isinstance(entry, str) else entry["row"]
            op_id = selection["source_operation"] if isinstance(entry, str) else entry["operation"]
            if selection["rule"] == "legacy-validation-profile-v1":
                ids = train_ids.get(row, [])
            else:
                ids = [t["id"] for t in graph.tasks if t["kind"] == "operate" and t["row"] == row
                       and t["identity"]["operation"] == op_id
                       and t["identity"]["checkpoint"] == checkpoint]
            if not ids:
                raise ValueError(f"stage {stage['name']}: candidate {candidate} ({row}) has no "
                                 "source tasks")
            sources.setdefault(candidate, []).extend(ids)
            needs += ids
    identity = {"task_kind": "select", "stage": stage["name"],
                "operation": selection["source_operation"], "seed_role": selection["seed_role"],
                "checkpoint": checkpoint,
                "operation_digest": canonical_sha256({k: selection[k] for k in
                                                      ("rule", "form", "candidates", "branches",
                                                       "settings")})}
    source_kind = ("none" if selection["rule"] == "replay" else "training_validation"
                   if selection["rule"] == "legacy-validation-profile-v1" else "operation")
    task_id = f"select/{stage['name']}"
    graph.add(task_id, identity, ["analysis", "_batch", "selections", "{KEY}"], needs=needs,
              handler="select", expected_outputs=[SELECTION_RECEIPT],
              selection_rule={**selection, "source_kind": source_kind, "sources": sources})
    return task_id


def _add_reports(graph, matrix, op_by_id) -> None:
    comparison = matrix["evaluation"]["comparison"] if matrix["evaluation"] else None
    for slug in matrix["scenarios"]:
        scenario_tasks = [t for t in graph.tasks if t["scenario"] == slug]
        trains = [t["id"] for t in scenario_tasks if t["kind"] == "train"]
        results = [t["id"] for t in scenario_tasks if t["kind"] in ("operate", "baseline")]
        index_needs = []
        if trains:
            index_needs.append(_report(graph, "curves", slug, trains, CURVE_SOURCES, "curves"))
        if comparison is not None:
            groups = {}
            for task in scenario_tasks:
                if task["kind"] == "operate" and task["identity"]["operation"] == comparison["operation"]:
                    groups.setdefault(task["identity"]["checkpoint"], []).append(task["id"])
            for checkpoint, ids in sorted(groups.items()):
                baselines = [t["id"] for t in scenario_tasks if t["kind"] == "baseline"]
                identity = {"task_kind": "compare", "scenario": slug, "checkpoint": checkpoint,
                            "operation": comparison["operation"],
                            "operation_digest": op_by_id[comparison["operation"]]["config_digest"]}
                task = graph.add(f"compare/{slug}/{comparison['operation']}/checkpoint-{checkpoint}",
                                 identity, ["analysis", slug, "comparisons", "{KEY}"],
                                 needs=ids + baselines, module=COMPARE_MODULE,
                                 args=["--eval-dirs", ACCEPTED_DIRS, "--output-dir", ATTEMPT_DIR],
                                 exit_codes=[0, 2], expected_outputs=[COMPARISON_NAME],
                                 needs_policy="terminal" if comparison["allow_incomplete"] else "completed",
                                 view={"operation": comparison["operation"], "sources": ids,
                                       "baselines": baselines,
                                       "allow_incomplete": comparison["allow_incomplete"]})
                index_needs.append(task["id"])
        if results:
            index_needs.append(_report(graph, "review", slug, results, REVIEW_NAME, "reviews"))
        if index_needs:
            graph.add(f"index/{slug}", {"task_kind": "index", "scenario": slug},
                      ["main", slug], needs=index_needs, needs_policy="terminal", handler="index",
                      attempts="projection", expected_outputs=[INDEX_NAME])


def _report(graph, kind, slug, needs, output, folder) -> str:
    task = graph.add(f"{kind}/{slug}", {"task_kind": kind, "scenario": slug},
                     ["analysis", slug, folder, "{KEY}"], needs=needs, needs_policy="terminal",
                     handler=kind, expected_outputs=[output])
    return task["id"]


def describe_expansion(plan: dict) -> list[str]:
    """Human-readable expansion printed by `validate`."""
    counts = {}
    for task in plan["tasks"]:
        counts[task["kind"]] = counts.get(task["kind"], 0) + 1
    lines = [f"matrix {plan['matrix']['name']} (kind {plan['matrix']['kind']}): "
             f"{len(plan['tasks'])} tasks",
             "  " + ", ".join(f"{kind} {count}" for kind, count in counts.items())]
    lines += [f"  {task['id']}  [{task['suffix']}]" for task in plan["tasks"]]
    return lines


def write_batch_plan(plan: dict, output_root) -> Path:
    """Write the plan once; an existing different plan is refused, never replaced."""
    root = Path(output_root).resolve()
    path = root / PLAN_NAME
    if path.is_file():
        try:
            existing = json.loads(path.read_text())
        except ValueError as exc:
            raise ValueError(f"{path} is unreadable; use a new --output-root") from exc
        if existing != json.loads(json.dumps(plan)):
            raise ValueError(_PLAN_DIFFERS.format(path=path))
        return path
    root.mkdir(parents=True, exist_ok=True)
    write_json(path, plan)
    return path


def read_plan_version(output_root):
    """experiment_plan_version of the plan in a root, or None when there is no plan."""
    path = Path(output_root).resolve() / PLAN_NAME
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    return data.get("experiment_plan_version") if isinstance(data, dict) else None


def load_batch_plan(output_root) -> dict:
    path = Path(output_root).resolve() / PLAN_NAME
    if not path.is_file():
        raise ValueError(f"no {PLAN_NAME} in {path.parent}; run plan first")
    plan = json.loads(path.read_text())
    if plan.get("experiment_plan_version") != EXPERIMENT_PLAN_VERSION:
        raise ValueError(f"{path} is not experiment plan version {EXPERIMENT_PLAN_VERSION}")
    return plan

