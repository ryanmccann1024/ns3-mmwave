"""Matrix v2 validation, plan v3 expansion and identity, selection rules and the launcher.

No simulator or training runs: binaries are fake executables that are hashed only.
"""

import copy
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.rl import experiment
from scripts.rl.experiments import selection
from scripts.rl.experiments.config import load_matrix_v2, native_decisions
from scripts.rl.experiments.plan import (EXPERIMENT_PLAN_VERSION, KEY_DIMENSIONS, PLAN_NAME,
                                         build_batch_plan, check_collisions, task_key,
                                         write_batch_plan)
from scripts.rl.policy import experiment as legacy
from scripts.sim_support import find_mesh_root

MESH = find_mesh_root()
TRACKED_V1 = MESH / "inputs/experiments/bypass-smoke-matrix.json"
EXAMPLE = MESH / "inputs/experiments/examples/coordination-smoke"
LAUNCHER = MESH / "scripts/rl/run-experiments.sh"


def _matrix(run_config: str, **changes) -> dict:
    """Small train batch on the shared 2-decision fake scenario."""
    data = {
        "matrix_version": 2, "name": "tiny", "description": "contract test", "kind": "train",
        "scenarios": {"scene": {"run_config": run_config}},
        "seeds": {"training": [1], "diagnostic": [21, 22]},
        "training": {"total_timesteps": 8, "n_steps": 2, "batch_size": 2, "n_epochs": 1,
                     "checkpoint_every_steps": 4, "keep_checkpoints": 2,
                     "checkpoint_timing": "after_update"},
        "evaluation": {"operations": [
            {"id": "frozen", "mode": "frozen_deterministic", "seed_role": "diagnostic",
             "at_steps": [4, "final"]}]},
        "rows": [{"name": "row-a", "scenario": "scene", "profile": "standard",
                  "observation_preset": "raw_links_v1", "action_profile": "move_2d",
                  "reward_components": ["delivery_ratio"], "reward_weights": [1.0]}],
    }
    data.update(changes)
    return data


CASE = {"mission": "coverage", "environment": "rural", "peers": 3}


def _write(directory: Path, data: dict, name: str = "batch.json") -> str:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(data))
    return str(path)


def _load(tmp_path: Path, data: dict) -> dict:
    return load_matrix_v2(_write(tmp_path / "m", data))


def _mutate(data: dict, path: tuple, value) -> dict:
    data = copy.deepcopy(data)
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return data


def _drop(data: dict, path: tuple) -> dict:
    data = copy.deepcopy(data)
    target = data
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    return data


def _parent_run(directory: Path, steps: int, seed: int = 1, run_ini: str | None = None) -> Path:
    """Completed training manifest plus a model ZIP carrying SB3 counters."""
    directory.mkdir(parents=True)
    model = directory / "maskable_ppo_mesh.zip"
    with zipfile.ZipFile(model, "w") as archive:
        archive.writestr("data", json.dumps({"num_timesteps": steps, "_n_updates": steps // 2}))
    from scripts.artifact_io import sha256_file
    manifest = {"status": "completed", "seed": seed, "num_timesteps": steps,
                "model_path": str(model), "model_sha256": sha256_file(model),
                "hyperparameters": {"n_steps": 2, "batch_size": 2, "n_epochs": 1},
                "scenario_identity": {"run_ini_sha256": sha256_file(run_ini) if run_ini else None},
                "selection": {"observation_preset": "raw_links_v1",
                              "reward_components": ["delivery_ratio"], "reward_weights": [1.0]},
                "checkpoints": []}
    (directory / "train_manifest.json").write_text(json.dumps(manifest))
    return directory






V2_REFUSALS = [
    ("unknown top key", ("colour",), "red", "unknown keys"),
    ("unknown row key", ("rows", 0, "epochs"), 3, "unknown keys"),
    ("unknown training key", ("training", "warmup"), 1, "unknown keys"),
    ("bad kind", ("kind",), "sweep", "kind must be one of"),
    ("unknown scenario", ("rows", 0, "scenario"), "nowhere", "not declared"),
    ("seed overlap", ("seeds", "diagnostic"), [1, 22], "disjoint"),
    ("held-out overlap", ("seeds", "held_out"), [21], "disjoint"),
    ("model selection overlap", ("seeds", "model_selection"), [22], "disjoint"),
    ("repeated seed", ("seeds", "diagnostic"), [21, 21], "distinct"),
    ("bad mode", ("evaluation", "operations", 0, "mode"), "online", "mode must be one of"),
    ("best without validation", ("evaluation", "operations", 0, "at_steps"), ["best"],
     "training validation"),
    ("checkpoint not retained", ("training", "keep_checkpoints"), 1, "not retained"),
    ("checkpoint never produced", ("evaluation", "operations", 0, "at_steps"), [6], "not retained"),
    ("cadence off rollout", ("training", "n_steps"), 8, "impossible after_update"),
    ("budget off cadence", ("training", "total_timesteps"), 10, "impossible after_update"),
    ("after-update with validation", ("training", "eval_every_steps"), 4, "without in-training"),
    ("asserted episode length", ("training", "decisions_per_episode"), 64, "native timing"),
    ("asserted total episodes", ("training", "total_episodes"), 3, "total_episodes"),
    ("unsafe pool directory", ("execution",), {"resource_pool": {"directory": "../pool", "capacity": 2}},
     "unsafe relative output path"),
    ("duplicate operation", ("evaluation", "operations"),
     [{"id": "frozen", "mode": "frozen_sampled", "seed_role": "diagnostic", "at_steps": ["final"]}] * 2,
     "distinct"),
    ("empty seed role", ("evaluation", "operations", 0, "seed_role"), "held_out", "has no seeds"),
]


@pytest.mark.parametrize("path,value,message", [c[1:] for c in V2_REFUSALS],
                         ids=[c[0] for c in V2_REFUSALS])
def test_v2_refusals(tmp_path, multi_run_config, path, value, message):
    data = _mutate(_matrix(multi_run_config), path, value)
    with pytest.raises(ValueError, match=message):
        _load(tmp_path, data)


@pytest.mark.parametrize("path", [("kind",), ("rows",), ("evaluation",), ("training", "total_timesteps")])
def test_v2_missing_required_keys(tmp_path, multi_run_config, path):
    with pytest.raises(ValueError):
        _load(tmp_path, _drop(_matrix(multi_run_config), path))


def test_checks_and_evaluate_kinds_take_no_training(tmp_path, multi_run_config):
    checks = {"matrix_version": 2, "name": "checks-only", "kind": "checks",
              "scenarios": {"scene": {"run_config": multi_run_config,
                                      "baselines": {"policies": ["hold", "random_valid"],
                                                    "seed_role": "diagnostic"}}},
              "seeds": {"diagnostic": [21]}}
    plan = build_batch_plan(_load(tmp_path, checks))
    assert {t["kind"] for t in plan["tasks"]} == {"baseline", "review", "index"}
    for bad, message in (((("training",), {"total_timesteps": 8}), "no training settings"),
                         ((("seeds", "training"), [1]), "no training seeds")):
        with pytest.raises(ValueError, match=message):
            _load(tmp_path, _mutate(checks, *bad))
    with pytest.raises(ValueError, match="at least one registered check"):
        _load(tmp_path, _mutate(checks, ("scenarios", "scene"), {"run_config": multi_run_config}))

    parent = _parent_run(tmp_path / "parent run", 8)
    evaluate = {"matrix_version": 2, "name": "evaluate-only", "kind": "evaluate",
                "scenarios": {"scene": {"run_config": multi_run_config}},
                "seeds": {"held_out": [31, 32]},
                "evaluation": {"operations": [{"id": "frozen", "mode": "frozen_deterministic",
                                               "seed_role": "held_out"}]},
                "rows": [{"name": "imported", "scenario": "scene",
                          "model_source": {"run_dir": str(parent), "model": "final"}}]}
    plan = build_batch_plan(_load(tmp_path, evaluate))
    leaves = [t for t in plan["tasks"] if t["kind"] == "operate"]
    assert len(leaves) == 2 and all("/model-" in t["output_dir"] for t in leaves)
    assert leaves[0]["identity"]["model_source"] and leaves[0]["identity"]["training_seed"] is None
    assert leaves[0]["args"][leaves[0]["args"].index("--run-dir") + 1] == str(parent.resolve())
    assert "train" not in {t["kind"] for t in plan["tasks"]}
    with pytest.raises(ValueError, match="model_source is required"):
        _load(tmp_path, _drop(evaluate, ("rows", 0, "model_source")))
    with pytest.raises(ValueError, match="not used by kind 'evaluate'"):
        _load(tmp_path, _mutate(evaluate, ("evaluation", "operations", 0, "at_steps"), ["final"]))
    with pytest.raises(ValueError, match="unknown keys"):
        train = _matrix(multi_run_config)
        train["rows"][0]["model_source"] = {"run_dir": str(parent)}
        _load(tmp_path, train)


def test_continuation_budget_seed_and_identity(tmp_path, multi_run_config):
    parent = _parent_run(tmp_path / "parent", 8, run_ini=multi_run_config)
    data = _matrix(multi_run_config)
    data["rows"][0]["continue_from"] = {"run_dir": str(parent), "model": "final"}
    with pytest.raises(ValueError, match="must exceed the parent's 8"):
        _load(tmp_path, data)
    data["training"]["total_timesteps"] = 16
    data["evaluation"]["operations"][0]["at_steps"] = [12, "final"]
    plan = build_batch_plan(_load(tmp_path, data))
    train = next(t for t in plan["tasks"] if t["kind"] == "train")
    assert train["args"][-4:] == ["--continue-from-run-dir", str(parent.resolve()),
                                  "--continue-model", "final"]
    assert "--observation-preset" not in train["args"]
    data["seeds"]["training"] = [2]
    with pytest.raises(ValueError, match="differs from the parent's seed"):
        _load(tmp_path, data)


def test_a09_config_key_is_independent_of_the_ppo_seed(tmp_path, multi_run_config):
    data = _matrix(multi_run_config, seeds={"training": [102], "diagnostic": [201, 202]})
    data["scenarios"]["scene"]["configs"] = {"training": {"101": multi_run_config}}
    data["rows"][0]["training_config_key"] = 101
    plan = build_batch_plan(_load(tmp_path, data))
    train = next(t for t in plan["tasks"] if t["kind"] == "train")
    args = train["args"]
    assert args[args.index("--seed") + 1] == "102"
    assert train["config_lookup"] == {"key": "101", "seed": 102, "ini": multi_run_config,
                                      "fallback": False}
    data["rows"][0]["training_config_key"] = 103
    with pytest.raises(ValueError, match="training_config_key 103"):
        _load(tmp_path, data)


def test_two_by_two_by_two_by_two_gives_sixteen_distinct_leaves(tmp_path, multi_run_config):
    data = _matrix(multi_run_config, seeds={"training": [1, 2], "diagnostic": [21, 22]})
    data["scenarios"]["scene"]["case"] = CASE
    data["evaluation"]["operations"] = [
        {"id": "gated", "mode": "online_gated_v1", "seed_role": "diagnostic",
         "at_steps": [4, "final"], "online": {"n_steps": 2, "batch_size": 2}},
        {"id": "sb3", "mode": "online_sb3_v1", "seed_role": "diagnostic",
         "at_steps": [4, "final"], "online": {"n_steps": 2, "batch_size": 2}}]
    plan = build_batch_plan(_load(tmp_path, data), tmp_path / "root", None)
    leaves = [t for t in plan["tasks"] if t["kind"] == "operate"]
    assert len(leaves) == 16
    assert len({t["key"] for t in leaves}) == len({t["output_dir"] for t in leaves}) == 16
    assert all(t["key"] == task_key(t["identity"]) for t in plan["tasks"])
    assert set(leaves[0]["identity"]) == set(KEY_DIMENSIONS)
    assert all(t["binding"]["producer"].startswith("train/") for t in leaves)

    data["evaluation"]["operations"] = [
        {"id": "sampled", "mode": "frozen_sampled", "seed_role": "diagnostic", "at_steps": ["final"]},
        {"id": "sampled-burst", "mode": "frozen_sampled", "seed_role": "diagnostic",
         "at_steps": ["final"], "schedule": {"kind": "initial-sampling",
                                             "settings": {"initial_sample_decisions": 1}}}]
    plan = build_batch_plan(_load(tmp_path, data), tmp_path / "root2", None)
    leaves = [t for t in plan["tasks"] if t["kind"] == "operate"]
    assert len(leaves) == 8 and len({t["key"] for t in leaves}) == 8
    scheduled = [t for t in leaves if t["identity"]["schedule_digest"]]
    assert len(scheduled) == 4 and all("--schedule-json" in t["args"] for t in scheduled)


@pytest.mark.parametrize("operation,message", [
    ({"mode": "online_sb3_v1", "online": {"n_steps": 2, "batch_size": 2},
      "schedule": {"kind": "initial-sampling", "settings": {"initial_sample_decisions": 1}}},
     "cannot be combined"),
    ({"mode": "frozen_sampled", "schedule": {"kind": "stall-burst", "settings": {"progress_window": 3}}},
     "missing settings"),
    ({"mode": "frozen_sampled", "schedule": {"kind": "stall-burst", "settings": {
        "progress_window": 3, "rejected_window": 5, "rejected_threshold": 2,
        "movement_threshold_m": 0.5, "progress_threshold": 0.01, "burst_decisions": 2,
        "cooldown_decisions": 1, "max_bursts": 1}}},
     "rejected_window cannot exceed"),
    ({"mode": "frozen_sampled", "schedule": {"kind": "sample-then-hold", "settings": {"extra": 1}}},
     "unexpected settings"),
    ({"mode": "frozen_sampled", "schedule": {"kind": "sample-then-hold",
                                             "settings": {"coverage_target": 1.5}}},
     "coverage_target must be in"),
    ({"mode": "frozen_sampled", "schedule": {"kind": "sample-then-hold", "settings": {}}},
     "coverage_target"),
    ({"mode": "online_gated_v1", "online": {"n_steps": 2, "batch_size": 2, "target_kl": 0.02}},
     "target_kl must be null"),
    ({"mode": "online_sb3_v1", "online": {"n_steps": 4, "batch_size": 2}}, "exceeds the 2-decision"),
    ({"mode": "online_sb3_v1"}, "online settings are required"),
    ({"mode": "frozen_deterministic", "online": {"n_steps": 2, "batch_size": 2}}, "only valid for online"),
])
def test_operation_protocol_refusals(tmp_path, multi_run_config, operation, message):
    data = _matrix(multi_run_config)
    data["scenarios"]["scene"]["case"] = CASE
    data["evaluation"]["operations"] = [{"id": "op", "seed_role": "diagnostic",
                                         "at_steps": ["final"], **operation}]
    with pytest.raises(ValueError, match=message):
        _load(tmp_path, data)


def test_collisions_are_detected_before_writing(tmp_path, multi_run_config):
    plan = build_batch_plan(_load(tmp_path, _matrix(multi_run_config)), tmp_path / "root", None)
    tasks = plan["tasks"]
    with pytest.raises(ValueError, match="key collision"):
        check_collisions(tasks + [{**tasks[0], "id": "other", "output_dir": "/elsewhere"}])
    with pytest.raises(ValueError, match="output_dir collision"):
        check_collisions(tasks + [{**tasks[0], "id": "other", "key": "0" * 64}])
    nested = {**tasks[0], "id": "nested", "key": "1" * 64, "output_dir": tasks[0]["output_dir"] + "/x"}
    with pytest.raises(ValueError, match="nested"):
        check_collisions(tasks + [nested])
    assert not (tmp_path / "root").exists()




def test_v2_plan_is_immutable(tmp_path, multi_run_config, sim_binary):
    matrix = _load(tmp_path, _matrix(multi_run_config))
    root = tmp_path / "root"
    plan = build_batch_plan(matrix, root, sim_binary)
    first = write_batch_plan(plan, root).read_bytes()
    write_batch_plan(build_batch_plan(matrix, root, sim_binary), root)
    assert (root / PLAN_NAME).read_bytes() == first
    changed = _load(tmp_path, _mutate(_matrix(multi_run_config), ("seeds", "diagnostic"), [21]))
    with pytest.raises(ValueError, match="plans are immutable"):
        write_batch_plan(build_batch_plan(changed, root, sim_binary), root)
    assert (root / PLAN_NAME).read_bytes() == first


def _no_children(monkeypatch):
    """Fail the test if anything tries to launch a child process."""
    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected child process: {args[:1]}")
    monkeypatch.setattr(subprocess, "Popen", refuse)






def test_selection_stage_plans_every_branch(tmp_path, multi_run_config):
    data = _matrix(multi_run_config)
    data["evaluation"]["operations"] = [
        {"id": "screen", "mode": "online_sb3_v1", "seed_role": "diagnostic",
         "at_steps": ["final"], "online": {"n_steps": 2, "batch_size": 2}}]
    base = data["rows"][0]
    data["rows"] = [{**base, "name": n, "profile": p} for n, p in
                    (("screen-a", "a"), ("screen-b", "b"), ("main-a", "a"), ("main-b", "b"))]
    data["stages"] = [
        {"name": "screen", "rows": ["screen-a", "screen-b"],
         "selection": {"rule": "legacy-online-profile-v1", "source_operation": "screen",
                       "candidates": {"a": ["screen-a"], "b": ["screen-b"]},
                       "branches": {"a": ["main-a"], "b": ["main-b"]}}},
        {"name": "main", "rows": ["main-a", "main-b"], "needs": ["screen"]}]
    plan = build_batch_plan(_load(tmp_path, data))
    select = next(t for t in plan["tasks"] if t["kind"] == "select")
    assert len(select["needs"]) == 4 and select["handler"] == "select"
    main_trains = [t for t in plan["tasks"] if t["kind"] == "train" and t["row"].startswith("main")]
    assert {t["selection"]["branch"] for t in main_trains} == {"a", "b"}
    assert all("select/screen" in t["needs"] for t in main_trains)
    held = _mutate(data, ("evaluation", "operations", 0, "seed_role"), "held_out")
    held["seeds"]["held_out"] = [31]
    with pytest.raises(ValueError, match="never consumes held-out"):
        _load(tmp_path, held)


def test_selection_rules_rank_and_block():
    def item(values, role="diagnostic", path="x"):
        return {"path": path, "sha256": "0" * 64, "seed_role": role, "values": values}
    receipt = selection.online_profile({"a": [item([0.5, 0.7])], "b": [item([0.6, 0.6])]},
                                       seed_role="diagnostic")
    assert receipt["selected"] == ["b"] and receipt["sample_counts"] == {"b": 2, "a": 2}
    mission = selection.mission_profile({"standard": [item([0.9, 0.9])], "wider": [item([0.1, 0.3])],
                                         "deeper": [item([0.1, 0.3])]},
                                        retain=["standard"], seed_role="diagnostic")
    assert mission["selected"] == ["deeper", "standard"]
    with pytest.raises(ValueError, match="never consumes"):
        selection.online_profile({"a": [item([1, 2], "held_out")]}, seed_role="held_out")
    with pytest.raises(ValueError, match="missing scores"):
        selection.online_profile({"a": [item([1, None])], "b": [item([1, 2])]}, seed_role="diagnostic")
    validation = selection.validation_profile(
        {"a": [{"path": "p", "sha256": "1", "seed_role": "model_selection", "best_mean_reward": 60,
                "checkpoint_means": [1, 2, 3, 4]}],
         "b": [{"path": "q", "sha256": "2", "seed_role": "model_selection", "best_mean_reward": 60,
                "checkpoint_means": [3, 3, 3]}]}, normalization_decisions=600)
    assert validation["selected"] == ["b"] and validation["ranking"][0]["checkpoint_std_mean"] == 0
    replay = selection.select({"rule": "replay", "candidates": {"a": [], "b": []},
                               "branches": {"a": ["x"], "b": ["y"]},
                               "settings": {"winners": ["a"], "provenance": "recorded"}}, {})
    assert replay["replay"] and replay["selected_branches"] == ["x"] and replay["skipped_branches"] == ["y"]


def test_public_example_validates_and_plans(tmp_path, sim_binary):
    from scripts.baselines.config import load_baseline
    from scripts.rl.env.config import (read_episode_output, read_jammer_onsets,
                                       read_manifest_every_decisions, read_scenario_identity)
    from scripts.rl.env.recording.settings import resolve_decision_records
    run_ini = str(EXAMPLE / "run.ini")
    assert native_decisions(run_ini) == 64
    assert read_scenario_identity(run_ini)["buildings_json_sha256"]
    assert read_manifest_every_decisions(run_ini) == 64
    assert read_episode_output(run_ini)["compact_training"] is False
    assert read_jammer_onsets(run_ini) == ((), ())
    assert not resolve_decision_records().enabled
    load_baseline(run_ini)

    matrix = load_matrix_v2(EXAMPLE / "batch.json")
    row = matrix["rows"][0]
    assert row["decisions_per_episode"] == 64 and row["retained_checkpoints"] == [128, 256]
    assert row["training"]["total_timesteps"] // row["training"]["n_steps"] == 8
    plan = build_batch_plan(matrix, tmp_path / "root", sim_binary)
    kinds = [t["kind"] for t in plan["tasks"]]
    assert kinds.count("operate") == 16 and kinds.count("baseline") == 6
    assert kinds.count("train") == 1 and kinds.count("replay_gate") == 1
    assert "preflight" not in kinds and len(kinds) == 27
    for task in plan["tasks"]:
        if task["kind"] == "operate" or task["identity"]["policy"] == "scripted":
            args = task["args"]
            assert args[args.index("--mission") + 1] == "coverage"
            assert args[args.index("--coverage-target") + 1] == "0.8"
        elif task["kind"] == "baseline":
            assert "--mission" not in task["args"]
    replay = next(t for t in plan["tasks"] if t["kind"] == "replay_gate")
    assert any(arg.startswith("{accepted_dir:baseline/") for arg in replay["args"])
    assert not (tmp_path / "root").exists()


def _fake_root(tmp_path: Path) -> tuple[Path, Path]:
    """Mesh-shaped root whose .venv python only records its argv and cwd."""
    root = tmp_path / "fake mesh"
    (root / "scripts/rl").mkdir(parents=True)
    (root / "sim.cc").write_text("")
    record = tmp_path / "argv.json"
    python = root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(f'#!{sys.executable}\nimport json, os, sys\n'
                      f'json.dump({{"argv": sys.argv[1:], "cwd": os.getcwd(), '
                      f'"bin": os.environ.get("MESH_SIM_BIN")}}, open({str(record)!r}, "w"))\n'
                      'sys.exit(7)\n')
    python.chmod(0o755)
    return root, record






def test_gated_and_scheduled_operations_need_a_case_mission(tmp_path, multi_run_config):
    for operation in ({"mode": "online_gated_v1", "online": {"n_steps": 2, "batch_size": 2}},
                      {"mode": "frozen_sampled", "schedule": {
                          "kind": "initial-sampling", "settings": {"initial_sample_decisions": 1}}}):
        data = _matrix(multi_run_config)
        data["evaluation"]["operations"] = [{"id": "op", "seed_role": "diagnostic",
                                             "at_steps": ["final"], **operation}]
        with pytest.raises(ValueError, match="needs scenarios.scene.case.mission"):
            _load(tmp_path, data)
        data["scenarios"]["scene"]["case"] = {**CASE, "coverage_target": 0.7}
        plan = build_batch_plan(_load(tmp_path, data))
        args = next(t for t in plan["tasks"] if t["kind"] == "operate")["args"]
        assert args[args.index("--mission") + 1] == "coverage"
        assert args[args.index("--coverage-target") + 1] == "0.7"
    data["evaluation"]["operations"][0]["schedule"] = {
        "kind": "sample-then-hold", "settings": {"coverage_target": 0.7}}
    data["scenarios"]["scene"]["case"] = dict(CASE)
    args = next(t for t in build_batch_plan(_load(tmp_path, data))["tasks"]
                if t["kind"] == "operate")["args"]
    assert args[args.index("--coverage-target") + 1] == "0.7"


def test_replay_gates_expand_one_task_per_seed(tmp_path, multi_run_config):
    data = _matrix(multi_run_config)
    data["scenarios"]["scene"]["baselines"] = {"policies": ["hold"], "seed_role": "diagnostic"}
    data["checks"] = [
        {"id": "replay", "kind": "replay_gate", "scenario": "scene", "seeds": [21, 22],
         "source": {"baseline": "hold"}}]
    plan = build_batch_plan(_load(tmp_path, data))
    gates = [t for t in plan["tasks"] if t["kind"] == "replay_gate"]
    assert [t["identity"]["seed"] for t in gates] == [21, 22]
    assert len({t["key"] for t in gates}) == 2
    for task in gates:
        seed = task["identity"]["seed"]
        args = task["args"]
        assert list(json.loads(args[args.index("--seed-configs-json") + 1])) == [str(seed)]
        source = f"baseline/scene/hold/diagnostic/seed-{seed}"
        assert args[args.index("--source") + 1] == "{accepted_dir:" + source + "}"
        assert source in task["needs"]
    train = next(t for t in plan["tasks"] if t["kind"] == "train")
    assert {t["id"] for t in gates} <= set(train["needs"])
    assert "preflight" not in describe_kinds(plan)
    data["checks"][0]["source"] = {"path": str(tmp_path)}
    with pytest.raises(ValueError, match="one episode for one seed"):
        _load(tmp_path, data)
    data["checks"][0]["source"] = {"baseline": "hold", "seed": 21}
    with pytest.raises(ValueError, match="single seed"):
        _load(tmp_path, data)


def describe_kinds(plan: dict) -> str:
    from scripts.rl.experiments.plan import describe_expansion
    return describe_expansion(plan)[1]


ROUTES_V2 = {"reference_version": 2, "description": "corrected", "reference_only": True,
             "radio_feasibility": "unverified_pending_user_run",
             "routes": {"node-b": [[90.0, 0.0, 10.0]], "node-c": []},
             "targets": {"node-b": [90, 0], "node-c": [97, 50]}}
WAYPOINTS = {"reference_version": 3, "description": "mission", "parallel": True,
             "start_after_failure": False, "start_below_delivery": 0.9, "start_after_s": 2.0,
             "node_order": ["node-c", "node-b"],
             "waypoints": {"node-b": [[90, 0], [90, 10]], "node-c": [[97, 40, 10.0]]}}


@pytest.mark.parametrize("kind,payload", [("scenario_routes_v1", ROUTES_V2),
                                          ("scenario_routes_v1", {**_drop(ROUTES_V2, ("targets",)),
                                                                  "reference_version": 2}),
                                          ("mission_waypoints_v1", WAYPOINTS),
                                          ("mission_waypoints_v1", _drop(WAYPOINTS, ("reference_version",)))])
def test_reference_formats_used_by_existing_readers_are_accepted(tmp_path, multi_run_config, kind, payload):
    (tmp_path / "reference.json").write_text(json.dumps(payload))
    data = _matrix(multi_run_config)
    data["scenarios"]["scene"]["reference"] = {"kind": kind, "path": str(tmp_path / "reference.json")}
    data["scenarios"]["scene"]["baselines"] = {"policies": ["scripted"], "seed_role": "diagnostic"}
    plan = build_batch_plan(_load(tmp_path, data))
    record = plan["scenarios"]["scene"]["reference"]
    assert record["kind"] == kind and record["version"] == payload.get("reference_version")


@pytest.mark.parametrize("kind,payload,message", [
    ("scenario_routes_v1", {**ROUTES_V2, "reference_version": 3}, "reference_version 1 or 2"),
    ("scenario_routes_v1", {**ROUTES_V2, "reference_version": 1}, "unknown keys"),
    ("scenario_routes_v1", {**ROUTES_V2, "targets": {"node-z": [1, 1]}}, "node ids"),
    ("scenario_routes_v1", {**ROUTES_V2, "targets": {"node-b": [1]}}, "invalid point"),
    ("scenario_routes_v1", {**ROUTES_V2, "routes": {"node-b": [[90, 0]]}}, "invalid point"),
    ("mission_waypoints_v1", {**WAYPOINTS, "speed": 3}, "unknown keys"),
    ("mission_waypoints_v1", {**WAYPOINTS, "parallel": "yes"}, "must be a boolean"),
    ("mission_waypoints_v1", {**WAYPOINTS, "start_below_delivery": 2}, r"\[0,1\]"),
    ("mission_waypoints_v1", {**WAYPOINTS, "node_order": ["node-a"]}, "node_order"),
    ("mission_waypoints_v1", {**WAYPOINTS, "waypoints": {"node-z": [[1, 1]]}, "node_order": []},
     "node ids"),
    ("mission_waypoints_v1", _drop(WAYPOINTS, ("start_after_failure",)), "must be a boolean"),
])
def test_malformed_references_are_refused(tmp_path, multi_run_config, kind, payload, message):
    (tmp_path / "reference.json").write_text(json.dumps(payload))
    data = _matrix(multi_run_config)
    data["scenarios"]["scene"]["reference"] = {"kind": kind, "path": str(tmp_path / "reference.json")}
    with pytest.raises(ValueError, match=message):
        _load(tmp_path, data)


def _scene_copy(directory: Path, run_config: str, marker: str) -> str:
    """Byte-distinct copy of the fake scenario (an INI comment differs)."""
    directory.mkdir(parents=True)
    source = Path(run_config)
    (directory / "run.ini").write_text(f"# {marker}\n" + source.read_text())
    (directory / "nodes.json").write_text((source.parent / "nodes.json").read_text())
    return str(directory / "run.ini")


def test_placement_baselines_record_planning_seed_and_settings(tmp_path, multi_run_config):
    data = _matrix(multi_run_config)
    data["scenarios"]["scene"]["baselines"] = {"policies": ["hold", "geometric", "optimization"],
                                               "seed_role": "diagnostic", "planning_seed": 401}
    plan = build_batch_plan(_load(tmp_path, data))
    by_policy = {t["identity"]["policy"]: t for t in plan["tasks"]
                 if t["kind"] == "baseline" and t["identity"]["seed"] == 21}
    for policy in ("geometric", "optimization"):
        task = by_policy[policy]
        args = task["args"]
        assert args[args.index("--planning-seed") + 1] == "401"
        for flag in ("--import-from", "--reference", "--mission", "--coverage-target",
                     "--allow-seed-overlap"):
            assert flag not in args
        assert task["planning"]["planning_seed"] == 401 and task["planning"]["planner_settings_sha256"]
    assert "--planning-seed" not in by_policy["hold"]["args"] and by_policy["hold"]["planning"] is None
    assert by_policy["geometric"]["identity"]["physical_digest"] != by_policy["hold"]["identity"]["physical_digest"]
    assert len({t["key"] for t in by_policy.values()}) == 3

    other = copy.deepcopy(data)
    other["scenarios"]["scene"]["baselines"]["planning_seed"] = 402
    moved = {t["identity"]["policy"]: t for t in build_batch_plan(_load(tmp_path, other))["tasks"]
             if t["kind"] == "baseline" and t["identity"]["seed"] == 21}
    assert moved["geometric"]["key"] != by_policy["geometric"]["key"]
    assert moved["hold"]["key"] == by_policy["hold"]["key"]

    overlap = _mutate(data, ("scenarios", "scene", "baselines", "planning_seed"), 21)
    with pytest.raises(ValueError, match="overlaps seeds.diagnostic"):
        _load(tmp_path, overlap)
    overlap["scenarios"]["scene"]["baselines"]["allow_seed_overlap"] = True
    allowed = build_batch_plan(_load(tmp_path, overlap))
    assert all("--allow-seed-overlap" in t["args"] for t in allowed["tasks"]
               if t["kind"] == "baseline" and t["identity"]["policy"] == "geometric")
    with pytest.raises(ValueError, match="planning_seed"):
        _load(tmp_path, _drop(data, ("scenarios", "scene", "baselines", "planning_seed")))
    with pytest.raises(ValueError, match="requires a placement policy"):
        _load(tmp_path, _mutate(data, ("scenarios", "scene", "baselines", "policies"), ["hold"]))

    parent = _parent_run(tmp_path / "imported", 8)
    (parent / "eval_manifest.json").write_text("{}")
    data["scenarios"]["scene"]["baselines"]["import_from"] = str(parent / "eval_manifest.json")
    imported = {t["identity"]["policy"]: t for t in build_batch_plan(_load(tmp_path, data))["tasks"]
                if t["kind"] == "baseline"}
    assert "--import-from" in imported["hold"]["args"]
    assert "--import-from" not in imported["geometric"]["args"]


def test_row_configs_keep_distinct_inis_distinct(tmp_path, multi_run_config):
    a201 = _scene_copy(tmp_path / "a201", multi_run_config, "row a 21")
    a202 = _scene_copy(tmp_path / "a202", multi_run_config, "row a 22")
    b201 = _scene_copy(tmp_path / "b201", multi_run_config, "row b 21")
    b202 = _scene_copy(tmp_path / "b202", multi_run_config, "row b 22")
    data = _matrix(multi_run_config)
    data["scenarios"]["scene"]["baselines"] = {"policies": ["hold"], "seed_role": "diagnostic"}
    row_a = {**data["rows"][0], "configs": {"diagnostic": {"21": a201, "22": a202}}}
    row_b = {**data["rows"][0], "name": "row-b", "configs": {"diagnostic": {"21": b201, "22": b202}}}
    data["rows"] = [row_a, row_b]
    plan = build_batch_plan(_load(tmp_path, data))
    operate = [t for t in plan["tasks"] if t["kind"] == "operate"]
    assert {t["config"]["path"] for t in operate} == {a201, a202, b201, b202}
    assert all(t["config"]["config_source"] == "row" for t in operate)
    baselines = [t for t in plan["tasks"] if t["kind"] == "baseline"]
    assert len(baselines) == 4 and len({t["key"] for t in baselines}) == 4
    assert {t["config"]["path"] for t in baselines} == {a201, a202, b201, b202}
    record = next(r for r in plan["rows"] if r["name"] == "row-b")
    assert record["configs"]["diagnostic"]["21"]["sha256"] == plan["inputs"][b201]["sha256"]

    data["rows"][1]["configs"] = copy.deepcopy(data["rows"][0]["configs"])
    shared = [t for t in build_batch_plan(_load(tmp_path, data))["tasks"] if t["kind"] == "baseline"]
    assert len(shared) == 2
    for bad, message in (({"training": {"7": a201}}, "match neither"),
                         ({"diagnostic": {"23": a201}}, "not declared diagnostic seeds")):
        data["rows"][1]["configs"] = bad
        with pytest.raises(ValueError, match=message):
            _load(tmp_path, data)


def test_checks_apply_across_scenarios_in_declared_order(tmp_path, multi_run_config):
    data = _matrix(multi_run_config)
    data["scenarios"]["other"] = {"run_config": multi_run_config}
    data["scenarios"]["scene"]["baselines"] = {"policies": ["hold"], "seed_role": "diagnostic"}
    data["rows"].append({**data["rows"][0], "name": "row-b", "scenario": "other"})
    data["checks"] = [
        {"id": "gate", "kind": "replay_gate", "scenario": "scene", "seeds": [21],
         "source": {"baseline": "hold"}, "applies_to": {"scenarios": ["scene", "other"]}},
        {"id": "physical", "kind": "replay_gate", "scenario": "scene", "seeds": [21],
         "source": {"baseline": "hold"}, "applies_to": {"rows": ["row-b"]}}]
    plan = build_batch_plan(_load(tmp_path, data))
    trains = {t["row"]: t for t in plan["tasks"] if t["kind"] == "train"}
    gate, physical = "check/scene/gate/seed-21", "check/scene/physical/seed-21"
    assert trains["row-b"]["needs"][:2] == [gate, physical]
    assert trains["row-a"]["needs"] == [gate]
    assert sum(t["kind"] == "replay_gate" for t in plan["tasks"]) == 2
    operate_b = [t for t in plan["tasks"] if t["kind"] == "operate" and t["row"] == "row-b"]
    assert all(t["needs"][1:3] == [gate, physical] for t in operate_b)
    for applies, message in (({"rows": ["nope"]}, "unknown rows/scenarios"),
                             ({"scenarios": ["elsewhere"]}, "unknown rows/scenarios"),
                             ({}, "must name rows and/or scenarios")):
        bad = copy.deepcopy(data)
        bad["checks"][0]["applies_to"] = applies
        with pytest.raises(ValueError, match=message):
            _load(tmp_path, bad)


def _operation_selection(multi_run_config):
    data = _matrix(multi_run_config, seeds={"training": [1], "diagnostic": [21, 22], "held_out": [31]})
    online = {"mode": "online_sb3_v1", "seed_role": "diagnostic", "at_steps": [4, "final"],
              "online": {"n_steps": 2, "batch_size": 2}}
    data["evaluation"]["operations"] = [
        {"id": "online-x", **online}, {"id": "online-y", **online},
        {"id": "held-x", "mode": "frozen_deterministic", "seed_role": "held_out", "at_steps": ["final"]},
        {"id": "held-y", "mode": "frozen_sampled", "seed_role": "held_out", "at_steps": ["final"]}]
    data["stages"] = [{"name": "screen", "rows": ["row-a"], "selection": {
        "rule": "legacy-online-profile-v1",
        "candidates": {"x": [{"row": "row-a", "operation": "online-x"}],
                       "y": [{"row": "row-a", "operation": "online-y"}]},
        "branches": {"x": [{"row": "row-a", "operation": "held-x"}],
                     "y": [{"row": "row-a", "operation": "held-y"}]}}}]
    return data


def test_operation_candidates_share_one_train_task_and_one_checkpoint(tmp_path, multi_run_config):
    data = _operation_selection(multi_run_config)
    plan = build_batch_plan(_load(tmp_path, data))
    assert sum(t["kind"] == "train" for t in plan["tasks"]) == 1
    select = next(t for t in plan["tasks"] if t["kind"] == "select")
    rule = select["selection_rule"]
    assert rule["form"] == "operations" and rule["source_kind"] == "operation"
    assert rule["source_checkpoint"] == "final" and len(select["needs"]) == 4
    assert all("/checkpoint-final/" in tid for tid in select["needs"])
    assert {c: len(ids) for c, ids in rule["sources"].items()} == {"x": 2, "y": 2}
    held = [t for t in plan["tasks"] if t["kind"] == "operate" and t["identity"]["operation"].startswith("held")]
    assert {t["selection"]["branch"] for t in held} == {"x", "y"}
    assert all("select/screen" in t["needs"] for t in held)
    online = [t for t in plan["tasks"] if t["kind"] == "operate" and t["identity"]["operation"].startswith("online")]
    assert all(t["selection"] is None for t in online)

    data["stages"][0]["selection"]["source_checkpoint"] = 4
    select = next(t for t in build_batch_plan(_load(tmp_path, data))["tasks"] if t["kind"] == "select")
    assert len(select["needs"]) == 4 and all("/checkpoint-4/" in tid for tid in select["needs"])

    refusals = [
        (("stages", 0, "selection", "source_checkpoint"), 6, "not an operated checkpoint"),
        (("stages", 0, "selection", "source_operation"), "online-x", "remove source_operation"),
        (("stages", 0, "selection", "candidates", "y"), ["row-a"], "mix rows"),
        (("stages", 0, "selection", "candidates", "y"), [{"row": "row-a", "operation": "nope"}],
         "does not declare operation"),
        (("stages", 0, "selection", "branches", "y"), ["row-a"], "candidates' form"),
        (("stages", 0, "selection", "candidates", "y"), [{"row": "row-a", "operation": "held-y"}],
         "held-out"),
        (("stages", 0, "selection", "branches", "y"), [{"row": "row-a", "operation": "online-x"}],
         "also a candidate"),
    ]
    for path, value, message in refusals:
        with pytest.raises(ValueError, match=message):
            _load(tmp_path, _mutate(data, path, value))


def test_row_candidates_source_only_the_declared_checkpoint(tmp_path, multi_run_config):
    data = _matrix(multi_run_config)
    data["evaluation"]["operations"] = [
        {"id": "screen", "mode": "online_sb3_v1", "seed_role": "diagnostic",
         "at_steps": [4, "final"], "online": {"n_steps": 2, "batch_size": 2}}]
    data["rows"] = [{**data["rows"][0], "name": n, "profile": n} for n in ("cand-a", "cand-b")]
    data["stages"] = [{"name": "screen", "rows": ["cand-a", "cand-b"], "selection": {
        "rule": "legacy-online-profile-v1", "source_operation": "screen",
        "candidates": {"a": ["cand-a"], "b": ["cand-b"]}}}]
    select = next(t for t in build_batch_plan(_load(tmp_path, data))["tasks"] if t["kind"] == "select")
    assert len(select["needs"]) == 4 and all("/checkpoint-final/" in t for t in select["needs"])
    data["stages"][0]["selection"]["source_checkpoint"] = 4
    select = next(t for t in build_batch_plan(_load(tmp_path, data))["tasks"] if t["kind"] == "select")
    assert all("/checkpoint-4/" in t for t in select["needs"]) and select["identity"]["checkpoint"] == "4"


def test_selection_receipt_records_declared_sample_counts():
    items = {"a": [{"path": "p", "sha256": "1", "seed_role": "diagnostic", "values": [1, 2], "samples": 6}],
             "b": [{"path": "q", "sha256": "2", "seed_role": "diagnostic", "values": [1, 3]}]}
    receipt = selection.online_profile(items, seed_role="diagnostic")
    assert {s["candidate"]: s["samples"] for s in receipt["sources"]} == {"a": 6, "b": 2}
    items["a"][0]["samples"] = 0
    with pytest.raises(ValueError, match="invalid samples"):
        selection.online_profile(items, seed_role="diagnostic")
    branches = selection.select({"rule": "replay", "candidates": {"x": [], "y": []},
                                 "branches": {"x": [{"row": "r", "operation": "o"}], "y": []},
                                 "settings": {"winners": ["x"], "provenance": "recorded"}}, {})
    assert branches["selected_branches"] == [{"row": "r", "operation": "o"}]


def test_row_training_configs_keep_key_101_per_row(tmp_path, multi_run_config):
    inis = {name: _scene_copy(tmp_path / name, multi_run_config, name) for name in ("ra", "rb")}
    data = _matrix(multi_run_config, seeds={"training": [101], "diagnostic": [201, 202]})
    data["rows"] = [{**data["rows"][0], "name": f"row-{n}", "training_config_key": 101,
                     "configs": {"training": {"101": inis[n]}}} for n in ("ra", "rb")]
    plan = build_batch_plan(_load(tmp_path, data))
    trains = {t["row"]: t for t in plan["tasks"] if t["kind"] == "train"}
    for name in ("ra", "rb"):
        task = trains[f"row-{name}"]
        assert task["config_lookup"]["key"] == "101" and task["config_lookup"]["ini"] == inis[name]
        assert task["config"] == {"path": inis[name], "sha256": plan["inputs"][inis[name]]["sha256"],
                                  "config_source": "row"}
        assert task["args"][task["args"].index("--run-config") + 1] == inis[name]
    # A09 form: key 101 resolves on the row while the PPO seed is 102.
    data["seeds"]["training"] = [102]
    a09 = build_batch_plan(_load(tmp_path, data))
    train = next(t for t in a09["tasks"] if t["kind"] == "train" and t["row"] == "row-ra")
    assert train["args"][train["args"].index("--seed") + 1] == "102"
    assert train["config_lookup"]["key"] == "101" and train["config"]["path"] == inis["ra"]
    data["rows"][0]["training_config_key"] = 103
    with pytest.raises(ValueError, match="training_config_key 103"):
        _load(tmp_path, data)
    evaluate = {"matrix_version": 2, "name": "ev", "kind": "evaluate",
                "scenarios": {"scene": {"run_config": multi_run_config}}, "seeds": {"held_out": [31]},
                "evaluation": {"operations": [{"id": "f", "mode": "frozen_deterministic",
                                               "seed_role": "held_out"}]},
                "rows": [{"name": "imported", "scenario": "scene",
                          "model_source": {"run_dir": str(_parent_run(tmp_path / "p", 8))},
                          "configs": {"training": {"101": inis["ra"]}}}]}
    with pytest.raises(ValueError, match="unknown keys"):
        _load(tmp_path, evaluate)


def test_scenario_scoped_baselines_run_once_per_seed(tmp_path, multi_run_config):
    inis = {n: _scene_copy(tmp_path / n, multi_run_config, n) for n in ("a21", "a22", "b21", "b22")}
    data = _matrix(multi_run_config)
    data["scenarios"]["scene"]["baselines"] = {"policies": ["hold", "random_valid"],
                                               "seed_role": "diagnostic", "configs_scope": "scenario"}
    data["rows"] = [{**data["rows"][0], "name": f"row-{x}",
                     "configs": {"diagnostic": {"21": inis[f"{x}21"], "22": inis[f"{x}22"]}}}
                    for x in ("a", "b")]
    data["scenarios"]["scene"]["baselines"]["seed_role"] = "diagnostic"
    data["checks"] = [{"id": "gate", "kind": "replay_gate", "scenario": "scene", "seeds": [21],
                       "source": {"baseline": "hold"}}]
    plan = build_batch_plan(_load(tmp_path, data))
    baselines = [t for t in plan["tasks"] if t["kind"] == "baseline"]
    assert len(baselines) == 4
    assert {t["config"]["path"] for t in baselines} == {multi_run_config}
    assert all("/config-" not in t["id"] for t in baselines)
    gate = next(t for t in plan["tasks"] if t["kind"] == "replay_gate")
    assert "baseline/scene/hold/diagnostic/seed-21" in gate["needs"]
    data["scenarios"]["scene"]["baselines"]["configs_scope"] = "rows"
    assert sum(t["kind"] == "baseline" for t in build_batch_plan(_load(tmp_path, data))["tasks"]) == 12
    data["scenarios"]["scene"]["baselines"]["configs_scope"] = "everywhere"
    with pytest.raises(ValueError, match="configs_scope"):
        _load(tmp_path, data)


def test_curriculum_beside_the_matrix_is_hashed(tmp_path, multi_run_config):
    folder = tmp_path / "campaign"
    folder.mkdir()
    (folder / "curriculum-row-a-v2.json").write_text(json.dumps({"stages": []}))
    data = _matrix(multi_run_config)
    data["rows"][0]["curriculum"] = "curriculum-row-a-v2.json"
    plan = build_batch_plan(load_matrix_v2(_write(folder, data)))
    train = next(t for t in plan["tasks"] if t["kind"] == "train")
    path = str(folder / "curriculum-row-a-v2.json")
    assert train["args"][-2:] == ["--curriculum-schedule", path]
    assert plan["inputs"][path]["kind"] == "curriculum"


def test_decision_record_seeds_restrict_emission(tmp_path, multi_run_config):
    data = _matrix(multi_run_config)
    op = data["evaluation"]["operations"][0]
    op["decision_records"] = True
    every = build_batch_plan(_load(tmp_path, data))
    assert all("--decision-records" in t["args"] for t in every["tasks"] if t["kind"] == "operate")
    op["decision_record_seeds"] = [22]
    some = build_batch_plan(_load(tmp_path, data))
    flagged = {t["identity"]["seed"]: "--decision-records" in t["args"]
               for t in some["tasks"] if t["kind"] == "operate"}
    assert flagged == {21: False, 22: True}
    assert ({t["identity"]["operation_digest"] for t in some["tasks"] if t["kind"] == "operate"}
            != {t["identity"]["operation_digest"] for t in every["tasks"] if t["kind"] == "operate"})
    for bad, message in (({"decision_record_seeds": [23]}, "not diagnostic seeds"),
                         ({"decision_records": False}, "requires decision_records")):
        with pytest.raises(ValueError, match=message):
            _load(tmp_path, _mutate(data, ("evaluation", "operations", 0), {**op, **bad}))


def test_baseline_decision_record_seeds_restrict_emission(tmp_path, multi_run_config):
    data = _matrix(multi_run_config)
    data["scenarios"]["scene"]["baselines"] = {"policies": ["hold"], "seed_role": "diagnostic"}
    plain = {t["identity"]["seed"]: t for t in build_batch_plan(_load(tmp_path, data))["tasks"]
             if t["kind"] == "baseline"}
    data["scenarios"]["scene"]["baselines"]["decision_records"] = True
    every = {t["identity"]["seed"]: t for t in build_batch_plan(_load(tmp_path, data))["tasks"]
             if t["kind"] == "baseline"}
    assert all("--decision-records" in t["args"] for t in every.values())
    assert {s: t["key"] for s, t in every.items()} == {s: t["key"] for s, t in plain.items()}
    data["scenarios"]["scene"]["baselines"]["decision_record_seeds"] = [21]
    some = {t["identity"]["seed"]: t for t in build_batch_plan(_load(tmp_path, data))["tasks"]
            if t["kind"] == "baseline"}
    assert {s: "--decision-records" in t["args"] for s, t in some.items()} == {21: True, 22: False}
    assert some[21]["key"] != every[21]["key"]
    for bad, message in (({"decision_record_seeds": [23]}, "not diagnostic seeds"),
                         ({"decision_records": False}, "requires decision_records"),
                         ({"decision_record_seeds": []}, "at least one seed")):
        with pytest.raises(ValueError, match=message):
            _load(tmp_path, _mutate(data, ("scenarios", "scene", "baselines"),
                                    {**data["scenarios"]["scene"]["baselines"], **bad}))


def test_replay_contract_parent_case_and_comparison_affect_plan(tmp_path, multi_run_config):
    parent = _parent_run(tmp_path / "parent", 8, run_ini=multi_run_config)
    data = _matrix(multi_run_config)
    data["scenarios"]["scene"]["case"] = CASE
    data["checks"] = [{"id": "gate", "kind": "replay_gate", "scenario": "scene", "seeds": [21],
                       "source": {"path": str(tmp_path)}, "comparison": "pre_contact_source_v1",
                       "parent": {"run_dir": str(parent)}, "contact_audit": True}]
    plan = build_batch_plan(_load(tmp_path, data))
    gate = next(t for t in plan["tasks"] if t["kind"] == "replay_gate")
    args = gate["args"]
    assert args[args.index("--comparison") + 1] == "pre_contact_source_v1"
    assert args[args.index("--parent-run-dir") + 1] == str(parent)
    assert json.loads(args[args.index("--case-json") + 1])["mission"] == "coverage"
    assert "--contact-audit" in args and gate["identity"]["model_source"]
    assert plan["inputs"][str(parent / "maskable_ppo_mesh.zip")]["kind"] == "model"
    data["checks"][0]["comparison"] = "strict_v1"
    changed = next(t for t in build_batch_plan(_load(tmp_path, data))["tasks"] if t["kind"] == "replay_gate")
    assert changed["key"] != gate["key"]
    data["checks"][0]["comparison"] = "ignore-all"
    with pytest.raises(ValueError, match="comparison"):
        _load(tmp_path, data)


def test_preflight_refused_before_planning_or_launch(tmp_path, multi_run_config):
    data = _matrix(multi_run_config)
    data["checks"] = [{"id": "physical", "kind": "preflight", "scenario": "scene", "seeds": [21]}]
    with pytest.raises(ValueError, match="R6"):
        _load(tmp_path, data)


def test_standard_nonmission_budget_refuses_rollout_overshoot(tmp_path, multi_run_config):
    data = _matrix(multi_run_config)
    data["training"].update(total_timesteps=7, checkpoint_timing="standard")
    with pytest.raises(ValueError, match="overshoots"):
        _load(tmp_path, data)
    data["training"]["total_timesteps"] = 8
    assert _load(tmp_path, data)["rows"][0]["training"]["total_timesteps"] == 8
