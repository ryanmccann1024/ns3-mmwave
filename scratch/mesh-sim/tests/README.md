# Baseline test map

This maps the checks introduced to protect the single-node RL bridge and
pre-change simulator results. Later centralized-control and evaluation tests
live in the same Python test directory but are not listed here. For commands,
see the [project verification guide](../README.md#verify) and [regression-suite
guide](../scripts/validation/README.md#regression-suite). Unit/Python tests use
temporary directories and assert pass/fail; they do not save reference data.

## Configuration unit tests

The following checks are in [`config-validator-test.cc`](unit/config/config-validator-test.cc).
They use an in-memory config or a temporary `run.ini`/`nodes.json`. Output is
pass/fail assertions; the temporary scenario is removed.

| Test | Purpose | Expected input → output |
| --- | --- | --- |
| `test_band_default` | Omitted radio band | No `band` key → `mmwave`, source `default`. |
| `test_band_from_ini` | INI radio band | `band = sub-6` → `sub-6`, source `run.ini`. |
| `test_band_invalid_rejected` | Band validation | `lte` → error naming `mmwave` and `sub-6`. |
| `test_reward_alias_normalized` | Old reward spelling | `mean_sinr` → `all_links_los`, alias retained. |
| `test_reward_canonical_unchanged` | Canonical reward spelling | `all_links_los` → unchanged, no alias. |
| `test_reward_unknown_rejected` | Reward validation | `bogus` → `rl.reward_type` error. |
| `test_reward_legacy_name_not_valid` | Loader/validator boundary | Unnormalized `mean_sinr` config → validation error. |
| `test_rl_inverted_z_bounds` | Height bounds | `z_min > z_max` → bounds error. |
| `test_rl_valid_z_bounds` | Height bounds | `z_min < z_max` → no height-bounds error. |

`make test` also runs the existing eval, routing, and traffic unit suites;
those test their own algorithms, not the new RL output layout. See
[`tests/Makefile`](Makefile) for the suite list.

## Real-binary CLI integration

[`cli-integration-test.sh`](integration/cli-integration-test.sh) needs a built
simulator binary. It uses the two small smoke scenarios and deletes its
temporary output directory afterward. Its lasting output is nine console
`PASS`/`FAIL` lines and a final count.

| Test | Purpose | Expected input → output |
| --- | --- | --- |
| 1: help | CLI discovery | `--PrintHelp` → success and `run-config` in help. |
| 2: missing config | Required argument | No `--run-config` → nonzero exit. |
| 3: missing file | Path validation | Nonexistent `run.ini` → nonzero exit. |
| 4: bad seed | Seed parsing | `--seeds=abc` → `invalid seed value` error. |
| 5: missing positions override | Path validation | Nonexistent JSON path → named missing-file error. |
| 6: valid run | Basic output contract | Single-node smoke → `run.log`, `seed-1/summary.json`, `links.csv`. |
| 7: CLI band override | Precedence | `--band=sub-6` → `run.log` records band and `band_source=cli`. |
| 8: jammer across bands | Interference switch | Same jammer input under `sub-6`/`mmwave` → matching link rows, at least one different SINR; jammer-path flag true/false. |
| 9: legacy RL stream | Protocol compatibility | Single-node smoke with closed stdin → five `step` lines, no `init`. |

## Python RL contract tests

[`test_mesh_env.py`](../scripts/rl/tests/test_mesh_env.py) drives
[`fake_sim.py`](../scripts/rl/tests/fake_sim.py), not the real radio simulator.
Inputs are temporary INI/JSON files and a fake executable; outputs are
assertions on returned values and temporary episode files. These checks do
**not** prove movement, propagation, or jammer physics.

| Test | Purpose | Expected input → output |
| --- | --- | --- |
| `test_two_resets_allocate_distinct_episodes` | Episode allocation | Two resets → `episode-0000/`, `episode-0001/`; same seed, interrupted status. |
| `test_done_episode_is_completed` | Episode lifecycle | Four stay actions → completed manifest with four steps. |
| `test_reset_seed_override_persists` | Seed persistence | Reset with seed 7 → later episode also seed 7, source `gym`. |
| `test_reset_with_resolved_seed_keeps_source` | Seed provenance | Reset with the INI's seed → source remains `run.ini`. |
| `test_missing_seed_is_rejected` | Required seed | No seed in INI/constructor → `ValueError`. |
| `test_seed_and_bounds_strip_inline_comments` | INI parsing | `#`/`;` comments → numeric seed and bounds read correctly. |
| `test_premature_exit_reports_code_and_stderr` | Child failure | Fake exit 3 → exception includes exit code and stderr. |
| `test_malformed_output_reports_line_and_text` | Protocol failure | Bad JSON line → exception names line and offending text. |
| `test_band_flag_forwarding` | Band forwarding | Band specified/omitted → simulator command includes/omits `--band`. |
| `test_bound_defaults_match_cpp_and_mask_z` | Default bounds/mask | No bounds in INI → C++ defaults; downward action masked at `z_min`. |
| `test_gym_registration_resolves` | Gymnasium registration | `gymnasium.make` → `MeshRlEnv` instance. |
| `test_cli_help` | Training CLI shape | Top-level/subcommand help → expected flags, exit 0. |
| `test_tiny_training_run` | Small end-to-end Python train | Fake sim, 16 steps → completed `train_manifest.json`, saved model, episode manifests; skips without `sb3_contrib`. |

[`test_bootstrap_venv.py`](../scripts/rl/tests/test_bootstrap_venv.py) adds two
dependency checks:

| Test | Purpose | Expected input → output |
| --- | --- | --- |
| `test_direct_pins_match_probe_dependencies` | Dependency coverage | `requirements.txt` → every direct dependency has a pin. |
| `test_version_probe_rejects_mismatch` | Version check | Deliberately wrong pytest version → probe exits 1 with mismatch message. |

## Regression checks

[`test_regression_check.py`](../scripts/validation/tests/test_regression_check.py)
tests the comparison/launcher code without a real simulator:

| Test | Purpose | Expected input → output |
| --- | --- | --- |
| `test_positions_header_and_coordinates` | Position comparison | CSV with/without metadata → x/y/z parsed; changing each axis produces one difference. |
| `test_no_header_is_empty` | Empty CSV handling | Empty or metadata-only CSV → empty table. |
| `test_unattended_launchers_close_stdin_and_clean_loader_paths` | Launcher safety | Mocked sweep/batch/capture → closed stdin and no empty library-path entries. |
| `test_missing_reference_explains_cloud_bundle` | Missing-data message | Absent reference snapshot → instruction to request approved bundle. |

The real-binary [regression suite](../scripts/validation/README.md#regression-suite)
uses [`manifest.json`](fixtures/regression/p0/manifest.json), seed 1, and
approved external reference snapshots. Each case writes a normalized capture
and `comparison.json` under its named output directory; `suite-report.json`
records `PASS`, `FAIL`, or `SKIP` for all cases.

| Case | Input | Expected check |
| --- | --- | --- |
| Static LOS | Baseline scenario 01, `mmwave` | Link and metric results match the static reference. |
| Building blockage | Baseline scenario 03, `mmwave` | Blocked-link and position results match the reference. |
| Three-node relay | Baseline scenario 07, `mmwave` | Relay topology and routing results match the reference. |
| Sherpa Spring Lake | Local Sherpa scenario, `mmwave` | Match if data installed; otherwise `SKIP` (optional). |
| CalFEX field scenario | CalFEX 1509–1513, `sub-6` | Field-derived run matches the reference. |
| Synthetic jammer | Jammer smoke scenario, `sub-6` | Jammed link/metric results match the reference. |

Without cloud references, [`smoke_check.py`](../scripts/validation/smoke_check.py)
runs the jammer scenario twice with the same seed. It checks finite metrics,
stationary positions, link rows, and identical normalized results. It writes
`run-1/` and `run-2/` beneath the requested `--out` directory and prints
`PASS` or `FAIL`; it does not establish agreement with the historical reference.

## Centralized RL and policy-input tests

These checks cover the centralized action contract and the configurable
observations, rewards, and telemetry described in the
[policy-input guide](../src/rl/policy-inputs.md). The Python-only tests use
`fake_sim.py` and temporary directories; they do not validate radio physics.
`test_real_binary.py` runs the bundled `centralized-multi-smoke` scenario in
pytest's temporary directory and skips unless `MESH_SIM_BIN` points to a built
simulator. No reference snapshots are created or changed by these tests.

| Test file and checks | Input → expected output |
| --- | --- |
| `test_mesh_env.py`: `test_centralized_spaces_contract_and_padding`, `test_centralized_single_slot_spaces` | Fake `init` with two active/one padded position or one position → fixed action/observation shapes, zero padding, hold-only padded mask. |
| `test_mesh_env.py`: `test_centralized_joint_action_is_forwarded`, `test_centralized_rejects_a_scalar_action`, `test_centralized_masked_random_run_completes` | Joint action/masked samples → expected movement and completed manifest; scalar or wrong-length action → error. |
| `test_mesh_env.py`: `test_centralized_faults_are_rejected`, `test_reset_signature_drift_fails_before_replacing_spaces`, `test_reset_mode_drift_is_rejected` | Malformed or changed simulator contract → failed episode/error, without silently changing established Gymnasium spaces. |
| `test_mesh_env.py`: `test_long_stdout_is_drained_on_close`, `test_close_is_idempotent_and_reset_still_works`, `test_completed_episode_leaves_no_process_or_reader` | Long/finished fake run or repeated close → child and reader thread cleaned up, correct episode status. |
| `test_real_binary.py`: `test_live_spaces_and_metadata`, `test_scripted_positions_and_masks`, `test_repeated_resets_are_deterministic` | Real three-node fixture and scripted actions → contract fields, clipped positions/masks, identical repeated trajectories. |
| `test_real_binary.py`: `test_structural_malformed_actions_hold_everything`, `test_malformed_action_stops_a_moving_node`, `test_semantic_errors_only_affect_invalid_slots` | Bad joint actions → all hold for a malformed list, or only invalid positions hold and appear in `revalidated_slots`. |
| `test_real_binary.py`: `test_partial_windows_clipping_and_reward_mean` | Coarse versus one-tick decisions → matching shared positions and mean reward over each full/partial window. |
| `test_observations_rewards.py`: `test_local_links_v1_exact_slot_vector`, `test_local_links_v1_padded_slot_is_zero`, `test_local_links_v1_clips_extreme_links`, `test_raw_links_matches_cpp_layout` | Raw facts → exact preset values, bounded local features, zero padding, unchanged raw layout. |
| `test_observations_rewards.py`: `test_schema_hash_is_deterministic_and_strict_json`, `test_raw_links_schema_uses_null_bounds_but_infinite_box`, `test_check_schema_rejects_structural_change`, `test_check_schema_reports_identity_change_as_warning` | Saved/live schemas → stable fingerprint, correct Box bounds, structural rejection and identity warnings. |
| `test_observations_rewards.py`: `test_delivery_ratio_masks_zero_demand`, `test_other_components`, `test_composer_total_is_weighted_sum_over_valid_components`, `test_legacy_component_reproduces_cpp_reward`, `test_composer_rejects_bad_configuration`, `test_reward_schema_authorities` | Synthetic window sums/configuration → component formulas, validity, weighted total, C++ alias, schema authority, and errors for invalid weights/names. |
| `test_observations_rewards.py`: `test_resolve_selection_precedence`, `test_resolve_selection_rejects_invalid_keys`, `test_resolve_selection_rejects_p2_selection_in_legacy_mode` | CLI/INI/default choices → recorded precedence or a pre-launch validation error. |
| `test_observations_rewards.py`: `test_telemetry_records_replay_without_mismatch`, `test_should_save_sampling` | Synthetic steps → header and sampled records; replay reports zero observation/reward mismatches. |
| `test_mesh_env.py`: `test_custom_preset_and_reward_block`, `test_negative_legacy_reward_window`, `test_zero_demand_masks_delivery_ratio` | Fake decisions → local observation shape, inspectable reward parts, preserved negative reward, zero-demand validity flag. |
| `test_mesh_env.py`: `test_telemetry_file_only_when_selected`, `test_telemetry_default_cadence_replays`, `test_telemetry_stride_keeps_full_manifest_totals`, `test_default_selection_telemetry_replays_via_raw_links` | Telemetry off/on/strided → optional `steps.jsonl`, successful replay, complete manifest totals even for unsaved decisions. |
| `test_mesh_env.py`: `test_binary_without_facts_is_rejected`, `test_training_records_selection_and_schema_hashes` | Old fake protocol or tiny training run → clear missing-facts failure or matching saved selection/schema fingerprints; training check skips without `sb3_contrib`. |
| `test_real_binary.py`: `test_facts_rows_window_and_raw_links_rebuild`, `test_window_sums_match_the_run_summary` | Real simulator facts → correct row/window sizes, C++ reward mean, rebuilt raw observation, summary totals. |
| `test_real_binary.py`: `test_custom_selection_observations_rewards_and_replay`, `test_telemetry_is_reproducible_and_cadence_bounded`, `test_training_run_writes_matching_schema_hashes` | Real run with custom selection → finite policy inputs, saved reward/trace replay, repeatable/strided telemetry, matching manifest fingerprints; training check skips without `sb3_contrib`. |


The config suite checks configurable proximity and live-coverage grid validity.
The eval suite checks coverage-cell area and largest-component union semantics.
Python `scripts/rl/tests/test_reward_matrix.py` covers validation seed cycling
and reward matrices. The real-binary coverage/building-mask case requires a
fresh user build; syntax checks and fake simulator tests do not prove RF fidelity.

`unit/rl` checks continuous joint motion safety, crossing paths, altitude, wall clipping and cascading holds without ns-3. Config validation checks opt-in initial separation, including 3D altitude.
