# Read a training run {#mesh_sim_rl_read_training}

[TOC]

What the training run from \ref mesh_sim_rl_train "Train a policy" wrote,
which file answers which question, what its manifest guarantees, and what the
trained policy actually does.

## 1\. Before you start

- `$OUT/train` exists from \ref mesh_sim_rl_train "Train a policy".
- Working directory: `scratch/mesh-sim/`.

## 2\. What the run wrote

<!-- Output-folder figure. Styles: .ms-outtree in theme/mesh-sim.css. Listing
     from outputs/rl-tutorial/train (2026-10-28): 411 episode folders, 65
     model-selection episode folders and 32 checkpoint-<N> folders under eval/,
     54 MB in all. -->
<div class="ms-outtree">
<div class="ms-ot-head"><span>File</span><span>What it holds</span><span>Read by</span></div>
<div class="ms-ot-row ms-ot-dir"><code>train/</code><span>One training run, 54 MB here.</span><span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>train_manifest.json</code><span>Status, seeds, settings, the contract, observation and reward schemas, scenario fingerprints, every model file's digest. <b>Read this first.</b></span><span><span class="ms-ot-tag ms-ot-you">you</span><span class="ms-ot-tag ms-ot-plot">evaluate</span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>maskable_ppo_mesh.zip</code><span>The final model, after 8,192 decisions.</span><span><span class="ms-ot-tag ms-ot-plot">evaluate</span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>best_model.zip</code><span>The model with the best model-selection return so far: here the one from 512 decisions.</span><span><span class="ms-ot-tag ms-ot-plot">evaluate</span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>checkpoints/</code><span><code>checkpoint_6144_steps.zip</code>, <code>checkpoint_8192_steps.zip</code>: the newest <code>&#45;&#45;keep-checkpoints</code>.</span><span><span class="ms-ot-tag ms-ot-plot">evaluate</span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>ppo/progress.csv</code><span>One row per PPO update: mean return, entropy, value loss, KL, clip fraction.</span><span><span class="ms-ot-tag ms-ot-you">you</span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>evaluations.npz</code><span>Model-selection returns at each evaluation (SB3 format).</span><span><span class="ms-ot-tag ms-ot-you">you</span></span></div>
<div class="ms-ot-row ms-ot-l1 ms-ot-dir"><code>eval/</code><span>The model-selection episodes on seed 2.</span><span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>checkpoint-&lt;N&gt;/</code><span><code>reward_matrix.json</code> and <code>.csv</code>: reward per decision for the evaluation at N decisions. 32 here.</span><span><span class="ms-ot-tag ms-ot-you">you</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>episode-NNNN/</code><span>65 here: 32 completed (one per evaluation) and 33 with zero steps (the first reset and one automatic reset after each evaluation). Each has <code>steps.jsonl</code>.</span><span><span class="ms-ot-tag ms-ot-viz">visualizer</span></span></div>
<div class="ms-ot-row ms-ot-l1 ms-ot-dir"><code>episode-NNNN/</code><span>One folder per training episode, 411 here.</span><span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>rl_episode.json</code><span>Status, decisions, cumulative reward, seed, command, schema hashes.</span><span><span class="ms-ot-tag ms-ot-you">you</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>sim_stderr.log</code><span>The simulator's stderr. Check here when an episode failed.</span><span><span class="ms-ot-tag ms-ot-you">you</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>run.log</code>, <code>inputs/</code>, <code>seed-1/</code><span>An ordinary simulator run: resolved settings, archived inputs, the CSVs and <code>summary.json</code>.</span><span><span class="ms-ot-tag ms-ot-plot">plotting</span><span class="ms-ot-tag ms-ot-viz">visualizer</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>steps.jsonl</code><span>Only with <code>telemetry = steps</code>: one record per saved decision. Not written in this run.</span><span><span class="ms-ot-tag ms-ot-you">you</span></span></div>
</div>

Each episode folder is a complete simulator run, so everything from
\ref mesh_sim_first_result "Understand the result" applies inside `seed-1/`.

## 3\. Did the run finish?

```bash
python3 -c "import json; m = json.load(open('$OUT/train/train_manifest.json')); print(m['status'], m['num_timesteps'], m['best_mean_reward'])"
```

**Checkpoint:** `completed 8192 15.6`.

A failed run says `failed` and has an `error` string. `completed` is the only
status evaluation accepts.

## 4\. Check the bundle

`inspect_model` reads the manifest and checks every recorded model file's
SHA-256 digest. It never loads the network.

```bash
.venv/bin/python -m scripts.rl.inspect_model --run-dir "$OUT/train"
```

**Checkpoint:** exit code 0, and (paths shortened):

```
manifest        version 7, status completed
timesteps       8192
algorithm       MaskablePPO
seed            1 (source: cli)
control mode    centralized, band -
contract        mesh_move_2d_v2
  nodes N       2   slots M 1
  obs_dim       6   mask_dim 5   num_decisions 20
selection
  observation_presetlocal_links_v1 (source: run.ini)
  reward_components [] (source: default)
  reward_weights    [] (source: default)
  telemetry         none (source: default)
  telemetry_every   1 (source: default)
observation     local_links_v1 dtype float32 dim 8
  sha256        5f3f34f19b8640316cf9bf70a9e7cb67033ac7474040b78575a087bcecaeee12
reward          authority cpp
  cpp reward    all_links_los window mean
  sha256        12d179c6251f16261c3314aa2feb6ea68df85bc872edd4fa772015c84b06c73d
scenario identity
  run_ini_sha256        7fe68026bac6487d3050b790184101beaaabc9b9b143f764d8434a1579ab686e
  nodes_json_sha256     e98578d17527d84beaf8270c1eee0b6b672cd436137323b3612376b981a8d07f
  buildings_json_sha256 9684a83da6a4795c553f9265b7de9a5db886ba92e872776ce97f5e3c9dd652be
  jammers_json_sha256   -
models
  final       exists=true digest=ok .../train/maskable_ppo_mesh.zip
  best        exists=true digest=ok .../train/best_model.zip
  checkpoint  exists=true digest=ok steps=6144 .../checkpoints/checkpoint_6144_steps.zip
  checkpoint  exists=true digest=ok steps=8192 .../checkpoints/checkpoint_8192_steps.zip
evaluation      every_steps=256, episodes=1, seed=2, seeds=2, seed_source=eval, ...
best_mean_reward 15.6
package versions (recorded vs installed)
  gymnasium           1.3.0 / 1.3.0
  sb3_contrib         2.9.0 / 2.9.0
  stable_baselines3   2.9.0 / 2.9.0
  torch               2.14.0 / 2.14.0
  ...
python          3.11.9
platform        Darwin arm64
```

How to read it:

- **`status completed`.** A failed run still exits 0 here, so read this line.
- **`reward authority cpp`.** No reward components were selected, so the
  policy learned from the C++ `all_links_los` reward.
- **The two `sha256` lines** match the pre-flight check. They are part of the
  identity evaluation checks.
- **`digest=ok` on every model.** The files are the ones training wrote.
- **Package versions.** Recorded at training against installed now. The
  recorded set is everything in `requirements.txt`.

| Exit | Meaning |
|---|---|
| 0 | Manifest readable. Check its `status` line. |
| 1 | Manifest missing or unreadable. |
| 2 | A model file is missing or its digest changed. |

## 5\. What is inside the manifest

`train_manifest.json` is the run's identity card. Evaluation reads it, not the
`run.ini`.

| Field | What it records |
|---|---|
| `manifest_version`, `status`, `error`, `started_at`, `ended_at` | Format version, `running` / `completed` / `failed`, and why. |
| `algorithm` | `MaskablePPO`, always, for runs from `train`. |
| `seed`, `seed_source` | The training seed and where it came from (`cli` or `run.ini`). |
| `hyperparameters` | Every PPO and cadence setting, defaults included. |
| `contract`, `control_mode` | The simulator's `init`: slots, node IDs, `obs_dim`, bounds, speeds, reward settings. |
| `selection`, `telemetry` | The resolved observation preset, reward components, weights, parameters, telemetry, and each one's source. |
| `observation_schema`, `reward_schema` | The full definitions and their SHA-256. |
| `scenario_identity`, `run_config`, `sim_binary`, `band` | SHA-256 of `run.ini`, `nodes.json`, and of `buildings.json` and `jammers.json` when they exist; the paths used. |
| `model_path`, `model_sha256`, `best_model_path`, `best_model_sha256`, `best_mean_reward`, `checkpoints` | Each model file with its SHA-256 and timestep count. |
| `evaluation`, `evaluation_state` | Model-selection cadence, episodes and seeds, and how many evaluations ran. |
| `resume` | For a resumed run: the parent checkpoint, and what was restored and what restarted. |
| `package_versions`, `python_version`, `platform` | The environment it ran in. |

The current `manifest_version` and every other schema version are listed in
\ref Contributing "Contributing".

## 6\. Did it learn?

Every training episode records its return in `rl_episode.json`. Compare the
first and last ten:

```bash
python3 - <<'PY'
import glob, json
runs = [json.load(open(f)) for f in sorted(glob.glob("outputs/rl-tutorial/train/episode-*/rl_episode.json"))]
done = [r["cumulative_reward"] for r in runs if r["status"] == "completed"]
print(len(runs), len(done), round(sum(done[:10]) / 10, 2), round(sum(done[-10:]) / 10, 2))
PY
```

**Checkpoint:** `411 409 -13.0 15.6`.

- **411 folders, 409 completed.** Episode 0 is a probe: training resets once
  to learn the action and observation sizes before it wraps the env, and that
  episode stops at once (`status interrupted`, `stop_reason reset`, zero
  steps). Episode 410 was cut off after 12 decisions when the budget ran out
  (`stop_reason close`). Always filter by `status` before averaging.
- **The mean return rose from −13.0 to +15.6.** The last ten training
  episodes, still sampling, all scored the best possible return.

The model-selection episodes score what the deterministic policy does:

```bash
.venv/bin/python -c "import numpy as np; d = np.load('$OUT/train/evaluations.npz'); print(d['timesteps'][:4], d['results'].ravel()[:4])"
```

**Checkpoint:** `[ 256  512  768 1024] [-20.   15.6  15.6  15.6]`. The first
evaluation ran before any update. Every later one scored 15.6, so
`best_model.zip` is the model from 512 decisions and was never replaced: a
later model has to be strictly better to replace it.

**Reward per decision.** `eval/checkpoint-8192/reward_matrix.json` holds the
reward of every decision of the evaluation at 8,192 decisions. Its mean curve
starts `-1.0, -1.0, 0.6, 1.0, 1.0`: two NLOS decisions, one partly LOS, then
LOS until the end.

**PPO's own health.** `ppo/progress.csv` has one row per update. This run:

| Column | Healthy sign | This run (update at 512 → at 8,192) |
|---|---|---|
| `rollout/ep_rew_mean` | Rises over training. | −9.77 (first) → 15.58 |
| `train/entropy_loss` | Becomes less negative slowly. A sudden collapse toward 0 means the policy stopped exploring. | −1.58 → −0.84 |
| `train/approx_kl`, `train/clip_fraction` | Small (KL around 0.01, clip fraction a few percent to ~0.1). Large values mean unstable updates. | 0.006, 0.01 → 0.013, 0.08 |
| `train/explained_variance` | Rises toward 1 as the value function learns. | 0.004 → 0.13 |

Explained variance stays low here because, once LOS, every state's return is
the same +1 per remaining decision regardless of position: there is little
for the critic to explain. That is a property of this reward, not a failure.

## 7\. What the trained policy does

\image html rl-trajectories.svg "Left: node-b's path on held-out seed 11 for the trained model (final, 8,192 decisions), random_valid and hold, every tick; filled markers are LOS ticks. From the evaluation in outputs/rl-tutorial/eval on the next page. Right: the first three and last three completed training episodes on seed 1, from each episode's positions.csv."

- **The model leaves the shadow by the shortest route.** South at full speed
  to y = −100, LOS from tick 23 (y = −46). North would have been equally good;
  the network happened to prefer south.
- **Then it wanders.** East to the corner, then back and forth along the
  bottom wall. The reward cannot tell this from holding.
- **Training changed the paths.** The first three training episodes are random
  walks from an untrained network: LOS on 75, 95 and 17 of 201 ticks, returns
  −5.0, −1.0 and −16.6. The last three all go straight south, stay near the
  bottom wall, are LOS on 178 of 201 ticks and return 15.6.
- **`hold` never leaves the shadow** (−20); **`random_valid`** got out
  partway through (−4.6).

## 8\. Look inside one episode's decisions

Training writes no `steps.jsonl` unless you ask for it with
`--telemetry steps`. Evaluation and the model-selection episodes always write
one. Each line after the header holds the decision number, the action that
produced the window, the mask, `revalidated_slots`, the raw facts, the reward
and an `obs_sha256`. The observation itself is not stored; replay rebuilds it
from the facts and checks it against the fingerprint:

```bash
.venv/bin/python -c 'from scripts.rl.env.telemetry import replay_file; import sys; print(replay_file(sys.argv[1]))' \
  "$OUT/eval/model/episode-0000/steps.jsonl"
```

**Checkpoint** (after \ref mesh_sim_rl_evaluate "Evaluate and compare"):
`ReplaySummary(records=21, obs_mismatches=0, reward_mismatches=0)`.

Every field, with a worked decode:
\ref src_rl_reading_output "Reading an RL output directory". For a richer
per-decision record that joins each action to the policy's preferences, see
\ref src_rl_decision_records "Decision records".

## 9\. Going further

- \ref scripts_rl "scripts/rl", section 7: the output reference, including
  reward matrices.
- \ref src_rl_policy_inputs "Policy inputs", section 7: decoding facts by hand.

<!-- Provenance: outputs/rl-tutorial/train and outputs/rl-tutorial/eval,
     2026-10-28; inspect_model output in outputs/rl-tutorial/logs/inspect.log.
     Figure: docs/diagrams/rl-tutorial.py. -->

Previous: \ref mesh_sim_rl_train "Train a policy" · Next: \ref mesh_sim_rl_evaluate "Evaluate and compare"
