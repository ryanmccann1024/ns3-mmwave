# P0 Trustworthy Baseline Implementation Plan

Phase: P0 — make the existing simulator and rough RL path trustworthy before expanding the environment

Status: human-approved implementation and R1 repairs complete; human H1 and fresh review/testing remain

Source of truth: `docs/rl-program/p0-baseline/baseline-scout-report.md`

## Approved R1 repair amendment (2026-09-15)

The human approved fixing B2 and N1-N12 from `baseline-review-and-test-charter.md`. H0B reconstructs only the six snapshots' `tables["positions.csv"]` from the preserved H0 raw outputs, after correcting leading-`#` CSV-header parsing. Preserve the old snapshots in disposable evidence, prove all other snapshot blocks and raw H0 files unchanged, and update only the manifest's six snapshot hashes; the original binary hash stays unchanged. Add one focused `scripts/validation/tests/test_regression_check.py` file to prevent recurrence and extend existing RL tests, not a broad new test hierarchy.

The remaining repairs clarify interrupted episode status, record all eight direct package versions, accept canonical reward names in the generator, strip Python INI inline comments like C++, correct help/docs and audit records, close stdin for unattended launchers, remove the unpinned pip upgrade, remove empty loader-path entries, and clarify Tester output-write authority. Document the unit runner's stop behavior rather than changing it. These repairs use the existing planned files except the single regression test file. They do not change jammer physics, reward arithmetic, scenario inputs, or C++ output schemas. H1 remains a human-only build under `CLAUDE.md`; the independent Reviewer must reissue the charter before Tester execution.

## 1. Objective and acceptance gate

P0 does not choose the final observation space, action space, reward, multi-node control policy, jammer physics, SLURM layout, or GUI design. It establishes a small, reproducible baseline on which those later phases can safely build.

P0 is accepted only when all of the following are true:

1. The existing standalone test suite passes, except for a failure proven by the before/after logs to be pre-existing and unrelated to every P0 file. Any failure in changed behavior blocks acceptance.
2. A human completes a fresh ns-3 configure/build, and the repaired CLI integration suite passes against that exact binary.
3. Every way of starting the simulator uses the scenario's same radio-mode selection unless the user explicitly overrides it, and the simulator saves the final selection and where it came from in `run.log`.
4. The incorrectly named `mean_sinr` reward identifier is replaced by `all_links_los`; the legacy name remains a warning-producing alias with unchanged reward arithmetic.
5. The existing jammer path is observable and demonstrably affects at least one link in a deterministic smoke scenario. P0 does not change jammer physics.
6. RL subprocess failures are understandable, each episode has an isolated output directory, the chosen seed is recorded, and a rerun cannot overwrite an earlier episode.
7. A short MaskablePPO process smoke finishes and saves a model plus a manifest containing the algorithm, seed, band, hyperparameters, source scenario, and tested dependency versions.
8. The Python environment can be created with one documented command using a small, tested dependency file. P0 does not claim that a lock produced on one operating system is a universal cluster lock.
9. The Implementer, Reviewer, Tester, and final Reviewer complete the evidence loop described in section 13. The Git/PR role is the only role that creates branches, stages, commits, pushes, or opens a pull request.
10. Compact deterministic pre-change snapshots cover the baseline, Sherpa, CalFEX, and synthetic-jammer families; post-change runs match them within the documented tolerance. Raw output directories are not committed.

Developer-owned jammer questions in section 9 may remain open. Core build, execution, output, and test failures may not be marked deferred merely to pass P0.

## 2. Verified starting state and ownership

The Scout recorded the following starting state:

- Branch `arpo-main`, HEAD `a4e700d9947db57d06ade3ce391425681a3c2746` at scouting time.
- `CLAUDE.md` is modified by the user.
- `docs/ORCHESTRATION.md`, `docs/claude/`, and `docs/rl-program/` are untracked user work.
- `run.log` is written once at the simulator invocation root, before the per-seed loop. It is not written in `seed-N/`.
- Per-seed CSV and JSON results are written under `seed-N/`.
- New scenarios currently follow `inputs/baselines/<name>/`; the integration script's `inputs/scenarios/triangle` fixture does not exist.
- The exact RL key is `[rl] controlled_node_id`.
- `JammerSpec.id` is a string and the jammer schema has target frequencies but no jammer-bandwidth field.

Ownership rules:

- Do not edit `CLAUDE.md`.
- The P0 plan explicitly authorizes only the workflow-document edits listed in section 15. Preserve every other existing user edit under `docs/`.
- Do not modify generated outputs, existing scientific datasets, `inputs/custom/`, or files outside `scratch/mesh-sim/`. P0 may read existing scenarios from each documented input family to produce regression evidence.
- Implementer, Reviewer, and Tester may use read-only Git commands such as `git status` and `git diff`. They must not mutate Git state.
- The Implementer must not run `./ns3 configure`, `./ns3 build`, `./ns3 run`, or `./ns3 clean`. The human performs those commands.

## 3. P0 decisions

### 3.1 Radio band

- Here `band` is the existing categorical radio-mode switch, not the numeric center frequency and not bandwidth. In ordinary terminology, `sub-6` means frequencies below about 6 GHz, while mmWave refers to much higher frequencies (commonly beginning around 24 GHz). The current simulator does not derive this label from `frequency_ghz`.
- In the current code, this switch specifically controls whether configured **jammer interference** is added: `sub-6` enables that path and `mmwave` skips it. It does not currently model general co-channel interference among ordinary mesh nodes.
- Store it beside `frequency_ghz` and `bandwidth_mhz` in `[channel]` because all three describe how `LinkEvaluator` treats the radio channel and must travel together with a reproducible scenario. P0 persists the existing switch; it does not claim the label is automatically implied by frequency.
- Add `band` to the existing `[channel]` section of `run.ini`.
- Valid values remain the exact strings `mmwave` and `sub-6`.
- Resolution is: explicitly supplied simulator `--band` override, then `[channel] band`, then the legacy default `mmwave`.
- Change `CliArgs.band` from a default of `mmwave` to an empty value meaning “no CLI override.” Validate a non-empty CLI value in `ParseCommandLine`; validate the resolved value in `ValidateConfig`.
- Store the resolved value and source (`cli`, `run.ini`, or `default`) in `SimConfig`.
- Do not change the legacy default to `sub-6` until the team answers TODO-BAND-1.
- Do not add an automatic frequency threshold or reject unusual band/frequency pairs in P0. Record that naming/validation decision as TODO-BAND-2.
- Missing `band` remains backward-compatible and is recorded as `band_source = default`; do not print a warning for every historical scenario.

### 3.2 Run log and jammer observability

Extend the existing human-readable `run.log`; do not introduce a second log grammar or a per-tick jammer CSV in P0.

Treat the current jammer calculations and their existing good alignment with observed results as the accepted regression baseline. P0 may expose configuration and compare outputs, but it must not tune or “correct” jammer calculations without a later team decision.

Add these entries to the existing sections:

```text
CLI overrides:
  --output-dir         = <value or (not set)>
  --debug-links        = <true|false>
  --rl-mode            = <true|false>
  --band               = <value or (not set)>

Resolved config:
  band                 = <mmwave|sub-6>
  band_source          = <cli|run.ini|default>
  rl.reward_type       = <throughput|all_links_los>
  rl.reward_alias      = <mean_sinr|none>
  jammers.configured   = <count in SimConfig>
  jammers.enabled      = <enabled count>
  jammer_path_enabled  = <true when band is sub-6 and an enabled jammer exists>
```

Write one concise line per configured jammer using fields already present in `JammerSpec`: string ID, enabled flag, type, target frequencies in MHz, transmit power, antenna gain, duty cycle, range, beamwidth, azimuth, zenith, and motion source (`waypoints`, `velocity`, or `static`). Do not invent jammer bandwidth, received antenna gain, spectral overlap, or disconnection fields.

`run.log` remains at `<invocation-output>/run.log`. In an RL run, the invocation output is the episode directory.

### 3.3 Reward compatibility

- Canonical names after P0 are `throughput` and `all_links_los`.
- When the loader sees `mean_sinr`, normalize it to `all_links_los` and set a small compatibility field such as `reward_type_alias = "mean_sinr"` in `RlConfig`.
- `sim.cc` prints one concise deprecation warning when the alias was used.
- Rename the C++ reward branch/helper accordingly, but do not change its arithmetic: it remains +1 only when the controlled node has at least one peer link and every such link is LOS; otherwise -1. Connectivity and SINR remain ignored.
- Update the existing `rl-test` scenario to use `all_links_los`; test the alias using a temporary copy.

### 3.4 RL movement and action safety

- Malformed action JSON or closed stdin maps to discrete action 6 (Stay), not action 0 (-X), and emits one warning to stderr.
- Add the missing `z_min < z_max` validation.
- Make Python use the same x/y/z defaults as `RlConfig`.
- Do not change action meanings, continuous-action dimensionality, speed caps, tick-level decision timing, or which node is controlled. Those are P1 decisions.

### 3.5 Episode directories and seeds

- Each `MeshRlEnv.reset()` allocates the next unused `episode-NNNN/` directory under the training output root.
- The simulator receives that episode directory through `--output-dir` and therefore writes:

```text
<training-output>/
  train_manifest.json
  maskable_ppo_mesh.zip
  episode-0000/
    run.log
    inputs/
    sim_stderr.log
    rl_episode.json
    seed-<seed>/
      positions.csv
      links.csv
      summary.json
      ...
```

- P0 deliberately uses one fixed training seed. Resolution is: an explicit training/Gym seed override, then `[scenario] seed` from `run.ini`. Remove the Python-only hardcoded default of 42. A reset without a seed reuses the resolved seed; it does not silently increment it.
- `episode-NNNN` is only a unique run-directory index. It never determines or modifies the seed.
- The phase records this limitation as TODO-RL-SEEDS-1. Multi-seed training/evaluation policy belongs in the experiment phase.
- Resets within one training process append episode directories. Starting a new training process against a directory that already contains a completed `train_manifest.json` or model fails clearly; it does not append to, or overwrite, an earlier experiment.

### 3.6 Python environment and dependency versions

- Add one top-level `requirements.txt` containing only direct project dependencies: `gymnasium`, `numpy`, `stable-baselines3`, `sb3-contrib`, `torch`, `pandas`, `matplotlib`, and `pytest`.
- Pin those direct dependencies to versions actually installed and tested by the Implementer. Do not commit a platform-specific full `pip freeze` as a universal lock.
- Add one small cross-platform helper, `scripts/rl/bootstrap_venv.py`, that creates `.venv`, installs `requirements.txt`, verifies the imports, and prints Python plus package versions. It must use Python's `venv` and `subprocess`, not a shell script.
- Add `.venv/` to a mesh-sim `.gitignore`.
- A later SLURM phase may add a cluster-specific constraints file, module/container profile, or lock after testing on the target cluster.

### 3.7 Launcher behavior

- RL accepts optional `--band` and forwards it as a simulator override. Omitting it lets `run.ini` decide.
- `build_config_files.py --band` writes `[channel] band` into every generated `run.ini`.
- `run_batch.py` accepts an optional band override and forwards it only when supplied.
- Sweeps need no new band-specific parser: the existing generic sweep format can set or sweep `channel.band`. The generated point `run.ini` is the source of truth.
- Change the sweep and validation subprocess-capture filename from `run.log` to `console.log`. Their current use of `run.log` conflicts with the simulator's own reproducibility log in the same directory.

### 3.8 Before/after regression record

The existing `compare_baseline.py` and `compare_runs.py` compare simulator results with field-validation summaries; they do not compare two simulator builds. Add one small standard-library utility, `scripts/validation/regression_check.py`, with three subcommands:

- `capture`: run one scenario with an explicit binary, seed, band, and disposable output directory while setting the required ns-3 library path; when `--snapshot` is supplied, also write one compact normalized snapshot;
- `compare`: compare a committed normalized snapshot with a candidate run directory and write a compact JSON report.
- `verify-suite`: validate a tracked suite manifest and all snapshot hashes, run every available listed case against one binary, compare every result, write one suite report, print a concise plain-language purpose/header plus one labeled PASS/FAIL/SKIP row per case, and return exit 0 only when every required and executed optional case passes.

The snapshot and comparison cover row identities, string fields, and numeric values in `positions.csv`, `links.csv`, `rx-power.csv`, `mcs.csv`, `flows.csv`, and `routes.csv`, plus stable `summary.json` fields. They ignore `run.log` because P0 intentionally expands that file, and ignore `summary.json` wall-clock timestamps and elapsed time. The default numeric tolerance is `1e-9`, configurable by `--atol`.

Each normalized snapshot records `snapshot_version = 1`, a descriptive case name, input family, the relative path and SHA-256 for `run.ini` and every referenced input file (`nodes.json`, plus buildings or jammers when present), explicit seed, explicit band, and only the stable simulation values needed for comparison. Raw run directories stay ignored under `outputs/`; compact normalized snapshots live under `tests/fixtures/regression/p0/` and are intended to be committed by the Git/PR role after review.

`tests/fixtures/regression/p0/manifest.json` is the machine-readable suite index. It records the pre-change Git commit, clean-build profile and architecture, pre-change simulator SHA-256, and each case's human label, required/optional status, family, seed, band, run configuration, snapshot path, and snapshot SHA-256. `verify-suite` checks manifest/snapshot integrity before starting a simulator process. It reports a shortened current binary fingerprint in the console and both full hashes in the JSON report, but does not require equality because a correctly rebuilt post-change binary will naturally differ.

The five cases whose inputs are tracked (`baselines` and `calfex`) are required. The ignored local Sherpa case is optional: run it automatically when its recorded source files are present and unchanged; otherwise print `SKIP`, list the missing paths, and plainly tell the user that the data is not included in Git and to ask the project team or data owner for the approved `inputs/custom/sherpa` data. A missing optional case does not fail the portable default suite. `--require-all` makes missing optional data fail for a complete lab-data check. An optional case that is present but changed or produces a mismatch always fails.

Suite run products are disposable. Reusing the same `verify-suite --out` automatically replaces only `suite-report.json` and the manifest-named case subdirectories owned by that suite. Require `--out` to resolve beneath `mesh-sim/outputs/`, reject `outputs/` itself and unsafe case-name path segments, and leave unrelated siblings untouched. This convenience never overwrites the tracked manifest or snapshots. The lower-level `capture --snapshot` command retains its explicit `--force` protection.

The human captures the “before” snapshots with the current binary after the utility and deterministic jammer fixture exist but before any simulator runtime edit. The set deliberately covers three committed synthetic baselines, one local Sherpa/ARPO mmWave scenario, one committed CalFEX sub-6 scenario, and the synthetic jammer smoke. Sherpa and CalFEX are separate families: the current Sherpa Spring Lake inputs describe April ARPO mmWave trials at 64.8 GHz, whereas the current CalFEX inputs describe May/June field-derived sub-6 scenarios around 2.2113 GHz. The same source path, source digest, seed, and explicit band are used after the fresh P0 build. Stable outputs must remain equal within tolerance unless the approved plan explicitly names a changed field.

### 3.9 Input and output family labels

P0 preserves the existing layout and documents it instead of moving data:

| Path | Label and role | Git policy in P0 |
| --- | --- | --- |
| `inputs/baselines/` | Small synthetic scenarios used for deterministic simulator validation | Existing inputs remain tracked; add only the two P0 smoke fixtures. |
| `inputs/custom/sherpa/` | Local custom/Sherpa scenarios, including Spring Lake ARPO mmWave cases | Read-only and currently ignored; do not relocate or start tracking the directory in P0. |
| `inputs/calfex/` | Field-derived CalFEX sub-6 scenario configurations | Preserve the currently tracked files and their names; do not regenerate or reorganize them in P0. |
| `data/` | Local raw and derived field telemetry used by validation generators/comparisons | Ignored and read-only. |
| `outputs/` | Disposable simulator, RL, sweep, and validation run products | Ignored; never commit raw captures. |
| `tests/fixtures/regression/p0/` | Compact normalized deterministic pre-change snapshots | New tracked test evidence; no raw logs, plots, or full output trees. |

The current checkout contains the main local field data and the scenario families above, but no EW-trials source CSV and no generated field `jammers.json` were found under `scratch/mesh-sim/`. The synthetic `p0-jammer-smoke` therefore supplies P0's deterministic jammer coverage. Add TODO-DATA-1 to identify the owner/location of the real EW trials table, document how it generates `jammers.json`, and decide whether any generated jammer input belongs in `inputs/calfex/` or remains local. This is a provenance question, not permission to change jammer physics.

## 4. Ordered implementation sequence

| Step | Work | Depends on | Owner |
| --- | --- | --- | --- |
| S0 | Record baseline status; add the isolated regression utility/fixtures | — | Implementer |
| H0 | Capture pre-change ordinary and jammer results with the current binary | S0 | Human |
| H0A | Record the baseline manifest and prove the one-command suite passes | H0 | Human-approved pre-S1 correction |
| S1 | Band configuration, validation, CLI precedence, and run logging | H0A | Implementer |
| S2 | Reward rename/alias, z validation, and Stay-on-invalid-action | S0 | Implementer |
| S3 | Small smoke scenarios and repaired CLI integration suite | S1–S2 | Implementer |
| S4 | Launcher consistency and `console.log` separation | S1 | Implementer |
| S5 | RL episode lifecycle, diagnostics, registration, and training manifest | S1–S2 | Implementer |
| S6 | Python dependency bootstrap and focused Python tests | S5 | Implementer |
| S7 | Minimal user and workflow documentation; implementation audit | S3–S6 | Implementer |
| H1 | Fresh ns-3 configure/build | S7 | Human |
| R1 | Diff review and test charter | S7 | Reviewer |
| T1 | Execute approved charter against `<BIN>` | H1, R1 | Tester |
| R2 | Resolve findings and write final verdict | T1 | Reviewer |
| G1 | Branch, commit, push, and PR only after acceptance | R2 accept | Git/PR role |

S1/S2 and S5/S6 may be implemented as separate concerns, but the Implementer does not create commits. Logical commit grouping is a later Git/PR decision based on the accepted audit.

## 5. Step-by-step implementation contract

### S0 — Baseline record

1. Read the applicable `CLAUDE.md` files for every directory that will be edited.
2. Record `git status --short`, `git rev-parse HEAD`, compiler version, Python version, and operating system in `baseline-implementation-audit.md`.
3. Run `cd tests && make test` before editing.
4. Record the full summary and exact failing test names. Do not fix unrelated failures.
5. Add only `scripts/validation/regression_check.py`, the empty `tests/fixtures/regression/p0/` destination, and the deterministic `p0-jammer-smoke` fixture described in S3. This utility must not import simulator code or alter inputs.
6. Ask the human to execute all six H0 captures. Verify that the normalized snapshots contain no wall-clock values, absolute paths, or raw logs, then record their paths and digests before proceeding to S1.
7. Stop if the suite cannot compile or H0 cannot produce complete outputs; the human decides whether P0 can proceed.

Expected output: an audit section that distinguishes the verified baseline from later results. No Git mutation.

### S1 — Band and run-log provenance

Files:

- `src/domain/sim-config.h`
- `src/config/config-loader.cc`
- `src/config/config-validator.cc`
- `src/cli/cli-parser.h`
- `src/cli/cli-parser.cc`
- `src/io/run-logger.h`
- `sim.cc`
- `tests/unit/config/config-validator-test.cc`

Implementation:

1. Add `SimConfig.band = "mmwave"` and `SimConfig.band_source = "default"`.
2. Load `[channel] band`; a non-empty value sets `band_source` to `run.ini`.
3. Make the CLI band empty by default and validate only a supplied CLI value in the parser.
4. Apply the CLI override in `sim.cc` before `ValidateConfig`.
5. Validate the resolved band and pass `cfg.band` to `LinkEvaluator::Configure`.
6. Extend the existing run logger exactly as section 3.2 describes. Log the vector of resolved seeds already supplied to the logger; do not add a singular seed field.

Focused config cases, added to the existing config test executable:

- Missing band resolves to `mmwave/default`.
- `[channel] band = sub-6` resolves to `sub-6/run.ini`.
- Invalid resolved band fails and lists both valid values.
- CLI precedence is verified by the real integration test because the standalone config suite does not construct `ns3::CommandLine`.

Stop if this requires moving validation into the loader or adding ns-3 headers to `config/`.

### S2 — Reward and action correctness

Files:

- `src/domain/sim-config.h`
- `src/config/config-loader.cc`
- `src/config/config-validator.cc`
- `src/rl/rl-bridge.cc`
- `inputs/baselines/rl-test/run.ini`
- `tests/unit/config/config-validator-test.cc`

Implementation:

1. Add the small legacy-alias field to `RlConfig`.
2. Normalize `mean_sinr` during loading; validate only `throughput` and `all_links_los` afterward.
3. Rename the reward branch/helper and correct the inaccurate one-line domain documentation without changing the calculation.
4. Print one deprecation warning in `sim.cc` and retain the alias value in `run.log`.
5. Change EOF/malformed discrete input to Stay. Do not add a large exception framework on the C++ side.
6. Validate `z_min < z_max` beside the existing x/y checks.
7. Add explicit `band = mmwave`, `reward_type = all_links_los`, `z_min`, and `z_max` to `inputs/baselines/rl-test/run.ini`.

Focused config cases:

- `mean_sinr` becomes `all_links_los` and records the alias.
- `all_links_los` remains unchanged with no alias.
- An unknown reward fails.
- Invalid z bounds fail; valid z bounds pass.

Reviewer check: the body of the ±1 reward calculation is unchanged except for naming.

### S3 — Fixtures and CLI integration

New scenarios (the jammer fixture is created during S0 so H0 can capture its current behavior; its contents are not changed afterward):

- `inputs/baselines/p0-smoke/run.ini`
- `inputs/baselines/p0-smoke/nodes.json`
- `inputs/baselines/p0-jammer-smoke/run.ini`
- `inputs/baselines/p0-jammer-smoke/nodes.json`
- `inputs/baselines/p0-jammer-smoke/jammers.json`

Both scenarios use three drone peers at `(0,0,10)`, `(100,0,10)`, and `(50,50,10)` metres. The third node is `relay`, uses `constant_velocity` with zero initial velocity, and is selected by `[rl] controlled_node_id = relay`; the first two nodes are fixed. Both use `duration_s = 0.4`, `tick_s = 0.1`, `seed = 1`, constant 10 Mbps all-pairs traffic, discrete actions, `step_size_m = 5`, `all_links_los`, bounds `x=0..100`, `y=-50..100`, and `z=0..50`. RL is enabled in `p0-smoke` for the process test and disabled in `p0-jammer-smoke` so the same jammer fixture can be executed by the pre-P0 binary without relying on the renamed reward.

`p0-smoke` uses `[channel] band = mmwave`, 28 GHz, 400 MHz bandwidth, and `static_los`. `p0-jammer-smoke` uses `[channel] band = sub-6`, 2.4 GHz, the same bandwidth and condition model, and references `jammers.json`. Its single jammer is exactly: enabled, string ID `jammer-0`, type `constant`, target frequency `[2400.0]` MHz, transmit power 30 dBm, transmit-array gain 12 dBi, duty cycle 1.0, unlimited range (`max_range_m = 0`), omnidirectional (`beamwidth_deg = 360`), position `(50,0,10)`, and no intervals, waypoints, velocity, or random walk. Azimuth 0 and zenith 90 are written explicitly but are immaterial for an omnidirectional jammer. This fixture avoids making unresolved direction, duty-cycle, motion, or spectrum-overlap choices part of the smoke test.

Repair `tests/integration/cli-integration-test.sh`:

1. Resolve the script directory as `tests/integration`, mesh-sim as two parents above it, and ns3-mmwave as two parents above mesh-sim.
2. Accept `MESH_SIM_BIN` first, retain an optional positional binary for compatibility, and otherwise require exactly one executable match under `build/scratch/mesh-sim/ns3*-sim-*`.
3. Set `DYLD_LIBRARY_PATH` and `LD_LIBRARY_PATH` for the child process without erasing existing values.
4. Replace the nonexistent triangle paths with `inputs/baselines/p0-smoke`.
5. Preserve tests 1–3. Correct tests 4–6 so each proves its named condition rather than merely observing failure.
6. Add only two integration contracts:
   - explicit `--band=sub-6` overrides the smoke scenario's `mmwave` and `run.log` records `band_source = cli`;
   - the jammer scenario run under `sub-6` and then `mmwave`, with the same seed, produces at least one matched link/tick whose SINR differs, while both root `run.log` files accurately record whether the jammer path was enabled.

The comparison reads existing `seed-1/links.csv`; it does not introduce a diagnostic file or assert a disputed disconnection threshold.

Expected final integration count: the corrected six existing tests plus two new tests. Do not expand it further in P0.

### S4 — Launcher and output consistency

Files:

- `scripts/sweep/runner.py`
- `scripts/validation/build_config_files.py`
- `scripts/validation/run_batch.py`
- `scripts/validation/regression_check.py`

Implementation:

1. Rename captured process output to `console.log` in both sweep and validation batch runs so the simulator owns `run.log`.
2. Keep `run.log` at each point/scenario root and record `console_log` and output directory in the existing manifest.
3. Write `[channel] band = <selected value>` from `build_config_files.py`.
4. Add optional `--band {mmwave,sub-6}` to `run_batch.py`; append `--band=<value>` only when supplied and record the override in `batch_manifest.json`.
5. Do not add a sweep-specific band argument. Demonstrate in documentation that `[sweep.override] channel.band = sub-6` fixes a band and `[sweep] channel.band = mmwave, sub-6` sweeps it using the existing format.
6. Keep the regression utility independent of pandas/matplotlib so it can run before the RL environment is installed.

Focused verification:

- A Python test may exercise a pure command-building helper only if the change naturally exposes one. Do not refactor the runners just to make a unit test possible.
- Tester uses sweep and validation dry runs plus one real minimal run to confirm `console.log` and simulator `run.log` coexist.

### S5 — RL lifecycle and training manifest

Files:

- `scripts/rl/__init__.py`
- `scripts/rl/env/mesh_env.py`
- `scripts/rl/train.py`

Implementation:

1. Correct Gym registration to `entry_point="scripts.rl.env.mesh_env:MeshRlEnv"` and guard duplicate registration.
2. Preserve the supported invocation `python -m scripts.rl.train` from mesh-sim.
3. Correct the `train.py` usage so global arguments precede `m-ppo` and PPO arguments follow it.
4. Add global `--band {mmwave,sub-6}`; omit the simulator flag when the option is absent.
5. Require a usable output directory in `MeshRlEnv`, allocate unique episode directories, set the ns-3 library path for the child, and always capture stderr in the episode directory.
6. Resolve one fixed seed from an explicit CLI/Gym override or `[scenario] seed`, pass that same value to MaskablePPO and every simulator episode, and record it in `rl_episode.json`.
7. On premature exit, raise an error containing the exit code and the last 40 stderr lines. On invalid JSON, include the line number and a bounded copy of the offending line. Close stdin and wait briefly before terminate/kill during cleanup.
8. Correct x/y/z bound defaults and the observation docstring. Leave continuous actions 2D and label them unverified for P1.
9. Make the `m-ppo --seed` default `None`; resolve the scenario seed when it is omitted. Write `train_manifest.json` before training with `manifest_version = 1`, status, timestamps, absolute simulator and scenario paths, algorithm name, resolved seed and its source (`cli` or `run.ini`), band override or null, every exposed MaskablePPO hyperparameter, output root, Python version, and direct package versions. Update status/model path on success or failure.
10. Keep the existing model basename `maskable_ppo_mesh` for compatibility.

`rl_episode.json` contains only: manifest version, episode index, seed, simulator command as an argument list, start/end timestamps, status, exit code, step count, and cumulative reward. Absolute local paths are acceptable in these diagnostic manifests; scenario inputs remain archived by the simulator.

### S6 — Python bootstrap and focused tests

New files:

- `requirements.txt`
- `.gitignore`
- `scripts/rl/bootstrap_venv.py`
- `scripts/rl/tests/fake_sim.py`
- `scripts/rl/tests/test_mesh_env.py`

Do not add package-marker files solely for pytest; the existing import layout already works from mesh-sim.

The fake simulator implements only the observed JSON fields used by `MeshRlEnv`, accepts the real flag spellings, creates the same root `run.log` plus `seed-N/` shape, and supports normal, exit-code-3, and malformed-output modes.

Keep the Python suite to five contract groups, using parameterization where useful:

1. Two resets create distinct episode directories without overwriting; both record the intentionally fixed seed.
2. `reset(seed=7)` changes the recorded seed to 7 and a following unseeded reset reuses 7.
3. Exit and malformed-protocol errors contain the required diagnostic context.
4. Band forwarding/omission and x/y/z mask defaults match the config contract.
5. Gym registration resolves, CLI help has the correct argument order, and a tiny fake-simulator training invocation produces a manifest/model when practical; the real-binary training smoke remains a Tester test.

`bootstrap_venv.py` behavior:

```text
python3 scripts/rl/bootstrap_venv.py [--venv PATH] [--check]
```

- Require Python 3.10 or newer.
- Create the venv when absent.
- Install `requirements.txt` unless `--check` is used.
- Import and print the versions of all direct dependencies.
- Exit nonzero with the failing command or import named.
- Print activation instructions for POSIX and Windows without claiming Windows ns-3 support.

### S7 — Minimal documentation and audit

Modify `README.md` only where needed to cover:

- ns-3 build remains the existing root workflow;
- one Python bootstrap command;
- valid `[channel] band` values and CLI precedence;
- `throughput`, `all_links_los`, and the deprecated alias;
- one correct MaskablePPO smoke command;
- one sweep-band example using the existing generic matrix;
- output locations for `run.log`, `console.log`, per-seed results, episode manifests, training manifest, and model.

Update `inputs/README.md` and `scripts/validation/README.md` narrowly to apply the labels in section 3.9, explain that Sherpa and CalFEX are distinct field-derived workflows, identify tracked inputs, ignored local source data, disposable outputs, and committed normalized regression snapshots, and document the single `verify-suite` command, safe automatic suite-output replacement, optional-data message, `--require-all`, and exit-code contract. Do not add a second tutorial or rewrite the validation guide.

Workflow documentation changes are limited to:

- add `docs/claude/TESTER_PROMPT.md` as the reusable execution-only Tester role;
- update `docs/claude/README.md` and `docs/claude/REVIEWER_PROMPT.md` just enough to state that a runtime-phase Reviewer writes a test charter, the Tester writes results back to the Reviewer, and only the Git/PR role mutates Git;
- preserve the existing documentation-only review workflow and its paths.

Human-approved post-S7 workflow correction: consolidate the redundant top-level `docs/ORCHESTRATION.md` index into new `docs/claude/ORCHESTRATOR_PROMPT.md`, and update `docs/claude/IMPLEMENTER_PROMPT.md` plus the workflow README to preserve the successful Fable-coordinator/parallel-Opus implementation pattern. Also clarify the runtime variant in `docs/claude/REVIEWER_PROMPT.md`: the independent Reviewer may write exactly one charter or completion artifact but may not edit implementation files or run tests. Delegation is limited to bounded, non-overlapping work inside an approved implementation stage. The Orchestrator reviews and integrates all worker results and maintains one audit. Reviewer, Tester, Progress, and Git/PR remain separate human-started, non-delegating roles; only Git/PR mutates Git.

Add the unresolved items from section 9 as a concise “Jammer model decisions” section in the existing `TODO.md`. Add TODO-DATA-1 for the missing EW-trials source table and its expected `jammers.json` generation/provenance. Link back to the P0 completion report for current status instead of creating a separate jammer or data TODO file.

The Implementer writes `docs/rl-program/p0-baseline/baseline-implementation-audit.md` with:

- starting status and baseline test result;
- exact files changed and why;
- decisions implemented and deviations from this approved plan;
- commands the Implementer ran and concise results;
- commands reserved for the human/Tester;
- final output contracts and remaining TODOs;
- confirmation that no Git mutation or prohibited ns-3 command was run.

## 6. Configuration and command interfaces

### Scenario configuration

| Section/key | Type | Default | Valid values | Purpose |
| --- | --- | --- | --- | --- |
| `[channel] band` | string | `mmwave` | `mmwave`, `sub-6` | Selects the existing radio/interference path. |
| `[rl] controlled_node_id` | string | empty → current last-node behavior | existing node ID | P0 still controls one node. |
| `[rl] action_type` | string | `discrete` | `discrete`, `continuous` | Continuous remains provisional. |
| `[rl] reward_type` | string | `throughput` | `throughput`, `all_links_los`; legacy `mean_sinr` alias | Selects current reward implementation. |
| `[rl] x_min/x_max/y_min/y_max/z_min/z_max` | float metres | C++ `RlConfig` defaults | min < max | Action bounds shared by C++ and Python. |

No `jammer_diagnostics` key is added in P0.

### Direct simulator CLI

`--band=<mmwave|sub-6>` is an optional override. Existing `--run-config`, seed, output, debug, and RL flags remain unchanged.

### Training CLI

```text
python -m scripts.rl.train \
  --sim-binary <BIN> \
  --run-config inputs/baselines/p0-smoke/run.ini \
  --output-dir outputs/p0-verification/rl \
  [--band sub-6] \
  m-ppo --total-timesteps 16 --n-steps 16 --seed 1
```

### Validation batch CLI

`python -m scripts.validation.run_batch ... [--band sub-6]`

### Sweep configuration

```ini
[sweep.override]
channel.band = sub-6

# Or as a dimension:
[sweep]
channel.band = mmwave, sub-6
```

## 7. Output and reproducibility contracts

### Direct, sweep point, or validation scenario

```text
<invocation-output>/
  run.log                 simulator configuration/provenance
  console.log             sweep/validation child output only; absent for direct runs
  inputs/                 archived scenario inputs
  seed-1/
    positions.csv
    links.csv
    flows.csv
    routes.csv
    summary.json
    ...
```

### RL training

Use the layout in section 3.5. `train_manifest.json` describes the training command and model. Each `rl_episode.json` describes exactly one simulator subprocess. Each episode's `run.log` describes one simulator invocation and contains its seed list.

### Compatibility

- Existing CSV and `summary.json` schemas do not change in P0, preserving GUI compatibility.
- Existing scenarios without `band` still run as `mmwave` and say `band_source = default` in their output.
- The old reward spelling still runs with a warning.
- The model filename remains `maskable_ppo_mesh.zip`.

## 8. Test standard and bounded test matrix

Use three levels only:

1. Unit/contract tests for pure config and Python process behavior.
2. Integration tests against the real simulator binary.
3. One short MaskablePPO process smoke; no convergence claim.

Standards:

- Every test states the contract it proves and has a deterministic fixture.
- Tests fail for the intended reason; fixture existence is checked before negative CLI tests.
- No test changes jammer physics or treats an unresolved scientific assumption as correct.
- Parameterize related cases rather than creating one file per case.
- P0 adds at most four C++ config groups, five Python groups, and two new real-binary integration contracts.
- A simple convergence scenario (stationary jammer escape or building avoidance) is required later, after P1 defines the observation/action/reward contract. It is not mislabeled as a P0 process smoke.

## 9. Jammer behavior frozen in P0 and team TODOs

P0 preserves the current behavior: jammers affect only `sub-6`; the model tests target frequencies against the carrier center; it evaluates both link endpoints and uses the larger interference value; direction uses the jammer's 3D cone; constant and random jammers interpret duty cycle differently; jammed SINR is floored at 0 dB; recorded jammer movement representation is unresolved.

Ask the team these plain-language questions before changing physics:

1. **Link failure:** Should 0 dB make a link unusable, or should the 0 dB floor be removed so SINR can fall below the existing -6.7 dB link threshold?
2. **Default band:** Should newly generated scenarios default to `sub-6` while old scenarios retain `mmwave`, or should one global default apply?
3. **Band versus frequency:** Should the existing `band` switch remain an explicit scenario choice, be renamed to describe its actual jammer-interference behavior, or eventually be derived/validated from `frequency_ghz`?
4. **Endpoint rule:** Is the current “calculate interference at both ends and use the worse end” behavior correct?
5. **Frequency overlap:** Should a jammer affect a channel whenever their frequency ranges overlap, rather than using the current carrier-center test?
6. **Recorded motion:** Which Sherpa file is the authoritative jammer trajectory, and should it become waypoints or another recorded-motion form?
7. **Antenna effects:** Should the receiving node's antenna direction/gain alter jammer interference, in addition to the jammer's own pointing direction?
8. **Duty cycle:** Should constant and random jammers continue to interpret duty cycle differently?

Record answers in the P0 completion report if received; otherwise carry the TODOs forward with owners. Do not infer answers.

## 10. Human verification procedure

Use `outputs/p0-verification/` for disposable verification results. Do not add those outputs to Git. The Tester records commands and concise observed results in `baseline-test-results.md`; large logs remain in the output directory.

### H0 — Human pre-change regression capture

Before S1 changes runtime behavior, use the current built binary. These six cases are intentionally limited: three synthetic behaviors plus one representative from each distinct field family and one synthetic jammer case.

```text
python3 -m scripts.validation.regression_check capture \
  --sim-binary <CURRENT_BIN> \
  --run-config inputs/baselines/01-static-los-baseline/run.ini \
  --band mmwave --seed 1 \
  --family baseline --case static-los \
  --out outputs/p0-regression/before/static-los \
  --snapshot tests/fixtures/regression/p0/baseline-static-los.json

python3 -m scripts.validation.regression_check capture \
  --sim-binary <CURRENT_BIN> \
  --run-config inputs/baselines/03-building-blockage/run.ini \
  --band mmwave --seed 1 \
  --family baseline --case building-blockage \
  --out outputs/p0-regression/before/building-blockage \
  --snapshot tests/fixtures/regression/p0/baseline-building-blockage.json

python3 -m scripts.validation.regression_check capture \
  --sim-binary <CURRENT_BIN> \
  --run-config inputs/baselines/07-three-node-relay/run.ini \
  --band mmwave --seed 1 \
  --family baseline --case three-node-relay \
  --out outputs/p0-regression/before/relay \
  --snapshot tests/fixtures/regression/p0/baseline-three-node-relay.json

python3 -m scripts.validation.regression_check capture \
  --sim-binary <CURRENT_BIN> \
  --run-config inputs/custom/sherpa/spring_lake/arpo-1-1-static-04172026/run.ini \
  --band mmwave --seed 1 \
  --family sherpa --case spring-lake-static \
  --out outputs/p0-regression/before/sherpa-static \
  --snapshot tests/fixtures/regression/p0/sherpa-spring-lake-static.json

python3 -m scripts.validation.regression_check capture \
  --sim-binary <CURRENT_BIN> \
  --run-config inputs/calfex/06-25/1509-1513/run.ini \
  --band sub-6 --seed 1 \
  --family calfex --case 06-25-1509-1513 \
  --out outputs/p0-regression/before/calfex-1509-1513 \
  --snapshot tests/fixtures/regression/p0/calfex-06-25-1509-1513.json

python3 -m scripts.validation.regression_check capture \
  --sim-binary <CURRENT_BIN> \
  --run-config inputs/baselines/p0-jammer-smoke/run.ini \
  --band sub-6 --seed 1 \
  --family baseline --case synthetic-jammer \
  --out outputs/p0-regression/before/jammer \
  --snapshot tests/fixtures/regression/p0/baseline-synthetic-jammer.json
```

PASS: all six captures exit successfully, each raw directory contains the stable CSV files plus `seed-1/summary.json`, and each snapshot contains the declared family, case, relative source-file paths and digests, seed, band, and normalized stable values. Record the current binary path and output locations in the implementation audit. Raw directories are not committed; the six reviewed snapshot JSON files are tracked evidence. If the ignored Sherpa source is absent on another machine, report that single case as unavailable rather than relabeling another input as Sherpa or CalFEX.

### H0A — Baseline manifest and one-command proof

After H0 and before S1, write `tests/fixtures/regression/p0/manifest.json` with the fields specified in section 3.8. Run:

```text
python3 -m scripts.validation.regression_check verify-suite \
  --sim-binary <CURRENT_BIN> \
  --manifest tests/fixtures/regression/p0/manifest.json \
  --out outputs/p0-regression/suite-prechange
```

PASS on this complete checkout: manifest integrity passes before simulation, all six cases print `PASS`, the result is `PASS — required 5/5, optional 1/1, skipped 0`, the process exits 0, and `suite-report.json` records the full baseline/current binary hashes and case results. Repeating the command against the same suite output replaces the prior disposable case results and prints that fact. On a fresh checkout without ignored Sherpa data, the expected portable result is five required passes plus one clearly explained optional skip. Preserve the six snapshots and manifest.

### H1 — Human build

From the ns3-mmwave root, the human runs the repository's documented configure/build commands. On the current macOS setup:

```text
./ns3 configure --build-profile=debug -- -DCMAKE_OSX_ARCHITECTURES=arm64
./ns3 build
```

PASS: the build completes and the human gives the Tester the absolute `<BIN>` path. The human does not need to clean unless diagnosing a build problem.

### T1 — Standalone unit tests

From `scratch/mesh-sim/tests/`:

```text
make test
```

PASS: every changed-scope test passes. An unrelated pre-existing failure is acceptable only when the baseline audit proves the identical failure existed before edits and the Reviewer explicitly accepts it.

### T1A — Post-change regression comparison

Run the complete tracked suite with the freshly built `<BIN>`:

```text
python3 -m scripts.validation.regression_check verify-suite \
  --sim-binary <BIN> \
  --manifest tests/fixtures/regression/p0/manifest.json \
  --out outputs/p0-regression/suite-postchange
```

PASS: manifest integrity passes, all five required comparisons pass, any available optional comparison passes, the final result is `PASS`, and the command exits 0. The complete project environment additionally runs T1A with `--require-all` and expects the Sherpa case to pass. Use the individual `compare` subcommand and per-case reports to diagnose a failure. `run.log` changes are inspected separately because P0 intentionally adds provenance fields.

### T2 — Real CLI integration

From `scratch/mesh-sim/tests/`:

```text
MESH_SIM_BIN=<BIN> make integration
```

PASS: all eight contracts pass, the valid run has root `run.log`, per-seed outputs exist, CLI band precedence is correct, and the jammer comparison observes at least one changed SINR.

### T3 — Python environment and contracts

From `scratch/mesh-sim/`:

```text
python3 scripts/rl/bootstrap_venv.py
.venv/bin/python -m pytest scripts/rl/tests -q
```

On Windows, use `.venv\Scripts\python.exe` for the second command.

PASS: bootstrap prints the tested versions and all five test groups pass.

### T4 — Real MaskablePPO process smoke

From `scratch/mesh-sim/`, using the venv:

```text
.venv/bin/python -m scripts.rl.train \
  --sim-binary <BIN> \
  --run-config inputs/baselines/p0-smoke/run.ini \
  --output-dir outputs/p0-verification/rl \
  m-ppo --total-timesteps 16 --n-steps 16 --seed 1
```

PASS:

- training exits successfully;
- `maskable_ppo_mesh.zip` and a completed `train_manifest.json` exist;
- at least two episode directories exist because the smoke scenario is shorter than the rollout;
- every episode uses seed 1 by design;
- each episode has root `run.log`, `rl_episode.json`, `sim_stderr.log`, and `seed-1/`;
- manifests contain the actual hyperparameters and package versions;
- no earlier episode was overwritten.

This proves process integration only, not learning or convergence.

### T5 — Sweep and validation surfaces

1. Run the existing sweep CLI with a temporary one-point sweep derived from `inputs/sweeps/example.ini`, using `inputs/baselines/p0-smoke` and `channel.band = mmwave`.
2. Run `scripts.validation.run_batch` on a temporary directory containing only the P0 smoke scenario.
3. Use one seed and the explicit binary.

PASS: each run retains simulator `run.log`, separate `console.log`, archived input with explicit band, per-seed results, and an accurate manifest. The audit must provide the exact temporary-file commands in an OS-appropriate form; do not commit another permanent sweep file solely for this check.

### T6 — Legacy reward alias

Create a temporary copy of `p0-smoke/run.ini`, replace `all_links_los` with `mean_sinr`, and run a short RL subprocess using the same binary and seed.

PASS: it runs, stderr contains one deprecation warning, and root `run.log` records `rl.reward_type = all_links_los` and `rl.reward_alias = mean_sinr`. No reward-logic difference is observed in the emitted sequence for the same fixed scenario/actions.

## 11. Expected results and failure interpretation

| Verification | Expected | A failure most likely means |
| --- | --- | --- |
| Pre/post regression | stable ordinary and jammer outputs match | unintended simulator behavior change |
| Config unit tests | resolved band/reward/bounds match contracts | loader or validator divergence |
| CLI integration | 8 PASS | bad path, wrong exit assertion, binary/library lookup, or band plumbing |
| Jammer A/B smoke | at least one SINR differs | jammer inactive, frequency mismatch, scenario geometry, or band not forwarded |
| Python tests | 5 groups pass | lifecycle, manifest, protocol, registration, or mask bug |
| MaskablePPO smoke | model + complete manifest + isolated episodes | SB3/Gym contract or subprocess lifecycle bug |
| Sweep/validation smoke | both logs coexist and band is archived | launcher log collision or missing config propagation |

Do not “fix” a failed jammer A/B smoke by changing the physics. Inspect `run.log`, archived `jammers.json`, carrier frequency, target frequency, and enabled flags first. A physics defect found during P0 is recorded and returned to the team for an explicit decision.

## 12. Documentation restraint

P0 documentation is limited to the top-level README, the existing `TODO.md`, the existing run/config comments directly changed by code, the small reusable Tester workflow file, and the four phase artifacts. Do not add module READMEs, long source comments, generated API documentation, tutorial screenshots, or duplicate setup guides.

The full end-to-end simulator tutorial, GUI tutorial integration, SLURM guide, and experiment guide remain later planned work. P0 supplies correct commands and output contracts those guides will build upon.

## 13. Agent handoff pipeline

### Implementer → Reviewer

The Implementer writes `baseline-implementation-audit.md` and stops. It does not create a branch or commit. The audit must make it possible to check every changed file without rediscovery.

### Reviewer → Tester

The Reviewer reads the approved plan, Scout report, audit, and diff. It writes `baseline-review-and-test-charter.md` containing:

- severity-ranked findings with file and line;
- confirmation that scope and role boundaries were respected;
- one row for H0, T1, T1A, and T2–T6 with exact command, expected evidence, and responsible person;
- any additional regression test justified by a specific diff risk;
- blockers that must return to the Implementer before testing.

The Reviewer does not run the ns-3 build and does not fix findings.

### Tester → Reviewer

The Tester executes the approved charter and writes `baseline-test-results.md`. For each row it records environment, binary path, exact command, expected result, actual result, output location, and PASS/FAIL/BLOCKED. The Tester does not edit production code and does not convert failures into deferrals.

### Final Reviewer → Git/PR

The Reviewer reads the test results, rechecks any fixes, and writes `baseline-completion-report.md` with `accept` or `return`. Only after `accept` does the Git/PR role create a branch, stage explicit accepted paths, form focused commits, push, and open a PR. The human merges.

## 14. Stop conditions

The Implementer stops and asks the human when:

1. Baseline `make test` cannot compile.
2. A required change would alter jammer SINR, frequency, antenna, endpoint, mobility, or duty-cycle physics.
3. Reward arithmetic would need to change rather than only its name/alias.
4. The real `[channel] band` precedence cannot be implemented without breaking existing CLI usage.
5. RL episode isolation requires changing the C++ output schema.
6. A dependency cannot be installed in a clean Python 3.10+ venv on the Implementer's platform.
7. A file outside section 15 appears necessary.
8. A user-owned dirty file would have to be overwritten rather than narrowly patched.

The Tester reports BLOCKED—not PASS—when the required binary, dependency access, or human build result is unavailable.

## 15. Exact planned file set

Runtime/configuration:

- `sim.cc`
- `src/domain/sim-config.h`
- `src/config/config-loader.cc`
- `src/config/config-validator.cc`
- `src/cli/cli-parser.h`
- `src/cli/cli-parser.cc`
- `src/io/run-logger.h`
- `src/rl/rl-bridge.cc`

Python and launchers:

- `scripts/rl/__init__.py`
- `scripts/rl/env/mesh_env.py`
- `scripts/rl/train.py`
- `scripts/rl/bootstrap_venv.py` (new)
- `scripts/rl/tests/fake_sim.py` (new)
- `scripts/rl/tests/test_mesh_env.py` (new)
- `scripts/sweep/runner.py`
- `scripts/validation/build_config_files.py`
- `scripts/validation/run_batch.py`
- `scripts/validation/regression_check.py` (new)
- `scripts/validation/tests/test_regression_check.py` (new; approved R1 repair)
- `requirements.txt` (new)
- `.gitignore` (new)

Tests and scenarios:

- `tests/unit/config/config-validator-test.cc`
- `tests/integration/cli-integration-test.sh`
- `inputs/baselines/rl-test/run.ini`
- `inputs/baselines/p0-smoke/run.ini` (new)
- `inputs/baselines/p0-smoke/nodes.json` (new)
- `inputs/baselines/p0-jammer-smoke/run.ini` (new)
- `inputs/baselines/p0-jammer-smoke/nodes.json` (new)
- `inputs/baselines/p0-jammer-smoke/jammers.json` (new)
- `tests/fixtures/regression/p0/baseline-static-los.json` (new, generated pre-change snapshot)
- `tests/fixtures/regression/p0/baseline-building-blockage.json` (new, generated pre-change snapshot)
- `tests/fixtures/regression/p0/baseline-three-node-relay.json` (new, generated pre-change snapshot)
- `tests/fixtures/regression/p0/sherpa-spring-lake-static.json` (new, generated pre-change snapshot)
- `tests/fixtures/regression/p0/calfex-06-25-1509-1513.json` (new, generated pre-change snapshot)
- `tests/fixtures/regression/p0/baseline-synthetic-jammer.json` (new, generated pre-change snapshot)
- `tests/fixtures/regression/p0/manifest.json` (new, machine-readable suite and baseline hashes)

Documentation and phase artifacts:

- `README.md`
- `inputs/README.md`
- `scripts/validation/README.md`
- `TODO.md`
- `docs/claude/README.md`
- `docs/claude/ORCHESTRATOR_PROMPT.md` (new; replaces `docs/ORCHESTRATION.md`)
- `docs/claude/IMPLEMENTER_PROMPT.md`
- `docs/claude/REVIEWER_PROMPT.md`
- `docs/claude/TESTER_PROMPT.md` (new)
- `docs/rl-program/p0-baseline/baseline-implementation-audit.md` (Implementer)
- `docs/rl-program/p0-baseline/baseline-review-and-test-charter.md` (Reviewer)
- `docs/rl-program/p0-baseline/baseline-test-results.md` (Tester)
- `docs/rl-program/p0-baseline/baseline-completion-report.md` (final Reviewer)

No new C++ source file is planned, so `CMakeLists.txt` does not change. No permanent sweep fixture or raw-output evidence directory is added; only the compact tracked regression fixtures and manifest listed above are retained. Any additional file requires a recorded plan deviation and human approval before editing.

## 16. Final P0 checklist

- [ ] Baseline status and pre-edit tests recorded.
- [ ] Human pre-change snapshots exist for three synthetic baselines, Sherpa, CalFEX, and the synthetic jammer case.
- [ ] Each snapshot labels its input family, all referenced source paths/digests, explicit band, and seed; raw run directories remain ignored.
- [ ] The tracked manifest records the original Git commit, clean-build facts, simulator hash, and all six snapshot hashes.
- [ ] The pre-change one-command verifier exits 0 with `PASS — required 5/5, optional 1/1, skipped 0` on the complete local dataset.
- [ ] A missing optional Sherpa source produces an actionable ask-the-team SKIP; `--require-all` makes that absence fail.
- [ ] Reusing a suite output safely replaces only that suite's generated report and case directories; tracked evidence remains immutable.
- [ ] No Implementer/Reviewer/Tester Git mutation occurred.
- [ ] Human fresh build succeeded and `<BIN>` was recorded.
- [ ] Post-change captures match all six stable pre-change snapshots.
- [ ] Final standalone unit suite passed for all changed behavior.
- [ ] Eight real-binary integration contracts passed.
- [ ] `[channel] band` and CLI precedence work and are logged accurately.
- [ ] `run.log` is at the invocation root; per-seed outputs remain under `seed-N/`.
- [ ] Sweep/validation `console.log` no longer conflicts with simulator `run.log`.
- [ ] `all_links_los` is canonical; `mean_sinr` remains a warning-producing alias with identical arithmetic.
- [ ] Invalid/closed action input maps to Stay.
- [ ] The fixed-seed policy is explicit in manifests and TODO-RL-SEEDS-1 is carried forward.
- [ ] Python venv bootstrap and five focused contract groups passed.
- [ ] Real MaskablePPO process smoke saved the model, manifest, and isolated episode outputs.
- [ ] Jammer A/B smoke demonstrated an observable SINR change without physics edits.
- [ ] Existing CSV/JSON GUI schemas were unchanged.
- [ ] Jammer questions remain plainly documented with owners/status.
- [ ] Input/output family labels are documented, and TODO-DATA-1 records the missing real EW source table without mislabeling the synthetic jammer fixture.
- [ ] Reviewer charter, Tester results, and final Reviewer verdict are present.
- [ ] Final Reviewer verdict is `accept` before the Git/PR role begins.
