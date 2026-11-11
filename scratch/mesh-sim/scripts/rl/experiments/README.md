@page scripts_rl_experiments Batch definitions
@brief Pure configuration, immutable planning and finite selection.

`scenario_timing` checks the INI cadence before budgeting decisions. Baseline
and operation gates must match the selected INI's `control_start_s`.
Replay checks preserve the source case's reference gate for scoring.
The [coordination smoke example](../../../inputs/experiments/examples/coordination-smoke/README.md)
shows how to preview a plan.

`config.load_matrix_v2` assembles validated v2 batches. `scenario_config` owns
scenario inputs, `row_config` owns row and training settings, and
`stage_config` owns selection rules and stage dependencies. `plan.build_batch_plan` builds a dependency graph
without executing it. `plan_tasks` builds commands, `plan_inputs` fingerprints
inputs, and `task_graph` owns task identities and destinations. `selection.select` reads declared selection evidence,
never held-out data. Version 1 helpers remain importable from
`policy.experiment`. Run the matrix and inventory tests under
`tests/experiments/` to exercise these library contracts.

## Result production

`reporting.py` dispatches reports from accepted artifacts. `report_curves`
reads training history, `report_comparison` pools comparable results,
`report_index` writes scenario indexes and asset copies, and
`report_selection` verifies the evidence used to rank candidates. Scenario index version 4 and online manifest version 5 preserve
explicit model/mode/seed references, source identities and missing-data states.
Readers must keep legacy branches. `tests/fixtures/batch_*_example.json` and
`tests/experiments/test_gui_index.py` define producer compatibility.
