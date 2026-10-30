@page scripts_validation scripts/validation

@brief Checks mesh-sim output against ARPO field data and against stored regression results.

This package does two jobs:

- **Simulator-vs-field comparison.** Builds scenarios from ARPO field data, runs
  mesh-sim over several seeds, and overlays the simulated distributions of SNR,
  RCPI (received channel power indicator, dBm) and MCS (modulation and coding
  scheme index) on the field traces. For each metric it reports the two-sample
  K-S (Kolmogorov-Smirnov) D statistic and |Δmedian| / |Δmean|. The
  step-by-step recipe is
  [Compare the simulator with field data](@ref mesh_sim_field_data_workflow).
- **Regression and smoke checks.** `regression_check` confirms that a new
  simulator binary reproduces stored results. `smoke_check` confirms that it is
  self-consistent on a tiny synthetic scenario.

## 1\. Setup

Run every command from `scratch/mesh-sim/` as
`python -m scripts.validation.<name>`; the scripts use package-relative
imports.

1. Build the simulator binary (the user handles builds).
2. Install the Python packages:

   ```bash
   pip install pandas numpy matplotlib pytest
   ```

3. For the field comparison, generate the per-day field trace CSVs from the
   per-node bundle. `--nodes` is a switch; `plot --all` fails on Silvus data.

   ```bash
   python -m scripts.arpo_data.cli plot --nodes -i <per-node-root> -o <daily-root> --day YYYY-MM-DD
   ```

   To slice one time window, use `split-scenario`; see
   [scripts/arpo_data](@ref scripts_arpo_data).

4. For the full regression suite, get the reference bundle from the project
   team and unpack its JSON snapshots under `tests/fixtures/regression/p0/`.
   The smoke check and unit tests do not need it.

## 2\. Simulator-vs-field comparison

### Node mode (CalFEX)

Run the five steps in order into one fresh workspace.
[Compare the simulator with field data](@ref mesh_sim_field_data_workflow)
gives the same steps with a checkpoint after each command.

| Step | Command | Notes |
|---|---|---|
| 1 | `build_config_files -i <runs-root> --day <run> --csv-dir <per-node-root> --band sub-6 --mode node [-o <out>]` | Writes `<out>/<run>/{run.ini,nodes.json}` with empty waypoints. |
| 2 | `build_waypoints node -i <out>/<run> -f <run>/gps_all_nodes_trace.csv --all-nodes --time-mode raw` | Edits `nodes.json` in place. |
| 3 | `run_batch --scenarios-dir <out> --only <run> --out <batch> --seeds 1,2,3,4,5 --sim-binary <BIN>` | Runs the simulator per seed. |
| 4 | `sim_to_traces -m node <batch>/<run>` | Converts simulator CSVs to field-style traces. |
| 5 | `compare -m node --batch_root <batch>/<run> --field-root <field-window-dir>` | Draws overlays and writes K-S results. |

Step details:

1. **`build_config_files`**
   - `-i` is the parent folder holding `<run>/gps_all_nodes_trace.csv`.
   - `--day` is that run folder's name (a calendar day, or a `HHMM-HHMM` window
     tag from `split-scenario`); `--all-days` processes every run.
   - `--band` and `--mode` are required; only `node` + `sub-6` is implemented.
   - `--csv-dir` is the original per-node root (`<node>/silvus/config.csv`).
   - `-o` defaults to `inputs/calfex`.
   - Duration is the GPS span unless `--time` is given.
2. **`build_waypoints`**
   - `-f` is the GPS CSV, or a per-node folder holding
     `csvs/gps_track_trace.csv`.
   - `--time-mode raw` keeps each node's field timing from its own first fix.
   - `--time-mode scale --duration N` stretches each track to N seconds; pair it
     with the same `--time N` in step 1, or nodes finish moving early.
3. **`run_batch`**
   - Always pass `--sim-binary`; auto-detection takes the first build match.
   - Without `--out`, the batch root is timestamped under `outputs/`.
   - Do not use `--auto-waypoints` (see section 9).
4. **`sim_to_traces`** takes the scenario result folder (the one holding
   `inputs/` and `seed-N/`), not the batch root.
5. **`compare`** takes the same scenario result folder. `--field-root` is the
   sliced window (or day) folder whose `<node>/csvs/<node>/IH_*` traces match
   the simulator labels.

### Follow-up tools

Run these after `compare`; they read `validation_summary.csv` or the simulator
outputs.

```bash
# Cross-batch heatmaps (auto-discovers outputs/**/validation_summary.csv)
python -m scripts.validation.compare_runs

# Layout / mobility audit (prints tables, writes nothing)
python -m scripts.validation.scenario_fidelity -m node \
    --field-gps <gps_all_nodes_trace.csv> outputs/.../<scenario>

# Signed per-node comparison against one baseline scenario
python -m scripts.validation.compare_baseline \
    --baseline outputs/.../<base> outputs/.../<other> ...
```

### Per-day wrapper

`validate_days` runs steps 4 and 5 plus `scenario_fidelity` for each day, then
`compare_runs` across days. Use it instead of running those steps by hand.

```bash
python -m scripts.validation.validate_days --day 2026-05-13 --time 60 --out-root <out-root> --field-root <field-root>
python -m scripts.validation.validate_days --all-days --time 60 --out-root <out-root> --field-root <field-root>
```

| Flag | Meaning |
|---|---|
| `--out-root` | Holds `<out-root>/<day>/{inputs/,seed-*/}`. Default `outputs/calfex`. |
| `--field-root` | Holds field traces at `<field-root>/<day>/<node>/csvs/<node>/IH_*`. |
| `--time` | Required by the parser; the value is not used. |

### Scenario mode (Spring Lake, legacy)

This route does not run as written: it needs `plot --all`, which raises
`TypeError` on Silvus data, and `inputs/custom/sherpa/spring_lake/`, which is
absent from a clean checkout. The scenario-mode versions of steps 2, 4 and 5
are:

```bash
python -m scripts.validation.build_waypoints scenario --all --time-mode scale --duration 60
python -m scripts.validation.sim_to_traces -m scenario outputs/.../<HH-MM-SS>-validation
python -m scripts.validation.compare -m scenario --batch_root outputs/.../<HH-MM-SS>-validation
```

## 3\. Jammer file

Build `jammers.json` from the field EW (electronic warfare) trial CSV:

```bash
python -m scripts.validation.make_jammers --trials <ew_trials.csv> \
    --trace <gps_all_nodes_trace.csv> -o <scenario dir>/jammers.json \
    [--run-ini <scenario dir>/run.ini]
```

## 4\. Regression suite

Re-run every case in the manifest against a freshly built binary and compare
the normalized results:

```bash
python3 -m scripts.validation.regression_check verify-suite \
    --sim-binary <BIN> \
    --manifest tests/fixtures/regression/p0/manifest.json \
    --out outputs/baseline-regression/<name>
```

- The manifest and every snapshot hash are checked before the simulator starts.
- The console prints one `PASS` / `FAIL` / `SKIP` row per case.
- The optional Sherpa Spring Lake case is `SKIP` when its data is absent, and
  the console names the missing paths. `--require-all` turns that into a
  failure.
- `--out` must resolve beneath `outputs/` and may not be `outputs/` itself.
- Reusing an `--out` replaces only `suite-report.json` and the manifest-named
  case subfolders. Other files there, the tracked manifest and the local
  reference snapshots are left alone.
- Case names must be nonempty single path segments; all names are checked
  before cleanup.

| Exit code | Meaning |
|---|---|
| `0` | All cases passed. |
| `1` | A mismatch or failure. |
| `2` | Usage or I/O error. |

Capture or compare a single run:

```bash
python3 -m scripts.validation.regression_check capture --sim-binary <BIN> \
    --run-config <run.ini> --band {mmwave,sub-6} --seed <N> --family <F> --case <C> \
    --out <run dir> [--snapshot <file.json>] [--force]
python3 -m scripts.validation.regression_check compare --baseline <snapshot.json> \
    --candidate <run dir> [--atol 1e-9] [--max-diffs 20] [--report <file.json>]
```

Reference snapshots stay local and untracked. Never recapture them from changed
code.

## 5\. Smoke check

Check the tiny synthetic jammer scenario's output contracts and two-run
same-seed repeatability, with no reference data:

```bash
python3 -m scripts.validation.smoke_check --sim-binary <BIN> --out outputs/smoke-check/<new-name>
```

- `--out` must not exist yet.
- It prints `PASS` (exit 0) or `FAIL: <reason>` (exit 1).
- CI runs it on Linux and macOS.

## 6\. Unit tests

```bash
python -m pytest scripts/validation/tests
```

## 7\. Output

| Step | Where |
|------|-------|
| `build_config_files` | `<output>/<run>/nodes.json` and `run.ini` (default `<output>` is `inputs/calfex`) |
| `build_waypoints` | Edits `nodes.json` in place |
| `run_batch` | `<batch>/batch_manifest.json` at the batch root, and `<batch>/<scenario>/{console.log, inputs/, run.log, seed-N/...}` per scenario (`<batch>` is `--out`, else `outputs/<YYYY-MM>/<DD>/<HH-MM-SS>-validation/`). `run.log` and `inputs/` come from the simulator; see [What a run records](@ref src_io_run_record) |
| `sim_to_traces` | `<scenario>/sim_traces/seed-N/csvs/<src>/` trace CSVs (`bh2_*` in scenario mode, `IH_*` in node mode). Exits 0 even when nothing was converted; check the per-seed counts |
| `compare` | `<scenario>/validation/pngs/<src>/hist_*.png`, `<scenario>/validation/metrics.csv`, `<batch_root>/validation_summary.csv`, `<batch_root>/summary/heatmap_*.png`. In node mode `<batch_root>` is the scenario folder itself. Exits 0 even when no pair or row is produced |
| `compare_runs` | `outputs/cross_batch_summary/heatmap_*.png` (or `--out`) |
| `compare_baseline` | `<baseline>/baseline_comparison/` heatmaps and `baseline_comparison.csv` (or `--out`) |
| `validate_days` | Outputs of the wrapped steps, plus `<out-root>/cross_day_summary/` |
| `make_jammers` | The `-o` JSON file |
| `regression_check verify-suite` | `<out>/suite-report.json` and `<out>/<case>/` with `console.log`, run output and `comparison.json` |
| `smoke_check` | `<out>/run-1/` and `<out>/run-2/`, each with `console.log` |

`validation_summary.csv` has one row per (scenario, link, metric) with means,
medians, IQRs, sample counts, `abs_diff_*` and `ks_statistic`. A NaN row means
the field collect had no telemetry for that link, which happens for some
scenarios.

## 8\. Comparison method

| Topic | Rule |
|---|---|
| Metrics | `snr` (dB), `rcpi` (dBm), `mcs`. |
| Time | Samples are compared as marginal distributions with no time alignment. `--window N` keeps only the first N seconds of both sides. |
| Seed pooling | If every seed's trace for a link has the same non-zero length, `compare` averages them element-wise by row index (no time or key alignment), which smooths seed-to-seed variation. Otherwise it concatenates them. |
| SNR | Field `snr` is the radio's reported value. The simulator value is its computed SINR (`links.csv` `sinr_db`). |
| RCPI | Field `rcpi` is the mean of `rssi_ant1..4` with sentinel values dropped. The simulator value is per-link received power including array gain (`rx-power.csv` `rx_power_dbm`). |
| MCS | Simulator MCS is `mcs.csv` `mcs_index`. Both sides are clipped at 12, the field firmware ceiling. |
| Link direction | Node mode mirrors each undirected simulator link into both directions, so every node appears as a source and both directions carry the same samples. |
| Histograms | Density-normalized (area = 1), so the two sides compare directly when their sample counts differ. No bootstrap band and no K-S p-value. |

**Naming.** Simulator scenario names map to field names by stripping `arpo-`,
joining the middle tokens with `_`, and upper-casing the minor token:
`arpo-1-x-misc-04172026` becomes `1-X_misc_04172026`. Simulator trace CSVs
leave `tag_interface` blank and fill the MAC columns with node names.

## 9\. Behavior notes and known issues

- **`build_config_files` defaults.** It supports only `-m node -b sub-6` and
  writes `--band` into the generated `run.ini`. Unless overridden it writes:
  Silvus AMC, noise figure 5 dB, 6/6 dBi gains, RMa, `static_los`, 1 s tick,
  0 s warm-up, 1.25 Mbps demand. It writes empty waypoints, so always run
  `build_waypoints` afterwards.
- **`build_waypoints` edits in place.** Regenerate with `build_config_files`
  to reset `nodes.json` (`inputs/calfex` is git-ignored, so Git cannot restore
  it). A node whose track fits in a 20 m box becomes `fixed` and is reported
  `skipped`; `--dry-run` still writes those static nodes.
- **`build_waypoints --anchor`** defaults to no alignment, despite the `--help`
  text.
- **`run_batch --auto-waypoints`** fails with a `TypeError`.
- **`run_batch` status `ok`** only means the simulator exited 0.
- **`validate_days --time`** is required but unused.
- **Silent empty results.** `sim_to_traces` and `compare` exit 0 with no useful
  output when inputs are missing or labels do not match.

## 10\. Module layout

| File | Role |
|------|------|
| @ref build_config_files.py "build_config_files" | Writes per-run `nodes.json` and `run.ini` from field GPS and Silvus config CSVs. |
| @ref build_waypoints.py "build_waypoints" | Patches waypoint mobility into `nodes.json` from a field GPS track (`scenario` and `node` subcommands). |
| @ref run_batch.py "run_batch" | Runs the simulator binary once per scenario over a set of seeds; writes `batch_manifest.json`. |
| @ref sim_to_traces.py "sim_to_traces" | Rewrites per-seed simulator CSVs into arpo_data-style trace CSVs. |
| @ref compare.py "compare" | Pools simulator seeds and field traces; draws histogram + KDE overlays; writes K-S CSVs and heatmaps. |
| @ref compare_runs.py "compare_runs" | Cross-batch heatmaps (scenario x batch) from `validation_summary.csv` files. |
| @ref compare_baseline.py "compare_baseline" | Signed per-node heatmaps of each scenario against one baseline scenario. |
| @ref scenario_fidelity.py "scenario_fidelity" | Audits simulator vs field mobile/static classification and initial pairwise distances (prints tables). |
| @ref validate_days.py "validate_days" | Runs `sim_to_traces`, `compare` and `scenario_fidelity` per day, then `compare_runs` across days. |
| @ref make_jammers.py "make_jammers" | Builds `jammers.json` from the field EW trial CSV. |
| @ref regression_check.py "regression_check" | CLI and run orchestration for the baseline regression (`capture`, `compare` and `verify-suite` subcommands). |
| @ref regression_snapshot.py "regression_snapshot" | Builds, normalizes and compares run snapshots. |
| `regression_suite.py` | Manifest validation, reference integrity and suite output cleanup. |
| @ref smoke_check.py "smoke_check" | Data-free two-run smoke and repeatability check. |
| @ref tests/test_regression_check.py "tests/test_regression_check.py" | pytest tests for the snapshot and launcher contracts. |

Launcher paths and loader setup live in `scripts/sim_support.py`, one level up.

## 11\. Dependencies

| Scope | Needs |
|-------|-------|
| Field-comparison scripts (`build_*`, `compare*`, `scenario_fidelity`, `sim_to_traces`, `validate_days`, `make_jammers`) | Python 3.10+ (`build_config_files` uses `match`), `pandas`, `numpy`, `matplotlib` |
| `run_batch`, `regression_check`, `smoke_check` | A built simulator binary passed with `--sim-binary` (without it `run_batch` takes the first `build/scratch/mesh-sim/ns3*-sim-*` match, which may be stale) and `scripts/sim_support.py` |
| `regression_check`, `regression_snapshot`, `regression_suite`, `smoke_check` | Standard library only |
| Tests | `pytest`, plus `scripts.sweep` (imported by one test) |

Data that must exist beforehand:

- Field traces from `scripts.arpo_data.cli plot --nodes` (default root
  `data/arpo_extracted/_plots/per_day/`, or the `-o` you chose), optionally
  sliced by `split-scenario`.
- Per-node Silvus config CSVs (`--csv-dir`).
- Spring Lake inputs under `inputs/custom/sherpa/spring_lake/` (scenario-mode
  default; absent from a clean checkout).
- Regression reference snapshots from the project team.
