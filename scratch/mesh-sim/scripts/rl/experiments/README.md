@page scripts_rl_experiments Batch definitions
@brief Pure configuration, immutable planning and finite selection.

`scenario_timing` checks the INI cadence before budgeting decisions. Baseline
and operation gates must match the selected INI's `control_start_s`.
Replay checks preserve the source case's reference gate for scoring.
The [coordination smoke example](../../../inputs/experiments/examples/coordination-smoke/README.md)
shows how to preview a plan.

`config.load_matrix_v2` validates explicit rows, seed roles, PPO budgets,
checkpoints and operations. `plan.build_batch_plan` builds a dependency graph
without executing it. `selection.select` reads declared selection evidence,
never held-out data. Version 1 helpers remain importable from
`policy.experiment`. Run the matrix and inventory tests under
`tests/experiments/` to exercise these library contracts.
