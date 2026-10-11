"""Continue PPO learning during moving-jammer operation with a matched sampled control."""

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.logger import configure

from scripts.rl.cli_common import now_iso, write_json
from scripts.rl.env.config import read_scenario_identity
from scripts.rl.env.mesh_env import MeshRlEnv
from scripts.rl.policy.bundle import read_bundle, selection_from_manifest, eval_selection
from scripts.rl.policy.compat import check_compatibility
from scripts.rl.policy.evaluate import ModelPolicy, run_episode, episode_metrics
from scripts.rl.policy.episode_review import endpoint_metrics
from scripts.rl.policy.reward_matrix import write_reward_matrix
from scripts.sim_support import parse_seed_spec


def parameter_digest(model):
    digest = hashlib.sha256()
    for name, tensor in sorted(model.policy.state_dict().items()):
        digest.update(name.encode())
        digest.update(tensor.detach().cpu().numpy().tobytes())
    return digest.hexdigest()


class UpdateRecorder(BaseCallback):
    """Record actual parameter changes after each optimizer update cycle."""

    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.events = []

    def _on_training_start(self):
        self.start = self.model.num_timesteps
        self.last_updates = self.model._n_updates
        self.initial = {k: v.detach().cpu().clone() for k, v in self.model.policy.state_dict().items()}
        self.initial_digest = parameter_digest(self.model)

    def record_update(self):
        if self.model._n_updates == self.last_updates:
            return
        delta = sum(float(((value.detach().cpu()-self.initial[key])**2).sum())
                    for key, value in self.model.policy.state_dict().items())**.5
        changes = {}
        for scope, prefixes in (("actor", ("mlp_extractor.policy_net", "action_net")),
                                 ("critic", ("mlp_extractor.value_net", "value_net"))):
            changes[scope+"_change_l2_from_start"] = sum(
                float(((value.detach().cpu()-self.initial[key])**2).sum())
                for key, value in self.model.policy.state_dict().items() if key.startswith(prefixes))**.5
        self.events.append({"decision": self.model.num_timesteps-self.start,
                            **changes,
                            "optimizer_epochs": self.model._n_updates-self.last_updates,
                            "parameter_change_l2_from_start": delta,
                            "parameter_sha256": parameter_digest(self.model)})
        self.last_updates = self.model._n_updates
        write_json(self.path, {"initial_parameter_sha256": self.initial_digest, "updates": self.events})

    def _on_rollout_start(self):
        self.record_update()

    def _on_step(self):
        return True

    def _on_training_end(self):
        self.record_update()


def run_online(run_dir, sim_binary, output, seeds, n_steps=120, batch_size=60):
    bundle = read_bundle(run_dir, "best")
    manifest = bundle.manifest
    config = manifest["run_config"]
    selection = eval_selection(selection_from_manifest(manifest))
    output = Path(output)
    record_path = output/"online_manifest.json"
    if record_path.exists():
        previous = json.loads(record_path.read_text())
        if previous["status"] == "completed" and previous["bundle"] == bundle.describe() and previous["seeds"] == seeds:
            return previous
        raise ValueError(f"incomplete or changed online run at {output}; move it aside to retry")
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"refusing to overwrite {output}")
    record = {"online_experiment_version": 1, "status": "running", "started_at": now_iso(),
              "bundle": bundle.describe(), "seeds": seeds, "episodes": [],
              "seed_roles": {"fixed_control": "held-out evaluation", "online": "adaptation experience; not learning-disabled evaluation"},
              "settings": {"n_steps": n_steps, "batch_size": batch_size,
                           "learning_rate": min(manifest["hyperparameters"].get("learning_rate", .0003), .0001),
                           "target_kl": .02, "ent_coef": .001}}
    output.mkdir(parents=True, exist_ok=True)
    write_json(record_path, record)
    try:
        for mode in ("fixed_sampled", "online"):
            results = []
            for seed in seeds:
                destination = output/mode/f"seed-{seed}"
                env = MeshRlEnv(sim_binary, config, seed=seed, output_dir=str(destination),
                                band=manifest["band"], selection=selection)
                try:
                    initial = env.reset(seed=seed, options={"seed_source": "eval"})
                    check_compatibility(manifest, env, live_identity=read_scenario_identity(config),
                                        live_band=manifest["band"], allow_different_scenario=False)
                    budget = env.contract["num_decisions"]
                    if budget % n_steps or n_steps < 2 or batch_size < 2:
                        raise ValueError("online rollout must divide the episode length exactly")
                    model = MaskablePPO.load(bundle.model_path, env=ActionMasker(env, lambda e: e.unwrapped.action_masks()),
                                             device="cpu", n_steps=n_steps, batch_size=batch_size,
                                             learning_rate=record["settings"]["learning_rate"],
                                             ent_coef=.001, target_kl=.02)
                    model.set_random_seed(seed)
                    before = parameter_digest(model)
                    events = []
                    if mode == "fixed_sampled":
                        result = run_episode(env, ModelPolicy(model, deterministic=False), seed, initial=initial)
                        episode_dir = Path(result.episode_dir)
                    else:
                        model.set_logger(configure(str(destination/"ppo"), ["csv"]))
                        callback = UpdateRecorder(destination/"weight_updates.json")
                        model.learn(total_timesteps=budget, reset_num_timesteps=False, callback=callback)
                        events = callback.events
                        completed = [p.parent for p in destination.glob("episode-*/rl_episode.json")
                                     if json.loads(p.read_text())["status"] == "completed"]
                        if len(completed) != 1:
                            raise RuntimeError("online operation must complete exactly one episode per seed")
                        episode_dir = completed[0]
                        if not events or parameter_digest(model) == before:
                            raise RuntimeError("online PPO completed without changing neural parameters")
                        model.save(str(destination/"adapted_model"))
                    metadata = json.loads((episode_dir/"rl_episode.json").read_text())
                    if metadata["status"] != "completed" or metadata["steps"] != budget:
                        raise RuntimeError("incomplete operation episode")
                    metrics = {**episode_metrics(episode_dir, env.contract["num_links"]), **endpoint_metrics(episode_dir)}
                    record["episodes"].append({"mode": mode, "seed": seed, "episode_dir": str(episode_dir),
                                               "return": metadata["cumulative_reward"], "metrics": metrics,
                                               "initial_parameter_sha256": before,
                                               "final_parameter_sha256": parameter_digest(model),
                                               "update_cycles": len(events)})
                    results.append(SimpleNamespace(status="completed", seed=seed, decisions=budget, episode_dir=str(episode_dir)))
                    write_json(record_path, record)
                finally:
                    env.close()
            write_reward_matrix(results, output/mode)
        record.update(status="completed", ended_at=now_iso())
        write_json(record_path, record)
        return record
    except BaseException as exc:
        record.update(status="failed", ended_at=now_iso(), error=f"{type(exc).__name__}: {exc}")
        write_json(record_path, record)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--sim-binary", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seeds", default="401-405")
    args = parser.parse_args()
    run_online(args.run_dir, args.sim_binary, args.output_dir, parse_seed_spec(args.seeds))


if __name__ == "__main__":
    main()
