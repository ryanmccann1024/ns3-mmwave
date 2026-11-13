@page scripts_validation scripts/validation

@brief Checks mesh-sim output against field data and against stored regression results.

This package does two jobs:

- **Simulator-vs-field comparison.** Builds scenarios from field data, runs
  mesh-sim over several seeds and compares the simulated SNR, RCPI and MCS
  distributions with the field traces. Its commands, comparison method and
  field-specific notes are on the private
  [Field comparison](@ref scripts_validation_field) page, which needs an
  unlocked checkout (git-crypt). The public recipe on synthetic data is
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

3. For the full regression suite, get the reference bundle from the project
   team and unpack its JSON snapshots under `tests/fixtures/regression/p0/`.
   The smoke check and unit tests do not need it.

## 2\. Regression suite

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
- An optional field-data case is `SKIP` when its data is absent, and the
  console names the missing paths. `--require-all` turns that into a
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

## 3\. Smoke check

Check the tiny synthetic jammer scenario's output contracts and two-run
same-seed repeatability, with no reference data:

```bash
python3 -m scripts.validation.smoke_check --sim-binary <BIN> --out outputs/smoke-check/<new-name>
```

- `--out` must not exist yet.
- It prints `PASS` (exit 0) or `FAIL: <reason>` (exit 1).
- CI runs it on Linux and macOS.

## 4\. Unit tests

```bash
python -m pytest scripts/validation/tests
```


## 5\. Output

| Step | Where |
|------|-------|
| `regression_check verify-suite` | `<out>/suite-report.json` and `<out>/<case>/` with `console.log`, run output and `comparison.json` |
| `smoke_check` | `<out>/run-1/` and `<out>/run-2/`, each with `console.log` |

Field-comparison outputs are listed on the
[Field comparison](@ref scripts_validation_field) page.

## 6\. Module layout

| File | Role |
|------|------|
| @ref build_config_files.py "build_config_files" | Writes per-run `nodes.json` and `run.ini` from field GPS and radio config CSVs. |
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

## 7\. Dependencies

| Scope | Needs |
|-------|-------|
| Field-comparison scripts (`build_*`, `compare*`, `scenario_fidelity`, `sim_to_traces`, `validate_days`, `make_jammers`) | Python 3.10+ (`build_config_files` uses `match`), `pandas`, `numpy`, `matplotlib` |
| `run_batch`, `regression_check`, `smoke_check` | A built simulator binary passed with `--sim-binary` (without it `run_batch` takes the first `build/scratch/mesh-sim/ns3*-sim-*` match, which may be stale) and `scripts/sim_support.py` |
| `regression_check`, `regression_snapshot`, `regression_suite`, `smoke_check` | Standard library only |
| Tests | `pytest`, plus `scripts.sweep` (imported by one test) |

The regression suite also needs the reference snapshots from the project team.
