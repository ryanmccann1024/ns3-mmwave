"""Run or continue MaskablePPO training and close its simulator environments."""

import os

from scripts.rl.agents.callbacks import build_callbacks, Cadence
from scripts.rl.agents.mask_ppo import MaskablePPOConfig, MaskablePpoTrainer
from scripts.rl.env.config import read_scenario_identity
from scripts.rl.env.mesh_env import MeshRlEnv
from scripts.rl.policy.compat import check_compatibility
from scripts.rl.policy.training_artifacts import EVAL_DIR, TrainingArtifacts


def mask_fn(env):
    return env.unwrapped.action_masks()


def train_mppo(cfg: MaskablePPOConfig, sim_binary: str, run_config: str,
               out_dir: str, band: str | None, seed_source: str, selection,
               cadence: Cadence, resume=None) -> str:
    artifacts = TrainingArtifacts(cfg, sim_binary, run_config, out_dir, band,
                                  seed_source, cadence, resume)
    trainer = None
    env = eval_env = eval_callback = None
    try:
        # Let the env resolve the run.ini seed itself so episode manifests report
        # the same seed_source as this training manifest.
        env_seed = cfg.seed if seed_source == "cli" else None
        env = MeshRlEnv(sim_binary, run_config, seed=env_seed,
                        output_dir=out_dir, band=band, selection=selection)
        env.reset()                   # populate dynamic obs/action spaces before wrapping
        if resume is not None:
            check_compatibility(resume.manifest, env,
                                live_identity=read_scenario_identity(run_config), live_band=band)
        artifacts.record_contract(env, selection)

        if cadence.eval_every > 0:
            eval_env = MeshRlEnv(sim_binary, run_config, seed=cadence.eval_seed,
                                 output_dir=os.path.join(out_dir, EVAL_DIR), band=band,
                                 selection=selection)
            eval_env.reset(seed=cadence.eval_seed, options={"seed_source": "eval"})

        callbacks, eval_callback = build_callbacks(
            out_dir, cadence.checkpoint_every, cadence.keep_checkpoints,
            eval_env, cadence.eval_every, cadence.eval_episodes, cfg.verbose,
            artifacts=artifacts, restored_steps=0 if resume is None else resume.num_timesteps)
        artifacts.eval_callback = eval_callback

        trainer = (MaskablePpoTrainer(cfg, env, mask_fn) if resume is None else
                   MaskablePpoTrainer.resume(cfg, env, mask_fn, resume))
        trainer.train(callback=callbacks or None, continuing=resume is not None)
        return artifacts.complete(trainer)
    except BaseException as exc:
        artifacts.fail(exc, trainer)
        raise
    finally:
        # Always reap the simulators; a recorded failure is never relabelled here.
        for instance in (env, eval_env):
            if instance is not None:
                try:
                    instance.close()
                except Exception:
                    pass

