#!/usr/bin/env python3
"""Train a MaskablePPO policy on mesh-sim scenarios."""

import argparse
import sys

from scripts.rl.agents.callbacks import Cadence
from scripts.rl.agents.mask_ppo import MaskablePPOConfig
from scripts.rl.cli_common import (add_scenario_arguments, add_selection_arguments,
                                   has_previous_run, make_out_dir, resolve_out_dir,
                                   resolve_seed,
                                   selection_from_args)
from scripts.rl.policy.bundle import (check_run_overlap, read_recovery_bundle,
                                      selection_from_manifest)
from scripts.rl.policy.training import train_mppo


def _cadence_from_args(args) -> Cadence | str:
    """Validate the cadence flags before anything is launched; a str is the error."""
    if args.checkpoint_every_steps < 0 or args.eval_every_steps < 0:
        return "--checkpoint-every-steps and --eval-every-steps must be >= 0"
    if args.keep_checkpoints < 1:
        return "--keep-checkpoints must be >= 1"
    if args.eval_episodes < 1:
        return "--eval-episodes must be >= 1"
    return Cadence(checkpoint_every=args.checkpoint_every_steps,
                   keep_checkpoints=args.keep_checkpoints,
                   eval_every=args.eval_every_steps,
                   eval_episodes=args.eval_episodes)


def main() -> int:
    p = argparse.ArgumentParser(description="Train an RL agent on mesh-sim")
    add_scenario_arguments(p)
    p.add_argument("--output-dir", default="")
    p.add_argument("--verbose", type=int, default=1, choices=[0, 1],
                   help="0 = quiet, 1 = SB3 training logs")
    add_selection_arguments(p)

    sub = p.add_subparsers(dest="modeltype", required=True,
                           help="Which agent to train")

    # Maskable PPO
    ppo = sub.add_parser("m-ppo", help="Maskable PPO")
    ppo.add_argument("--total-timesteps", type=int, default=100_000,
                     help="Cumulative timestep target, including restored steps when resuming")
    ppo.add_argument("--n-steps", type=int, default=None)
    ppo.add_argument("--gamma", type=float, default=None)
    ppo.add_argument("--ent-coef", type=float, default=None)
    ppo.add_argument("--resume-run-dir", default=None,
                     help="Continue from a verified checkpoint in this previous run")
    ppo.add_argument("--resume-checkpoint", default=None,
                     help="checkpoints/<file>.zip; omitted -> latest retained checkpoint")
    ppo.add_argument("--seed", type=int, default=None,
                     help="Training seed; defaults to [scenario] seed in run.ini")
    ppo.add_argument("--tensorboard-log", default=None)
    ppo.add_argument("--checkpoint-every-steps", type=int, default=0,
                     help="Save a checkpoint every N timesteps; 0 disables checkpoints")
    ppo.add_argument("--keep-checkpoints", type=int, default=3,
                     help="How many newest checkpoints to retain (>= 1)")
    ppo.add_argument("--eval-every-steps", type=int, default=0,
                     help="Run a masked evaluation every N timesteps; 0 disables it")
    ppo.add_argument("--eval-episodes", type=int, default=1,
                     help="Episodes per evaluation (>= 1)")
    ppo.add_argument("--eval-seed", type=int, default=None,
                     help="Seed for the evaluation env; defaults to the training seed + 1")

    # QR-DQN (disabled for now — kept so the CLI shape is stable)
    qr = sub.add_parser("qr-dqn", help="Quantile-Regression DQN (disabled)")
    qr.add_argument("--seed", type=int, default=None)

    args = p.parse_args()

    if args.modeltype == "qr-dqn":
        print("qr-dqn is disabled in this version", file=sys.stderr)
        return 1

    if args.modeltype != "m-ppo":
        return 1

    cadence = _cadence_from_args(args)
    if isinstance(cadence, str):
        print(cadence, file=sys.stderr)
        return 1

    resume = None
    try:
        if args.resume_checkpoint and not args.resume_run_dir:
            raise ValueError("--resume-checkpoint requires --resume-run-dir")
        if args.resume_run_dir:
            resume = read_recovery_bundle(args.resume_run_dir, args.resume_checkpoint)
            if args.total_timesteps <= resume.num_timesteps:
                raise ValueError("--total-timesteps must exceed the restored timestep count")
            flags = ("observation_preset", "reward_components", "reward_weights",
                     "telemetry", "telemetry_every")
            if any(getattr(args, flag) is not None for flag in flags):
                raise ValueError("selection flags cannot change when resuming; the manifest decides")
            selection = selection_from_manifest(resume.manifest)
            seed = int(resume.manifest["seed"])
            if args.seed is not None and args.seed != seed:
                raise ValueError("--seed cannot change when resuming")
            seed_source = resume.manifest["seed_source"]
            args.band = args.band if args.band is not None else resume.manifest.get("band")
        else:
            seed, seed_source = resolve_seed(args.seed, args.run_config)
            selection = selection_from_args(args)
        defaults = MaskablePPOConfig()
        for key in ("n_steps", "gamma", "ent_coef"):
            saved = (resume.manifest["hyperparameters"][key] if resume is not None
                     else getattr(defaults, key))
            value = getattr(args, key)
            if resume is not None and value is not None and value != saved:
                raise ValueError(f"--{key.replace('_', '-')} cannot change when resuming")
            setattr(args, key, saved if value is None else value)
        if args.total_timesteps < 1 or args.n_steps < 2:
            raise ValueError("--total-timesteps must be positive and --n-steps must be >= 2")
        cadence.eval_seed = args.eval_seed if args.eval_seed is not None else seed + 1
        out_dir = resolve_out_dir(args.output_dir)
        if resume is not None:
            check_run_overlap(out_dir, resume.run_dir)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    out_dir = make_out_dir(out_dir)
    existing = has_previous_run(out_dir)
    if existing:
        print(f"Refusing to start: {out_dir} already contains {existing}. "
              "Choose a new --output-dir.", file=sys.stderr)
        return 1

    print("Creating Maskable-PPO model ...")
    cfg = MaskablePPOConfig(
        total_timesteps=args.total_timesteps,
        n_steps=args.n_steps,
        gamma=args.gamma,
        ent_coef=args.ent_coef,
        seed=seed,
        verbose=args.verbose,
        tensorboard_log=args.tensorboard_log,
    )
    try:
        train_mppo(cfg, args.sim_binary, args.run_config, out_dir,
                   args.band, seed_source, selection, cadence, resume)
    except Exception as exc:
        print(f"Training failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"\nDone. Model + logs in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
