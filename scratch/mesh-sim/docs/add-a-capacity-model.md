# Add a capacity model {#mesh_sim_add_capacity_model}

[TOC]

This page adds one small, illustrative value to the existing `[channel] amc_model` selector, checks it with the eval unit suite, rebuilds, and runs it on a copied scenario without touching tracked inputs or earlier results. \ref mesh_sim_setting_trace "Follow a setting" traces an existing value through the run; this page adds a new one and shows which owners are involved.

\note **Status: proposed/unverified.** `scaled_shannon` is unavailable in an unchanged checkout. The documentation batch executed none of the snippets or commands below.

## What you will build

- `scaled_shannon`: for `sinr_db >= SINR_MIN_DB` (−6.7 dB), `capacity_mbps = 0.75 * bandwidth_hz * log2(1 + 10^(sinr_db/10)) / 1e6`. Below the threshold the function's existing zero return is kept.
- `0.75` is an arbitrary teaching factor. It is not a calibration, not a measurement and not research evidence.
- The change adds a value to an existing selector. It is not a new INI key, so the loader, validator and reference table need no edit for it to run (see "What changes together" below).

**Prerequisites.** A working full build per \ref mesh_sim_install_build "Install and build" (C++20 toolchain) for Steps 3 and 4. Step 2 needs only the eval Makefile's toolchain (`c++`, C++17). All commands run from the ns3-mmwave repository root; the unit command is wrapped in a subshell so it does not change your directory.

## Step 1 — add the branch

Open your local \ref sinr-capacity.h "scratch/mesh-sim/src/eval/sinr-capacity.h" and find the inline `SinrToCapacity(double sinr_db, double bandwidth_hz, const std::string& amc_model)`. Keep the outage guard at the top of the function (`if (sinr_db < SINR_MIN_DB) return 0.0;`) and every existing case. Insert the new `else if` between the existing `"shannon"` branch and the `"silvus"` branch:

```cpp
    // ... the existing "shannon" branch ends here:
        return capacity_bps / 1e6;  // → Mbps
    }

    else if (amc_model == "scaled_shannon")
    {
        // Illustrative only: 0.75 is an arbitrary teaching factor.
        const double linear = std::pow(10.0, sinr_db / 10.0);
        return 0.75 * bandwidth_hz * std::log2(1.0 + linear) / 1e6;  // → Mbps
    }

    else if (amc_model == "silvus")
    // ... the existing branch continues unchanged
```

The unknown-name rejection (`else if (amc_model != "table") throw ...`) comes after this point, so the new name is accepted and the `"table"` fall-through is untouched.

Documentation you update in the same local change (this page does not make these edits; the shipped lists still name three models):

- In `sinr-capacity.h`: the file comment's model table ("Three capacity models"), the `@param amc_model` list on `SinrToCapacity`, and the `std::runtime_error` message, which enumerates `'shannon', 'table', or 'silvus'`; add `'scaled_shannon'` to that message.
- The accepted-name lists in `src/domain/channel-config.h` (the `amc_model` field comment) and `src/eval/link-evaluator.h` (the `@throws` note on `Evaluate`), the capacity-model list in the \ref src_eval "eval guide", and the `amc_model` row of the \ref src_config_run_ini_reference "run.ini reference".

## What changes together

| Concern | Owner | Verification |
|---|---|---|
| Formula and threshold | \ref sinr-capacity.h "src/eval/sinr-capacity.h" | unit checkpoints (Step 2) |
| Name acceptance | loader (`config-loader.cc`) and \ref config-validator.cc "validator" | the string passes through with no whitelist; no edit needed |
| MCS index / `spectral_eff` | \ref link-evaluator.cc "evaluator CQI dispatch" and `VizWriter::WriteMcs` | any non-`silvus` name retains CQI semantics for a given SINR; no byte-identical rerun is promised |
| Recorded provenance | `ArchiveScenarioInputs` and `WriteRunLog` | the explicit name survives in copied `inputs/run.ini`, not `run.log` (\ref src_io_run_record "What a run records") |
| Default when omitted | domain default and loader fallback (`shannon`) | not exercised: this exercise writes the key explicitly |

Adding a validator whitelist is a separate behavior change. If one is introduced later, include the new name in it. No loader, validator or MCS-dispatch edit is needed for this exercise today.

## Step 2 — unit checkpoints

`tests/unit/eval/eval-test.cc` already provides `check(bool, name)` and `approx(a, b, tol)`. `approx` uses an **absolute** tolerance, so pass `1e-9 * std::fabs(expected)` for positive formula expectations and `1e-9` for dimensionless ratios; zero returns are compared exactly. Paste the following function above `main`, for example immediately after `test_unknown_amc_throws`. Then add the call shown below: a function that is defined but not called never runs.

```cpp
// ---- scaled_shannon (local extension) ----

static void
test_scaled_shannon()
{
    const double bw = 100e6;
    auto cap = [](double sinr, double b) {
        return SinrToCapacity(sinr, b, "scaled_shannon");
    };

    // 1. Usable SINR: the formula, then the ratio to the existing shannon model.
    const double expect10 = 0.75 * bw * std::log2(11.0) / 1e6;  // 10 dB -> linear 10
    check(approx(cap(10.0, bw), expect10, 1e-9 * std::fabs(expect10)),
          "scaled_shannon 10 dB matches 0.75*B*log2(11)/1e6");
    check(approx(cap(10.0, bw) / SinrToCapacity(10.0, bw, "shannon"), 0.75, 1e-9),
          "scaled_shannon is 0.75 x shannon at 10 dB");

    // 2. Outage: below SINR_MIN_DB returns exactly 0.
    check(cap(-10.0, bw) == 0.0, "scaled_shannon -10 dB returns exactly 0");

    // 3. Exact threshold, then the next representable input below it.
    const double expectMin =
        0.75 * bw * std::log2(1.0 + std::pow(10.0, SINR_MIN_DB / 10.0)) / 1e6;
    check(expectMin > 0.0 &&
          approx(cap(SINR_MIN_DB, bw), expectMin, 1e-9 * std::fabs(expectMin)),
          "scaled_shannon at SINR_MIN_DB is positive and matches the formula");
    check(cap(std::nextafter(SINR_MIN_DB, SINR_MIN_DB - 1.0), bw) == 0.0,
          "scaled_shannon just below SINR_MIN_DB returns exactly 0");

    // 4. Bandwidth scaling.
    check(approx(cap(10.0, 2.0 * bw) / cap(10.0, bw), 2.0, 1e-9),
          "scaled_shannon scales linearly with bandwidth");

    // 5. Existing models: the shannon and table tests already run from main.
    //    One source-derived silvus check: at 0 dB the MCS 0 row (6.5 Mbps at
    //    20 MHz) scales to 32.5 Mbps at 100 MHz.
    const double expectSilvus = 6.5 * (bw / 20e6);
    check(approx(SinrToCapacity(0.0, bw, "silvus"), expectSilvus, 1e-9 * expectSilvus),
          "silvus 0 dB at 100 MHz is 32.5 Mbps");

    // 6. Unknown name: throws at usable SINR, returns 0 below the threshold.
    //    This documents the current ordering; it does not verify scaled_shannon
    //    (checkpoints 1-4 do).
    bool threw = false;
    try { SinrToCapacity(10.0, bw, "no_such_model"); }
    catch (const std::runtime_error&) { threw = true; }
    check(threw, "unknown amc_model throws at 10 dB");
    check(SinrToCapacity(-10.0, bw, "no_such_model") == 0.0,
          "unknown amc_model returns 0 below SINR_MIN_DB");
}
```

Then register it in `main`, next to the other `SinrToCapacity` tests:

```cpp
    test_unknown_amc_throws();
    test_scaled_shannon();   // local extension
```

Run the suite from the repository root:

```bash
(cd scratch/mesh-sim && make -B -C tests/unit/eval test)
```

`-B` forces recompilation. The `eval-test` prerequisites list `eval-test.cc`, `link-table.cc` and `coverage-grid.cc` but not `sinr-capacity.h`, so without `-B` a header-only edit can leave a stale binary that still passes. The same target also builds and runs `reconfigure-test`, which compiles the real evaluator and jammer code against local ns-3 stubs and checks only that reconfiguration clears an old jammer; it is not a propagation-model check (see the \ref src_eval "eval guide").

**Checkpoint:** the command exits 0, prints no `FAIL:` lines, and `eval-test` ends with `All tests passed.`. The pass count depends on the suite; do not expect a fixed number. The expected silvus value (32.5 Mbps) is a calculation from the table, not a reported run result.

## Step 3 — rebuild the simulator

`sinr-capacity.h` is compiled into the simulator, so rebuild after the header change and before running. Use the build command from \ref mesh_sim_install_build "Install and build" (from the repository root):

```bash
./ns3 build scratch/mesh-sim/sim
```

**Checkpoint:** the build finishes without errors. A directly launched older binary can report the unknown-model error at usable SINR. The `./ns3 run` wrapper normally rebuilds changed sources; still check that the intended executable was rebuilt.

## Step 4 — run a copied scenario

The tracked scenario `inputs/baselines/06-mcs-table-mode/` already uses a non-default `amc_model` (`table`), so it is a good base. The tracked files are never edited: copy them into the ignored work area that \ref mesh_sim_change_one_setting "Change one setting" uses, edit the copy, and run it into its own result folder. `mkdir` without `-p` fails if the leaf exists; `&&` stops the chain at the first failure; `cp -n` never overwrites. If creation fails, choose a fresh leaf name and use it consistently below.

```bash
mkdir -p scratch/mesh-sim/outputs/my-scenarios && \
mkdir scratch/mesh-sim/outputs/my-scenarios/add-capacity-model && \
cp -n scratch/mesh-sim/inputs/baselines/06-mcs-table-mode/run.ini   scratch/mesh-sim/outputs/my-scenarios/add-capacity-model/ && \
cp -n scratch/mesh-sim/inputs/baselines/06-mcs-table-mode/nodes.json scratch/mesh-sim/outputs/my-scenarios/add-capacity-model/
```

```bash
ls scratch/mesh-sim/outputs/my-scenarios/add-capacity-model
diff scratch/mesh-sim/inputs/baselines/06-mcs-table-mode/run.ini scratch/mesh-sim/outputs/my-scenarios/add-capacity-model/run.ini
```

**Checkpoint:** `ls` shows `nodes.json` and `run.ini`; `diff` prints nothing.

Open the copied `run.ini`, find the `[channel]` section and change only the value on the active `amc_model` line. The comment block at the top predicts table-mode numbers (CQI 14, about 2220 Mbps); those comments are not expectations for the new model and are left alone.

```ini
# before
amc_model        = table
# after
amc_model        = scaled_shannon
```

**Checkpoint:** repeating the `diff` prints exactly one changed pair of lines, the active `amc_model` key, `table` on the `<` side and `scaled_shannon` on the `>` side.

Launch only after Steps 1–3 succeeded. This separate guarded chain creates a fresh result folder and refuses to launch into an existing one:

```bash
mkdir -p scratch/mesh-sim/outputs/getting-started && \
mkdir scratch/mesh-sim/outputs/getting-started/add-capacity-model && \
./ns3 run scratch/mesh-sim/sim -- \
  --run-config=scratch/mesh-sim/outputs/my-scenarios/add-capacity-model/run.ini \
  --seeds=1 \
  --output-dir=scratch/mesh-sim/outputs/getting-started/add-capacity-model
```

**Checkpoint:** exit code 0 (`echo $?` prints `0`). Do not continue to Step 5 after a failed copy, test, build or run; fix that stage first.

## Step 5 — read the outputs

```
scratch/mesh-sim/outputs/getting-started/add-capacity-model/
├── inputs/run.ini      # the copy you launched: names scaled_shannon explicitly
├── inputs/nodes.json
├── run.log             # seeds, CLI block, resolved config; no AMC model line
└── seed-1/
    ├── links.csv       # capacity_mbps from the new branch
    ├── mcs.csv         # CQI mcs_index and spectral_eff, unchanged semantics
    ├── summary.json
    └── positions.csv  rx-power.csv  flows.csv  routes.csv
```

```bash
grep -n '^[[:space:]]*amc_model[[:space:]]*=' scratch/mesh-sim/outputs/getting-started/add-capacity-model/inputs/run.ini
head -n 3 scratch/mesh-sim/outputs/getting-started/add-capacity-model/seed-1/links.csv
```

**Checkpoint:** the first command prints one line showing `scaled_shannon`. `run.log` has no `amc_model` line: the resolved block omits it, so the archived copy records the explicitly selected name (\ref src_io_run_record "What a run records"). The second command prints the header `time_s,node_a,node_b,dist_m,sinr_db,condition,condition_reason,capacity_mbps,delivered_mbps,hop_count` followed by data rows.

To relate one row to the formula, check the `condition` and `sinr_db` columns and pick an LOS row comfortably above −6.7 dB. The nodes are fixed and 100 m apart, but the fixture leaves `condition_model=auto`, so LOS is not guaranteed; if no suitable row exists, defer this check. For a suitable row, compute `0.75 * 400e6 * log2(1 + 10^(sinr_db/10)) / 1e6` with the fixture's `bandwidth_mhz = 400.0`. The writer prints `capacity_mbps` with one decimal and `sinr_db` with six, so expect agreement within about 0.1 Mbps, not the unit-test precision. Near the threshold a rounded SINR could hide which branch ran; use a non-boundary row. `mcs.csv` keeps CQI semantics (`mcs_index` from `SinrToMcsIndex`, `spectral_eff` from `MCS_TABLE`) and does not become a Shannon spectral efficiency. Both files are among the six CSVs that `--no-viz` disables (\ref src_io_output "Output").

No real CSV row or measured capacity is stated here, and no comparison against a table-mode baseline is promised. The fixture's demand is 500 Mbps; if the new capacity still exceeds it, `delivered_mbps` can equal the demand exactly as in table mode, which is expected rather than a sign that the model failed.

## Source links

- \ref sinr-capacity.h "src/eval/sinr-capacity.h": `SINR_MIN_DB`, `MCS_TABLE`, `SILVUS_MCS_TABLE`, `SinrToCapacity`.
- \ref link-evaluator.h "src/eval/link-evaluator.h" and \ref link-evaluator.cc "link-evaluator.cc": `Configure`, `Evaluate`, MCS dispatch.
- \ref config-validator.cc "src/config/config-validator.cc": the allowed-value checks (none for `amc_model`).
- `sim.cc`: CLI overrides, archive, run log and the per-seed evaluation loop (\ref mesh_sim_run_flow "How a run works").
- `tests/unit/eval/Makefile`, `tests/unit/eval/eval-test.cc`: the suite extended in Step 2.
- `inputs/baselines/06-mcs-table-mode/run.ini`, `nodes.json`: the tracked fixture copied in Step 4 (\ref inputs_baselines "inputs/baselines").

Provenance: the branch position, test helpers, Makefile prerequisites, fixture values and CSV formats on this page come from source inspection; every checkpoint is *proposed/unverified* until you run it.

## Next

- \ref mesh_sim_setting_trace "Follow a setting": how an existing value travels from INI to output.
- \ref src_eval "eval": capacity models, MCS dispatch and the unit suites.
- \ref src_io_run_record "What a run records": what the archive and `run.log` do and do not preserve.
