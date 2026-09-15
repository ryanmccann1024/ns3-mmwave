# P0 Baseline Implementation Audit

Phase: P0 — trustworthy baseline
Plan: `docs/rl-program/p0-baseline/baseline-implementation-plan.md`
Status: **S0, H0, H0A, S1–S7, and the approved R1 code/evidence repairs (including H0B) are complete. H1 remains human-only and unsatisfied (B1). The existing R1 charter is RETURN_TO_IMPLEMENTER; fresh R1, Tester, final Reviewer, and Git/PR remain. P0 is not complete.**

## Files changed

Complete list of every durable project file created or modified by S0–S7 and
the later human-approved workflow correction and R1 repairs.
Files whose status begins "S1"–"S7" were changed in this implementation pass;
the earlier S0/H0A entries are retained. H0/H0A also created only disposable,
ignored run evidence under `outputs/p0-regression/`. The per-step sections
below (S1–S7) explain the initial changes; section 11 records every later repair.

| File | Status |
| --- | --- |
| `docs/rl-program/p0-baseline/baseline-implementation-audit.md` | new (this file) |
| `docs/rl-program/p0-baseline/baseline-implementation-plan.md` | human-approved H0A, workflow, and R1 repair amendments; current status corrected |
| `scripts/validation/regression_check.py` | new |
| `inputs/baselines/p0-jammer-smoke/run.ini` | new |
| `inputs/baselines/p0-jammer-smoke/nodes.json` | new |
| `inputs/baselines/p0-jammer-smoke/jammers.json` | new |
| `tests/fixtures/regression/p0/*.json` | six H0 snapshots plus H0A manifest; unchanged in S1–S7, then approved H0B positions-only repair and snapshot-hash update (section 11) |
| `sim.cc` | S1/S2: CLI band override before validation, `cfg.band` to `LinkEvaluator`, one `mean_sinr` deprecation warning |
| `src/domain/sim-config.h` | S1/S2: `SimConfig.band`/`band_source`, `RlConfig.reward_type_alias`, corrected reward table |
| `src/config/config-loader.cc` | S1/S2: read `[channel] band`; normalize `mean_sinr` → `all_links_los` |
| `src/config/config-validator.cc` | S1/S2: validate `channel.band`; reward set `{throughput, all_links_los}`; `z_min < z_max` |
| `src/cli/cli-parser.h` | S1: `CliArgs.band` empty by default; doc table `--band` row |
| `src/cli/cli-parser.cc` | S1: validate `--band` only when supplied; help text |
| `src/io/run-logger.h` | S1/S2: CLI override lines, band/reward/jammer provenance, per-jammer lines |
| `src/rl/rl-bridge.cc` | S2: reward branch renamed `all_links_los` (arithmetic unchanged); EOF/malformed → Stay + one warning |
| `inputs/baselines/rl-test/run.ini` | S2: explicit `band = mmwave`, `reward_type = all_links_los`, `z_min`/`z_max` |
| `tests/unit/config/config-validator-test.cc` | S1/S2: three new groups (band, reward, z-bounds), 15 checks |
| `inputs/baselines/p0-smoke/run.ini` | S3: new RL/CLI smoke scenario |
| `inputs/baselines/p0-smoke/nodes.json` | S3: new (identical nodes to `p0-jammer-smoke`) |
| `tests/integration/cli-integration-test.sh` | S3: path/binary/library-path repair, tests 4–6 corrected, tests 7–8 added |
| `scripts/sweep/runner.py` | S4: captured output → `console.log`; manifest `console_log`/`output_dir` |
| `scripts/validation/run_batch.py` | S4: `console.log`; optional `--band`; manifest `band_override`/`console_log` |
| `scripts/validation/build_config_files.py` | S4: `_create_ini` writes `[channel] band` |
| `scripts/rl/__init__.py` | S5: correct, guarded Gym registration |
| `scripts/rl/env/mesh_env.py` | S5: episode directories, seed resolution, band forwarding, diagnostics, `rl_episode.json` |
| `scripts/rl/train.py` | S5: usage/argument order, `--band`, seed resolution, overwrite refusal, `train_manifest.json` |
| `requirements.txt` | S6: new, eight pinned direct dependencies |
| `.gitignore` | S6: new (`.venv/`, `.pytest_cache/`) |
| `scripts/rl/bootstrap_venv.py` | S6: new venv bootstrap |
| `scripts/rl/tests/fake_sim.py` | S6: new fake simulator |
| `scripts/rl/tests/test_mesh_env.py` | S6: new, five contract groups (13 items); R1 adds completion/interruption and inline-comment checks (16 RL items total) |
| `scripts/validation/tests/test_regression_check.py` | approved R1 repair: new, six focused items for metadata CSVs, coordinate mismatch, unattended stdin, and loader paths |
| `README.md` | S7: see section S7 |
| `inputs/README.md` | S7: see section S7 |
| `scripts/validation/README.md` | S7: see section S7 |
| `TODO.md` | S7: see section S7 |
| `docs/claude/README.md` | S7 plus human-approved post-S7 workflow correction; see section 10.8 |
| `docs/claude/ORCHESTRATOR_PROMPT.md` | new in human-approved post-S7 workflow correction; replaces redundant `docs/ORCHESTRATION.md` |
| `docs/claude/IMPLEMENTER_PROMPT.md` | human-approved post-S7 workflow correction; reusable bounded-worker contract |
| `docs/claude/REVIEWER_PROMPT.md` | S7: see section S7 (user-owned untracked file, narrowly patched) |
| `docs/claude/TESTER_PROMPT.md` | S7: new |

## 1. Starting state

| Item | Value |
| --- | --- |
| Branch | `arpo-main` |
| HEAD | `a4e700d9947db57d06ade3ce391425681a3c2746` |
| `git status --short` (before S0) | ` M CLAUDE.md`, `?? docs/ORCHESTRATION.md`, `?? docs/claude/`, `?? docs/rl-program/` |
| C++ compiler | Apple clang 21.0.0 (clang-2100.1.1.101), target `arm64-apple-darwin25.6.0` |
| `clang++` | identical to `c++` (same Xcode toolchain, same version string) |
| Python | 3.11.9 |
| Kernel | `Darwin 25.6.0`, `xnu-12377.161.13~4/RELEASE_ARM64_T6000`, arm64 |
| OS | macOS 26.6.1 (build 25G76) |
| Existing binary | `/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/scratch/mesh-sim/ns3.42-sim-debug` **exists** (2,183,600 bytes, dated May 19 12:33). It was **not executed** during S0. |

The Scout's recorded starting state is confirmed unchanged: `CLAUDE.md` is
user-modified, and `docs/ORCHESTRATION.md`, `docs/claude/`, and
`docs/rl-program/` are untracked user work. All four must be preserved; S0
touched none of them except to add this audit under `docs/rl-program/`.

Note: the existing binary predates HEAD by months. It is the current build
artifact but is not proof of a current-source build. H1 replaces it.

## 2. Baseline `make test` results (before any S0 file was created)

Command: `cd tests && make test`
Full log: scratchpad `baseline-make-test.log` (not committed).
Result: **exit 2 — pre-existing failures.**

`tests/Makefile`'s `test` target iterates `UNIT_DIRS` with `|| exit 1`, so the
run stops at the first failing suite. `unit/config` failed, and `unit/eval`,
`unit/routing`, and `unit/traffic` were therefore never reached by `make test`.
Each remaining suite was then run individually (`make -C <dir> test`) to obtain a
complete baseline.

| Suite | Result | Failing test names |
| --- | --- | --- |
| lint (clang-tidy) | "Lint passed." | Advisory only — the Makefile pipes through `|| true`, so lint cannot fail the run. Many `readability-braces-around-statements` warnings are emitted. |
| `unit/config` | **36 passed, 2 failed** | `valid config should pass`, `gateway with valid node ID accepted` |
| `unit/eval` | **156 passed, 2 failed** | `table clamps at highest MCS`, `mcs_index at 50 dB clamps to 14` |
| `unit/routing` | 42 passed, 0 failed | none |
| `unit/traffic` | 32 passed, 0 failed | none |

Four pre-existing failures total. Per the plan they were **not** investigated or
fixed in S0; they are recorded here as the before-state against which S1–S7 must
be compared. The plan's acceptance gate (section 1, item 1) requires the
Reviewer to confirm these same four failures — and no others — after the P0
edits.

This is the first reproduction of the "two configuration-test failures" the
Scout could not verify (scout report section 11): they are real, and there are
two additional eval failures the earlier reports did not mention.

The suite compiles, so plan stop condition 14.1 is not triggered.

## 3. S0 implementation

### 3.1 `inputs/baselines/p0-jammer-smoke/nodes.json`

Three drone peers per plan S3: `node-a` at (0, 0, 10) `fixed`, `node-b` at
(100, 0, 10) `fixed`, `relay` at (50, 50, 10) `constant_velocity` with zero
initial velocity.

Key spellings verified against `src/config/config-loader.cc` `parseNodeSpec`
(lines 25-87) and `src/config/config-validator.cc` (lines 81-124, 192-196):

| Key | Verified spelling | Note |
| --- | --- | --- |
| node type | **`node_type`**, not `type` | `config-loader.cc:32`; validator allows `drone`, `vehicle`, `pedestrian` (`config-validator.cc:194-195`) |
| role | `role` = `"peer"` | `config-loader.cc:30`; `inputs/CLAUDE.md` requires `peer` for every node |
| mobility | `mobility` = `"fixed"` / `"constant_velocity"` | `config-loader.cc:31`; validator allows `fixed`, `constant_velocity`, `random_walk`, `waypoint` (`config-validator.cc:83-84`) |
| position | `position` object with `x`, `y`, `z` | `config-loader.cc:34-40` |
| velocity | `velocity` object with `vx`, `vy`, `vz` | `config-loader.cc:42-48` |

The file matches the shape of `inputs/baselines/rl-test/nodes.json` exactly,
which is the only committed fixture that uses `constant_velocity`.

### 3.2 `inputs/baselines/p0-jammer-smoke/run.ini`

Values are exactly as the plan's S3 fixture spec requires. A six-line header
comment states the purpose. Choices that needed verification:

- **`band = sub-6` in `[channel]` is not parsed by the current binary.**
  `config-loader.cc` never reads a `band` key, and `src/util/ini-parser.cc`
  builds a plain `section -> key -> value` map that is only ever consulted
  through `iniGet`/`iniGetBool` with a default. There is no unknown-key
  rejection anywhere. Writing `band` now is therefore inert for H0 and becomes
  live in S1, exactly as the plan intends.
- **`reward_type = all_links_los` is not rejected, because RL is disabled.**
  `config-validator.cc:199` guards the whole RL block with
  `if (cfg.rl.enabled)`. With `enabled = false` neither `reward_type`,
  `action_type`, `step_size_m`, the x/y bounds, nor `controlled_node_id` is
  validated. The current validator only accepts `{throughput, mean_sinr}`
  (`config-validator.cc:203-204`), so this fixture would be **rejected** if RL
  were enabled before S2 — which is precisely why the plan disables RL here.
  **Confirmed: the current validator accepts this file as written.**
- **`z_min` / `z_max` are parsed** (`config-loader.cc:311-312`, defaults 0.0 and
  100.0) but are **not validated** — the validator checks only x and y
  (`config-validator.cc:215-218`). The Scout's claim is confirmed; S2 adds the
  missing check.
- **`condition_model = static_los`** is the exact key/value spelling:
  `config-loader.cc:251` reads `[channel] condition_model` (default `auto`) and
  `config-validator.cc:131-132` allows only `auto` and `static_los`. There is no
  `los_model` key.
- **`scenario = RMa`, `channel_model = 3gpp`, `blockage_enabled = false`** mirror
  `inputs/baselines/01-static-los-baseline/run.ini`. RMa is chosen for the same
  reason as the 01 baseline: it gives the flattest, most deterministic
  time-series. The plan does not name a `[channel] scenario` for this fixture;
  this is a documented choice, not a deviation. Allowed values are `UMi`, `UMa`,
  `RMa`, `InH`, `InF` (`config-validator.cc:133-134`).
- **`jammers_file = jammers.json`** is read from `[scenario]`
  (`config-loader.cc:333`), and is optional — an empty value skips jammer
  loading entirely.
- `buildings_file` is present and empty, matching the 01 baseline's style; an
  empty value is a documented no-op (`config-loader.cc:351-352`).

### 3.3 `inputs/baselines/p0-jammer-smoke/jammers.json`

A JSON array with exactly one jammer, no `intervals`, `waypoints`, `velocity`,
or `random_walk`. Key spellings verified against `parseJammerSpec`
(`config-loader.cc:89-162`):

| Field | Key used | Loader line | Default if omitted |
| --- | --- | --- | --- |
| id | `id` | 94 | `""` |
| enabled | `enabled` | 93 | `false` |
| type | `type` | 95 | `constant` |
| target frequency | `target_freq` | 96 | `[]` (matches everything) |
| tx power | `tx_power_dbm` | 97 | 25.0 |
| **antenna gain** | **`tx_array_gain_dbi`** | **98** | 12.0 |
| duty cycle | `duty_cycle` | 99 | 1.0 |
| range | `max_range_m` | 100 | 0.0 (unlimited) |
| beamwidth | `beamwidth_deg` | 101 | 360.0 |
| azimuth | `azimuth_deg` | 102 | 0.0 |
| zenith | `zenith_deg` | 103 | **0.0** |
| position | `position` `{x, y, z}` | 105-111 | (0, 0, 0) |

`zenith_deg = 90.0` is written explicitly rather than relying on the loader
default of 0.0. The default points the cone straight up; 90 is horizontal. It is
immaterial here because `beamwidth_deg = 360.0` means omnidirectional
(`jammer-model.cc` `InBeam` treats beamwidth >= 360 as omni), but writing it
explicitly avoids depending on an unresolved default.

Validator checks this fixture satisfies (`config-validator.cc:241-286`): type is
one of `{constant, random}`; `duty_cycle` is in [0, 1]; `beamwidth_deg` is in
(0, 360]; no intervals to order-check; random-walk bounds are only required when
`type == "random"`, which this jammer is not.

**Frequency-match verification.** `LinkEvaluator::Configure` sets
`m_frequencyHz = cfg.channel.frequency_ghz * 1e9` and passes it to
`JammerModel::Configure` (`link-evaluator.cc:60, 86`), which stores
`m_carrierMhz = carrierHz / 1e6` (`jammer-model.cc:35`). With
`frequency_ghz = 2.4` the carrier is exactly **2400.0 MHz**.
`JammerModel::InBand` (`jammer-model.cc:100-114`) applies the single-entry spot
rule when `target_freq.size() == 1`:
`abs(m_carrierMhz - target_freq.front()) <= 2.5`. Here that is
`abs(2400.0 - 2400.0) = 0.0 <= 2.5` — **the jammer matches the carrier**, with
the full 2.5 MHz margin to spare.

**Band gating.** `m_computeInterference = (band == "sub-6")`
(`link-evaluator.cc:63`), and jammer power is only summed when that flag is set
and a jammer is active (`link-evaluator.cc:165-171`). So this fixture is
expected to show jammer effect under `--band=sub-6` and none under
`--band=mmwave` — the A/B contract S3 will assert. No jammer physics was
inspected for correctness or changed; per plan section 3.2 the current
calculations are the accepted regression baseline.

### 3.4 `scripts/validation/regression_check.py`

New standard-library-only utility implementing plan section 3.8. Imports:
`argparse`, `configparser`, `csv`, `hashlib`, `json`, `math`, `os`, `shutil`,
`subprocess`, `sys`, `pathlib`. **No** simulator/project imports, **no** pandas,
**no** matplotlib. Runnable both as `python3 -m scripts.validation.regression_check`
from the mesh-sim root and as a plain script path.

**Verified CLI flag spellings** (from `src/cli/cli-parser.cc:24-53`): the
simulator accepts `--run-config`, `--positions-override`, `--seeds`, `--seed`,
`--run-id`, `--output-dir`, `--debug-links`, `--rl-mode`, `--band`. Both
`--seed` (singular int override) and `--seeds` (comma list) exist; `--seed` was
used because the plan's H0 captures name a single seed and
`ResolveSeeds` prefers `--seeds` over `--seed` over `[scenario] seed`
(`cli-parser.cc:94-105`). The exact argument vector the utility builds is:

```text
[<sim_binary>, --run-config=<abs run.ini>, --band=<band>,
 --seed=<int>, --output-dir=<abs out>]
```

`capture` behavior:

- Sets `DYLD_LIBRARY_PATH` and `LD_LIBRARY_PATH` to `<ns3root>/build/lib`
  **prepended** to any existing value, mirroring `scripts/sweep/runner.py:233-237`.
  `ns3root` is derived by walking up from this file to the directory containing
  `sim.cc` (the mesh-sim root, as `runner.py:95-100` does) and taking two
  parents, matching `runner.py:234`.
- Creates `--out`, and refuses to run when `<out>/seed-<seed>/summary.json`
  already exists unless `--force`. Also refuses to overwrite an existing
  `--snapshot` without `--force`.
- Captures the child's stdout+stderr to **`<out>/console.log`**, never
  `run.log`, which the simulator owns. This anticipates the same rename S4
  applies to the sweep and validation runners.
- Prints the full command before running. On a nonzero exit it prints the exit
  code plus the last 40 lines of `console.log` to stderr and exits with the
  child's code.
- With `--snapshot`, builds and writes the normalized snapshot
  (`json.dumps(indent=2, sort_keys=True)`), creating parent directories.

Normalized snapshot (`snapshot_version = 1`) contains: `family`, `case`, `seed`,
`band`, `sources`, `seed_dir`, `tables`, `tables_missing`, and `summary`.

- `sources` is `run.ini` plus each referenced `nodes_file`, `buildings_file`,
  and `jammers_file` resolved relative to the run.ini directory, each recorded
  as a mesh-sim-root-relative posix path plus SHA-256, sorted by path. Missing
  or empty entries are omitted. The ini is parsed with `configparser`
  (`allow_no_value=True`, `strict=False`, `interpolation=None`,
  case-preserving `optionxform`). Inline comments are stripped by cutting at the
  first `#` or `;`, which mirrors `src/util/ini-parser.cc:29-38` exactly — the
  C++ parser cuts at the first occurrence of either character anywhere on the
  line, with no whitespace requirement.
- `tables` covers `positions.csv`, `links.csv`, `rx-power.csv`, `mcs.csv`,
  `flows.csv`, `routes.csv` under `<out>/seed-<seed>/`, as `{"columns": [...],
  "rows": [{col: value}, ...]}` in file order. Cells parse to JSON numbers when
  float-parsable; NaN/inf become the strings `"nan"`/`"inf"`/`"-inf"`; anything
  else stays a string. Absent optional files are listed in `tables_missing`
  rather than failing; a missing `summary.json` or `links.csv` **does** fail.
  Correction: the original S0 parser treated GUI metadata as the positions
  header, so H0 positions coverage was incomplete. Approved H0B now skips only
  leading `#` metadata records and checks the actual seven positions columns;
  section 11 records the repair and evidence rather than treating the original
  captures as correctly normalized.
- `summary` is `summary.json` with every top-level key starting `wall_` removed
  — covering `wall_clock_start`, `wall_clock_end`, and `wall_elapsed_s`, the only
  three the writer emits (`src/io/metrics-writer.cc:145-147`). `scenario`,
  `seed`, `duration_s`, `warmup_s`, `per_node`, `per_flow`, and `network` are
  kept. Inspection of `metrics-writer.cc:135-232` confirms `summary.json`
  contains no absolute paths, so the hygiene self-check below cannot misfire on
  legitimate content.
- A self-check runs on the serialized JSON before it is written and refuses the
  write if it contains the absolute mesh-sim root, the substring `wall_`, or
  `run.log` / `console.log`.

`compare` behavior: builds the candidate's normalized values from the candidate
run directory using the **baseline's** `seed`/`seed_dir`, recomputes each
recorded source digest against the current checkout, then compares table
presence, column lists, row counts, per-row per-column values, and the summary
recursively. Strings must be equal; numbers must satisfy `|a - b| <= atol`
(default `1e-9`, `--atol`); two NaNs are equal; a number/string type mismatch is
a difference. Up to `--max-diffs` (default 20) differences are recorded per
table plus the summary, with total counts always exact. Source-digest mismatches
are reported and **do** count as a mismatch. A JSON report is written with
`--report`. Exit codes: **0** match, **1** mismatch, **2** usage/IO error.

Pure helpers exported for later testing without a binary: `build_snapshot`,
`normalize_summary`, `load_table`, `normalize_value`, `compare_snapshots`,
`compare_source_digests`, `scenario_source_files`, `source_digests`,
`serialize_snapshot`, `check_snapshot_clean`, `mesh_sim_root`.

### 3.5 `tests/fixtures/regression/p0/`

S0 created this as an empty destination without a `.gitkeep`. H0 then populated
it with the six normalized snapshot JSON files listed in section 6. H0A added
`manifest.json`, which records the original clean-build binary hash, Git commit,
build facts, and each case's configuration and snapshot hash. The directory is
now intended tracked regression evidence; raw run trees remain ignored under
`outputs/`.

### 3.6 Approved H0A one-command suite

After H0, the human approved a narrow pre-S1 usability correction. The existing
standard-library utility now provides `verify-suite`. It validates
`manifest_version`, rejects absolute or escaping manifest paths, verifies every
snapshot SHA-256 and duplicated case metadata before launching the simulator,
runs all six cases, invokes the existing normalized comparison for each case,
writes per-case reports plus `suite-report.json`, prints per-case PASS/FAIL and
a final suite result, and exits 0 only when all cases pass.

The suite reports both the baseline and current binary hashes but deliberately
does not require equality: the original hash proves provenance, while a later
post-change binary is expected to have different bytes. Existing `capture` and
`compare` interfaces remain available for single-case capture and diagnosis.

### 3.7 Approved portability and console refinement

The human approved a second narrow pre-S1 refinement after seeing the first
aggregate output. The manifest now labels five tracked-input cases as required
and the ignored local Sherpa case as optional. An available optional case runs
normally and any mismatch fails. If its source is absent, the default suite
prints SKIP, lists the missing paths, and tells the user that the data is not in
Git and to ask the project team or data owner for the approved Sherpa inputs.
`--require-all` converts that missing-data skip into a failure for complete lab
environments.

Successful suite output now shows a short purpose, reference commit/build,
short current-binary fingerprint, one human-labeled row per case, and one final
required/optional/skipped result. Full commands remain in per-case
`console.log`; full hashes and machine-readable results remain in
`suite-report.json`.

The human then approved automatic replacement for repeated suite runs. The
suite requires its output beneath `mesh-sim/outputs/`, rejects the broad
`outputs/` directory and unsafe manifest case names, and deletes only its
manifest-named case subdirectories plus `suite-report.json` before rerunning.
It leaves unrelated sibling outputs and all tracked snapshots/manifests alone.
The lower-level `capture --snapshot` overwrite guard remains unchanged.

## 4. Commands run and results

All commands were run from the mesh-sim root unless noted. Temporary artifacts
live in the session scratchpad; nothing was written under `outputs/` or
`tests/fixtures/regression/p0/`.

| Command | Result |
| --- | --- |
| `git status --short` / `rev-parse HEAD` / `branch --show-current` | recorded in section 1; read-only |
| `c++ --version`, `clang++ --version`, `python3 --version`, `uname -a`, `sw_vers` | recorded in section 1 |
| `ls build/scratch/mesh-sim/` | `ns3.42-sim-debug` present; not executed |
| `cd tests && make test` | exit 2; see section 2 |
| `make -C unit/eval test`, `unit/routing`, `unit/traffic` | 2 failed / 0 failed / 0 failed; see section 2 |
| `python3 -m py_compile scripts/validation/regression_check.py` | OK |
| `python3 -m scripts.validation.regression_check --help` and subcommand help | OK; usage as documented in 3.4 and 3.6 |
| `python3 scripts/validation/regression_check.py --help` | OK (script-path invocation works) |
| `json.load` on `nodes.json` and `jammers.json`; `configparser` on `run.ini` | all parse; run.ini sections `scenario, channel, traffic, routing, rl, output` |
| `capture` against a scratchpad fake binary, `--run-config inputs/baselines/p0-jammer-smoke/run.ini` | wrote `console.log` beside the fake `run.log`, wrote the snapshot; sources listed the three fixture files with relative paths + SHA-256 |
| snapshot hygiene assertions | no `wall_`, no absolute mesh-sim path, no `run.log`/`console.log` in the JSON; `summary` keys = `duration_s, network, per_flow, per_node, scenario, seed, warmup_s` |
| `compare` snapshot vs. the same directory | `MATCH`, exit 0 |
| `compare` after perturbing one SINR by 1e-6 | `MISMATCH: 2 difference(s)`, exit 1, `where = links.csv[row 0].sinr_db` |
| `compare` after perturbing one SINR by ~5e-13 | `MATCH`, exit 0 (within default atol 1e-9) |
| `compare` against a run missing `links.csv` | `Error: Missing required .../links.csv`, exit 2 |
| `compare` against a run missing optional `flows.csv` | `MISMATCH`, exit 1, `flows.csv: baseline='<present>' candidate='<absent>'` |
| `compare` after perturbing one recorded summary value | `MISMATCH`, exit 1, `where = summary.network.mean_sinr_db` |
| `compare` with a tampered baseline source digest | `MISMATCH`, exit 1, `where = sources[inputs/baselines/p0-jammer-smoke/jammers.json].sha256` |
| `capture` re-run over an existing capture without `--force` | refused, exit 2 |
| `capture` against a fake binary exiting 3 | printed exit code and the console.log tail, exited 3 |
| `git status --short` (after S0) | only the pre-existing user paths plus the two new untracked S0 paths |
| H0 six `capture` commands against the clean pre-change binary (human) | all exited 0; six raw summaries and six normalized snapshots produced |
| manifest validation against the six snapshots | PASS; all six snapshot hashes and duplicated metadata match |
| `verify-suite --sim-binary ... --manifest tests/fixtures/regression/p0/manifest.json --out outputs/p0-regression/suite-prechange` | exit 0; every case PASS; final result `SUITE PASS: 6/6` |
| in-memory compile of the amended Python source | PASS; a direct `py_compile` cache write was denied by the narrow session filesystem permission, not by Python syntax |
| manifest escape-path rejection and saved suite-report assertions | PASS; escape rejected, report status PASS, 6/6 cases, baseline/current hash equal |
| initial repeat-output behavior check | correctly refused; the human subsequently approved safe automatic replacement for suite-owned disposable results |
| optional-source classification with a fabricated missing path | PASS; missing local data is distinguished from a changed input before simulation |
| readable `verify-suite ... --out outputs/p0-regression/suite-prechange-readable --require-all` | exit 0; `RESULT: PASS — required 5/5, optional 1/1, skipped 0` |
| isolated missing-Sherpa console test with simulator calls stubbed | default exits 0 with SKIP, missing path, and ask-the-team action; `--require-all` exits 1 |
| output-boundary checks | accepts a nested `outputs/...` suite directory; rejects `.`, `outputs/`, and a path outside the project output tree |
| exact repeat of the user's `suite-user-check` command | previous suite-owned output replaced, exit 0, required 5/5 and optional 1/1 PASS; a temporary unrelated sibling marker was preserved and then removed |

The Implementer did not execute the simulator during S0. The human executed
the six H0 captures and the clean configure/build before H0. Codex executed the
three aggregate H0A checks in this table (`suite-prechange`,
`suite-prechange-readable`, and the repeat of `suite-user-check`) under the
human-approved pre-S1 exception. The human also independently ran the posted
`suite-user-check` command. These historical runs used the pre-change binary;
none constitutes post-change build or regression evidence.

## 5. Commands reserved for the human / Tester

- **H0 completed** — all six `regression_check capture` invocations succeeded
  against the clean pre-change binary. H0A then proved the aggregate verifier
  passes all six cases.
- **H1 remains reserved** — after S1–S7, run
  `./ns3 configure --build-profile=debug -- -DCMAKE_OSX_ARCHITECTURES=arm64`
  and `./ns3 build` from the ns3-mmwave root.
- **T1A / T2–T6** — post-change regression comparison, the CLI integration suite
  (`MESH_SIM_BIN=<BIN> make integration`), the Python contract tests, the
  MaskablePPO smoke, the sweep/validation surfaces, and the legacy-alias check.

The integration suite was not run in S0: it requires the binary, and the Scout
confirmed it is currently broken by its own path calculation
(`tests/integration/cli-integration-test.sh:15, 21-33`), which S3 repairs.

## 6. Baseline binary and snapshot digests

H0 used the clean pre-change binary at
`/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/scratch/mesh-sim/ns3.42-sim-debug`.
Its SHA-256 is
`370d8356186a2b97d988061019cbd8ab4391c191f076da8b559e531854da32d5`.
The absolute path is recorded only in this audit; the tracked manifest stores
the hash and portable build facts. After approved H0B, the current
`manifest.json` SHA-256 is
`74bbf83a09b64b6fe822bfab74ea97f4fe17369635d317b190ed32abe0d2c2eb`.
The pre-repair manifest hash was
`3b08e894f64aeb7f8e89694e51a7ad84e9800e4e7324e858b9281b5ae6742bb4`;
its original bytes and all six original snapshots are preserved under
`outputs/p0-verification/reviewer-fixes/original-snapshots/`.

| Snapshot | SHA-256 |
| --- | --- |
| `tests/fixtures/regression/p0/baseline-static-los.json` | `10e8683c440bc83e5d4d89a7b655cd541745dd2b9fe079e7307877f9245816d5` |
| `tests/fixtures/regression/p0/baseline-building-blockage.json` | `4633c33619210ae9b6e608b0f1917527d05ed4983c18959d3b0acc86d0481bf3` |
| `tests/fixtures/regression/p0/baseline-three-node-relay.json` | `ed8f888924da4acdb0f558b6b76a85713174ae32842c8f8a12921a0aebaba338` |
| `tests/fixtures/regression/p0/sherpa-spring-lake-static.json` | `278fe57b3eb298e5c6a28dd7839d326dfc9b431a9da05680c46ee9b4320d4924` |
| `tests/fixtures/regression/p0/calfex-06-25-1509-1513.json` | `1c9b14f2d77869fa18df48f46f299659317ce3789e469413d78c7f0a24422512` |
| `tests/fixtures/regression/p0/baseline-synthetic-jammer.json` | `39152a1fec6bb0f170840696849eee2732ab264707d91309842d16dda6fb9ab7` |

Current digests of the three S0 fixture files, cross-checked against the
`sources` block of the jammer snapshot H0 produced:

| File | SHA-256 |
| --- | --- |
| `inputs/baselines/p0-jammer-smoke/run.ini` | `bb923178325633632fc4a9841a9fb14e112f8fa6e257bdbb63d3f7ef89129f69` |
| `inputs/baselines/p0-jammer-smoke/nodes.json` | `12fbcb0e17633971114c049e42d36f7b5d3596420e4d6a7221bcb2a6b30ec829` |
| `inputs/baselines/p0-jammer-smoke/jammers.json` | `2a623a4c81b874ec08eb7600dd3d05a36e33174ad589a3d8da64258e7bd4e2fd` |

Per plan S3, the jammer fixture's contents must not change after H0 captures it.

## 7. Plan deviations

**None.** The manifest and aggregate verifier are a human-approved H0A plan
amendment made before S1, not an unapproved deviation. Two choices the original
plan left unspecified are recorded rather than treated as deviations:

1. `[channel] scenario = RMa` for `p0-jammer-smoke` (plan S3 fixes the band,
   frequency, bandwidth and condition model but not the 3GPP scenario). RMa
   mirrors `01-static-los-baseline` and is the most deterministic choice.
2. `tests/fixtures/regression/p0/` was created without a `.gitkeep`; H0 then
   populated it with real snapshot files (section 3.5).

No file outside the approved S0/H0A list was created or modified by the code
change. `CLAUDE.md`, `inputs/custom/`, `inputs/calfex/`, and `data/` were not
modified. H0/H0A wrote only disposable runs beneath the ignored
`outputs/p0-regression/` tree. No repo-wide formatter or `--fix` linter was run.

## 8. Open jammer and data notes

- **TODO-DATA-1 (pending S7).** This checkout contains no EW-trials source CSV
  and no field-generated `jammers.json` under `scratch/mesh-sim/`, confirming
  plan section 3.9. The synthetic `inputs/baselines/p0-jammer-smoke/jammers.json`
  created in S0 is therefore P0's **only** jammer coverage. It must not be
  described as field data or relabeled into the CalFEX or Sherpa families. S7
  records TODO-DATA-1 to identify the owner and location of the real EW trials
  table, how it generates `jammers.json`, and whether the generated input belongs
  under `inputs/calfex/` or stays local.
- The eight jammer-physics questions in plan section 9 remain open and are out of
  scope for S0. S0 changed no jammer physics and inspected the model only to
  confirm key spellings and the 2400 MHz carrier match.

## 9. Git and build confirmation

No Git-mutating command was run in S0. Only `git status --short`,
`git rev-parse HEAD`, and `git branch --show-current` were used, all read-only.
No branch, stage, commit, stash, checkout, reset, or push occurred.

The Implementer ran no prohibited `./ns3` command during S0. Before H0, the
human intentionally ran clean, configure, and build to replace the stale May
binary with a trustworthy pre-change build. H0 and H0A executed that binary;
the resulting hash and evidence are recorded in section 6. H1 remains a second
human build after S1–S7.

---

## 10. S1–S7 implementation record

### 10.1 Process and model routing

The top-level session ran on Fable 5.1, so per the human's model requirement it
coordinated only. All code and documentation edits were made by non-Fable
(Opus) implementer subagents on disjoint file sets: A = S1+S2 (C++ and the
config test), B = S3, C = S4, D = S5+S6, E = S7. No two agents edited the same
file. The coordinating Implementer read every diff, returned two corrections
to agent D (section 10.6), independently re-ran the standalone C++ suite and
the Python suite, re-verified the immutable evidence digests, and wrote this
audit. Two subagents wrote transient audits under `feature-research/`, a path
outside the plan's file set; the coordinator deleted that directory after
folding their content into this document.

### 10.2 S1 — Band configuration and run-log provenance

Decisions implemented (plan 3.1, 3.2, S1):

- `SimConfig.band = "mmwave"`, `SimConfig.band_source = "default"`
  (`src/domain/sim-config.h`, beside `channel`/`mesh`). Band stays a
  categorical switch; nothing derives it from `frequency_ghz`.
- Loader reads `[channel] band` with an empty default; a non-empty value sets
  `band_source = "run.ini"` (`config-loader.cc`). No warning is printed for
  historical scenarios that omit the key.
- `CliArgs.band` default changed from `"mmwave"` to empty ("no override");
  `ParseCommandLine` validates only a supplied value (`cli-parser.h/.cc`).
- `sim.cc` applies the CLI value (`band_source = "cli"`) after the other CLI
  overrides and **before** `ValidateConfig`; `LinkEvaluator::Configure` now
  receives `cfg.band` instead of `args.band`. Precedence is therefore
  CLI > run.ini > legacy default `mmwave`.
- `ValidateConfig` checks `channel.band ∈ {mmwave, sub-6}`; the existing
  `checkOneOf` message lists both valid values.
- `run.log` (`src/io/run-logger.h`) gains, in the existing sections, exactly
  the plan-3.2 entries: `--output-dir`, `--debug-links`, `--rl-mode`, `--band`
  under "CLI overrides"; `band`, `band_source`, `rl.reward_type`,
  `rl.reward_alias`, `jammers.configured`, `jammers.enabled`,
  `jammer_path_enabled` under "Resolved config"; and a "Jammers:" section with
  one line per configured jammer (id, enabled, type, target_freq_mhz,
  tx_power_dbm, tx_array_gain_dbi, duty_cycle, max_range_m, beamwidth_deg,
  azimuth_deg, zenith_deg, motion=waypoints|velocity|static). Only existing
  `JammerSpec` fields are used; no bandwidth/rx-gain/overlap/disconnection
  fields were invented. The seed vector already logged is unchanged; no
  singular seed field was added. `run.log` remains at the invocation root.
- No jammer physics, endpoint, frequency, antenna, duty-cycle, mobility, or
  link-disconnection code was touched (`src/eval/`, `src/jammer/`,
  `src/setup/` are unmodified — see `git status` in 10.9).

### 10.3 S2 — Reward and action correctness

- `RlConfig.reward_type_alias` added; loader normalizes `mean_sinr` →
  `all_links_los` and records the alias. Validator accepts only
  `{throughput, all_links_los}` (a raw `mean_sinr` reaching the validator
  without the loader is rejected — covered by a test).
- `sim.cc` prints one deprecation warning to stderr after validation:
  `Warning: [rl] reward_type 'mean_sinr' is deprecated; use 'all_links_los'.`
- `rl-bridge.cc`: the branch condition is now `"all_links_los"`; the loop
  body and `(count > 0 && losCount == count) ? 1.0 : -1.0` are byte-identical
  (Reviewer check: `git diff src/rl/rl-bridge.cc`). The stale `// TODO` above
  `ComputeReward` became a one-line description. The reward table in
  `sim-config.h` now describes what the code computes.
- `ReadAction`: closed stdin or discarded JSON sets `m_lastDiscreteAction = 6`
  (Stay) instead of 0 (−X), with one stderr warning per process via a
  function-local `static bool warned` (rl-bridge.h is outside the plan's file
  set, so no member was added). Continuous-mode parsing is unchanged.
- `z_min < z_max` validated beside x/y.
- `inputs/baselines/rl-test/run.ini`: `band = mmwave`,
  `reward_type = all_links_los`, `z_min = 0.0`, `z_max = 100.0` (the C++
  defaults, so behavior is unchanged).

Config test additions (`tests/unit/config/config-validator-test.cc`, three
groups, 15 checks, loader-backed via a temp scenario directory): missing band
→ `mmwave/default`; `band = sub-6` → `sub-6/run.ini`; invalid band rejected
naming both valid values; `mean_sinr` → `all_links_los` + alias;
`all_links_los` unchanged, no alias; unknown reward rejected; raw `mean_sinr`
rejected by the validator; inverted z rejected; valid z accepted. Positive
assertions check absence of the specific error rather than `r.ok()` because
`makeValid()` fails for the pre-existing reason in 10.10.

### 10.4 S3 — Smoke fixtures and CLI integration

- `inputs/baselines/p0-smoke/{run.ini,nodes.json}` created exactly per plan
  S3 (RL enabled on `relay`, `band = mmwave`, 28 GHz, `all_links_los`,
  `step_size_m = 5`, bounds x 0..100 / y −50..100 / z 0..50, `static_los`,
  RMa). `nodes.json` is byte-identical to the jammer fixture's.
- `p0-jammer-smoke/*` untouched; digests re-verified (section 10.8).
- `tests/integration/cli-integration-test.sh`: `SCRIPT_DIR`/`MESH_SIM_DIR`/
  `NS3_ROOT` resolved correctly; binary from `MESH_SIM_BIN`, then optional
  positional, then exactly one `build/scratch/mesh-sim/ns3*-sim-*` match
  (zero or several → error listing candidates); `DYLD_LIBRARY_PATH`/
  `LD_LIBRARY_PATH` prepended, existing values preserved; fixture-existence
  preflight before tests 4–8; tests 1–3 unchanged; test 4 requires nonzero
  exit **and** `invalid seed value` on stderr; test 5 requires
  `positions-override file not found`; test 6 runs `p0-smoke` with
  `--output-dir` (stdin `/dev/null`, stdout discarded because RL is enabled)
  and checks `run.log`, `seed-1/summary.json`, `seed-1/links.csv`; test 7
  (new) `--band=sub-6` over the `mmwave` scenario → `run.log` has
  `band = sub-6` and `band_source = cli`; test 8 (new) jammer scenario under
  `sub-6` then `mmwave` with seed 1 → `jammer_path_enabled = true`/`false`
  respectively and ≥1 matched `links.csv` row (keyed on
  `time_s,node_a,node_b`) whose `sinr_db` differs; same key set required.
  Eight tests total. Deviation: `((PASS++))` → `PASS=$((PASS + 1))`, because
  under `set -e` the former returns status 1 when the counter is 0 and would
  abort at the first pass.
- The integration suite was **not** run against a real binary (prohibited;
  the current binary predates S1). Agent B exercised the script's logic
  against a throwaway fake binary in the scratchpad (8/8, and 7/8 with a
  fake that emits identical SINR across bands, proving test 8 is not
  vacuous). That is a dry run, not verification.

### 10.5 S4 — Launcher and output consistency

- `scripts/sweep/runner.py`: captured output → `<point>/console.log`;
  manifest point entries (executed and `--resume`-skipped) gain
  `console_log` and `output_dir`.
- `scripts/validation/run_batch.py`: captured output → `console.log`;
  optional `--band {mmwave,sub-6}` appended as `--band=<v>` only when given;
  `batch_manifest.json` gains `band_override` (null when absent) and per-run
  `console_log`; docstrings updated.
- `scripts/validation/build_config_files.py`: `_create_ini(..., band, ...)`
  writes `band` as the first `[channel]` key. Nothing under `inputs/calfex/`
  was regenerated.
- `scripts/validation/regression_check.py`: **unchanged**. It already writes
  `console.log`, ignores both logs in comparison, and imports only stdlib.
  All approved H0A behavior (five required + one optional case, SKIP text,
  `--require-all`, console format, JSON report, safe replacement of
  suite-owned output, `outputs/` containment, immutable evidence) is preserved.
- No sweep-specific band argument: `scripts/sweep/config.py` parses
  `[sweep.override]`/`[sweep]` keys generically and `ini_writer.write_point_ini`
  applies them with `cfg.set(section, key, value)`, so `channel.band` reaches
  the generated point `run.ini` like any other key (confirmed by a dry run).

### 10.6 S5 — RL lifecycle and training manifest

- `scripts/rl/__init__.py`: `mesh_sim/MeshEnv-v0` →
  `scripts.rl.env.mesh_env:MeshRlEnv`, guarded by a registry check.
- `MeshRlEnv(sim_binary, run_config, seed=None, output_dir, band=None,
  render_mode=None)`: `output_dir` required; seed resolved from the explicit
  argument (`cli`) else `[scenario] seed` (`run.ini`), else `ValueError`
  naming both options — the Python-only default 42 is gone. Each `reset()`
  finalizes any running episode and allocates the next unused
  `episode-NNNN/` (max+1, `mkdir(exist_ok=False)` with retry); the simulator
  receives that directory via `--output-dir`, so `run.log`, `inputs/`, and
  `seed-<seed>/` land inside it; `sim_stderr.log` is always captured there;
  `--band=<v>` is appended only when `band` is given; `DYLD_LIBRARY_PATH`/
  `LD_LIBRARY_PATH` are prepended with `<ns3>/build/lib` for the child.
  `rl_episode.json` holds exactly: `manifest_version`, `episode`, `seed`,
  `seed_source`, `command` (list), `started_at`, `ended_at`, `status`,
  `exit_code`, `steps`, `cumulative_reward`. The episode index never feeds
  the seed. Premature exit → `RuntimeError` with exit code, command, and the
  last 40 stderr lines; invalid JSON → `RuntimeError` with the 1-based message
  line number and the offending line truncated to 200 chars. Cleanup closes
  stdin, waits 2 s, `terminate()`, waits 2 s, `kill()`. Bound defaults now
  equal `RlConfig` (x −1000..2000, y −1000..1000, z 0..100) and z is always
  masked. Observation docstring corrected; continuous actions stay 2-D with a
  one-line "unverified for P1" note.
- `train.py`: docstring usage corrected (globals before `m-ppo`); global
  `--band`; `m-ppo --seed` default `None` → `[scenario] seed`; refuses an
  output directory that already holds `train_manifest.json` or
  `maskable_ppo_mesh.zip`; `train_manifest.json` written before training
  with `manifest_version = 1`, status, timestamps, absolute simulator/scenario
  paths, `algorithm = MaskablePPO`, seed + `seed_source`, band or null, all
  exposed MaskablePPO hyperparameters, output root, Python version, and
  direct package versions; updated to `completed` + `model_path` or `failed`
  + bounded error. Model basename remains `maskable_ppo_mesh`.
- Two coordinator-requested corrections, both applied and re-tested:
  (1) `train.py` no longer calls `env.reset(seed=...)`; it constructs the env
  with `seed=None` when the seed came from `run.ini` so episode manifests carry
  the same `seed_source` as the training manifest; (2) `MeshRlEnv.reset()`
  relabels `seed_source = "gym"` only when the incoming seed **differs** from
  the resolved value, because SB3's `DummyVecEnv` re-issues `reset(seed=<same
  seed>)`. A manual fake-simulator training run then showed every
  `episode-000N` with `seed=1, seed_source=run.ini`, matching
  `train_manifest.json`.
- Small addition beyond the letter of the plan: `_send_action` swallows
  `BrokenPipeError`/`OSError` so a dead child is reported by `_read_message`
  with the required diagnostics rather than an opaque broken-pipe traceback.

### 10.7 S6 — Python environment and focused tests

- `requirements.txt` (direct deps only, pinned to what was installed and
  tested on this machine; header states it is not a universal lock):
  gymnasium 1.3.0, numpy 2.4.6, stable-baselines3 2.9.0, sb3-contrib 2.9.0,
  torch 2.14.0, pandas 3.0.5, matplotlib 3.11.2, pytest 9.1.1. Interpreter:
  Python 3.11.9 (macOS arm64). No `pip freeze` lock was committed.
- `.gitignore` (new, mesh-sim root): `.venv/`, `.pytest_cache/`. The second
  entry is a small addition to the plan's `.venv/` so pytest's cache does not
  appear as untracked.
- `scripts/rl/bootstrap_venv.py`: `[--venv PATH] [--check]`; requires
  ≥ 3.10; creates the venv with `venv`; installs `requirements.txt` unless
  `--check`; imports every direct dependency inside the venv and prints
  `name==version`; nonzero exit names the failing command/import; prints
  POSIX and Windows activation lines with an explicit "ns-3 is not supported
  on Windows" note. Stdlib only.
- `scripts/rl/tests/fake_sim.py`: stdlib; real flag spellings; unknown flags
  rejected; writes root `run.log` + `seed-N/{summary.json,links.csv}`; emits
  the tick-0 message, then reads actions; modes `normal|exit3|malformed` via
  `FAKE_SIM_MODE`.
- `scripts/rl/tests/test_mesh_env.py`: five contract groups, 13 items after
  parameterization: (1) two resets → distinct episode dirs, fixed seed
  recorded; (2) `reset(seed=7)` recorded and reused, `reset(seed=<resolved>)`
  keeps its source, missing seed rejected; (3) exit-3 and malformed-JSON
  diagnostics; (4) `--band` forwarding/omission, C++ bound defaults, z mask;
  (5) `gymnasium.make` resolves, CLI help order, tiny fake-simulator training
  produces `train_manifest.json` + `maskable_ppo_mesh.zip`, every episode's
  provenance matches, rerun refused. No `__init__.py` was added under
  `scripts/rl/tests/`. Tests write only under pytest's `tmp_path`.

### 10.8 S7 — Documentation

Documentation-only; no runtime behavior changed. Every command, path,
option, and default was verified by agent E against the post-S6 source, and
re-read by the coordinator.

- `README.md`: kept `@mainpage`, Build, the existing run/sweep commands,
  Documentation, and About verbatim. Added: Python environment (one bootstrap
  command, venv pytest, Windows interpreter path, "pins, not a lock"); a
  one-line note that `--band` is optional; Band selection (values, CLI >
  run.ini > default, `band`/`band_source` in `run.log`, `sub-6` is the only
  jammer-active mode, categorical not derived from frequency); RL reward
  types (`throughput`, `all_links_los`, deprecated `mean_sinr` alias with one
  warning and `rl.reward_alias`, z-bound validation); the MaskablePPO smoke
  command exactly as plan section 6; sweep/validation band examples using the
  existing generic matrix; an output-locations table (`run.log`,
  `console.log`, per-seed files, episode/training manifests, model); a Verify
  section (`make test`, `MESH_SIM_BIN=<BIN> make integration`, `verify-suite`).
- `inputs/README.md`: `[channel] band` in the layout and one resolution
  sentence; a Scenario families table (`baselines/` tracked incl. the two P0
  fixtures, `custom/sherpa/` ignored/read-only/ask-the-team, `calfex/`
  tracked, `sweeps/`); Sherpa vs CalFEX distinction; `data/` contents
  git-ignored (root `.gitignore` `scratch/mesh-sim/data/*` — coordinator
  corrected agent E's "not committed" wording after verifying with
  `git check-ignore`), `outputs/` disposable, `tests/fixtures/regression/p0/`
  normalized snapshots only. "How to run" and "Design philosophy" untouched.
- `scripts/validation/README.md`: one "Regression suite" section — the
  single `verify-suite` command, pre-simulation integrity check, five
  required / one optional case, the verbatim `missing_help` SKIP text,
  `--require-all`, `--out` containment and suite-owned replacement rules,
  exit codes 0/1/2, plus `console.log`/`--band`/`[channel] band` launcher
  notes. Existing guide preserved.
- `TODO.md`: forward pointer to `baseline-completion-report.md`; reward line
  names `all_links_los` (alias noted); 3-D movement paragraph corrected
  (discrete already has ±Z; continuous still 2-D); TODO-RL-SEEDS-1; a
  "Jammer model decisions (P0, unresolved)" section with the eight plan-9
  questions as TODO-JAM-1..6 plus TODO-BAND-1/2, each with owner and status;
  TODO-DATA-1 under "Data provenance" (no EW-trials table or field
  `jammers.json` present; `make_jammers.py` identified as the generator; the
  synthetic fixture is not field data). No separate jammer or data file.
- `docs/claude/TESTER_PROMPT.md` (new): execution-only Tester role modeled on
  `REVIEWER_PROMPT.md` (BLOCKED-not-PASS, no builds, no Git, no deferrals,
  results written to `<phase-dir>/…-test-results.md`).
- `docs/claude/README.md` and `docs/claude/REVIEWER_PROMPT.md`: Tester
  row/link and runtime-phase handoff (Reviewer writes the charter, Tester
  writes results back, Reviewer writes the completion report, and only Git/PR
  mutates Git). `docs/claude/TESTER_PROMPT.md` and these S7 edits were
  intentional plan work, not unrequested worker changes.
- Human-approved post-S7 correction: removed the redundant untracked
  `docs/ORCHESTRATION.md`; added `docs/claude/ORCHESTRATOR_PROMPT.md`; and
  updated `docs/claude/README.md` plus `docs/claude/IMPLEMENTER_PROMPT.md` to
  retain the Fable-coordinator/parallel-Opus pattern for substantial approved
  implementation stages. Delegation is bounded to non-overlapping worker
  slices; one Orchestrator integrates them and maintains the one audit.
  `docs/claude/REVIEWER_PROMPT.md` was also clarified so its runtime variant
  may write exactly one charter or completion artifact without contradicting
  the general prohibition on implementation edits. Reviewer and Tester remain
  separately human-started, independent, non-delegating roles. The
  documentation-only workflow and its `review-research/` paths remain
  available.

Claims deliberately left qualified: `make test`/`make integration`/
`verify-suite`/the MaskablePPO smoke are documented as commands whose targets
exist, not as executed here; `baseline-completion-report.md` is linked before
it exists. Noted but not changed (out of S7 scope): TODO.md's "Continuous
Desired-Position Actions" paragraph still says "left/right/stay", and
`inputs/README.md` still labels baselines "numbered 01-16".

### 10.9 Commands run in S1–S7 and approved workflow cleanup

All from the mesh-sim root unless noted. PASS/FAIL below are the coordinator's
own re-runs unless attributed to a subagent.

| Command | Result |
| --- | --- |
| `make -C tests/unit/config clean test` (agent A, then coordinator via `cd tests && make test`) | **51 passed, 2 failed**; failing: `valid config should pass`, `gateway with valid node ID accepted` (both pre-existing; 15 new checks pass). Baseline was 36/2. |
| `cd tests && make test` | lint "Lint passed." (advisory `readability-braces-around-statements` warnings only); stops at `unit/config` exit 1 as it did at baseline |
| `make -C tests/unit/eval test` | **156 passed, 2 failed**; `table clamps at highest MCS`, `mcs_index at 50 dB clamps to 14` (pre-existing) |
| `make -C tests/unit/routing test` | 42 passed, 0 failed |
| `make -C tests/unit/traffic test` | 32 passed, 0 failed |
| agent A: `-fsyntax-only` of `rl-bridge.cc` and `sim.cc` against `build/include`; `cli-parser.cc` against a stub `ns3/command-line.h`; `run-logger.h` compiled and executed in a throwaway TU | clean; sample `run.log` matched the section-3.2 layout. Not a link or run of the simulator. |
| `python3.11 scripts/rl/bootstrap_venv.py` (agent D) | venv created at `.venv`, all installs succeeded; `--check` exit 0 |
| `.venv/bin/python -m pytest scripts/rl/tests -q` (coordinator) | **13 passed** in 5.64 s |
| `.venv/bin/python -m py_compile` on all changed Python files (agent D); `python3 -m py_compile` on S4 files (agent C) | OK |
| `python3 -m scripts.validation.run_batch --help`; `... --scenarios-dir inputs/baselines --only p0-jammer-smoke --sim-binary /bin/true --dry-run` | `--band` shown; dry run exit 0 |
| agent C: `_run_one` with `/bin/echo`, band None / `sub-6` | `console.log` written; `--band=sub-6` present only when supplied |
| agent C: `_create_ini(..., band="sub-6")` into scratchpad | `[channel]` starts with `band = sub-6` |
| agent C: `python3 -m scripts.sweep.cli --config <scratch sweep.ini> --dry-run` with `channel.band` override + dimension | two points listed (`mmwave`, `sub-6`); nothing written under `outputs/` |
| `bash -n tests/integration/cli-integration-test.sh` (agent B) | OK; shellcheck not installed |
| agent B: integration script against a scratchpad fake binary | 8/8 (dry run only, **not** real verification) |
| `shasum -a 256 tests/fixtures/regression/p0/*.json inputs/baselines/p0-jammer-smoke/*` | all ten digests equal the values in section 6 |
| `git status --short --untracked-files=all`, `git diff --stat` (rerun after approved workflow cleanup) | 22 tracked files modified (including the user's own `CLAUDE.md` +30 lines) and 30 untracked files. The untracked set includes pre-existing user workflow/phase documents as well as P0 additions; see 10.11. `git diff --check` is clean. |

Not run (prohibited or reserved): `./ns3 configure/build/run/clean`; any
real-binary execution (integration suite, verify-suite post-change, MaskablePPO
real smoke, sweep/validation real runs, legacy-alias run); H1; T1A–T6.
The unchanged pre-S1 binary was **not** used to claim anything about
post-change behavior.

### 10.10 Known baseline failures — status unchanged

The same four failures exist after S1–S7 and no new failure appeared:

| Suite | Failing test | Status |
| --- | --- | --- |
| unit/config | `valid config should pass` | unchanged |
| unit/config | `gateway with valid node ID accepted` | unchanged |
| unit/eval | `table clamps at highest MCS` | unchanged |
| unit/eval | `mcs_index at 50 dB clamps to 14` | unchanged |

Root cause of the two config failures (read-only investigation, not fixed):
`NodeSpec::node_type` has no default initializer (`src/domain/node-spec.h`),
the test's `makeValid()` never sets it, and `ValidateConfig` requires
`drone|vehicle|pedestrian`, so every `makeValid()` config carries two
`node_type: unknown value ''` errors; only the two tests asserting bare
`r.ok()` fail. Production is unaffected because the loader defaults
`node_type` to `"drone"`. Whether an unset `node_type` should be legal is a
behavior decision outside P0. The eval failures were not investigated.

### 10.11 Preserved behavior, datasets, and user-owned files (S1–S7)

- Jammer SINR/propagation/endpoint/frequency/overlap/antenna/duty-cycle/
  mobility/disconnection code: unmodified.
- Reward arithmetic: unmodified (name/alias only).
- CSV and `summary.json` schemas: unmodified.
- `inputs/custom/`, `inputs/calfex/`, `data/`, `outputs/`: not modified,
  reorganized, regenerated, deleted, or tracked. No file was written under
  `outputs/` by S1–S7.
- Six snapshots, `manifest.json`, `p0-jammer-smoke/*`: byte-identical during
  S1–S7. The later approved H0B exception changes only snapshot positions and
  manifest snapshot hashes; `p0-jammer-smoke/*` remains byte-identical.
- `regression_check.py`: unchanged from the approved H0A state.
- `CLAUDE.md`: the user's own uncommitted edit (+30 lines) is untouched.
- The pre-existing untracked workflow documents were preserved except for the
  explicit S7 handoff edits and the human-approved post-S7 consolidation in
  section 10.8. `docs/ORCHESTRATION.md` was replaced by
  `docs/claude/ORCHESTRATOR_PROMPT.md`; `docs/claude/IMPLEMENTER_PROMPT.md`,
  `README.md`, `REVIEWER_PROMPT.md`, and new `TESTER_PROMPT.md` contain the
  corresponding role contracts. Other `docs/claude/` role prompts are
  untouched.
- No repo-wide formatter, `--fix` linter, or codemod was run.

### 10.12 Deviations and stop events

No stop condition was triggered. Recorded deviations, all small and
explained in place: integration-script counter arithmetic (10.4);
`.pytest_cache/` in `.gitignore` (10.7); `_send_action` broken-pipe guard
(10.6); `_create_ini`'s `band` parameter position (positional after
`sim_duration`; the only caller passes it by keyword); subagent-created
`feature-research/` audits deleted (10.1); `seed_source` in `rl_episode.json`
(including the `gym` label for a genuinely different explicit Gym seed), a
useful provenance addition beyond the original field list. The original S1-S7 implementation
respected the then-approved section-15 file set. The later human-approved plan
amendment replaced `docs/ORCHESTRATION.md` with
`docs/claude/ORCHESTRATOR_PROMPT.md` and added
`docs/claude/IMPLEMENTER_PROMPT.md` to that set; no unapproved durable file was
left created or modified.

### 10.13 Checks reserved for the human, Reviewer, and Tester

- **H1** (human): `./ns3 configure --build-profile=debug -- -DCMAKE_OSX_ARCHITECTURES=arm64` then `./ns3 build` from the ns3-mmwave root; record `<BIN>`.
- **R1** (Reviewer): diff review over the union of plan section 15 and the
  file list at the top of this audit; write
  `baseline-review-and-test-charter.md`. Specific review points: reward body
  byte-identical (`git diff src/rl/rl-bridge.cc`); `run.log` layout vs plan
  3.2; `cfg.band` reaching `LinkEvaluator::Configure`.
- **T1** run `make -C tests/unit/config test`, `make -C tests/unit/eval test`,
  `make -C tests/unit/routing test`, and `make -C tests/unit/traffic test`
  separately (expect the same four failures only; `make test` stops early).
- **T1A** `python3 -m scripts.validation.regression_check verify-suite --sim-binary <BIN> --manifest tests/fixtures/regression/p0/manifest.json --out outputs/p0-regression/suite-postchange` (and `--require-all` on the complete lab checkout). `run.log` is intentionally excluded from comparison.
- **T2** `MESH_SIM_BIN=<BIN> make integration` from `tests/` (8 contracts).
- **T3** fresh test venv and focused contracts as the reissued charter directs;
  include `scripts/rl/tests` and new `scripts/validation/tests`.
- **T4** real MaskablePPO smoke: `.venv/bin/python -m scripts.rl.train --sim-binary <BIN> --run-config inputs/baselines/p0-smoke/run.ini --output-dir outputs/p0-verification/rl m-ppo --total-timesteps 16 --n-steps 16 --seed 1`.
- **T5** sweep and validation surfaces with temporary configs (OS-appropriate commands in agent C's dry-run pattern: a scratch `sweep.ini` with `base_scenario = inputs/baselines/p0-smoke`, `seeds = 1`, `auto_plot = none`, `[sweep.override] channel.band = mmwave`; and `python -m scripts.validation.run_batch --scenarios-dir <tmp dir containing only p0-smoke> --seeds 1 --sim-binary <BIN> --out outputs/p0-verification/batch`).
- **T6** legacy alias: temporary copy of `p0-smoke/run.ini` with `reward_type = mean_sinr`; expect one deprecation warning, `rl.reward_type = all_links_los`, `rl.reward_alias = mean_sinr` in `run.log`.
- **R2/G1**: final verdict and Git/PR handling. The Implementer created no branch, commit, stash, or PR.

### 10.14 Remaining TODOs carried forward

- **Jammer** (plan section 9, TODO-JAM-1..6 / TODO-BAND-1 / TODO-BAND-2 in `TODO.md`): 0 dB floor vs disconnection, default band, band-vs-frequency naming/validation, endpoint rule, spectral overlap, recorded Sherpa motion, receive-antenna effects, duty-cycle semantics — all open, physics frozen.
- **Data** (TODO-DATA-1): no EW-trials source CSV or field-generated `jammers.json` exists under `scratch/mesh-sim/`; the synthetic `p0-jammer-smoke` fixture is P0's only jammer coverage and is not field data.
- **Seeds** (TODO-RL-SEEDS-1): one fixed seed reused across episodes; multi-seed training/evaluation policy deferred.
- **Continuous actions**: the Box remains 2-D while C++ accepts an optional z; unverified, deferred to P1.
- **Portability**: `requirements.txt` pins were tested only on macOS arm64 / Python 3.11.9; a cluster lock/constraints file is later SLURM work. The integration script and launchers assume a POSIX shell/loader path (`DYLD_`/`LD_LIBRARY_PATH`).
- **Test hygiene** (outside P0): the two `node_type` config failures and two eval MCS-clamp failures remain for a separately approved task.

### 10.15 Git and ns-3 confirmation

Only read-only Git commands were run during S1–S7 (`git status`,
`git diff`, `git diff --stat`, `git check-ignore`). No branch, stage,
commit, stash, checkout, reset, push, or PR. No `./ns3 configure`, `build`,
`run`, or `clean` was executed by the coordinator or any subagent; the
simulator binary was never executed. All standalone test builds used the
`tests/` Makefiles only.

## 11. Approved R1 repairs and H0B (2026-09-15)

The human requested fixes for the independent Reviewer's B1/B2 and N1-N12.
The approved amendment is recorded at the top of the plan. Codex performed the
repairs below without delegation, ns-3 commands, real-simulator execution, or
Git mutation. The Reviewer's charter was not edited or reclassified by the
Implementer.

### 11.1 Finding disposition and exact files

| Finding | Repair / disposition |
| --- | --- |
| B1 | **Still pending human H1.** Read-only hash/mtime inspection confirms the binary remains `370d8356…32d5`, mtime `2026-09-14 17:43:01 -0400`. `CLAUDE.md` prohibits agent ns-3 builds, so no build was attempted and no post-change hash is claimed. |
| B2 / H0B | `regression_check.py` skips leading `#` metadata before the CSV header. Six fixtures' positions tables were reconstructed from saved H0 raw outputs, with the manifest's six snapshot hashes updated. One new regression test file prevents recurrence. |
| N1 | `mesh_env.py` records an explicitly stopped episode as `interrupted` even when closing stdin leads to exit 0. Only natural `done=true` completion is `completed`. Existing RL tests now check both cases and the zero-step initialization episode. |
| N2 | `train.py` uses `bootstrap_venv.DIRECT_DEPS` as the one eight-package provenance list. Its manifest test verifies all eight installed versions. |
| N3 | `build_config_files.py` accepts `all_links_los` as well as the legacy alias, and its default comment names the canonical reward. A temporary generated INI confirms canonical output. No committed scenario was regenerated. |
| N4 | `mesh_env.py` strips at the first `#` or `;` anywhere in seed/bounds values, with interpolation disabled. Existing RL tests cover both markers, with and without preceding whitespace. `fake_sim.py` avoids evaluating an unused INI seed fallback when the explicit seed flag exists. |
| N5 | `src/cli/cli-parser.cc` help now describes jammer interference enabled/disabled, not general co-channel interference. This text-only C++ change requires H1 verification. |
| N6 | `inputs/README.md` labels `[channel] band` optional, matching old baseline files. |
| N7 | Section 10.12 records the episode `seed_source` field and `gym` label as a provenance addition beyond the original field list. |
| N8 | Plan status and TODO numbering are corrected. Section 4 identifies human H0 captures/build and human-approved Codex H0A aggregate checks, distinguishing them from post-change evidence. |
| N9 | `README.md` explains that `make test` stops early and gives all four individual suite commands. The unit runner and four known failures were not changed. |
| N10 | `runner.py`, `run_batch.py`, and `regression_check.py` pass `stdin=subprocess.DEVNULL` to unattended simulator children. New regression tests mock all three launches; no real binary is invoked. EOF still selects the existing Stay fallback; physics and reward are unchanged. |
| N11 | `bootstrap_venv.py` no longer upgrades pip; it installs only pinned requirements. All three launchers and the RL env join non-empty loader-path entries only, retaining supplied non-empty entries. Mocked launch tests cover unset variables and pre-existing empty entries. |
| N12 | `docs/claude/README.md` distinguishes documentation-only versus runtime edits. `TESTER_PROMPT.md` allows the one durable results artifact plus charter-authorized disposable outputs, temporary test inputs, logs, caches, and test venv paths. It still prohibits implementation edits, unauthorized project-venv changes, builds, and Git mutation. |

### 11.2 H0B reconstruction proof

Evidence is disposable and ignored:
`outputs/p0-verification/reviewer-fixes/h0b-repair-report.json`.
Original snapshots/manifest are copied unchanged under `original-snapshots/`;
the one-off reconstruction script is retained as `h0b-reconstruct.py` in that
same evidence directory. It never launches the simulator. It refuses to
overwrite populated original evidence.

For each case, the repair loaded every stable table and the normalized summary
from the H0 raw directory, asserted equality with the old snapshot for every
non-positions table and summary, and substituted only the corrected positions
table. Restoring the old positions block reproduces the original serialized
snapshot bytes exactly. Sources, metadata, table-presence lists, and all other
blocks therefore remain byte-equal. Replacing the six new hashes with their
old values also reproduces the original manifest bytes exactly. The baseline
binary hash remains unchanged.

All raw H0 files were hashed before and after reconstruction and are unchanged.
The raw positions-file mtimes are `2026-09-14 17:43:47` through `17:44:21`
local (`-0400`), earlier than the S1 edits. Every corrected positions table has
exact columns `time_s,node_id,x,y,z,node_type,active`:

| Case | H0 directory under `outputs/p0-regression/before/` | Positions rows |
| --- | --- | ---: |
| Static LOS | `static-los` | 102 |
| Building blockage | `building-blockage` | 602 |
| Three-node relay | `relay` | 153 |
| Sherpa Spring Lake | `sherpa-static` | 3603 |
| CalFEX window | `calfex-1509-1513` | 1666 |
| Synthetic jammer | `jammer` | 15 |

Current digests are in section 6; the evidence report includes each old/new
digest and the raw-file hashes. No recapture, post-change simulation, field-data
regeneration, or input reorganization took place.

### 11.3 Implementer-authorized checks

| Command / check | Observed result |
| --- | --- |
| One-off H0B script (`python3 -B …/repair_p0_snapshots.py <mesh-sim-root>`) | Six fixtures reconstructed; integrity validates all six. Only positions blocks and manifest snapshot hashes changed. |
| `python3 -B -m scripts.validation.regression_check compare --baseline <snapshot> --candidate <saved-H0-run> --report <evidence>/<case>-match.json` for each of six cases | **MATCH, exit 0, six of six.** This compares saved data only, not a simulator execution. |
| Same `compare` on a copied jammer candidate with first-row X increased by 1 m | **MISMATCH, exit 1, exactly one difference:** `positions.csv[row 0].x`. Report: `perturbed-x-mismatch.json`. |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest scripts/rl/tests scripts/validation/tests -q` | **22 passed in 25.01 s** (16 RL items, 6 regression/launcher items). All simulator launches are fake or mocked. |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/rl/bootstrap_venv.py --check` | Exit 0; Python 3.11.9 and all eight pinned dependency versions printed. This is an existing-venv check, not a fresh-install claim. |
| `…/.venv/bin/python -m scripts.validation.build_config_files --help` and `_create_ini` into `canonical-generator/` | Canonical reward is accepted in help and written as `reward_type = all_links_los`; band remains explicit. |
| Mocked bootstrap installation path | Exactly one pip command, `install -r requirements.txt`, and no pip upgrade; no installation performed in this mock check. |
| `ast.parse` on all ten repaired Python files | All parse without cache writes. |
| `git diff --check`; read-only status | Clean diff whitespace. Current tree has 22 tracked modified files (including user-owned `CLAUDE.md`) and 32 untracked files (including the independent charter and one new test file). Nothing staged. |

The initial one-off H0B harness wrongly asserted that the manifest validator's
successful six-entry return list should be empty. It stopped before any
fixture or manifest rewrite; that harness assertion was corrected to require
six entries. Its subsequent reconstruction and all recorded checks passed.

### 11.4 Remaining gates and restraint

B1 is not fixed by a regression MATCH: the old binary must not be used as
post-change evidence. The human must run H1, record completion, full binary
SHA-256 and mtime, then start a fresh Reviewer. That Reviewer owns reissuing
`baseline-review-and-test-charter.md` and incorporating the new test file and
digests. Testing remains unauthorized until that reissue.

The original four unit-test failures were neither fixed nor re-executed in
this repair pass. The Tester must verify their exact names and counts by
running all four suites. Fresh-venv installation, real CLI, real MaskablePPO,
Stay/alias/default-band checks, and post-change suite execution remain reserved
to the charter. Jammer physics, reward arithmetic, C++ CSV/summary schemas,
all committed scenario inputs, ignored field data, the raw H0 outputs, and the
Reviewer's charter were preserved. No build, real simulator run, Git mutation,
or phase advancement was performed.
