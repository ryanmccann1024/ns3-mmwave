# Train a policy {#mesh_sim_rl_train}

[TOC]

Train a MaskablePPO policy on the example scenario for 8,192 decisions, watch
it learn, and know exactly which PPO settings it used.

## 1\. Before you start

- You ran the pre-flight check in
  \ref mesh_sim_rl_configure "Configure an RL scenario", and `SIM_BIN`,
  `RUN_CONFIG` and `OUT` are still set.
- Working directory: `scratch/mesh-sim/`.
- Budget about 7 minutes. Training is one process; it starts a fresh
  simulator for every episode.

## 2\. Seed roles

Every seed has one job. Keeping the jobs apart is what makes the final result
honest.

| Seed | Role | Used by |
|---|---|---|
| 1 | Training: every training episode runs on this seed. It also seeds the network's initialization and PPO's sampling. | `train --seed 1` |
| 2 | Model selection: a deterministic episode on this seed every 256 decisions picks `best_model.zip` | `train --eval-seed 2` |
| 11–15 | Held out: the final comparison | \ref mesh_sim_rl_evaluate "Evaluate and compare" |

`train` refuses a model-selection seed equal to the training seed.
`evaluate` refuses a held-out seed that was used for training or model
selection, and says which seed and why.

## 3\. Train

```bash
.venv/bin/python -m scripts.rl.train \
  --sim-binary "$SIM_BIN" --run-config "$RUN_CONFIG" \
  --output-dir "$OUT/train" \
  m-ppo --total-timesteps 8192 --n-steps 256 --seed 1 \
  --checkpoint-every-steps 2048 --keep-checkpoints 2 \
  --eval-every-steps 256 --eval-episodes 1 --eval-seed 2
```

- **Option order matters.** Scenario options (`--sim-binary`, `--run-config`,
  `--output-dir`, `--band`, `--verbose`) and selection options
  (`--observation-preset`, `--reward-components`, …) go **before** `m-ppo`.
  PPO and cadence options go after it.
- **A timestep is one decision.** Training uses one environment, so 8,192
  timesteps is 409 complete episodes of 20 decisions plus 12 decisions of a
  410th that the budget cut off.
- **`--n-steps 256`.** PPO collects 256 decisions (12.8 episodes), then
  updates the network: 32 updates in all.
- **`--eval-every-steps 256`.** Every 256 decisions, the current policy plays
  one masked, deterministic episode on seed 2. If its return is the best so
  far, it is saved as `best_model.zip`. Those episodes never train the network.
- **`--checkpoint-every-steps 2048 --keep-checkpoints 2`.** A copy of the
  model every 2,048 decisions; only the newest two are kept.

SB3 prints `Using cpu device`, then one table per update and one line per
model-selection evaluation.

**Checkpoint:** after about 6 minutes (376 s here), the first evaluation lines
read

```
Eval num_timesteps=256, episode_reward=-20.00 +/- 0.00
...
New best mean reward!
...
Eval num_timesteps=512, episode_reward=15.60 +/- 0.00
...
New best mean reward!
```

and the run ends with

```
|    ep_rew_mean     | 15.6     |
| time/              |          |
|    fps             | 21       |
|    iterations      | 32       |
|    time_elapsed    | 372      |
|    total_timesteps | 8192     |
---------------------------------

Done. Model + logs in outputs/rl-tutorial/train
```

and `echo $?` prints `0`.

## 4\. Watch it learn

\image html rl-learning-curve.svg "Training run outputs/rl-tutorial/train: building-bypass-smoke, training seed 1, model-selection seed 2, 8,192 timesteps, n_steps 256. Top: every completed training episode's return (rl_episode.json), their rolling mean, and the deterministic model-selection return (evaluations.npz). Bottom: the policy's mean entropy after each update (ppo/progress.csv)."

How to read it:

- **The model-selection line jumps first.** At 256 decisions the network has
  not been updated yet and its deterministic choice scores −20, the same as
  holding. After the first update (512 decisions) it scores 15.6, the best
  possible, and stays there for all 32 evaluations. The **deterministic**
  policy (the most likely move every time) found the answer almost at once.
- **The training returns rise slowly.** Training episodes **sample** moves, so
  they explore. Their rolling mean climbs from about −8 over the first 20
  episodes to 15.6 over the last 20, and SB3's `ep_rew_mean` (the mean of the
  last 100 episodes) reaches 15.6 by the end. The gap between the two lines is
  exploration, not a bug.
- **Entropy falls, but not to zero.** It starts at 1.58, close to
  \f$\ln 5 = 1.61\f$ (all five moves equally likely), and settles near 0.85.
  Once node-b is out of the shadow every move scores +1, so the policy has no
  reason to prefer one; it stays uncertain about *where to wander* while being
  certain about *leaving the shadow*.

## 5\. What PPO was given

`scripts/rl/agents/mask_ppo.py` builds the model. These are every argument it
passes to `MaskablePPO`, with this run's values (the manifest's
`hyperparameters` block records them):

| `MaskablePPO` argument | Flag | Default | This run | What it does |
|---|---|---|---|---|
| `policy` | | `MaskableActorCriticPolicy` | same | An actor (move probabilities) and a critic (value estimate). |
| `seed` | `--seed` | `[scenario] seed` | 1 | Seeds torch, NumPy and the action sampling. |
| `n_steps` | `--n-steps` | 1024 | 256 | Decisions collected per update. |
| `batch_size` | `--batch-size` | 64 | 64 | Minibatch size: 256 / 64 = 4 minibatches per epoch. |
| `n_epochs` | `--n-epochs` | 10 | 10 | Passes over each rollout: 40 gradient steps per update. |
| `gamma` | `--gamma` | 0.95 | 0.95 | Discount per decision. Rewards 20 decisions ahead weigh \f$0.95^{20} = 0.36\f$. |
| `gae_lambda` | `--gae-lambda` | 0.95 | 0.95 | Bias/variance trade-off of the advantage estimate. |
| `learning_rate` | `--learning-rate` | 3e-4 | 3e-4 | Adam step size. |
| `clip_range` | `--clip-range` | 0.2 | 0.2 | How far one update may move the policy. |
| `ent_coef` | `--ent-coef` | 0.01 | 0.01 | Entropy bonus that keeps exploring. `--ent-coef-final` decays it linearly. |
| `target_kl` | `--target-kl` | none | none | Stops an update's epochs early when the KL divergence passes it. |
| `policy_kwargs.net_arch` | `--net-arch` | `64,64` | `[64, 64]` | Hidden widths, used for both the actor and the critic network. |
| `verbose`, `tensorboard_log` | `--verbose`, `--tensorboard-log` | 1, none | 1, none | Logging only. |

Everything else is the installed SB3 default (`stable_baselines3` and
`sb3_contrib` 2.9.0 here): value-loss weight 0.5, gradient-norm clip 0.5,
normalized advantages, no value clipping, tanh activations, orthogonal
initialization, a shared feature extractor, the Adam optimizer, and
`device="auto"`, which chose the CPU here. Saved models are always reloaded on
the CPU.

The objective PPO maximizes on each minibatch, with \f$\rho_t\f$ the ratio of
the new to the old probability of the action taken and \f$\hat A_t\f$ its
advantage:

\f[ L = \mathbb{E}_t\!\left[\min\!\left(\rho_t \hat A_t,\ \mathrm{clip}(\rho_t, 1-\epsilon, 1+\epsilon)\,\hat A_t\right)\right] - 0.5\,L_{\text{value}} + c_{\text{ent}}\,H[\pi] \f]

**How the mask enters.** For every slot, MaskablePPO replaces the logit of
every masked move with \f$-10^{8}\f$ before the softmax, so a masked move has
probability zero, both when sampling and when computing \f$\rho_t\f$ and the
entropy \f$H\f$. The mask comes from the env's `action_masks()`, which the
`ActionMasker` wrapper reads before every step. The action space is
`MultiDiscrete([5] * slots)`: one independent 5-way choice per slot, drawn
from one shared network.

## 6\. Other training options

Saving and model selection, after `m-ppo`:

| Option | Default | What it does |
|---|---|---|
| `--checkpoint-every-steps` | 0 (off) | Save `checkpoints/checkpoint_<N>_steps.zip` every N decisions. |
| `--keep-checkpoints` | 3 | Keep only the newest N checkpoints. |
| `--eval-every-steps` | 0 (off) | Run the model-selection evaluation every N decisions and save `best_model.zip`. |
| `--eval-episodes` | 1 | Episodes per model-selection evaluation. |
| `--eval-seed` / `--eval-seeds` | training seed + 1 | Model-selection seed, or an explicit list such as `201-210` (its count must equal `--eval-episodes`). |
| `--resume-run-dir`, `--resume-checkpoint` | none | Continue from a verified checkpoint of an earlier run. `--total-timesteps` then counts the restored steps too. Selection flags, the seed and every PPO setting cannot change. |

Selection and recording, before `m-ppo`: `--observation-preset`,
`--observation-parameters`, `--reward-components`, `--reward-weights`,
`--reward-parameters`, `--telemetry`, `--telemetry-every` and
`--decision-records`. They override `[rl]` in `run.ini`
(\ref mesh_sim_rl_configure "Configure an RL scenario", section 2).

`qr-dqn` is listed as a subcommand but is disabled: it prints
`qr-dqn is disabled in this version` and exits 1. Other algorithms:
\ref mesh_sim_rl_add_algorithm "Add an RL algorithm".

## 7\. Going further

- \ref scripts_rl_agents "scripts/rl/agents": the trainer and callbacks.
- \ref mesh_sim_rl_experiments "Experiments and operations": tune these
  settings with Optuna.

<!-- Provenance: run 2026-10-28 on building-bypass-smoke with binary
     build/scratch/mesh-sim/ns3.42-sim-debug (sha256 d7a2f4d1...6c9fe2), mesh-sim
     commit b54bfbe7 plus the working tree, macOS arm64, Python 3.11.9,
     stable_baselines3 2.9.0, sb3_contrib 2.9.0, torch 2.14.0. Output in
     outputs/rl-tutorial/train; log in outputs/rl-tutorial/logs/train.log.
     Wall time 376 s. Figure: docs/diagrams/rl-tutorial.py. -->

Previous: \ref mesh_sim_rl_configure "Configure an RL scenario" · Next: \ref mesh_sim_rl_read_training "Read a training run"
