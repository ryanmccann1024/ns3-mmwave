@page scripts_rl_policy scripts/rl/policy
@brief Library behind `evaluate.py` and `compare.py`: verify a saved training run, run policies, compute paired statistics.

This package holds the logic. The two command-line programs, [`../evaluate.py`](@ref scripts/rl/evaluate.py)
and [`../compare.py`](@ref scripts/rl/compare.py), own argument parsing, printing, and process exit codes.
For the wider RL code map see [scripts/rl README](@ref scripts_rl); for the four-command
walkthrough see [Model lifecycle](@ref scripts_rl_model_lifecycle).

## Module Layout

| File | Role |
| --- | --- |
| [`bundle.py`](@ref scripts/rl/policy/bundle.py) | Reads `train_manifest.json` and the model file, verifies both, and rebuilds the saved observation/reward selection. |
| [`compat.py`](@ref scripts/rl/policy/compat.py) | Ordered checks that a saved model fits the live environment; defines the error types. |
| [`evaluate.py`](@ref scripts/rl/policy/evaluate.py) | Baseline and model policies, the per-episode loop, per-episode metrics, and `eval_manifest.json` writing. |
| [`compare_inputs.py`](@ref scripts/rl/policy/compare_inputs.py) | Loads `eval_manifest.json` files and flattens them into per-episode rows. |
| [`compare.py`](@ref scripts/rl/policy/compare.py) | Paired model-minus-baseline statistics, run grouping, and `exit_code`. |
| [`training.py`](@ref scripts/rl/policy/training.py), [`training_artifacts.py`](@ref scripts/rl/policy/training_artifacts.py) | Training lifecycle, resume and continuation, curriculum factory, `train_manifest.json`. |
| [`experiment.py`](@ref scripts/rl/policy/experiment.py) | Version 1 matrix compatibility facade; public helper names unchanged. |
| [`operation.py`](@ref scripts/rl/policy/operation.py) | One saved policy on one evaluation seed: frozen and online modes, `DiagnosticEnv`/`OperationEnv`, `online_manifest.json`; also the standalone `online` algorithm (`run_online`). |
| [`online_adaptation.py`](@ref scripts/rl/policy/online_adaptation.py) | `OnlinePolicy`: the gated online protocol (`online_gated_v1`). |
| [`schedules.py`](@ref scripts/rl/policy/schedules.py) | Frozen execution schedules: initial sampling, stall bursts, coverage sample-then-deterministic/hold. |
| [`replay_gate.py`](@ref scripts/rl/policy/replay_gate.py) | Native saved-action replay gate and its pass test. |
| [`reward_audit.py`](@ref scripts/rl/policy/reward_audit.py) | Named reward reconstruction audits. |
| [`scripted.py`](@ref scripts/rl/policy/scripted.py) | `ReferencePolicy`, `ScriptedMissionPolicy`, baseline runs and outcome validation. |
| [`mission_metrics.py`](@ref scripts/rl/policy/mission_metrics.py), [`episode_review.py`](@ref scripts/rl/policy/episode_review.py) | Mission metrics and endpoint/physical/motion reviews. |

## Lifecycle

Train, evaluate, and compare are three separate commands. This package serves the last two.

1. Training (`../train.py`) writes `train_manifest.json` and the model files.
2. Evaluation loads that run with `read_bundle`, checks it with `check_compatibility`,
   runs policies with `evaluate`, and writes `eval_manifest.json`.
3. Comparison reads one or more `eval_manifest.json` files and writes `episodes.csv` and
   `comparison.json`.

Test maps: [lifecycle](@ref src_rl_policy_lifecycle_tests) and
[comparison](@ref src_rl_policy_comparison_tests).

`training.py::train_mppo` also accepts an optional campaign-owned
`post_update_callback_factory(artifacts)`. With it, the ordinary per-step
checkpoint callback is suppressed, and the returned callback owns optimized
checkpoint timing. It cannot be combined with in-training evaluation. Omitted
behavior is unchanged. The post-update checkpoint workflow supports both
fresh and continued runs, evaluating saved checkpoints after training so
evaluation does not disturb the training random state.

`train_mppo` also takes `checkpoint_timing`, `decisions_per_episode`,
`curriculum` and `continuation`, the library side of the `train.py m-ppo`
options `--checkpoint-timing`, `--decisions-per-episode`,
`--curriculum-schedule` and `--continue-from-run-dir`/`--continue-model`.
`after-update` timing uses `agents/post_update.py`'s `PostUpdateCheckpoints`;
the decisions-per-episode assertion is checked against the native `init`
contract after the first reset, before any update. Test map:
`test_checkpoint_recovery_support.py` in [scripts/rl/tests](@ref scripts_rl_tests).

## Batch operations

Batch tasks operate one model on one evaluation seed through
`operation.run_operation`. Modes, records, preserved online defaults and
schedules are specified in the
[batch experiment reference](@ref mesh_sim_rl_batch_protocols); this section
records only the invariants this package owns.

- Frozen modes (`frozen_deterministic`, `frozen_sampled`, optionally scheduled)
  fail if the parameter or optimizer digest changes.
- `online_gated_v1` and `online_sb3_v1` are separate protocols from one
  scientific engine each; neither is merged into the other. Each reloads its
  parent for every evaluation seed.
- `run_operation` writes `online_manifest.json` with an explicit `protocol`;
  `run_online` (the standalone CLI) keeps its legacy envelope, whose version
  alone does not identify the protocol (see [Contributing](@ref Contributing)).
- `bundle.py` provides `parameter_digest`, `optimizer_digest`,
  `checkpoint_counters`, and write-once model bindings (`bind_model`,
  `read_bound_checkpoint`) that re-verify the manifest bytes, model SHA-256,
  counters and optimizer digest without rewriting the source run.
- A replay gate passes only by `replay_gate.gate_passed`; a zero exit code is
  not success.

Tests: `test_operation.py`, `test_online_protocols.py` (map in
[scripts/rl/tests](@ref scripts_rl_tests)).

## Bundle Verification

`read_bundle` refuses a run unless all of these hold:

- `manifest_version` is the current `MANIFEST_VERSION` from `training_artifacts.py`, or one of
  the earlier versions `bundle.py` still lists as readable; anything else is refused with
  "retrain with current tooling". Version numbers live in [Contributing](@ref Contributing).
- `status` is `completed`.
- `control_mode` is `centralized`.
- The chosen model file exists and its SHA-256 matches the digest in the manifest.

`--model` picks `final`, `best`, or `checkpoints/<name>.zip`; a checkpoint must be listed
in the manifest. `best` exists only if training used `--eval-every-steps > 0`.
No flag skips a digest check. Every failure is a `BundleError`.

## Compatibility Checks

`check_compatibility` must run before `load_model`. The checks run in this order and stop
at the first failure:

1. Structural contract (`contract`, `dimensions`, `obs_dim`, `mask_dim`, and so on).
   Always fatal (`StructuralMismatchError`).
2. Observation schema (`check_schema`). Structural differences raise
   `SchemaMismatchError` and are always fatal; scenario-level differences it returns as
   warnings are folded into step 4.
3. Reward schema SHA-256, plus `reward_type` and `reward_window` when the reward is
   authored in the simulator. Always fatal (`RewardMismatchError`).
4. Scenario identity: node slots, the four input-file SHA-256s, band, and any
   observation-schema findings. This is the only overridable step
   (`--allow-different-scenario`); the report then says `scenario: overridden`.
   Otherwise it raises `ScenarioMismatchError`.

A passing report still carries the note that matching checks do not imply transfer.

## Evaluation

`evaluate.py` offers these policies:

| Policy | Behavior |
| --- | --- |
| `hold` | Every slot takes the hold action. |
| `random_valid` | Uniform choice among valid actions, reseeded per episode. |
| `model` | Deterministic MaskablePPO prediction under the live mask. |
| `geometric`, `optimization` | Prepare a channel-scored initial placement once, then hold every slot. |

Each policy gets its own environment and runs every seed. `eval_selection` forces
`telemetry=steps` so metrics come from the per-decision telemetry file.
The `metrics.py` registry owns scored metrics, reduction, units and CSV columns.
Delivery, connectivity, LOS and travel use scored windows after warmup; decisions
continue during warmup. `initial_displacement_m_total` measures source-to-plan
x/y relocation before reset and is carried separately from scored travel. It is
not summed with travel or included in paired/group statistics.

Placement requires a dedicated `planning_seed`; the evaluation seed list never
selects the plan. Overlap with planning, training or model-selection seeds is
refused before preparation unless `--allow-seed-overlap` explicitly requests
diagnostics. Such evaluations are marked non-held-out and excluded from groups.
Each episode's return is checked against `rl_episode.json`, and a mismatch is an error.

`eval_manifest.json` is written before the first episode and rewritten after every
episode. A crash therefore leaves a manifest with status `failed` or `partial`, never
none. Seeds that were never attempted are recorded as `not_run`.

## Comparison

`build_comparison` pairs `model` with each baseline on the same evaluation seed and
computes `model - baseline` differences.

- **Primary metric**: `delivery_ratio` (`PRIMARY_METRIC`). Higher is better.
- **Excluded pairs**: a seed is dropped if either side is missing, not `completed`,
  or has a null metric.
- **Interval**: 95% t interval when at least 2 pairs exist; otherwise omitted.
- **Groups**: evaluations sharing a `--label` are grouped, and a t interval is taken across
  training runs. Runs whose settings or scenario digests differ raise `ComparisonError`.
  Runs with seed overlap or no usable pairs are excluded from the group.

### Two kinds of interval

They never share a label.

- **Across evaluation seeds, one saved model.** The model and a baseline are
  paired seed by seed inside one evaluation. The interval shows how the paired
  difference varies over held-out scenario seeds with the model fixed.
- **Across independently trained models.** Evaluations sharing a `--label`
  contribute one mean difference each, over the seeds common to all of them. The
  interval shows run-to-run variation. The training seed currently sets both the
  PPO initialization and the training scenario seed, so the two cannot be
  separated (TODO-RL-SEEDS-1).

A single evaluation seed or a single training run yields a value and no
interval; `interval_omitted` says why. The intervals are t intervals that assume
approximately normal paired differences, so on a bounded ratio with few seeds
they are approximate.

### Reading the output

- Every comparison reports `n_expected` (requested seeds) beside `n_used` (pairs
  both policies completed), and lists each dropped seed with a reason per side,
  such as `model:failed`, `hold:metric_null`, or `random_valid:not_run`.
- A `null` metric is never read as zero. `zero_variance` marks a zero-width
  interval so a deterministic scenario is not mistaken for certainty.
- Metrics after `delivery_ratio`: `connectivity`, `los_fraction`,
  `unroutable_fraction`. `return` is compared only inside one evaluation, where
  every policy shares one reward definition, and is flagged
  `comparable_across_reward_definitions: false`.
- All statistics come from the RL telemetry window, stated as `metric_source`.
  Nothing is read from a run's `summary.json`, because that file excludes warmup
  ticks while the RL window does not. Mixing them would be wrong whenever
  `warmup_s > 0` (see the RL-reward warmup entry in `TODO.md`).

`exit_code` returns:

| Code | Meaning |
| --- | --- |
| 0 | Comparison is complete and clean. |
| 1 | Comparison is incomplete, or inputs were refused (`ComparisonError`). |
| 2 | Some evaluation overlapped a training, model-selection or channel-planning seed, or a policy has non-zero `mask_violations` or `revalidated_slots`. |

## Output

| Step | Where |
| --- | --- |
| Evaluate | `<output-dir>/eval_manifest.json` (`eval_manifest_version` = `EVAL_MANIFEST_VERSION`) plus per-episode simulator output. |
| Compare | `<output-dir>/episodes.csv` and `<output-dir>/comparison.json` (`COMPARISON_VERSION`). Current version numbers are in [Contributing](@ref Contributing). |

## Conventions

- `REQUIRED_MANIFEST_VERSION` in `compare_inputs.py` must track `EVAL_MANIFEST_VERSION`
  in `evaluate.py`; change both together.
- Comparisons group by scenario digests and training settings, not by path.
- Docstrings are one line.

## Dependencies

- `numpy`; MaskablePPO (via [`../agents/mask_ppo.py`](@ref scripts/rl/agents/mask_ppo.py)) only when loading a model.
- `../cli_common.py`, `../env/`, and `scripts/stats.py` (`t_critical_95`) from this repository.
- Run the CLIs as `python -m scripts.rl.evaluate` / `python -m scripts.rl.compare` from
  `scratch/mesh-sim/`; evaluation needs a built simulator binary.

For placement inputs, snapshots and how to read a plan, see
[Placement baselines](@ref mesh_sim_placement_start).
Evaluation and comparison outputs written at an earlier schema version require
regeneration; changing their version number does not supply missing facts.

## PPO operation and continuation

Use `scripts.rl.operate model` to run one saved policy on one diagnostic seed.
Supply the completed training run, a model selector, the seed's `run.ini`, and
a fresh output directory. The band defaults to the parent run's band.
Per-seed inputs may change the seed, native deployment time, and jammer
event times. The operation verifies the original training inputs against
their saved hashes before allowing timing changes.

| Mode | Protocol settings | Behavior |
| --- | --- | --- |
| `frozen_deterministic` | `{}` | Deterministic inference, with an optional frozen action schedule. |
| `frozen_sampled` | `{}` | Sampled inference, with an optional frozen action schedule. |
| `online_gated_v1` | Explicit `n_steps`, `batch_size`, and a `--mission` argument | Trains on eligible windows from one episode. Other PPO settings come from the parent, including a null `target_kl`. |
| `online_sb3_v1` | Explicit `n_steps` and `batch_size`. Optional `learning_rate`, `ent_coef`, and `target_kl`. | Uses the SB3 learning loop. Defaults cap the parent learning rate at 0.0001, with `ent_coef=0.001` and `target_kl=0.02`. |

Use `--protocol-settings-json '{"n_steps":120,"batch_size":60}'` for an online
operation that can fit that rollout. The rollout size must be divisible by the
minibatch size. Each seed starts from the saved parent model and optimizer.

A frozen operation can take
`--schedule-json '{"kind":"sample-then-hold","settings":{"coverage_target":0.8}}'`.
Coverage schedules accumulate 30 seconds of qualifying scored simulator time
before switching. The schedule records its rules in `online_manifest.json`
and its transitions in `coverage_execution.json` version 2.

Operations write `weight_audit.json` to record policy and optimizer identity.
Sampled, scheduled, and online operations also write `online_manifest.json`
version 5 with the protocol, settings, and update accounting. A replay gate
uses the saved actions and preserves a scenario-check case's reference-policy
gate. Native `[rl] control_start_s` still controls when the simulator accepts
movement.

`scripts.rl.operate preflight` probes one INI and seed before operation. Pass
`--seed-configs-json '{"201":"path/to/run.ini"}'` and list the required
capabilities with `--requirements`. Supported names are `coverage`,
`building_masks`, and `peer_separation`. `check_result.json` records what the
simulator exposes and which requirements are missing. Use the
[scenario-check guide](@ref mesh_sim_rl_scenario_check_runner) for the separate
campaign difficulty checks.

Use `scripts.rl.train m-ppo --continue-from-run-dir` to extend a completed
compatible run. `--continue-model` defaults to `final` and also accepts
`best` or a retained checkpoint path. Supply a larger cumulative timestep
budget. With `--checkpoint-timing after-update`, enable checkpointing and
align the cadence and budget to complete rollouts and episodes. The
`post_update_checkpoints.json` record identifies checkpoints saved after
optimization.
