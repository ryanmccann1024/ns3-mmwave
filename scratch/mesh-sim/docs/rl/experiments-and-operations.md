# Experiments and operations {#mesh_sim_rl_experiments}

[TOC]

Run many trainings and evaluations from one file. Then measure what a bigger
run will cost, tune PPO, and take the work to a cluster.

## 1\. Before you start

- You did \ref mesh_sim_rl_evaluate "Evaluate and compare" once by hand. A
  matrix runs exactly those commands for you.
- Working directory: `scratch/mesh-sim/`, with `SIM_BIN` and `OUT` set.
- `SIM_BIN` is a simulator you (the human) built. No tool on this page builds
  it; a binary older than the mesh-sim sources is refused, and you rebuild it
  from the `ns3-mmwave` root with `./ns3 build scratch/mesh-sim/sim`.

## 2\. Two kinds of matrix

| | Version 1 matrix | Version 2 batch |
|---|---|---|
| Use for | A small train/evaluate/compare grid on one scenario | Several scenarios, checks, baselines, checkpoints, frozen and online operations, optional finite selection, recovery |
| Run with | `scripts.rl.experiment` directly | `bash scripts/rl/run-experiments.sh` (or `scripts.rl.experiment`) |
| Execution | Sequential, inherited output | Dependency graph, bounded workers, per-task logs |
| Completion | The step folder's manifest | A per-task receipt validated against the task's own artifacts |
| Retry | Move or delete a blocked step folder | `resume`, which appends a new attempt |
| Sections | 5 to 7 | 3 and 4 |

Every field, path rule, state and flag of version 2 is in
\ref mesh_sim_rl_batch_reference "Batch experiment reference"; this page walks
through it once. Schema version numbers are in
\ref Contributing "Contributing".

## 3\. Run a batch

**Purpose.** Validate, plan, run, inspect and, after an interruption, resume
one version 2 batch with the maintained launcher.

**Prerequisites and versions.** The project `.venv`
(`python3 scripts/rl/bootstrap_venv.py`); a simulator binary built by the
human from the current sources. Declared versions are in `requirements.txt`;
no version has been tested with this workflow end to end.

**Working directory.** `scratch/mesh-sim/`. The launcher resolves relative
`--matrix`, `--output-root`, `--sim-binary` and `MESH_SIM_BIN` against the
directory you run it from, so it also works from elsewhere.

**Inputs.** The public example
`inputs/experiments/examples/coordination-smoke/`: `batch.json`, `run.ini`,
`nodes.json`, `buildings.json`, `reference.json`. Paths inside `batch.json`
resolve against that folder. Its `run.ini` gives 64 decisions per episode (64 s,
0.1 s ticks, 1 s decisions). It is a plumbing fixture, not a mission-performance
experiment.

**Commands.** One per block.

1. Validate. Reads the matrix and its assets, prints every task, and writes
   nothing; no binary needed.

```bash
bash scripts/rl/run-experiments.sh validate --matrix inputs/experiments/examples/coordination-smoke/batch.json
```

**Checkpoint** (executed; static only):

```text
matrix coordination-smoke (kind train): 27 tasks
  baseline 6, replay_gate 1, train 1, operate 16, curves 1, review 1, index 1
  baseline/rural-coverage-3-peers/scripted/diagnostic/seed-201  [f3933222b3]
  ...
  index/rural-coverage-3-peers  [96a46b79d3]
```

The 16 operation tasks are one training seed × two checkpoints (128 and
`final`) × four operations × two diagnostic seeds. Each line ends with the
task's key suffix.

2. Plan. Hashes the binary and every input without launching anything, refuses
   a stale binary, and writes `experiment_plan.json`. Proposed; unverified.

```bash
bash scripts/rl/run-experiments.sh plan --matrix inputs/experiments/examples/coordination-smoke/batch.json --sim-binary "$SIM_BIN" --output-root outputs/batch-smoke/coordination
```

3. Run. Proposed; unverified. Add `--dry-run` first if you want to see the
   exact command the launcher would `exec`.

```bash
bash scripts/rl/run-experiments.sh run --matrix inputs/experiments/examples/coordination-smoke/batch.json --sim-binary "$SIM_BIN" --output-root outputs/batch-smoke/coordination --workers 2
```

4. Status. Needs no binary. Proposed; unverified.

```bash
bash scripts/rl/run-experiments.sh status --output-root outputs/batch-smoke/coordination
```

5. Resume after an interruption, in a **separate** root so a deliberate stop
   cannot damage the successful one. Run step 3 with
   `--output-root outputs/batch-smoke/recovery`, interrupt it with Ctrl-C after
   checkpoint 128 is written, then prepare and inspect the proposal before
   resuming. Proposed; unverified.

```bash
bash scripts/rl/run-experiments.sh resume --output-root outputs/batch-smoke/recovery --prepare-only
```

```bash
bash scripts/rl/run-experiments.sh resume --output-root outputs/batch-smoke/recovery
```

**Expected outputs.** `experiment_plan.json` and the task folders in
\ref mesh_sim_rl_batch_layout "the output layout": a training run under
`models/`, operation results under `operations/`, baselines under
`baselines/`, the replay-gate check under `preflight/`, curves, reviews and comparisons under
`analysis/`, and the scenario index under `main/rural-coverage-3-peers/`.
Receipts under `state/steps/`, bindings under `state/bindings/`,
`runtime_identity.json`, `campaign_status.json` and per-task logs under
`local/` are written by the scheduler (`ops/local.py`, `ops/recovery.py`).

**Expected behavior and tolerances.** Training writes post-update checkpoints
at 128 and 256 decisions after 8 rollout updates; both frozen modes leave the
policy and optimizer digests unchanged; each online protocol reloads its
parent per seed. `status` reports `completed` (or `completed_with_warnings`).
The recovery root resumes from the checkpoint-128 training state and still
evaluates checkpoint 128. Learning results are not meaningful at this budget.

**Failure recovery.**

- `no simulator binary: pass --sim-binary or set MESH_SIM_BIN`: pass the binary.
- `simulator binary ... is older than ... mesh-sim source file(s)`: the human
  rebuilds; never bypass the check.
- `... differs from the plan for this matrix, binary and --rows; plans are
  immutable, use a new --output-root`: a changed matrix, binary or row filter
  needs a new root.
- A validation error names the field path, for example
  `row raw-delivery.training`; fix the matrix and validate again.

**Extension points.** Copy the example folder, then change one thing: a row's
reward or observation, an operation, a seed list, or `execution.workers`.
Kind-specific `checks` and `evaluate` examples are in
\ref mesh_sim_rl_batch_reference "the reference", section 16.

**Verification.** `scripts/rl/tests/experiments/test_matrix_v2.py` checks validation, the
plan, the 16-leaf identity and the launcher without a simulator
(\ref src_rl_policy_comparison_tests "Policy comparison tests").

**Provenance.** Step 1 executed 2026-10-29 on the working tree of commit
`b54bfbe7`, macOS arm64, static only: PASS for validation. Steps 2 to 5 are
proposed and unverified. The native smoke and the interrupted/resumed smoke are
human-run checks and are BLOCKED until executed. The scheduler, recovery and
reporting owners they need are implemented and covered by synthetic tests on
the fake simulator (`test_ops_local.py`, `test_ops_recovery.py`,
`test_gui_index.py`); that is not native execution.

## 4\. Read a batch root

**Where results are.** Each task has its own folder; nothing is shared between
tasks except the scenario index under `main/`, which only the reporting owner
writes. Operation folders encode the training seed, checkpoint, operation, seed
role and evaluation seed, plus a short key, so two runs of the same mode on
different checkpoints or seeds never share a folder.

**Completion.** A task is `completed` only when its receipt's kind-specific
check passes: a training run needs a completed manifest and matching counters,
an operation needs the requested seed's record, a replay gate needs its own
success test. An existing folder without a valid receipt is `blocked`, never
assumed done. Exit code 2 from an operation or `compare` is a recorded warning.
The batch ends `completed`, `completed_with_warnings`, `failed` or
`interrupted`; an incomplete comparison you allowed is recorded as such and
does not make the batch a success. `status` reads the receipts without
disturbing a running batch; `status --json` lists every task's state, detail
and receipt path.

**Two terminals.** Worker limits are per launcher. Two batches started in two
terminals add their workers unless both declare the same
`execution.resource_pool` directory and capacity, which shares one cap across
them. The same root cannot be run twice at once. No worker count is safe on
every machine; start with one.

**Recovery.** `resume` never reruns a completed task and never rewrites an
interrupted folder. It writes a full proposal first (`--prepare-only` stops
there), then appends a new attempt for each interrupted task. Interrupted
training restarts from its latest verified post-update checkpoint only when the
batch declares `execution.recovery: checkpoint`; otherwise, or with no safe
checkpoint, the task is `blocked` for review. Changed code, inputs, binary or
dependencies are refused; a deliberate change needs a new root. The proposal
lists one action per task (`keep`, `pending`, `retry`, `resume_checkpoint`,
`accept` or `blocked`). Details:
\ref mesh_sim_rl_batch_resume "Identity and resume".

## 5\. A version 1 matrix

One trained model on a few seeds says little: training is random, and so are
scenarios. A **matrix** names a scenario, a seed plan, a training budget and a
list of **rows**. Each row is one setup: an observation preset, an action
profile and a reward. The tool trains every row on every training seed,
evaluates each model on the held-out seeds, and compares everything at the end
with intervals across training runs.

\htmlonly
<div class="ms-gates">
<div class="ms-gate"><strong>1. Plan</strong><span>freeze every command</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>2. Train</strong><span>each row, each seed</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>3. Evaluate</strong><span>labeled by row</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate ms-gate-end"><strong>4. Compare</strong><span>across training runs</span></div>
</div>
\endhtmlonly

`inputs/experiments/bypass-smoke-matrix.json`:

```json
{
  "matrix_version": 1,
  "name": "bypass-smoke",
  "run_config": "inputs/baselines/building-bypass-smoke/run.ini",
  "seeds": {"training": [101, 102], "model_selection": 201, "held_out": "301-303"},
  "training": {"total_timesteps": 256, "n_steps": 64, "eval_every_steps": 128},
  "evaluation": {"model": "best", "policies": ["model", "hold", "random_valid"]},
  "rows": [
    {"name": "local-delivery", "observation_preset": "local_links_v1",
     "action_profile": "move_2d", "reward_components": ["delivery_ratio"], "reward_weights": [1.0]},
    {"name": "raw-delivery", ...},
    {"name": "local-connectivity", ...},
    {"name": "local-legacy", ...}
  ]
}
```

- **Rows are listed one by one.** The tool never takes a product of settings,
  so every combination you run is one you wrote down.
- **The three seed groups must not overlap.** `load_matrix` refuses a held-out
  seed that also trains or selects.
- **Budgets are smoke-sized.** 256 decisions per row and seed; the file's own
  description says it is not evidence of learning.

## 6\. Plan a version 1 matrix

```bash
.venv/bin/python -m scripts.rl.experiment plan \
  --matrix inputs/experiments/bypass-smoke-matrix.json \
  --output-root "$OUT/matrix" --sim-binary "$SIM_BIN" --rows local-delivery
```

`--rows local-delivery` keeps one row, so this example stays small.

**Checkpoint:**

```
train/local-delivery/train-seed-101  pending
evaluate/local-delivery/train-seed-101  pending
train/local-delivery/train-seed-102  pending
evaluate/local-delivery/train-seed-102  pending
compare  pending
```

`$OUT/matrix/experiment_plan.json` now holds every step's exact command. The
plan is frozen: re-planning the same root with a different matrix, binary or
`--rows` is refused. Use a new root.

## 7\. Run and check status

```bash
.venv/bin/python -m scripts.rl.experiment run \
  --matrix inputs/experiments/bypass-smoke-matrix.json \
  --output-root "$OUT/matrix" --sim-binary "$SIM_BIN" --rows local-delivery
.venv/bin/python -m scripts.rl.experiment status --output-root "$OUT/matrix"
```

`run` executes the pending steps one at a time in fresh processes, then always
runs `compare` last. It took 51 seconds here.

**Checkpoint:** each evaluation prints

```
model: mean_return=20.0 episodes=3/3 revalidated=0 mask_violations=0
hold: mean_return=20.0 episodes=3/3 revalidated=0 mask_violations=0
random_valid: mean_return=20.0 episodes=3/3 revalidated=0 mask_violations=0
```

`run` ends with the comparison, including two group lines:

```
local-delivery (group)        vs hold  delivery_ratio  +0.0000 [+0.0000, +0.0000]  t across 2/2 training runs, 3 common held-out seeds
local-delivery (group)        vs random_valid  delivery_ratio  +0.0000 [+0.0000, +0.0000]  t across 2/2 training runs, 3 common held-out seeds
```

and `status` shows every step `done`.

**What this result means.** `model`, `hold` and `random_valid` all scored
20.0, the maximum. This row's reward is `delivery_ratio`, and on this scenario
the NLOS link still carries the 10 Mbps flow, so almost every decision scores
+1 whatever the policy does. A reward that cannot tell good moves from bad
teaches nothing. Check that before spending a large budget; it is what the
`local-legacy` row (the C++ LOS reward used in the tutorial) is there for.

Layout under the root:

<!-- Output-folder figure. Listing from outputs/rl-tutorial/matrix (2026-10-28). -->
<div class="ms-outtree">
<div class="ms-ot-head"><span>File</span><span>What it holds</span><span>Read by</span></div>
<div class="ms-ot-row ms-ot-dir"><code>matrix/</code><span>One experiment root.</span><span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>experiment_plan.json</code><span>Every step's exact command, frozen at plan time.</span><span><span class="ms-ot-tag ms-ot-you">you</span><span class="ms-ot-tag ms-ot-plot">run</span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>train/&lt;row&gt;/train-seed-&lt;S&gt;/</code><span>An ordinary training run.</span><span><span class="ms-ot-tag ms-ot-plot">evaluate</span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>eval/&lt;row&gt;/train-seed-&lt;S&gt;/</code><span>An ordinary evaluation, labeled with the row.</span><span><span class="ms-ot-tag ms-ot-plot">compare</span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>comparison/</code><span><code>comparison.json</code>, <code>episodes.csv</code>, with per-model and group lines.</span><span><span class="ms-ot-tag ms-ot-you">you</span></span></div>
</div>

**Step state comes only from each step's folder.**

| Folder state | Step state |
|---|---|
| No folder | `pending` |
| A completed manifest | `done` |
| Anything else | `blocked` |

Nothing is ever deleted or overwritten for you. To retry a blocked step, move
or delete its folder. Exit code 2 from `evaluate` or `compare` (health
counters, overlap) is a warning, not a failure; the runner carries on.

## 8\. Measure before you scale

`ops.benchmark run` runs one task and records its wall time and peak memory.
A task is one row on one training seed: its train step, then its evaluate
step. `ops.benchmark estimate` scales that measurement to a whole matrix.

```bash
.venv/bin/python -m scripts.rl.experiment plan \
  --matrix inputs/experiments/bypass-smoke-matrix.json \
  --output-root "$OUT/bench" --sim-binary "$SIM_BIN" --rows local-delivery
.venv/bin/python -m scripts.rl.ops.benchmark run --output-root "$OUT/bench" --task-index 0
.venv/bin/python -m scripts.rl.ops.benchmark estimate \
  --benchmark "$OUT/bench/benchmark/task-0000.json" \
  --target-matrix inputs/experiments/bypass-smoke-matrix.json \
  --safety-factor 2.0 --output "$OUT/bench/benchmark/estimate.json"
```

**Checkpoint:** `run` prints

```
train/local-delivery/train-seed-101  exit 0  15.737s  tolerated
evaluate/local-delivery/train-seed-101  exit 0  8.374s  tolerated
```

and `estimate` prints, among its lines,

```
local-delivery  2 tasks  00:00:49 per task with safety factor
raw-delivery  warning: observation or reward selection differs from the benchmarked row; its Python and agent work was not measured
serial total 00:06:26; not a cluster estimate
```

The benchmark record (`task-0000.json`) also holds `seconds_per_timestep`
(0.061 here) and the peak memory of the process tree (415,360 KB). The warning
is honest: only the benchmarked row's own Python work was measured.

## 9\. Tune PPO

`ops.tune` runs an Optuna study. Each trial trains one row on one training seed
with sampled PPO settings and is scored by its `best_mean_reward` on the
model-selection seed. Held-out seeds are never used. Optuna is pinned
separately, in `requirements-tuning.txt` (`optuna==5.0.0`):

```bash
.venv/bin/python -m pip install -r requirements-tuning.txt
.venv/bin/python -m scripts.rl.ops.tune --study inputs/experiments/bypass-smoke-study.json \
  --output-root "$OUT/tune" --sim-binary "$SIM_BIN" --dry-run
```

**Checkpoint:** Optuna 5.0.0 was already installed here, so the `pip` line was
not run. The dry run prints three candidate settings with their exact training
commands, then

```
trial 0000 params: n_steps=64 gamma=0.9394568308296805 ent_coef=0.01694906074981449
...
dry run: no output directory, record, or process was created
```

Drop `--dry-run` to run the trials, and add `--resume` to continue a stopped
study. To use a result, copy the chosen values into the `training` block of a
new matrix by hand. The searchable settings are `n_steps`, `gamma`,
`ent_coef`, `learning_rate`, `batch_size`, `n_epochs`, `gae_lambda`,
`clip_range`, `target_kl` and `ent_coef_final`
(`agents.config.PPO_SEARCH_PARAMETERS`).

## 10\. Cluster runs and fetching results

These were **not run** for this page (unverified here). They need a SLURM
cluster. Benchmarking, tuning and cluster submission work on version 1 plans
only; cluster execution of version 2 batch tasks is deferred work.

| Command | What it does |
|---|---|
| `ops.cluster plan` | Previews the job array for a plan and a cluster config, from `scripts/rl/ops/cluster-config.example.json`. |
| `ops.cluster submit` | Submits tasks as array jobs. Use `--tasks 0 --no-compare` for a canary. |
| `ops.cluster status`, `resume`, `cancel` | Tracks jobs from saved receipts; resubmits only what failed or never ran. |
| `ops.run_task` | Runs one task (or the comparison) on this host, without a scheduler. |
| `ops.fetch` | Copies chosen results (`comparison`, `manifests`, `inputs`, `logs`) from a remote root with rsync into a fresh local folder. |

Make the plan on the cluster, on its shared filesystem, with a binary built
there. A laptop plan embeds laptop paths. If the scheduler cannot be queried, a
job's state is `unknown`, and that blocks resubmission rather than risking
duplicates. The full workflow, file formats and recovery rules:
\ref scripts_rl_ops "Experiment operations".

## 11\. Campaigns and their replacements

Larger studies used to have their own launchers: `scripts.rl.campaign`,
`adaptive_campaign`, the `mission_*` runners and the `phase_one` …
`phase_nine` packages, each preparing private inputs under `inputs/custom/`
(not in a public checkout). These duplicated runtime modules were removed on
2026-10-30. Their source-backed contracts are documented here. New studies
are version 2 batches with explicit stages, checks and, where a study used
automatic selection, a named selection rule. The full mapping is in
\ref mesh_sim_rl_batch_retired "Retired commands and their replacements";
the [mission reward reference](mission-rewards.md) documents the retained formulas.

These tools stay supported:

| Tool | What it runs |
|---|---|
| `scripts.rl.preflight_campaign` | Checks a freshly built binary's coverage, obstacle and proximity features before a study. |
| `scripts.rl.online` | Keeps a trained policy learning during operation, against a matched frozen control. Its legacy record versions are ambiguous; see \ref mesh_sim_rl_batch_protocols "Operation protocols". |
| `scripts.rl.scenario_check` | The checks-only reference campaign with its own CLI. |

The historical private `inputs/custom/**/run-*.sh` launchers are immutable
records of what was run, not supported launchers. The [mission reward reference](mission-rewards.md) documents the retained reward families.

## 12\. Going further

- \ref mesh_sim_rl_batch_reference "Batch experiment reference": every
  version 2 field, path rule, state, protocol and flag.
- \ref scripts_rl_ops "Experiment operations": benchmark, tune, cluster and
  fetch in full.
- \ref scripts_rl_comparing_policies "Comparing policies": the version 1
  matrix file format.

<!-- Provenance: version 1 plan, run, status, benchmark run/estimate and tune
     --dry-run executed 2026-10-28 with build/scratch/mesh-sim/ns3.42-sim-debug
     (sha256 d7a2f4d1...6c9fe2), mesh-sim commit b54bfbe7 plus the working tree,
     macOS arm64. Outputs in outputs/rl-tutorial/{matrix,bench}; logs in
     outputs/rl-tutorial/logs/. pip install, cluster and fetch commands:
     unverified. Version 2 batch: validate executed 2026-10-29 (static);
     plan/run/status/resume proposed and unverified; native smoke BLOCKED until
     the human runs it. -->

Previous: \ref mesh_sim_rl_assumptions "Every assumption" · Next: \ref mesh_sim_rl_batch_reference "Batch experiment reference"
