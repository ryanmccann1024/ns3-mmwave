"""Batch contract inventory checks with explicit, hand-counted public fixtures."""

import copy

import json

import tempfile

import zipfile

from pathlib import Path

import pytest

from scripts.artifact_io import sha256_file

from scripts.rl.agents.config import PPO_FIELDS

from scripts.rl.experiments.config import load_matrix_v2, native_decisions

from scripts.rl.experiments.plan import build_batch_plan

from scripts.sim_support import find_mesh_root

MESH = find_mesh_root()

CUSTOM = MESH / "inputs/custom"

OUTPUTS = MESH / "outputs/custom"

SELECTION_KEYS = ("observation_preset", "observation_parameters", "reward_components",
                  "reward_weights", "reward_parameters")

GATED = {"n_steps": 120, "batch_size": 60}

def _ini(peers: int, seed: int) -> str:
    nodes = ", ".join(f"peer-{i}" for i in range(1, peers + 1))
    return f"""[scenario]
name = conversion-fixture-{peers}
seed = {seed}
duration_s = 5.0
tick_s = 0.5
nodes_file = ../nodes.json

[rl]
enabled = true
controlled_nodes = {nodes}
max_controlled_nodes = {peers}
action_profile = move_2d
decision_interval_s = 0.5
reward_type = all_links_los
step_size_m = 1.0
x_min = 0.0
x_max = 200.0
y_min = 0.0
y_max = 200.0
z_min = 0.0
z_max = 50.0
"""

def _scene(root: Path, name: str, peers: int, seeds=(101, 201, 202)) -> dict:
    """One physical case: a shared nodes file and one INI per seed (10 decisions)."""
    folder = root / name
    folder.mkdir(parents=True)
    nodes = [{"id": f"peer-{i}", "role": "peer", "mobility": "constant_velocity",
              "node_type": "drone", "position": {"x": 10.0 * i, "y": 20.0, "z": 10.0},
              "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0}} for i in range(1, peers + 1)]
    (folder / "nodes.json").write_text(json.dumps(nodes))
    paths = {}
    for seed in seeds:
        path = folder / f"seed-{seed}" / "run.ini"
        path.parent.mkdir()
        path.write_text(_ini(peers, seed))
        paths[str(seed)] = str(path)
    return paths

def _scenario(paths: dict, peers: int, mission: str = "coverage", target=None) -> dict:
    case = {"mission": mission, "environment": "rural", "peers": peers}
    if target is not None:
        case["coverage_target"] = target
    return {"run_config": paths["101"], "band": "sub-6",
            "configs": {"training": {"101": paths["101"]},
                        "diagnostic": {"201": paths["201"], "202": paths["202"]}},
            "case": case}

TRAINING = {"total_timesteps": 40, "n_steps": 10, "batch_size": 5, "n_epochs": 1,
            "eval_every_steps": 0, "checkpoint_every_steps": 20, "keep_checkpoints": 2,
            "checkpoint_timing": "after_update", "decisions_per_episode": 10}

SELECTION = {"observation_preset": "raw_links_v1", "action_profile": "move_2d",
             "reward_components": ["delivery_ratio"], "reward_weights": [1.0]}

def _row(name: str, scenario: str, **extra) -> dict:
    return {"name": name, "scenario": scenario, "profile": "reference-ppo", **SELECTION, **extra}

def _train(scenarios: dict, rows: list, operations: list, **extra) -> dict:
    data = {"matrix_version": 2, "name": "conversion-fixture", "description": "fixture",
            "kind": "train", "scenarios": scenarios,
            "seeds": {"training": [101], "diagnostic": [201, 202]},
            "training": dict(TRAINING), "evaluation": {"operations": operations}, "rows": rows}
    data.update(extra)
    return data

def _plan(directory: Path, data: dict, name: str = "batch.json"):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(data))
    matrix = load_matrix_v2(path)
    return matrix, build_batch_plan(matrix)

def _kinds(plan: dict) -> dict:
    counts = {}
    for task in plan["tasks"]:
        counts[task["kind"]] = counts.get(task["kind"], 0) + 1
    return counts

def _tasks(plan: dict, kind: str) -> list:
    return [task for task in plan["tasks"] if task["kind"] == kind]

def _arg(task: dict, flag: str):
    args = task["args"]
    return args[args.index(flag) + 1] if flag in args else None

def _parent(directory: Path, steps: int, run_ini: str, seed: int = 101) -> Path:
    """A completed parent run: manifest plus a model ZIP that carries SB3 counters."""
    directory.mkdir(parents=True)
    model = directory / "maskable_ppo_mesh.zip"
    with zipfile.ZipFile(model, "w") as archive:
        archive.writestr("data", json.dumps({"num_timesteps": steps, "_n_updates": steps // 10}))
    manifest = {"status": "completed", "seed": seed, "num_timesteps": steps,
                "model_path": str(model), "model_sha256": sha256_file(model),
                "hyperparameters": {"n_steps": 10, "batch_size": 5, "n_epochs": 1},
                "scenario_identity": {"run_ini_sha256": sha256_file(run_ini)},
                "selection": {"observation_preset": "raw_links_v1",
                              "reward_components": ["delivery_ratio"], "reward_weights": [1.0]},
                "checkpoints": []}
    (directory / "train_manifest.json").write_text(json.dumps(manifest))
    return directory

FINAL_D = {"id": "final-d", "mode": "frozen_deterministic", "seed_role": "diagnostic",
           "at_steps": ["final"]}

FINAL_S = {"id": "final-s", "mode": "frozen_sampled", "seed_role": "diagnostic",
           "at_steps": ["final"]}

def test_three_six_nine_peer_rows_expand_as_hand_counted(tmp_path):
    scenarios, rows = {}, []
    for peers in (3, 6, 9):
        name = f"rural-coverage-{peers}-peers"
        scenarios[name] = _scenario(_scene(tmp_path / "in", name, peers), peers)
        rows.append(_row(f"p-{peers}", name))
    matrix, plan = _plan(tmp_path / "m", _train(scenarios, rows, [FINAL_D, FINAL_S]))
    # 3 rows x (1 train + 2 operations x 1 checkpoint x 2 diagnostic seeds) + curves/review/index.
    assert _kinds(plan) == {"train": 3, "operate": 12, "curves": 3, "review": 3, "index": 3}
    for row, peers in zip(plan["rows"], (3, 6, 9)):
        assert row["decisions_per_episode"] == 10 == native_decisions(scenarios[row["scenario"]]["run_config"])
        assert row["retained_checkpoints"] == [20, 40]
        assert plan["scenarios"][row["scenario"]]["case"]["peers"] == peers
    operations = sorted((t["row"], t["identity"]["operation"], t["identity"]["seed"]) for t in _tasks(plan, "operate"))
    assert operations == sorted((f"p-{n}", op, seed) for n in (3, 6, 9)
                                for op in ("final-d", "final-s") for seed in (201, 202))
    for task in _tasks(plan, "operate"):
        assert task["identity"]["checkpoint"] == "final" and task["identity"]["seed_role"] == "diagnostic"
        assert task["inputs"] == [scenarios[task["scenario"]]["configs"]["diagnostic"][str(task["identity"]["seed"])]]

def test_a09_style_ppo_seed_and_config_lookup_key_stay_separate(tmp_path):
    paths = _scene(tmp_path / "in", "rural-coverage-9-peers", 9)
    scenarios = {"a01": _scenario(paths, 9), "a09": _scenario(paths, 9)}
    rows = [_row("a01", "a01"),
            _row("a09", "a09", seeds={"training": [102]}, training_config_key=101,
                 training={"total_timesteps": 20})]
    matrix, plan = _plan(tmp_path / "m", _train(scenarios, rows, [FINAL_D]))
    trains = {t["row"]: t for t in _tasks(plan, "train")}
    assert trains["a01"]["identity"]["training_seed"] == 101
    assert trains["a09"]["identity"]["training_seed"] == 102
    assert _arg(trains["a09"], "--seed") == "102"
    assert trains["a09"]["config_lookup"] == {"key": "101", "seed": 102, "ini": paths["101"],
                                              "fallback": False}
    assert _arg(trains["a09"], "--run-config") == paths["101"]
    assert _arg(trains["a09"], "--total-timesteps") == "20"
    assert "--continue-from-run-dir" not in trains["a09"]["args"]  # fresh, never a seed-101 continuation
    # Diagnostic 201/202 are evaluation seeds, not held out.
    assert matrix["seeds"]["diagnostic"] == [201, 202] and matrix["seeds"]["held_out"] == []
    assert {t["identity"]["seed_role"] for t in _tasks(plan, "operate")} == {"diagnostic"}
    # Without the lookup key the PPO seed's entry is used, and the run_config fallback is explicit.
    rows[1].pop("training_config_key")
    _, fallback = _plan(tmp_path / "m2", _train(scenarios, rows, [FINAL_D]))
    lookup = next(t for t in _tasks(fallback, "train") if t["row"] == "a09")["config_lookup"]
    assert lookup["key"] == "102" and lookup["fallback"] is True

def test_continuation_names_one_parent_and_a_cumulative_budget(tmp_path):
    paths = _scene(tmp_path / "in", "urban-recovery-3-peers", 3)
    parent = _parent(tmp_path / "parent", 20, paths["101"])
    scenarios = {"a01": _scenario(paths, 3, mission="recovery")}
    row = _row("a01", "a01", continue_from={"run_dir": str(parent), "model": "final"})
    matrix, plan = _plan(tmp_path / "m", _train(scenarios, [row], [FINAL_D]))
    train = _tasks(plan, "train")[0]
    record = plan["rows"][0]
    assert record["continue_from"]["num_timesteps"] == 20 and record["continue_from"]["seed"] == 101
    assert train["identity"]["model_source"] == record["continue_from"]["digest"]
    assert _arg(train, "--continue-from-run-dir") == str(parent.resolve())
    assert _arg(train, "--continue-model") == "final" and _arg(train, "--total-timesteps") == "40"
    assert record["retained_checkpoints"] == [40]
    assert _kinds(plan)["operate"] == 2
    refusals = [({"seeds": {"training": [101, 103]}}, "exactly one training seed"),
                ({"training": {"total_timesteps": 20}}, "must exceed"),
                ({"seeds": {"training": [103]}}, "differs from the parent's seed")]
    for change, message in refusals:
        with pytest.raises(ValueError, match=message):
            _plan(tmp_path / f"bad-{len(message)}", _train(scenarios, [{**row, **change}], [FINAL_D]))

def _selection_batch(tmp_path: Path, selection: dict) -> dict:
    six = _scene(tmp_path / "in", "urban-coverage-6-peers", 6, seeds=(101, 201, 202, 211, 212))
    nine = _scene(tmp_path / "in", "urban-coverage-9-peers", 9)
    scenarios = {"screen": _scenario(six, 6), "extend": _scenario(nine, 9)}
    scenarios["screen"]["configs"]["model_selection"] = {"211": six["211"], "212": six["212"]}
    validate = {"id": "validate", "mode": "frozen_deterministic", "seed_role": "model_selection",
                "at_steps": ["best"]}
    rows = [_row("screen-standard", "screen", operations=["validate"]),
            _row("screen-exploration", "screen", operations=["validate"]),
            _row("extend-standard", "extend", operations=["final-d"]),
            _row("extend-exploration", "extend", operations=["final-d"])]
    data = _train(scenarios, rows, [validate, FINAL_D],
                  stages=[{"name": "screen", "rows": ["screen-standard", "screen-exploration"],
                           "selection": selection},
                          {"name": "extend", "rows": ["extend-standard", "extend-exploration"],
                           "needs": ["screen"]}])
    data["seeds"]["model_selection"] = [211, 212]
    data["training"].update(checkpoint_timing="standard", eval_every_steps=20)
    return data

SELECTION_BASE = {"candidates": {"standard": ["screen-standard"], "exploration": ["screen-exploration"]},
                  "branches": {"standard": ["extend-standard"], "exploration": ["extend-exploration"]}}

def test_named_rule_selection_differs_from_a_replay_pinned_winner(tmp_path):
    named = {**SELECTION_BASE, "rule": "legacy-mission-profile-v1", "source_operation": "validate",
             "source_checkpoint": "best", "retain": ["standard"]}
    _, plan = _plan(tmp_path / "named", _selection_batch(tmp_path / "a", named))
    # 4 trains; 2 screen rows x best x 2 model-selection seeds; 2 extension rows x final x 2 diagnostic seeds.
    assert _kinds(plan) == {"train": 4, "operate": 8, "select": 1, "curves": 2, "review": 2, "index": 2}
    select = _tasks(plan, "select")[0]
    validate_ids = sorted(t["id"] for t in _tasks(plan, "operate") if t["identity"]["operation"] == "validate")
    assert sorted(select["needs"]) == validate_ids and len(validate_ids) == 4
    assert select["selection_rule"]["rule"] == "legacy-mission-profile-v1"
    assert select["selection_rule"]["seed_role"] == "model_selection"
    assert select["selection_rule"]["settings"] == {"retain": ["standard"]}
    for task in _tasks(plan, "train"):
        if task["row"].startswith("extend-"):
            assert select["id"] in task["needs"]
            assert task["selection"] == {"task": select["id"], "branch": task["row"].split("-", 1)[1]}

    replay = {**SELECTION_BASE, "rule": "replay", "winners": ["exploration"],
              "provenance": "recorded winner of the historical selection receipt"}
    _, pinned = _plan(tmp_path / "replay", _selection_batch(tmp_path / "b", replay))
    select = _tasks(pinned, "select")[0]
    assert select["needs"] == [] and select["selection_rule"]["rule"] == "replay"
    assert select["selection_rule"]["settings"]["winners"] == ["exploration"]
    assert select["key"] != _tasks(plan, "select")[0]["key"]

def test_batches_share_one_resource_pool(tmp_path):
    pool = {"directory": str(tmp_path / "shared-pool"), "capacity": 3}
    paths = _scene(tmp_path / "in", "urban-coverage-6-peers", 6)
    parent = _parent(tmp_path / "parent", 20, paths["101"])
    package_a = _train({"a07": _scenario(paths, 6, target=0.8)}, [_row("a07", "a07")], [FINAL_D],
                       execution={"workers": 2, "resource_pool": pool})
    schedules = [{"id": kind, "mode": "frozen_deterministic", "seed_role": "diagnostic",
                  "schedule": {"kind": kind, "settings": {}}}
                 for kind in ("sample-then-deterministic", "sample-then-hold")]
    package_b = {"matrix_version": 2, "name": "package-b", "kind": "evaluate",
                 "scenarios": {"a07": _scenario(paths, 6, target=0.8)},
                 "seeds": {"diagnostic": [201, 202]}, "evaluation": {"operations": schedules},
                 "execution": {"workers": 1, "resource_pool": pool},
                 "rows": [{"name": "a07", "scenario": "a07",
                           "model_source": {"run_dir": str(parent), "model": "final"}}]}
    _, plan_a = _plan(tmp_path / "a", package_a, "batch-a-v2.json")
    _, plan_b = _plan(tmp_path / "b", package_b, "batch-b-v2.json")
    pool_a, pool_b = plan_a["execution_declared"]["resource_pool"], plan_b["execution_declared"]["resource_pool"]
    assert pool_a["path"] == pool_b["path"] == str((tmp_path / "shared-pool").resolve())
    assert pool_a["capacity"] == pool_b["capacity"] == 3
    assert (plan_a["execution_declared"]["workers"], plan_b["execution_declared"]["workers"]) == (2, 1)
    assert _kinds(plan_b) == {"operate": 4, "review": 1, "index": 1}
    for task in _tasks(plan_b, "operate"):
        assert task["schedule"] == {"kind": task["identity"]["operation"], "settings": {"coverage_target": 0.8}}
        assert task["identity"]["training_seed"] is None and task["identity"]["checkpoint"] == "final"
        assert task["binding"]["model_sha256"] == json.loads((parent / "train_manifest.json").read_text())["model_sha256"]

def test_both_online_protocols_expand_per_checkpoint_and_seed(tmp_path):
    paths = _scene(tmp_path / "in", "rural-recovery-3-peers", 3)
    gated = {"id": "online-gated", "mode": "online_gated_v1", "seed_role": "diagnostic",
             "at_steps": [20, "final"], "online": {"n_steps": 10, "batch_size": 5, "target_kl": None}}
    sb3 = {"id": "online-sb3", "mode": "online_sb3_v1", "seed_role": "diagnostic",
           "at_steps": [20, "final"],
           "online": {"n_steps": 10, "batch_size": 5, "learning_rate": 0.0001, "ent_coef": 0.001,
                      "target_kl": 0.02}}
    scenarios = {"r": _scenario(paths, 3, mission="recovery")}
    _, plan = _plan(tmp_path / "m", _train(scenarios, [_row("r", "r")], [gated, sb3]))
    operations = _tasks(plan, "operate")
    assert len(operations) == 8  # 2 protocols x 2 checkpoints x 2 seeds
    settings = {t["identity"]["protocol"]: json.loads(_arg(t, "--protocol-settings-json")) for t in operations}
    assert settings["online_gated_v1"] == {"n_steps": 10, "batch_size": 5}
    assert settings["online_sb3_v1"] == {"n_steps": 10, "batch_size": 5, "learning_rate": 0.0001,
                                         "ent_coef": 0.001, "target_kl": 0.02}
    assert len({t["key"] for t in operations}) == 8 and len({t["output_dir"] for t in operations}) == 8
    with pytest.raises(ValueError, match="target_kl must be null"):
        bad = copy.deepcopy(gated)
        bad["online"]["target_kl"] = 0.02
        _plan(tmp_path / "bad", _train(scenarios, [_row("r", "r")], [bad]))

ESCAPE = {"initial_sample_decisions": 60, "burst_decisions": 20, "cooldown_decisions": 40,
          "max_bursts": 3, "rejected_window": 20, "rejected_threshold": 10,
          "movement_threshold_m": 1.0, "progress_window": 60, "progress_threshold": 0.01}

SPLIT = {"initial-sampling": {"initial_sample_decisions": 60},
         "stall-burst": {k: v for k, v in ESCAPE.items() if k != "initial_sample_decisions"},
         "sample-then-deterministic": {}, "sample-then-hold": {"coverage_target": 0.8}}

def test_each_schedule_kind_takes_only_its_split_settings(tmp_path):
    paths = _scene(tmp_path / "in", "urban-coverage-3-peers", 3)
    operations = [{"id": kind, "mode": "frozen_deterministic", "seed_role": "diagnostic",
                   "at_steps": ["final"], "schedule": {"kind": kind, "settings": settings}}
                  for kind, settings in SPLIT.items()]
    scenarios = {"c": _scenario(paths, 3, target=0.8)}
    _, plan = _plan(tmp_path / "m", _train(scenarios, [_row("c", "c")], operations))
    schedules = {t["identity"]["operation"]: t["schedule"] for t in _tasks(plan, "operate")}
    assert schedules == {"initial-sampling": {"kind": "initial-sampling", "settings": {"initial_sample_decisions": 60}},
                         "stall-burst": {"kind": "stall-burst", "settings": {
                             **SPLIT["stall-burst"], "movement_threshold_m": 1.0, "progress_threshold": 0.01}},
                         "sample-then-deterministic": {"kind": "sample-then-deterministic",
                                                       "settings": {"coverage_target": 0.8}},
                         "sample-then-hold": {"kind": "sample-then-hold", "settings": {"coverage_target": 0.8}}}
    assert _kinds(plan)["operate"] == 8 and len({t["identity"]["schedule_digest"] for t in _tasks(plan, "operate")}) == 4
    for kind in ("initial-sampling", "stall-burst"):
        shared = [{**operations[0], "schedule": {"kind": kind, "settings": ESCAPE}}]
        with pytest.raises(ValueError, match="unknown keys|unexpected settings"):
            _plan(tmp_path / f"shared-{kind}", _train(scenarios, [_row("c", "c")], shared))

def _number(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        return {k: _number(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_number(v) for v in value]
    return value

def normalize_selection(selection: dict) -> dict:
    return {key: _number(selection.get(key)) for key in SELECTION_KEYS}

def normalize_ppo(settings: dict) -> dict:
    return {key: _number(list(settings[key]) if key == "net_arch" and settings.get(key) is not None
                         else settings.get(key)) for key in PPO_FIELDS}

def case_name(case: dict | None, slug: str | None = None) -> str:
    if not case:
        return slug
    return f"{case['environment']}-{case['mission']}-{case['peers']}-peers"

def normalize_case(case: dict | None, slug: str | None = None) -> dict:
    if not case:
        return {"name": slug}
    gates = {str(seed): float(entry["gate_s"]) for seed, entry in (case.get("seeds") or {}).items()}
    target = case.get("coverage_target")
    return {"name": case_name(case), "mission": case["mission"], "environment": case["environment"],
            "peers": case["peers"], "coverage_target": None if target is None else float(target),
            "reviewed_exception": bool(case.get("reviewed_exception")),
            "exception_reason": case.get("exception_reason"), "gates": gates}

def _parent_record(run_dir) -> dict:
    run_dir = Path(run_dir).resolve()
    manifest = json.loads((run_dir / "train_manifest.json").read_text())
    return {"run_dir": str(run_dir), "model_sha256": manifest["model_sha256"],
            "num_timesteps": int(manifest["num_timesteps"]), "seed": manifest.get("seed")}

def _schedule_key(schedule):
    return None if schedule is None else json.dumps(_number(schedule), sort_keys=True)

def _online_key(settings):
    return None if not settings else json.dumps(_number(settings), sort_keys=True)

def _sha(path) -> str:
    return sha256_file(Path(path))

def _op(row, training_seed, steps, mode, seed, ini, *, role="diagnostic", schedule=None, online=None,
        records=False) -> list:
    return [row, training_seed, steps, mode, role, seed, _schedule_key(schedule),
            _online_key(GATED if mode == "online_gated_v1" and online is None else online), _sha(ini), records]

def _imported_baselines(manifest_path, case: str, role: str = "diagnostic") -> list:
    manifest = json.loads(Path(manifest_path).read_text())
    digest = sha256_file(manifest_path)
    return sorted([case, policy, role, int(episode["seed"]), digest, None, None, False]
                  for policy, block in manifest["policies"].items() for episode in block["episodes"])

def _fresh_baselines(case: str, configs: dict, policies=("hold", "random_valid", "scripted"),
                     role: str = "diagnostic", seeds=(201, 202)) -> list:
    return [[case, policy, role, seed, None, _sha(configs[str(seed)]), None, False]
            for policy in policies for seed in seeds]

def _finish(inventory: dict) -> dict:
    for key in ("operations", "baselines", "checks", "comparisons"):
        inventory[key] = sorted(inventory[key], key=json.dumps)
    inventory["history"] = {case: sorted(dirs) for case, dirs in inventory["history"].items() if dirs}
    rows = inventory["rows"]
    training = [r for r in rows.values() if r.get("kind") == "train"]
    inventory["counts"] = {
        "rows": len(rows), "training_rows": len(training),
        "training_tasks": sum(len(r["ppo_seeds"]) for r in training),
        "continuations": sum(r["parent"] is not None for r in training),
        "fresh": sum(r["parent"] is None for r in training),
        "evaluate_rows": len(rows) - len(training),
        "training_decisions": sum(len(r["ppo_seeds"]) * (r["total_timesteps"] - (r["parent"] or {}).get("num_timesteps", 0))
                                  for r in training),
        "operations": len(inventory["operations"]), "baselines": len(inventory["baselines"]),
        "imported_baselines": sum(b[4] is not None for b in inventory["baselines"]),
        "checks": len(inventory["checks"]), "comparisons": len(inventory["comparisons"]),
        "cases": len({r["case"]["name"] for r in rows.values()})}
    return inventory

def _empty(seeds: dict, execution: dict) -> dict:
    return {"rows": {}, "operations": [], "baselines": [], "checks": [], "check_scope": {},
            "history": {}, "stages": {}, "comparisons": [],
            "seeds": {role: list(seeds.get(role, [])) for role in ("training", "model_selection", "diagnostic", "held_out")},
            "execution": execution}

def _training_row(case, selection, ppo, seeds, keys, ini, parent, total, timing, every, keep,
                  validation=0, decisions=600, curriculum=None, slug=None) -> dict:
    return {"kind": "train", "case": normalize_case(case, slug), "selection": normalize_selection(selection),
            "ppo": normalize_ppo(ppo), "ppo_seeds": sorted(seeds), "config_keys": {str(s): str(k) for s, k in keys.items()},
            "training_ini_sha256": _sha(ini), "parent": parent, "total_timesteps": total,
            "checkpoint": {"timing": timing, "every": every, "keep": keep},
            "validation_every": validation, "decisions_per_episode": decisions, "curriculum": curriculum}

def _gate_all(inventory: dict, check: list, *, comparison="strict_v1", parent=None, case=None,
              contact_audit=False) -> None:
    if check[0] == "replay_gate":
        check.append({"comparison": comparison, "parent": _parent_record(parent) if parent else None,
                      "case": normalize_case(case, check[1]), "contact_audit": contact_audit})
    inventory["checks"].append(check)
    inventory["check_scope"][":".join(map(str, check[:3]))] = None

def _scope_all(inventory: dict) -> None:
    for key, scope in inventory["check_scope"].items():
        if scope is None:
            inventory["check_scope"][key] = sorted(inventory["rows"])

def _planning_seed(ini: Path):
    """The run.ini planning seed, or None when the INI records none (pre-planning-seed inputs)."""
    from scripts.baselines.config import ConfigError, load_baseline, resolve_planning_seed
    try:
        return resolve_planning_seed(load_baseline(str(ini)), None)[0]
    except ConfigError:
        return None

def _merge(parts: list) -> dict:
    merged = copy.deepcopy(parts[0])
    for part in parts[1:]:
        merged["rows"].update(part["rows"])
        for key in ("operations", "baselines", "checks", "comparisons"):
            merged[key] += [x for x in part[key] if x not in merged[key]]
        for check, rows in part["check_scope"].items():
            merged["check_scope"][check] = sorted(set(merged["check_scope"].get(check) or []) | set(rows or []))
        merged["history"].update(part["history"])
        merged["stages"].update(part["stages"])
        for role, seeds in part["seeds"].items():
            merged["seeds"][role] = sorted(set(merged["seeds"][role]) | set(seeds))
    return _finish(merged)

def v2_inventory(*pairs) -> dict:
    """The normalized inventory read from one or more (version 2 matrix, plan v3) pairs."""
    return _merge([_v2_one(matrix, plan) for matrix, plan in zip(pairs[::2], pairs[1::2])])

def _v2_one(matrix: dict, plan: dict) -> dict:
    files = plan["inputs"]

    def sha(path):
        return files[str(Path(path).resolve())]["sha256"]

    scenarios = plan["scenarios"]
    records = {r["name"]: r for r in plan["rows"]}
    execution = matrix["execution"]
    pool = execution.get("resource_pool")
    inventory = _empty(plan["seeds"], {"workers": execution.get("workers", 1), "nice": execution.get("nice", 0),
                                       "resource_pool_capacity": pool["capacity"] if pool else None})

    def case_of(slug):
        return case_name(scenarios[slug]["case"], slug)

    totals = {}
    for task in _tasks(plan, "train"):
        record = records[task["row"]]
        training = record["training"]
        seed = task["identity"]["training_seed"]
        row = inventory["rows"].get(task["row"])
        if row is not None:
            row["ppo_seeds"] = sorted(row["ppo_seeds"] + [seed])
            row["config_keys"][str(seed)] = task["config_lookup"]["key"]
            continue
        parent = record["continue_from"]
        parent = None if parent is None else {**_parent_record(parent["run_dir"]),
                                              "model_sha256": parent["model_sha256"],
                                              "num_timesteps": parent["num_timesteps"]}
        curriculum = None
        if record["curriculum"] is not None:
            from scripts.rl.env.curriculum import load_curriculum_schedule
            curriculum = load_curriculum_schedule(record["curriculum"]["path"])["config_sha256"]
        totals[task["row"]] = training["total_timesteps"]
        inventory["rows"][task["row"]] = {
            "kind": "train", "case": normalize_case(scenarios[task["scenario"]]["case"], task["scenario"]),
            "selection": normalize_selection(record["selection"]), "ppo": normalize_ppo(training),
            "ppo_seeds": [seed], "config_keys": {str(seed): task["config_lookup"]["key"]},
            "training_ini_sha256": sha(task["config_lookup"]["ini"]), "parent": parent,
            "total_timesteps": training["total_timesteps"],
            "checkpoint": {"timing": training["checkpoint_timing"],
                           "every": training.get("checkpoint_every_steps", 0),
                           "keep": training.get("keep_checkpoints", 3)},
            "validation_every": training.get("eval_every_steps", 0),
            "decisions_per_episode": record["decisions_per_episode"], "curriculum": curriculum}
    for record in plan["rows"]:
        if record["model_source"] is not None:
            source = record["model_source"]
            totals[record["name"]] = source["num_timesteps"]
            inventory["rows"][record["name"]] = {
                "kind": "evaluate", "case": normalize_case(scenarios[record["scenario"]]["case"], record["scenario"]),
                "parent": {**_parent_record(source["run_dir"]), "model_sha256": source["model_sha256"],
                           "num_timesteps": source["num_timesteps"]}}
    operations = {op["id"]: op for op in plan["operations"]}
    for task in _tasks(plan, "operate"):
        segment = task["identity"]["checkpoint"]
        steps = totals[task["row"]] if segment == "final" else segment if segment == "best" else int(segment)
        op = operations[task["identity"]["operation"]]
        inventory["operations"].append([
            task["row"], task["identity"]["training_seed"], steps, task["identity"]["protocol"],
            task["identity"]["seed_role"], task["identity"]["seed"], _schedule_key(task["schedule"]),
            _online_key(op["online"]), sha(task["inputs"][0]), "--decision-records" in task["args"]])
    for task in _tasks(plan, "baseline"):
        baselines = scenarios[task["scenario"]]["baselines"]
        imported = baselines["import_from"] if task["identity"]["policy"] not in ("geometric", "optimization") else None
        inventory["baselines"].append([
            case_of(task["scenario"]), task["identity"]["policy"], task["identity"]["seed_role"],
            task["identity"]["seed"], imported["sha256"] if imported else None,
            None if imported else sha(task["inputs"][0]),
            (task.get("planning") or {}).get("planning_seed"), "--decision-records" in task["args"]])
    gated = {}
    for task in plan["tasks"]:
        if task["kind"] in ("train", "operate"):
            for need in task["needs"]:
                gated.setdefault(need, set()).add(task["row"])
    for task in plan["tasks"]:
        if task["kind"] not in ("replay_gate", "preflight", "reward_audit"):
            continue
        source = _arg(task, "--source")
        check = [task["kind"], case_of(task["scenario"]), task["identity"]["seed"],
                 str(Path(source).resolve()) if source and not source.startswith("{") else source,
                 sha(task["inputs"][0]) if task["inputs"] else None]
        if task["kind"] == "replay_gate":
            parent = _arg(task, "--parent-run-dir")
            check.append({"comparison": _arg(task, "--comparison"),
                          "parent": _parent_record(parent) if parent else None,
                          "case": normalize_case(json.loads(_arg(task, "--case-json") or "{}"), check[1]),
                          "contact_audit": "--contact-audit" in task["args"]})
        inventory["checks"].append(check)
        inventory["check_scope"][":".join(map(str, check[:3]))] = sorted(gated.get(task["id"], ()))
    for slug, scenario in scenarios.items():
        dirs = [h["path"] if isinstance(h, dict) else h for h in scenario.get("history_sources") or []]
        if dirs:
            inventory["history"].setdefault(case_of(slug), []).extend(str(Path(d).resolve()) for d in dirs)
    for stage in plan["stages"]:
        inventory["stages"][stage["name"]] = {"rows": sorted(stage["rows"]), "needs": list(stage["needs"])}
    for task in _tasks(plan, "compare"):
        item = [case_of(task["scenario"]), task["identity"]["checkpoint"]]
        if item not in inventory["comparisons"]:
            inventory["comparisons"].append(item)
    return _finish(inventory)

def compare_inventories(legacy: dict, converted: dict, limit: int = 60) -> list:
    """Field-level differences; an empty list is parity."""
    differences = []
    for key in ("seeds", "execution", "counts", "stages", "history"):
        for field in sorted(set(legacy[key]) | set(converted[key])):
            if legacy[key].get(field) != converted[key].get(field):
                differences.append(f"{key}.{field}: legacy={legacy[key].get(field)!r} "
                                   f"converted={converted[key].get(field)!r}")
    for name in sorted(set(legacy["rows"]) | set(converted["rows"])):
        a, b = legacy["rows"].get(name), converted["rows"].get(name)
        if a is None or b is None:
            differences.append(f"rows.{name}: present only in {'converted' if a is None else 'legacy'}")
            continue
        for field in sorted(set(a) | set(b)):
            if a.get(field) != b.get(field):
                differences.append(f"rows.{name}.{field}: legacy={a.get(field)!r} converted={b.get(field)!r}")
    for key in ("operations", "baselines", "checks", "comparisons"):
        left = {json.dumps(x) for x in legacy[key]}
        right = {json.dumps(x) for x in converted[key]}
        for item in sorted(left - right):
            differences.append(f"{key}: legacy only {item}")
        for item in sorted(right - left):
            differences.append(f"{key}: converted only {item}")
    for check in sorted(set(legacy["check_scope"]) | set(converted["check_scope"])):
        a, b = legacy["check_scope"].get(check), converted["check_scope"].get(check)
        if a != b:
            differences.append(f"check_scope.{check}: legacy gates {len(a or [])} rows, "
                               f"converted gates {len(b or [])} rows")
    if limit and len(differences) > limit:
        differences = differences[:limit] + [f"... {len(differences) - limit} more differences"]
    return differences

def test_inventory_comparison_reports_each_changed_dimension(tmp_path):
    paths = _scene(tmp_path / "in", "rural-coverage-9-peers", 9)
    scenarios = {"a09": _scenario(paths, 9)}
    rows = [_row("a09", "a09", seeds={"training": [102]}, training_config_key=101)]
    matrix, plan = _plan(tmp_path / "m", _train(scenarios, rows, [FINAL_D, FINAL_S]))
    inventory = v2_inventory(matrix, plan)
    assert inventory["counts"]["operations"] == 4 and compare_inventories(inventory, inventory) == []
    assert inventory["rows"]["a09"]["ppo_seeds"] == [102] and inventory["rows"]["a09"]["config_keys"] == {"102": "101"}
    changed = copy.deepcopy(inventory)
    changed["rows"]["a09"]["ppo_seeds"] = [101]
    changed["operations"][0][8] = "0" * 64
    changed["check_scope"]["replay_gate:x:201"] = ["a09"]
    differences = compare_inventories(inventory, changed)
    assert "rows.a09.ppo_seeds: legacy=[102] converted=[101]" in differences
    assert any(d.startswith("operations: legacy only") for d in differences)
    assert any(d.startswith("check_scope.replay_gate:x:201") for d in differences)

@pytest.mark.parametrize('field,value', [('comparison', 'strict_v1'), ('parent', None), ('case', {'mission': 'coverage'}), ('contact_audit', False)])
def test_inventory_comparison_detects_changed_replay_contract(field, value):
    contract = {"comparison": "pre_contact_source_v1", "parent": {"model_sha256": "a" * 64},
                "case": {"mission": "jamming"}, "contact_audit": True}
    inventory = {"seeds": {}, "execution": {}, "stages": {}, "history": {},
                 "counts": {}, "rows": {}, "operations": [], "baselines": [],
                 "checks": [["replay_gate", "case", 201, contract]],
                 "comparisons": [], "check_scope": {}}
    changed = copy.deepcopy(inventory)
    changed["checks"][0][-1][field] = value
    differences = compare_inventories(inventory, changed)
    assert any(d.startswith("checks: legacy only") for d in differences)
    assert any(d.startswith("checks: converted only") for d in differences)


def conversion_paths(name: str) -> list:
    return [CONVERSIONS[name][0] / f for f in CONVERSIONS[name][2]]

def conversion_inventory(name: str) -> dict:
    pairs = []
    for path in conversion_paths(name):
        matrix = load_matrix_v2(path)
        pairs += [matrix, build_batch_plan(matrix)]
    return v2_inventory(*pairs)
