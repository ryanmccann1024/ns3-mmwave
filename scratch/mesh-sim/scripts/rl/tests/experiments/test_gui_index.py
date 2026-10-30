"""Batch reporting on controlled fake leaves: index v4, reviews, curves, views and summaries.

Plans come from the public coordination-smoke example; every accepted attempt
is a small hand-written leaf (eval manifest v8, online manifest v5, bindings,
tiny model ZIPs). No simulator runs. The contract fixtures under
``tests/fixtures/`` are what these writers produce; set
``MESH_REGENERATE_BATCH_FIXTURES=1`` to rewrite them deliberately.
"""

import csv
import json
import os
import shutil
import zipfile
from pathlib import Path

import pytest

from scripts.artifact_io import sha256_file
from scripts.rl.experiments import reporting
from scripts.rl.experiments.config import load_matrix_v2
from scripts.rl.experiments.plan import build_batch_plan, write_batch_plan
from scripts.rl.policy import episode_review
from scripts.rl.policy.compare import build_comparison, load_evaluation

MESH = Path(__file__).resolve().parents[4]
EXAMPLE = MESH / "inputs/experiments/examples/coordination-smoke"
FIXTURES = MESH / "tests/fixtures"
INDEX_FIXTURE = FIXTURES / "batch_index_v4_example.json"
ONLINE_FIXTURE = FIXTURES / "batch_online_manifest_v5_example.json"
REGENERATE = os.environ.get("MESH_REGENERATE_BATCH_FIXTURES") == "1"
BATCH = "example-batch"
SCENE = "rural-coverage-3-peers"
T0, T1 = "2026-10-01T00:00:00+00:00", "2026-10-01T00:01:00+00:00"
METRIC_SOURCE = {"kind": "telemetry_window", "warmup_excluded": True}
SB3_FINAL_202 = (f"operate/{SCENE}/raw-delivery/train-seed-101/checkpoint-final/online-sb3/"
                 "diagnostic/seed-202")
PATH_KEYS = {"path", "attempt", "eval_manifest", "online_manifest", "weight_audit", "episode_dir",
             "inputs", "binding", "model_path", "run_dir", "train_manifest", "curves", "source",
             "comparison", "phase_comparison", "reward_summary", "batch_reward_summary", "plan"}


def _plan(tmp_path, sim_binary, name=BATCH, comparison=None):
    matrix_path = EXAMPLE / "batch.json"
    if comparison is not None:
        inputs = tmp_path / "inputs"
        shutil.copytree(EXAMPLE, inputs)
        data = json.loads((inputs / "batch.json").read_text())
        data["evaluation"]["comparison"] = comparison
        (inputs / "batch.json").write_text(json.dumps(data))
        matrix_path = inputs / "batch.json"
    matrix = load_matrix_v2(matrix_path)
    matrix["name"] = name
    root = tmp_path / name
    plan = build_batch_plan(matrix, root, sim_binary)
    write_batch_plan(plan, root)
    return plan, root


def _dir(plan, root, task):
    return root / Path(task["output_dir"]).relative_to(plan["output_root"])


def _task(plan, task_id):
    return next(t for t in plan["tasks"] if t["id"] == task_id)


def _identity(plan):
    record = plan["scenarios"][SCENE]["run_config"]
    return {"run_ini_sha256": record["sha256"], "nodes_json_sha256": record["nodes"]["sha256"],
            "buildings_json_sha256": record["buildings"]["sha256"], "jammers_json_sha256": None}


def _zip(path: Path, steps: int, updates: int) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in (("data", json.dumps({"num_timesteps": steps, "_n_updates": updates})),
                           ("policy.pth", b"policy"), ("policy.optimizer.pth", b"optimizer")):
            archive.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), data)
    return sha256_file(path)


def _train_episodes(attempt: Path, first: int, count: int, steps=64, seed=101):
    for index in range(first, first + count):
        folder = attempt / f"episode-{index:04}"
        folder.mkdir(parents=True)
        (folder / "rl_episode.json").write_text(json.dumps(
            {"status": "completed", "steps": steps, "seed": seed, "cumulative_reward": 0.25 * index}))


def _progress(attempt: Path, steps):
    (attempt / "ppo").mkdir(parents=True, exist_ok=True)
    lines = ["time/total_timesteps,train/loss"] + [f"{s},{s / 1000}" for s in steps]
    (attempt / "ppo/progress.csv").write_text("\n".join(lines) + "\n")


def _train_manifest(attempt: Path, plan, num_timesteps, status="completed", resume=None, checkpoints=()):
    final = attempt / "maskable_ppo_mesh.zip"
    manifest = {"manifest_version": 7, "status": status, "seed": 101, "control_mode": "centralized",
                "num_timesteps": num_timesteps, "scenario_identity": _identity(plan),
                "hyperparameters": {"total_timesteps": 256, "n_steps": 32, "batch_size": 16, "n_epochs": 2,
                                    "gamma": 0.99, "ent_coef": 0.0, "learning_rate": 0.0003,
                                    "eval_every_steps": 0, "eval_episodes": 1},
                "model_path": "maskable_ppo_mesh.zip" if final.is_file() else None,
                "model_sha256": sha256_file(final) if final.is_file() else None,
                "checkpoints": [{"path": f"checkpoints/{p.name}", "sha256": sha256_file(p),
                                 "num_timesteps": n} for p, n in checkpoints],
                "observation_schema": {"sha256": "o" * 64}, "reward_schema": {"sha256": "r" * 64},
                "resume": resume}
    (attempt / "train_manifest.json").write_text(json.dumps(manifest, indent=2))


def _write_trains(plan, root):
    """One completed fake training attempt per train task, plus the bindings its consumers declare."""
    accepted, shas = {}, {}
    for train in (t for t in plan["tasks"] if t["kind"] == "train"):
        attempt = _dir(plan, root, train) / "attempt-1"
        zips = {"128": (_zip(attempt / "checkpoints/checkpoint_128_steps.zip", 128, 8),
                        attempt / "checkpoints/checkpoint_128_steps.zip", 128, 8, "checkpoint"),
                "final": (_zip(attempt / "maskable_ppo_mesh.zip", 256, 16),
                          attempt / "maskable_ppo_mesh.zip", 256, 16, "final")}
        _zip(attempt / "checkpoints/checkpoint_256_steps.zip", 256, 16)
        _train_episodes(attempt, 1, 4)
        _progress(attempt, range(32, 257, 32))
        _train_manifest(attempt, plan, 256, checkpoints=[
            (attempt / "checkpoints/checkpoint_128_steps.zip", 128),
            (attempt / "checkpoints/checkpoint_256_steps.zip", 256)])
        accepted[train["id"]] = str(attempt)
        for task in plan["tasks"]:
            binding = task.get("binding")
            if task["kind"] != "operate" or not binding or binding["producer"] != train["id"] \
                    or (train["id"], binding["checkpoint"]) in shas:
                continue
            sha, model, steps, updates, selection = zips[binding["checkpoint"]]
            record = {"model_binding_version": 1, "run_dir": str(attempt), "model_selection": selection,
                      "model_path": str(model), "model_sha256": sha, "optimizer_sha256": "e" * 64,
                      "num_timesteps": steps, "n_updates": updates,
                      "train_manifest_path": str(attempt / "train_manifest.json"),
                      "train_manifest_sha256": sha256_file(attempt / "train_manifest.json")}
            (root / binding["path"]).parent.mkdir(parents=True, exist_ok=True)
            (root / binding["path"]).write_text(json.dumps(record))
            shas[(train["id"], binding["checkpoint"])] = (sha, steps, selection)
    return accepted, shas


def _metrics(value):
    return {"delivery_ratio": value, "worst_node_delivery_fraction": value, "post_jammer_delivery_ratio": None,
            "recovery_time_s": None, "coverage_fraction_mean": value, "unsafe_proximity_fraction": 0.0,
            "travel_m_total": 12.0, "displacement_m_final": 4.0, "connectivity": 1.0, "los_fraction": 0.5,
            "unroutable_fraction": 0.0, "first_all_los_decision": 3}


def _episode(seed, value, episode_dir):
    return {"seed": seed, "episode_dir": episode_dir, "status": "completed", "error": None, "exit_code": 0,
            "decisions": 64, "return": 1.5, "reward_components_sum": {"delivery_ratio": 1.5},
            "revalidated_slots_total": 0, "mask_violations": 0, "actions_sha256": "c" * 64,
            "metrics": _metrics(value), "summary_json": None, "initial_displacement_m_total": 0.0}


def _episode_folder(leaf: Path, seed: int, absolute: bool) -> str:
    folder = leaf / "episode-0001"
    (folder / "inputs").mkdir(parents=True)
    (folder / "inputs/run.ini").write_text("[scenario]\n")
    (folder / "steps.jsonl").write_text("{}\n")
    (folder / "rl_episode.json").write_text(json.dumps({"status": "completed", "steps": 64, "seed": seed}))
    return str(folder) if absolute else "episode-0001"


def _eval_manifest(plan, policy, seed, role, episode, model=None, metadata=None):
    block = {"episodes": [episode], "summary": {"expected_episodes": 1, "completed_episodes": 1}}
    if metadata:
        block["baseline"] = metadata
    return {"eval_manifest_version": 8, "status": "completed", "error": None, "label": f"{policy} seed {seed}",
            "started_at": T0, "ended_at": T1, "metric_source": METRIC_SOURCE,
            "seed_roles": {"role": role, "training_seed": 101 if model else None, "evaluation_seeds": [seed],
                           "held_out": role == "held_out"},
            "training": None if model is None else {
                "algorithm": "MaskablePPO", "seed": 101, "seed_source": "cli", "evaluation_seed": None,
                "evaluation_seeds": [], "evaluation_episodes": 1, "scenario_identity": _identity(plan),
                "hyperparameters": {"total_timesteps": 256, "n_steps": 32, "gamma": 0.99, "ent_coef": 0.0,
                                    "eval_every_steps": 0, "eval_episodes": 1}},
            "episodes_expected": 1, "episodes_completed": 1, "sim_binary": "fake-sim", "run_config": "run.ini",
            "band": "sub-6", "scenario_identity": _identity(plan), "contract": {"num_decisions": 64},
            "bundle": model, "compatibility": None,
            "selection": {"observation_preset": "raw_links_v1", "reward_components": ["delivery_ratio"],
                          "reward_weights": [1.0]},
            "observation_schema": {"sha256": "o" * 64}, "reward_schema": {"sha256": "r" * 64},
            "deterministic": metadata is not None and metadata.get("protocol") == "frozen_deterministic",
            "seeds": [seed], "seed_source": "eval", "policies": {policy: block}}


def _settings(protocol):
    if protocol == "online_gated_v1":
        return {"learning_rate": 0.0003, "gamma": 0.99, "gae_lambda": 0.95, "clip_range": 0.2,
                "ent_coef": 0.0, "n_epochs": 2, "target_kl": None, "n_steps": 16, "batch_size": 8,
                "eligible_only": True, "flush_final_partial": True}
    if protocol == "online_sb3_v1":
        return {"n_steps": 16, "batch_size": 8, "learning_rate": 0.0001, "target_kl": 0.02, "ent_coef": 0.001}
    return {}


def _accounting(protocol):
    if protocol == "online_gated_v1":
        return {"update_cycles": 4, "optimizer_steps": 16, "optimizer_epochs": 8, "episode_decisions": 64,
                "eligible_decisions": 64, "trained_decisions": 64, "excluded_prefix_decisions": 0,
                "untrained_tail_decisions": 0, "actor_change_l2": 0.01, "policy_parameters_changed": True,
                "optimizer_state_changed": True,
                "tail_policy": "final partial rollout flushed; a singleton tail is skipped",
                "weight_updates": "weight_updates.json"}
    if protocol == "online_sb3_v1":
        return {"update_cycles": 4, "optimizer_epochs": 8, "episode_budget": 64, "actual_decisions": 64,
                "untrained_tail_decisions": 0,
                "tail_policy": "budget % n_steps decisions after the last full rollout are not trained",
                "weight_updates": "weight_updates.json"}
    return {"update_cycles": 0, "optimizer_steps": 0, "untrained_tail_decisions": 0}


def _online_record(task, model_sha, steps, selection, value, eval_manifest):
    ident = task["identity"]
    protocol, online = ident["protocol"], ident["protocol"] in ("online_gated_v1", "online_sb3_v1")
    audit = {"initial_parameter_sha256": "p" * 64, "final_parameter_sha256": ("q" if online else "p") * 64,
             "initial_optimizer_sha256": "e" * 64, "final_optimizer_sha256": ("f" if online else "e") * 64,
             **_accounting(protocol)}
    return {"online_experiment_version": 5, "protocol": protocol, "status": "completed", "started_at": T0,
            "ended_at": T1, "error": None, "label": None, "seed": ident["seed"], "seed_role": ident["seed_role"],
            "evaluation_seeds": [ident["seed"]], "settings": _settings(protocol), "schedule": None,
            "allow_different_scenario": False,
            "parent": {"run_dir": "models/<scenario>/<row>/train/train-seed-101/attempt-1",
                       "model_selection": selection, "model_path": "<bound model>", "model_sha256": model_sha,
                       "num_timesteps": steps, "train_manifest_sha256": "t" * 64},
            "run_config": "<run.ini>", "scenario_identity": {"run_ini_sha256": "s" * 64},
            "binary_sha256": "b" * 64,
            "model": {"initial_parameter_sha256": "p" * 64, "final_parameter_sha256": audit["final_parameter_sha256"],
                      "adapted_model": "adapted_model.zip" if online else None,
                      "adapted_model_sha256": "a" * 64 if online else None},
            "optimizer": {"initial_optimizer_sha256": "e" * 64,
                          "final_optimizer_sha256": audit["final_optimizer_sha256"]},
            "accounting": _accounting(protocol),
            "evaluation": {"eval_manifest": eval_manifest, "episode_dir": "episode-0001", "decisions": 64,
                           "weight_audit": "weight_audit.json",
                           "steps_sha256": "2b4e7e1a1e1fbb6b1b8e8a2b46a6b0a1c4f1c1d7c6f3bc8b7a4c5d6e7f8091a2"},
            "episodes": [{"mode": protocol, "seed": ident["seed"], "episode_dir": "episode-0001", "decisions": 64,
                          "metrics": _metrics(value), "return": 1.5, **audit}]}


def _write_operate(plan, root, task, shas, value=0.8, absolute=False):
    ident = task["identity"]
    leaf = _dir(plan, root, task) / "attempt-1"
    episode_dir = _episode_folder(leaf, ident["seed"], absolute)
    sha, steps, selection = shas[(task["binding"]["producer"], ident["checkpoint"])]
    protocol = ident["protocol"]
    has_eval = protocol != "online_sb3_v1"
    if has_eval:
        bundle = {"run_dir": "<train attempt>", "model_selection": selection, "model_path": "<bound model>",
                  "model_sha256": sha, "num_timesteps": steps, "train_manifest_sha256": "t" * 64}
        metadata = {"weights_frozen": protocol != "online_gated_v1", "protocol": protocol,
                    "model_selection": selection, "execution_schedule": None}
        manifest = _eval_manifest(plan, "model", ident["seed"], ident["seed_role"],
                                  _episode(ident["seed"], value, episode_dir), bundle, metadata)
        (leaf / "eval_manifest.json").write_text(json.dumps(manifest, indent=2))
    if protocol != "frozen_deterministic":
        record = _online_record(task, sha, steps, selection, value, "eval_manifest.json" if has_eval else None)
        (leaf / "online_manifest.json").write_text(json.dumps(record, indent=2))
    (leaf / "weight_audit.json").write_text(json.dumps({"initial_parameter_sha256": "p" * 64}))
    return leaf


def _write_baseline(plan, root, task, value=0.5):
    ident = task["identity"]
    leaf = _dir(plan, root, task) / "attempt-1"
    episode_dir = _episode_folder(leaf, ident["seed"], False)
    metadata = {"fingerprint": "f" * 64} if ident["policy"] == "scripted" else None
    manifest = _eval_manifest(plan, ident["policy"], ident["seed"], ident["seed_role"],
                              _episode(ident["seed"], value, episode_dir), None, metadata)
    (leaf / "eval_manifest.json").write_text(json.dumps(manifest, indent=2))
    return leaf


def _review_stub(directory):
    return {"final_minute_coverage": 0.5, "final_minute_survivor_delivery": None, "unsafe_fraction": 0.0,
            "travel_m_total": 3.0}


def _leaves(plan, root, skip=(), values=None, absolute=False, baselines=True):
    accepted, shas = _write_trains(plan, root)
    for task in plan["tasks"]:
        if task["id"] in skip:
            continue
        if task["kind"] == "operate":
            value = (values or {}).get(task["id"], 0.8)
            accepted[task["id"]] = str(_write_operate(plan, root, task, shas, value, absolute))
        elif task["kind"] == "baseline" and baselines:
            accepted[task["id"]] = str(_write_baseline(plan, root, task))
    return accepted


def _pipeline(plan, root, monkeypatch, **kwargs):
    monkeypatch.setattr(episode_review, "review_metrics", _review_stub)
    accepted = _leaves(plan, root, **kwargs)
    for kind in ("curves", "review"):
        task = _task(plan, f"{kind}/{SCENE}")
        result = reporting.run_report_task(task, plan, root, accepted)
        accepted[task["id"]] = str(root / result["attempt_dir"])
    result = reporting.run_report_task(_task(plan, f"index/{SCENE}"), plan, root, accepted)
    return accepted, result, json.loads((root / "main" / SCENE / "mission_scenario.json").read_text())


def _check_paths(value, root, key=None):
    if isinstance(value, dict):
        for k, v in value.items():
            _check_paths(v, root, k)
    elif isinstance(value, list):
        for v in value:
            _check_paths(v, root, key)
    elif isinstance(value, str):
        assert not value.startswith("/") and "://" not in value, (key, value)
        if key in PATH_KEYS:
            reporting.check_relative(value)
            assert (root / value).exists(), (key, value)


def _fixture(path: Path, payload):
    if REGENERATE:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    assert json.loads(path.read_text()) == payload, f"{path.name} drifted from the writer; see module docstring"


def test_index_v4_fields_relative_paths_and_contract_fixtures(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary)
    accepted, result, index = _pipeline(plan, root, monkeypatch, skip={SB3_FINAL_202})
    assert reporting.MISSION_SCENARIO_VERSION == 4 and index["mission_scenario_version"] == 4
    assert index["batch"]["name"] == BATCH and index["scene"] == SCENE
    assert index["incomplete"] is True and result["incomplete"] is True
    assert index["missing"] == [SB3_FINAL_202]
    _check_paths(index, root)
    for key in ("case", "assets", "models", "baselines", "reports", "seeds", "validation_seeds"):
        assert key in index
    assert index["assets"]["run_config"]["run_config"]["path"].startswith(f"main/{SCENE}/assets/")
    assert index["assets"]["reference"]["kind"] == "scenario_routes_v1"
    model = index["models"][0]
    for key in ("row", "profile", "training_seed", "checkpoint", "selection", "ppo", "schemas", "model",
                "training", "evaluations", "reward_label"):
        assert key in model
    assert model["model"]["status"] == "bound" and model["model"]["binding"].startswith("state/bindings/")
    refs = [r for m in index["models"] for r in m["evaluations"]]
    assert len(refs) == 16 and {r["protocol"] for r in refs} == {
        "frozen_deterministic", "frozen_sampled", "online_gated_v1", "online_sb3_v1"}
    missing = [r for r in refs if r["status"] == "missing"]
    assert [r["task"] for r in missing] == [SB3_FINAL_202] and missing[0]["attempt"] is None
    sb3 = next(r for r in refs if r["protocol"] == "online_sb3_v1" and r["status"] == "complete")
    assert sb3["eval_manifest"] is None and sb3["online_manifest"].endswith("/online_manifest.json")
    det = next(r for r in refs if r["protocol"] == "frozen_deterministic")
    assert det["online_manifest"] is None and det["eval_manifest"].endswith("/eval_manifest.json")
    assert all(e["inputs"] for r in refs if r["status"] == "complete" for e in r["episodes"])
    assert len(index["baselines"]) == 3 and all(len(b["evaluations"]) == 2 for b in index["baselines"])
    assert index["reports"]["mission_review"]["path"] == f"main/{SCENE}/mission_review.json"
    assert index["reports"]["curves"][0]["curves"].endswith("/training_curves.csv")
    for path in root.rglob("mission_scenario.json"):
        assert json.loads(path.read_text())["mission_scenario_version"] == 4
    assert all(reporting.check_relative(p) for p in result["outputs"])

    _fixture(INDEX_FIXTURE, index)
    gated = _task(plan, f"operate/{SCENE}/raw-delivery/train-seed-101/checkpoint-final/online-gated/"
                        "diagnostic/seed-201")
    _fixture(ONLINE_FIXTURE, json.loads((Path(accepted[gated["id"]]) / "online_manifest.json").read_text()))


def test_arbitrary_batch_name_complete_index(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary, name="zz-any-name-7")
    _, result, index = _pipeline(plan, root, monkeypatch)
    assert index["batch"]["name"] == "zz-any-name-7"
    assert index["incomplete"] is False and index["missing"] == [] and index["issues"] == []
    refs = [r for m in index["models"] for r in m["evaluations"]] + \
        [r for b in index["baselines"] for r in b["evaluations"]]
    assert refs and all(r["status"] == "complete" and not r["issues"] for r in refs)
    assert result["incomplete"] is False
    _check_paths(index, root)


def test_missing_leaves_label_index_incomplete(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary)
    _, _, index = _pipeline(plan, root, monkeypatch, baselines=False)
    assert index["incomplete"] is True
    baseline_ids = sorted(t["id"] for t in plan["tasks"] if t["kind"] == "baseline")
    assert index["missing"] == baseline_ids
    for entry in index["baselines"]:
        assert all(r["status"] == "missing" and r["eval_manifest"] is None for r in entry["evaluations"])


def test_skipped_selection_is_not_counted_missing(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary)
    monkeypatch.setattr(episode_review, "review_metrics", _review_stub)
    accepted = _leaves(plan, root, skip={SB3_FINAL_202})
    task = _task(plan, f"index/{SCENE}")
    reporting.run_report_task(task, plan, root, accepted, skipped={SB3_FINAL_202})
    index = json.loads((root / "main" / SCENE / "mission_scenario.json").read_text())
    assert SB3_FINAL_202 not in index["missing"]
    ref = next(r for m in index["models"] for r in m["evaluations"] if r["task"] == SB3_FINAL_202)
    assert ref["status"] == "skipped_selection"


def test_groups_agree_only_on_full_identity(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary)
    _, _, index = _pipeline(plan, root, monkeypatch)
    refs = {(r["operation"], m["checkpoint"], r["seed"]): r for m in index["models"] for r in m["evaluations"]}
    assert refs[("frozen-deterministic", "128", 201)]["group"] == refs[("frozen-deterministic", "128", 202)]["group"]
    distinct = {refs[(op, ckpt, 201)]["group"] for op in ("frozen-deterministic", "frozen-sampled",
                                                           "online-gated", "online-sb3") for ckpt in ("128", "final")}
    assert len(distinct) == 8
    assert refs[("frozen-deterministic", "128", 201)]["model_sha256"] != \
        refs[("frozen-deterministic", "final", 201)]["model_sha256"]
    baselines = {b["policy"]: b["evaluations"] for b in index["baselines"]}
    assert baselines["hold"][0]["group"] == baselines["hold"][1]["group"] != baselines["scripted"][0]["group"]


def test_recorded_model_digest_mismatch_is_incomplete(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary)
    monkeypatch.setattr(episode_review, "review_metrics", _review_stub)
    accepted = _leaves(plan, root)
    task_id = f"operate/{SCENE}/raw-delivery/train-seed-101/checkpoint-128/frozen-deterministic/diagnostic/seed-201"
    path = Path(accepted[task_id]) / "eval_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["bundle"]["model_sha256"] = "9" * 64
    path.write_text(json.dumps(manifest))
    reporting.run_report_task(_task(plan, f"index/{SCENE}"), plan, root, accepted)
    index = json.loads((root / "main" / SCENE / "mission_scenario.json").read_text())
    ref = next(r for m in index["models"] for r in m["evaluations"] if r["task"] == task_id)
    assert ref["status"] == "incomplete" and "differs from the bound model" in ref["issues"][0]
    assert index["incomplete"] is True


def test_reward_summary_keeps_campaign_meanings_and_nulls(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary)
    nulls = {t["id"]: None for t in plan["tasks"] if t["kind"] == "operate"
             and t["identity"]["operation"] == "frozen-sampled" and t["identity"]["checkpoint"] == "final"}
    half = {f"operate/{SCENE}/raw-delivery/train-seed-101/checkpoint-128/frozen-deterministic/"
            "diagnostic/seed-202": 0.4}
    _pipeline(plan, root, monkeypatch, values={**nulls, **half})
    with (root / "main" / SCENE / reporting.REWARD_SUMMARY_CSV).open() as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames) == reporting.REWARD_SUMMARY_FIELDS
        assert reader.fieldnames[:13] == ["scenario", "reward", "training_seed", "policy", "completed_episodes",
                                          *reporting.REWARD_SUMMARY_METRICS]
        rows = list(reader)
    sampled = next(r for r in rows if r["operation"] == "frozen-sampled" and r["checkpoint"] == "final")
    assert sampled["delivery_ratio"] == "" and sampled["completed_episodes"] == "2"
    data = json.loads((root / "main" / SCENE / reporting.REWARD_SUMMARY_JSON).read_text())
    row = next(r for r in data["rows"] if r["operation"] == "frozen-sampled" and r["checkpoint"] == "final")
    assert row["delivery_ratio"] is None and row["post_jammer_delivery_ratio"] is None
    det = next(r for r in data["rows"] if r["operation"] == "frozen-deterministic" and r["checkpoint"] == "128")
    assert det["delivery_ratio"] == pytest.approx(0.6) and det["evaluation_seeds"] == [201, 202]
    assert len(det["sources"]) == 2 and all(reporting.check_relative(s["manifest"]) for s in det["sources"])
    hold = next(r for r in data["rows"] if r["policy"] == "hold")
    assert hold["reward"] is None and hold["training_seed"] is None and hold["delivery_ratio"] == 0.5
    assert "not ranked" in data["note"] and "rank" not in json.dumps(data["rows"])
    batch = json.loads((root / "main" / reporting.REWARD_SUMMARY_JSON).read_text())
    assert batch["scope"] == "batch" and batch["rows"] == data["rows"]
    assert batch["scenarios"][0]["path"] == f"main/{SCENE}/{reporting.REWARD_SUMMARY_JSON}"
    assert (root / "main" / reporting.REWARD_SUMMARY_CSV).is_file()


def test_review_is_v1_without_status_and_projected(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary)
    accepted, _, _ = _pipeline(plan, root, monkeypatch)
    source = Path(accepted[f"review/{SCENE}"]) / "mission_review.json"
    review = json.loads(source.read_text())
    assert set(review) == {"mission_review_version", "objective", "ranking_basis", "ranking", "episodes"}
    assert review["mission_review_version"] == 1 and review["objective"] == "coverage"
    assert len(review["ranking"]) == 2  # frozen deterministic, one per checkpoint; seeds pooled
    leaves = [t for t in plan["tasks"] if t["kind"] in ("operate", "baseline")]
    assert len(review["episodes"]) == len(leaves)
    assert all(not k.startswith("/") for k in review["episodes"])
    assert (root / "main" / SCENE / "mission_review.json").read_bytes() == source.read_bytes()


def test_main_rebuild_never_moves_or_changes_siblings(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary)
    accepted, _, _ = _pipeline(plan, root, monkeypatch)

    def snapshot():
        return {p.relative_to(root).as_posix(): sha256_file(p) for p in root.rglob("*")
                if p.is_file() and p.relative_to(root).parts[0] != "main"}
    before = snapshot()
    index_path = root / "main" / SCENE / "mission_scenario.json"
    first = index_path.read_bytes()
    reporting.run_report_task(_task(plan, f"index/{SCENE}"), plan, root, accepted)
    assert snapshot() == before and index_path.read_bytes() == first


def test_accepted_directory_must_belong_to_its_task(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary)
    accepted = _leaves(plan, root)
    operate = next(t for t in plan["tasks"] if t["kind"] == "operate")
    baseline = next(t for t in plan["tasks"] if t["kind"] == "baseline")
    accepted[operate["id"]] = accepted[baseline["id"]]
    with pytest.raises(ValueError, match="not inside that task's destination"):
        reporting.run_report_task(_task(plan, f"index/{SCENE}"), plan, root, accepted)
    with pytest.raises(ValueError, match="escapes|not a batch-relative"):
        reporting.check_relative("../outside")
    with pytest.raises(ValueError):
        reporting.check_relative("/abs/path")


def test_absolute_episode_dirs_become_relative(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary)
    _, _, index = _pipeline(plan, root, monkeypatch, absolute=True)
    _check_paths(index, root)
    det = next(r for m in index["models"] for r in m["evaluations"] if r["protocol"] == "frozen_deterministic")
    assert det["episodes"][0]["episode_dir"].startswith("operations/")


def _resumed_train(plan, root):
    train = _task(plan, f"train/{SCENE}/raw-delivery/train-seed-101")
    first = _dir(plan, root, train) / "attempt-1"
    checkpoint = first / "checkpoints/checkpoint_128_steps.zip"
    sha = _zip(checkpoint, 128, 8)
    _train_episodes(first, 1, 3)
    tail = first / "episode-0004"
    tail.mkdir()
    (tail / "rl_episode.json").write_text(json.dumps({"status": "interrupted", "steps": 10, "seed": 101}))
    _progress(first, range(32, 193, 32))
    _train_manifest(first, plan, 192, status="interrupted", checkpoints=[(checkpoint, 128)])
    second = _dir(plan, root, train) / "attempt-2"
    _zip(second / "maskable_ppo_mesh.zip", 256, 16)
    _train_episodes(second, 1, 2)
    _progress(second, range(160, 257, 32))
    parent = {"run_dir": str(first), "model_selection": "checkpoint", "model_path": str(checkpoint),
              "model_sha256": sha, "num_timesteps": 128,
              "train_manifest_sha256": sha256_file(first / "train_manifest.json")}
    _train_manifest(second, plan, 256, resume={"parent": parent, "restored_timesteps": 128,
                                               "target_timesteps": 256, "remaining_timesteps": 128})
    return train, first, second, checkpoint


def test_curves_follow_accepted_history_and_exclude_abandoned_tail(tmp_path, sim_binary):
    plan, root = _plan(tmp_path, sim_binary)
    train, first, second, _ = _resumed_train(plan, root)
    before = {p: sha256_file(p) for p in first.rglob("*") if p.is_file()}
    task = _task(plan, f"curves/{SCENE}")
    result = reporting.run_report_task(task, plan, root, {train["id"]: str(second)})
    assert result["incomplete"] is False
    attempt = root / result["attempt_dir"]
    folder = attempt / "raw-delivery/train-seed-101"
    with (folder / "training_curves.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert [int(r["total_episode"]) for r in rows] == [1, 2, 3, 4]
    assert [r["source"] for r in rows] == ["recovered", "recovered", "attempt", "attempt"]
    assert len({r["episode_dir"] for r in rows}) == 4
    assert rows[0]["episode_dir"].endswith("attempt-1/episode-0001")
    sources = json.loads((folder / "training_curve_sources.json").read_text())
    assert set(sources) == {"training_curve_version", "sources", "note"}
    assert sources["training_curve_version"] == reporting.TRAINING_CURVE_SOURCES_VERSION == 1
    parent, child = sources["sources"]
    assert "status" not in parent and "status" not in child
    assert parent["total_episodes"] == 2 and parent["complete_episodes_after_checkpoint_excluded"] == 1
    assert parent["selected_checkpoint"]["model_path"].endswith("checkpoint_128_steps.zip")
    assert not parent["selected_checkpoint"]["model_path"].startswith("/")
    assert child["restored_episodes"] == 2 and child["total_episodes"] == 4
    with (root / parent["ppo_progress"]).open() as handle:
        steps = [int(r["time/total_timesteps"]) for r in csv.DictReader(handle)]
    with (root / child["ppo_progress"]).open() as handle:
        steps += [int(r["time/total_timesteps"]) for r in csv.DictReader(handle)]
    assert steps == sorted(set(steps)) and max(steps[:4]) <= 128
    top = json.loads((attempt / "training_curve_sources.json").read_text())
    assert top["sources"] == sources["sources"]
    assert before == {p: sha256_file(p) for p in first.rglob("*") if p.is_file()}


def test_curves_refuse_changed_checkpoint_bytes(tmp_path, sim_binary):
    plan, root = _plan(tmp_path, sim_binary)
    train, _, second, checkpoint = _resumed_train(plan, root)
    _zip(checkpoint, 128, 9)
    with pytest.raises(ValueError, match="checkpoint bytes differ"):
        reporting.run_report_task(_task(plan, f"curves/{SCENE}"), plan, root, {train["id"]: str(second)})


def _compare_plan(tmp_path, sim_binary, allow_incomplete=False):
    plan, root = _plan(tmp_path, sim_binary, comparison={"operation": "frozen-deterministic",
                                                         "allow_incomplete": allow_incomplete})
    task = _task(plan, f"compare/{SCENE}/frozen-deterministic/checkpoint-128")
    return plan, root, task


def test_comparison_view_pools_seeds_for_compare(tmp_path, sim_binary):
    plan, root, task = _compare_plan(tmp_path, sim_binary)
    accepted = _leaves(plan, root)
    attempt = _dir(plan, root, task) / "attempt-1"
    dirs = reporting.build_comparison_view(task, plan, root, accepted, attempt_dir=attempt)
    assert dirs == [str(attempt.resolve() / "view" / "raw-delivery--train-seed-101")]
    evaluation = load_evaluation(dirs[0])
    assert evaluation.seeds == (201, 202)
    assert set(evaluation.records) == {"model", "hold", "random_valid", "scripted"}
    assert evaluation.label == "raw-delivery checkpoint-128 frozen-deterministic"
    comparison = build_comparison([evaluation])
    assert comparison["status"] == "complete"
    sources = json.loads((Path(dirs[0]) / reporting.VIEW_SOURCES).read_text())
    assert [s["role"] for s in sources["sources"]].count("model") == 2 and len(sources["sources"]) == 8
    assert all(not s["eval_manifest"].startswith("/") for s in sources["sources"])


def test_comparison_view_refuses_mixed_or_missing_inputs(tmp_path, sim_binary):
    plan, root, task = _compare_plan(tmp_path, sim_binary)
    accepted = _leaves(plan, root)
    seed_202 = next(i for i in task["view"]["sources"] if i.endswith("seed-202"))
    path = Path(accepted[seed_202]) / "eval_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["scenario_identity"]["run_ini_sha256"] = "0" * 64
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="refusing to pool .*scenario_identity"):
        reporting.build_comparison_view(task, plan, root, accepted)
    without = {k: v for k, v in accepted.items() if k != seed_202}
    with pytest.raises(ValueError, match="missing accepted evaluations"):
        reporting.build_comparison_view(task, plan, root, without)
    online = [t["id"] for t in plan["tasks"] if t["kind"] == "operate"
              and t["identity"]["operation"] == "online-sb3" and t["identity"]["checkpoint"] == "128"]
    task["view"].update(operation="online-sb3", sources=online)
    with pytest.raises(ValueError, match="writes no evaluation manifest"):
        reporting.build_comparison_view(task, plan, root, accepted)


def test_incomplete_view_is_explicit(tmp_path, sim_binary):
    plan, root, task = _compare_plan(tmp_path, sim_binary, allow_incomplete=True)
    accepted = _leaves(plan, root, values={i: None for i in task["view"]["sources"] if i.endswith("201")})
    seed_202 = next(i for i in task["view"]["sources"] if i.endswith("seed-202"))
    del accepted[seed_202]
    dirs = reporting.build_comparison_view(task, plan, root, accepted)
    evaluation = load_evaluation(dirs[0])
    assert evaluation.manifest["status"] == "partial" and evaluation.seeds == (201, 202)
    assert 202 not in evaluation.records["model"]
    assert evaluation.records["model"][201]["metrics"]["delivery_ratio"] is None
    assert build_comparison([evaluation])["status"] == "incomplete"


def test_scheduler_record_forms_are_accepted(tmp_path, sim_binary, monkeypatch):
    plan, root = _plan(tmp_path, sim_binary)
    monkeypatch.setattr(episode_review, "review_metrics", _review_stub)
    accepted = _leaves(plan, root, skip={SB3_FINAL_202})
    records = {t["id"]: {"state": "completed", "attempt_dir": accepted[t["id"]]} if t["id"] in accepted
               else {"state": "skipped_selection" if t["id"] == SB3_FINAL_202 else "pending",
                     "attempt_dir": None} for t in plan["tasks"]}
    task = _task(plan, f"review/{SCENE}")
    attempt = _dir(plan, root, task) / "attempt-3"
    attempt.mkdir(parents=True)
    result = reporting.run_report_task({**task, "attempt_dir": str(attempt)}, plan, str(root), records)
    assert result["attempt_dir"].endswith("/attempt-3") and result["incomplete"] is False
    reporting.run_report_task(_task(plan, f"index/{SCENE}"), plan, str(root), records)
    index = json.loads((root / "main" / SCENE / "mission_scenario.json").read_text())
    assert SB3_FINAL_202 not in index["missing"]
    assert f"review/{SCENE}" in index["missing"]  # still pending in this record set


def _stage_plan(tmp_path, sim_binary, rule):
    inputs = tmp_path / "inputs"
    shutil.copytree(EXAMPLE, inputs)
    data = json.loads((inputs / "batch.json").read_text())
    base = data["rows"][0]
    data["rows"] = [{**base, "name": n, "profile": p} for n, p in
                    (("screen-a", "a"), ("screen-b", "b"), ("main-a", "a"), ("main-b", "b"))]
    for op in data["evaluation"]["operations"]:
        op["at_steps"] = ["final"]
    selection = {"rule": rule, "candidates": {"a": ["screen-a"], "b": ["screen-b"]},
                 "branches": {"a": ["main-a"], "b": ["main-b"]}}
    if rule == "legacy-validation-profile-v1":
        data["seeds"]["model_selection"] = [301]
        data["training"].update(eval_every_steps=128, checkpoint_timing="standard")
        data["execution"]["recovery"] = "none"
        selection["normalization_decisions"] = 64
    elif rule == "replay":
        selection.update(winners=["b"], provenance="recorded winner of an earlier screen")
    else:
        selection["source_operation"] = ("online-sb3" if rule == "legacy-online-profile-v1"
                                         else "frozen-deterministic")
    data["stages"] = [{"name": "screen", "rows": ["screen-a", "screen-b"], "selection": selection},
                      {"name": "main", "rows": ["main-a", "main-b"], "needs": ["screen"]}]
    (inputs / "batch.json").write_text(json.dumps(data))
    matrix = load_matrix_v2(inputs / "batch.json")
    root = tmp_path / BATCH
    plan = build_batch_plan(matrix, root, sim_binary)
    return plan, root, _task(plan, "select/screen")


def _score_leaves(plan, root, task, scores, monkeypatch):
    """Operation leaves for every declared source; mission scores keyed by episode directory."""
    from scripts.rl.policy import mission_metrics
    by_dir, accepted, shas = {}, {}, {}
    for candidate, ids in task["selection_rule"]["sources"].items():
        for index, source_id in enumerate(ids):
            source = _task(plan, source_id)
            binding = source["binding"]
            shas.setdefault((binding["producer"], binding["checkpoint"]), ("7" * 64, 256, "final"))
            leaf = _write_operate(plan, root, source, shas)
            accepted[source_id] = str(leaf)
            by_dir[str((leaf / "episode-0001").resolve())] = scores[candidate][index]
    monkeypatch.setattr(mission_metrics, "mission_episode_metrics",
                        lambda d: {"mission_score": by_dir[str(Path(d).resolve())]})
    return accepted


def test_selection_evidence_for_mission_rule_feeds_select(tmp_path, sim_binary, monkeypatch):
    from scripts.rl.experiments.selection import select
    plan, root, task = _stage_plan(tmp_path, sim_binary, "legacy-mission-profile-v1")
    accepted = _score_leaves(plan, root, task, {"a": [0.2, 0.4], "b": [0.9, 0.7]}, monkeypatch)
    evidence = reporting.selection_evidence(task, plan, str(root), accepted)
    assert set(evidence) == {"a", "b"} and all(len(items) == 2 for items in evidence.values())
    item = evidence["b"][0]
    assert item["task"] in task["selection_rule"]["sources"]["b"] and item["seed_role"] == "diagnostic"
    assert item["path"].endswith("/eval_manifest.json") and item["attempt"].endswith("/attempt-1")
    assert item["sha256"] == sha256_file(root / item["path"]) and item["samples"] == 1
    assert item["values"] == [0.9] and item["case"] == SCENE
    receipt = select({**task["selection_rule"], "settings": {"retain": []}}, evidence)
    assert receipt["selected"] == ["b"] and receipt["selected_branches"] == ["main-b"]
    assert receipt["held_out_seeds_used"] is False and len(receipt["sources"]) == 4


def test_selection_evidence_online_rule_reads_online_episodes(tmp_path, sim_binary, monkeypatch):
    from scripts.rl.experiments.selection import select
    plan, root, task = _stage_plan(tmp_path, sim_binary, "legacy-online-profile-v1")
    accepted = _score_leaves(plan, root, task, {"a": [0.5, 0.6], "b": [0.1, 0.2]}, monkeypatch)
    evidence = reporting.selection_evidence(task, plan, str(root), accepted)
    assert all(i["path"].endswith("/online_manifest.json") for items in evidence.values() for i in items)
    assert select(task["selection_rule"], evidence)["selected"] == ["a"]


def test_selection_evidence_refuses_missing_and_held_out(tmp_path, sim_binary, monkeypatch):
    plan, root, task = _stage_plan(tmp_path, sim_binary, "legacy-mission-profile-v1")
    accepted = _score_leaves(plan, root, task, {"a": [0.2, 0.4], "b": [0.9, 0.7]}, monkeypatch)
    dropped = task["selection_rule"]["sources"]["a"][0]
    with pytest.raises(ValueError, match="selection blocked: .* has no accepted result"):
        reporting.selection_evidence(task, plan, str(root),
                                     {k: v for k, v in accepted.items() if k != dropped})
    source = _task(plan, dropped)
    source["identity"]["seed_role"] = "held_out"
    with pytest.raises(ValueError, match="never consumes 'held_out'"):
        reporting.selection_evidence(task, plan, str(root), accepted)


def test_selection_evidence_validation_and_replay(tmp_path, sim_binary):
    import numpy as np
    from scripts.rl.experiments.selection import select
    plan, root, task = _stage_plan(tmp_path, sim_binary, "legacy-validation-profile-v1")
    accepted = {}
    for candidate, best in (("a", 32.0), ("b", 48.0)):
        (source_id,) = task["selection_rule"]["sources"][candidate]
        attempt = _dir(plan, root, _task(plan, source_id)) / "attempt-1"
        attempt.mkdir(parents=True)
        (attempt / "train_manifest.json").write_text(json.dumps(
            {"status": "completed", "best_mean_reward": best, "evaluation": {"seeds": [301]}}))
        np.savez(attempt / "evaluations.npz", results=np.array([[1.0, 3.0], [2.0, 2.0], [4.0, 6.0]]))
        accepted[source_id] = str(attempt)
    evidence = reporting.selection_evidence(task, plan, str(root), accepted)
    item = evidence["b"][0]
    assert item["seed_role"] == "model_selection" and item["checkpoint_means"] == [2.0, 2.0, 5.0]
    assert item["path"].endswith("/train_manifest.json") and item["evaluations"].endswith("evaluations.npz")
    receipt = select(task["selection_rule"], evidence)
    assert receipt["selected"] == ["b"] and receipt["ranking"][0]["validation_mean_reward"] == 48.0 / 64
    plan["seeds"]["held_out"] = [301]
    with pytest.raises(ValueError, match="held-out"):
        reporting.selection_evidence(task, plan, str(root), accepted)

    replay_plan, replay_root, replay_task = _stage_plan(tmp_path / "r", sim_binary, "replay")
    assert reporting.selection_evidence(replay_task, replay_plan, str(replay_root), {}) == {}
    assert select(replay_task["selection_rule"], {})["selected"] == ["b"]


def _edited_plan(tmp_path, sim_binary, edit):
    inputs = tmp_path / "inputs"
    shutil.copytree(EXAMPLE, inputs)
    data = json.loads((inputs / "batch.json").read_text())
    edit(data, inputs)
    (inputs / "batch.json").write_text(json.dumps(data))
    root = tmp_path / BATCH
    plan = build_batch_plan(load_matrix_v2(inputs / "batch.json"), root, sim_binary)
    write_batch_plan(plan, root)
    return plan, root


def test_operation_candidates_feed_select_at_exact_checkpoint(tmp_path, sim_binary, monkeypatch):
    from scripts.rl.experiments.selection import select

    def edit(data, _):
        base = data["rows"][0]
        data["rows"] = [{**base, "name": n} for n in ("screen", "main")]
        data["stages"] = [
            {"name": "screen", "rows": ["screen"], "selection": {
                "rule": "legacy-mission-profile-v1", "source_checkpoint": "final",
                "candidates": {"det": [{"row": "screen", "operation": "frozen-deterministic"}],
                               "sam": [{"row": "screen", "operation": "frozen-sampled"}]},
                "branches": {"det": [{"row": "main", "operation": "frozen-deterministic"}],
                             "sam": [{"row": "main", "operation": "frozen-sampled"}]}}},
            {"name": "main", "rows": ["main"], "needs": ["screen"]}]
    plan, root = _edited_plan(tmp_path, sim_binary, edit)
    task = _task(plan, "select/screen")
    assert task["selection_rule"]["form"] == "operations" and task["selection_rule"]["source_kind"] == "operation"
    accepted = _score_leaves(plan, root, task, {"det": [0.3, 0.5], "sam": [0.8, 0.6]}, monkeypatch)
    evidence = reporting.selection_evidence(task, plan, str(root), accepted)
    items = [i for group in evidence.values() for i in group]
    assert len(items) == 4 and {i["checkpoint"] for i in items} == {"final"}
    assert {(i["row"], i["operation"]) for i in evidence["sam"]} == {("screen", "frozen-sampled")}
    receipt = select(task["selection_rule"], evidence)
    assert receipt["selected"] == ["sam"] and receipt["held_out_seeds_used"] is False
    # A source at another checkpoint is never a declared input.
    stray = next(t for t in plan["tasks"] if t["kind"] == "operate" and t["identity"]["checkpoint"] == "128")
    task["selection_rule"]["sources"]["det"].append(stray["id"])
    with pytest.raises(ValueError, match="not a declared input"):
        reporting.selection_evidence(task, plan, str(root), accepted)


def test_placement_baseline_entry_carries_planning(tmp_path, sim_binary, monkeypatch):
    def edit(data, _):
        data["scenarios"][SCENE]["baselines"] = {"policies": ["scripted", "hold", "geometric"],
                                                 "seed_role": "diagnostic", "planning_seed": 401}
    plan, root = _edited_plan(tmp_path, sim_binary, edit)
    mapping = tmp_path / "inputs" / "mapping.json"
    mapping.write_text('{"cells": []}')
    for task in plan["tasks"]:
        if task["kind"] == "baseline" and task["identity"]["policy"] == "geometric":
            task["planning"]["mapping_file"] = str(mapping)
    plan["inputs"][str(mapping.resolve())] = {"kind": "mapping", "sha256": sha256_file(mapping), "reference": None}
    _, _, index = _pipeline(plan, root, monkeypatch)
    entries = {e["policy"]: e for e in index["baselines"]}
    planning = entries["geometric"]["planning"]
    assert planning["planning_seed"] == 401 and planning["planner_settings_sha256"]
    assert planning["planning_seed_source"] is not None
    assert planning["mapping_file"]["sha256"] == sha256_file(mapping)
    assert planning["mapping_file"]["path"].startswith(f"main/{SCENE}/assets/mapping-")
    assert all(r["planning"] == planning for r in entries["geometric"]["evaluations"])
    assert "planning" not in entries["hold"] and "planning" not in entries["hold"]["evaluations"][0]
    ref = entries["geometric"]["evaluations"][0]
    assert ref["config"]["config_source"] == "run_config" and ref["config"]["path"].startswith("main/")
    _check_paths(index, root)


def _row_configs(data, inputs):
    base = data["rows"][0]
    data["rows"] = [{**base, "name": n} for n in ("row-a", "row-b")]
    text = (inputs / "run.ini").read_text()
    for row in data["rows"]:
        configs = {}
        for seed in ("201", "202"):
            (inputs / f"{row['name']}-{seed}.ini").write_text(text + f"# {row['name']} seed {seed}\n")
            configs[seed] = f"{row['name']}-{seed}.ini"
        row["configs"] = {"diagnostic": configs}


def test_row_specific_inis_never_share_a_group(tmp_path, sim_binary, monkeypatch):
    plan, root = _edited_plan(tmp_path, sim_binary, _row_configs)
    _, _, index = _pipeline(plan, root, monkeypatch)
    refs = [r for m in index["models"] for r in m["evaluations"]
            if r["operation"] == "frozen-deterministic" and m["checkpoint"] == "final"]
    assert len(refs) == 4 and len({r["config"]["sha256"] for r in refs}) == 4
    assert len({r["group"] for r in refs}) == 4
    assert all(r["config"]["config_source"] == "row" and r["config"]["path"].startswith("main/") for r in refs)
    hold = next(e for e in index["baselines"] if e["policy"] == "hold")["evaluations"]
    seed_201 = [r for r in hold if r["seed"] == 201]
    assert len({r["config"]["sha256"] for r in seed_201}) == len(seed_201) == len({r["group"] for r in seed_201})
    _check_paths(index, root)


def test_comparison_view_refuses_mixed_inis(tmp_path, sim_binary):
    def edit(data, inputs):
        _row_configs(data, inputs)
        data["evaluation"]["comparison"] = {"operation": "frozen-deterministic", "allow_incomplete": False}
    plan, root = _edited_plan(tmp_path, sim_binary, edit)
    accepted = _leaves(plan, root)
    task = _task(plan, f"compare/{SCENE}/frozen-deterministic/checkpoint-final")
    with pytest.raises(ValueError, match="different INIs"):
        reporting.build_comparison_view(task, plan, root, accepted)
