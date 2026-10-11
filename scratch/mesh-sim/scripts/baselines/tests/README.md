# Baseline tests

Run from `scratch/mesh-sim/`:

```bash
.venv/bin/python -m pytest scripts/baselines/tests -q -rs
```

| Tests | Input and expected behavior |
| --- | --- |
| `test_config.py` baseline cases | Absent/none, both methods and all objectives, required/unknown keys, numeric values, movable IDs, paths, and inline comments: valid settings parse; malformed settings fail. |
| `test_config.py` INI structure cases | Duplicate sections/keys, colon assignments, continuations, and padded section headers: reject them. `[DEFAULT]` stays ordinary. |
| `test_padded_scenario_cannot_select_default_nodes` | Both default and custom nodes files exist: padded scenario header fails; corrected header selects the custom file. |
| `test_config.py` mapping cases | Version 2 rectangular geofence and platforms: valid input resolves; missing/unknown/nonfinite fields and polygon requests fail. |
| `test_replace_failure_preserves_destination_and_removes_temp` | Inject failed replacement with/without a destination: existing bytes survive, no new destination appears, and temporary JSON is removed. |
| `test_serialization_failure_preserves_existing_bytes` | NaN, infinity, and a nonserializable object: reject the write without changing the destination or leaving temporary JSON. |
| `test_baseline_and_rl_share_the_atomic_writer` | Both callers use the shared implementation; RL JSON remains readable with its values intact. |
| `test_baseline_imports_need_no_rl_or_planner_dependencies` | A fresh subprocess blocks third-party imports: baseline configuration, mapping, artifact, and input modules still import. |
| `test_adapter.py` node/result cases | Platform mapping, roster/control order, datum, IDs, finite x/y/z, unchanged altitude, movement caps and bounds: valid plans publish; invalid plans fail without clamping. |
| `test_active_traffic_gateway_cannot_be_rl_controlled` / `test_active_traffic_gateway_cannot_be_selected_for_standalone_placement` / `test_gateway_topology_accepts_the_other_nodes` | Gateway topology rejects explicit/all gateway control and gateway selection; other selected nodes remain valid. |
| `test_adapter.py` preparation cases | Stub planning, argument/ownership errors, failed planner, stable/sensitive fingerprints and manifest transitions: preparation records the outcome and writes effective inputs only for valid plans. |
| `test_effective_inputs.py` | Byte-preserving INI edits, copied assets, relocated paths, waypoint reject/translate, unchanged unselected nodes and no-plan copies. |
| `test_provenance.py` | Nine pinned reference hashes, all adapted code/library identities, Mach-O install-name and inherited-rpath resolution, and stable/sensitive fingerprints. |
| `test_planning_contract.py` | Dedicated planning seed, evaluation order independence, refused/explicit overlap, effective engine settings and gateway refusal before launch. |
| `test_simulator_defaults.py` | Pure C++ configuration-loader harness versus Python defaults/partial overrides; no ns-3 simulation. |
| `test_runner.py` lifecycle cases | Fake child checks argv/environment, seeds, status sequence, missing summaries, nonzero exits, signal cleanup and terminate/kill/reap. No simulator is used. |
| `test_ordinary_failure_stops_and_reaps_child` | Fail the running-manifest write, ordinary wait, or all later status writes: fake child is stopped/reaped; failed evidence is saved when writable, otherwise stderr reports the recording failure. |
| `../../rl/tests/test_evaluation_pipeline.py` placement cases | Plans become initial positions; preparation failure starts no episode; failed/aborted evaluation preserves placement metadata; default policies/imports stay unchanged. |
| `../../rl/tests/test_experiment_matrix.py` placement cases | Every supported policy is accepted, unknown names fail before plan publication, existing matrix policies stay unchanged. |
| `../../rl/tests/test_policy_comparison.py` placement cases | Equal fingerprints group; differing fingerprints are refused; comparisons without placement blocks retain their normal grouping. |
| `test_real_binary.py` | Direct-binary guard, standalone execution and full placement evaluation; requires an explicitly supplied real binary. Not part of local fake-child checks. |

These checks exercise configuration, supplied planners on synthetic inputs,
artifacts and process behavior. They do not show that coverage/balanced/resilience
improve simulator-delivered demand. Real-binary tests skip with `BLOCKED:` when
`MESH_SIM_BIN` is unset; those skips are missing evidence, not passes. Exclude
`test_real_binary.py` explicitly when running only the local suite.

`test_engine_settings.py` covers owned parameter validation/precedence, score
composition and extension, settings hashes, bounded cache/batches, serial
timeouts, current-only warm-start provenance and early gateway rejection.
It launches only `fake_query.py`. Query process units live in
`tests/unit/query`; real simulator parity/timing remain separate.
