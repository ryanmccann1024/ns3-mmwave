@page scripts_rl_experiments Batch definitions
@brief Pure configuration, immutable planning and finite selection.

`config.load_matrix_v2` validates explicit rows, seed roles, PPO budgets,
checkpoints and operations. `plan.build_batch_plan` builds a dependency graph
without executing it. `selection.select` reads declared selection evidence,
never held-out data. Version 1 helpers remain importable from
`policy.experiment`. Run the matrix and inventory tests under
`tests/experiments/` to exercise these library contracts.

## Result production

`reporting.py` derives curves, mission reviews and comparisons from accepted
artifacts. Scenario index version 4 and online manifest version 5 preserve
explicit model/mode/seed references, source identities and missing-data states.
Readers must keep legacy branches. `tests/fixtures/batch_*_example.json` and
`tests/experiments/test_gui_index.py` define producer compatibility.

