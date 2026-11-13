# Operations test map {#scripts_rl_ops_tests}

Tests for [experiment operations](@ref scripts_rl_ops): tasks, benchmarks,
tuning, cluster runs, fetch and local batches. Run them from
`scratch/mesh-sim/`:

```bash
.venv/bin/python -m pytest -q -rs \
  scripts/rl/tests/cluster scripts/rl/tests/ops scripts/rl/tests/tuning/test_ops_tune.py
```

No test here runs a real simulator or scheduler. Stub training and synthetic
objectives establish orchestration and sampler behavior, not simulator
integration or learning. Real process sampling and target-cluster benchmarking
need their own environment; a laptop measurement does not predict cluster
throughput.

## 1\. Tasks, benchmarks and processes

| Test | Input and expected behavior |
| --- | --- |
| `cluster/test_ops_tasks.py` | Planned task mapping, pending/done/partial steps, exit tolerance, compare prerequisites and records: only eligible steps execute; raw exits and skipped work are preserved. |
| `cluster/test_ops_benchmark.py` (measurement) | Stub process/ps data and manifests: timing, peak tree memory, step completion and version 2 records are saved; dirty steps/existing records are refused. |
| `cluster/test_ops_benchmark.py::test_benchmark_failure_stops_and_reaps_process_group` | Ordinary wait or sampler startup failure after spawning a fake Python child: the process group is stopped and the parent reaped. |
| `cluster/test_ops_benchmark.py::test_estimate_rejects_failed_or_incomplete_measurements` | Failed train, failed/partial evaluation and old schema despite present timing rates: the estimate is refused. |
| `cluster/test_ops_benchmark.py::test_estimate_uses_configured_evaluation_cadence` | Target and measured evaluation episode counts match at 3: estimation accepts the configured cadence. |
| `cluster/test_ops_benchmark.py` (other estimate tests) | Known seconds, timestep rounding, memory peaks, changed scenario/cadence/selection: arithmetic is correct, incompatible rows are excluded and changed selection is labeled. |
| `cluster/test_ops_benchmark.py::test_a_real_process_tree_is_measured` | Live fake Python process tree and real `ps`: measure parent and descendants. Skips with `BLOCKED:` if the environment prohibits process queries; that is missing evidence, not a pass. |
| `ops/test_measurement_boundaries.py` | Injected launches and `ps` snapshots: descendants still count after the root exits, and the first sample is taken immediately after spawn. |
| `ops/test_ops_process.py` | SIGINT/SIGTERM during a fake parent/descendant run: both stop, the parent is reaped and prior handlers are restored. No simulator or `ps` query. |

## 2\. Tuning

| Test | Input and expected behavior |
| --- | --- |
| `tuning/test_ops_tune.py` (configuration) | Unknown trainer/settings, invalid distributions, seeds, nonfinite bounds, cadence and missing dependencies: refuse before training; trial commands preserve fixed budgets and seed roles. |
| `tuning/test_ops_tune.py` (running and recovery) | Prelaunch records, interrupted/unfinished training, completed training awaiting reconciliation and completed studies: preserve completed trials, reconcile results once, mark incomplete attempts failed and launch only remaining attempts. |
| `tuning/test_ops_tune.py` (checkpoint and writer) | Changed spec, corrupt checkpoint, second writer and failed JSON mirror: refuse incompatible state and concurrent writes; the authoritative checkpoint permits mirror recovery. |
| `tuning/test_ops_tune.py::test_build_failure_records_and_closes_the_asked_trial` | Command construction fails after sampling: record the failure and close its Optuna trial; no hidden running trial remains. |
| `tuning/test_ops_tune.py::test_interrupted_sampler_mutation_is_not_committed_without_its_record` | Real ask/tell mutates a proposed study, then an interruption: the proposal is discarded; recovery keeps consistent records and the candidate sequence. |
| `tuning/test_ops_tune.py::test_adaptive_search_and_resume_preserve_seeded_continuation` | Real pinned Optuna with a synthetic objective past startup, interrupted after an adaptive trial: resumed candidates, objectives and best equal an uninterrupted run. |

## 3\. Cluster runs

Every scheduler here is a fake (`scripts/rl/tests/support/fake_slurm.py` or
canned shims under `tmp_path`); no real SLURM command runs.

| Test | Input and expected behavior |
| --- | --- |
| `cluster/test_ops_cluster.py` | Fake sbatch/squeue/sacct/scancel: closed config, argv and scripts, task states, submissions, assertions, cancellation and comparison exits. |
| `cluster/test_slurm_jobs.py` | Scheduler adapter edges: parsers, config schema, argv, job scripts and query shims. |
| `cluster/test_submission_failures.py` | CLI flows: the submission protocol, compare, cancel and refusals. |
| `cluster/test_reconciliation_edges.py` | Receipt × scheduler × filesystem combinations → the reported state, resume rules and the single writer of `comparison.json`. |
| `cluster/test_cluster_recovery.py::test_foreign_receipts_refuse_mutations_without_side_effects` | Another receipt owner: plan/submit/resume/assert/cancel/compare refuse before scheduler calls or artifact writes. |
| `cluster/test_cluster_recovery.py::test_status_queries_the_recorded_owner_without_writing` | Foreign receipt inspected read-only: the scheduler uses the recorded user; the filesystem is unchanged. |
| `cluster/test_cluster_recovery.py` (compare-only) | Covered/finished tasks, missing comparison, refused/lost response: queue only the comparison; retain no-ID intents; recover accepted jobs without duplicates; record explicit abandonment before replacement. |
| `cluster/test_cluster_recovery.py` (locks) | Existing operation lock or comparison executing: every mutation refuses; local and scheduled comparison hold the same lock; exceptions release it. |
| `cluster/test_cluster_recovery.py` (termination) | Successful cancellation without terminal evidence, unfamiliar state, delayed cancellation: the writer stays blocked until recognized termination or a checked assertion. |
| `cluster/test_cluster_recovery.py` (history) | Explicit `sacct --starttime` before intent creation: prior-day jobs remain searchable in recovery and abandonment checks. |
| `cluster/test_cluster_recovery.py` (scripts and runtime) | The scheduled comparison verifies its receipt/job ID and records results; quoted scripts invoke the locked cluster path. |
| `ops/test_receipt_concurrency.py` | Many concurrent submitters: exactly one gets the lock; allocations never share a number; loading orders by submission and ignores temporary and foreign files. |

Receipt version 2 adds a compare-only kind; owned version 1 receipts remain
readable. Status version 2 removes cancellation-request-as-termination
inference. Live-site scheduler/account visibility and shared-filesystem locking
remain unverified; see `TODO-RL-OPS-1`.

## 4\. Fetch

| Test | Input and expected behavior |
| --- | --- |
| `cluster/test_ops_fetch.py` | CLI/category refusals, argv, destination and symlink checks, copied task/comparison states, local inventory/digests, manifest history, dry-run and transfer failures. |
| `cluster/test_ops_fetch_local.py` | Installed rsync's real include/exclude behavior for every category, checkpoint/baseline/decision artifacts, unchanged local files on update, fresh destination refresh, and malformed copied states. |
| `cluster/test_retrieval_safety.py` | No selection ever adds a deleting or overwriting rsync option; a failed rsync leaves no manifest even after partial files; repeated updates keep every earlier manifest. |

The fake transfer tool stages controlled fixtures and failures without network
access and does not implement rsync filtering. Real transfer tests use only
pytest's temporary local directories and skip if rsync is unavailable.

## 5\. Batch scheduler and recovery

Version 2 batches (plan v3) are executed by `ops/local.py` and resumed through
`ops/recovery.py`, with runtime identity in `ops/batch_identity.py`, receipts
and bindings in `ops/batch_receipts.py`, and locks and slots in
`ops/batch_processes.py`; see the
[batch experiment reference](@ref mesh_sim_rl_batch_states).

| Test | Input and expected behavior |
| --- | --- |
| `experiments/test_experiment_launcher.py::test_run_and_status_fail_cleanly_without_the_scheduler` | Plan v3 root with the scheduler owner absent: `run` refuses before writing anything; `status` and `resume` fail with a named import error, exit 1. |
| `experiments/test_experiment_launcher.py::test_run_delegates_with_resolved_execution` | `run` with CLI and matrix execution settings: the scheduler receives the root and CLI > matrix > default settings with their sources. |
| `experiments/test_experiment_launcher.py::test_launcher_*` | `bash -n`, `--dry-run` quoting of paths with spaces, both flag forms and `MESH_SIM_BIN` normalized against the invoking directory; a real `validate` from another directory. No simulator. |
| `ops/test_ops_local.py::test_dag_completes_with_receipts_status_bindings_and_logs` | Inert children over a multi-task plan → every task `completed` with receipts, `campaign_status.json`, bindings and per-attempt logs. |
| `ops/test_ops_local.py::test_root_lock_refuses_a_second_supervisor`, `::test_per_root_worker_cap`, `::test_pool_capacity_mismatch_is_refused`, `::test_shared_pool_caps_two_supervisors` | Second supervisor on one root refused; worker cap per root; a pool with another capacity refused; two supervisors share one pool cap. |
| `ops/test_ops_local.py::test_worker_crash_keeps_slot_until_owned_child_is_reaped`, `::test_sigint_stops_reaps_records_interrupted_and_releases_slots` | Worker crash keeps its slot until the owned child is reaped; SIGINT stops and reaps owned groups, records `interrupted`, releases slots, exits 130. |
| `ops/test_ops_local.py::test_continue_and_stop_failure_policies`, `::test_selection_branches_skip_unselected_rows`, `::test_warning_exit_partial_and_train_exit_two` | `continue`/`stop`; unselected branches `skipped_selection`; exit 2 a warning only where tolerated, `partial` for incomplete outputs, train exit 2 a failure. |
| `ops/test_ops_local.py::test_sixteen_leaves_get_distinct_receipts_and_attempts`, `::test_malformed_receipt_and_unknown_directory_are_blocked`, `::test_changed_output_hash_invalidates_the_accepted_attempt`, `::test_step_dispatch_is_allowlisted_and_placeholders_must_resolve` | 16 leaves → 16 receipts and attempt directories; malformed receipt or receipt-less directory → `blocked`; changed accepted output → invalidated; only allowlisted modules run and every placeholder must resolve. |
| `ops/test_ops_recovery.py::test_identity_is_pinned_once_and_changes_are_refused_before_dispatch`, `::test_parent_model_zip_change_is_refused`, `::test_source_change_during_a_batch_stops_dispatch` | `runtime_identity.json` written once; changed code, inputs, parent ZIP or a source edited mid-batch → refused before dispatch. |
| `ops/test_ops_recovery.py::test_interrupt_before_first_checkpoint_is_blocked`, `::test_terminal_zip_without_final_manifest_is_blocked` | No verified checkpoint, or a terminal ZIP without a final manifest → `blocked`, never restarted from zero. |
| `ops/test_ops_recovery.py::test_checkpoint_recovery_128_to_256_and_ancestor_milestone` | Training interrupted after checkpoint 128 → `resume_checkpoint` to 256 with the abandoned tail excluded; all checkpoint-128 operate tasks bind the interrupted attempt's checkpoint. |
| `ops/test_ops_recovery.py::test_one_interrupted_seed_retries_alone`, `::test_malformed_receipt_and_changed_output_are_listed_in_the_proposal`, `::test_replaced_bound_zip_blocks_the_consumer` | One interrupted seed retried alone with completed siblings kept; defects listed in the proposal; a replaced bound ZIP blocks its consumer. |

The scheduler and recovery tests use inert child, worker and supervisor entry
points on the fake simulator and temporary artifacts only; they pin
`batch_identity._source_root` to a private tree so concurrent source edits do
not trip the identity refusal. The native interrupted/resumed smoke is a
human-run check and is BLOCKED until executed.
