"""Plan and write inert batch artifacts for reporting tests."""

import json
import shutil
import zipfile
from pathlib import Path

from scripts.artifact_io import sha256_file
from scripts.rl.experiments import reporting
from scripts.rl.experiments.config import load_matrix_v2
from scripts.rl.experiments.plan import build_batch_plan, write_batch_plan
from scripts.rl.policy import episode_review

MESH = Path(__file__).resolve().parents[4]


EXAMPLE = MESH / "inputs/experiments/examples/coordination-smoke"


BATCH = "example-batch"


SCENE = "rural-coverage-3-peers"


T0 = "2026-10-01T00:00:00+00:00"


T1 = "2026-10-01T00:01:00+00:00"


METRIC_SOURCE = {"kind": "telemetry_window", "warmup_excluded": True}


SB3_FINAL_202 = (
    f"operate/{SCENE}/raw-delivery/train-seed-101/checkpoint-final/online-sb3/"
    "diagnostic/seed-202"
)


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
    return {
        "run_ini_sha256": record["sha256"],
        "nodes_json_sha256": record["nodes"]["sha256"],
        "buildings_json_sha256": record["buildings"]["sha256"],
        "jammers_json_sha256": None,
    }


def _zip(path: Path, steps: int, updates: int) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in (
            ("data", json.dumps({"num_timesteps": steps, "_n_updates": updates})),
            ("policy.pth", b"policy"),
            ("policy.optimizer.pth", b"optimizer"),
        ):
            archive.writestr(
                zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), data
            )
    return sha256_file(path)


def _train_episodes(attempt: Path, first: int, count: int, steps=64, seed=101):
    for index in range(first, first + count):
        folder = attempt / f"episode-{index:04}"
        folder.mkdir(parents=True)
        (folder / "rl_episode.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "steps": steps,
                    "seed": seed,
                    "cumulative_reward": 0.25 * index,
                }
            )
        )


def _progress(attempt: Path, steps):
    (attempt / "ppo").mkdir(parents=True, exist_ok=True)
    lines = ["time/total_timesteps,train/loss"] + [f"{s},{s / 1000}" for s in steps]
    (attempt / "ppo/progress.csv").write_text("\n".join(lines) + "\n")


def _train_manifest(
    attempt: Path, plan, num_timesteps, status="completed", resume=None, checkpoints=()
):
    final = attempt / "maskable_ppo_mesh.zip"
    manifest = {
        "manifest_version": 7,
        "status": status,
        "seed": 101,
        "control_mode": "centralized",
        "num_timesteps": num_timesteps,
        "scenario_identity": _identity(plan),
        "hyperparameters": {
            "total_timesteps": 256,
            "n_steps": 32,
            "batch_size": 16,
            "n_epochs": 2,
            "gamma": 0.99,
            "ent_coef": 0.0,
            "learning_rate": 0.0003,
            "eval_every_steps": 0,
            "eval_episodes": 1,
        },
        "model_path": "maskable_ppo_mesh.zip" if final.is_file() else None,
        "model_sha256": sha256_file(final) if final.is_file() else None,
        "checkpoints": [
            {
                "path": f"checkpoints/{p.name}",
                "sha256": sha256_file(p),
                "num_timesteps": n,
            }
            for p, n in checkpoints
        ],
        "observation_schema": {"sha256": "o" * 64},
        "reward_schema": {"sha256": "r" * 64},
        "resume": resume,
    }
    (attempt / "train_manifest.json").write_text(json.dumps(manifest, indent=2))


def _write_trains(plan, root):
    """One completed fake training attempt per train task, plus the bindings its consumers declare."""
    accepted, shas = {}, {}
    for train in (t for t in plan["tasks"] if t["kind"] == "train"):
        attempt = _dir(plan, root, train) / "attempt-1"
        zips = {
            "128": (
                _zip(attempt / "checkpoints/checkpoint_128_steps.zip", 128, 8),
                attempt / "checkpoints/checkpoint_128_steps.zip",
                128,
                8,
                "checkpoint",
            ),
            "final": (
                _zip(attempt / "maskable_ppo_mesh.zip", 256, 16),
                attempt / "maskable_ppo_mesh.zip",
                256,
                16,
                "final",
            ),
        }
        _zip(attempt / "checkpoints/checkpoint_256_steps.zip", 256, 16)
        _train_episodes(attempt, 1, 4)
        _progress(attempt, range(32, 257, 32))
        _train_manifest(
            attempt,
            plan,
            256,
            checkpoints=[
                (attempt / "checkpoints/checkpoint_128_steps.zip", 128),
                (attempt / "checkpoints/checkpoint_256_steps.zip", 256),
            ],
        )
        accepted[train["id"]] = str(attempt)
        for task in plan["tasks"]:
            binding = task.get("binding")
            if (
                task["kind"] != "operate"
                or not binding
                or binding["producer"] != train["id"]
                or (train["id"], binding["checkpoint"]) in shas
            ):
                continue
            sha, model, steps, updates, selection = zips[binding["checkpoint"]]
            record = {
                "model_binding_version": 1,
                "run_dir": str(attempt),
                "model_selection": selection,
                "model_path": str(model),
                "model_sha256": sha,
                "optimizer_sha256": "e" * 64,
                "num_timesteps": steps,
                "n_updates": updates,
                "train_manifest_path": str(attempt / "train_manifest.json"),
                "train_manifest_sha256": sha256_file(attempt / "train_manifest.json"),
            }
            (root / binding["path"]).parent.mkdir(parents=True, exist_ok=True)
            (root / binding["path"]).write_text(json.dumps(record))
            shas[(train["id"], binding["checkpoint"])] = (sha, steps, selection)
    return accepted, shas


def _metrics(value):
    return {
        "delivery_ratio": value,
        "worst_node_delivery_fraction": value,
        "post_jammer_delivery_ratio": None,
        "recovery_time_s": None,
        "coverage_fraction_mean": value,
        "unsafe_proximity_fraction": 0.0,
        "travel_m_total": 12.0,
        "displacement_m_final": 4.0,
        "connectivity": 1.0,
        "los_fraction": 0.5,
        "unroutable_fraction": 0.0,
        "first_all_los_decision": 3,
    }


def _episode(seed, value, episode_dir):
    return {
        "seed": seed,
        "episode_dir": episode_dir,
        "status": "completed",
        "error": None,
        "exit_code": 0,
        "decisions": 64,
        "return": 1.5,
        "reward_components_sum": {"delivery_ratio": 1.5},
        "revalidated_slots_total": 0,
        "mask_violations": 0,
        "actions_sha256": "c" * 64,
        "metrics": _metrics(value),
        "summary_json": None,
        "initial_displacement_m_total": 0.0,
    }


def _episode_folder(leaf: Path, seed: int, absolute: bool) -> str:
    folder = leaf / "episode-0001"
    (folder / "inputs").mkdir(parents=True)
    (folder / "inputs/run.ini").write_text("[scenario]\n")
    (folder / "steps.jsonl").write_text("{}\n")
    (folder / "rl_episode.json").write_text(
        json.dumps({"status": "completed", "steps": 64, "seed": seed})
    )
    return str(folder) if absolute else "episode-0001"


def _eval_manifest(plan, policy, seed, role, episode, model=None, metadata=None):
    block = {
        "episodes": [episode],
        "summary": {"expected_episodes": 1, "completed_episodes": 1},
    }
    if metadata:
        block["baseline"] = metadata
    return {
        "eval_manifest_version": 8,
        "status": "completed",
        "error": None,
        "label": f"{policy} seed {seed}",
        "started_at": T0,
        "ended_at": T1,
        "metric_source": METRIC_SOURCE,
        "seed_roles": {
            "role": role,
            "training_seed": 101 if model else None,
            "evaluation_seeds": [seed],
            "held_out": role == "held_out",
        },
        "training": None
        if model is None
        else {
            "algorithm": "MaskablePPO",
            "seed": 101,
            "seed_source": "cli",
            "evaluation_seed": None,
            "evaluation_seeds": [],
            "evaluation_episodes": 1,
            "scenario_identity": _identity(plan),
            "hyperparameters": {
                "total_timesteps": 256,
                "n_steps": 32,
                "gamma": 0.99,
                "ent_coef": 0.0,
                "eval_every_steps": 0,
                "eval_episodes": 1,
            },
        },
        "episodes_expected": 1,
        "episodes_completed": 1,
        "sim_binary": "fake-sim",
        "run_config": "run.ini",
        "band": "sub-6",
        "scenario_identity": _identity(plan),
        "contract": {"num_decisions": 64},
        "bundle": model,
        "compatibility": None,
        "selection": {
            "observation_preset": "raw_links_v1",
            "reward_components": ["delivery_ratio"],
            "reward_weights": [1.0],
        },
        "observation_schema": {"sha256": "o" * 64},
        "reward_schema": {"sha256": "r" * 64},
        "deterministic": metadata is not None
        and metadata.get("protocol") == "frozen_deterministic",
        "seeds": [seed],
        "seed_source": "eval",
        "policies": {policy: block},
    }


def _settings(protocol):
    if protocol == "online_gated_v1":
        return {
            "learning_rate": 0.0003,
            "gamma": 0.99,
            "gae_lambda": 0.95,
            "clip_range": 0.2,
            "ent_coef": 0.0,
            "n_epochs": 2,
            "target_kl": None,
            "n_steps": 16,
            "batch_size": 8,
            "eligible_only": True,
            "flush_final_partial": True,
        }
    if protocol == "online_sb3_v1":
        return {
            "n_steps": 16,
            "batch_size": 8,
            "learning_rate": 0.0001,
            "target_kl": 0.02,
            "ent_coef": 0.001,
        }
    return {}


def _accounting(protocol):
    if protocol == "online_gated_v1":
        return {
            "update_cycles": 4,
            "optimizer_steps": 16,
            "optimizer_epochs": 8,
            "episode_decisions": 64,
            "eligible_decisions": 64,
            "trained_decisions": 64,
            "excluded_prefix_decisions": 0,
            "untrained_tail_decisions": 0,
            "actor_change_l2": 0.01,
            "policy_parameters_changed": True,
            "optimizer_state_changed": True,
            "tail_policy": "final partial rollout flushed; a singleton tail is skipped",
            "weight_updates": "weight_updates.json",
        }
    if protocol == "online_sb3_v1":
        return {
            "update_cycles": 4,
            "optimizer_epochs": 8,
            "episode_budget": 64,
            "actual_decisions": 64,
            "untrained_tail_decisions": 0,
            "tail_policy": "budget % n_steps decisions after the last full rollout are not trained",
            "weight_updates": "weight_updates.json",
        }
    return {"update_cycles": 0, "optimizer_steps": 0, "untrained_tail_decisions": 0}


def _online_record(task, model_sha, steps, selection, value, eval_manifest):
    ident = task["identity"]
    protocol, online = (
        ident["protocol"],
        ident["protocol"] in ("online_gated_v1", "online_sb3_v1"),
    )
    audit = {
        "initial_parameter_sha256": "p" * 64,
        "final_parameter_sha256": ("q" if online else "p") * 64,
        "initial_optimizer_sha256": "e" * 64,
        "final_optimizer_sha256": ("f" if online else "e") * 64,
        **_accounting(protocol),
    }
    return {
        "online_experiment_version": 5,
        "protocol": protocol,
        "status": "completed",
        "started_at": T0,
        "ended_at": T1,
        "error": None,
        "label": None,
        "seed": ident["seed"],
        "seed_role": ident["seed_role"],
        "evaluation_seeds": [ident["seed"]],
        "settings": _settings(protocol),
        "schedule": None,
        "allow_different_scenario": False,
        "parent": {
            "run_dir": "models/<scenario>/<row>/train/train-seed-101/attempt-1",
            "model_selection": selection,
            "model_path": "<bound model>",
            "model_sha256": model_sha,
            "num_timesteps": steps,
            "train_manifest_sha256": "t" * 64,
        },
        "run_config": "<run.ini>",
        "scenario_identity": {"run_ini_sha256": "s" * 64},
        "binary_sha256": "b" * 64,
        "model": {
            "initial_parameter_sha256": "p" * 64,
            "final_parameter_sha256": audit["final_parameter_sha256"],
            "adapted_model": "adapted_model.zip" if online else None,
            "adapted_model_sha256": "a" * 64 if online else None,
        },
        "optimizer": {
            "initial_optimizer_sha256": "e" * 64,
            "final_optimizer_sha256": audit["final_optimizer_sha256"],
        },
        "accounting": _accounting(protocol),
        "evaluation": {
            "eval_manifest": eval_manifest,
            "episode_dir": "episode-0001",
            "decisions": 64,
            "weight_audit": "weight_audit.json",
            "steps_sha256": "2b4e7e1a1e1fbb6b1b8e8a2b46a6b0a1c4f1c1d7c6f3bc8b7a4c5d6e7f8091a2",
        },
        "episodes": [
            {
                "mode": protocol,
                "seed": ident["seed"],
                "episode_dir": "episode-0001",
                "decisions": 64,
                "metrics": _metrics(value),
                "return": 1.5,
                **audit,
            }
        ],
    }


def _write_operate(plan, root, task, shas, value=0.8, absolute=False):
    ident = task["identity"]
    leaf = _dir(plan, root, task) / "attempt-1"
    episode_dir = _episode_folder(leaf, ident["seed"], absolute)
    sha, steps, selection = shas[(task["binding"]["producer"], ident["checkpoint"])]
    protocol = ident["protocol"]
    has_eval = protocol != "online_sb3_v1"
    if has_eval:
        bundle = {
            "run_dir": "<train attempt>",
            "model_selection": selection,
            "model_path": "<bound model>",
            "model_sha256": sha,
            "num_timesteps": steps,
            "train_manifest_sha256": "t" * 64,
        }
        metadata = {
            "weights_frozen": protocol != "online_gated_v1",
            "protocol": protocol,
            "model_selection": selection,
            "execution_schedule": None,
        }
        manifest = _eval_manifest(
            plan,
            "model",
            ident["seed"],
            ident["seed_role"],
            _episode(ident["seed"], value, episode_dir),
            bundle,
            metadata,
        )
        (leaf / "eval_manifest.json").write_text(json.dumps(manifest, indent=2))
    if protocol != "frozen_deterministic":
        record = _online_record(
            task,
            sha,
            steps,
            selection,
            value,
            "eval_manifest.json" if has_eval else None,
        )
        (leaf / "online_manifest.json").write_text(json.dumps(record, indent=2))
    (leaf / "weight_audit.json").write_text(
        json.dumps({"initial_parameter_sha256": "p" * 64})
    )
    return leaf


def _write_baseline(plan, root, task, value=0.5):
    ident = task["identity"]
    leaf = _dir(plan, root, task) / "attempt-1"
    episode_dir = _episode_folder(leaf, ident["seed"], False)
    metadata = {"fingerprint": "f" * 64} if ident["policy"] == "scripted" else None
    manifest = _eval_manifest(
        plan,
        ident["policy"],
        ident["seed"],
        ident["seed_role"],
        _episode(ident["seed"], value, episode_dir),
        None,
        metadata,
    )
    (leaf / "eval_manifest.json").write_text(json.dumps(manifest, indent=2))
    return leaf


def _review_stub(directory):
    return {
        "final_minute_coverage": 0.5,
        "final_minute_survivor_delivery": None,
        "unsafe_fraction": 0.0,
        "travel_m_total": 3.0,
    }


def _leaves(plan, root, skip=(), values=None, absolute=False, baselines=True):
    accepted, shas = _write_trains(plan, root)
    for task in plan["tasks"]:
        if task["id"] in skip:
            continue
        if task["kind"] == "operate":
            value = (values or {}).get(task["id"], 0.8)
            accepted[task["id"]] = str(
                _write_operate(plan, root, task, shas, value, absolute)
            )
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
    result = reporting.run_report_task(
        _task(plan, f"index/{SCENE}"), plan, root, accepted
    )
    return (
        accepted,
        result,
        json.loads((root / "main" / SCENE / "mission_scenario.json").read_text()),
    )


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


def _row_configs(data, inputs):
    base = data["rows"][0]
    data["rows"] = [{**base, "name": n} for n in ("row-a", "row-b")]
    text = (inputs / "run.ini").read_text()
    for row in data["rows"]:
        configs = {}
        for seed in ("201", "202"):
            (inputs / f"{row['name']}-{seed}.ini").write_text(
                text + f"# {row['name']} seed {seed}\n"
            )
            configs[seed] = f"{row['name']}-{seed}.ini"
        row["configs"] = {"diagnostic": configs}
