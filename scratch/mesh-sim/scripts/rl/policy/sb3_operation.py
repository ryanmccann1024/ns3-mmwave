"""Run the SB3 online and legacy sampled evaluation protocols."""

import json
from pathlib import Path
from types import SimpleNamespace

from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.logger import configure

from scripts.artifact_io import now_iso, sha256_file, write_json
from scripts.rl.policy import bundle as _bundle
from scripts.rl.policy.evaluate import ModelPolicy, episode_metrics, run_episode

ONLINE_MANIFEST_NAME = "online_manifest.json"

DEFAULT_MODES = ("fixed_sampled", "online")
SB3_DEFAULTS = {"ent_coef": 0.001, "target_kl": 0.02}
SB3_LEARNING_RATE_CAP = 0.0001
SB3_PARENT_LEARNING_RATE_FALLBACK = 0.0003
_PPO_SCOPES = (
    ("actor", ("mlp_extractor.policy_net", "action_net")),
    ("critic", ("mlp_extractor.value_net", "value_net")),
)


class UpdateRecorder(BaseCallback):
    """Record actual parameter changes after each optimizer update cycle."""

    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.events = []

    def _on_training_start(self):
        self.start = self.model.num_timesteps
        self.last_updates = self.model._n_updates
        self.initial = {
            k: v.detach().cpu().clone()
            for k, v in self.model.policy.state_dict().items()
        }
        self.initial_digest = _bundle.parameter_digest(self.model)

    def record_update(self):
        if self.model._n_updates == self.last_updates:
            return
        state = self.model.policy.state_dict()
        delta = (
            sum(
                float(((value.detach().cpu() - self.initial[key]) ** 2).sum())
                for key, value in state.items()
            )
            ** 0.5
        )
        changes = {
            scope + "_change_l2_from_start": sum(
                float(((value.detach().cpu() - self.initial[key]) ** 2).sum())
                for key, value in state.items()
                if key.startswith(prefixes)
            )
            ** 0.5
            for scope, prefixes in _PPO_SCOPES
        }
        self.events.append(
            {
                "decision": self.model.num_timesteps - self.start,
                **changes,
                "optimizer_epochs": self.model._n_updates - self.last_updates,
                "parameter_change_l2_from_start": delta,
                "parameter_sha256": _bundle.parameter_digest(self.model),
            }
        )
        self.last_updates = self.model._n_updates
        write_json(
            self.path,
            {"initial_parameter_sha256": self.initial_digest, "updates": self.events},
        )

    def _on_rollout_start(self):
        self.record_update()

    def _on_step(self):
        return True

    def _on_training_end(self):
        self.record_update()


def operation_modes(values):
    """Validate the standalone CLI's legacy mode tuple."""
    modes = tuple(values)
    if (
        not modes
        or len(set(modes)) != len(modes)
        or any(m not in DEFAULT_MODES for m in modes)
    ):
        raise ValueError("operation modes must be distinct fixed_sampled/online names")
    return modes


def sb3_settings(
    hyperparameters,
    n_steps,
    batch_size,
    learning_rate=None,
    ent_coef=None,
    target_kl=None,
):
    """Resolve ``online_sb3_v1`` settings; omitted values take the protocol defaults."""
    from scripts.rl.agents.config import validate_training_settings

    settings = {
        "n_steps": n_steps,
        "batch_size": batch_size,
        "learning_rate": (
            min(
                hyperparameters.get("learning_rate", SB3_PARENT_LEARNING_RATE_FALLBACK),
                SB3_LEARNING_RATE_CAP,
            )
            if learning_rate is None
            else learning_rate
        ),
        "target_kl": SB3_DEFAULTS["target_kl"] if target_kl is None else target_kl,
        "ent_coef": SB3_DEFAULTS["ent_coef"] if ent_coef is None else ent_coef,
    }
    validate_training_settings(settings)
    if batch_size > n_steps or n_steps % batch_size:
        raise ValueError("online batch size must divide its rollout")
    return settings


def sb3_collaborators(**overrides):
    """The callables the SB3 protocol uses; the standalone CLI passes its own module names through."""
    from scripts.rl.env.config import read_scenario_identity
    from scripts.rl.env.mesh_env import MeshRlEnv
    from scripts.rl.policy.compat import check_compatibility
    from scripts.rl.policy.episode_review import endpoint_metrics
    from scripts.rl.policy.reward_matrix import write_reward_matrix

    names = dict(
        read_bundle=_bundle.read_bundle,
        selection_from_manifest=_bundle.selection_from_manifest,
        eval_selection=_bundle.eval_selection,
        parameter_digest=_bundle.parameter_digest,
        read_scenario_identity=read_scenario_identity,
        check_compatibility=check_compatibility,
        MeshRlEnv=MeshRlEnv,
        MaskablePPO=MaskablePPO,
        ActionMasker=ActionMasker,
        configure=configure,
        ModelPolicy=ModelPolicy,
        run_episode=run_episode,
        episode_metrics=episode_metrics,
        endpoint_metrics=endpoint_metrics,
        write_reward_matrix=write_reward_matrix,
        UpdateRecorder=UpdateRecorder,
        now_iso=now_iso,
        sha256_file=sha256_file,
        write_json=write_json,
    )
    names.update(overrides)
    return SimpleNamespace(**names)


def sb3_operate(
    bundle,
    env,
    initial,
    seed,
    destination,
    settings,
    learn,
    collaborators=None,
    track_optimizer=True,
):
    """One SB3 episode on a reset, compatibility-checked env; ``learn`` selects online vs frozen sampled."""
    c = collaborators or sb3_collaborators()
    destination = Path(destination)
    budget = env.contract["num_decisions"]
    n_steps, batch_size = settings["n_steps"], settings["batch_size"]
    if n_steps > budget or n_steps < 2 or batch_size < 2:
        raise ValueError("online rollout must fit within the episode")
    model = c.MaskablePPO.load(
        bundle.model_path,
        env=c.ActionMasker(env, lambda e: e.unwrapped.action_masks()),
        device="cpu",
        n_steps=n_steps,
        batch_size=batch_size,
        learning_rate=settings["learning_rate"],
        ent_coef=settings["ent_coef"],
        target_kl=settings["target_kl"],
    )
    model.set_random_seed(seed)
    before = c.parameter_digest(model)
    optimizer_before = _bundle.optimizer_digest(model) if track_optimizer else None
    updates_before = int(model._n_updates) if track_optimizer else None
    events = []
    if not learn:
        result = c.run_episode(
            env, c.ModelPolicy(model, deterministic=False), seed, initial=initial
        )
        episode_dir = Path(result.episode_dir)
    else:
        model.set_logger(c.configure(str(destination / "ppo"), ["csv"]))
        callback = c.UpdateRecorder(destination / "weight_updates.json")
        callbacks = [callback]
        if budget % n_steps:
            from scripts.rl.agents.callbacks import MissionBudgetCallback

            callbacks.append(MissionBudgetCallback(model.num_timesteps + budget))
        model.learn(
            total_timesteps=budget, reset_num_timesteps=False, callback=callbacks
        )
        events = callback.events
        completed = [
            p.parent
            for p in destination.glob("episode-*/rl_episode.json")
            if json.loads(p.read_text())["status"] == "completed"
        ]
        if len(completed) != 1:
            raise RuntimeError(
                "online operation must complete exactly one episode per seed"
            )
        episode_dir = completed[0]
        if not events or c.parameter_digest(model) == before:
            raise RuntimeError(
                "online PPO completed without changing neural parameters"
            )
        model.save(str(destination / "adapted_model"))
    if not learn and c.parameter_digest(model) != before:
        raise RuntimeError("frozen sampled control changed neural parameters")
    metadata = json.loads((episode_dir / "rl_episode.json").read_text())
    if metadata["status"] != "completed" or metadata["steps"] != budget:
        raise RuntimeError("incomplete operation episode")
    return SimpleNamespace(
        model=model,
        episode_dir=episode_dir,
        metadata=metadata,
        budget=budget,
        events=events,
        initial_parameter_sha256=before,
        final_parameter_sha256=c.parameter_digest(model),
        initial_optimizer_sha256=optimizer_before,
        final_optimizer_sha256=_bundle.optimizer_digest(model)
        if track_optimizer
        else None,
        optimizer_epochs=int(model._n_updates) - updates_before
        if track_optimizer
        else None,
        untrained_tail_decisions=budget % n_steps if learn else 0,
    )


def run_online(
    run_dir,
    sim_binary,
    output,
    seeds,
    n_steps=120,
    batch_size=60,
    learning_rate=None,
    ent_coef=0.001,
    target_kl=0.02,
    model_selection="best",
    modes=DEFAULT_MODES,
    collaborators=None,
):
    """Standalone SB3 operation over several seeds, writing the legacy v3/v4 envelope unchanged.

    ``collaborators`` (see :func:`sb3_collaborators`) lets the standalone CLI keep its
    historical module-level names effective, including test substitutions.
    """
    c = collaborators or sb3_collaborators()
    modes = operation_modes(modes)
    bundle = c.read_bundle(run_dir, model_selection)
    manifest = bundle.manifest
    config = manifest["run_config"]
    selection = c.eval_selection(c.selection_from_manifest(manifest))
    settings = sb3_settings(
        manifest["hyperparameters"],
        n_steps,
        batch_size,
        learning_rate,
        ent_coef,
        target_kl,
    )
    if set(seeds) & {manifest["seed"]}:
        raise ValueError("online operation cannot reuse the training seed")
    binary_digest = c.sha256_file(sim_binary)
    live_identity = c.read_scenario_identity(config)
    output = Path(output)
    record_path = output / ONLINE_MANIFEST_NAME
    if record_path.exists():
        previous = json.loads(record_path.read_text())
        if (
            previous["status"] == "completed"
            and previous["bundle"] == bundle.describe()
            and previous["seeds"] == seeds
            and previous.get("settings") == settings
            and previous.get("binary_sha256") == binary_digest
            and previous.get("scenario_identity") == live_identity
            and tuple(previous.get("modes", DEFAULT_MODES)) == modes
        ):
            return previous
        raise ValueError(
            f"incomplete or changed online run at {output}; move it aside to retry"
        )
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"refusing to overwrite {output}")
    record = {
        "online_experiment_version": 3 if modes == DEFAULT_MODES else 4,
        "status": "running",
        "started_at": c.now_iso(),
        "bundle": bundle.describe(),
        "seeds": seeds,
        "episodes": [],
        "seed_roles": {
            "fixed_control": (
                "model-selection diagnostics; not held out"
                if set(seeds) & set((manifest.get("evaluation") or {}).get("seeds", []))
                else "held-out evaluation"
            ),
            "online": "adaptation experience; not learning-disabled evaluation",
        },
        "settings": settings,
        "binary_sha256": binary_digest,
        "scenario_identity": live_identity,
    }
    if modes != DEFAULT_MODES:
        record["modes"] = list(modes)
    output.mkdir(parents=True, exist_ok=True)
    c.write_json(record_path, record)
    try:
        for mode in modes:
            results = []
            for seed in seeds:
                destination = output / mode / f"seed-{seed}"
                env = c.MeshRlEnv(
                    sim_binary,
                    config,
                    seed=seed,
                    output_dir=str(destination),
                    band=manifest["band"],
                    selection=selection,
                )
                try:
                    initial = env.reset(seed=seed, options={"seed_source": "eval"})
                    c.check_compatibility(
                        manifest,
                        env,
                        live_identity=c.read_scenario_identity(config),
                        live_band=manifest["band"],
                        allow_different_scenario=False,
                    )
                    run = sb3_operate(
                        bundle,
                        env,
                        initial,
                        seed,
                        destination,
                        settings,
                        learn=mode == "online",
                        collaborators=c,
                        track_optimizer=False,
                    )
                    metrics = {
                        **c.episode_metrics(run.episode_dir, env.contract["num_links"]),
                        **c.endpoint_metrics(run.episode_dir),
                    }
                    record["episodes"].append(
                        {
                            "mode": mode,
                            "seed": seed,
                            "episode_dir": str(run.episode_dir),
                            "return": run.metadata["cumulative_reward"],
                            "metrics": metrics,
                            "initial_parameter_sha256": run.initial_parameter_sha256,
                            "final_parameter_sha256": run.final_parameter_sha256,
                            "update_cycles": len(run.events),
                            "untrained_tail_decisions": run.untrained_tail_decisions,
                        }
                    )
                    results.append(
                        SimpleNamespace(
                            status="completed",
                            seed=seed,
                            decisions=run.budget,
                            episode_dir=str(run.episode_dir),
                        )
                    )
                    c.write_json(record_path, record)
                finally:
                    env.close()
            c.write_reward_matrix(results, output / mode)
        record.update(status="completed", ended_at=c.now_iso())
        c.write_json(record_path, record)
        return record
    except BaseException as exc:
        record.update(
            status="failed", ended_at=c.now_iso(), error=f"{type(exc).__name__}: {exc}"
        )
        c.write_json(record_path, record)
        raise
