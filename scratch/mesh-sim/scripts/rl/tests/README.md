@page scripts_rl_tests scripts/rl/tests

@brief Map of the RL, ops, and placement-baseline Python tests and their helpers.

This page lists each RL test with its input and expected output. Tests use
temporary output directories and never write to scenario inputs.

Tests follow the owner whose behavior they verify: `env/`, `agents/`, `policy/`,
`experiments/`, `ops/`, `cluster/` and `tuning/`. `tooling/` checks Python setup;
`integration/` contains optional native-binary checks. Shared simulator/Slurm
fakes and protocol helpers live in `support/`; root `conftest.py` exposes common
fixtures. Run any directory with `python -m pytest scripts/rl/tests/<owner>`.

## 1\. Running the tests

Run from `scratch/mesh-sim/`. Install the Python requirements first as described
in the [main README](@ref readme_python_environment).

```bash
.venv/bin/python -m pytest scripts/rl/tests/env/test_mesh_env.py -q
MESH_SIM_BIN=/absolute/path/to/mesh-sim-binary .venv/bin/python -m pytest scripts/rl/tests/integration/test_real_binary.py -q
MESH_SIM_BIN=/absolute/path/to/mesh-sim-binary .venv/bin/python -m pytest scripts/baselines/tests/test_real_binary.py -q
make -C tests/unit/config test
MESH_SIM_BIN=/absolute/path/to/mesh-sim-binary make -C tests integration
```

- Set `MESH_SIM_BIN` to a freshly built simulator for the real-binary tests.
  Without it, `integration/test_real_binary.py` skips.
- `support/fake_sim.py` supplies protocol messages for the Python tests; it does not
  model radio propagation.

## 2\. Test helpers

| File | Role |
| --- | --- |
| `support/fake_sim.py` | Stand-in simulator with the real flags and RL protocol; `FAKE_SIM_MODE` selects fault modes, `FAKE_SIM_FAIL_SEEDS` kills chosen seeds. No radio model. |
| `support/fake_slurm.py` | `sbatch`/`squeue`/`sacct`/`scancel` shims over one JSON state file (`FAKE_SLURM_STATE`); `fake_slurm.install(tmp_path)` returns a handle to inspect submissions and inject failures. |
| `conftest.py` | Shared `sim_binary` and `multi_run_config` fixtures. |

## 3\. Other test maps

| Modules | Map |
| --- | --- |
| `env/test_observations_rewards.py`, `env/test_policy_input_parameters.py`, and policy-input cases in `env/test_mesh_env.py` / `integration/test_real_binary.py` | [policy-input-tests.md](../../../src/rl/policy-input-tests.md) |
| `policy/test_lifecycle_cli.py`, `policy/test_policy_lifecycle.py` | [policy-lifecycle-tests.md](../../../src/rl/policy-lifecycle-tests.md) |
| `policy/test_evaluation_pipeline.py`, `experiments/test_experiment_matrix.py`, `policy/test_policy_comparison.py`, `experiments/test_matrix_v2.py`, `experiments/test_gui_index.py`, `experiments/test_conversion_parity.py` | [policy-comparison-tests.md](../../../src/rl/policy-comparison-tests.md) |
| `env/test_registry_identity.py` | [policy-input-tests.md](../../../src/rl/policy-input-tests.md) |
| `agents/test_checkpoint_recovery_support.py` | [policy-lifecycle-tests.md](../../../src/rl/policy-lifecycle-tests.md) |
| `policy/test_online_protocols.py`, `policy/test_operation.py` and the other batch-operation owners, `env/test_geometry.py`, `env/test_curriculum.py`, `env/test_seeded_env.py`, `policy/test_model_compatibility.py` | Section 11 below |
| Task execution, measurement, tuning, cluster, fetch and batch-scheduler tests (`cluster/`, `ops/`, `tuning/`) | [ops-tests.md](ops-tests.md) |
| `env/test_decision_records.py`, `env/test_decision_record_contract.py` | [decision-records.md](../../../src/rl/decision-records.md) |

## 4\. Python adapter: test_mesh_env.py

Unless noted, input is an in-process scenario with `support/fake_sim.py`; expected
output is the stated Gymnasium result or error plus a correctly finalized
`rl_episode.json`.

| Test | Input → expected output |
| --- | --- |
| `test_centralized_spaces_contract_and_padding` | Two controlled nodes, three positions → `MultiDiscrete([5,5,5])`, 24 observations, padded position masked to hold. |
| `test_centralized_single_slot_spaces` | One controlled node → one five-action position and eight observations. |
| `test_centralized_joint_action_is_forwarded` | `[2,1,4]` → correct positions after five ticks, wall mask, and decision metadata. |
| `test_centralized_rejects_a_scalar_action` | Scalar or short action → `ValueError` before forwarding. |
| `test_centralized_masked_random_run_completes` | Valid masked random actions → two decisions and completed episode metadata. |
| `test_centralized_faults_are_rejected` | Six malformed init/step variants → protocol error, failed episode, cleaned-up process. |
| `test_reset_signature_drift_fails_before_replacing_spaces` | Change slot capacity between resets → error; original Gym spaces remain. |
| `test_legacy_stream_is_rejected` | A stream that does not start with `init` → `RuntimeError` "legacy control is unsupported". |
| `test_long_stdout_is_drained_on_close` | Long simulator output, then close → process and reader thread exit; episode interrupted. |
| `test_close_is_idempotent_and_reset_still_works` | Close twice, then reset → new episode allocated without leaked reader. |
| `test_completed_episode_leaves_no_process_or_reader` | Two valid actions → completed episode and no child/reader left running. |
| `test_scenario_identity_uses_relative_nodes_and_inline_comments` | Relative nodes path with comment → absolute `run_config` and exact file hashes. |
| `test_scenario_identity_accepts_absolute_nodes_path` | Absolute nodes path → hash of that file. |
| `test_scenario_identity_reports_missing_nodes_file` | Missing nodes file → `FileNotFoundError`. |
| `test_centralized_tiny_training_run` | 16-step MaskablePPO run → saved model, training manifest, episode metadata; skipped without `sb3_contrib`. |
| `test_training_failure_closes_the_environment` | Fake simulator exits with error → failed manifest and no leaked process; skipped without `sb3_contrib`. |
| `test_episode_allocation_scans_existing_directories_once` | Existing episode directories → next two names allocated with one directory scan. |

## 5\. Real simulator: test_real_binary.py

Input is `inputs/baselines/centralized-multi-smoke/` unless the test creates a small
temporary variant. Outputs are parsed simulator messages, metrics, and episode
manifests under pytest's temporary directory.

| Test | Input → expected output |
| --- | --- |
| `test_live_spaces_and_metadata` | Reset → real `init`, spaces, slot mapping, reset info, and padding match contract. |
| `test_scripted_positions_and_masks` | South/east then hold/west → exact positions, clipping, masks, and completed manifest. |
| `test_repeated_resets_are_deterministic` | Same scenario, seed, and actions twice → identical observations/rewards. |
| `test_structural_malformed_actions_hold_everything` | Wrong-length joint action → one warning and all nodes hold. |
| `test_malformed_action_stops_a_moving_node` | Valid move then malformed action → earlier movement does not persist. |
| `test_semantic_errors_only_affect_invalid_slots` | Masked direction and non-hold padding → only invalid positions hold; reported in `revalidated_slots`. |
| `test_close_mid_episode_is_interrupted` | Close after one decision → interrupted manifest, no child/reader leak. |
| `test_partial_windows_clipping_and_reward_mean` | Same scripted path at coarse/fine cadence → clipped trajectory, final short window, coarse reward equals mean of fine tick rewards (excluding reset). |
| `test_deployment_gate` | User-run native extension check after rebuilding, for deployment-gated control. |

## 6\. Placement baselines on the real simulator

`scripts/baselines/tests/test_real_binary.py` holds the placement-baseline rows
that reach `scripts.rl.evaluate` or the RL bridge (command in section 1).

- Every row writes a synthetic scenario under pytest's temporary directory and
  needs `MESH_SIM_BIN`. Without it, each row is skipped with a reason starting
  `BLOCKED:`; a `BLOCKED:` row did not run and has not passed.
- The file's R1-R4 rows cover the direct-binary guard and the runner's `none`
  path.
- The placement contract is in [scripts/baselines/README.md](@ref scripts_baselines).

| Row | Test | Input → expected output |
| --- | --- | --- |
| R5 | `test_r5_runner_places_selected_nodes` | Standalone runner, both methods, two of four `[rl]` nodes movable, small grids → version 2 manifest and plan, standalone ownership, selected nodes start at the plan on both seeds, others at their source start. |
| R6 | `test_r6_evaluation_suite_with_placement_policies` | `--policies hold,random_valid,geometric,optimization`, `movable_nodes` equal to a reordered `controlled_nodes` → decision-0 positions match each plan or the source, and RL slots are exactly the placed nodes in `controlled_nodes` order. |
| R6 | `test_r6_evaluation_refuses_unequal_rosters` | `movable_nodes` a strict subset of `controlled_nodes` → exit 1 naming both differences and the fix; no episode and no `eval_manifest.json`. |
| R7 | `test_r7_query_matches_direct_first_tick` | Standalone `--channel-query` with and without probes vs the first-tick `links.csv` of a direct run → equal SINR, capacity and LOS. |
| R8 | `test_r8_evaluation_query_matches_rl_reset_links` | `--channel-query --rl-mode` with and without probes vs `facts.links` of the RL reset message on the same INI and seed → equal SINR, capacity and LOS. |
| R9 | `test_r9_query_is_repeatable_and_leaves_runs_unchanged` | Layouts A,B,A then B,A in two worker lifetimes → equal results; ordinary runs before and after the queries are identical. |
| R10 | `test_r10_*` | NYU with shadowing → R7 and R9 hold; another planning seed changes the draws. |
| R11 | `test_r11_*` | Building blockage and sub-6 jammer fixtures → LOS/NLOS differences, run-equivalent jammer seed, a strong jammer disconnecting links, and probe thresholds. |
| R12 | `test_r12_all_movable_standalone` | Three all-movable nodes, no mapping file, each method standalone → plans applied at the first tick; reference costs keep every node put. |
| R12 | `test_r12_zero_cost_moves_a_node_reference_cost_keeps` | Same scenario, geometric, reference vs all-zero movement costs → some node moves only under zero cost. |
| R12 | `test_r12_all_movable_evaluation_suite` | Same scenario with `controlled_nodes = all`, `--policies hold,random_valid,geometric,optimization` → every episode completes; decision-0 positions match each plan and slot i is node i. |
| R12 | `test_r12_partial_selection_standalone_keeps_unselected_traces` | Only a fixed node moves; constant-velocity, waypoint and random-walk nodes unselected → their `positions.csv` rows equal a direct run of the same scenario with `algorithm = none`. |
| R12 | `test_r12_partial_selection_evaluation_keeps_unselected_traces` | Same selection in evaluation (both methods) → unselected rows equal a direct `--rl-mode` run on the source INI. |

## 7\. C++ configuration and CLI

`tests/unit/config/config-validator-test.cc` uses in-memory configurations
and checks accepted values or precise errors; it writes no simulation output.

| Test | Input → expected output |
| --- | --- |
| `test_rl_inverted_z_bounds` | Inverted z bounds with RL enabled → error. |
| `test_rl_valid_z_bounds` | Valid z bounds → accepted. |
| `test_rl_disabled_has_no_control` | Disabled RL → mode `disabled`, no slots. |
| `test_rl_selection_order` | Explicit node list → list order preserved. |
| `test_rl_selection_all` | `all` → every mesh node in file order. |
| `test_rl_all_with_ids_rejected` | `all` mixed with IDs → error. |
| `test_rl_jammer_id_rejected` | Jammer ID in selection → jammer-specific error. |
| `test_rl_unknown_id_rejected` | Unknown mesh ID → error. |
| `test_rl_duplicate_token_rejected` | Repeated selected ID → error. |
| `test_rl_empty_selector_rejected` | Present but empty selector → error. |
| `test_rl_action_profile` | Unsupported 3D or unknown profile → error. |
| `test_rl_max_controlled_nodes` | Invalid/valid capacities → error or correctly padded position count. |
| `test_rl_decision_interval` | Default, valid, fractional, excessive, invalid intervals → correct tick count or error. |
| `test_rl_tick_counts` | Fractional duration/tick ratios → the robust RL tick count and the truncating non-RL count. |
| `test_rl_removed_keys_rejected` | Removed `controlled_node_id`, `action_type` or `arrival_threshold_m` with RL enabled → error. |
| `test_rl_missing_selection_rejected` | No selector → error; no implicit last node. |
| `test_rl_gateway_selection_rejected` | The active traffic gateway in the selection → error. |
| `test_rl_duplicate_node_ids` | Duplicate node IDs → error; selection checks skipped when RL is disabled. |
| `test_rl_start_outside_bounds` | Controlled start outside bounds → error. |
| `test_rl_validator_reports_resolver_errors` | Invalid selection → validator reports it only with RL enabled. |
| `test_rl_safety_cases` | Invalid time, bounds, step, nodes, or waypoints → error, never an uncaught exception. |
| `test_controlled_start_position` | Fixed/waypoint/empty waypoint node → correct start or exception. |
| `test_apply_rl_control` | Resolved settings or invalid resolution → copied fields or exception. |

The C++ configuration suite also checks 18 generated mission scenarios
(2 environments × 3 missions × 3 team sizes) and rejects invalid dropout and
target cases. The C++ config, traffic and joint-motion suites cover explicit
mission geometry and pair rates.

`tests/integration/cli-integration-test.sh` Test 9 runs the one-slot smoke
scenario with closed stdin. It expects six lines (`init` plus five steps), a
first line advertising `"contract":"mesh_move_2d_v2"`, and `scored_ticks` on
every step; other CLI checks are described
in the [main verification section](@ref readme_verify).

## 8\. Ops and tooling tests

These use stub executors, `support/fake_slurm.py`, or a fake `rsync`; no cluster or
simulator is needed. Behavior is specified in [scripts/rl/ops](@ref scripts_rl_ops); the
[operations test map](ops-tests.md) groups the same files by behavior.
Parametrized tests cover several inputs each; only the pattern is listed.

### 8.1 cluster/test_ops_tasks.py

| Test | Input → expected output |
| --- | --- |
| `test_tracked_matrix_maps_to_eight_paired_tasks` | Tracked experiment matrix → eight paired train/evaluate tasks. |
| `test_malformed_plans_are_refused` | Malformed plan variants → error. |
| `test_plan_root_requires_a_plan_argument` | Missing plan argument → error. |
| `test_tolerated_table`, `test_tolerated_refuses_an_unknown_kind` | Step kind and exit code → tolerated or not; unknown kind → error. |
| `test_task_state_reports_both_steps_and_the_train_manifest_status` | Manifests on disk → per-step state and train status. |
| `test_failed_training_skips_the_evaluation` | Training exits 1 → evaluation not run. |
| `test_tolerated_evaluation_exit_is_recorded_but_not_a_failure` | Tolerated evaluation exit code → recorded, run succeeds. |
| `test_a_finished_training_is_skipped` | Completed train manifest → training not re-run. |
| `test_a_dirty_directory_is_refused_and_left_untouched` | Step directory with stray content → refusal, contents unchanged. |
| `test_an_out_of_range_task_index_is_refused` | Index beyond the task table → error. |
| `test_compare_*` (four tests), `test_a_tolerated_compare_exit_is_not_a_failure` | Unfinished evaluations → refused unless incomplete is allowed; tolerated compare exit is not a failure; exactly one selector required. |
| `test_comparison_outcome_reads_the_comparison_status` | `comparison.json` status → outcome string. |
| `test_non_object_artifacts_block_execution` | Non-object JSON artifact (list, `null`, string, number) → exercises the current policy experiment owner (step `blocked`) and the task status and comparison readers. |

### 8.2 cluster/test_ops_benchmark.py

| Test | Input → expected output |
| --- | --- |
| `test_ps_text_maps_to_one_process_tree`, `test_ps_parsing_skips_unusable_lines` | `ps` output text → one process tree; bad lines skipped. |
| `test_a_real_process_tree_is_measured` | Real child process → memory and process-count peaks recorded. |
| `test_a_ps_failure_nulls_memory_but_keeps_timing` | `ps` unavailable → memory fields `null`, wall time kept. |
| `test_effective_timesteps_round_up_to_whole_rollouts` | Requested steps and `n_steps` → next whole rollout, or `None` if invalid. |
| `test_seconds_format_as_hms` | Seconds → `HH:MM:SS`. |
| `test_a_measured_task_records_both_steps` | Fake launcher → record with train and evaluate steps. |
| `test_a_failed_training_stops_the_benchmark` | Training fails → benchmark stops. |
| `test_an_existing_record_is_refused`, `test_a_dirty_step_directory_is_refused` | Existing record or dirty step directory → refusal. |
| `test_estimate_arithmetic_scales_the_measured_seconds` | Benchmark record, matrix, safety factor → per-task and serial totals. |
| `test_the_estimate_takes_the_largest_step_peak` | Train/evaluate memory peaks → the larger one, or `None`. |
| `test_a_changed_selection_still_estimates_but_warns` | Differing selection → estimate with warning. |
| `test_a_mismatched_row_gets_no_estimate` | Row not matching the benchmark → no estimate, reason given. |
| `test_an_unmeasurable_benchmark_is_refused` | Benchmark without measurements → refused. |
| `test_estimate_writes_a_file_and_records_the_benchmark_hash` | Estimate run → estimate file with benchmark hash. |
| `test_a_missing_safety_factor_is_an_argparse_error`, `test_a_non_positive_safety_factor_is_refused` | Missing or non-positive safety factor → error. |

### 8.3 cluster/test_ops_cluster.py

| Test | Input → expected output |
| --- | --- |
| `test_the_example_config_is_refused_unedited`, `test_cluster_config_refusals`, `test_a_venv_without_bin_python_is_refused` | Unedited example, bad values, or bad venv → refused. |
| `test_a_valid_config_keeps_every_value` | Valid config → all values preserved. |
| `test_array_spec_compression` | Task indices and concurrency → compact `--array` spec. |
| `test_sbatch_argv_*`, `test_the_job_script_quotes_paths_and_exports_threads` | Config → `sbatch` argv (null values omitted, placement and dependency carried) and a quoted job script. |
| `test_parse_squeue_*`, `test_parse_sacct_*`, `test_parse_job_id` | Scheduler text → parsed rows and job IDs. |
| `test_a_missing_scheduler_binary_is_reported_not_raised` | No scheduler on PATH → reported, no exception. |
| `test_reconcile_state_table` and the pending, active, and compare-row tests | Filesystem, receipts, and queue snapshot → task state; active elements never resume-eligible; compare row follows `comparison.json`. |
| `test_plan_*`, `test_the_submit_resume_sequence`, `test_submit_refuses_*`, lock tests | `plan` writes the task table only; `submit`/`resume` submit the right elements; blocked directories, non-unsubmitted tasks, and a held lock → refused. |
| Intent and assertion tests (`test_sbatch_dying_*`, `test_an_unmatched_intent_*`, `test_abandoning_*`, `test_one_queue_match_*`, `test_a_known_job_*`, `test_an_assertion_*`, `test_no_second_job_*`) | sbatch failure or ambiguity → recoverable intent; no duplicate job for a covered task; human assertions cannot override active or populated tasks. |
| `test_cancel_*`, `test_a_failed_scancel_*` | Selectors → exact element IDs canceled, only from receipts; failed `scancel` not recorded. |
| `test_dry_runs_change_nothing`, `test_a_submit_dry_run_previews_the_argv_and_script` | `--dry-run` → preview, no writes. |
| `test_a_plan_from_another_root_is_refused`, `test_a_non_executable_binary_is_refused` | Foreign plan root or non-executable binary → refused. |
| `test_status_*`, `test_ops_never_writes_the_plan_or_a_step_directory` | `status` works without a scheduler, lists every task and the comparison, never writes. |
| `test_manual_compare_*`, `test_evidence_that_a_compare_job_ended_*`, `test_a_compare_job_without_*` | Manual compare reports each outcome and is refused while tasks or compare jobs are active or unresolved. |
| `test_a_new_compare_job_cancels_and_verifies_the_earlier_one`, `test_a_failed_cancellation_blocks_a_second_compare_job` | Resubmitted compare → earlier job canceled first; failed cancel blocks it. |

### 8.4 cluster/test_ops_fetch.py

| Test | Input → expected output |
| --- | --- |
| `test_each_category_adds_its_include_rules`, `test_the_always_included_files_need_no_selection`, `test_two_categories_are_combined_in_order` | Categories → `rsync` include rules. |
| `test_an_unknown_category_is_refused` | Unknown category → error. |
| `test_ignore_existing_is_always_passed` | Any run → `--ignore-existing` in the argv. |
| `test_a_non_empty_destination_is_refused_without_update` | Populated destination → refused unless update. |
| `test_dangerous_destinations_are_refused`, `test_a_destination_symlink_cannot_bypass_the_checks`, `test_a_local_source_inside_the_destination_is_refused` | Root, home, mesh root, symlinked, or overlapping destination → refused. |
| `test_a_missing_rsync_is_reported_not_crashed` | No `rsync` → reported error. |
| `test_task_states_come_from_the_rebased_remote_paths`, `test_unfetched_manifests_are_never_reported_as_missing_tasks` | Fetched manifests → task states and incompleteness. |
| `test_the_comparison_state_is_read_when_selected` | Fetched `comparison.json` → comparison state. |
| `test_the_manifest_records_remote_argv_and_file_digests`, `test_update_keeps_the_earlier_manifest` | Fetch → provenance manifest with argv and digests; update keeps the earlier one. |
| `test_a_failed_rsync_writes_no_manifest`, `test_dry_run_prints_the_argv_and_writes_nothing` | Failed rsync or dry run → no manifest. |

### 8.5 tuning/test_ops_tune.py

| Test | Input → expected output |
| --- | --- |
| `test_bad_specs_are_refused_before_anything_runs`, `test_refusal_messages_name_the_offending_setting` | Invalid study specs (unknown key, fixed budget, bad ranges, seeds, cadence) → refused with a message naming the setting. |
| `test_an_existing_study_directory_is_refused` | Existing study directory → refused. |
| `test_a_missing_binary_is_refused_unless_the_run_is_dry` | Missing binary → refused; dry run allowed. |
| `test_trial_arguments_carry_the_sampled_values_and_the_right_seeds` | Sampled values → trial arguments with correct seeds. |
| `test_a_sampled_value_equal_to_a_held_out_seed_is_not_refused`, `test_a_held_out_seed_in_a_seed_flag_is_refused` | Held-out seed as a sampled value → allowed; in a seed flag → refused. |
| `test_no_plan_file_is_written_for_a_trial` | Trial → no plan file. |
| `test_a_completed_study_records_objectives_and_the_best_training_block` | Stub trainer → study record with objectives and best block. |
| `test_a_failed_trial_is_recorded_and_the_study_continues` | Trial failure → recorded; later trials still run. |
| `test_a_dry_run_prints_commands_without_creating_anything` | `--dry-run` → commands printed, nothing created. |
| `test_the_install_hint_names_the_pin_file`, `test_the_pin_file_holds_one_exact_optuna_pin`, `test_a_version_other_than_the_pin_is_refused` | Optuna missing or wrong version → refusal naming the pin file. |
| `test_the_seeded_sampler_matches_its_dry_run_preview`, `test_two_runs_with_the_same_sampler_seed_agree` | Same sampler seed → same trials as the preview and across runs. |

### 8.6 tooling/test_bootstrap_venv.py

| Test | Input → expected output |
| --- | --- |
| `test_direct_pins_match_probe_dependencies` | `requirements.txt` → pinned names equal `DIRECT_DEPS`. |
| `test_version_probe_rejects_mismatch` | Wrong expected version → probe exits 1 and reports `expected 0.0.invalid`. |

## 9\. Supporting behavior

| File | What it checks |
| --- | --- |
| `policy/test_baseline_statistics.py` | Node service conservation, zero-demand masking, compact commands, jammer onset schedules, immutable baseline rescoring and delayed-jammer metrics. |
| `policy/test_adaptation_metrics.py` | Dense fairness feedback, previous-health movement cost/reset, PPO/network wiring, route variation and real online updates versus a frozen sampled control on the fake simulator. |
| `experiments/test_preflight_challenge.py` | Manifest cadence, final totals, hold/challenge acceptance, criteria fingerprints, policy-library dispatch and read-only completed-check reuse. |
| `experiments/test_module_boundaries.py` | No numbered research runtime modules or retired imports; environment/agents independent of public CLIs; batch definitions independent of execution owners. |
| `env/test_config_readers.py` | INI precedence/bounds, progress/output settings, jammer onset schedules and invalid actions. |
| `experiments/test_experiment_matrix.py` | Generated signed reward weights reach the actual training parser. |

The scheduler/process equivalents of retired campaign tests live in
`ops/test_ops_local.py`, `ops/test_ops_process.py` and `ops/test_ops_recovery.py`;
see [the operations test map](ops-tests.md). Historical fixed campaign inventory
counts are not maintained as public runtime behavior.

## 10\. Mission and coordination behavior

| Tests | Contract exercised |
| --- | --- |
| `env/test_binary_objectives.py`, `env/test_continuous_objectives.py` | Sparse/graded goals, demand eligibility, event windows, schema identity and gated online buffer accounting. |
| `policy/test_movement_and_exploration.py` | Available-peer travel, weakest service, target roles, wall contacts, sampling/stall schedules, reward replay and protocol compatibility. |
| `env/test_proximity_and_compact_inputs.py`, `env/test_target_arrival.py` | Pairwise closeness, demanded-path margin, potential telescoping, compact feature layout, arrival/departure and saved observation hashes. |
| `env/test_coordination_state.py` | Dwell/hysteresis/relapse, stage reset, low-tail/isolation, complete reward decomposition, observation extensions, live env hooks, replay and tamper rejection. |
| `env/test_team_radio_and_curriculum.py` | Global radio partitions, failed relays, one-feature observation changes, saved decomposition and curriculum episode counting. |
| `policy/test_qualification_and_checkpoints.py`, `agents/test_training_milestones.py` | Coverage qualification/fallback, graph unity, optimized checkpoint timing, complete milestone retention and training-hook wiring. |
| `env/test_mission_facts.py`, `env/test_physical_audit.py`, `env/test_geometry.py`, `env/test_curriculum.py`, `env/test_seeded_env.py`, `policy/test_model_compatibility.py` | Mission counters/validation, safe segments and routes, peer collisions, legal curriculum starts, seeded reset and actual saved ZIP loading. |
| `experiments/test_scenario_check.py`, `experiments/test_preflight_challenge.py` | Scenario acceptance gates, normalized traffic, route legality, jammer timing, feature checks and challenge difficulty. |
| `experiments/test_matrix_v2.py`, `experiments/test_conversion_parity.py` | Explicit job expansion, seed/config lookup separation, existing-parent continuation, shared pools, schedules, checks and selection contracts. |
| `experiments/test_gui_index.py`, `policy/test_operation.py`, `ops/test_ops_local.py`, `ops/test_ops_recovery.py` | Complete GUI inventories, independent operation seeds/modes, frozen weights, receipts, concurrency, identity refusal and interrupted-work recovery. |

Saved-data checks skip when private campaign evidence is unavailable. They read
results; they do not recreate historical runners. Native checks belong to
`integration/test_real_binary.py` and are user-run only.

## 11\. Batch operation and env-owner tests

These cover the owners that batch tasks call
([batch experiment reference](@ref mesh_sim_rl_batch_reference)). They use
`support/fake_sim.py`, an in-process stub environment or synthetic facts; none runs
the native simulator. Cases needing `sb3_contrib` skip without it. Run from
`scratch/mesh-sim/`:

```bash
.venv/bin/python -m pytest -q -rs scripts/rl/tests/policy/test_online_protocols.py \
  scripts/rl/tests/policy/test_operation.py scripts/rl/tests/policy/test_operate_cli.py \
  scripts/rl/tests/policy/test_operate_integration.py scripts/rl/tests/policy/test_schedules.py \
  scripts/rl/tests/policy/test_replay_and_audit.py scripts/rl/tests/policy/test_episode_review.py \
  scripts/rl/tests/policy/test_scripted_mission_policy.py scripts/rl/tests/policy/test_model_compatibility.py \
  scripts/rl/tests/env/test_geometry.py scripts/rl/tests/env/test_curriculum.py \
  scripts/rl/tests/env/test_seeded_env.py
```

### 11.1 policy/test_online_protocols.py

| Test | Input → expected output |
| --- | --- |
| `test_eligibility_keeps_zero_demand_but_excludes_forced_windows` | Per-mission window facts → zero-demand windows stay eligible; forced deployment-prefix windows are excluded. |
| `test_partial_batch_never_has_a_singleton_or_pads` | Rollout sizes → minibatch sizes with no singleton and no padding. |
| `test_gated_update_accounting_and_final_partial_flush`, `test_gated_singleton_tail_is_skipped_and_counted` | Gated episode → update cycles, trained/tail decisions balance; final partial rollout flushed; a singleton tail skipped and counted. |
| `test_gated_ineligible_gap_refused_only_with_unflushed_buffer` | Ineligible window after eligible ones → error only while the eligible buffer is unflushed. |
| `test_gated_settings_inherit_and_refuse_target_kl` | Parent hyperparameters → inherited gated settings; non-null `target_kl` or missing keys → error. |
| `test_sb3_defaults_and_explicit_overrides` | No overrides → `min(parent lr, 1e-4)`, entropy 0.001, target KL 0.02; explicit values kept. |
| `test_sb3_operation_records_tail_and_v5_fields` | SB3 operation → batch online record with `protocol`, settings, digests, `budget % n_steps` tail and accounting. |
| `test_gated_operation_reloads_parent_per_seed` | Two seeds → each starts from the parent's parameter and optimizer digests. |
| `test_legacy_cli_envelope_v3_default_and_v4_other_orders` | Standalone `run_online` with the default tuple, a subset and a reversed order → legacy versions and key order unchanged. |
| `test_online_cli_reexports_existing_helpers` | `scripts.rl.online` → `parameter_digest`, `UpdateRecorder`, `operation_modes`, `DEFAULT_MODES`, `run_online` still importable. |
| `test_online_protocols_refuse_schedules_and_unknown_settings` | Schedule or unknown key on an online mode → error. |

### 11.2 Operations, schedules, replay and review

| Test | Input → expected output |
| --- | --- |
| `policy/test_schedules.py::test_initial_sampling_exactly_n_eligible_decisions` | `initial-sampling` → sampling for exactly N eligible decisions. |
| `policy/test_schedules.py::test_stall_trigger_burst_cooldown_and_limit`, `::test_stall_progress_trigger_when_slots_move` | Rejection and progress stalls → bursts, cooldown and `max_bursts` limit. |
| `policy/test_schedules.py::test_coverage_qualification_relapse_and_severe_loss`, `::test_coverage_rules_are_the_documented_versioned_constants` | Coverage schedules → 30 s qualification, 5 s relapse and severe-loss fallback from the versioned constants. |
| `policy/test_schedules.py::test_schedule_settings_refused_without_defaults` | Missing or inconsistent schedule settings → error; no defaults supplied. |
| `policy/test_replay_and_audit.py::test_replay_comparison_stops_on_changed_fact_mask_or_observation`, `::test_replay_pre_contact_variant_ignores_only_the_new_contact_field`, `::test_replay_policy_refuses_newly_masked_action` | Saved vs replayed rows → stop on any changed fact, mask or observation; the pre-contact variant ignores only `boundary_contacted_slots`; a newly masked action is refused. |
| `policy/test_replay_and_audit.py::test_replay_gate_passes_identical_physics_and_stops_on_change` | Fake replay → `gate_passed` true for identical physics, false after a change. |
| `policy/test_replay_and_audit.py::test_reward_audit_methods_are_separately_named`, `::test_position_replay_reconstructs_and_detects_tampering`, `::test_reward_audit_recomputes_only_for_matching_identities` | Saved telemetry → named methods, exact reconstruction, tamper detection, refusal on mismatched schema or seed identity. |
| `policy/test_operation.py::test_frozen_modes_keep_parameter_and_optimizer_digests`, `::test_frozen_operation_refuses_changed_optimizer` | Frozen operation → digests unchanged; a changed optimizer state fails. |
| `policy/test_operation.py::test_scheduled_frozen_operation_logs_switches` | `sample-then-hold` on a frozen operation → schedule metadata in `online_manifest.json`, unchanged digests, per-decision executed states in `coverage_execution.json` with zero optimizer updates. |
| `policy/test_operation.py::test_seeded_adapter_uses_first_declared_seed` | Seeded adapter → the first declared evaluation seed is used for construction. |
| `policy/test_operation.py::test_gates_come_from_native_settings` | Gates resolve from native `control_start_s`; a case gate that differs is refused. |
| `policy/test_operation.py::test_per_seed_scenario_difference_is_explicit` | A per-seed INI differing only in native timing → an explicit, prevalidated difference; a changed nodes file → refused. |
| `policy/test_operation.py::test_gated_and_sampling_operations_need_the_declared_mission`, `::test_band_and_decision_records_reach_the_seeded_env_and_record` | Missing case mission → error; band and decision-record settings reach every seed's env and the record. |
| `policy/test_operate_cli.py` (`test_operate_help_and_usage_errors_exit_one`, `test_model_command_dispatches_contract_arguments`, `test_baseline_and_check_commands_dispatch`) | `scripts.rl.operate` → usage errors exit 1; plan argument lists dispatch to the owners. |
| `policy/test_replay_and_audit.py::test_check_result_passed_truth_table` | `check_result.json` → the pass truth table. |
| `policy/test_operate_integration.py::test_operate_end_to_end_frozen_model_and_hold_baseline` | A frozen model and a hold baseline, end to end on the fake simulator. |
| `policy/test_operate_cli.py::test_placement_baselines_delegate_to_the_evaluate_placement_path`, `policy/test_operate_integration.py::test_placement_baseline_end_to_end_with_the_stub_planner` | `operate baseline --policy geometric` or `optimization` → the existing evaluate placement path with its planning seed, unchanged; end to end with a stub planner on the fake simulator. |
| `policy/test_operate_integration.py::test_bound_checkpoint_of_an_interrupted_run_needs_its_binding` | A checkpoint of an interrupted (unfinished) training attempt → refused without `--binding`; accepted through the verified binding. |
| `policy/test_episode_review.py::test_scene_review_without_models_is_a_valid_empty_v1_payload` | `episode_review.scene_review` with no models → a valid empty version 1 review. |
| `policy/test_episode_review.py::test_scene_review_reads_explicit_baselines_before_the_legacy_path` | Explicit baseline references are read before legacy paths. |
| `policy/test_episode_review.py::test_scene_review_resolves_v5_episode_dirs_against_their_manifest` | Version 5 episode directories resolve relative to their manifest. |

### 11.3 Geometry, curriculum, and model compatibility

| Test | Input → expected output |
| --- | --- |
| `env/test_geometry.py` (`test_segment_hits_*`, `test_physical_audit_expected_values`, `test_route_and_swept_distance_fixed_values`) | Segments, boxes and routes → fixed expected values. |
| `env/test_curriculum.py` (`test_validate_positions_rejects_violations`, `test_starts_from_reference_expected_values`, `test_pinned_curriculum_frames_validate_pinned_frames`) | Curriculum starts → legal positions with fixed expected values; violations rejected. |
| `env/test_curriculum.py` (`test_curriculum_counts_completed_episodes_not_probe_resets`, `test_curriculum_schedule_file_records_stage_hashes`, `test_load_curriculum_schedule_hashes_and_validates`) | Curriculum env and schedule file → stage switches by completed episodes; stage INI hashes recorded and validated. |
| `env/test_seeded_env.py` (`test_seeded_env_*`, `test_scenario_check_seeded_env_keeps_initial_seed_and_scopes_cancellation`) | Per-seed INI maps → the right config, band, decision records and `seed_source` per reset; `scenario_check` keeps its initial-seed and cancel behavior. |
| `policy/test_scripted_mission_policy.py` (`test_scripted_mission_policy_*`, `test_reference_policy_*`) | Both route formats → waypoint following, delivery triggers, gates, swept reservation and mask-valid actions only. |
| `policy/test_scripted_mission_policy.py::test_scenario_check_geometry_reexports_owners` | `scenario_check.geometry` → re-exports the env geometry owners. |
| `policy/test_model_compatibility.py::test_saved_zip_with_renamed_registry_inputs_deserializes` | Tiny model trained on the fake simulator with renamed registry modules → ZIP holds no `scripts.rl` or `env.phase` reference and loads with legacy modules blocked. |
| `policy/test_model_compatibility.py::test_historical_zip_deserializes_without_legacy_modules` | One real saved model → loads without legacy modules. Skips unless `MESH_HISTORICAL_ZIP` is set; a skip is missing evidence, not a pass. |

Native execution authority: these tests never build or run the simulator.
The human builds the binary and runs real-binary checks and the batch native
smoke; until then those checks are BLOCKED, not passed.

### 11.4 Regression checks

| Owner | Input → expected behavior |
|---|---|
| `experiments/test_matrix_v2.py` (replay) | Replay variant/parent/case/audit → emitted argv, hashed inputs and distinct task identities. |
| `experiments/test_matrix_v2.py` (refusals) | Unsupported preflight, undeclared seed and overshooting non-mission budget → early refusal; missing v1 binary → exit 2. |
| `policy/test_replay_and_audit.py::test_replay_parent_contact_and_jammer_checks` | Fake simulator with real PPO, saved pre-contact trace → strict refusal / pre-contact pass, boundary evidence and verified parent; parent or jammer-timing mismatch → failed gate. |
| `policy/test_online_protocols.py::test_gated_loaded_settings_match_before_adaptation` | Loaded inherited settings, including callable clip range → equality required before adaptation; altered settings refused. |
| `experiments/test_conversion_parity.py::test_inventory_comparison_detects_changed_replay_contract` | Change gate variant, parent, case or audit flag independently → parity difference reported. |
| `policy/test_operate_integration.py` binding test | Copy an otherwise valid scheduler binding outside `state/bindings/` → refused. |

Contact evidence is owned by `policy/episode_review.py::contact_audit`; there is no duplicated legacy implementation. Fake checks prove plumbing and failure
handling, not radio equivalence. Native replay remains human-only.

## 12\. History

Research-specific runner inventory tests were retired with those runners.
Their reusable reward, observation, stage transition, online buffer, sampling,
physical safety and checkpoint assertions now have behavior names in these
packages. Matrix expansion, selection, GUI indexes and recovery are checked by
`experiments/test_matrix_v2.py`, `experiments/test_gui_index.py`,
`policy/test_operation.py` and `ops/test_ops_recovery.py`.
