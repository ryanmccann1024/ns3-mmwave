"""Training manifests, verified checkpoint records, and final/best model provenance."""

import math
import os
import platform
from pathlib import Path

from scripts.rl.cli_common import (MANIFEST_NAME, MODEL_BASENAME, now_iso,
                                   package_versions, sha256_file, write_json)
from scripts.rl.env.config import read_scenario_identity

MANIFEST_VERSION = 6
CHECKPOINT_DIR = "checkpoints"
CHECKPOINT_PREFIX = "checkpoint"
BEST_MODEL_NAME = "best_model.zip"
EVAL_LOG_NAME = "evaluations.npz"
EVAL_DIR = "eval"


def list_checkpoints(directory, name_prefix=CHECKPOINT_PREFIX):
    """Return saved checkpoints ordered by timestep; ignore incomplete temporary files."""
    found = []
    for path in Path(directory).glob(f"{name_prefix}_*_steps.zip"):
        steps = path.name[len(name_prefix) + 1:-len("_steps.zip")]
        if steps.isdigit():
            found.append((int(steps), path))
    return sorted(found)


def evaluation_block(out_dir, cadence):
    """Describe the during-training evaluation output and cadence."""
    if cadence.eval_every <= 0:
        return None
    return {"every_steps": cadence.eval_every, "episodes": cadence.eval_episodes,
            "seed": cadence.eval_seed, "seed_source": "eval",
            "output_dir": os.path.abspath(os.path.join(out_dir, EVAL_DIR)),
            "log_path": os.path.abspath(os.path.join(out_dir, EVAL_LOG_NAME))}


class TrainingArtifacts:
    """Persist lifecycle progress before retention can remove a recovery checkpoint."""

    def __init__(self, cfg, sim_binary, run_config, out_dir, band, seed_source, cadence,
                 resume=None):
        self.out_dir = Path(out_dir).resolve()
        self.eval_callback = None
        self.manifest = {
            "manifest_version": MANIFEST_VERSION,
            "status": "running",
            "started_at": now_iso(),
            "ended_at": None,
            "sim_binary": os.path.abspath(sim_binary),
            "run_config": os.path.abspath(run_config),
            "scenario_identity": read_scenario_identity(run_config),
            "control_mode": None,
            "contract": None,
            "algorithm": "MaskablePPO",
            "seed": cfg.seed,
            "seed_source": seed_source,
            "band": band,
            "selection": None,
            "observation_schema": None,
            "reward_schema": None,
            "telemetry": None,
            "hyperparameters": {
                "total_timesteps": cfg.total_timesteps,
                "n_steps": cfg.n_steps,
                "gamma": cfg.gamma,
                "ent_coef": cfg.ent_coef,
                "verbose": cfg.verbose,
                "tensorboard_log": cfg.tensorboard_log,
                "checkpoint_every_steps": cadence.checkpoint_every,
                "keep_checkpoints": cadence.keep_checkpoints,
                "eval_every_steps": cadence.eval_every,
                "eval_episodes": cadence.eval_episodes,
            },
            "evaluation": evaluation_block(out_dir, cadence),
            "evaluation_state": None,
            "output_dir": os.path.abspath(out_dir),
            "python_version": platform.python_version(),
            "platform": {"system": platform.system(), "machine": platform.machine()},
            "package_versions": package_versions(),
            "model_path": None,
            "model_sha256": None,
            "best_model_path": None,
            "best_model_sha256": None,
            "best_mean_reward": None,
            "checkpoints": [],
        }
        self.manifest["num_timesteps"] = 0 if resume is None else resume.num_timesteps
        self.manifest["resume"] = None if resume is None else {
            "parent": resume.describe(),
            "restored_timesteps": resume.num_timesteps,
            "target_timesteps": cfg.total_timesteps,
            "remaining_timesteps": cfg.total_timesteps - resume.num_timesteps,
            "exact_resume": False,
            "restored": ["policy", "optimizer", "num_timesteps", "callback_cadence"],
            "restarted": ["simulator", "episode", "rollout_buffer", "random_generators",
                          "evaluation_history", "best_reward_threshold"],
        }
        self.write()

    def write(self):
        write_json(self.out_dir / MANIFEST_NAME, self.manifest)

    def record_contract(self, env, selection):
        self.manifest.update({"control_mode": env.control_mode, "contract": env.contract,
                              "selection": selection.describe(),
                              "observation_schema": env.observation_schema,
                              "reward_schema": env.reward_schema,
                              "telemetry": {"mode": selection.telemetry,
                                            "every": selection.telemetry_every}})
        self.write()

    def record_evaluation(self):
        callback = self.eval_callback
        if callback is None:
            return
        path = self.out_dir / BEST_MODEL_NAME
        if path.is_file():
            reward = float(callback.best_mean_reward)
            self.manifest.update({"best_model_path": str(path),
                                  "best_model_sha256": sha256_file(path),
                                  "best_mean_reward": reward if math.isfinite(reward) else None})
        self.manifest["evaluation_state"] = {
            "callback_calls": callback.n_calls,
            "completed_evaluations": len(callback.evaluations_timesteps),
            "best_mean_reward": self.manifest["best_mean_reward"],
        }

    def record_checkpoint(self, path, steps, keep_last):
        entry = {"path": str(Path(path).resolve()), "sha256": sha256_file(path),
                 "num_timesteps": int(steps)}
        old = self.manifest["checkpoints"]
        retained = (old + [entry])[-keep_last:]
        self.manifest["checkpoints"] = retained
        self.manifest["num_timesteps"] = int(steps)
        self.record_evaluation()
        entry["evaluation_state"] = self.manifest.get("evaluation_state")
        self.write()
        for discarded in old:
            if discarded not in retained:
                Path(discarded["path"]).unlink(missing_ok=True)

    def complete(self, trainer):
        path = self.out_dir / f"{MODEL_BASENAME}.zip"
        temporary = self.out_dir / f"{MODEL_BASENAME}.tmp.zip"
        try:
            trainer.save(str(temporary))
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        self.manifest.update({"status": "completed", "ended_at": now_iso(),
                              "num_timesteps": int(trainer.model.num_timesteps),
                              "model_path": str(path), "model_sha256": sha256_file(path)})
        self.record_evaluation()
        self.write()
        return str(path)

    def fail(self, exc, trainer=None):
        self.manifest.update({"status": "failed", "ended_at": now_iso(),
                              "error": f"{type(exc).__name__}: {exc}"[:1000]})
        if trainer is not None:
            self.manifest["num_timesteps"] = int(trainer.model.num_timesteps)
        self.record_evaluation()
        self.write()
