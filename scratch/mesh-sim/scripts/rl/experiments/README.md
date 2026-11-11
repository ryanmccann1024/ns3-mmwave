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
| `config.py` | `load_matrix_v2` validates a version 2 matrix: keys, names, seed roles, kind requirements, scenario assets and references, parent models, training budgets and schedules. `scenario_config.py`, `row_config.py` and `stage_config.py` own the corresponding validation rules. `matrix_fields.py` supplies shared version 1 and 2 field helpers. `resolve_execution` applies CLI > matrix > defaults. |
| `plan.py` | `build_batch_plan` expands the validated matrix into plan v3: task IDs, SHA-256 keys over fixed dimensions, destinations, argument lists, dependencies and hashed inputs. `plan_tasks.py` builds commands, `plan_inputs.py` fingerprints inputs, and `task_graph.py` owns task identities and destinations. |
| `selection.py` | `select` applies a stage's named rule to gathered evidence and returns the selection receipt. |
| `reporting.py` | Dispatches reports. `report_curves.py` reads training history, `report_comparison.py` pools comparable results, `report_index.py` writes scenario indexes and asset copies, and `report_selection.py` verifies selection evidence. |

`scenario_timing.py` checks native cadence and deployment gates before
planning. Replay preserves the saved case's reference gate for scoring.

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
