@page scripts_rl scripts/rl

@brief Code map and command guide for the Python side of mesh-sim RL: environment, training, evaluation, comparison, and experiment matrices.

This package is the Python side of mesh-sim RL: a Gymnasium environment that
drives the simulator over a stdin/stdout JSON bridge, MaskablePPO training,
saved-policy evaluation and comparison, experiment matrices, and the batch
experiment runner. The wire contract is in [src/rl](@ref src_rl); the `run.ini` keys are
in the [run.ini reference](@ref src_config_run_ini_reference).

Run every command from `scratch/mesh-sim/`. Replace `<BIN>` with an
already-built simulator binary; no tool here builds it.

New to this workflow? The [RL guide](@ref mesh_sim_rl_start) walks the same
commands end to end with a checkpoint after each one. This page is the flag
reference it links back to.

## 1\. Commands at a glance

| Task | Command | Section |
| --- | --- | --- |
| Create or check the Python environment | `python3 scripts/rl/bootstrap_venv.py [--check]` | 2 |
| Check a scenario before training | `.venv/bin/python -m scripts.rl.validate_config` | 4.1 |
| Train a policy | `.venv/bin/python -m scripts.rl.train ... m-ppo ...` | 3, 4.2 |
| Summarize a training run | `.venv/bin/python -m scripts.rl.inspect_model` | 4.3 |
| Evaluate a saved policy against baselines | `.venv/bin/python -m scripts.rl.evaluate` | 4.4 |
| Compare evaluations (model minus baseline) | `.venv/bin/python -m scripts.rl.compare` | 5.1 |
| Plan, run, or check a version 1 experiment matrix | `.venv/bin/python -m scripts.rl.experiment plan\|run\|status` | 5.2 |
| Validate, plan, run, report or resume a version 2 batch | `bash scripts/rl/run-experiments.sh validate\|plan\|run\|status\|resume` | 9 |
| Benchmark, tune, run on SLURM, fetch results | `scripts.rl.ops` | 6 |
| Continue learning during operation (standalone) | `.venv/bin/python -m scripts.rl.online` | 9.2 |

## 2\. Setup

See the [Overview](@ref index) for the one-command environment setup.

```bash
python3 scripts/rl/bootstrap_venv.py          # creates .venv from requirements.txt
python3 scripts/rl/bootstrap_venv.py --check  # verify installed versions only
.venv/bin/python -m pytest scripts/rl/tests -q
```

Tuning needs Optuna, which you install by hand:

```bash
.venv/bin/python -m pip install -r requirements-tuning.txt
```

## 3\. Smoke run {#scripts_rl_smoke_run}

A 16-step MaskablePPO run that checks training works end to end:

```bash
.venv/bin/python -m scripts.rl.train \
  --sim-binary <BIN> \
  --run-config inputs/baselines/p0-smoke/run.ini \
  --output-dir outputs/rl-smoke-verification/rl \
  m-ppo --total-timesteps 16 --n-steps 16 --seed 1
```

- Global options (such as `--sim-binary`, `--run-config`, `--output-dir`, and
  `--band sub-6`) go before the `m-ppo` subcommand.
- Omitting `--seed` falls back to `[scenario] seed` in the `run.ini`. Every
  episode reuses that one seed; training does not yet support multiple seeds.
- Training refuses to start if the output directory already contains
  `train_manifest.json` or `maskable_ppo_mesh.zip`.
- For centralized control, use `--run-config
  inputs/baselines/centralized-multi-smoke/run.ini` and `--output-dir
  outputs/rl-multi`.
- Observation, reward, and telemetry flags are in
  [Selecting observations, rewards, and telemetry](@ref src_rl_policy_inputs_selection).

## 4\. Model lifecycle {#scripts_rl_model_lifecycle}

Four commands take a centralized run from configuration to evaluation:

1. `validate_config` checks the scenario.
2. `train` trains and writes `train_manifest.json`.
3. `inspect_model` summarizes the run.
4. `evaluate` runs the saved model and baselines and writes `eval_manifest.json`.

Each stage writes a manifest that the next one reads. All but `inspect_model`
need a built simulator binary. The [lifecycle test map](@ref src_rl_policy_lifecycle_tests)
lists the focused check for each stage.

### 4.1 Validate the configuration

```bash
.venv/bin/python -m scripts.rl.validate_config \
  --sim-binary <BIN> \
  --run-config inputs/baselines/building-bypass-smoke/run.ini \
  --output-dir outputs/bypass-validate --launch --json
```

- Without `--launch`, every check is static and no simulator process starts.
- With `--launch`, the simulator starts under `<output-dir>/validate/`, resets
  once, and reports the live contract. It does not complete an episode.

### 4.2 Train

```bash
.venv/bin/python -m scripts.rl.train \
  --sim-binary <BIN> \
  --run-config inputs/baselines/building-bypass-smoke/run.ini \
  --output-dir outputs/bypass-train \
  m-ppo --total-timesteps 1024 --n-steps 128 --seed 1 \
  --checkpoint-every-steps 512 --keep-checkpoints 2 \
  --eval-every-steps 256 --eval-episodes 1 --eval-seed 2
```

`train.py` requires the `m-ppo` subcommand; `qr-dqn` is disabled and exits 1.

| Flag | Default | Meaning |
| --- | --- | --- |
| `--checkpoint-every-steps` | `0` (off) | Save a checkpoint every N SB3 timesteps. |
| `--keep-checkpoints` | `3` | Prune the oldest checkpoints beyond this count. |
| `--eval-every-steps` | `0` (off) | Run the masked during-training evaluation every N timesteps. |
| `--eval-episodes` | `1` | Episodes per during-training evaluation. |
| `--eval-seed` | training seed + 1 | First seed for the during-training evaluation. |
| `--eval-seeds` | none | Explicit validation seed set, e.g. `201-210`. Its count must equal `--eval-episodes`. |
| `--checkpoint-timing` | `standard` | `after-update` saves checkpoints only after an optimizer update, without in-training validation, and writes `post_update_checkpoints.json`. |
| `--decisions-per-episode` | none | Asserts the simulator's decisions per episode against the native contract; never changes it. |
| `--continue-from-run-dir`, `--continue-model` | none, `final` | Continue a verified completed run (`final`, `best` or `checkpoints/<file>.zip`) to a larger cumulative `--total-timesteps`; exclusive with `--resume-run-dir`. |
| `--curriculum-schedule` | none | Existing curriculum schedule JSON for the training environment only. |

- Timesteps equal policy decisions because training uses one environment.
- [callbacks.py](@ref scripts/rl/agents/callbacks.py) wires SB3's checkpoint
  callback and `MaskableEvalCallback`: masked, deterministic evaluation on a
  separate environment and seed. It saves `best_model.zip` when the mean
  evaluation reward improves. Neither callback changes the training reward or
  action rules.

**Multiple-seed checkpoint evaluation.** `train ... m-ppo --eval-episodes 10
--eval-seeds 201-210` freezes the policy and runs the complete seed set at each
checkpoint. Without `--eval-seeds`, validation seeds run consecutively from
`--eval-seed` for `--eval-episodes` episodes. Centralized validation forces full
decision telemetry. The resulting reward matrices are described in
[Output](@ref scripts_rl_output).

### 4.3 Inspect

Summarizes a finished or failed run without loading the model. Add `--json` for
machine-readable output.

```bash
.venv/bin/python -m scripts.rl.inspect_model --run-dir outputs/bypass-train
```

It reads the manifest and saved files and prints: status, seed and seed source,
control mode, the contract shape, selection, schema digests, scenario digests,
every model file with `exists`/`digest_ok`, the evaluation settings, and
recorded versus installed package versions.

| Exit | Meaning |
| --- | --- |
| `0` | Manifest readable; every recorded model file present with a matching digest. |
| `1` | Manifest missing or unreadable. |
| `2` | A model file is missing or its digest differs. |

### 4.4 Evaluate

Evaluates a saved model against the `hold` and seeded `random_valid` baselines:

```bash
.venv/bin/python -m scripts.rl.evaluate \
  --sim-binary <BIN> \
  --run-dir outputs/bypass-train \
  --output-dir outputs/bypass-eval \
  --seeds 11,12,13 --policies model,hold,random_valid
```

| Flag | Meaning |
| --- | --- |
| `--model` | `final` (default), `best`, or `checkpoints/<file>.zip`. |
| `--run-dir` | Takes the run config, band, and selection from the training manifest. `--run-config` and `--band` may override them; the scenario check still runs, so an override may cause a mismatch. |
| `--seeds` | Comma-separated seeds and inclusive ranges: `301-303,310` equals `301,302,303,310`. |
| `--policies` | Default `model,hold,random_valid`. `geometric` and `optimization` are placement baselines (see the [placement-baseline guide](@ref scripts_baselines)); they are not in the default list. |
| `--label` | Names the experiment row an evaluation belongs to; [compare.py](@ref scripts/rl/compare.py) uses it to group evaluations of independently trained models. |
| `--allow-seed-overlap` | Downgrades the seed-overlap refusal to a warning (see 4.5). |
| `--allow-different-scenario` | Relaxes only the scenario-identity compatibility step. |
| `--baseline-cache-dir` | Reuses baseline trajectories across reward variants (see below). |
| `--stochastic-model` | Samples the saved policy, reseeded for each evaluation episode. |
| `--decision-record-seeds` | Writes decision-record sidecars only for this subset of `--seeds`; requires decision records to be enabled. |

**Policies.**

| Policy | Behavior |
| --- | --- |
| `model` | Deterministic MaskablePPO predictions under the live mask. |
| `hold` | Stops every controlled node. |
| `random_valid` | Picks uniformly among each position's valid actions, restarting its generator from each episode seed. |
| `geometric`, `optimization` | Placement baselines. `[baseline] movable_nodes` and `[rl] controlled_nodes` must name the same nodes (or both `all`); otherwise preparation fails and no episode runs. |

**Bundle and compatibility checks.**
[bundle.py](@ref scripts/rl/policy/bundle.py) treats the training manifest plus
a chosen final, best, or checkpoint ZIP as a saved model bundle and checks run
status and the ZIP's digest before loading.
[compat.py](@ref scripts/rl/policy/compat.py) then checks the live scenario and
policy contract, in the order given in the [policy package](@ref scripts_rl_policy).
`--allow-different-scenario` never bypasses the digest, structural,
observation-schema, or reward checks; the evaluation manifest records the run as
`overridden`.

**Baseline reuse.** A matrix evaluation can set `reuse_baselines=true`; the CLI
form is `--baseline-cache-dir`. The tool validates a binary, scenario, seed, and
planner identity, reuses immutable baseline trajectories, and rescales their
composed rewards. The evaluation manifest records the cache root as
`baseline_cache`; `compare` still requires the current `eval_manifest_version`
(see [Contributing](@ref Contributing)).

**Other behavior.**

- `evaluate` refuses an `--output-dir` inside the training run.
- The evaluation manifest is rewritten after every episode.
- If a seed's simulator dies mid-episode, its record keeps the episode
  directory and the partial return but reports every metric as `null`; the
  other seeds stay intact.

| Exit | Meaning |
| --- | --- |
| `0` | Every episode completed, with no revalidated slots and no masked actions. |
| `1` | An error, or an episode that did not complete. |
| `2` | Episodes completed, but the revalidated-slot or masked-action counter is non-zero. |

### 4.5 Seed discipline

Keep the training seed, the during-training evaluation (validation) seeds, and
the standalone evaluation seeds disjoint.

- With `model` in `--policies`, `evaluate` refuses to start when a requested
  seed is the training seed or a recorded model-selection seed, naming each
  seed and its role. Seed-overlap checks reserve all validation seeds,
  including when reading a best-model bundle.
- `--allow-seed-overlap` turns the refusal into a stderr `WARNING:` line,
  records `seed_roles.held_out: false`, and excludes the evaluation from
  across-run aggregates.
- Validation and held-out seeds must be disjoint from training.
- The during-training evaluation runs in its own environment, seed, and
  `<output-dir>/eval/` directory and contributes no gradient steps. Only that
  callback writes `best_model.zip`; standalone evaluation never informs model
  selection.

### 4.6 Diagnostic fixture

`inputs/baselines/building-bypass-smoke/` is the fixture used in the commands
above: two drones with one building between them.

- Going north or south around the building is the fastest route to line of
  sight.
- Action masks check bounds, not buildings, so moving west through the building
  also reaches line of sight once x < 90.
- Its `run.ini` header records the geometry and the expected hold and
  north-moving numbers.

Use it as a smoke fixture for the lifecycle tools; it is not a benchmark.

## 5\. Comparing policies and running an experiment matrix {#scripts_rl_comparing_policies}

[compare.py](@ref scripts/rl/compare.py) turns finished evaluations into paired
model-minus-baseline statistics. [experiment.py](@ref scripts/rl/experiment.py)
expands a named matrix into the train, evaluate, and compare steps that produce
them. The statistics and exit codes are explained in the
[policy package](@ref scripts_rl_policy).

```bash
.venv/bin/python -m scripts.rl.compare \
  --eval-dirs outputs/bypass-eval --output-dir outputs/bypass-compare

.venv/bin/python -m scripts.rl.experiment plan \
  --matrix inputs/experiments/bypass-smoke-matrix.json \
  --output-root outputs/bypass-matrix --sim-binary <BIN>

.venv/bin/python -m scripts.rl.experiment run \
  --matrix inputs/experiments/bypass-smoke-matrix.json \
  --output-root outputs/bypass-matrix --sim-binary <BIN>

.venv/bin/python -m scripts.rl.experiment status --output-root outputs/bypass-matrix
```

### 5.1 compare

| Flag | Meaning |
| --- | --- |
| `--eval-dirs DIR [DIR ...]` or `--plan experiment_plan.json` | Exactly one is required. |
| `--output-dir` | Required; must not already contain a training or evaluation manifest. |
| `--baselines a,b` | Restrict baselines; default is every non-`model` policy present. |
| `--json` | Print `comparison.json` instead of the summary lines. |

- Reads only `eval_manifest.json` files and refuses any whose
  `eval_manifest_version` is not the current `REQUIRED_MANIFEST_VERSION` (see
  [Contributing](@ref Contributing)).
- Writes `episodes.csv` (one row per evaluation directory, policy, and seed) and
  `comparison.json`. Neither file carries a timestamp, so repeating the command
  reproduces byte-identical output.
- A listed directory without a readable manifest becomes a
  `missing_evaluations` entry instead of a crash.

### 5.2 experiment

**Matrix file.**

- `run_config` names the scenario.
- `seeds` lists independent training, model-selection, and held-out evaluation
  seeds. `seeds.model_selection` accepts an integer, a list, or a range; a list
  means one episode per seed.
- Training and evaluation budgets are set in the matrix.
- Each `rows` entry chooses one observation preset, action profile, and
  weighted reward. Rows are explicit combinations, not a Cartesian product.

**Running.**

- Add `--rows local-delivery` to both `plan` and `run` to select one row; use
  the same filter for one output root.
- `run` executes pending steps sequentially in fresh processes and always runs
  `compare` last, so a missing run is reported.
- Step state comes from its manifest alone: `pending`, `done`, `partial`, or
  `blocked`. A blocked step is never re-run automatically; move or delete its
  directory.
- Re-planning the same root with a different matrix, binary, or `--rows` is
  refused; use a new root.

**Layout under `--output-root`:** `experiment_plan.json`,
`train/<row>/train-seed-<S>/`, `eval/<row>/train-seed-<S>/`, and
`comparison/{episodes.csv,comparison.json}`.

A matrix with `matrix_version: 2` is a batch (section 9); its fields are in
the [batch experiment reference](@ref mesh_sim_rl_batch_reference), not here.

**Example matrix.** `inputs/experiments/bypass-smoke-matrix.json` has four
explicit rows around one anchor on the bypass fixture, with smoke-sized
budgets. It exercises the harness. See
[Policy comparison tests](@ref src_rl_policy_comparison_tests).

## 6\. Benchmarking, tuning, cluster runs, and fetch

[scripts/rl/ops](@ref scripts_rl_ops) wraps an existing plan:

| Command | What it does |
| --- | --- |
| `benchmark` | Measures one `(row, training seed)` task. |
| `tune` | Searches the wired PPO knobs with Optuna. |
| `cluster` | Submits the plan to SLURM. |
| `fetch` | Copies results back. |

Commands, schemas, and refusals are documented on that page.

## 7\. Output {#scripts_rl_output}

| Step | Where |
| --- | --- |
| RL training | `<output-dir>/train_manifest.json`, `<output-dir>/maskable_ppo_mesh.zip`, and one `episode-NNNN/` per episode (below). With the cadence flags also `checkpoints/checkpoint_<N>_steps.zip`, `best_model.zip`, `evaluations.npz`, and `eval/episode-NNNN/` for the during-training evaluation. |
| RL evaluation | `<output-dir>/eval_manifest.json` and one `<policy>/episode-NNNN/` per evaluated policy and seed, with the same episode contents as training. |
| Compare | `<output-dir>/episodes.csv` and `<output-dir>/comparison.json`. |
| Experiment (version 1) | `experiment_plan.json`, `train/`, `eval/`, and `comparison/` under `--output-root`. |
| Batch (version 2) | `experiment_plan.json` and per-task folders under `models/`, `operations/`, `baselines/`, `preflight/`, `analysis/` and `main/`; see the [batch output layout](@ref mesh_sim_rl_batch_layout). |

For a file-by-file reading path, see
[Reading an RL output directory](@ref src_rl_reading_output). The direct-run
layout is in the [Overview](@ref readme_where_output_lands).

### 7.1 Episode directories

Each `episode-NNNN/` holds:

- `run.log`, `inputs/`, `sim_stderr.log`, `rl_episode.json`, and `seed-<seed>/...`;
- optional `steps.jsonl` (the decision trace);
- optional `policy_decisions.jsonl` and `policy_decisions_manifest.json`
  (`--decision-records`).

Startup and evaluation resets can leave zero-step interrupted episodes; filter
by `rl_episode.json` `status` when aggregating.

### 7.2 Manifests

Each file carries its schema version (`manifest_version`,
`eval_manifest_version`); the current numbers are in
[Contributing](@ref Contributing).

| File | Contents |
| --- | --- |
| `train_manifest.json` | `status`/`error`, `algorithm`, `seed` and `seed_source`, `control_mode`, the live `contract`, resolved `selection`, `observation_schema` and `reward_schema` (with SHA-256), `scenario_identity` (SHA-256 of `run.ini`, `nodes.json`, and when configured `buildings.json` and `jammers.json`), `model_path`/`model_sha256`, `best_model_path`/`best_model_sha256`/`best_mean_reward`, a `checkpoints` list of `{path, sha256, num_timesteps}`, the `evaluation` block (or `null`), `hyperparameters`, `package_versions`, `python_version`, `platform`, plus `num_timesteps`, `band`, `telemetry`, `evaluation_state` and the `resume` record. |
| `eval_manifest.json` | `status`/`error`, `label`; `seed_roles` (training, model-selection, held-out seeds, any overlap, whether overlap was allowed, whether held out); `training` (copied from the training manifest); `metric_source`; `episodes_expected` and `episodes_completed`; `scenario_identity`, `bundle` and `compatibility`. Every policy holds one record per requested seed, in seed order, with `status` `completed`, `failed`, or `not_run`; each record adds `error`, `return`, action-health counters, `metrics`, and a `summary_json` pointer that is never parsed. |

- Manifest `status` is `completed` (all expected episodes completed), `partial`
  (some did), or `failed` (aborted or nothing completed).
- Per-seed metrics and action-validity counts are in `eval_manifest.json`.
- `read_bundle` loads a training manifest at the current `MANIFEST_VERSION` or
  one of the earlier versions `bundle.py` still lists; any other version is
  refused with "retrain with current tooling".

### 7.3 Reward matrices and PPO logs

- Checkpoint and final evaluation write episode-by-decision reward matrices,
  means, sample standard deviations, and cumulative reward curves to
  `reward_matrix.{json,csv}`.
- Checkpoint matrices live under `train/.../eval/checkpoint-<step>/`; final
  matrices live under each policy's evaluation directory.
- Incomplete or sparsely recorded episodes do not become zero-padded rows.
- Default PPO logging writes `ppo/progress.csv` with entropy, value loss,
  approximate KL, clipping fraction, and explained variance. Explicit
  TensorBoard logging keeps its existing behavior.

## 8\. Control modes

The mode is chosen in `run.ini`, not on the command line.

| Mode | Selector | Action space | Notes |
| --- | --- | --- | --- |
| Legacy single-node | `controlled_node_id` | `Discrete(7)` | No `init` message. Python builds the mask from the `[rl]` bounds. The jammer is part of the scenario, not an agent. |
| Centralized multi-node | `controlled_nodes` | `MultiDiscrete([5]*M)` | C++ owns masks and clamping; Python builds observations and rewards from the raw facts. |

- The two selectors are mutually exclusive. Keys are in the
  [run.ini reference](@ref src_config_run_ini_reference); observation and
  reward selection is in
  [Selecting observations, rewards, and telemetry](@ref src_rl_policy_inputs_selection).
- C++ owns the simulation because ns-3 mobility, propagation, link evaluation,
  and routing live there and must stay deterministic and testable without
  Python. Python provides the Gymnasium and Stable-Baselines3 integration.
- In centralized mode, movement limits and action validity are decided once, in
  C++; Python never re-derives them.

## 9\. Batch experiments {#scripts_rl_batch}

A version 2 batch describes scenarios, seeds, checks, baselines, training,
operations, optional finite selection stages and execution limits in one JSON
file, and one launcher runs it:

```bash
bash scripts/rl/run-experiments.sh validate --matrix inputs/experiments/examples/coordination-smoke/batch.json
```

That `validate` writes nothing and needs no binary. `plan`, `run`, `status`
and `resume` follow the same pattern; `plan` and `run` need `--sim-binary <BIN>`
or `MESH_SIM_BIN`.

| Read | For |
| --- | --- |
| [Experiments and operations](@ref mesh_sim_rl_experiments) | The worked workflow: validate, plan, run, status, resume, and how to read the result. |
| [Batch experiment reference](@ref mesh_sim_rl_batch_reference) | Every field, path rule, flag, exit code, task state, protocol, schedule and selection rule. |
| [scripts/rl/experiments](@ref scripts_rl_experiments) | The pure batch domain owners. |

### 9.1 Owners

| Responsibility | Owner |
| --- | --- |
| Launcher | `run-experiments.sh` |
| CLI | `experiment.py` |
| Matrix validation, plan v3, selection | `experiments/config.py`, `experiments/plan.py`, `experiments/selection.py` |
| Local scheduler, receipts, batch status | `ops/local.py` |
| Identity checks and recovery proposals | `ops/recovery.py` |
| Curves, reviews, scenario index | `experiments/reporting.py` |
| Operation CLI used by tasks | `operate.py` |
| One operation on one seed, both online protocols, schedules, replay gates, reward audits, scripted baselines | `policy/operation.py`, `policy/online_adaptation.py`, `policy/schedules.py`, `policy/replay_gate.py`, `policy/reward_audit.py`, `policy/scripted.py` |
| After-update checkpoints, continuation, curriculum | `agents/post_update.py`, `policy/training.py`, `env/curriculum.py`; `train.py m-ppo` flags |
| Model bindings and digests | `policy/bundle.py` |

Replay-gate task flags are `--comparison`, `--parent-run-dir`, `--parent-model`,
`--case-json` and `--contact-audit`, in addition to source, seed configurations,
binary and output. Their defaults and accepted matrix fields are in the
[batch check contract](@ref mesh_sim_rl_batch_reference). A matrix `preflight`
check is refused during validation until the single-case adapter exists.

### 9.2 Standalone online operation

`online` loads one verified checkpoint per operation seed and runs the SB3
learning loop with short rollouts; its matched sampled control never trains.
Its command line is unchanged; the algorithm now lives in
`policy/operation.py`. It keeps writing its legacy `online_manifest.json`
envelope, whose version is ambiguous between protocols; batch operations write
a newer version with an explicit `protocol` field. See
[Operation protocols](@ref mesh_sim_rl_batch_protocols) and
[Contributing](@ref Contributing).

## 10\. Configuring experiments

Use one version 2 `batch.json` with the maintained `run-experiments.sh` launcher.
The [worked batch example](@ref mesh_sim_rl_experiments) starts with validation
and explains planning, running, status and resume. Copy and adapt
`inputs/experiments/examples/coordination-smoke/`; new experiment combinations
belong in configuration, not a new Python runner.

- `run.ini` describes one physical scenario and its `[rl]` input/reward selection.
- `batch.json` lists scenarios, reward/observation rows, PPO profiles, seed roles,
  budgets, checks, evaluation operations and optional selection stages.
- `scripts/sweep` expands native simulator INI grids; it does not train PPO.
- `scenario_check/` checks legal routes and purposeful reference behavior before
  training. `preflight_campaign` remains a compatibility CLI for stationary
  feature/difficulty checks; its implementation is `scenario_check/preflight.py`.
- Reward formulas and state-dependent priorities are in the [mission reward reference](../../docs/rl/mission-rewards.md).
  Numbered research records are not runtime packages.
  Completed outputs and model/configuration identities are preserved.

## 11\. Module layout

| File | Role |
| --- | --- |
| `__init__.py` | Registers `mesh_sim/MeshEnv-v0` with Gymnasium. |
| [bootstrap_venv.py](@ref scripts/rl/bootstrap_venv.py) | Creates `.venv` from `requirements.txt` and checks pins; does not build the simulator. |
| [cli_common.py](@ref scripts/rl/cli_common.py) | Shared CLI options, atomic JSON writes, hashes, package versions. |
| [validate_config.py](@ref scripts/rl/validate_config.py) | Pre-flight scenario check. |
| [train.py](@ref scripts/rl/train.py) | MaskablePPO training CLI; requires the `m-ppo` subcommand (`qr-dqn` is disabled and exits 1). |
| [inspect_model.py](@ref scripts/rl/inspect_model.py) | Training-run summary. |
| [evaluate.py](@ref scripts/rl/evaluate.py) | Policy and baseline evaluation CLI. |
| [compare.py](@ref scripts/rl/compare.py) | Paired comparison CLI. |
| [experiment.py](@ref scripts/rl/experiment.py) | `validate`/`plan`/`run`/`status`/`resume` for version 1 matrices and version 2 batches. |
| `run-experiments.sh` | Maintained batch launcher (section 9). |
| [online.py](@ref scripts/rl/online.py) | Standalone online-operation CLI (section 9.2). |
| `preflight_campaign.py` | Thin compatibility CLI for `scenario_check/preflight.py`. |

The CLI modules parse arguments and delegate lifecycle and artifact work to
`policy/training.py`, `policy/training_artifacts.py`, `policy/experiment.py`,
`policy/evaluate.py`, and the metric registry. Current saved schema versions
are listed in [Contributing](@ref Contributing).

| Directory | Contents |
| --- | --- |
| @ref scripts_rl_agents | MaskablePPO glue; exploratory `q_learning.py` (not on the training path). |
| @ref scripts_rl_env | Gymnasium env, simulator subprocess, protocol checks, selection, observations, rewards, telemetry. |
| @ref scripts_rl_policy | Bundle loading, compatibility checks, evaluation, comparison. |
| @ref scripts_rl_ops | SLURM, benchmark, tuning, and fetch wrappers around an existing plan. |
| @ref scripts_rl_tests | Test map; `fake_sim.py` exercises the Python exchange without ns-3. |
| @ref scripts_rl_experiments | Batch domain: matrix version 2 validation, plan v3, selection rules. |
| `scenario_check/` | Checks-only reference campaign; kept (section 10.5). |

The C++ end of the bridge is [rl-bridge.cc](@ref src/rl/rl-bridge.cc).

## 12\. Dependencies

- Python packages are pinned in `requirements.txt` (installed by
  `bootstrap_venv.py`). Its direct dependencies are recorded in every training
  and evaluation manifest and checked by `bootstrap_venv.py --check`.
- `requirements-tuning.txt` pins Optuna separately, for `ops/tune.py` only.
  Adding a tuner to `requirements.txt` would change every manifest and force a
  tuning-only package on machines that only train, evaluate, or compare.
- An already-built simulator binary is passed with `--sim-binary`.
