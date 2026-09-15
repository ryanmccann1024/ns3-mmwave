#!/usr/bin/env python3
"""Training entry point for the mesh-sim RL agent (MaskablePPO).

Usage (run from mesh-sim)
-------------------------
    python -m scripts.rl.train \
        --sim-binary <BIN> \
        --run-config inputs/baselines/p0-smoke/run.ini \
        --output-dir outputs/<dir> \
        [--band sub-6] \
        m-ppo --total-timesteps 16 --n-steps 16 --seed 1
"""

import argparse
import importlib.metadata
import json
import os
import platform
import sys
from datetime import datetime, timezone

from scripts.rl.agents.mask_ppo import MaskablePPOConfig, MaskablePpoTrainer
from scripts.rl.bootstrap_venv import DIRECT_DEPS
from scripts.rl.env.mesh_env import MeshRlEnv, read_scenario_seed

MANIFEST_NAME = "train_manifest.json"
MODEL_BASENAME = "maskable_ppo_mesh"

_MAX_ERROR_CHARS = 1000


## @brief Adapter ActionMasker calls each step to fetch the current mask.
def mask_fn(env):
    return env.unwrapped.action_masks()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


## @brief Installed versions of all direct project dependencies.
def _package_versions() -> dict:
    versions = {}
    for mod, distribution in DIRECT_DEPS.items():
        try:
            versions[mod] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[mod] = None
    return versions


## @brief Build the output directory (explicit, or timestamped).
def _make_out_dir(output_dir: str) -> str:
    if output_dir:
        out_dir = output_dir
    else:
        now = datetime.now()
        out_dir = os.path.join("outputs", now.strftime("%Y-%m"),
                               now.strftime("%d"), now.strftime("%H-%M-%S"))
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


## @brief True when out_dir already holds a training run we must not clobber.
def _has_previous_run(out_dir: str) -> str | None:
    for name in (MANIFEST_NAME, f"{MODEL_BASENAME}.zip"):
        if os.path.exists(os.path.join(out_dir, name)):
            return name
    return None


def _write_manifest(out_dir: str, manifest: dict) -> None:
    with open(os.path.join(out_dir, MANIFEST_NAME), "w") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")


## @brief Train a MaskablePPO agent on the mesh sim.
def train_mppo(cfg: MaskablePPOConfig, sim_binary: str, run_config: str,
               out_dir: str, band: str | None, seed_source: str) -> str:
    manifest = {
        "manifest_version": 1,
        "status": "running",
        "started_at": _now_iso(),
        "ended_at": None,
        "sim_binary": os.path.abspath(sim_binary),
        "run_config": os.path.abspath(run_config),
        "algorithm": "MaskablePPO",
        "seed": cfg.seed,
        "seed_source": seed_source,
        "band": band,
        "hyperparameters": {
            "total_timesteps": cfg.total_timesteps,
            "n_steps": cfg.n_steps,
            "gamma": cfg.gamma,
            "ent_coef": cfg.ent_coef,
            "verbose": cfg.verbose,
            "tensorboard_log": cfg.tensorboard_log,
        },
        "output_dir": os.path.abspath(out_dir),
        "python_version": platform.python_version(),
        "package_versions": _package_versions(),
        "model_path": None,
    }
    _write_manifest(out_dir, manifest)

    model_path = os.path.abspath(os.path.join(out_dir, f"{MODEL_BASENAME}.zip"))
    try:
        # Let the env resolve the run.ini seed itself so episode manifests report
        # the same seed_source as this training manifest.
        env_seed = cfg.seed if seed_source == "cli" else None
        env = MeshRlEnv(sim_binary, run_config, seed=env_seed,
                        output_dir=out_dir, band=band)
        env.reset()                   # populate dynamic obs/action spaces before wrapping

        trainer = MaskablePpoTrainer(cfg, env, mask_fn)
        trainer.train()
        trainer.save(os.path.join(out_dir, MODEL_BASENAME))
        env.close()
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["ended_at"] = _now_iso()
        manifest["error"] = f"{type(exc).__name__}: {exc}"[:_MAX_ERROR_CHARS]
        _write_manifest(out_dir, manifest)
        raise

    manifest["status"] = "completed"
    manifest["ended_at"] = _now_iso()
    manifest["model_path"] = model_path
    _write_manifest(out_dir, manifest)
    return model_path


def main() -> int:
    p = argparse.ArgumentParser(description="Train an RL agent on mesh-sim")
    p.add_argument("--sim-binary", required=True, help="Path to mesh-sim executable")
    p.add_argument("--run-config", required=True, help="run.ini with an [rl] section")
    p.add_argument("--output-dir", default="")
    p.add_argument("--band", choices=["mmwave", "sub-6"], default=None,
                   help="Override the scenario band; omitted -> scenario decides")
    p.add_argument("--verbose", type=int, default=1, choices=[0, 1],
                   help="0 = quiet, 1 = SB3 training logs")

    sub = p.add_subparsers(dest="modeltype", required=True,
                           help="Which agent to train")

    # Maskable PPO
    ppo = sub.add_parser("m-ppo", help="Maskable PPO")
    ppo.add_argument("--total-timesteps", type=int, default=100_000)
    ppo.add_argument("--n-steps", type=int, default=1024)
    ppo.add_argument("--gamma", type=float, default=0.95)
    ppo.add_argument("--ent-coef", type=float, default=0.01)
    ppo.add_argument("--seed", type=int, default=None,
                     help="Training seed; defaults to [scenario] seed in run.ini")
    ppo.add_argument("--tensorboard-log", default=None)

    # QR-DQN (disabled for now — kept so the CLI shape is stable)
    qr = sub.add_parser("qr-dqn", help="Quantile-Regression DQN (disabled)")
    qr.add_argument("--seed", type=int, default=None)

    args = p.parse_args()

    if args.modeltype == "qr-dqn":
        print("qr-dqn is disabled in this version", file=sys.stderr)
        return 1

    if args.modeltype != "m-ppo":
        return 1

    if args.seed is not None:
        seed, seed_source = args.seed, "cli"
    else:
        ini_seed = read_scenario_seed(args.run_config)
        if ini_seed is None:
            print("No seed available: pass m-ppo --seed <int> or set [scenario] seed "
                  f"in {args.run_config}", file=sys.stderr)
            return 1
        seed, seed_source = ini_seed, "run.ini"

    out_dir = _make_out_dir(args.output_dir)
    existing = _has_previous_run(out_dir)
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
                   args.band, seed_source)
    except Exception as exc:
        print(f"Training failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"\nDone. Model + logs in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
