# mesh-sim test coverage

Run from `scratch/mesh-sim/`:

```sh
make -C tests test
.venv/bin/python -m pytest scripts/rl/tests scripts/validation/tests scripts/baselines/tests -q -rs
```

Python tests live beside their package owners, so the documented command and
CI discover them together. The C++ runner retains the existing config, eval,
routing, traffic, RL, and query suites and includes the additional suites below.
The smoke workflow runs these unit tests on Linux and macOS before rebuilding
the simulator and executing its existing CLI and real-binary checks.
`CLANG_TIDY=` in CI disables the separate local lint convenience target; a unit
pass is not a lint result.

## Additional standalone C++ checks

| Suite | Inputs and expected protection |
| --- | --- |
| `unit/loader` | Full key/value scenarios, relative paths, optional assets, node overrides, and loader/struct defaults; catch silently changed input interpretation. |
| `unit/config-rules` | Cadence rounding and centralized random-walk layouts; distinguish floating-point tolerance from genuinely incompatible timing or movement bounds. |
| `unit/eval-jammer` | Deterministic loss/condition models, worked noise/gain calculations, jammer gates and power sums; preserve negative jammed SINR and zero capacity below threshold. |
| `unit/routing-extra` | Small random graphs checked by independent exhaustive path enumeration, opposite-direction contention, and worked multi-edge congestion; retain delivered-capacity invariants instead of copying the scaling implementation as the oracle. |
| `unit/traffic-extra` | Scripted Poisson arrivals/holding times, exact expiry/arrival boundaries, and controlled statistical samples; check the real traffic state machine. |
| `unit/io-cli` | Hand-calculated metrics, documented CSV precision/columns, archiving, seed precedence, and flag registration. Human-log whitespace is not the principal oracle. |
| `unit/rl-bridge` | Real C++ init/step emission, slot/peer order, masks, movement/clipping, EOF, terminal windows, and scored warmup windows; protect the producer independently of Python fake simulators. |

The evaluator stub header is shared with the focused reconfiguration regression
in the separate fixes PR. Both branches add the same header contents; neither
needs the other's production changes to compile. The additional suites preserve
`develop`'s centralized v2 protocol rather than restoring legacy control.

## Additional Python checks

Paths below are relative to `scripts/`. Existing package conftests and fake
query/simulator/SLURM helpers remain the fixture owners.

| Files | Inputs and expected protection |
| --- | --- |
| `baselines/tests/test_node_records.py`, `test_preparation_boundaries.py`, `test_plan_validation_boundaries.py` | Partial mobility bounds, ground-level datum, selected versus unselected waypoint nodes, and plan feasibility at boundaries. |
| `baselines/tests/test_channel_failures.py` | Split framing, authoritative connectivity, worker death between requests, and resistant workers; preserve transport integrity and process cleanup. |
| `baselines/tests/test_objective_boundaries.py` | Fixed worked cell areas, objective totals with all terms nonzero, core/vulnerability examples, and feasibility; protect scientific scoring with independent examples. |
| `baselines/tests/test_geometric_boundaries.py`, `test_optimization_boundaries.py` | Fallback feasibility, start-relative caps, best-layout retention, deterministic search, and respecting the worker's advertised batch cap. |
| `baselines/tests/test_input_snapshots.py`, `test_ini_preservation.py` | Asset bytes, rebased references, comments/newlines, and missing sections. Semantic checks call the actual compiled C++ INI parser through one shared fixture, rather than a Python copy of it. |
| `baselines/tests/test_runtime_identity.py`, `test_fingerprint_boundaries.py` | Atomic/write-once behavior and field-sensitive identity, including all dynamically linked ns-3 libraries. Dedicated planning seeds remain owned by existing planning-contract tests. |
| `baselines/tests/test_runner_interruption.py` | Interruption during preparation or execution, completed-seed preservation, and resistant-child cleanup. |
| `rl/tests/test_episode_failures.py` | Malformed/early exits, done followed by nonzero exit, recovery, escalation, and failure telemetry. `protocol_peer.py` and `scripted_peer.py` supply controlled process failures. |
| `rl/tests/test_decision_record_failures.py` | Recorder open/close failures cannot stop inference or destroy normal episode evidence. Existing decision-record tests own the versioned formats and caps. |
| `rl/tests/test_observation_boundaries.py`, `test_reward_boundaries.py`, `test_selection_sources.py` | Sentinel/clipping and peer/slot ordering, numerical reward boundaries, and mixed per-key precedence. Existing parameter tests own configurable scales and expanded schemas. |
| `rl/tests/test_measurement_boundaries.py` | Immediate sampling and descendants surviving the leader; protect resource accounting. |
| `rl/tests/test_submission_failures.py`, `test_reconciliation_edges.py` | Submission intent, scheduler disagreement, exact job identity, missing evidence, and writer blockers. A cancellation request alone never proves termination. |
| `rl/tests/test_receipt_concurrency.py`, `test_slurm_jobs.py` | Concurrent locks/receipt allocation and executing rendered jobs through hostile paths; prevent duplicate submissions and quoting failures. |
| `rl/tests/test_retrieval_safety.py` | No destructive rsync options, preservation of earlier manifests, and incomplete-transfer safety. Existing real-local-rsync checks own actual filtering. |
| `rl/tests/test_statistics_boundaries.py`, `test_comparison_statistics.py` | Independent quantiles, two-sample intervals, negative differences, and across-run missing-data examples. |
| `rl/tests/test_policy_lifecycle.py` | Scenario overrides cannot bypass structural or reward compatibility checks; reuse the existing bundle/environment fixtures. |

## Coverage consolidated into existing owners

The original PR's duplicate valid-INI, key/mapping, ordinary CLI, training,
callback, bundle-version, and normal lifecycle matrices are not copied as a
second hierarchy. Relevant protection already lives in baseline `test_config`,
`test_adapter`, `test_effective_inputs`, `test_provenance`, and
`test_planning_contract`, and RL `test_mesh_env`, `test_policy_lifecycle`,
`test_lifecycle_cli`, `test_evaluation_pipeline`, `test_policy_comparison`,
`test_observations_rewards`, `test_policy_input_parameters`, and
`test_decision_records`.

Current `test_ops_tasks`, `test_ops_tune`, `test_cluster_recovery`, and retrieval
checks also supersede older task/tuning/CLI matrices and recovery assumptions.
Malformed-seed, hop-overflow, gateway/hang, stale-jammer, parser, non-object
artifact, action-conversion, and duplicate-evaluation-seed regressions accompany
the production fixes in the other PR. Unsupported legacy control, first-evaluation
planning seeds, zero-floor jammed SINR, exact private module inventories, and
incidental log/sampler sequences are not compatibility promises.

## Limits

These stubs compile real mesh-sim implementation files; they do not establish
ns-3 propagation behavior, real RNG seed setup, simulator scheduling, or binary
and Python agreement. The bridge driver is a test driver, not proof of `sim.cc`
orchestration. Fake schedulers do not contact a cluster, and the rsync shim does
not validate rsync's own filter engine. Parser compilation errors fail when a
compiler exists; absence of a compiler is an explicit skip.

Use a simulator rebuilt from the integrated source for the separate checks:

```sh
MESH_SIM_BIN=/absolute/path/to/simulator make -C tests integration
MESH_SIM_BIN=/absolute/path/to/simulator .venv/bin/python -m pytest scripts/rl/tests/test_real_binary.py scripts/baselines/tests/test_real_binary.py -q -rs
```

Optional dependencies and private inputs can cause skips. Report skips and
platform restrictions alongside pass counts rather than equating a unit pass
with complete simulator validation.
