# scripts/rl/experiments

Batch domain: matrix version 2 validation (`config.py`), the plan v3 task graph
(`plan.py`) and named selection rules (`selection.py`). Read
[README.md](README.md) and the canonical contract in
[docs/rl/batch-reference.md](../../../docs/rl/batch-reference.md) before editing.

- Pure modules: read configuration and assets, hash inputs and the binary, build
  plans. Never start a process, import `ops/`, a scheduler, a public CLI, a
  campaign or a `phase_*` module.
- Reuse existing validators (`agents/config.py`, `env/selection.py`,
  `env/config.py`, `scripts/sim_support.py`, `scripts/artifact_io.py`); do not
  copy domain rules here.
- Version 2 paths resolve against the matrix directory; version 1 keeps its
  mesh-root rules. Record resolved paths, hashes and the original reference.
- Task keys hash every `KEY_DIMENSIONS` entry (unused = null). Adding,
  removing or reordering a dimension changes every key; treat it as a plan
  version change. Detect collisions before writing anything.
- Plans are immutable: never rewrite an existing `experiment_plan.json`.
- Dispatch targets come from code (allowlisted modules/handlers), never from
  matrix JSON. No free-form commands.
- No hidden Cartesian expansion beyond the listed rows × their seeds,
  operations and checkpoints; no research defaults for schedules or online
  settings; selection never reads held-out evidence.
- Bump `EXPERIMENT_PLAN_VERSION`, `MATRIX_V2_VERSION` or
  `SELECTION_RECEIPT_VERSION` with their readers and the
  [CONTRIBUTING.md](../../../CONTRIBUTING.md) rows when fields change.
- Tests: `../tests/experiments/test_matrix_v2.py` (no simulator; fake executables are
  hashed only). Native runs are human-only.
