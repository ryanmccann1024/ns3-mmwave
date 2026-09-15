# P0 Baseline Test Results

Role: independent Tester, fresh context.
Date: 2026-09-15.
Charter: `docs/rl-program/p0-baseline/baseline-review-and-test-charter.md`, status **READY_FOR_TEST**. Section 7 was executed as written.
Order run: T0, T1, T1A, T2, T7, T8, T6, T3, T4, T5.

All paths are relative to `scratch/mesh-sim/` unless absolute. Every code block was run as a single zsh invocation, exactly as the charter gives it. The commands are not repeated here; each row cites the charter block it ran.

## Environment and simulator provenance

| Item | Value |
| --- | --- |
| Host | macOS 26.6.1 (25G76), arm64, `/bin/zsh` |
| System Python (T0–T2, T6–T8, bootstrap) | `/Library/Frameworks/Python.framework/Versions/3.11/bin/python3`, 3.11.9 |
| Test venv Python (T3–T5) | `outputs/p0-verification/t3/venv/bin/python`, 3.11.9, freshly created by T3 |
| Toolchain (T1) | Apple clang 21.0.0 (clang-2100.1.1.101), GNU Make 3.81 |
| Binary (`BIN`) | `/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/scratch/mesh-sim/ns3.42-sim-debug` |
| Binary SHA-256 (observed) | `57613a69f88a6bb11832b62d8f80a4ccf46644b2d6cbe46f60a6bc645beb3722`. This matches H1 and is not the H0 hash `370d8356…32d5`. |
| Binary mtime (observed) | `2026-09-15T12:40:54` |
| Loader path (`LIB`) | `/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/lib` |
| Build | Built by the human with `./ns3 build`. The configure invocation is not known to the Tester (R-3). The Tester ran no build. |
| Git | Branch `arpo-main`, HEAD `a4e700d9947db57d06ade3ce391425681a3c2746` |

After T5, `git status --porcelain=v1 -uall -- .` was re-run before this document was written. Diffed against `outputs/p0-verification/t0/git-status.txt`, it was identical (exit 0), so testing changed no tracked or untracked project path.

## Row results

### T0 — Binary, reviewed-code, and evidence provenance preflight — **PASS**

- **Working directory:** mesh-sim root.
- **Command:** the charter §7 T0 block, verbatim.
- **Expected:**
  - both precondition lines;
  - the H1 hash and mtime;
  - string counts ≥1/≥1/≥1/≥1/=0;
  - the reviewed HEAD;
  - `git-status diff exit=0`;
  - `reviewed-digests exit=0` with 35 `OK` lines.
- **Actual:**
  - Precondition output: `PRECONDITION: run paths absent` and `reviewer-fixes evidence: present (preserve, do not modify)`.
  - SHA-256 `57613a69…3722` and mtime `2026-09-15T12:40:54`.
  - String counts:
    - `band_source: 1`
    - `jammer_path_enabled: 1`
    - `is deprecated; use 'all_links_los': 1`
    - `(jammer interference enabled): 1`
    - `co-channel interference computed: 0`
  - HEAD: `a4e700d9947db57d06ade3ce391425681a3c2746`.
  - `git-status diff exit=0`, with `git-status.diff` empty.
  - `reviewed-digests exit=0` and `digest OK lines=35`. No non-OK lines.
- **Output:** `outputs/p0-verification/t0/`

### T1 — Standalone unit tests — **PASS**

- **Working directory:** `tests/`.
- **Command:** the charter §7 T1 block, verbatim.
- **Expected:**
  - `unit/config`: 51 passed, 2 failed. The only failures are `valid config should pass` and `gateway with valid node ID accepted`.
  - `unit/eval`: 156 passed, 2 failed. The only failures are `table clamps at highest MCS` and `mcs_index at 50 dB clamps to 14`.
  - `unit/routing`: 42 passed, 0 failed.
  - `unit/traffic`: 32 passed, 0 failed.
  - `config` and `eval` exit nonzero; `routing` and `traffic` exit 0.
  - `make test` stops at `unit/config`.
- **Actual:**
  - Exit codes:
    - `clean exit=0`
    - `make test exit=2`, stopping at `unit/config`: `make-test.log` holds only the config suite's output.
    - `unit/config exit=2`
    - `unit/eval exit=2`
    - `unit/routing exit=0`
    - `unit/traffic exit=0`
  - Results:
    - `config.log`: `51 passed, 2 failed.` with FAIL lines `valid config should pass` and `gateway with valid node ID accepted`.
    - `eval.log`: `156 passed, 2 failed.` with FAIL lines `table clamps at highest MCS` and `mcs_index at 50 dB clamps to 14`.
    - `routing.log`: `42 passed, 0 failed.`
    - `traffic.log`: `32 passed, 0 failed.`
  - There were no other FAIL lines and no compile errors.
  - The four pre-existing failures match the charter's accepted names and counts exactly.
- **Output:** `outputs/p0-verification/t1/` (`clean.log`, `make-test.log`, `config.log`, `eval.log`, `routing.log`, `traffic.log`). The test binaries were rebuilt under `tests/unit/*/` (write authority, item 5).

### T1A — Post-change regression suite — **PASS**

- **Working directory:** mesh-sim root.
- **Command:** the charter §7 T1A block, verbatim.
- **Expected:**
  - structure exit 0;
  - suite exit 0 and require-all exit 0;
  - report-check prints `OK` and exits 0.
- **Actual:**
  - `structure exit=0`: six snapshots, each with `['time_s', 'node_id', 'x', 'y', 'z', 'node_type', 'active']`, and `BAD []`.
  - `suite exit=0` and `require-all exit=0`.
  - Both consoles show:
    - `Binary: 57613a69f88a... (different binary; results decide compatibility)`;
    - six `PASS` rows: static LOS, building blockage, three-node relay, Sherpa Spring Lake, CalFEX, and synthetic jammer;
    - `RESULT: PASS — required 5/5, optional 1/1, skipped 0`.
  - Neither console contains `matches reference`. Sherpa ran; it was not skipped.
  - `report-check exit=0`. Both reports read `PASS 5 5 1 1 0 0 57613a69…3722`, followed by `OK`.
- **Output:**
  - `outputs/p0-regression/suite-postchange/`
  - `outputs/p0-regression/suite-postchange-require-all/`
  - `outputs/p0-verification/t1a/` (`snapshot-structure.txt`, both `.console` files, `report-check.txt`)

### T2 — Real-binary CLI integration — **PASS**

- **Working directory:** `tests/`.
- **Command:** the charter §7 T2 block, verbatim, with `MESH_SIM_BIN=<BIN> make integration`.
- **Expected:**
  - exit 0;
  - 8 `PASS:` and 0 `FAIL:` lines;
  - test 7 reads `run.log records band = sub-6 and band_source = cli`;
  - test 8 reads `jammer band A/B differs in N matched links` with N ≥ 1.
- **Actual:**
  - `integration exit=0`, with `Binary:` naming `BIN`.
  - Eight `PASS:` lines and zero `FAIL:` lines.
  - Test 7: `run.log records band = sub-6 and band_source = cli`.
  - Test 8: `jammer band A/B differs in 15 matched links`.
  - `Results: 8 passed, 0 failed.`
- **Output:** `outputs/p0-verification/t2/integration.log`

### T7 — Band resolution without a CLI override — **PASS**

- **Working directory:** mesh-sim root.
- **Command:** the charter §7 T7 block, verbatim.
- **Expected:**
  - Both runs exit 0.
  - The default run logs `--band = (not set)`, `band = mmwave`, `band_source = default`, and `jammer_path_enabled = false`.
  - The INI run logs `band = sub-6`, `band_source = run.ini`, `jammers.configured = 1`, `jammers.enabled = 1`, `jammer_path_enabled = true`, and the exact `jammer-0:` line.
  - Both compares exit 0 with `MATCH`.
- **Actual:**
  - `default-band exit=0` and `ini-band exit=0`.
  - `default-band/run.log`:
    - `--band = (not set)`
    - `band = mmwave`
    - `band_source = default`
    - `jammer_path_enabled = false`
  - `ini-band/run.log`:
    - `--band = (not set)`
    - `band = sub-6`
    - `band_source = run.ini`
    - `jammers.configured = 1`
    - `jammers.enabled = 1`
    - `jammer_path_enabled = true`
    - `jammer-0: enabled=true type=constant target_freq_mhz=[2400] tx_power_dbm=30 tx_array_gain_dbi=12 duty_cycle=1 max_range_m=0 beamwidth_deg=360 azimuth_deg=0 zenith_deg=90 motion=static`
  - Compares:
    - `MATCH: …baseline-static-los.json == …t7/default-band (atol=1e-09)`, `compare default exit=0`
    - `MATCH: …baseline-synthetic-jammer.json == …t7/ini-band (atol=1e-09)`, `compare ini exit=0`
- **Output:** `outputs/p0-verification/t7/` (both run directories, consoles, `default-band-compare.json`, `ini-band-compare.json`)

### T8 — Closed and malformed RL action input maps to Stay — **PASS**

- **Working directory:** mesh-sim root.
- **Command:** the charter §7 T8 block, verbatim.
- **Expected:**
  - Both runs exit 0.
  - `closed`: closed-warn = 1 and malformed-warn = 0.
  - `malformed`: malformed-warn = 1 and closed-warn = 0.
  - The position check exits 0 with ≥ 4 relay rows and 0 moved rows.
  - stdout contains only JSON lines, one per tick.
- **Actual:**
  - `closed exit=0` and `malformed exit=0`.
  - Warning counts:
    - `closed closed-warn=1`, `closed malformed-warn=0`
    - `malformed closed-warn=0`, `malformed malformed-warn=1`
  - The position check found `relay_rows 5 moved_rows 0` for both runs, `position-check exit=0`.
  - The stdout criterion was checked with a read-only inspection of the produced files. Each stdout file has 5 lines, all 5 parse as JSON, and each `positions.csv` has 5 distinct `time_s` ticks. The first line is a `"type":"step"` object with `controlled_pos [50.0,50.0,10.0]`.
- **Output:** `outputs/p0-verification/t8/` (`closed/`, `malformed/`, `*.stdout`, `*.stderr`)

### T6 — Legacy reward alias — **PASS**

- **Working directory:** mesh-sim root.
- **Command:** the charter §7 T6 block, verbatim.
- **Expected:**
  - diff exit 1 with a single `reward_type` change;
  - both runs exit 0;
  - deprecation warning counts: legacy = 1, canonical = 0;
  - `run.log` reward type and alias fields as specified;
  - reward-compare exit 0 and stdout cmp exit 0.
- **Actual:**
  - `diff exit=1`. The only change is `42c42`, `reward_type = all_links_los` → `reward_type = mean_sinr`.
  - `legacy exit=0` and `canonical exit=0`.
  - `legacy deprecation=1` and `canonical deprecation=0`.
  - `legacy/run.log`: `rl.reward_type = all_links_los` and `rl.reward_alias = mean_sinr`.
  - `canonical/run.log`: `rl.reward_type = all_links_los` and `rl.reward_alias = none`.
  - Reward sequences: legacy and canonical are both `[1.0, 1.0, 1.0, 1.0, 1.0]`, `reward-compare exit=0`.
  - `stdout cmp exit=0`.
- **Output:** `outputs/p0-verification/t6/` (the temporary scenario copy is in `legacy-scenario/`, plus `ini.diff`, both run directories, and stdout/stderr)

### T3 — Fresh Python environment and focused contracts — **PASS**

- **Working directory:** mesh-sim root.
- **Command:** the charter §7 T3 block, verbatim.
- **Expected:**
  - bootstrap exit 0 and check exit 0;
  - exactly 2 `+ ` command lines, venv then `pip install -r`, with no pip upgrade;
  - eight exact pins;
  - POSIX and Windows activation lines;
  - `22 passed` with no skipped, failed, error, xfailed, or deselected items.
- **Actual:**
  - `bootstrap exit=0` and `bootstrap command lines=2`:
    1. `+ /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 -m venv /Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/scratch/mesh-sim/outputs/p0-verification/t3/venv`
    2. `+ /Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/scratch/mesh-sim/outputs/p0-verification/t3/venv/bin/python -m pip install -r /Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/scratch/mesh-sim/requirements.txt`
  - `check exit=0`. The check log lists:
    - `python==3.11.9`
    - `gymnasium==1.3.0`
    - `numpy==2.4.6`
    - `stable-baselines3==2.9.0`
    - `sb3-contrib==2.9.0`
    - `torch==2.14.0`
    - `pandas==3.0.5`
    - `matplotlib==3.11.2`
    - `pytest==9.1.1`
  - The check log also has both the `POSIX:` and `Windows:` activation lines.
  - `pytest exit=0` with the summary `22 passed in 19.90s`. The log has no skip, xfail, deselect, error, or warning text.
- **Output:** `outputs/p0-verification/t3/` (`bootstrap.log`, `bootstrap-commands.txt`, `bootstrap-check.log`, `pytest.log`, `venv/`). The project `.venv/` was not used or modified.

### T4 — Real MaskablePPO process smoke — **PASS**

This row proves process integration only, not learning or convergence.

- **Working directory:** mesh-sim root.
- **Dependency:** T3 PASS.
- **Command:** the charter §7 T4 block, verbatim.
- **Expected:**
  - train exit 0 and inspect exit 0 with `ERRORS []`, which includes the N1 status contract;
  - rerun exit 1 and refusal = 1;
  - manifest cmp exit 0 and listing cmp exit 0.
- **Actual:**
  - `train exit=0` and `inspect exit=0`.
  - The manifest has `status completed` and `python_version 3.11.9`, and all eight package pins match.
  - Episodes:
    - `episode-0000`: interrupted, 0 steps, exit 0, reward 0.0
    - `episode-0001` to `episode-0004`: each completed, 4 steps, exit 0, reward 4.0
    - `episode-0005`: interrupted, 0 steps, exit 0, reward 0.0
  - `ERRORS []`.
  - No interrupted episode had a negative exit code (R-4 was not observed).
  - Rerun:
    - `rerun exit=1`
    - `refusal=1`, with the message `Refusing to start: outputs/p0-verification/rl already contains train_manifest.json. Choose a new --output-dir.`
    - `manifest cmp exit=0` and `listing cmp exit=0`
- **Output:**
  - `outputs/p0-verification/rl/` (manifest, `maskable_ppo_mesh.zip`, `episode-0000`…`episode-0005`)
  - `outputs/p0-verification/t4/` (`train.console`, `inspect.txt`, `rerun.console`, before/after hashes and listings)

### T5 — Sweep and validation surfaces — **PASS**

- **Working directory:** mesh-sim root.
- **Dependency:** T3 PASS.
- **Command:** the charter §7 T5 block, verbatim.
- **Expected:** sweep, batch, batch-band, and inspect all exit 0, and inspect prints `ERRORS []`.
- **Actual:**
  - `sweep exit=0`, and the console shows `Succeeded: 1` and `Failed: 0`.
  - `batch exit=0` and `batch-band exit=0`.
  - `inspect exit=0` with `ERRORS []`.
- **Output:**
  - `outputs/p0-verification/t5/` (`sweep.ini`, `sweep.console`, `batch/`, `batch-band/`, both batch consoles, `inspect.txt`)
  - Sweep directory created by T5: `outputs/2026-09/15/13-27-29/`

## Summary

| Row | Verdict |
| --- | --- |
| T0 | PASS |
| T1 | PASS (only the four charter-accepted pre-existing failures) |
| T1A | PASS |
| T2 | PASS |
| T7 | PASS |
| T8 | PASS |
| T6 | PASS |
| T3 | PASS |
| T4 | PASS |
| T5 | PASS |

- **Counts:** 10 PASS, 0 FAIL, 0 BLOCKED.
- **Failures:** none.
- **Blockers:** none.
- **Deviations:** none. No command was altered, and no row, seed, or scenario was added.
- **Checks outside the charter blocks:** read-only inspection of files the rows had already produced. That covered:
  - the T8 criterion that stdout holds only JSON lines, one per tick;
  - the T1A, T3, T4, and T5 evidence lines quoted above;
  - the environment versions;
  - the post-run `git status` comparison.
- **Preserved:**
  - `outputs/p0-regression/{before,suite-prechange,suite-prechange-readable,suite-user-check}/`
  - `outputs/p0-verification/reviewer-fixes/`
  - the project `.venv/`
  - all of these were left untouched.
- **Carried-forward reviewer items:** R-1 (stale audit text) and R-2 (GUI metadata not compared) are outside Tester scope. For R-3, the configure invocation is still unknown to the Tester. R-4 was not observed.

## Handoff

This document goes back to the human for the fresh final Reviewer, who writes `baseline-completion-report.md` with `accept` or `return`. The Tester does not declare P0 accepted, and no Git or PR action has been taken.
