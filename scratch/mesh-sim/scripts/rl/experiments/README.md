@page scripts_rl_experiments scripts/rl/experiments

@brief Pure batch domain: matrix version 2 validation, the immutable plan v3 task graph, and the named selection rules.

This package turns a batch matrix into a fixed, hashed task graph. It reads
configuration, assets and saved training manifests, and hashes the simulator
binary, but it never starts a process, imports a scheduler or imports a
command-line module. Execution, receipts and recovery belong to `../ops/`;
operating one model belongs to `../policy/`.

The field catalog, path rules, task states and examples are in the
[batch experiment reference](@ref mesh_sim_rl_batch_reference); this page does
not repeat them. The worked workflow is
[Experiments and operations](@ref mesh_sim_rl_experiments).

## Module layout

| File | Role |
| --- | --- |
| `config.py` | `load_matrix_v2` validates a version 2 matrix: keys, names, seed roles, kind requirements, scenario assets and references, parent models, training budgets and schedules, native decisions per episode (`native_decisions`). `resolve_execution` applies CLI > matrix > defaults. Also holds the version 1 field helpers used by the `policy/experiment.py` facade. |
| `plan.py` | `build_batch_plan` expands the validated matrix into plan v3: task IDs, SHA-256 keys over fixed dimensions, destinations, argument lists, dependencies and hashed inputs; `check_collisions`, `check_binary_fresh`, `write_batch_plan` (write once; a different plan is refused). |
| `selection.py` | `select` applies a stage's named rule to gathered evidence and returns the selection receipt. |
| `reporting.py` | Curves, reviews, comparison views, the scenario index, reward summaries and selection evidence (`selection_evidence`). |

## Callers

- `../experiment.py` parses the commands and calls these owners; `../ops/local.py`
  and `../ops/recovery.py`
  consume the written plan.
- `../policy/experiment.py` re-exports the version 1 helpers under their
  existing names.

## Tests

`../tests/experiments/test_matrix_v2.py`; behavior map in
[Policy comparison tests](@ref src_rl_policy_comparison_tests). Saved-file
versions are listed in [Contributing](@ref Contributing).
