# Operations test map

Run from `scratch/mesh-sim/`:

```bash
.venv/bin/python -m pytest scripts/rl/tests/test_ops_tasks.py scripts/rl/tests/test_ops_benchmark.py scripts/rl/tests/test_ops_tune.py scripts/rl/tests/test_ops_process.py scripts/rl/tests/test_ops_cluster.py scripts/rl/tests/test_cluster_recovery.py -q -rs
```

| Test group | Input and expected behavior |
| --- | --- |
| `test_ops_tasks.py` | Planned task mapping, pending/done/partial steps, exit tolerance, compare prerequisites and records: only eligible steps execute; raw exits and skipped work are preserved. |
| `test_ops_benchmark.py` measurement | Stub process/ps data and manifests: timing, peak tree memory, step completion and version 2 records are saved; dirty steps/existing records are refused. |
| `test_benchmark_failure_stops_and_reaps_process_group` | Ordinary wait or sampler startup failure after spawning a fake Python child: process group is stopped and parent reaped. |
| `test_ops_process.py` | SIGINT/SIGTERM during a fake parent/descendant run: both stop, parent is reaped, prior handlers restore. No simulator or `ps` query is used. |
| `test_estimate_rejects_failed_or_incomplete_measurements` | Failed train, failed/partial evaluation and old schema despite present timing rates: estimate is refused. |
| `test_estimate_uses_configured_evaluation_cadence` | Target and measured evaluation episode counts match at 3: estimation accepts the configured cadence. |
| Existing estimate tests | Known seconds, timestep rounding, memory peaks, changed scenario/cadence/selection: arithmetic is correct, incompatible rows are excluded and changed selection is labeled. |
| `test_ops_tune.py` configuration | Unknown trainer/settings, invalid distributions, seeds, nonfinite bounds, cadence and missing dependencies: refuse before training; trial commands preserve fixed budgets and seed roles. |
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
| `test_ops_cluster.py` | Fake sbatch/squeue/sacct/scancel: closed config, argv/scripts, task states, submissions, assertions, cancellation and comparison exits. No real scheduler jobs or simulator run. |
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
