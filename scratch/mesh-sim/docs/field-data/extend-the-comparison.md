# Extend the comparison {#mesh_sim_field_data_extend}

[TOC]

How the field comparison is put together, and how to grow it: compare
another window or day, try different radio settings, or compare a new metric.
Each change is walked through on the practice bundle with its real output.

<!-- Every output on this page comes from the synthetic practice bundle on
     2026-10-28 (binary SHA-256 d7a2f4d1eb52c30abb0c6cecc8480aa29232afd12730fcc402caa0fc446c9fe2).
     Section 5 (two extra windows) is part of docs/diagrams/field-example.py.
     Section 7 (the mcs_rx metric) was applied to a scratch copy of scripts/ and
     run there; the repository does not contain mcs_rx. Figures:
     docs/diagrams/field-extend.py. -->

## 1\. Before you start

- You have run, or read, the sequence from
  \ref mesh_sim_field_data_traces "Prepare field traces" to
  \ref mesh_sim_field_data_read "Read the comparison".
- Run every command from `scratch/mesh-sim/`, with the shell values from
  \ref mesh_sim_field_data_traces "Prepare field traces", section 2.

## 2\. How the pieces fit

Two packages do the work. `scripts/arpo_data` turns the raw field logs into
traces. `scripts/validation` builds a scenario from a window, runs it,
converts the simulator's output into the same kind of trace, and compares the
two.

**What to look for:** the two green boxes. They are where the field side and
the simulator side meet.

\image html field-pipeline-map.svg "The field-data pipeline. Top: the field side. Bottom: the simulator side. The window's traces and the simulator's traces share one file format, so compare reads both the same way."

The whole design rests on that meeting point. We convert the simulator's
output into **exactly** the trace files the field side writes, so `compare`
needs only one reader and never has to know which side a file came from.

## 3\. The one rule: both sides write the same trace file

Every trace file, field or simulator, looks like this:

```
sec,source,peer,tag_local_mac,tag_sta_mac,tag_interface,snr_db
0.0,unit-b,neighbors,unit-b,unit-c,,20.340232
```

| Part | Rule |
|---|---|
| File name | `IH_<metric>__<node>_to_neighbors_trace.csv`, one per node and metric |
| Folder | `windows/<tag>/<node>/csvs/<node>/` on the field side; `sim_traces/seed-N/csvs/<node>/` on the simulator side |
| Columns | `sec`, `source`, `peer`, `tag_local_mac`, `tag_sta_mac`, `tag_interface`, then one value column. Field files also keep `t_utc`. |
| Value column | `snr_db`, `rcpi_dbm` or `mcs_tx`, and the same name on both sides |

If you rename the file, move the folder or change the value column on one
side only, `compare` quietly finds nothing to compare. Always change both
sides together.

## 4\. Where everything lives

**`scripts/arpo_data/`: the field side.** It reads the raw logs and never
writes to them.

| File | What it does |
|---|---|
| `loaders.py` | Reads the raw CSVs: GPS, radio statistics, and the RCPI average |
| `plots/bh2.py` | One `plot_silvus_<metric>` function per metric; each returns a plot and the trace table |
| `plots/gps.py` | GPS tracks, and the conversion to meters east and north |
| `cli.py` | Every command (`plot`, `split-scenario`, …) and every file it writes |
| `split_trace_by_scenario.py` | Cutting traces to a window |
| `extract.py`, `paths.py`, `topology.py`, `multi_day.py`, … | The older Spring Lake log format |

**`scripts/validation/`: the simulator side and the comparison.**

| File | What it does |
|---|---|
| `build_config_files.py` | Writes `run.ini` and `nodes.json` from a window; its defaults are constants at the top |
| `build_waypoints.py` | Turns GPS tracks into waypoints in `nodes.json` |
| `run_batch.py` | Runs the simulator once per scenario and seed |
| `sim_to_traces.py` | Converts simulator output into trace files; `_METRIC_SPECS_NODE` says which simulator column feeds which metric |
| `compare.py` | Averages the seeds, computes the numbers, draws the plots; `_METRICS` lists the metrics it knows |
| `compare_runs.py`, `compare_baseline.py`, `scenario_fidelity.py`, `validate_days.py` | Follow-up tools (\ref mesh_sim_field_data_read "Read the comparison", section 9) |
| `make_jammers.py` | Builds a `jammers.json` from a field jamming trial |

## 5\. Compare another window or day

No code changes: run the sequence again with new values. Each window gets its
own scenario folder (named by its tag) and its own batch folder.

The practice bundle logs from 14:50 to 15:30, so besides 15:00–15:20 we can
cut two more windows. For 14:50–15:00:

```bash
.venv/bin/python -m scripts.arpo_data.cli split-scenario \
  -i "$field_work/daily/$field_day" -o "$field_work/windows" --start 14.50 --end 15.00
.venv/bin/python -m scripts.validation.build_config_files \
  -i "$field_work/windows" --day 1450-1500 \
  --csv-dir "$field_csv_root" --band sub-6 --mode node -o "$field_work/scenarios"
.venv/bin/python -m scripts.validation.build_waypoints node \
  -i "$field_work/scenarios/1450-1500" \
  -f "$field_work/windows/1450-1500/gps_all_nodes_trace.csv" --all-nodes --time-mode raw
.venv/bin/python -m scripts.validation.run_batch \
  --scenarios-dir "$field_work/scenarios" --only 1450-1500 \
  --out "$field_work/batch-1450-1500" --seeds 1,2,3,4,5 --sim-binary "$SIM_BIN"
.venv/bin/python -m scripts.validation.sim_to_traces -m node "$field_work/batch-1450-1500/1450-1500"
.venv/bin/python -m scripts.validation.compare -m node \
  --batch_root "$field_work/batch-1450-1500/1450-1500" \
  --field-root "$field_work/windows/1450-1500"
```

Give each window its own `--out` folder. `run_batch` writes one
`batch_manifest.json` per output folder.

**Checkpoint:** the split prints `gps_all_nodes_trace.csv: 2400 rows, 4 nodes`
(10 minutes × 4 nodes), the scenario is `1450-1500: 4 nodes, duration=599s`,
and `build_waypoints` ends `summary: 3 patched, 1 skipped, 0 errors`.

**What to look for:** whether each node's gap stays put from window to window.

\image html field-windows.svg "SNR median gap per node in three windows of the practice bundle, each with its own scenario and 5 seeds (validation/metrics.csv of each batch)."

Here every node's gap stays within a few dB across all three windows. A gap
that holds steady like this points to something **systematic**: a radio
setting or the channel model, which every window shares. A gap that jumps in
one window points to something that changed **in that event**: a different
layout, an obstruction, a node with a problem.

**A whole day at once:** leave out `--day` in `plot --nodes` to write every
day, pass `--all-days` to `build_config_files`, and use `validate_days
--all-days` to convert and compare them all. Remember why we cut windows in
the first place (\ref mesh_sim_field_data_assumptions "Transforms and assumptions",
section 2).

## 6\. Try different radio or channel settings

Use the generator's flags rather than editing its code. That way every run
records its own choice in its `run.ini`.

| To change | Flag on `build_config_files` |
|---|---|
| Antenna gains | `--tx-gain`, `--rx-gain` |
| Receiver noise | `--noise-figure` |
| Path-loss model | `--channel-scenario` (`RMa`, `UMi`, `UMa`, `InH`) |
| Line of sight | `--condition-model` (`static_los`, `auto`) |
| MCS table | `--amc-model` |
| Tick and length | `--tick`, `--time` |

Change one thing per run, write each to its own `-o` folder, and compare the
results. \ref mesh_sim_field_data_read "Read the comparison", section 6,
walks through one such change: matching the gains and noise figure closes
exactly 6 dB of the gap.

Only edit a constant in `build_config_files.py` when the default itself is
wrong for every run, and then update the defaults table on
\ref mesh_sim_field_data_scenario "Build a scenario from field data".

## 7\. Compare a new metric

Adding a metric means teaching three places about it: the field side has to
write its trace, the simulator side has to write the matching trace, and
`compare` has to know the metric's name and column. Here is a full worked
example: the **receive-side MCS** (`mcs_rx`), which the radios already log in
`network_status.csv` but the pipeline doesn't compare yet. The simulator has
one MCS per link, so its side reuses `mcs_index`.

That is seven small edits in five files.

**Step 1. Carry the field column through.** In `scripts/arpo_data/plots/bh2.py`,
add the column to the map in `_silvus_to_bh2_format`:

```python
        "mcs":             "field_mcs_tx",
        "mcs_rx":          "field_mcs_rx",
```

**Step 2. Write the field trace.** In the same file, add a plot function
modeled on `plot_silvus_mcs`:

```python
def plot_silvus_mcs_rx(df: pd.DataFrame, scenario_name: str = "") -> list[_BH2_PairResult]:
    return _per_radio_metric(
        df=_silvus_to_bh2_format(df),
        scenario_name=scenario_name,
        value_col="field_mcs_rx",
        metric_label="MCS (receive)",
        title_metric="MCS rx",
        trace_col="mcs_rx",
        file_prefix="IH_mcs_rx",
        integer_yaxis=True,
        use_antenna_legend=True,
        connect_lines=True,
    )
```

`trace_col` becomes the value column; `file_prefix` becomes the file name.

**Step 3. Export it.** Add `plot_silvus_mcs_rx` to the import list and to
`__all__` in `scripts/arpo_data/plots/__init__.py`.

**Step 4. Call it.** In `scripts/arpo_data/cli.py`, import it, and add one line
after each of the **two** places that save `IH_mcs`:

```python
        _save_pairs(plot_silvus_mcs_rx(rf_data, node_dir.name),     out, "IH_mcs_rx")
```

(the second place uses `rf_day` instead of `rf_data`).

**Checkpoint:** `plot --nodes` now also writes `IH_mcs_rx` files, and
`split-scenario` cuts them:

```
    wrote work/daily/2026-03-14/unit-a/csvs/unit-a/IH_mcs_rx__unit-a_to_neighbors_trace.csv
  unit-b/csvs/unit-b/IH_mcs_rx__unit-b_to_neighbors_trace.csv: 1755 rows
```

**Step 5. Write the simulator trace.** In `scripts/validation/sim_to_traces.py`,
add a row to `_METRIC_SPECS_NODE`: which simulator file and column, then the
metric's short name and the trace column. They must match step 2.

```python
_METRIC_SPECS_NODE = (
    ("links",    "sinr_db",      "snr",  "snr_db"),
    ("mcs",      "mcs_index",    "mcs",  "mcs_tx"),
    ("mcs",      "mcs_index",    "mcs_rx", "mcs_rx"),
    ("rx-power", "rx_power_dbm", "rcpi", "rcpi_dbm"),
)
```

Add it to `_METRIC_SPECS_NODE` only; the similar `_METRIC_SPECS` above it is
for the older format.

**Checkpoint:** each seed now has 16 trace files instead of 12:

```
  seed-4: 16 trace csvs
  seed-5: 16 trace csvs
  total: 80 csvs
```

**Step 6. Teach `compare`.** In `scripts/validation/compare.py`, add the metric
to `_METRICS`, capped like MCS, and give it a unit in `_UNIT_BY_SHORT`:

```python
    _MetricSpec("mcs_rx", "mcs_rx", "MCS (receive)", integer_cap=_MCS_FIELD_CAP),
```

```python
_UNIT_BY_SHORT = {"snr": "dB", "rcpi": "dB", "mcs": "", "mcs_rx": "", "per": "", "throughput": "Mbps"}
```

**Checkpoint:**

```bash
.venv/bin/python -m scripts.validation.compare -m node \
  --batch_root "$field_work/batch/$field_window" \
  --field-root "$field_work/windows/$field_window" --metrics mcs_rx
```

```
  wrote validation/pngs/unit-a/hist_mcs_rx__unit-a_to_neighbors.png
  ...
    wrote validation/metrics.csv
```

and `metrics.csv` has a row per node, for example `unit-a, mcs_rx, n_sim 3600,
n_field 1748, sim median 6.0, field median 3.0`.

In the practice bundle, `mcs_rx` is a copy of `mcs`, so these numbers match
the MCS row. With real logs the two differ.

**Step 7. Check it means what you think.** Make sure the field column and the
simulator column measure the same thing. For example, the simulator's
`links.csv` `delivered_mbps` is the traffic our router put on a link, set by
the scenario's 1.25 Mbps demand. It is not the radio's throughput, so it
should not be paired with the radios' `IH_throughput`. Write down any
remaining difference on
\ref mesh_sim_field_data_differences "Why the two sides differ".

There are no unit tests for `sim_to_traces` or `compare`, so the checkpoints
above are the test: the file counts go up, and the new metric gets a row with
both sample counts above zero.

## 8\. Other changes

- **Keep a generated scenario.** By default `build_config_files` writes to
  `inputs/calfex/`, which Git ignores. A generated `nodes.json` holds field GPS
  positions, so ask the data owner before you copy one into a tracked folder.
- **Add jammers from a field trial.** `scripts.validation.make_jammers` writes a
  `jammers.json` from a jamming-trial CSV
  (\ref scripts_validation "scripts/validation", section 3).

## 9\. Known issues we have not fixed yet

| Issue | What happens |
|---|---|
| `run_batch --auto-waypoints` | Fails. Run `build_waypoints` first instead. |
| `build_waypoints --anchor` | Off by default, although `--help` says otherwise. |
| `build_waypoints --dry-run` | Still writes the nodes that didn't move. |
| `validate_days --time` | Required, but not used. |
| `sim_to_traces`, `compare` | Exit 0 even when they produce nothing; always read the counts. |
| `plot --scenario` / `--all` | Fail on Silvus data. Only `plot --nodes` works. |
| `multi-day` | Only finds the older `bh2_*` traces. |
| The older Spring Lake route (`-m scenario`) | Needs folders a clean checkout doesn't have. |

## 10\. Tests

| Command | What it checks |
|---|---|
| `.venv/bin/python -m pytest scripts/validation/tests -q` | The regression tools, and the `run_batch` and sweep launchers |

`scripts/arpo_data`, `build_config_files`, `build_waypoints`, `sim_to_traces`
and `compare` have no unit tests. Check a change by running the sequence on
the practice bundle and comparing with an earlier workspace.

## 11\. Going further

- \ref scripts_validation "scripts/validation" and
  \ref scripts_arpo_data "scripts/arpo_data": every flag and output.
- \ref research_field_calibration "Field calibration limits": what we know
  about real comparisons.

Previous: \ref mesh_sim_field_data_jamming "Jammed windows"
