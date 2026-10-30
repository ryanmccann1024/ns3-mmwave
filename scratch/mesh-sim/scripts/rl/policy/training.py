"""Run or continue MaskablePPO training and close its simulator environments."""

import os
from dataclasses import replace
from functools import partial
from stable_baselines3.common.logger import configure
from scripts.rl.env.config import read_episode_output
from scripts.rl.policy.bundle import (bind_model, checkpoint_counters, eval_selection,
                                      read_bundle)

from scripts.rl.agents.callbacks import build_callbacks, Cadence
from scripts.rl.agents.post_update import (CHECKPOINT_TIMINGS, PostUpdateCheckpoints,
                                           validate_after_update_schedule)
from scripts.rl.agents.mask_ppo import MaskablePPOConfig, MaskablePpoTrainer
from scripts.rl.env.recording.decisions import DecisionContext
from scripts.rl.env.recording.decisions import DecisionRecording
from scripts.rl.env.config import read_scenario_identity
from scripts.rl.env.mesh_env import MeshRlEnv
from scripts.rl.policy.compat import BundleError, check_compatibility
from scripts.rl.policy.training_artifacts import EVAL_DIR, TrainingArtifacts


def mask_fn(env):
    return env.unwrapped.action_masks()


def continuation_parent(run_dir, model: str = "final"):
    """Verified completed parent whose restored count is the saved ZIP's own counter.

    ``read_bundle`` leaves final/best ``num_timesteps`` unset; it is never read
    as zero. A final model must match the manifest's recorded count, a best
    model cannot be later than it, and a checkpoint must match its entry.
    """
    bundle = read_bundle(run_dir, model)
    counters = checkpoint_counters(bundle.model_path)
    if not (counters["policy_state_present"] and counters["optimizer_state_present"]):
        raise BundleError(f"{bundle.model_path} lacks policy or optimizer state for continuation")
    steps = counters["num_timesteps"]
    recorded = bundle.manifest.get("num_timesteps")
    if bundle.num_timesteps is not None and bundle.num_timesteps != steps:
        raise BundleError("checkpoint ZIP counter differs from its manifest entry")
    if model == "final" and recorded != steps:
        raise BundleError(f"final model ZIP has {steps} timesteps; manifest records {recorded}")
    if model == "best" and (not isinstance(recorded, int) or steps > recorded):
        raise BundleError(f"best model ZIP has {steps} timesteps beyond the run's {recorded}")
    return replace(bundle, num_timesteps=steps)


def curriculum_env_factory(path):
    """Training-only env factory for an existing curriculum schedule, plus its hashes."""
    from scripts.rl.env.curriculum import CurriculumEnv, load_curriculum_schedule

    loaded = load_curriculum_schedule(path)
    return (partial(CurriculumEnv, schedule=loaded["schedule"]),
            {"schedule_path": loaded["path"], "schedule_sha256": loaded["sha256"],
             "config_sha256": dict(loaded["config_sha256"])})


def validate_training_options(cfg, cadence: Cadence, resume=None, checkpoint_timing="standard",
                              decisions_per_episode=None, curriculum=None) -> None:
    """Checks needing no simulator; train_mppo repeats them and adds native timing."""
    if checkpoint_timing not in CHECKPOINT_TIMINGS:
        raise ValueError(f"checkpoint timing must be one of {CHECKPOINT_TIMINGS}")
    if decisions_per_episode is not None and (isinstance(decisions_per_episode, bool) or
                                              not isinstance(decisions_per_episode, int) or
                                              decisions_per_episode < 1):
        raise ValueError("decisions per episode must be an integer >= 1")
    if curriculum is not None and resume is not None:
        raise ValueError("a curriculum schedule starts at its first stage; it cannot continue a parent")
    if checkpoint_timing == "after-update":
        validate_after_update_schedule(cfg, cadence, 0 if resume is None else resume.num_timesteps,
                                       decisions_per_episode)


def train_mppo(cfg: MaskablePPOConfig, sim_binary: str, run_config: str,
               out_dir: str, band: str | None, seed_source: str, selection,
               cadence: Cadence, resume=None, records=None, env_factory=None,
               post_update_callback_factory=None, checkpoint_timing="standard",
               decisions_per_episode=None, curriculum=None, continuation=None) -> str:
    """Train or continue one policy.

    ``checkpoint_timing='after-update'`` installs ``PostUpdateCheckpoints``;
    ``decisions_per_episode`` is asserted against the native contract;
    ``curriculum`` is the provenance of an ``env_factory`` from
    ``curriculum_env_factory``; ``continuation`` is the parent's model selector
    when ``resume`` is a ``continuation_parent``. Each is recorded as an
    optional manifest field only when used.
    """
    artifacts = TrainingArtifacts(cfg, sim_binary, run_config, out_dir, band,
                                  seed_source, cadence, resume)
    trainer = None
    env = eval_env = eval_callback = None
    try:
        validate_training_options(cfg, cadence, resume, checkpoint_timing,
                                  decisions_per_episode, curriculum)
        after_update = checkpoint_timing == "after-update"
        if after_update and post_update_callback_factory is not None:
            raise ValueError("after-update timing supplies its own post-update callback")
        if curriculum is not None and env_factory is None:
            raise ValueError("curriculum provenance requires its env factory")
        if continuation is not None and resume is None:
            raise ValueError("continuation requires a verified parent bundle")
        provenance = {}
        if after_update:
            provenance["checkpoint_timing"] = checkpoint_timing
        if curriculum is not None:
            provenance["curriculum"] = dict(curriculum)
        if continuation is not None:
            provenance["continuation"] = {"selector": continuation,
                                          "parent": bind_model(resume.run_dir, resume.model_path)}
        if provenance:
            artifacts.manifest.update(provenance)
            artifacts.write()
        if post_update_callback_factory is not None and cadence.eval_every:
            raise ValueError('campaign post-update checkpoints require separate validation, not in-training evaluation')
        # Let the env resolve the run.ini seed itself so episode manifests report
        # the same seed_source as this training manifest.
        env_seed = cfg.seed if seed_source == "cli" else None
        output_settings = read_episode_output(run_config)
        compact = output_settings["compact_training"]
        if output_settings["validation_after_update"]:
            from scripts.rl.agents.post_update import validate_schedule
            validate_schedule(cfg, cadence, resume)
        # Optional campaign-owned training distribution; validation always uses
        # the canonical MeshRlEnv and original run_config below.
        env = (env_factory or MeshRlEnv)(sim_binary, run_config, seed=env_seed, record_viz=not compact,
                        output_dir=out_dir, band=band, selection=selection,
                        decision_records=(DecisionRecording(records, DecisionContext("training", "train"))
                                          if records is not None else None))
        env.reset()                   # populate dynamic obs/action spaces before wrapping
        if decisions_per_episode is not None or after_update:
            native = int(env.contract["num_decisions"])
            if decisions_per_episode is not None and decisions_per_episode != native:
                raise ValueError(f"asserted {decisions_per_episode} decisions per episode; "
                                 f"the simulator contract has {native}")
            artifacts.manifest["decisions_per_episode"] = {"asserted": decisions_per_episode,
                                                           "native": native}
            artifacts.write()
            if after_update:
                validate_after_update_schedule(
                    cfg, cadence, 0 if resume is None else resume.num_timesteps, native)
                post_update_callback_factory = partial(
                    PostUpdateCheckpoints, every=cadence.checkpoint_every,
                    keep=cadence.keep_checkpoints, decisions_per_episode=native)
        if resume is not None:
            check_compatibility(resume.manifest, env,
                                live_identity=read_scenario_identity(run_config), live_band=band)
        artifacts.record_contract(env, selection)

        if cadence.eval_every > 0:
            validation_selection = eval_selection(selection)
            if compact and not output_settings["record_validation_telemetry"]:
                validation_selection = replace(validation_selection, telemetry="none")
            eval_env = MeshRlEnv(sim_binary, run_config, seed=cadence.eval_seed, record_viz=not compact,
                                 output_dir=os.path.join(out_dir, EVAL_DIR), band=band,
                                 selection=validation_selection,
                                 decision_records=(DecisionRecording(records, DecisionContext(
                                     "evaluation", "train_eval", policy="model"))
                                     if records is not None else None))
            eval_env.reset(seed=cadence.eval_seed, options={"seed_source": "eval"})

        callbacks, eval_callback = build_callbacks(
            out_dir, 0 if post_update_callback_factory is not None else cadence.checkpoint_every,
            cadence.keep_checkpoints,
            eval_env, cadence.eval_every, cadence.eval_episodes, cfg.verbose,
            artifacts=artifacts, restored_steps=0 if resume is None else resume.num_timesteps,
            eval_seeds=cadence.eval_seeds,
            after_update=output_settings["validation_after_update"])
        artifacts.eval_callback = eval_callback

        trainer = (MaskablePpoTrainer(cfg, env, mask_fn) if resume is None else
                   MaskablePpoTrainer.resume(cfg, env, mask_fn, resume))
        if cfg.tensorboard_log is None:
            formats = ["csv"] + (["stdout"] if cfg.verbose else [])
            trainer.model.set_logger(configure(str(artifacts.out_dir / "ppo"), formats))
        # Campaign-owned post-update checkpointing can run on fresh or resumed
        # training without constructing an evaluation environment or changing
        # existing callback defaults. The factory receives lifecycle ownership.
        if post_update_callback_factory is not None:
            callbacks.append(post_update_callback_factory(artifacts))
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
