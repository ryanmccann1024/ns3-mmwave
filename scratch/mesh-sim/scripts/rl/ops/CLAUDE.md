# Experiment operations

Read [README.md](README.md) and [the test map](../tests/ops-tests.md).

- CLI entry points parse and delegate. `tasks.py` owns task state/mapping;
  `task_execution.py` owns workflow records; `measurement.py` owns measurement;
  `estimation.py` owns scaling; `process.py` owns launched child groups.
- Import matrix validation/planning from `policy/experiment.py`. Reuse
  `scripts/artifact_io.py`; retain useful schema/input provenance.
- Put tuning in `../tuning/`, with an explicit trainer adapter. Do not put
  algorithm validation, study persistence or search in an operations CLI.
- Stop/reap child groups after interruptions and ordinary errors. Estimates
  require successful, complete measurements; label missing memory evidence.
- Never overwrite step directories or silently resume training checkpoints.
  Keep task resume, study resume and training resume separate.
- Preserve exit tolerance and compare prerequisite rules used by cluster jobs.
  Cluster workflows live in `../cluster/`; read its guide before scheduler edits.
  Keep ownership, intent recovery and writer locking out of the CLI.
- Batch execution (matrix version 2, plan v3) has one local owner:
  `local.py` (queue, root lock, optional shared slot pool, progress,
  `campaign_status.json`, receipts written only by the scheduler) and
  `recovery.py` (identity checks, attempt selection, checkpoint recovery
  proposals under `state/recovery/`). Contract in
  `docs/rl/batch-reference.md`; implemented and covered by worker-run synthetic
  tests (`test_ops_local.py`, `test_ops_recovery.py`), not by a native batch. Reuse
  `process.py` and `measurement.py`; do not add a second process engine.
- Version 3 receipts are validated against each task's own artifacts, never
  inferred from directory existence. Attempts are append-only; never rewrite an
  interrupted or accepted attempt, a plan, or a binding. Identity changes are
  refused, not warned.
- Legacy pair mode (`tasks.py`, `task_execution.py`, `run_task.py`) and its
  cluster callers keep working for plan v2. Version 3 steps run only from an
  allowlisted dispatch table, never an arbitrary module from JSON.
- Tests use fake processes and scheduler-independent data. Never run `./ns3
  build`, `./ns3 run`, or a real simulator as part of these checks.
