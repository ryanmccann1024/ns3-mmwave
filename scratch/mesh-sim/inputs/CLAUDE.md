# inputs/

## Scope
Scenario definitions only. Each baseline scenario is a directory under `baselines/` containing configuration files that drive a simulation run.
`experiments/` holds named RL experiment matrices, each row an explicit observation, action, and reward selection over one scenario, and the tuning study specs that search one row of such a matrix.

## Per-scenario files
- **run.ini** -- Simulation parameters (channel, traffic, routing, mesh, output settings)
- **nodes.json** -- Node positions, roles, and mobility models
- **buildings.json** -- (optional) Building geometry for urban/obstruction scenarios

## Rules
- No output data here -- outputs go to `outputs/`.
- Node IDs must be unique within a scenario.
- All nodes have `role: "peer"` (no eNB/UE distinction in mesh-sim).
