@page scripts_baselines_tests scripts/baselines/tests

@brief What each placement-baseline test file checks, and how to run them.

Run the local suite from `scratch/mesh-sim/`:

```bash
.venv/bin/python -m pytest scripts/baselines/tests -q -rs
```

These tests use fake workers (`fake_query.py`, `fake_child.py`) and temporary
directories; no real simulator starts. `test_real_binary.py` runs only when
`MESH_SIM_BIN` points to a built binary, and otherwise skips with `BLOCKED:`.
Those skips are missing evidence, not passes. To run only the local suite while
`MESH_SIM_BIN` is set, add `--ignore scripts/baselines/tests/test_real_binary.py`.

The suite checks configuration, planners on synthetic inputs, artifacts and
process behavior. It does not show that the `coverage`, `balanced` or
`resilience` objectives improve simulator-delivered demand.

## 1\. Configuration and inputs

| File | What it checks |
| --- | --- |
| `test_config.py` | Strict `[baseline]` and mapping-file parsing: methods, objectives, numeric bounds, movable IDs, removed keys, duplicate sections/keys, colon assignments, continuations, padded headers, and `[DEFAULT]` staying ordinary. |
| `test_node_records.py` | `nodes.json` loading: node-type defaults, random-walk bounds, datum from ground level or the first waypoint. |
| `test_simulator_defaults.py` | Python planning fallbacks versus the actual ns-3-free C++ input loader, including partial overrides. No ns-3 simulation. |
| `test_effective_inputs.py` | Effective INI edits, staging, `nodes.json` rewrite, asset rebasing, waypoint reject/translate and source snapshots. |
| `test_ini_preservation.py` | Byte-level line preservation when editing the effective INI. |
| `test_input_snapshots.py` | Snapshots, staging, asset rebasing and waypoint translation through `prepare()`. |
| `test_artifact_io.py` | Atomic JSON writes keep existing bytes on failure, baselines and RL share the writer, and baseline modules import without RL or planner dependencies. |

## 2\. Planners and the shared objective

| File | What it checks |
| --- | --- |
| `test_objective.py` | Pure objective helpers (movement cost, vulnerability, grid, components) and the request builders the strategy tests share. |
| `test_objective_boundaries.py` | Exact objective arithmetic on hand-built link tables, grid geometry and edge cases. |
| `test_geometric.py` | The greedy peer-anchor planner against the fake distance channel. |
| `test_geometric_boundaries.py` | Greedy-planner edges: acceptance threshold, anchor filter precedence, need fallback, worker batching. |
| `test_optimization.py` | The annealing planner: proposal rules and keep-best runs. |
| `test_optimization_boundaries.py` | Annealing edges: schedules, keep-best, seed choice, determinism, iteration bounds. |
| `test_engine_settings.py` | Parameter validation and precedence, score composition and extension, settings hashes, bounded cache and batches, serial timeouts, warm-start provenance and early gateway rejection. |

## 3\. Channel query client

| File | What it checks |
| --- | --- |
| `test_channel.py` | `ChannelScorer` against `fake_query.py`: handshake, batching and byte limits, probes, timeouts and worker faults. |
| `test_channel_failures.py` | Client edge cases with custom workers: bad init lines, silent or dying workers, split responses, shutdown escalation. |

Query process unit tests are in `tests/unit/query`.

## 4\. Preparation and plan validation

| File | What it checks |
| --- | --- |
| `test_adapter.py` | Node records, platform mapping and control order, ownership, penalties, result validation and the `prepare()` lifecycle. |
| `test_plan_validation_boundaries.py` | Boundary-exact plan validation: rectangle edges, movement caps, RL and random-walk bounds. Invalid plans fail without clamping. |
| `test_preparation_boundaries.py` | `prepare()` argument handling, seed and identity recording, ownership and region gates. |
| `test_planning_contract.py` | Planning identity through a fake worker: evaluation order does not change the plan, explicit overlap, a required planning seed, and refusing the active gateway even with `all`. |
| `test_fingerprint_boundaries.py` | Plan fingerprints cover every planning input and ignore timing and paths. |

## 5\. Runner, processes and provenance

| File | What it checks |
| --- | --- |
| `test_runner.py` | Standalone runner lifecycle against `fake_child.py`: argv, environment, seeds, manifest status sequence, failures and terminate/kill/reap. |
| `test_runner_interruption.py` | SIGINT/SIGTERM: exit `128+signal`, an `interrupted` manifest and no leftover processes or staging. |
| `test_provenance.py` | The nine pinned `third_party/arpo_placement` hashes, adapted-code and channel-runtime identity, and Mach-O library resolution. |
| `test_runtime_identity.py` | Runtime provenance hashes every linked ns-3 library. |
| `test_real_binary.py` | Real-binary checks (guard, runner, evaluation, channel query parity). Needs `MESH_SIM_BIN`. |

## 6\. Placement tests in other packages

| File | What it checks |
| --- | --- |
| `scripts/rl/tests/policy/test_evaluation_pipeline.py` | Plans become initial positions; preparation failure starts no episode; placement metadata survives failed evaluations. |
| `scripts/rl/tests/experiments/test_experiment_matrix.py` | Every supported placement policy is accepted and unknown names fail before a plan is published. |
| `scripts/rl/tests/policy/test_policy_comparison.py` | Equal plan fingerprints group; differing fingerprints are refused. |
| `scripts/rl/tests/integration/test_real_binary.py` | Includes `test_active_gateway_cannot_be_controlled` (RL control of the active gateway). Needs `MESH_SIM_BIN`. |
