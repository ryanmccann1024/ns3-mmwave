# P0 Baseline Review and Test Charter

Phase: P0 — trustworthy baseline
Role: R1 re-review, a fresh independent Reviewer. The role is read-only: no builds, tests, simulator runs, formatters, Doxygen, Git mutation, or delegation.
Date: 2026-09-15. This revision replaces the 2026-09-14 R1 revision, which was marked RETURN_TO_IMPLEMENTER.

Inputs read in full:

- `CLAUDE.md`
- `docs/claude/REVIEWER_PROMPT.md` and `TESTER_PROMPT.md`
- `baseline-implementation-plan.md`, including the approved R1 repair amendment
- `baseline-implementation-audit.md`, including section 11
- the previous revision of this charter

Also inspected:

- the scoped diffs and current contents of every repaired file
- the disposable repair evidence under `outputs/p0-verification/reviewer-fixes/`
- the raw H0 captures under `outputs/p0-regression/before/`
- the human H1 build evidence

All paths are relative to `scratch/mesh-sim/` unless they are absolute.

## 1. Status

**READY_FOR_TEST**

- Both blocking findings (B1, B2) are resolved.
- N1–N12 are resolved.
- The execution charter in section 7 is authorized, with literal hashes and digests filled in.
- No real-binary test has been run by any role. This charter makes no claim that any row passes.

## 2. Finding dispositions

### Blocking

#### B1 — RESOLVED — H1 build evidence matches the supplied binary, and the binary contains the P0 changes

- **Original finding (R1):** the binary at the supplied path was the pre-change H0 binary (`370d8356…32d5`, mtime 2026-09-14 17:43:01), and the H1 hash was an unfilled placeholder.
- **Human H1 evidence supplied:**
  - `./ns3 build` completed.
  - Binary path: `/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/scratch/mesh-sim/ns3.42-sim-debug`.
  - SHA-256: `57613a69f88a6bb11832b62d8f80a4ccf46644b2d6cbe46f60a6bc645beb3722`.
  - Mtime: 2026-09-15 12:40:54 -0400.
- **Independent read-only verification:**
  1. `shasum -a 256` gives `57613a69f88a6bb11832b62d8f80a4ccf46644b2d6cbe46f60a6bc645beb3722`. That equals the supplied hash and differs from the H0 hash `370d8356186a2b97d988061019cbd8ab4391c191f076da8b559e531854da32d5`.
  2. `stat` gives `2026-09-15 12:40:54 -0400`, which equals the supplied mtime. The binary is 2,389,968 bytes, and `file` reports a Mach-O 64-bit arm64 executable.
  3. The binary is newer than every mesh-sim C++ source. The newest is `src/cli/cli-parser.cc` at 2026-09-15 08:04:23, the N5 repair. `find src sim.cc CMakeLists.txt -newer <BIN>` returns nothing.
  4. `strings` counts:
     - `band_source`: 1
     - `jammer_path_enabled`: 1
     - `is deprecated; use 'all_links_los'`: 1
     - `rl.reward_alias`: 1
     - `RL action stream closed; holding position (Stay).`: 1
     - `malformed RL action JSON; holding position (Stay).`: 1
     - the repaired N5 help text `Override [channel] band from run.ini: 'mmwave' (jammer interference disabled) or 'sub-6' (jammer interference enabled).`: present
     - the pre-repair help fragment `co-channel interference computed`: 0
- **Qualification (non-blocking, R-3):** the H1 evidence names `./ns3 build` but does not restate the plan's configure command.
  - The `-debug` binary suffix and the arm64 Mach-O type match the plan's debug arm64 profile.
  - `build/lib/*.dylib` still date from 2026-09-14 17:41–17:42. That is consistent with rebuilding only the mesh-sim executable, because P0 changed no library code.
- **Result:** B1 is satisfied. The literal hash is substituted throughout section 7.

#### B2 — RESOLVED — `positions.csv` values are now parsed, snapshotted, and compared

- **Original finding (R1):** `load_table` took the first GUI metadata line (`# scenario=…`) as the header, so `node_id`, `x`, `y`, `z`, `node_type`, and `active` were never compared. All six H0 snapshots encoded that defect.
- **Parser repair:** `scripts/validation/regression_check.py` `load_table`, lines 134–153.
  - After reading the first record, `while columns and columns[0].startswith("#"): columns = next(reader)` skips only the leading records whose first field starts with `#`. A file with no header after its metadata returns `{"columns": [], "rows": []}`.
  - Parsing of the other five tables is unchanged. The H0B script asserted that rebuilt non-positions tables equal the old snapshot tables, and I confirmed that independently (below).
  - The module still imports only the standard library.
  - `src/io/viz-writer.cc:64-76` writes exactly 11 `# key=value` lines, then `time_s,node_id,x,y,z,node_type,active`. Raw `outputs/p0-regression/before/jammer/seed-1/positions.csv` has the same layout.
- **Recurrence test:** `scripts/validation/tests/test_regression_check.py`. This file was added by the approved plan amendment and is listed in plan §15.
  - `test_positions_header_and_coordinates` is parameterized with and without a metadata prefix. It asserts the seven columns and the parsed `x`/`y`/`z` values, and asserts that a +1 change in each axis produces exactly one difference named `positions.csv[row 0].<axis>`.
  - `test_no_header_is_empty` covers empty and metadata-only files.
- **Coordinate-change detection on real H0 data:** `outputs/p0-verification/reviewer-fixes/perturbed-x-mismatch.json`.
  - `match: false`, `counts.total: 1`, and the only difference is `positions.csv[row 0].x`, baseline `0.0` and candidate `1.0`.
  - All three jammer source digests match.
- **Unchanged-candidate evidence:** the six `*-match.json` reports under `reviewer-fixes/` all have `match: true`.

### H0B verification (independent, read-only Python over the preserved files)

| Snapshot | Original SHA-256 (preserved copy) | New SHA-256 (tracked) | Positions rows | Non-positions blocks equal | Old positions columns | New positions == raw H0 CSV | Restoring old positions reproduces original bytes |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| `baseline-static-los.json` | `bd0beeac9042a57d961c150768aaa75d36e7e9103976ca1e18693a58af855c47` | `10e8683c440bc83e5d4d89a7b655cd541745dd2b9fe079e7307877f9245816d5` | 102 | yes | `["# scenario=01-static-los-baseline"]` | yes | yes |
| `baseline-building-blockage.json` | `1f7b5e786cdb985ee7cfc739f358dcea01c1dd3bd3e5956942f71ac4d8b6ba8e` | `4633c33619210ae9b6e608b0f1917527d05ed4983c18959d3b0acc86d0481bf3` | 602 | yes | `["# scenario=03-building-blockage"]` | yes | yes |
| `baseline-three-node-relay.json` | `fad2ee7bffa2ea1176bc547625e2dac09a3b5b043d88f0c0d461352babf6585c` | `ed8f888924da4acdb0f558b6b76a85713174ae32842c8f8a12921a0aebaba338` | 153 | yes | `["# scenario=07-three-node-relay"]` | yes | yes |
| `sherpa-spring-lake-static.json` | `4214b0bcc4ca642acc59a201b1342bb7a0004dc426de46a7fe74b9c77be61bdb` | `278fe57b3eb298e5c6a28dd7839d326dfc9b431a9da05680c46ee9b4320d4924` | 3603 | yes | `["# scenario=arpo-1-1-static-04172026"]` | yes | yes |
| `calfex-06-25-1509-1513.json` | `5a429cdd8ef1cd3fbe996d92639da5049241c2ea14c9074f2cfb90fb6da94e7d` | `1c9b14f2d77869fa18df48f46f299659317ce3789e469413d78c7f0a24422512` | 1666 | yes | `["# scenario=calfex"]` | yes | yes |
| `baseline-synthetic-jammer.json` | `8cf5a58cab4bc0afacb561521414a5771f4a33a54f7a550a23150fe303d77e63` | `39152a1fec6bb0f170840696849eee2732ab264707d91309842d16dda6fb9ab7` | 15 | yes | `["# scenario=p0-jammer-smoke"]` | yes | yes |

Method and results:

- **Non-positions blocks equal:** every top-level key other than `tables` is equal (`snapshot_version`, `family`, `case`, `seed`, `band`, `sources`, `seed_dir`, `tables_missing`, `summary`), and so are all five other tables.
- **Positions match the raw data:** I parsed the raw `outputs/p0-regression/before/<case>/seed-1/positions.csv` without the repository parser, using a plain `csv` reader on the non-`#` lines. For all six cases the tracked positions block has exactly `time_s,node_id,x,y,z,node_type,active` and equal rows.
- **Byte reproduction:** putting each old positions block back into the new snapshot and serializing with `json.dumps(indent=2, sort_keys=True) + "\n"` reproduces the preserved original bytes exactly. Each tracked file is also in canonical serialization.
- **Chain of custody:**
  - The preserved `original-snapshots/manifest.json` has SHA-256 `3b08e894f64aeb7f8e89694e51a7ad84e9800e4e7324e858b9281b5ae6742bb4`, the value R1 recorded for the pre-repair manifest.
  - Its six `snapshot_sha256` values equal the preserved originals listed above.
  - The preserved files keep their H0 mtimes, 2026-09-14 17:43:48–17:44:21 (manifest 18:02:51).
- **Raw H0 files:**
  - All 68 files under `outputs/p0-regression/before/` hash to the values in `h0b-repair-report.json` `raw_h0_file_sha256`, with 0 mismatches and 68 of 68 files covered.
  - The newest raw mtime is 2026-09-14 17:44:21. `find … -newermt '2026-09-14 17:45:00'` returns nothing, so no raw H0 file changed after capture.
- **The reconstruction script never launched the simulator:** `reviewer-fixes/h0b-reconstruct.py` only calls `regression_check.build_snapshot` on the saved runs and `compare` as a subprocess.

### Manifest verification

- **Current manifest:** SHA-256 `74bbf83a09b64b6fe822bfab74ea97f4fe17369635d317b190ed32abe0d2c2eb`.
- **Only the snapshot hashes changed:** a recursive diff against the preserved original finds exactly six differences, `cases[0..5].snapshot_sha256`, old value to new value as in the table above. Putting the six old hashes back reproduces the original manifest bytes exactly.
- **Baseline block unchanged:**
  - `baseline.simulator_binary_sha256` = `370d8356186a2b97d988061019cbd8ab4391c191f076da8b559e531854da32d5`
  - `git_commit` = `a4e700d9947db57d06ade3ce391425681a3c2746`
  - build `debug`/`arm64`/`clean`
- **Per-case hashes:** every case's `snapshot_sha256` equals the SHA-256 of its tracked file.

### Non-blocking findings from R1

| ID | Original finding | Disposition | Evidence |
| --- | --- | --- | --- |
| N1 | `_stop_proc` labeled an abandoned episode `completed` whenever the simulator exited 0 | **Resolved** | `scripts/rl/env/mesh_env.py`: `reset()` line 132 and `close()` line 271 call `_stop_proc("interrupted")`, which finalizes with the given status and the exit code (lines 414–434). Only `_wait_proc`, reached after `done=true` (line 221), writes `completed` (line 403). Tests: `test_two_resets_allocate_distinct_episodes` asserts `interrupted` with exit 0; `test_done_episode_is_completed` asserts `completed` after 4 steps; `test_tiny_training_run` asserts every zero-step episode is `interrupted`. T4 now enforces this against the real binary. |
| N2 | The training manifest recorded 5 of the 8 direct dependencies | **Resolved** | `scripts/rl/train.py:23` imports `DIRECT_DEPS` from `scripts/rl/bootstrap_venv.py:17-26` (all eight import names). `_package_versions` (lines 42–49) iterates over it. `test_tiny_training_run` asserts the key set equals `DIRECT_DEPS`, has length 8, and all values are truthy. T4's pin dictionary is updated to eight entries; left at five, it would have failed. |
| N3 | `build_config_files.py` could only write the deprecated `mean_sinr` | **Resolved** | `scripts/validation/build_config_files.py:552` choices are `["throughput", "all_links_los", "mean_sinr"]`, and the line-49 comment names the canonical reward. Evidence file `reviewer-fixes/canonical-generator/run.ini` has `band = mmwave` and `reward_type = all_links_los`. No committed scenario was regenerated (no `inputs/calfex/` change in `git status`). |
| N4 | The Python INI readers did not strip inline comments the way C++ does | **Resolved** | `mesh_env.py:26-29` `_strip_inline_comment` cuts at the first `#` or `;` anywhere; it is used by `read_scenario_seed` (line 38) and `_read_rl_bounds` (lines 449–450), both with `interpolation=None`. `test_seed_and_bounds_strip_inline_comments` is parameterized for `#` and `;`, with and without preceding whitespace. `fake_sim.py:85` evaluates the INI seed only when `--seed` is absent. |
| N5 | `--band` help text claimed general co-channel interference | **Resolved** | The `src/cli/cli-parser.cc:50-52` diff changes only the help string to jammer-interference enabled/disabled. The H1 binary contains the new text and not the old fragment (B1). |
| N6 | `inputs/README.md` implied every baseline declares `band` | **Resolved** | `inputs/README.md:13` now reads `run.ini          simulation parameters (optional [channel] band)`. |
| N7 | `seed_source` in `rl_episode.json` was not recorded as a deviation | **Resolved** | Audit §10.12 (lines 866–868) records `seed_source`, including the `gym` label, as a provenance addition. |
| N8 | TODO numbering, plan status, and H0A attribution | **Resolved** | Audit §10.8 (line 753) and §10.14 (line 897) now say TODO-JAM-1..6 plus TODO-BAND-1/2, which matches `TODO.md`. Plan line 5 now reads "human-approved implementation and R1 repairs complete; human H1 and fresh review/testing remain". Audit §4 (lines 405–411) attributes the H0 captures and build to the human and the three H0A aggregate runs to Codex under the human-approved pre-S1 exception. |
| N9 | `make test` stops at the first failing suite | **Resolved (documentation)** | `README.md:135-137` states the stop behavior and gives the four per-suite commands. The runner is intentionally unchanged, per the plan amendment. T1 still runs each suite. |
| N10 | Unattended launchers inherited the caller's stdin | **Resolved** | `stdin=subprocess.DEVNULL` at `scripts/sweep/runner.py:246`, `scripts/validation/run_batch.py:119`, and `scripts/validation/regression_check.py:474`. `test_unattended_launchers_close_stdin_and_clean_loader_paths` mocks all three launches and asserts `DEVNULL`. The charter's `</dev/null` redirections are kept as harmless defense in depth. |
| N11 | Unpinned pip self-upgrade; empty loader-path entries | **Resolved** | `bootstrap_venv.py:92` runs only `python -m pip install -r requirements.txt`. The `+ ` command echo makes this observable in T3. Only non-empty entries are joined at `runner.py:241`, `run_batch.py:207`, `regression_check.py:466`, and `mesh_env.py:299`. The same mocked test covers an unset variable and one that already contains empty entries. |
| N12 | Workflow documents could confuse doc-only and runtime edit rules, and Tester write scope | **Resolved** | `docs/claude/README.md:90-96` separates doc-only comment edits from planned runtime changes and says charters authorize disposable outputs, temporary inputs, caches, and a test venv. `docs/claude/TESTER_PROMPT.md:23-27` allows the one durable results document plus charter-authorized run products, logs, temporary test inputs, and a test venv, without altering `.venv/`. Section 7 of this charter lists those paths explicitly. |

### New non-blocking findings from this re-review

| ID | Sev. | Location | Evidence | Impact | Recommended remedy |
| --- | --- | --- | --- | --- | --- |
| R-1 | Low | `baseline-implementation-audit.md`: header line 5; §11.1 B1 row (line 925); §11.4 (lines 997–1001); §10.11 line 848; files-changed row line 20; §11.3 line 980 | The audit (mtime 08:55:42) predates H1 (12:40:54), so it still says H1 is unsatisfied. Line 848 still says `regression_check.py` is "unchanged from the approved H0A state", which B2, N10, and N11 made false. The line-20 row says only "new". §11.3 names the run script `…/repair_p0_snapshots.py`, but the retained copy is `h0b-reconstruct.py` (the script copies itself under that name at line 20). | Records only. §11.1 correctly lists every repair, and this charter verifies the actual code and evidence. | The final Reviewer or a later audit update should mark H1 satisfied, qualify line 848 and the line-20 row, and name the retained script. |
| R-2 | Info | `regression_check.py` `load_table`, line 140 | The 11 GUI `# key=value` metadata lines in `positions.csv` are now skipped and are not compared. Before B2 they were compared only by accident, as bogus rows. No plan item requires them, and `src/io/viz-writer.cc` is unmodified. | A future change to that GUI metadata would not be detected by `verify-suite`. | Consider a metadata comparison in a later phase if GUI metadata becomes a compatibility contract. |
| R-3 | Info | H1 evidence | The human evidence records `./ns3 build` but not the configure step. The profile and architecture are visible from the binary (B1). | None for P0 testing. | Record the configure invocation in the test results environment section if known. |
| R-4 | Info | `mesh_env.py:414-430` | An interrupted episode gets exit code 0 only if the simulator exits within 2 s of stdin closing; otherwise `terminate()` makes the exit code negative. | If the real simulator is slow to exit, T4's per-episode `exit_code == 0` criterion fails. That would be a genuine lifecycle finding, not a charter defect. | None now. |

### Defects in the previous charter revision, corrected here

Each correction is required by a concrete repair or by observed repository state:

- **T0 precondition:** it required `outputs/p0-verification` to be absent. The approved repair evidence now lives at `outputs/p0-verification/reviewer-fixes/`, so the row would always have been BLOCKED. The precondition now checks only the row-owned paths, and the evidence is preserved.
- **T0 integrity checks:** they compared only fixture and input digests and deferred the Git path set to "the re-review". Both are now literal and checked mechanically. T0 also hashes every reviewed runtime and test file, so the Tester cannot test code that changed after this review.
- **T3:** it ran only `scripts/rl/tests` and expected `13 passed`. After the repairs it runs `scripts/rl/tests` and `scripts/validation/tests` and expects `22 passed` (16 + 6, counted from the test functions and their parameterization). It also checks that the N11 bootstrap runs no pip upgrade.
- **T4 pins:** it pinned 5 packages, which the N2 repair makes a guaranteed FAIL. It now pins all 8. T4 also now asserts the N1 status contract instead of recording it only.
- **Write authority:** it omitted three things that other rows need:
  - the timestamped sweep directory T5 creates under `outputs/<YYYY-MM>/<DD>/<HH-MM-SS>/`;
  - the git-ignored test binaries and `ns3/` stub directories that T1's `make clean` deletes and rebuilds;
  - T2's and pytest's system temporary directories, Python bytecode caches, and per-user package caches.

  These are now authorized explicitly. Deleting any other pre-existing path remains prohibited.

### Verified with no finding

The R1 checks are carried forward. Every file they depend on is unchanged since R1 except where noted.

- **Repairs changed no jammer physics, reward arithmetic, committed scenario inputs, C++ output schemas, or unrelated user work:**
  - **Untouched code:** `git status` shows no change under `src/eval/`, `src/jammer/`, `src/setup/`, `src/io/viz-writer.cc`, `src/io/metrics-writer.cc`, `src/rl/rl-bridge.h`, or `CMakeLists.txt`.
  - **C++ edited after R1:** the only file is `src/cli/cli-parser.cc`, mtime 2026-09-15 08:04:23, and its diff is the help string plus the S1 empty-band check. `sim.cc`, `sim-config.h`, `config-loader.cc`, `config-validator.cc`, `cli-parser.h`, `run-logger.h`, and `rl-bridge.cc` keep their R1-reviewed mtimes (2026-09-14 18:19:08–18:22:25).
  - **Reward arithmetic:** the `rl-bridge.cc` diff still changes only the `ComputeReward` condition string and comment, plus the Stay fallback. The ±1 loop body is identical.
  - **Scenario inputs:** the digests are unchanged:
    - `p0-jammer-smoke` `run.ini` `bb923178…`, `nodes.json` `12fbcb0e…`, `jammers.json` `2a623a4c…`
    - `p0-smoke` `run.ini` `ddd91f76…`, `nodes.json` `12fbcb0e…`
    - `rl-test/run.ini` `6a9da94a…`
  - **Recent changes:** `find inputs data src tests CMakeLists.txt sim.cc -newermt '2026-09-14 19:10'` lists only `inputs/README.md` (N6), `src/cli/cli-parser.cc` (N5), and the seven regression fixtures (H0B).
  - **User-owned files:** `CLAUDE.md` (mtime 2026-09-08) and the user's `docs/claude/{GIT_PR,PLANNER,PROGRESS,SCOUT}_PROMPT.md` and `baseline-scout-report.md` keep their pre-P0 mtimes.
  - **This charter:** the Implementer did not edit it; its mtime was 2026-09-14 19:09:51 before this revision.
- **`channel.band` end to end, reward alias, Stay fallback, RL lifecycle, launchers, integration script, regression utility, pre-existing unit failures, requirements, and ignore rules:** as verified in R1. The repaired Python files keep those contracts: seed resolution, episode allocation, diagnostics, `console.log` ownership, `--band` forwarding, and `band_override`.
- **`verify-suite` output contract:** the console line `Binary: %s... (%s)`, the text `different binary; results decide compatibility`, the `RESULT:` line, and the `suite-report.json` keys used by T1A (`status`, `required_passed/total`, `optional_passed/total`, `skipped`, `failed`, `baseline_simulator_sha256`, `current_simulator_sha256`, and per-case `status`/`capture_exit`/`compare_exit`) are unchanged at `regression_check.py:738-889`.
- **Local Sherpa data:** the optional Sherpa case's sources (`inputs/custom/sherpa/spring_lake/arpo-1-1-static-04172026/{run.ini,nodes.json}`) are present locally and match the snapshot's recorded digests, so T1A `--require-all` can run.

## 3. Scope and role-boundary assessment

- **Scope union:**
  - plan §15, including the post-S7 workflow amendment and the R1 repair amendment that adds `scripts/validation/tests/test_regression_check.py`;
  - the audit's "Files changed" list, which includes that test file.
  - Every audit-listed file is in plan §15. **No out-of-scope file.**
- **Dirty paths outside the union:** `CLAUDE.md` and the user's pre-existing untracked `docs/claude/` prompts and scout report are unchanged since R1. `baseline-review-and-test-charter.md` is the Reviewer's artifact.
- **Disposable repair evidence:** `outputs/p0-verification/reviewer-fixes/` (git-ignored via `outputs/`) holds the preserved originals, the reconstruction script and report, compare reports, the perturbed candidate, and the canonical-generator INI. This matches the amendment ("Preserve the old snapshots in disposable evidence"). The Tester must not modify it.
- **Git state:**
  - branch `arpo-main`, HEAD `a4e700d9947db57d06ade3ce391425681a3c2746`;
  - nothing staged and the stash is empty;
  - 22 tracked modified files and 32 untracked files (section 6.1).
  - No Git mutation by any role is evident.
- **Build and run gates:**
  - The Implementer reports no `./ns3` command and no real-simulator execution during the repairs. Consistent with that, `build/` changed only at H1 (12:40:54) and all H0B evidence predates it (08:51–08:54).
  - H1 was performed by the human.
- **This session:**
  - Commands used:
    - read-only Git commands: `git status`, `git diff`, `git rev-parse`, `git branch`, `git stash list`, and `git check-ignore`;
    - file and binary inspection: `shasum`, `stat`, `file`, `otool -L`, `strings`, `grep`, `find`, `ls`, and `sed -n`;
    - read-only Python inspection of the JSON and CSV evidence, with bytecode writes disabled.
  - The only file written is this charter. The one exception is scratch digest and status listings in the session scratchpad, outside the repository.

## 4. Audit-to-diff reconciliation (repairs)

| Audit claim (§6, §11) | Verified against | Result |
| --- | --- | --- |
| B1 still pending H1 (§11.1) | Binary hash and mtime | Superseded: H1 was performed after the audit (R-1) |
| `load_table` skips leading `#` metadata | `regression_check.py:134-153` | Match |
| Only positions blocks changed; other blocks byte-equal | Independent structural and byte-reproduction check | Match (6/6) |
| Manifest changed only six snapshot hashes; baseline binary hash unchanged | Recursive diff and byte reproduction | Match |
| Raw H0 files unchanged; positions mtimes 17:43:47–17:44:21 | 68 hashes and mtimes | Match |
| Manifest SHA `74bbf83a…`; six new snapshot digests (§6) | `shasum` | Match |
| Six `compare` MATCHes; perturbed x produces exactly one `positions.csv[row 0].x` difference | Evidence reports | Match |
| 22 pytest items: 16 RL, 6 regression/launcher | Test function and parameter enumeration (not executed by the Reviewer) | Count matches; execution is T3 |
| N1–N12 dispositions (§11.1) | Source, tests, and docs (section 2) | Match |
| `regression_check.py` "unchanged from approved H0A state" (§10.11) | Current source | **Stale (R-1)** |
| Script name `repair_p0_snapshots.py` (§11.3) | Retained `h0b-reconstruct.py` | Naming differs (R-1) |
| 22 tracked modified and 32 untracked files; nothing staged (§11.3) | `git status` | Match |

## 5. H0 and H0B evidence assessment

- **H0 raw evidence:** sound and preserved, as assessed in R1. It was not re-run and must not be re-run.
- **H0B:** the normalized snapshots now contain the positions coverage the plan claims. They were derived from the same pre-change raw captures (binary `370d8356…`) without re-simulation, and nothing except `tables["positions.csv"]` changed (section 2).
- **H0A aggregate PASS runs** (`suite-prechange*`, `suite-user-check`): these predate H0B and used the defective parser. They remain valid provenance for the non-positions tables only. The post-change T1A run is the first suite execution with positions comparison.

## 6. H1 build evidence

| Item | Value |
| --- | --- |
| Binary path | `/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/scratch/mesh-sim/ns3.42-sim-debug` |
| Supplied SHA-256 | `57613a69f88a6bb11832b62d8f80a4ccf46644b2d6cbe46f60a6bc645beb3722` |
| Observed SHA-256 | `57613a69f88a6bb11832b62d8f80a4ccf46644b2d6cbe46f60a6bc645beb3722` (not the H0 `370d8356…32d5`) |
| Supplied / observed mtime | 2026-09-15 12:40:54 -0400 / 2026-09-15 12:40:54 -0400 |
| Last C++ source edit | `src/cli/cli-parser.cc` 2026-09-15 08:04:23 (earlier than the binary) |
| Type / size | Mach-O 64-bit arm64 executable, 2,389,968 bytes |
| Embedded P0 strings | See B1 (all present; old N5 fragment absent) |
| Build completion | Human-reported: `./ns3 build` completed and returned to the shell prompt |
| **Assessment** | **SATISFIED** |

### 6.1 Recorded Git status (mesh-sim scope, at this review)

`git status --porcelain=v1 -uall -- .` from the mesh-sim root lists 54 entries. Git prints paths relative to the repository root. T0 compares the Tester's output against this exact list, after dropping only the Tester's own `baseline-test-results.md` line. The list is embedded verbatim in the T0 block.

## 7. Bounded execution charter

**AUTHORIZED.** Run the rows exactly as written, against the binary whose SHA-256 is `57613a69f88a6bb11832b62d8f80a4ccf46644b2d6cbe46f60a6bc645beb3722`.

### Common rules

- **Owner:** the Tester for every row. The human owned H1, which is complete.
- **Order:** run the rows in this order: T0, T1, T1A, T2, T7, T8, T6, T3, T4, T5.
  - If T0 is not PASS, every other row is BLOCKED.
  - If T3 is not PASS, T4 and T5 are BLOCKED.
  - Otherwise, rows are independent: run every remaining row even after a FAIL.
- **Blocks:** run each code block as one `sh`/`zsh` invocation, from the working directory named in its first `cd`, exactly as written. Record the full console output and every `… exit=` line in the results document.
- **Verdicts:**
  - PASS: every pass criterion of the row is met.
  - FAIL: any criterion is not met, unless the failure interpretation says BLOCKED.
  - BLOCKED: a required binary, toolchain, network access, local data, or a precondition is unavailable, or a dependency row did not pass.
  - Never convert a FAIL into a deferral.
- **Write authority.** The Tester may create or modify only the following:
  1. `docs/rl-program/p0-baseline/baseline-test-results.md`, the one durable artifact.
  2. New run products under `outputs/p0-verification/{t0,t1,t1a,t2,t3,t4,t5,t6,t7,t8,rl}/`. This includes:
     - logs and consoles;
     - the T6 temporary scenario copy under `outputs/p0-verification/t6/legacy-scenario/`;
     - the T5 temporary `sweep.ini`;
     - the fresh test venv at `outputs/p0-verification/t3/venv/`.
  3. `outputs/p0-regression/suite-postchange/` and `outputs/p0-regression/suite-postchange-require-all/`. T0 proves these are absent first.
  4. Exactly one new timestamped sweep directory `outputs/<YYYY-MM>/<DD>/<HH-MM-SS>/`, created by the T5 sweep command. Record its path.
  5. Git-ignored standalone-test build products under `tests/unit/`:
     - Binaries: T1's `make clean` removes and `make test` rebuilds `tests/unit/config/config-validator-test`, `tests/unit/eval/eval-test`, `tests/unit/routing/mesh-router-test`, and `tests/unit/traffic/traffic-matrix-test`.
     - Stub directories: the same targets remove and rebuild the generated `ns3/` stub directories in `tests/unit/{eval,routing,traffic}/`.

     This is the only authorized deletion of a pre-existing path.
  6. Git-ignored Python bytecode caches (`__pycache__/*.pyc`) under `scripts/`, created when `python -m scripts…` imports modules.
  7. Temporary directories under the system temporary directory:
     - T2's `mktemp -d`, removed by its own `trap`;
     - pytest's `tmp_path` directories in T3, including pytest's own retention cleanup of its `pytest-of-<user>` directories.
  8. Per-user package caches written by pip, matplotlib, or torch during T3, T4, or T5 (for example the pip download cache and the matplotlib font cache).
- **Prohibited:**
  - editing source, tests, scripts, inputs, fixtures, the manifest, the plan, the audit, this charter, or other documentation;
  - creating or altering the project `.venv/`;
  - modifying or deleting `outputs/p0-verification/reviewer-fixes/`, `outputs/p0-regression/{before,suite-prechange,suite-prechange-readable,suite-user-check}/`, or any other pre-existing output;
  - deleting any path not covered by item 5;
  - `./ns3` configure, build, or run;
  - any Git mutation, delegation, extra rows, or rewritten commands.
- **Unavailable dependencies:** a missing binary, missing toolchain, no network for pip, or absent Sherpa data makes the affected row or portion BLOCKED, never PASS.
- **Constants used in the blocks:**
  - mesh-sim root: `/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/scratch/mesh-sim`
  - `BIN=/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/scratch/mesh-sim/ns3.42-sim-debug`
  - `LIB=/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/lib`
  - H1 SHA-256: `57613a69f88a6bb11832b62d8f80a4ccf46644b2d6cbe46f60a6bc645beb3722`
  - H0 (pre-change) SHA-256: `370d8356186a2b97d988061019cbd8ab4391c191f076da8b559e531854da32d5`

### T0 — Binary, reviewed-code, and evidence provenance preflight (additional; see section 8)

- **Working directory:** mesh-sim root
- **Owner:** Tester

```sh
cd /Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/scratch/mesh-sim
BIN=/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/scratch/mesh-sim/ns3.42-sim-debug
PRE=""
for p in outputs/p0-verification/t0 outputs/p0-verification/t1 outputs/p0-verification/t1a outputs/p0-verification/t2 outputs/p0-verification/t3 outputs/p0-verification/t4 outputs/p0-verification/t5 outputs/p0-verification/t6 outputs/p0-verification/t7 outputs/p0-verification/t8 outputs/p0-verification/rl outputs/p0-regression/suite-postchange outputs/p0-regression/suite-postchange-require-all; do
  if [ -e "$p" ]; then PRE="$PRE $p"; fi
done
mkdir -p outputs/p0-verification/t0
if [ -z "$PRE" ]; then echo "PRECONDITION: run paths absent"; else echo "PRECONDITION: EXISTS:$PRE"; fi | tee outputs/p0-verification/t0/precondition.txt
if [ -d outputs/p0-verification/reviewer-fixes ]; then echo "reviewer-fixes evidence: present (preserve, do not modify)"; else echo "reviewer-fixes evidence: absent"; fi | tee -a outputs/p0-verification/t0/precondition.txt
shasum -a 256 "$BIN" | tee outputs/p0-verification/t0/bin.sha256
stat -f '%Sm' -t '%Y-%m-%dT%H:%M:%S' "$BIN" | tee outputs/p0-verification/t0/bin.mtime
for s in band_source jammer_path_enabled "is deprecated; use 'all_links_los'" "(jammer interference enabled)" "co-channel interference computed"; do printf '%s: ' "$s"; strings "$BIN" | grep -c -F -- "$s"; done | tee outputs/p0-verification/t0/p0-strings.txt
git rev-parse HEAD | tee outputs/p0-verification/t0/head.txt
git status --porcelain=v1 -uall -- . > outputs/p0-verification/t0/git-status.txt
grep -v -F 'scratch/mesh-sim/docs/rl-program/p0-baseline/baseline-test-results.md' outputs/p0-verification/t0/git-status.txt > outputs/p0-verification/t0/git-status-filtered.txt
diff outputs/p0-verification/t0/git-status-filtered.txt - > outputs/p0-verification/t0/git-status.diff <<'EOF'
 M scratch/mesh-sim/CLAUDE.md
 M scratch/mesh-sim/README.md
 M scratch/mesh-sim/TODO.md
 M scratch/mesh-sim/inputs/README.md
 M scratch/mesh-sim/inputs/baselines/rl-test/run.ini
 M scratch/mesh-sim/scripts/rl/__init__.py
 M scratch/mesh-sim/scripts/rl/env/mesh_env.py
 M scratch/mesh-sim/scripts/rl/train.py
 M scratch/mesh-sim/scripts/sweep/runner.py
 M scratch/mesh-sim/scripts/validation/README.md
 M scratch/mesh-sim/scripts/validation/build_config_files.py
 M scratch/mesh-sim/scripts/validation/run_batch.py
 M scratch/mesh-sim/sim.cc
 M scratch/mesh-sim/src/cli/cli-parser.cc
 M scratch/mesh-sim/src/cli/cli-parser.h
 M scratch/mesh-sim/src/config/config-loader.cc
 M scratch/mesh-sim/src/config/config-validator.cc
 M scratch/mesh-sim/src/domain/sim-config.h
 M scratch/mesh-sim/src/io/run-logger.h
 M scratch/mesh-sim/src/rl/rl-bridge.cc
 M scratch/mesh-sim/tests/integration/cli-integration-test.sh
 M scratch/mesh-sim/tests/unit/config/config-validator-test.cc
?? scratch/mesh-sim/.gitignore
?? scratch/mesh-sim/docs/claude/GIT_PR_PROMPT.md
?? scratch/mesh-sim/docs/claude/IMPLEMENTER_PROMPT.md
?? scratch/mesh-sim/docs/claude/ORCHESTRATOR_PROMPT.md
?? scratch/mesh-sim/docs/claude/PLANNER_PROMPT.md
?? scratch/mesh-sim/docs/claude/PROGRESS_PROMPT.md
?? scratch/mesh-sim/docs/claude/README.md
?? scratch/mesh-sim/docs/claude/REVIEWER_PROMPT.md
?? scratch/mesh-sim/docs/claude/SCOUT_PROMPT.md
?? scratch/mesh-sim/docs/claude/TESTER_PROMPT.md
?? scratch/mesh-sim/docs/rl-program/p0-baseline/baseline-implementation-audit.md
?? scratch/mesh-sim/docs/rl-program/p0-baseline/baseline-implementation-plan.md
?? scratch/mesh-sim/docs/rl-program/p0-baseline/baseline-review-and-test-charter.md
?? scratch/mesh-sim/docs/rl-program/p0-baseline/baseline-scout-report.md
?? scratch/mesh-sim/inputs/baselines/p0-jammer-smoke/jammers.json
?? scratch/mesh-sim/inputs/baselines/p0-jammer-smoke/nodes.json
?? scratch/mesh-sim/inputs/baselines/p0-jammer-smoke/run.ini
?? scratch/mesh-sim/inputs/baselines/p0-smoke/nodes.json
?? scratch/mesh-sim/inputs/baselines/p0-smoke/run.ini
?? scratch/mesh-sim/requirements.txt
?? scratch/mesh-sim/scripts/rl/bootstrap_venv.py
?? scratch/mesh-sim/scripts/rl/tests/fake_sim.py
?? scratch/mesh-sim/scripts/rl/tests/test_mesh_env.py
?? scratch/mesh-sim/scripts/validation/regression_check.py
?? scratch/mesh-sim/scripts/validation/tests/test_regression_check.py
?? scratch/mesh-sim/tests/fixtures/regression/p0/baseline-building-blockage.json
?? scratch/mesh-sim/tests/fixtures/regression/p0/baseline-static-los.json
?? scratch/mesh-sim/tests/fixtures/regression/p0/baseline-synthetic-jammer.json
?? scratch/mesh-sim/tests/fixtures/regression/p0/baseline-three-node-relay.json
?? scratch/mesh-sim/tests/fixtures/regression/p0/calfex-06-25-1509-1513.json
?? scratch/mesh-sim/tests/fixtures/regression/p0/manifest.json
?? scratch/mesh-sim/tests/fixtures/regression/p0/sherpa-spring-lake-static.json
EOF
echo "git-status diff exit=$?"
shasum -a 256 -c - > outputs/p0-verification/t0/reviewed-digests.txt 2>&1 <<'EOF'
cd31851b1f6463cb7a63d7b43d4ef5040bd2d8478dedbc6d8fecd7cb9cf721d4  sim.cc
0b3cb18a15148872148c4cb427fb591c93a4b4443d4d2d1e1ca68265c6d811bf  src/domain/sim-config.h
be8a3d78435dc542182f3d14ea6ec1175f6b33af94accc180b593c1791ad400d  src/config/config-loader.cc
3c0e1335576787dbcb2bff86d4f1f738f180dd269c4a11397e4fdf522391bab6  src/config/config-validator.cc
8d72048939671cd127b85e7b8c9c2851b3dad0ff71b403de301fa1a5c58988da  src/cli/cli-parser.h
bcdc25126a4b771e3bf66062bfcae9d1116c8dfa6ece81e783d5ec25a34104ee  src/cli/cli-parser.cc
590a9bf16c7d6921613cca39066fe1433b0a28a0bd14e3fa4d5e56a858019346  src/io/run-logger.h
ccbc09c2c32081c5db7d6321a882c4318b4ce718e9e6984c91fd76f30bde818f  src/rl/rl-bridge.cc
9b027ab2bde48c472e9f046fd76b5543183d0859136237f27c0893a27ba0bc4f  scripts/rl/__init__.py
a252c4633c53d33e5c52e91249eb5441cd54ebd18c76603fdee8d861d2aaa3aa  scripts/rl/env/mesh_env.py
51969118d46a2b02576c194bd7ec084607325d83224fc2ac95726b9ab34f3eeb  scripts/rl/train.py
a74af8f15026b7aabda05e2327232931171a93f0c51dad9561efa825f2ed1174  scripts/rl/bootstrap_venv.py
d4efcf57942c8142fa63721bf820be87ef5ec439cbaa11f7fbd0f217a2462cab  scripts/rl/tests/fake_sim.py
20686344bf7cb3f314040ec02f25cde8eac353579c721203fe975267ff560698  scripts/rl/tests/test_mesh_env.py
b5a081d2526057b19506b478afabbba54f7d35bda85fff85cf7db4393d4fc19c  scripts/sweep/runner.py
74db1131e8e3c285382ccf149e1024377b294be1a8d49443c7e210028e1b419a  scripts/validation/build_config_files.py
a09947a641fd31fcab7bd067af0c51a79c1f4d8cda9310868db0dd51c5d14209  scripts/validation/run_batch.py
46512a16be9f27da1ce8c0654474d5cbc3eb668b97f79779a96fb58ce7278a1d  scripts/validation/regression_check.py
822e26d191229adf45c69c57ee25e72c58224a827e4428621c0784637e6b6f53  scripts/validation/tests/test_regression_check.py
8508263334ad78b42466aeebb480006177a735346cec5c653f2390251949850a  requirements.txt
7868843b83e0f3d3f491cf2ded77782dd04f4438b46f2c9fd99f7f2acaec37a8  tests/unit/config/config-validator-test.cc
fe8719c83a3fb876aecef054ce6bdf558e7928f6cfca13e9327cc4b414081c42  tests/integration/cli-integration-test.sh
6a9da94aa654ad87df1ee0c54b888a638c25b80c14a4e55bef8cda81b8e4b91d  inputs/baselines/rl-test/run.ini
ddd91f7647e120e3aa6adadc4bb5a5c7160fbad801ecc94d935304c05e9523c7  inputs/baselines/p0-smoke/run.ini
12fbcb0e17633971114c049e42d36f7b5d3596420e4d6a7221bcb2a6b30ec829  inputs/baselines/p0-smoke/nodes.json
bb923178325633632fc4a9841a9fb14e112f8fa6e257bdbb63d3f7ef89129f69  inputs/baselines/p0-jammer-smoke/run.ini
12fbcb0e17633971114c049e42d36f7b5d3596420e4d6a7221bcb2a6b30ec829  inputs/baselines/p0-jammer-smoke/nodes.json
2a623a4c81b874ec08eb7600dd3d05a36e33174ad589a3d8da64258e7bd4e2fd  inputs/baselines/p0-jammer-smoke/jammers.json
10e8683c440bc83e5d4d89a7b655cd541745dd2b9fe079e7307877f9245816d5  tests/fixtures/regression/p0/baseline-static-los.json
4633c33619210ae9b6e608b0f1917527d05ed4983c18959d3b0acc86d0481bf3  tests/fixtures/regression/p0/baseline-building-blockage.json
ed8f888924da4acdb0f558b6b76a85713174ae32842c8f8a12921a0aebaba338  tests/fixtures/regression/p0/baseline-three-node-relay.json
278fe57b3eb298e5c6a28dd7839d326dfc9b431a9da05680c46ee9b4320d4924  tests/fixtures/regression/p0/sherpa-spring-lake-static.json
1c9b14f2d77869fa18df48f46f299659317ce3789e469413d78c7f0a24422512  tests/fixtures/regression/p0/calfex-06-25-1509-1513.json
39152a1fec6bb0f170840696849eee2732ab264707d91309842d16dda6fb9ab7  tests/fixtures/regression/p0/baseline-synthetic-jammer.json
74bbf83a09b64b6fe822bfab74ea97f4fe17369635d317b190ed32abe0d2c2eb  tests/fixtures/regression/p0/manifest.json
EOF
echo "reviewed-digests exit=$?"
printf 'digest OK lines='; grep -c ': OK$' outputs/p0-verification/t0/reviewed-digests.txt
grep -v ': OK$' outputs/p0-verification/t0/reviewed-digests.txt
```

- **Expected evidence:**
  - the precondition lines;
  - the binary hash and mtime;
  - five string counts;
  - HEAD;
  - `git-status.txt` and an empty `git-status.diff`;
  - `reviewed-digests.txt` with 35 `OK` lines.
- **Pass criteria (all required):**
  - `precondition.txt` contains `PRECONDITION: run paths absent`.
  - `bin.sha256` begins with `57613a69f88a6bb11832b62d8f80a4ccf46644b2d6cbe46f60a6bc645beb3722`.
  - `bin.mtime` is `2026-09-15T12:40:54`.
  - The string counts are:
    - `band_source` ≥ 1
    - `jammer_path_enabled` ≥ 1
    - `is deprecated; use 'all_links_los'` ≥ 1
    - `(jammer interference enabled)` ≥ 1
    - `co-channel interference computed` = 0
  - HEAD is `a4e700d9947db57d06ade3ce391425681a3c2746`.
  - `git-status diff exit=0`.
  - `reviewed-digests exit=0` and `digest OK lines=35`.
- **Output location:** `outputs/p0-verification/t0/`
- **Failure interpretation:**
  - **`PRECONDITION: EXISTS:`:** BLOCKED. Ask the human to move the named paths. Do not delete them.
  - **Wrong hash or mtime, any wrong string count, or the hash equals H0:** the binary is not the reviewed H1 build. BLOCKED; every row is BLOCKED and the case returns to the human and the Reviewer.
  - **HEAD mismatch, non-empty `git-status.diff`, or any `FAILED` digest line:** code, evidence, or Git state changed after this review. BLOCKED; return to the Reviewer. Do not proceed.

### T1 — Standalone unit tests

- **Working directory:** `tests/`
- **Owner:** Tester

```sh
cd /Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/scratch/mesh-sim/tests
mkdir -p ../outputs/p0-verification/t1
make clean > ../outputs/p0-verification/t1/clean.log 2>&1; echo "clean exit=$?"
make test > ../outputs/p0-verification/t1/make-test.log 2>&1; echo "make test exit=$?"
for d in unit/config unit/eval unit/routing unit/traffic; do make -C "$d" test > "../outputs/p0-verification/t1/$(basename "$d").log" 2>&1; echo "$d exit=$?"; done
grep -H -E "passed, [0-9]+ failed|^FAIL: " ../outputs/p0-verification/t1/*.log
```

- **Expected evidence:**
  - `make test` exits nonzero and stops at `unit/config`, as it did at baseline (N9, documented in README).
  - the per-suite summaries.
- **Pass criteria:** the per-suite results are exactly:
  - `unit/config`: `51 passed, 2 failed.` The only FAIL lines are `valid config should pass` and `gateway with valid node ID accepted`.
  - `unit/eval`: `156 passed, 2 failed.` The only FAIL lines are `table clamps at highest MCS` and `mcs_index at 50 dB clamps to 14`.
  - `unit/routing`: `42 passed, 0 failed.`
  - `unit/traffic`: `32 passed, 0 failed.`
  - `unit/config` and `unit/eval` exit nonzero; `unit/routing` and `unit/traffic` exit 0.
- **Reviewer acceptance:** the Reviewer accepts exactly these four pre-existing failures.
  - They were recorded before any edits (audit §2).
  - The config pair is caused by `node-spec.h:87`/`makeValid()`, which P0 did not touch.
  - The eval pair lives in unmodified `src/eval` and `tests/unit/eval`.
  - The repairs changed no C++ test and no unit-tested C++ source.
- **Output location:** `outputs/p0-verification/t1/`. Rebuilt test binaries appear in `tests/unit/*/` (write authority, item 5).
- **Failure interpretation:**
  - Any other failure, any change in pass counts, or a compile error in changed files is a P0 regression: FAIL.
  - A missing compiler or toolchain: BLOCKED.

### T1A — Post-change regression suite

- **Working directory:** mesh-sim root
- **Owner:** Tester

```sh
cd /Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/scratch/mesh-sim
BIN=/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/scratch/mesh-sim/ns3.42-sim-debug
mkdir -p outputs/p0-verification/t1a
python3 - > outputs/p0-verification/t1a/snapshot-structure.txt 2>&1 <<'EOF'
import glob, json, sys
bad = []
for f in sorted(glob.glob("tests/fixtures/regression/p0/*.json")):
    if f.endswith("manifest.json"):
        continue
    cols = json.load(open(f))["tables"]["positions.csv"]["columns"]
    print(f, cols)
    if cols != ["time_s", "node_id", "x", "y", "z", "node_type", "active"]:
        bad.append(f)
print("BAD", bad)
sys.exit(1 if bad else 0)
EOF
echo "structure exit=$?"
python3 -m scripts.validation.regression_check verify-suite --sim-binary "$BIN" --manifest tests/fixtures/regression/p0/manifest.json --out outputs/p0-regression/suite-postchange > outputs/p0-verification/t1a/suite-postchange.console 2>&1; echo "suite exit=$?"
python3 -m scripts.validation.regression_check verify-suite --sim-binary "$BIN" --manifest tests/fixtures/regression/p0/manifest.json --out outputs/p0-regression/suite-postchange-require-all --require-all > outputs/p0-verification/t1a/suite-postchange-require-all.console 2>&1; echo "require-all exit=$?"
python3 - outputs/p0-regression/suite-postchange/suite-report.json outputs/p0-regression/suite-postchange-require-all/suite-report.json > outputs/p0-verification/t1a/report-check.txt 2>&1 <<'EOF'
import json, sys
H1 = "57613a69f88a6bb11832b62d8f80a4ccf46644b2d6cbe46f60a6bc645beb3722"
BASE = "370d8356186a2b97d988061019cbd8ab4391c191f076da8b559e531854da32d5"
ok = H1 != BASE
for p in sys.argv[1:]:
    r = json.load(open(p))
    print(p, r["status"], r["required_passed"], r["required_total"], r["optional_passed"],
          r["optional_total"], r["skipped"], r["failed"], r["current_simulator_sha256"])
    ok = ok and r["status"] == "PASS" and r["required_passed"] == r["required_total"] == 5 \
        and r["optional_passed"] == r["optional_total"] == 1 and r["skipped"] == 0 \
        and r["failed"] == 0 and r["baseline_simulator_sha256"] == BASE \
        and r["current_simulator_sha256"] == H1 \
        and all(c["status"] == "PASS" and c["capture_exit"] == 0 and c["compare_exit"] == 0 for c in r["cases"])
print("OK" if ok else "NOT OK")
sys.exit(0 if ok else 1)
EOF
echo "report-check exit=$?"
```

- **Expected evidence:**
  - The structure check prints six snapshots, each with the seven positions columns.
  - Each console shows `Binary: 57613a69f88a... (different binary; results decide compatibility)`, six `PASS` rows, and `RESULT: PASS — required 5/5, optional 1/1, skipped 0`.
  - Both `suite-report.json` files exist.
- **Pass criteria:** structure exit 0, suite exit 0, require-all exit 0, and report-check prints `OK` with exit 0.
- **Output location:**
  - `outputs/p0-regression/suite-postchange/`
  - `outputs/p0-regression/suite-postchange-require-all/`
  - `outputs/p0-verification/t1a/`
- **Failure interpretation:**
  - **Structure failure:** tracked fixtures changed after review (T0 should already have caught this). BLOCKED; return to the Reviewer.
  - **Integrity error (exit 2) before any case runs:** tracked evidence changed. FAIL.
  - **A case FAIL with a `comparison.json` mismatch:** unintended simulator behavior change. This now includes node trajectories: a `positions.csv[...]` difference is a mobility or position regression. FAIL. Inspect the per-case report; never adjust the tolerance or the snapshots.
  - **Missing Sherpa data:** a Sherpa `SKIP` in the default run, or a `FAIL` for missing data under `--require-all`, means local data is unavailable. BLOCKED for the Sherpa portion only, not PASS.
  - **`matches reference` in the console:** the pre-change binary was used, a B1 recurrence. BLOCKED.
  - **`run.log` differences** are intentionally not compared.

### T2 — Real-binary CLI integration

- **Working directory:** `tests/`
- **Owner:** Tester

```sh
cd /Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/scratch/mesh-sim/tests
mkdir -p ../outputs/p0-verification/t2
MESH_SIM_BIN=/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/scratch/mesh-sim/ns3.42-sim-debug make integration > ../outputs/p0-verification/t2/integration.log 2>&1; echo "integration exit=$?"
grep -E "^Binary:|PASS:|FAIL:|^Results:" ../outputs/p0-verification/t2/integration.log
```

- **Expected evidence:** a `Binary:` line naming `BIN`, eight `PASS:` lines (tests 1–8), and `Results: 8 passed, 0 failed.`
- **Pass criteria (all required):**
  - Exit 0.
  - Exactly 8 `PASS:` lines and 0 `FAIL:` lines.
  - Test 7 reads `run.log records band = sub-6 and band_source = cli`.
  - Test 8 reads `jammer band A/B differs in N matched links` with N ≥ 1.
- **Output location:** `outputs/p0-verification/t2/integration.log`. The script's `mktemp -d` run directories are removed by its own `trap`.
- **Failure interpretation:**
  - Tests 1–3: binary or loader problem.
  - Tests 4–5: exit-code or message plumbing.
  - Test 6: output layout or RL closed-stdin handling.
  - Test 7: CLI band precedence or `run.log`.
  - Test 8: jammer inactive, frequency mismatch, band not forwarded, or `run.log` jammer fields. Do not change physics; inspect `run.log` and the archived `jammers.json`.

### T7 — Band resolution without a CLI override (additional; see section 8)

- **Working directory:** mesh-sim root
- **Owner:** Tester

```sh
cd /Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/scratch/mesh-sim
BIN=/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/scratch/mesh-sim/ns3.42-sim-debug
LIB=/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/lib
mkdir -p outputs/p0-verification/t7
DYLD_LIBRARY_PATH="$LIB" LD_LIBRARY_PATH="$LIB" "$BIN" --run-config=inputs/baselines/01-static-los-baseline/run.ini --seed=1 --output-dir=outputs/p0-verification/t7/default-band </dev/null > outputs/p0-verification/t7/default-band.console 2>&1; echo "default-band exit=$?"
DYLD_LIBRARY_PATH="$LIB" LD_LIBRARY_PATH="$LIB" "$BIN" --run-config=inputs/baselines/p0-jammer-smoke/run.ini --seed=1 --output-dir=outputs/p0-verification/t7/ini-band </dev/null > outputs/p0-verification/t7/ini-band.console 2>&1; echo "ini-band exit=$?"
grep -H -E '^  (--band|band|band_source|jammer_path_enabled|jammers\.configured|jammers\.enabled) +=|^  jammer-0:' outputs/p0-verification/t7/default-band/run.log outputs/p0-verification/t7/ini-band/run.log
python3 -m scripts.validation.regression_check compare --baseline tests/fixtures/regression/p0/baseline-static-los.json --candidate outputs/p0-verification/t7/default-band --report outputs/p0-verification/t7/default-band-compare.json; echo "compare default exit=$?"
python3 -m scripts.validation.regression_check compare --baseline tests/fixtures/regression/p0/baseline-synthetic-jammer.json --candidate outputs/p0-verification/t7/ini-band --report outputs/p0-verification/t7/ini-band-compare.json; echo "compare ini exit=$?"
```

- **Expected evidence:** two run directories, the grep lines, and two `MATCH:` lines.
- **Pass criteria (all required):**
  - Both runs exit 0.
  - `default-band/run.log` has `--band = (not set)`, `band = mmwave`, `band_source = default`, and `jammer_path_enabled = false`.
  - `ini-band/run.log` has `--band = (not set)`, `band = sub-6`, `band_source = run.ini`, `jammers.configured = 1`, `jammers.enabled = 1`, and `jammer_path_enabled = true`.
  - `ini-band/run.log` has one `jammer-0:` line containing `enabled=true type=constant target_freq_mhz=[2400] tx_power_dbm=30 tx_array_gain_dbi=12 duty_cycle=1 max_range_m=0 beamwidth_deg=360 azimuth_deg=0 zenith_deg=90 motion=static`.
  - Both `compare` runs exit 0 and print `MATCH`.
- **Output location:** `outputs/p0-verification/t7/`
- **Failure interpretation:**
  - A wrong `band`/`band_source`: loader or CLI resolution defect.
  - A compare mismatch, including a `positions.csv` difference: the default or `run.ini` band path produces different results from the pre-change explicit `--band` path. That is a `cfg.band` plumbing regression: FAIL.
  - A wrong jammer line: logging defect only (physics is judged by compare).

### T8 — Closed and malformed RL action input maps to Stay (additional; see section 8)

- **Working directory:** mesh-sim root
- **Owner:** Tester

```sh
cd /Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/scratch/mesh-sim
BIN=/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/scratch/mesh-sim/ns3.42-sim-debug
LIB=/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/lib
mkdir -p outputs/p0-verification/t8
DYLD_LIBRARY_PATH="$LIB" LD_LIBRARY_PATH="$LIB" "$BIN" --run-config=inputs/baselines/p0-smoke/run.ini --seed=1 --output-dir=outputs/p0-verification/t8/closed </dev/null > outputs/p0-verification/t8/closed.stdout 2> outputs/p0-verification/t8/closed.stderr; echo "closed exit=$?"
printf 'not-json\nnot-json\nnot-json\nnot-json\nnot-json\nnot-json\n' | DYLD_LIBRARY_PATH="$LIB" LD_LIBRARY_PATH="$LIB" "$BIN" --run-config=inputs/baselines/p0-smoke/run.ini --seed=1 --output-dir=outputs/p0-verification/t8/malformed > outputs/p0-verification/t8/malformed.stdout 2> outputs/p0-verification/t8/malformed.stderr; echo "malformed exit=$?"
for f in closed malformed; do printf '%s closed-warn=' "$f"; grep -c -F "RL action stream closed; holding position (Stay)." "outputs/p0-verification/t8/$f.stderr"; printf '%s malformed-warn=' "$f"; grep -c -F "malformed RL action JSON; holding position (Stay)." "outputs/p0-verification/t8/$f.stderr"; done
python3 - outputs/p0-verification/t8/closed/seed-1/positions.csv outputs/p0-verification/t8/malformed/seed-1/positions.csv <<'EOF'
import csv, sys
ok = True
for p in sys.argv[1:]:
    rows = list(csv.reader(line for line in open(p) if not line.startswith("#")))
    hdr, data = rows[0], rows[1:]
    i = {k: hdr.index(k) for k in ("node_id", "x", "y", "z")}
    relay = [r for r in data if r[i["node_id"]] in ("2", "relay")]
    moved = [r for r in relay if abs(float(r[i["x"]]) - 50) > 1e-9
             or abs(float(r[i["y"]]) - 50) > 1e-9 or abs(float(r[i["z"]]) - 10) > 1e-9]
    print(p, "relay_rows", len(relay), "moved_rows", len(moved))
    ok = ok and len(relay) >= 4 and not moved
sys.exit(0 if ok else 1)
EOF
echo "position-check exit=$?"
```

- **Expected evidence:** two runs, the warning counts, and relay row counts.
- **Pass criteria (all required):**
  - Both simulator exits are 0.
  - `closed`: closed-warn = 1 and malformed-warn = 0.
  - `malformed`: malformed-warn = 1 and closed-warn = 0.
  - The position check exits 0, with ≥ 4 relay rows and 0 moved rows for each run.
  - Both stdout files contain only JSON lines, one per tick.
- **Output location:** `outputs/p0-verification/t8/`
- **Failure interpretation:**
  - Relay x decreasing: the legacy −X default survived (`ReadAction` regression).
  - Warning count other than 1: warning logic defect.
  - Non-JSON on stdout: RL protocol pollution.

### T6 — Legacy reward alias

- **Working directory:** mesh-sim root
- **Owner:** Tester

```sh
cd /Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/scratch/mesh-sim
BIN=/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/scratch/mesh-sim/ns3.42-sim-debug
LIB=/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/lib
mkdir -p outputs/p0-verification/t6/legacy-scenario
cp inputs/baselines/p0-smoke/nodes.json outputs/p0-verification/t6/legacy-scenario/nodes.json
sed -E 's/^(reward_type[[:space:]]*=[[:space:]]*)all_links_los$/\1mean_sinr/' inputs/baselines/p0-smoke/run.ini > outputs/p0-verification/t6/legacy-scenario/run.ini
diff inputs/baselines/p0-smoke/run.ini outputs/p0-verification/t6/legacy-scenario/run.ini > outputs/p0-verification/t6/ini.diff; echo "diff exit=$?"; cat outputs/p0-verification/t6/ini.diff
DYLD_LIBRARY_PATH="$LIB" LD_LIBRARY_PATH="$LIB" "$BIN" --run-config=outputs/p0-verification/t6/legacy-scenario/run.ini --seed=1 --output-dir=outputs/p0-verification/t6/legacy </dev/null > outputs/p0-verification/t6/legacy.stdout 2> outputs/p0-verification/t6/legacy.stderr; echo "legacy exit=$?"
DYLD_LIBRARY_PATH="$LIB" LD_LIBRARY_PATH="$LIB" "$BIN" --run-config=inputs/baselines/p0-smoke/run.ini --seed=1 --output-dir=outputs/p0-verification/t6/canonical </dev/null > outputs/p0-verification/t6/canonical.stdout 2> outputs/p0-verification/t6/canonical.stderr; echo "canonical exit=$?"
printf 'legacy deprecation='; grep -c -F "reward_type 'mean_sinr' is deprecated; use 'all_links_los'." outputs/p0-verification/t6/legacy.stderr
printf 'canonical deprecation='; grep -c -F "reward_type 'mean_sinr' is deprecated; use 'all_links_los'." outputs/p0-verification/t6/canonical.stderr
grep -H -E '^  rl\.reward_(type|alias) +=' outputs/p0-verification/t6/legacy/run.log outputs/p0-verification/t6/canonical/run.log
python3 - outputs/p0-verification/t6/legacy.stdout outputs/p0-verification/t6/canonical.stdout <<'EOF'
import json, sys
seqs = [[json.loads(l)["reward"] for l in open(p) if l.strip()] for p in sys.argv[1:3]]
print("legacy", seqs[0])
print("canonical", seqs[1])
sys.exit(0 if seqs[0] and seqs[0] == seqs[1] else 1)
EOF
echo "reward-compare exit=$?"
cmp outputs/p0-verification/t6/legacy.stdout outputs/p0-verification/t6/canonical.stdout; echo "stdout cmp exit=$?"
```

- **Expected evidence:** a one-line ini diff (`all_links_los` → `mean_sinr`), two runs, warning counts, `run.log` reward lines, reward sequences, and the `cmp` result.
- **Pass criteria (all required):**
  - diff exit 1, with exactly one changed `reward_type` line.
  - Both simulator exits are 0.
  - legacy deprecation = 1; canonical deprecation = 0.
  - `legacy/run.log` has `rl.reward_type = all_links_los` and `rl.reward_alias = mean_sinr`.
  - `canonical/run.log` has `rl.reward_type = all_links_los` and `rl.reward_alias = none`.
  - reward-compare exit 0 (non-empty, identical sequences).
  - stdout cmp exit 0 (byte-identical RL stream for the same fixed scenario and actions).
- **Output location:** `outputs/p0-verification/t6/` (the temporary scenario copy lives here, never under `inputs/`)
- **Failure interpretation:**
  - No or duplicate warning: `sim.cc` warning defect.
  - Wrong `run.log` fields: logging defect.
  - Reward or stdout difference: the alias changed reward arithmetic or protocol. That is a stop condition; FAIL.

### T3 — Fresh Python environment and focused contracts (RL and regression/launcher tests)

- **Working directory:** mesh-sim root
- **Owner:** Tester

```sh
cd /Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/scratch/mesh-sim
mkdir -p outputs/p0-verification/t3
python3 scripts/rl/bootstrap_venv.py --venv outputs/p0-verification/t3/venv > outputs/p0-verification/t3/bootstrap.log 2>&1; echo "bootstrap exit=$?"
grep -E '^\+ ' outputs/p0-verification/t3/bootstrap.log | tee outputs/p0-verification/t3/bootstrap-commands.txt
printf 'bootstrap command lines='; grep -c -E '^\+ ' outputs/p0-verification/t3/bootstrap.log
python3 scripts/rl/bootstrap_venv.py --venv outputs/p0-verification/t3/venv --check > outputs/p0-verification/t3/bootstrap-check.log 2>&1; echo "check exit=$?"
grep -E '^(python|gymnasium|numpy|stable-baselines3|sb3-contrib|torch|pandas|matplotlib|pytest)==' outputs/p0-verification/t3/bootstrap-check.log
PYTHONDONTWRITEBYTECODE=1 outputs/p0-verification/t3/venv/bin/python -m pytest scripts/rl/tests scripts/validation/tests -q -rs -p no:cacheprovider > outputs/p0-verification/t3/pytest.log 2>&1; echo "pytest exit=$?"
tail -n 5 outputs/p0-verification/t3/pytest.log
```

- **Expected evidence:**
  - A fresh venv is created from `requirements.txt`.
  - Exactly two bootstrap command lines.
  - The check log shows `python==3.x` (3.10 or newer) and eight `name==version` lines.
  - The pytest summary.
- **Pass criteria (all required):**
  - bootstrap exit 0 and check exit 0.
  - `bootstrap command lines=2` (N11: no pip self-upgrade):
    - the first line contains ` -m venv ` and ends with `/outputs/p0-verification/t3/venv`;
    - the second ends with `/outputs/p0-verification/t3/venv/bin/python -m pip install -r /Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/scratch/mesh-sim/requirements.txt`.
  - The check log shows exactly `gymnasium==1.3.0`, `numpy==2.4.6`, `stable-baselines3==2.9.0`, `sb3-contrib==2.9.0`, `torch==2.14.0`, `pandas==3.0.5`, `matplotlib==3.11.2`, `pytest==9.1.1`.
  - The check log includes the POSIX and Windows activation lines.
  - pytest exit 0, with a summary of `22 passed` and no skipped, failed, error, xfailed, or deselected items. A skipped `test_tiny_training_run` is not PASS.
- **Output location:** `outputs/p0-verification/t3/` (the venv lives here). Pytest temporary directories are under the system temp directory.
- **Failure interpretation:**
  - **pip or network failure:** BLOCKED.
  - **Import failure after install:** pin incompatibility, so FAIL.
  - **A third `+ ` line mentioning pip:** N11 regression. FAIL.
  - **Test failures, by test:**
    - `test_two_resets…` / `test_done_episode_is_completed`: episode isolation or the N1 status contract.
    - seed tests / `test_seed_and_bounds_strip_inline_comments`: seed policy or N4 INI parity.
    - `test_premature_exit…` / `test_malformed_output…`: diagnostics.
    - `test_band_flag_forwarding` / `test_bound_defaults…`: band forwarding or mask defaults.
    - `test_gym_registration…` / `test_cli_help` / `test_tiny_training_run`: registration, CLI order, the manifest/model path, or N2 package provenance.
    - `test_positions_header_and_coordinates` / `test_no_header_is_empty`: B2 parser regression.
    - `test_unattended_launchers_close_stdin_and_clean_loader_paths`: N10 or N11 launcher regression.

### T4 — Real MaskablePPO process smoke

- **Working directory:** mesh-sim root
- **Owner:** Tester
- **Depends on:** T3

```sh
cd /Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/scratch/mesh-sim
BIN=/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/scratch/mesh-sim/ns3.42-sim-debug
PY=outputs/p0-verification/t3/venv/bin/python
mkdir -p outputs/p0-verification/t4
"$PY" -m scripts.rl.train --sim-binary "$BIN" --run-config inputs/baselines/p0-smoke/run.ini --output-dir outputs/p0-verification/rl m-ppo --total-timesteps 16 --n-steps 16 --seed 1 </dev/null > outputs/p0-verification/t4/train.console 2>&1; echo "train exit=$?"
"$PY" - outputs/p0-verification/rl "$BIN" > outputs/p0-verification/t4/inspect.txt 2>&1 <<'EOF'
import json, re, sys
from pathlib import Path
out, binary = Path(sys.argv[1]).resolve(), sys.argv[2]
err = []
m = json.loads((out / "train_manifest.json").read_text())
print(json.dumps(m, indent=2))
pins = {"gymnasium": "1.3.0", "numpy": "2.4.6", "stable_baselines3": "2.9.0", "sb3_contrib": "2.9.0",
        "torch": "2.14.0", "pandas": "3.0.5", "matplotlib": "3.11.2", "pytest": "9.1.1"}
hp = {"total_timesteps": 16, "n_steps": 16, "gamma": 0.95, "ent_coef": 0.01, "verbose": 1, "tensorboard_log": None}
checks = {
    "manifest_version": m.get("manifest_version") == 1, "status": m.get("status") == "completed",
    "algorithm": m.get("algorithm") == "MaskablePPO", "seed": m.get("seed") == 1,
    "seed_source": m.get("seed_source") == "cli", "band": m.get("band") is None,
    "hyperparameters": m.get("hyperparameters") == hp, "package_versions": m.get("package_versions") == pins,
    "ended_at": bool(m.get("ended_at")), "python_version": bool(m.get("python_version")),
    "sim_binary": m.get("sim_binary") == binary,
    "model_path": m.get("model_path") == str(out / "maskable_ppo_mesh.zip") and (out / "maskable_ppo_mesh.zip").is_file(),
}
err += [k for k, v in checks.items() if not v]
eps = sorted(p for p in out.iterdir() if p.is_dir() and p.name.startswith("episode-"))
if len(eps) < 2 or [p.name for p in eps] != ["episode-%04d" % i for i in range(len(eps))]:
    err.append("episode directories %s" % [p.name for p in eps])
statuses = []
for idx, ep in enumerate(eps):
    for rel in ("run.log", "rl_episode.json", "sim_stderr.log", "inputs/run.ini", "seed-1/summary.json", "seed-1/links.csv"):
        if not (ep / rel).is_file():
            err.append("%s missing %s" % (ep.name, rel))
    e = json.loads((ep / "rl_episode.json").read_text())
    status, steps = e.get("status"), e.get("steps")
    statuses.append(status)
    print(ep.name, "status", status, "steps", steps, "exit_code", e.get("exit_code"), "reward", e.get("cumulative_reward"))
    cmd = e.get("command", [])
    if e.get("episode") != idx or e.get("seed") != 1 or e.get("seed_source") != "cli" or status not in ("completed", "interrupted") or e.get("exit_code") != 0:
        err.append("%s manifest fields" % ep.name)
    if status == "completed" and not steps:
        err.append("%s completed with no steps" % ep.name)
    if steps == 0 and status != "interrupted":
        err.append("%s zero-step episode not interrupted" % ep.name)
    if "--seed=1" not in cmd or any(a.startswith("--band") for a in cmd) or not any(
            a.startswith("--output-dir=") and Path(a.split("=", 1)[1]).resolve() == ep for a in cmd):
        err.append("%s command %s" % (ep.name, cmd))
    log = (ep / "run.log").read_text() if (ep / "run.log").is_file() else ""
    for pat in (r"^seeds: +\[1\]$", r"^  --rl-mode += true$", r"^  band_source += run\.ini$", r"^  rl\.reward_type += all_links_los$"):
        if not re.search(pat, log, re.M):
            err.append("%s run.log lacks %s" % (ep.name, pat))
if not statuses or statuses[0] != "interrupted":
    err.append("episode-0000 (pre-wrap reset) not interrupted")
if "completed" not in statuses:
    err.append("no naturally completed episode")
print("ERRORS", err)
sys.exit(1 if err else 0)
EOF
echo "inspect exit=$?"
shasum -a 256 outputs/p0-verification/rl/train_manifest.json > outputs/p0-verification/t4/manifest-before.sha256
ls -1 outputs/p0-verification/rl > outputs/p0-verification/t4/listing-before.txt
"$PY" -m scripts.rl.train --sim-binary "$BIN" --run-config inputs/baselines/p0-smoke/run.ini --output-dir outputs/p0-verification/rl m-ppo --total-timesteps 16 --n-steps 16 --seed 1 </dev/null > outputs/p0-verification/t4/rerun.console 2>&1; echo "rerun exit=$?"
shasum -a 256 outputs/p0-verification/rl/train_manifest.json > outputs/p0-verification/t4/manifest-after.sha256
ls -1 outputs/p0-verification/rl > outputs/p0-verification/t4/listing-after.txt
cmp outputs/p0-verification/t4/manifest-before.sha256 outputs/p0-verification/t4/manifest-after.sha256; echo "manifest cmp exit=$?"
cmp outputs/p0-verification/t4/listing-before.txt outputs/p0-verification/t4/listing-after.txt; echo "listing cmp exit=$?"
printf 'refusal='; grep -c "Refusing to start" outputs/p0-verification/t4/rerun.console
```

- **Expected evidence:** the training console, the full manifest with eight package versions, the per-episode status/steps/exit code/reward lines, and the rerun refusal.
- **Pass criteria (all required):**
  - train exit 0 and inspect exit 0 (`ERRORS []`).
    - The episode-status contract (N1):
      - every episode is `completed` or `interrupted` with exit code 0;
      - `episode-0000`, the pre-wrap `env.reset()`, is `interrupted`;
      - every zero-step episode is `interrupted`;
      - at least one episode is `completed`, and every completed episode has steps > 0.
  - rerun exit 1 and refusal = 1.
  - manifest cmp exit 0 and listing cmp exit 0.
- **Scope of the result:** this proves process integration only, not learning.
- **Output location:** `outputs/p0-verification/rl/` and `outputs/p0-verification/t4/`
- **Failure interpretation:**
  - **Train nonzero:** read the manifest `error` and the episode `sim_stderr.log` (SB3/Gym contract or subprocess lifecycle).
  - **Manifest field or `package_versions` mismatch:** provenance defect (N2).
  - **Missing or misnumbered episodes:** isolation defect.
  - **A seed other than 1:** seed-policy defect.
  - **Status contract violation:** N1 regression.
  - **Negative exit code on an interrupted episode:** the simulator did not exit within 2 s of stdin closing (R-4). That is a lifecycle FAIL.
  - **Rerun not refused, or the listing changed:** overwrite-protection defect.

### T5 — Sweep and validation surfaces

- **Working directory:** mesh-sim root
- **Owner:** Tester
- **Depends on:** T3 (these launchers import numpy and pandas)

```sh
cd /Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/scratch/mesh-sim
BIN=/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/scratch/mesh-sim/ns3.42-sim-debug
PY=outputs/p0-verification/t3/venv/bin/python
mkdir -p outputs/p0-verification/t5
cat > outputs/p0-verification/t5/sweep.ini <<'EOF'
[sweep.meta]
base_scenario = inputs/baselines/p0-smoke
seeds = 1
auto_plot = none
label = p0-band-smoke

[sweep]
channel.band = mmwave
EOF
"$PY" -m scripts.sweep.cli --config outputs/p0-verification/t5/sweep.ini --sim-binary "$BIN" </dev/null > outputs/p0-verification/t5/sweep.console 2>&1; echo "sweep exit=$?"
"$PY" -m scripts.validation.run_batch --scenarios-dir inputs/baselines --only p0-smoke --seeds 1 --sim-binary "$BIN" --out outputs/p0-verification/t5/batch </dev/null > outputs/p0-verification/t5/batch.console 2>&1; echo "batch exit=$?"
"$PY" -m scripts.validation.run_batch --scenarios-dir inputs/baselines --only p0-smoke --seeds 1 --sim-binary "$BIN" --band sub-6 --out outputs/p0-verification/t5/batch-band </dev/null > outputs/p0-verification/t5/batch-band.console 2>&1; echo "batch-band exit=$?"
"$PY" - outputs/p0-verification/t5 > outputs/p0-verification/t5/inspect.txt 2>&1 <<'EOF'
import configparser, json, re, sys
from pathlib import Path
t5 = Path(sys.argv[1]).resolve()
err = []
def has(path, pat):
    return path.is_file() and re.search(pat, path.read_text(), re.M) is not None
con = (t5 / "sweep.console").read_text()
mo = re.search(r"^  Output: +(.+)$", con, re.M)
if not mo or not re.search(r"Succeeded: +1$", con, re.M) or not re.search(r"Failed: +0$", con, re.M):
    err.append("sweep console summary")
else:
    sweep = Path(mo.group(1).strip()); pt = sweep / "point-001"
    print("sweep dir", sweep)
    ini = configparser.ConfigParser(); ini.read(pt / "run.ini")
    if ini.get("channel", "band", fallback=None) != "mmwave": err.append("sweep point run.ini band")
    if not has(pt / "inputs" / "run.ini", r"^band\s*=\s*mmwave$"): err.append("sweep archived band")
    if not has(pt / "run.log", r"^  band += mmwave$") or not has(pt / "run.log", r"^  band_source += run\.ini$"): err.append("sweep run.log band")
    if not (pt / "run.log").read_text().startswith("mesh-sim run log"): err.append("sweep run.log owner")
    if not (pt / "console.log").read_text().startswith("Command:"): err.append("sweep console.log")
    if not (pt / "seed-1" / "summary.json").is_file(): err.append("sweep seed-1 summary")
    man = json.loads((sweep / "sweep_manifest.json").read_text())
    p = man["points"][0] if man.get("points") else {}
    if not (len(man.get("points", [])) == 1 and p.get("status") == "completed" and p.get("console_log") == "point-001/console.log"
            and p.get("output_dir") == str(pt) and p.get("params") == {"channel.band": "mmwave"}):
        err.append("sweep manifest %s" % p)
for name, override, band, source in (("batch", None, "mmwave", "run.ini"), ("batch-band", "sub-6", "sub-6", "cli")):
    root = t5 / name; sc = root / "p0-smoke"
    man = json.loads((root / "batch_manifest.json").read_text())
    r = man["runs"][0] if man.get("runs") else {}
    if not (man.get("band_override") == override and len(man.get("runs", [])) == 1 and r.get("status") == "ok"
            and r.get("exit_code") == 0 and r.get("console_log") == str(sc / "console.log") and r.get("output_dir") == str(sc)):
        err.append("%s manifest %s" % (name, man))
    first = (sc / "console.log").read_text().splitlines()[0] if (sc / "console.log").is_file() else ""
    if not first.startswith("Command:") or (("--band=sub-6" in first) != (override == "sub-6")):
        err.append("%s console.log command %r" % (name, first))
    if not (sc / "run.log").read_text().startswith("mesh-sim run log"): err.append("%s run.log owner" % name)
    if not has(sc / "run.log", r"^  band += %s$" % re.escape(band)) or not has(sc / "run.log", r"^  band_source += %s$" % re.escape(source)):
        err.append("%s run.log band" % name)
    if not has(sc / "inputs" / "run.ini", r"^band\s*=\s*mmwave$"): err.append("%s archived band" % name)
    if not (sc / "seed-1" / "summary.json").is_file(): err.append("%s seed-1 summary" % name)
print("ERRORS", err)
sys.exit(1 if err else 0)
EOF
echo "inspect exit=$?"
```

- **Expected evidence:**
  - A one-point sweep under the printed `outputs/YYYY-MM/DD/HH-MM-SS/` directory; the sweep runner does not accept an output path, and this directory is covered by write authority item 4.
  - Two batch roots.
  - The inspection output.
- **Pass criteria (all required):**
  - sweep, batch, batch-band, and inspect all exit 0.
  - inspect prints `ERRORS []`. That confirms, for each surface:
    - the simulator-owned root `run.log` and the separate launcher `console.log` coexist;
    - the archived input carries an explicit band;
    - per-seed results exist;
    - the manifest `console_log`, `output_dir`, and band fields are accurate.
- **Output location:** `outputs/p0-verification/t5/` plus the sweep directory path printed by `inspect.txt` (`sweep dir …`). Record that path in the results.
- **Failure interpretation:**
  - **`run.log` begins with `Command:`:** launcher log collision.
  - **Missing band in the point or archived `run.ini`:** config propagation defect.
  - **Wrong `band_source` under `--band`:** batch override not forwarded.
  - **A hang:** stdin handling regression, even though the launchers now pass `DEVNULL` (N10). FAIL; recheck that the command was run exactly as written.
  - **Sweep exit 0 with `Failed: 1`:** simulator failure; read `point-001/console.log`. The sweep CLI does not return nonzero on point failure, which is why the console counts are checked.

## 8. Additional checks and justification

Each check below is tied to an observed diff risk:

- **T0 (provenance and reviewed-code integrity):**
  - `verify-suite` intentionally reports PASS for the reference binary (B1 history), so explicit hash, mtime, and string checks are required.
  - The `(jammer interference enabled)` / `co-channel interference computed` pair proves the binary includes the post-R1 N5 edit.
  - The literal Git status and 35 file digests ensure the Tester exercises exactly the reviewed code and evidence.
  - The precondition checks only row-owned paths, because the approved repair evidence already lives in `outputs/p0-verification/reviewer-fixes/`.
- **T1 per-suite runs:** `tests/Makefile` stops at the first failing suite (N9, documented rather than changed), and `unit/config` fails for pre-existing reasons.
- **T1A snapshot-structure assertion:** guards the B2/H0B repair. The post-change suite is the first execution that compares node trajectories.
- **T7 (band resolution):** `sim.cc:163` switched from `args.band` to `cfg.band`, and the default and `run.ini` sources are new. Every T1A case passes an explicit `--band`.
- **T8 (Stay):** `rl-bridge.cc` `ReadAction` changed behavior, and no real-binary test covers it otherwise.
- **T3 fresh venv, both test directories, bootstrap command lines:**
  - The approved amendment added `scripts/validation/tests` (B2, N10, N11).
  - The N11 repair removed the pip upgrade, which the `+ ` echo lines make observable.
  - The existing `.venv` is not a clean-install proof and must not be altered.
- **T4 eight pins and status contract:** the N2 repair changed the manifest to eight packages, and the N1 repair defined `interrupted` versus `completed`. Both now have real-binary evidence.
- **T5 `--band` batch variant and `--only p0-smoke`:** unchanged from R1 (S4.4 forwarding; avoids copying tracked inputs).
- **`</dev/null` on launcher commands:** retained as defense in depth after N10.

## 9. Handoff

**Testing may begin.** The human may now start the Tester with:

- `<phase-dir>` = `docs/rl-program/p0-baseline`
- `<charter>` = `docs/rl-program/p0-baseline/baseline-review-and-test-charter.md`
- `<BIN>` = `/Users/ryanmccann/Desktop/git.nosync/ns3-mmwave/build/scratch/mesh-sim/ns3.42-sim-debug` (SHA-256 `57613a69f88a6bb11832b62d8f80a4ccf46644b2d6cbe46f60a6bc645beb3722`)

Then:

1. **Tester:** execute section 7 exactly as written, in order, within the write authority. Write `docs/rl-program/p0-baseline/baseline-test-results.md` with one entry per row (T0, T1, T1A, T2, T7, T8, T6, T3, T4, T5) and hand it back.
2. **Fresh final Reviewer:** in a separate session, recheck the results, carry forward R-1 to R-4, and write `baseline-completion-report.md` with `accept` or `return`. That Reviewer does not repeat the tests.
3. **Git/PR role:** acts only after `accept`.

This charter does not state or imply that any test has passed.
