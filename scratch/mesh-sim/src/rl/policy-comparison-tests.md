@page src_rl_policy_comparison_tests src/rl/policy-comparison-tests

@brief Map of the policy comparison, experiment-matrix, batch reporting, conversion-parity and evaluation-pipeline tests.

Run these from `scratch/mesh-sim/`. These files use temporary
manifests, a stub executor, or `fake_sim.py`; they do not need an ns-3 build:

```bash
.venv/bin/python -m pytest -q scripts/rl/tests/policy/test_policy_comparison.py \
  scripts/rl/tests/experiments/test_experiment_matrix.py \
  scripts/rl/tests/experiments/test_batch_timing.py \
  scripts/rl/tests/policy/test_evaluation_pipeline.py \
  scripts/rl/tests/policy/test_metrics.py
```

| Test file | Input | What it checks | Expected result |
| --- | --- | --- | --- |
| `test_policy_comparison.py` | Hand-built `eval_manifest.json` files with controlled per-seed metrics | Shared t statistics; paired model-minus-baseline differences; missing, failed, and null episodes; held-out seed and compatibility refusals; grouping across trained models; deterministic CSV/JSON and CLI flags | A valid comparison writes `episodes.csv` and `comparison.json` under the chosen output directory. Incomplete inputs are reported without turning missing values into zero; incompatible inputs write nothing. |
| `test_experiment_matrix.py` | Temporary matrices and the tracked `inputs/experiments/bypass-smoke-matrix.json` | Matrix validation, explicit row filtering, seed roles, generated CLI arguments, reproducible plan, manifest-based step status, failure/blocked handling, and resume | `experiment_plan.json` contains the expected train/evaluate/compare steps. Invalid matrices fail before execution; a second run executes only pending steps. |
| `test_batch_timing.py` | Copies of the coordination smoke batch and its INIs | Native cadence, scenario and row gate assertions, and historical replay gates | Invalid timing fails during matrix validation. Deployment tasks use the gate from the selected INI, and replay retains the declared reference gate. |
| `test_evaluation_pipeline.py` | Tiny training jobs against `fake_sim.py`, then evaluation and comparison | A failed evaluation seed is retained and excluded from paired statistics; two trained models form an across-run group | Temporary train/evaluation manifests and comparison files agree on completed seeds, excluded seeds, and interval type. Training cases require `sb3_contrib`. |
| `test_metrics.py` | Scored telemetry windows with elapsed ticks spanning warmup | Shared metric reductions use scored denominators and retain null values for empty windows | Warmup time never dilutes scored fractions or produces a first-LOS result. |

## Batch matrix and plan tests: test_matrix_v2.py

Matrix version 2 validation, plan v3 expansion and identity, selection rules
and the launcher ([batch experiment reference](@ref mesh_sim_rl_batch_reference)).
No simulator or training runs: binaries are fake executables that are hashed
only, and run/status use a stand-in scheduler module.

```bash
.venv/bin/python -m pytest -q -rs scripts/rl/tests/experiments/test_matrix_v2.py
```

| Test | Input → expected output |
| --- | --- |
| `test_v1_facade_names_constants_and_golden_argv`, `test_v1_cli_plan_keeps_plan_v2_and_takes_the_environment_binary` | Version 1 matrix → unchanged facade names/constants, golden train/evaluate argv and plan v2; `MESH_SIM_BIN` accepted. |
| `test_v2_refusals`, `test_v2_missing_required_keys` | Unknown keys, bad kind or mode, undeclared scenario, overlapping or repeated seeds, `best` without training validation, unretained or never-produced checkpoints, misaligned after-update schedules, wrong asserted episode length or episode count, an unsafe pool directory, duplicate operation IDs, an empty seed role; missing `kind`, `rows`, `evaluation` or `training.total_timesteps` → validation errors. |
| `test_checks_and_evaluate_kinds_take_no_training` | `checks`/`evaluate` with training settings or training seeds → refused; valid forms need no dummy training seeds. |
| `test_continuation_budget_seed_and_identity`, `test_a09_config_key_is_independent_of_the_ppo_seed` | Continuation rows → refused for a non-increasing budget, seed mismatch or changed INI bytes; `training_config_key` 101 with PPO seed 102 keeps both identities. |
| `test_two_by_two_by_two_by_two_gives_sixteen_distinct_leaves` | Two training seeds × two checkpoints × both online protocols × two evaluation seeds → 16 distinct keys and destinations. |
| `test_operation_protocol_refusals`, `test_gated_and_scheduled_operations_need_a_case_mission` | Schedule on an online mode, missing `online` settings, non-null gated `target_kl`, missing case mission → refused. |
| `test_collisions_are_detected_before_writing` | Colliding task IDs/keys/destinations → error and nothing written. |
| `test_validate_writes_nothing_and_resolves_paths_with_spaces` | `validate` on a matrix in a directory with spaces → paths resolve against the matrix directory; nothing written. |
| `test_v2_plan_is_immutable` | Re-planning a root with a changed matrix → refused; identical plan accepted. |
| `test_replay_gates_and_preflights_expand_one_task_per_seed` | Check declarations → expected check tasks and arguments. |
| `test_selection_stage_plans_every_branch`, `test_selection_rules_rank_and_block` | Selection stages → every branch planned before execution; each named rule ranks with its tie rule; missing or held-out evidence blocks. |
| `test_public_example_validates_and_plans` | `inputs/experiments/examples/coordination-smoke/batch.json` → 64 native decisions, retained checkpoints 128 and 256, 8 rollout updates, 16 operation and 6 baseline tasks. |
| `test_reference_formats_used_by_existing_readers_are_accepted`, `test_malformed_references_are_refused` | `scenario_routes_v1` version 1 and 2 files and `mission_waypoints_v1` files with versions 1–3, 2-D/3-D waypoints and the optional scripted-policy fields → accepted with the version recorded; unknown keys, bad versions or node IDs → refused. |
| `test_placement_baselines_record_planning_seed_and_settings` | `geometric`/`optimization` baselines → planning seed and planner-settings hash in the physical digest, `--planning-seed` argv, a planning seed overlapping declared seeds refused without `allow_seed_overlap`. |
| `test_row_configs_keep_distinct_inis_distinct`, `test_row_training_configs_keep_key_101_per_row` | `rows[].configs` (including the `training` role) → byte-distinct INIs stay distinct tasks with `config_source: row`; identical INIs share a baseline; the lookup key 101 is kept per row. |
| `test_scenario_scoped_baselines_run_once_per_seed` | `baselines.configs_scope: scenario` → one baseline per declared seed on the scenario's own configs. |
| `test_checks_apply_across_scenarios_in_declared_order` | `checks[].applies_to` → one check task in its own scenario; dependents in other scenarios need it; declared order kept. |
| `test_operation_candidates_share_one_train_task_and_one_checkpoint`, `test_row_candidates_source_only_the_declared_checkpoint` | `{row, operation}` and row candidates → no duplicated training task; the select task sources exactly `source_checkpoint`. |
| `test_selection_receipt_records_declared_sample_counts` | Selection receipt → declared sample counts recorded, never invented. |
| `test_curriculum_beside_the_matrix_is_hashed` | A curriculum schedule beside the matrix → resolved against the matrix directory and hashed. |
| `test_decision_record_seeds_restrict_emission`, `test_baseline_decision_record_seeds_restrict_emission` | Operation and baseline `decision_record_seeds` → `--decision-records` only for those seeds; existing digests unchanged when absent. |
| `test_run_and_status_fail_cleanly_without_the_scheduler`, `test_run_delegates_with_resolved_execution` | See the [operations test map](@ref scripts_rl_ops_tests). |
| `test_launcher_syntax_dry_run_and_path_normalization`, `test_launcher_runs_real_validate_from_another_directory` | `run-experiments.sh` syntax, `--dry-run` quoting and path normalization; a real `validate` from another directory. |

A native run of a version 2 batch is a human-run check and is BLOCKED until
executed.

## Batch reporting tests: test_gui_index.py

`experiments/reporting.py` on controlled fake leaves: plans come from the public
coordination-smoke example and every accepted attempt is a small hand-written
leaf (evaluation manifest v8, online manifest v5, bindings, tiny model ZIPs).
No simulator runs. The contract fixtures
`tests/fixtures/batch_index_v4_example.json` and
`tests/fixtures/batch_online_manifest_v5_example.json` are what these writers
produce; `MESH_REGENERATE_BATCH_FIXTURES=1` rewrites them deliberately (the
GUI repository copies them and checks for drift).

```bash
.venv/bin/python -m pytest -q -rs scripts/rl/tests/experiments/test_gui_index.py
```

| Test | Input → expected output |
| --- | --- |
| `test_index_v4_fields_relative_paths_and_contract_fixtures`, `test_arbitrary_batch_name_complete_index`, `test_absolute_episode_dirs_become_relative` | Complete fake batch → `mission_scenario.json` version 4 equal to the fixture; every path relative; any batch name works. |
| `test_missing_leaves_label_index_incomplete`, `test_skipped_selection_is_not_counted_missing`, `test_recorded_model_digest_mismatch_is_incomplete` | Missing leaves or a model digest differing from its binding → index labeled incomplete with `missing`/`issues`; `skipped_selection` branches are not missing. |
| `test_groups_agree_only_on_full_identity`, `test_row_specific_inis_never_share_a_group` | Evaluation groups → pooled only when every identity field, including the INI hash, agrees. |
| `test_reward_summary_keeps_campaign_meanings_and_nulls` | Reward summaries → the retired campaign summary's metric meanings and leading columns; missing values stay empty. |
| `test_review_is_v1_without_status_and_projected`, `test_main_rebuild_never_moves_or_changes_siblings` | Review → version 1 payload with no invented status; rebuilding `main/` never moves or changes sibling artifacts. |
| `test_accepted_directory_must_belong_to_its_task`, `test_scheduler_record_forms_are_accepted` | Accepted directories must be the task's own attempts; scheduler receipt forms are read. |
| `test_curves_follow_accepted_history_and_exclude_abandoned_tail`, `test_curves_refuse_changed_checkpoint_bytes` | Recovered training → curves follow the accepted lineage and drop the abandoned tail; changed checkpoint bytes refused. |
| `test_comparison_view_pools_seeds_for_compare`, `test_comparison_view_refuses_mixed_or_missing_inputs`, `test_comparison_view_refuses_mixed_inis`, `test_incomplete_view_is_explicit` | Comparison views → one merged evaluation per model; mixed identities, INIs or missing inputs refused; `allow_incomplete` gives an explicitly partial view. |
| `test_selection_evidence_for_mission_rule_feeds_select`, `test_selection_evidence_online_rule_reads_online_episodes`, `test_selection_evidence_validation_and_replay`, `test_selection_evidence_refuses_missing_and_held_out`, `test_operation_candidates_feed_select_at_exact_checkpoint` | `selection_evidence` → declared sources only, at exactly the select task's checkpoint; missing or held-out evidence refused. |
| `test_placement_baseline_entry_carries_planning` | Placement baseline index entry → `planning` with the planning seed and planner-settings hash. |

## Conversion parity tests: test_conversion_parity.py

Layer (a) builds small version 2 batches in a temporary directory and checks
the planned inventory against hand-counted expectations (3/6/9-peer rows, an
A09-style PPO seed separate from its config key, a single-parent continuation
with a cumulative budget, named-rule versus replay-pinned selection, two
Phase 8-style batches sharing one resource pool, both online protocols per
checkpoint and seed, each schedule kind with only its own settings, and the
inventory comparator itself). The fixtures are self-contained and do not import retired study runners.
Private experiment data is not required by these public contract fixtures. No simulator
or historical campaign is started.

```bash
.venv/bin/python -m pytest -q -rs scripts/rl/tests/experiments/test_conversion_parity.py
```

| Test | Input → expected output |
| --- | --- |
| `test_three_six_nine_peer_rows_expand_as_hand_counted`, `test_a09_style_ppo_seed_and_config_lookup_key_stay_separate`, `test_continuation_names_one_parent_and_a_cumulative_budget`, `test_named_rule_selection_differs_from_a_replay_pinned_winner`, `test_batches_share_one_resource_pool`, `test_both_online_protocols_expand_per_checkpoint_and_seed`, `test_each_schedule_kind_takes_only_its_split_settings`, `test_inventory_comparison_reports_each_changed_dimension` | Generic fixtures → the expected task inventory; no private data. |

Historical experiment parity is separate from the maintained functionality suite.

Matrix tests also reject fractional rollout sizes, invalid budgets/cadence,
nonfinite hyperparameters, and unsupported evaluation choices before writing a
plan. Comparison tests require the current evaluation schema, reject missing or mixed
scoring definitions, and retain warmup metadata in JSON and CSV. The pipeline
includes an empty scoring window whose decisions continue and whose reward is
zero; it is excluded from network metric pairs.

For the built simulator, run the focused fresh-process smoke test after setting
`MESH_SIM_BIN` to an absolute path:

```bash
MESH_SIM_BIN=/absolute/path/to/ns3.42-sim-debug \
  .venv/bin/python -m pytest -q \
  scripts/rl/tests/integration/test_real_binary.py::test_experiment_matrix_smoke_in_fresh_processes
```

That test uses one temporary matrix with two training seeds and two held-out
seeds. It checks completed evaluation manifests, real summary files, and the
paired and across-run comparison under `tmp_path/matrix-root/`. Without
`MESH_SIM_BIN`, the real-binary module skips instead of testing the simulator.
All test outputs stay in pytest's temporary directory; they are not reference
results or evidence of RL improvement.


`test_reward_matrix.py` checks distinct/restarted validation seeds, all-seed
held-out overlap detection, matrix CLI seed expansion, exclusion of reset and
incomplete telemetry, column means, cumulative means, and two checkpoint
matrices from a short real MaskablePPO run against the fake simulator.

`policy/test_baseline_statistics.py` checks that shared baseline rescoring changes returns while preserving action hashes and physical metrics, and does not mutate cached files. Accepted manifest versions are defined by the writer/reader and documented in CONTRIBUTING.md.

`test_objective_diagnostics.py` checks that zero-demand mission scores remain
undefined and that reward audits replay a weighted coordinated component in a
composed reward. `test_scenario_check.py` covers rebasing scenario inputs from
their original INI directory when writing the input archive.

Iteration-three tests verify constructor/manifest/CLI parameter wiring and six bounded plans with one shared baseline cache per scenario. The online test proves parameter updates occur in continuing operation, are absent from the sampled control, and do not carry between seeds.
