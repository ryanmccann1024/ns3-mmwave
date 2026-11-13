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

## 1\. Module layout

**Validation** (`load_matrix_v2` in `config.py` validates a version 2 matrix;
`resolve_execution` applies CLI > matrix > defaults):

| File | Validates or resolves |
| --- | --- |
| `config.py` | Keys, names, seed roles, kind requirements, training budgets and schedules; delegates to the owners below. |
| `scenario_config.py` | Scenarios, per-seed INIs, references and baseline settings. |
| `row_config.py` | Experiment rows, training settings and rollout budgets. |
| `model_config.py` | Saved models and checkpoint selectors. |
| `operation_config.py` | Policy operations, schedules and episode budgets. |
| `check_config.py` | Batch checks, their sources and dependents. |
| `stage_config.py` | Selection rules and dependencies between stages. |
| `matrix_fields.py` | Field helpers shared by matrix versions 1 and 2. |
| `scenario_timing.py` | Native cadence and deployment gates, checked before planning. Replay keeps the saved case's reference gate for scoring. |

**Planning** (`build_batch_plan` in `plan.py` expands the validated matrix into
plan v3: task IDs, SHA-256 keys over fixed dimensions, destinations, argument
lists, dependencies and hashed inputs):

| File | Role |
| --- | --- |
| `plan_tasks.py` | Builds task commands. |
| `plan_inputs.py` | Fingerprints inputs. |
| `task_graph.py` | Task identities and destinations. |

**Selection and reporting:**

| File | Role |
| --- | --- |
| `selection.py` | `select` applies a stage's named rule to gathered evidence and returns the selection receipt. |
| `reporting.py` | Dispatches reports to the owners below. |
| `report_artifacts.py` | Reads accepted batch attempts and resolves their artifact references. |
| `report_curves.py` | Reads training history. |
| `report_comparison.py` | Pools comparable results. |
| `report_index.py` | Writes scenario indexes and asset copies. |
| `report_selection.py` | Verifies selection evidence. |

## 2\. Callers

- `../experiment.py` parses the commands and calls these owners; `../ops/local.py`
  and `../ops/recovery.py` consume the written plan.
- `../policy/experiment.py` owns matrix version 1 and plan v2, reusing
  `matrix_fields.py`.

## 3\. Tests

`../tests/experiments/test_matrix_v2.py`; behavior map in
[Policy comparison tests](@ref src_rl_policy_comparison_tests). Saved-file
versions are listed in [Contributing](@ref Contributing).
