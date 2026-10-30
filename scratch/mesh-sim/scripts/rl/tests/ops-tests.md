# Operations test map {#scripts_rl_ops_tests}

Run from `scratch/mesh-sim/`:

```bash
.venv/bin/python -m pytest scripts/rl/tests/cluster/test_ops_tasks.py scripts/rl/tests/cluster/test_ops_benchmark.py scripts/rl/tests/tuning/test_ops_tune.py scripts/rl/tests/ops/test_ops_process.py scripts/rl/tests/cluster/test_ops_cluster.py scripts/rl/tests/cluster/test_cluster_recovery.py -q -rs
```

| Test group | Input and expected behavior |
| --- | --- |
| `cluster/test_ops_tasks.py` | Planned task mapping, pending/done/partial steps, exit tolerance, compare prerequisites and records: only eligible steps execute; raw exits and skipped work are preserved. |
| `cluster/test_ops_benchmark.py` measurement | Stub process/ps data and manifests: timing, peak tree memory, step completion and version 2 records are saved; dirty steps/existing records are refused. |
| `test_benchmark_failure_stops_and_reaps_process_group` | Ordinary wait or sampler startup failure after spawning a fake Python child: process group is stopped and parent reaped. |
| `ops/test_ops_process.py` | SIGINT/SIGTERM during a fake parent/descendant run: both stop, parent is reaped, prior handlers restore. No simulator or `ps` query is used. |
| `test_estimate_rejects_failed_or_incomplete_measurements` | Failed train, failed/partial evaluation and old schema despite present timing rates: estimate is refused. |
| `test_estimate_uses_configured_evaluation_cadence` | Target and measured evaluation episode counts match at 3: estimation accepts the configured cadence. |
| Existing estimate tests | Known seconds, timestep rounding, memory peaks, changed scenario/cadence/selection: arithmetic is correct, incompatible rows are excluded and changed selection is labeled. |
| `tuning/test_ops_tune.py` configuration | Unknown trainer/settings, invalid distributions, seeds, nonfinite bounds, cadence and missing dependencies: refuse before training; trial commands preserve fixed budgets and seed roles. |
| Running/recovery tests | Prelaunch records, interrupted/unfinished training, completed training awaiting reconciliation and completed studies: preserve completed trials, reconcile results once, mark incomplete attempts failed and launch only remaining attempts. |
| Checkpoint/writer tests | Changed spec, corrupt checkpoint, second writer and failed JSON mirror: refuse incompatible state/concurrent writes; authoritative checkpoint permits mirror recovery. |
| `test_build_failure_records_and_closes_the_asked_trial` | Command construction fails after sampling: record the failure and close its Optuna trial; no hidden running trial remains. |
| `test_interrupted_sampler_mutation_is_not_committed_without_its_record` | Real ask/tell mutates a proposed study, then interruption occurs: discard that proposal; recovery retains consistent records and the candidate sequence. |
| `test_adaptive_search_and_resume_preserve_seeded_continuation` | Real pinned Optuna with a synthetic objective past startup, then interruption after an adaptive trial: resumed candidates/objectives/best equal uninterrupted execution. |
| `test_a_real_process_tree_is_measured` | Live fake Python process tree and real `ps`: measure parent/descendants. Skip with `BLOCKED:` if the environment prohibits process queries; that is missing evidence, not a pass. |

Stub training and synthetic objectives establish orchestration and sampler behavior,
not simulator integration or learning. No test here runs a real simulator.
Real process sampling and target-cluster benchmarking need their own environment;
a laptop measurement does not predict cluster throughput.

| Cluster group | Input and expected behavior |
| --- | --- |
| `cluster/test_ops_cluster.py` | Fake sbatch/squeue/sacct/scancel: closed config, argv/scripts, task states, submissions, assertions, cancellation and comparison exits. No real scheduler jobs or simulator run. |
| `test_foreign_receipts_refuse_mutations_without_side_effects` | Another receipt owner: plan/submit/resume/assert/cancel/compare refuse before scheduler calls or artifact writes. |
| `test_status_queries_the_recorded_owner_without_writing` | Foreign receipt inspected read-only: scheduler uses recorded user, filesystem unchanged. |
| Compare-only tests | Covered/finished tasks, missing comparison, refused/lost response: queue only comparison; retain no-ID intents; recover accepted jobs without duplicates; record explicit abandonment before replacement. |
| Lock tests | Existing operation lock or comparison executing: every mutation refuses; local and scheduled comparison hold the same lock; exceptions release it. |
| Termination tests | Successful cancellation without terminal evidence, unfamiliar state, delayed cancellation: writer remains blocked until recognized termination or checked assertion. |
| Historical recovery | Explicit `sacct --starttime` before intent creation: prior-day jobs remain searchable in recovery and abandonment checks. |
| Script/runtime checks | Scheduled comparison verifies its receipt/job ID and records results; quoted scripts invoke the locked cluster path. |

Receipt version 2 adds a compare-only kind; owned version 1 receipts remain
readable. Status version 2 removes cancellation-request-as-termination inference.
Live-site scheduler/account visibility and shared-filesystem locking remain
unverified; see `TODO-RL-OPS-1`.

## Batch scheduler and recovery

Version 2 batches (plan v3) are executed by `ops/local.py` and resumed by
`ops/recovery.py`; see the
[batch experiment reference](@ref mesh_sim_rl_batch_states). Run from
`scratch/mesh-sim/`:

```bash
.venv/bin/python -m pytest -q -rs scripts/rl/tests/ops/test_ops_local.py scripts/rl/tests/ops/test_ops_recovery.py
```

| Test group | Input and expected behavior |
| --- | --- |
| `test_matrix_v2.py::test_run_and_status_fail_cleanly_without_the_scheduler` | Plan v3 root with the scheduler owner absent: `run` refuses before writing anything; `status` and `resume` fail with a named import error, exit 1. |
| `test_matrix_v2.py::test_run_delegates_with_resolved_execution` | `run` with CLI and matrix execution settings: the scheduler receives the root and CLI > matrix > default settings with their sources. |
| `test_matrix_v2.py::test_launcher_*` | `bash -n`, `--dry-run` quoting of paths with spaces, both flag forms and `MESH_SIM_BIN` normalized against the invoking directory; a real `validate` from another directory. No simulator. |
| `test_ops_local.py::test_dag_completes_with_receipts_status_bindings_and_logs` | Inert children over a multi-task plan → every task `completed` with receipts, `campaign_status.json`, bindings and per-attempt logs. |
| `test_ops_local.py::test_root_lock_refuses_a_second_supervisor`, `::test_per_root_worker_cap`, `::test_pool_capacity_mismatch_is_refused`, `::test_shared_pool_caps_two_supervisors` | Second supervisor on one root refused; worker cap per root; a pool with another capacity refused; two supervisors share one pool cap. |
| `test_ops_local.py::test_worker_crash_keeps_slot_until_owned_child_is_reaped`, `::test_sigint_stops_reaps_records_interrupted_and_releases_slots` | Worker crash keeps its slot until the owned child is reaped; SIGINT stops and reaps owned groups, records `interrupted`, releases slots, exits 130. |
| `test_ops_local.py::test_continue_and_stop_failure_policies`, `::test_selection_branches_skip_unselected_rows`, `::test_warning_exit_partial_and_train_exit_two` | `continue`/`stop`; unselected branches `skipped_selection`; exit 2 a warning only where tolerated, `partial` for incomplete outputs, train exit 2 a failure. |
| `test_ops_local.py::test_sixteen_leaves_get_distinct_receipts_and_attempts`, `::test_malformed_receipt_and_unknown_directory_are_blocked`, `::test_changed_output_hash_invalidates_the_accepted_attempt`, `::test_step_dispatch_is_allowlisted_and_placeholders_must_resolve` | 16 leaves → 16 receipts and attempt directories; malformed receipt or receipt-less directory → `blocked`; changed accepted output → invalidated; only allowlisted modules run and every placeholder must resolve. |
| `test_ops_recovery.py::test_identity_is_pinned_once_and_changes_are_refused_before_dispatch`, `::test_parent_model_zip_change_is_refused`, `::test_source_change_during_a_batch_stops_dispatch` | `runtime_identity.json` written once; changed code, inputs, parent ZIP or a source edited mid-batch → refused before dispatch. |
| `test_ops_recovery.py::test_interrupt_before_first_checkpoint_is_blocked`, `::test_terminal_zip_without_final_manifest_is_blocked` | No verified checkpoint, or a terminal ZIP without a final manifest → `blocked`, never restarted from zero. |
| `test_ops_recovery.py::test_checkpoint_recovery_128_to_256_and_ancestor_milestone` | Training interrupted after checkpoint 128 → `resume_checkpoint` to 256 with the abandoned tail excluded; all checkpoint-128 operate tasks bind the interrupted attempt's checkpoint. |
| `test_ops_recovery.py::test_one_interrupted_seed_retries_alone`, `::test_malformed_receipt_and_changed_output_are_listed_in_the_proposal`, `::test_replaced_bound_zip_blocks_the_consumer` | One interrupted seed retried alone with completed siblings kept; defects listed in the proposal; a replaced bound ZIP blocks its consumer. |

The scheduler and recovery tests use inert child, worker and supervisor entry
points on the fake simulator and temporary artifacts only; they pin
`recovery._source_root` to a private tree so concurrent source edits do not trip
the identity refusal. The native interrupted/resumed smoke is a human-run check and
is BLOCKED until executed.
