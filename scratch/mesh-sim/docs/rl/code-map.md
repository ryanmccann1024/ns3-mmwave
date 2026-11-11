# Where the RL code lives {#mesh_sim_rl_code_map}

[TOC]

Which file owns which part of RL, on both sides of the bridge, and where its
tests are.

## 1\. Before you start

- You know the loop from \ref mesh_sim_rl_how_it_works "How a decision works".
- This page runs no commands. Paths are relative to `scratch/mesh-sim/`.

## 2\. Follow one step through the code

\image html rl-code-flow.svg "Which file calls which for train, evaluate and compare, and where they meet the simulator. Drawn by docs/diagrams/rl-tutorial.py from the imports and calls in the code, not from a run."

Read the files in this order to see one training step:

1. `scripts/rl/train.py`: parses the command line, then calls
   `policy/training.py`.
2. `scripts/rl/policy/training.py`: builds the training and model-selection
   environments and the callbacks, runs `learn()`, and has
   `policy/training_artifacts.py` write the manifest.
3. `scripts/rl/agents/mask_ppo.py`: wraps the environment in `ActionMasker` and
   builds `MaskablePPO`.
4. `scripts/rl/env/mesh_env.py`: the Gymnasium `reset()`, `step()` and
   `action_masks()`.
5. `scripts/rl/env/episode.py`: starts the simulator process with `--rl-mode`
   and reads its stdout.
6. `sim.cc`: the tick loop creates the `RlBridge` and calls it every tick.
7. `src/rl/rl-bridge.cc`: writes `init` and `step`, reads the action, builds
   masks, clamps velocity.

Evaluation takes the same path from step 4 down. `scripts/rl/evaluate.py`
verifies the bundle (`policy/bundle.py`), checks compatibility
(`policy/compat.py`) and plays each policy with `policy/evaluate.py`.
`compare.py` starts no simulator: it reads `eval_manifest.json` files only.

## 3\. C++ side

| File | Owns |
|---|---|
| `sim.cc` | Starts RL when `--rl-mode` or `[rl] enabled` is set; creates the bridge; drives it from the tick loop. |
| `src/rl/rl-bridge.h`, `rl-bridge.cc` | `RlBridge`: the `init` and `step` messages, reading actions, masks, per-tick velocity clamping, revalidation, facts. The contract name `mesh_move_2d_v2` is written here. |
| `src/rl/reward-window.h` | Counts elapsed and scored ticks and averages the per-tick reward after warmup. |
| `src/rl/joint-motion.h` | Path-distance math for `avoid_node_collisions`. |
| `src/rl/rl-agent.h` | An unused placeholder. |
| `src/config/rl-control.h`, `rl-control.cc` | Resolves slots, cadence and start positions once. Rejects unknown action profiles and bad `decision_interval_s`. |
| `src/config/config-loader.cc` | Reads the `[rl]` keys and flags the removed single-node keys. |
| `src/domain/sim-config.h` | The `RlConfig` struct the bridge reads. |
| `src/io/run-logger.h` | Writes the RL lines of `run.log`, including the contract name. |

The wire contract: \ref src_rl "src/rl".

## 4\. Python side: `scripts/rl/`

### Command-line tools

| Module | Command |
|---|---|
| `bootstrap_venv.py` | Creates and checks `.venv`. |
| `validate_config.py` | Pre-flight check; `--launch` adds one reset. |
| `train.py` | MaskablePPO training (`m-ppo`). |
| `inspect_model.py` | Summarizes a training run and checks model digests. |
| `evaluate.py` | Runs the model and baselines on seeds. |
| `compare.py` | Paired model-minus-baseline statistics. |
| `experiment.py` | `validate`, `plan`, `run`, `status` and `resume` for a version 1 matrix or a version 2 batch. |
| `run-experiments.sh` | The maintained batch launcher: normalizes path flags, finds the root and `.venv`, and `exec`s `experiment.py`. |
| `online.py` | Standalone continued-learning CLI; the algorithm lives in `policy/operation.py`. |
| `operate.py` | Operation CLI that batch tasks call (model, baseline, preflight, replay gate, reward audit). Run the standalone `preflight` subcommand to probe the capabilities of one INI and seed. |
| `cli_common.py` | Options shared by the tools, atomic JSON writes, hashes, package versions. |

The tools only parse arguments and print. The work is in the packages below.
Every batch flag is in \ref mesh_sim_rl_batch_reference "Batch experiment reference".

### `env/`: the Gymnasium environment

| Owner | Responsibility |
| --- | --- |
| `mesh_env.py`, `episode.py`, `protocol.py` | Gymnasium lifecycle, simulator process and wire validation. |
| `selection.py`, `config.py`, `normalization.py` | Resolve configuration and immutable identities; shared physical scales. |
| `rewards/` | Composer/registry plus `objectives.py` (binary and continuous), `shaping.py` (travel, boundary, signal, proximity, arrival), `mission_terms.py` (mission stages), `coordination.py` and `radio.py`. |
| `observations/` | Registry/schema plus `compact.py`, `coordination.py` and `radio.py` feature layouts. |
| `state/` | `mission.py` and `coordination.py` track observable history; `measurements.py` supplies shared metrics; `extensions.py` attaches requested facts. |
| `recording/` | `artifacts.py` owns episode manifests; `telemetry.py` records/replays steps; `settings.py` and `decisions.py` own optional decision sidecars. |
| `geometry.py`, `curriculum.py`, `seeded_env.py`, `jammer_motion.py` | Legal paths, training-only staged starts, fresh environments per seed and reproducible jammer motion. |

Every family registers in a fixed order. Public identifiers, descriptors and
schema hashes are unchanged; there are no phase-named compatibility aliases.

More: \ref scripts_rl_env "scripts/rl/env".

### `agents/`: the learner

| Module | Owns |
|---|---|
| `mask_ppo.py` | `MaskablePpoTrainer`: builds `MaskablePPO` with every PPO setting, saves and loads (CPU only). Re-exports `MaskablePPOConfig`. |
| `config.py` | `MaskablePPOConfig`, `Cadence`, `PPO_FIELDS`, `PPO_SEARCH_PARAMETERS`, the defaults, and validation of every setting before a simulator starts. |
| `callbacks.py` | Checkpoint retention and the masked model-selection evaluation. |
| `post_update.py` | Opt-in checkpoints (`--checkpoint-timing after-update`) and validation after completed PPO updates, with cadence/budget alignment checks. |
| `q_learning.py` | An exploratory tabular agent written for the removed single-node mode. Nothing imports it except `__init__.py`; see \ref mesh_sim_rl_add_algorithm "Add an RL algorithm". |

More: \ref scripts_rl_agents "scripts/rl/agents".

### `policy/`: training runs, evaluation and comparison

| Module | Owns |
|---|---|
| `training.py` | Runs or resumes training and closes its environments. |
| `training_artifacts.py` | `train_manifest.json`, model provenance and `list_checkpoints`. |
| `bundle.py` | Reads a training run as a verified bundle. |
| `compat.py` | The ordered compatibility checks. |
| `evaluate.py` | The policies (`HoldPolicy`, `RandomValidPolicy`, `ModelPolicy`), the episode loop, `eval_manifest.json`. |
| `metrics.py` | Every evaluation metric: reduction, units, direction, CSV column. |
| `compare_inputs.py`, `compare.py` | Loads evaluations and computes the paired statistics. |
| `reward_matrix.py` | `reward_matrix.json` and `.csv`. |
| `experiment.py` | Version 1 matrix facade: public helper names, plan v2 and step state, kept for existing callers. |
| `operation.py` | One model on one evaluation seed: frozen and online modes, their records. |
| `online_adaptation.py` | The gated online protocol (`online_gated_v1`). |
| `schedules.py` | Frozen sampling, stall and coverage schedules. |
| `replay_gate.py`, `reward_audit.py` | Saved-action replay gates and named reward reconstructions. |
| `scripted.py` | Scripted reference controllers and baseline execution. |
| `baseline_cache.py` | Reuses baseline episodes across reward variants. |
| `preferences.py` | Captures the policy's per-slot action preferences for decision records. |
| `episode_review.py`, `mission_metrics.py` | Mission, physical and motion measurements and reviews. |

More: \ref scripts_rl_policy "scripts/rl/policy".

### `experiments/`: the batch domain

| Module | Owns |
|---|---|
| `config.py` | Matrix version 2 validation (and the shared version 1 helpers), kind requirements, seed roles, native decision counts. |
| `plan.py` | Plan v3: task graph, SHA-256 task keys, destinations, argument lists. Starts no process. |
| `selection.py` | The named, finite selection rules and their receipts. |
| `reporting.py` | Curves, reviews, comparison views, the scenario index, reward summaries and selection evidence. |

These modules import no scheduler and no command-line module. More:
\ref scripts_rl_experiments "scripts/rl/experiments".

### `ops/`, `cluster/`, `tuning/`: operations

| Package | Owns |
|---|---|
| `ops/` | The command-line entry points: `run_task`, `benchmark`, `tune`, `cluster`, `fetch`; plus task mapping, measurement and process control. `local.py` (local batch scheduler) and `recovery.py` (identity checks, receipts, recovery proposals) execute and resume version 2 batches. |
| `cluster/` | SLURM plans, submission, receipts, reconciliation and recovery. `ops/slurm.py`, `receipts.py` and `reconcile.py` only re-export it. |
| `tuning/` | The Optuna study driver, trainer and records. |

More: \ref scripts_rl_ops "Experiment operations".

### Configure experiments instead of adding runners

Use `run.ini` for scenario/RL settings and a version 2 `batch.json` for rows,
PPO profiles, seed roles, budgets and operations. The single maintained launcher
is `scripts/rl/run-experiments.sh`; `scripts/sweep` remains the native INI-grid
runner. New capabilities belong in the owning package above; a new research
experiment needs configuration, not a Python package named after its phase.
Mission formulas remain in the [reward reference](mission-rewards.md).
The numbered runtime packages, duplicated campaign runners and env aliases have
been removed. Old private shell scripts are historical records; use the
[replacement commands](@ref mesh_sim_rl_batch_retired) in a fresh output root.

## 5\. Tests

| Where | What | Run with |
|---|---|---|
| `scripts/rl/tests/` | Python tests. Most use `fake_sim.py`, a scripted stand-in for the simulator with no radio model, so they run without a build. | `.venv/bin/python -m pytest scripts/rl/tests -q` |
| `scripts/rl/tests/integration/test_real_binary.py` | The same checks against a real binary. Skipped without `MESH_SIM_BIN`. | `MESH_SIM_BIN=$SIM_BIN .venv/bin/python -m pytest scripts/rl/tests/integration/test_real_binary.py -q` |
| `tests/unit/rl`, `tests/unit/rl-bridge` | C++ reward-window, joint-motion and bridge tests, no ns-3 build needed. | `make -C tests/unit/rl test` and `make -C tests/unit/rl-bridge test` |

Which test covers what:

- \ref src_rl_policy_input_tests "Policy-input tests": the contract,
  observations, rewards and telemetry.
- \ref src_rl_policy_lifecycle_tests "Lifecycle tests": validate, train,
  inspect and evaluate.
- \ref src_rl_policy_comparison_tests "Comparison tests": compare,
  version 1 matrices and version 2 batch plans.
- \ref scripts_rl_tests "scripts/rl/tests": the full map, including ops.

Run the two C++ suites, which need no ns-3 build:

```bash
make -C tests/unit/rl test
make -C tests/unit/rl-bridge test
```

**Checkpoint:** the output ends with

```
Reward warmup, boundary, mean, and reset checks passed.
joint motion: crossing, altitude, wall clipping, cascade and safe motion passed
178 passed, 0 failed
```

The organization cutover was verified on 2026-10-30 with
`1693 passed, 9 skipped` in 6 min 55 s. The native test module was not run;
seven optional JSON-schema tests lacked `jsonschema`, and the opt-in historical
ZIP test was executed separately on 11 saved models. The full fake-worker suite
needed process-query permission for crash/recovery checks. These counts describe the tested working tree; the individual tests and
optional requirements are mapped in \ref scripts_rl_tests "RL tests".
A clean checkout/native radio run remains unverified.

## 6\. Documentation that goes with the code

| Page | Covers |
|---|---|
| \ref src_rl "src/rl" | The wire contract, field by field. |
| \ref src_rl_policy_inputs "Policy inputs" | Every preset feature and reward formula. |
| \ref src_rl_decision_records "Decision records" | The opt-in per-decision records. |
| \ref scripts_rl "scripts/rl" | Every command-line flag and output file. |
| \ref Contributing "Contributing" | What to update together, and the current schema versions. |

## 7\. Going further

- \ref mesh_sim_rl_extend "Change or extend RL": where each kind of change
  goes.
- \ref mesh_sim_rl_add_algorithm "Add an RL algorithm": every file a new
  learner touches.

Previous: \ref mesh_sim_rl_batch_reference "Batch experiment reference" · Next: \ref mesh_sim_rl_extend "Change or extend RL"
