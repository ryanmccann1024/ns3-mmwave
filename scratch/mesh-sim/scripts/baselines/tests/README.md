# Baseline input tests

Run from `scratch/mesh-sim/`:

```bash
.venv/bin/python -m pytest scripts/baselines/tests -q -rs
```

| Tests | Input and expected behavior |
| --- | --- |
| `test_config.py` baseline cases | Absent/none, both methods and all objectives, required/unknown keys, numeric values, gateway/movable IDs, paths, and inline comments: valid settings parse; malformed settings fail. |
| `test_config.py` INI structure cases | Duplicate sections/keys, colon assignments, continuations, and padded section headers: reject them. `[DEFAULT]` stays ordinary. |
| `test_padded_scenario_cannot_select_default_nodes` | Both default and custom nodes files exist: padded scenario header fails; corrected header selects the custom file. |
| `test_config.py` mapping cases | Version 1 origin, rectangular geofence, radios, and platforms: valid input resolves; missing/unknown/nonfinite fields and polygon requests fail. |
| `test_downstream_mapping_imports_remain_available` | Existing config imports resolve to the new mapping owner's class/function and platform names. |
| `test_replace_failure_preserves_destination_and_removes_temp` | Inject failed replacement with/without a destination: existing bytes survive, no new destination appears, and temporary JSON is removed. |
| `test_serialization_failure_preserves_existing_bytes` | NaN, infinity, and a nonserializable object: reject the write without changing the destination or leaving temporary JSON. |
| `test_baseline_and_rl_share_the_atomic_writer` | Both callers use the shared implementation; RL JSON remains readable with its values intact. |
| `test_baseline_imports_need_no_rl_or_planner_dependencies` | A fresh subprocess blocks third-party imports: baseline configuration, mapping, artifact, and input modules still import. |

These tests check configuration and artifact behavior. They do not run the
supplied planners, model a radio channel, or show that coverage/balanced/resilience
improve delivered demand. Adapter, runner, and algorithm checks are introduced
in the downstream reviews; simulator validation requires a separately built
binary.
