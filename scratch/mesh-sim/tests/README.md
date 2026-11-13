@page tests_coverage Test coverage

@brief Every C++ and Python test suite, what it checks, and how to run it.

[TOC]

Python tests live beside their package owners, so one `pytest` command and CI
discover them together.

## 1\. Run the tests

From `scratch/mesh-sim/`, the unit tests (no simulator needed):

```sh
make -C tests test
.venv/bin/python -m pytest scripts/rl/tests scripts/validation/tests scripts/baselines/tests -q -rs
```

The integration and real-binary checks, against a simulator rebuilt from the
current source:

```sh
MESH_SIM_BIN=/absolute/path/to/simulator make -C tests integration
MESH_SIM_BIN=/absolute/path/to/simulator .venv/bin/python -m pytest \
    scripts/rl/tests/integration/test_real_binary.py \
    scripts/baselines/tests/test_real_binary.py -q -rs
```

| Command | Runs |
|---|---|
| `make -C tests test` | Lint, then every C++ unit suite in `UNIT_DIRS` (section 2). |
| `pytest scripts/rl/tests scripts/validation/tests scripts/baselines/tests` | All Python tests (section 3). |
| `make -C tests integration` | The CLI checks in `integration/cli-integration-test.sh`. |
| `pytest .../test_real_binary.py` (both files) | The RL and baseline real-binary Python checks. |

**CI.** The smoke workflow runs the unit tests on Linux and macOS, then
rebuilds the simulator and runs the CLI and real-binary checks. CI sets
`CLANG_TIDY=`, which turns off the local lint target, so a CI unit pass does
not include lint.

## 2\. C++ unit suites

The C++ runner builds and runs these suites from `tests/unit/`:

| Suite | What it checks |
| --- | --- |
| `unit/config`, `unit/eval`, `unit/routing`, `unit/traffic`, `unit/rl`, `unit/query` | Core suites for configuration, link evaluation, routing, traffic, RL and channel query. |
| `unit/loader` | Full key/value scenarios, relative paths, optional assets, node overrides, and loader/struct defaults; catches silently changed input interpretation. |
| `unit/config-rules` | Cadence rounding and centralized random-walk layouts; separates floating-point tolerance from incompatible timing or movement bounds. |
| `unit/eval-jammer` | Deterministic loss/condition models, worked noise/gain calculations, jammer gates and power sums; keeps negative jammed SINR and zero capacity below threshold. |
| `unit/routing-extra` | Small random graphs checked by independent exhaustive path enumeration, opposite-direction contention, and worked multi-edge congestion; checks delivered-capacity invariants without using the scaling implementation as the oracle. |
| `unit/traffic-extra` | Scripted Poisson arrivals/holding times, exact expiry/arrival boundaries, and controlled statistical samples, run through the real traffic state machine. |
| `unit/io-cli` | Hand-calculated metrics, documented CSV precision/columns, archiving, seed precedence, and flag registration. Human-log whitespace is not the main check. |
| `unit/rl-bridge` | Real C++ init/step emission, slot/peer order, masks, movement/clipping, EOF, terminal windows, and scored warmup windows; tests the producer independently of the Python fake simulators. |

The suites share an evaluator stub header and follow `develop`'s centralized v2
protocol; legacy control is not restored.

## 3\. Python test files

Paths are relative to `scripts/`. RL tests are grouped by package under
`rl/tests/` (`env/`, `ops/`, `cluster/`, `experiments/`, `policy/`, and so on);
the per-package maps are linked from @ref scripts_rl_tests "the RL tests page".
The existing package conftests and the fake query, simulator and SLURM helpers
own the fixtures.

| Files | What it checks |
| --- | --- |
| `baselines/tests/test_node_records.py`, `test_preparation_boundaries.py`, `test_plan_validation_boundaries.py` | Partial mobility bounds, ground-level datum, selected versus unselected waypoint nodes, and plan feasibility at boundaries. |
| `baselines/tests/test_channel_failures.py` | Split framing, authoritative connectivity, worker death between requests, and resistant workers; transport integrity and process cleanup. |
| `baselines/tests/test_objective_boundaries.py` | Fixed worked cell areas, objective totals with all terms nonzero, core/vulnerability examples, and feasibility, using independent worked examples. |
| `baselines/tests/test_geometric_boundaries.py`, `test_optimization_boundaries.py` | Fallback feasibility, start-relative caps, best-layout retention, deterministic search, and the worker's advertised batch cap. |
| `baselines/tests/test_input_snapshots.py`, `test_ini_preservation.py` | Asset bytes, rebased references, comments/newlines, and missing sections. Semantic checks call the compiled C++ INI parser through one shared fixture. |
| `baselines/tests/test_runtime_identity.py`, `test_fingerprint_boundaries.py` | Atomic/write-once behavior and field-sensitive identity, including all dynamically linked ns-3 libraries. Dedicated planning seeds are covered by the planning-contract tests. |
| `baselines/tests/test_runner_interruption.py` | Interruption during preparation or execution, completed-seed preservation, and resistant-child cleanup. |
| `rl/tests/env/test_episode_failures.py` | Malformed/early exits, done followed by nonzero exit, recovery, escalation, and failure telemetry. `protocol_peer.py` and `scripted_peer.py` supply controlled process failures. |
| `rl/tests/env/test_decision_record_failures.py` | Recorder open/close failures do not stop inference or destroy normal episode output. The decision-record tests own the versioned formats and caps. |
| `rl/tests/env/test_observation_boundaries.py`, `test_reward_boundaries.py`, `test_selection_sources.py` | Sentinel/clipping and peer/slot ordering, numerical reward boundaries, and mixed per-key precedence. The parameter tests own configurable scales and expanded schemas. |
| `rl/tests/ops/test_measurement_boundaries.py` | Immediate sampling and descendants that outlive the leader; resource accounting. |
| `rl/tests/cluster/test_submission_failures.py`, `test_reconciliation_edges.py` | Submission intent, scheduler disagreement, exact job identity, missing evidence, and writer blockers. A cancellation request alone does not count as termination. |
| `rl/tests/ops/test_receipt_concurrency.py`, `rl/tests/cluster/test_slurm_jobs.py` | Concurrent locks/receipt allocation and running rendered jobs through hostile paths; prevents duplicate submissions and quoting failures. |
| `rl/tests/cluster/test_retrieval_safety.py` | No destructive rsync options, preservation of earlier manifests, and incomplete-transfer safety. The real-local-rsync checks own actual filtering. |
| `rl/tests/experiments/test_statistics_boundaries.py`, `rl/tests/policy/test_comparison_statistics.py` | Independent quantiles, two-sample intervals, negative differences, and across-run missing-data examples. |
| `rl/tests/policy/test_policy_lifecycle.py` | Scenario overrides cannot bypass structural or reward compatibility checks; reuses the existing bundle/environment fixtures. |

## 4\. Coverage held by existing tests

These existing tests own the valid-INI, key/mapping, ordinary CLI, training,
callback, bundle-version and normal lifecycle cases:

| Package | Tests |
|---|---|
| `scripts/baselines` | `test_config`, `test_adapter`, `test_effective_inputs`, `test_provenance`, `test_planning_contract` |
| `scripts/rl` | `test_mesh_env`, `test_policy_lifecycle`, `test_lifecycle_cli`, `test_evaluation_pipeline`, `test_policy_comparison`, `test_observations_rewards`, `test_policy_input_parameters`, `test_decision_records` |
| `scripts/rl` (ops) | `test_ops_tasks`, `test_ops_tune`, `test_cluster_recovery` and the retrieval checks own task, tuning, CLI and recovery cases. |

Regression tests for malformed seeds, hop overflow, gateway/hang, stale jammers,
the parser, non-object artifacts, action conversion and duplicate evaluation
seeds live with the corresponding production fixes.

These behaviors are not tested as compatibility promises: unsupported legacy
control, first-evaluation planning seeds, zero-floor jammed SINR, exact private
module inventories, and incidental log/sampler sequences.

## 5\. Scope and skips

The unit stubs compile real mesh-sim implementation files. They do not cover:

- ns-3 propagation behavior, real RNG seed setup or simulator scheduling;
- agreement between the binary and Python (use the real-binary checks);
- `sim.cc` orchestration (the bridge driver is a test driver);
- a real cluster (fake schedulers contact none);
- rsync's own filter engine (the rsync shim does not run it).

Skips:

- Parser compilation errors fail the test when a compiler exists; with no
  compiler the test is an explicit skip.
- Optional dependencies and private inputs can cause skips. Report skip counts
  and platform restrictions along with pass counts.
