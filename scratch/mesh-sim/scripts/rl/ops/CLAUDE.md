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
- Tests use fake processes and scheduler-independent data. Never run `./ns3
  build`, `./ns3 run`, or a real simulator as part of these checks.
