# Run and compare {#mesh_sim_field_data_compare}

[TOC]

Run the field scenario over several seeds, convert the simulator's output into
the field trace format, and compare the two.

## 1\. Before you start

- You finished \ref mesh_sim_field_data_scenario "Build a scenario from field data",
  so `$field_work/scenarios/$field_window/` has a patched `nodes.json`.
- `$SIM_BIN` points at your built simulator. No tool here builds it.
- The shell still has the values from
  \ref mesh_sim_field_data_traces "Prepare field traces", section 2.
- Run every command from `scratch/mesh-sim/`.

The output shown on this page comes from the synthetic practice bundle
(\ref mesh_sim_field_data_traces "Prepare field traces", section 2), window
`1500-1520`, nodes `unit-a` to `unit-d`. With your own bundle you see your
window's tag and node names in the same places.

## 2\. Run the simulator batch

```bash
.venv/bin/python -m scripts.validation.run_batch \
  --scenarios-dir "$field_work/scenarios" --only "$field_window" \
  --out "$field_work/batch" --seeds 1,2,3,4,5 \
  --sim-binary "$SIM_BIN"
```

| Flag | Why |
|---|---|
| `--sim-binary` | Always pass it. Without it the tool takes the first `build/scratch/mesh-sim/ns3*-sim-*` match, which may be an old build. |
| `--only` | Runs just this window's scenario. |
| `--out` | Keeps the batch in the workspace. Without it, the batch goes to a timestamped folder under `outputs/`. |
| `--seeds` | One simulator run per seed. Five seeds show how much the random channel draws move the result. |

Do not add `--auto-waypoints`. It fails, and the previous page already added
the waypoints.

**Checkpoint:** after a few seconds the console ends with `Done: 1 ok, 0 failed`:

```
Seeds:      1,2,3,4,5 (5 per scenario)
Scenarios:  1
  - 1500-1520

[1/1] 1500-1520
  ok  -> .../outputs/field-data-workflow/batch/1500-1520

Done: 1 ok, 0 failed
```

`$field_work/batch/batch_manifest.json` has one entry under `runs` with
`"status": "ok"` and `"exit_code": 0`. `ok` only means the simulator exited 0,
so also check the files:

<!-- Batch output figure. Styles: .ms-outtree in theme/mesh-sim.css. Layout
     from scripts/validation/run_batch.py, sim_to_traces.py and compare.py, and
     the practice-bundle run of docs/diagrams/field-example.py. -->
<div class="ms-outtree">
<div class="ms-ot-head"><span>File</span><span>What it holds</span><span>Read by</span></div>
<div class="ms-ot-row ms-ot-dir"><code>batch/</code><span>The batch root.</span><span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>batch_manifest.json</code><span>Binary, seeds, and one <code>status</code> / <code>exit_code</code> per scenario.</span><span><span class="ms-ot-tag ms-ot-you">you</span></span></div>
<div class="ms-ot-row ms-ot-l1 ms-ot-dir"><code>&lt;window&gt;/</code><span>The <b>scenario result folder</b>. Steps 6 and 7 take this path.</span><span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>inputs/</code><span>The archived <code>run.ini</code> and <code>nodes.json</code>.</span><span><span class="ms-ot-tag ms-ot-plot">sim_to_traces</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>run.log, console.log</code><span>The resolved settings, and the simulator's console output.</span><span><span class="ms-ot-tag ms-ot-you">you</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>seed-1/ … seed-5/</code><span>The usual per-seed CSVs: <code>links.csv</code>, <code>rx-power.csv</code>, <code>mcs.csv</code> and the rest.</span><span><span class="ms-ot-tag ms-ot-plot">sim_to_traces</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>sim_traces/seed-N/csvs/&lt;node&gt;/</code><span>Written in section 3: the seed's results in the field trace layout.</span><span><span class="ms-ot-tag ms-ot-plot">compare</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>validation/</code><span>Written in section 4: <code>metrics.csv</code> and <code>pngs/&lt;node&gt;/hist_*.png</code>.</span><span><span class="ms-ot-tag ms-ot-you">you</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>validation_summary.csv, summary/</code><span>Written in section 4: the same rows, and heatmaps.</span><span><span class="ms-ot-tag ms-ot-you">you</span></span></div>
</div>

Each `seed-N/` needs a non-empty `links.csv`, `rx-power.csv` and `mcs.csv`.
How to read those files: \ref mesh_sim_first_result "Understand the result".

Nothing here records the simulator's source commit or a fingerprint of the
raw bundle. Note both with your commands, so the comparison can be reproduced
(\ref src_io_run_record "What a run records").

## 3\. Convert simulator output to traces

```bash
.venv/bin/python -m scripts.validation.sim_to_traces -m node \
  "$field_work/batch/$field_window"
```

- The argument is the **scenario result folder**, not the batch root.
- It reads the archived `inputs/nodes.json` to turn simulator node numbers back
  into field names.
- It drops rows before the scenario's `warmup_s` (0 for generated scenarios).
- It takes SNR from `links.csv` `sinr_db`, RCPI from `rx-power.csv`
  `rx_power_dbm` and MCS from `mcs.csv` `mcs_index`.
- The simulator evaluates each pair of nodes once. The converter writes every
  row twice, once from each end, so each node lists all its neighbors. Both
  copies carry the same value
  (\ref mesh_sim_field_data_assumptions "Transforms and assumptions", section 7).

**Checkpoint:** one `seed-N: K trace csvs` line per seed, with K greater than 0:

```
[1500-1520]
  seed-1: 12 trace csvs
  seed-2: 12 trace csvs
  seed-3: 12 trace csvs
  seed-4: 12 trace csvs
  seed-5: 12 trace csvs
  total: 60 csvs
```

That is three metrics for each of four nodes, per seed. The files have the
same names as the field traces:

```
sim_traces/seed-1/csvs/unit-b/IH_mcs__unit-b_to_neighbors_trace.csv
sim_traces/seed-1/csvs/unit-b/IH_rcpi__unit-b_to_neighbors_trace.csv
sim_traces/seed-1/csvs/unit-b/IH_snr__unit-b_to_neighbors_trace.csv
```

Put a simulator trace beside the field trace for the same node:

```bash
head -n 3 "$field_work/batch/$field_window/sim_traces/seed-1/csvs/unit-b/IH_snr__unit-b_to_neighbors_trace.csv"
head -n 3 "$field_work/windows/$field_window/unit-b/csvs/unit-b/IH_snr__unit-b_to_neighbors_trace.csv"
```

```
sec,source,peer,tag_local_mac,tag_sta_mac,tag_interface,snr_db
0.0,unit-b,neighbors,unit-b,unit-c,,20.340232
0.0,unit-b,neighbors,unit-b,unit-d,,25.528507
sec,t_utc,source,peer,tag_local_mac,tag_sta_mac,tag_interface,snr_db
0.0,2026-03-14 15:00:00,unit-b,neighbors,unit-b,unit-a,,14.2
0.0,2026-03-14 15:00:00,unit-b,neighbors,unit-b,unit-d,,6.3
```

Same columns, same value column, so one reader loads both. The field trace
also keeps the UTC time, `t_utc`. Look at the one link both show at t = 0:
`unit-b` to `unit-d` is 25.5 dB in the simulator and 6.3 dB in the field. The
next page explains a gap like that.

`tag_sta_mac` holds the neighbor's name; the field traces hold radio MAC
addresses there. `tag_interface` is blank. The command exits 0 even when it
converts nothing, so always read the counts.

## 4\. Compare

```bash
.venv/bin/python -m scripts.validation.compare -m node \
  --batch_root "$field_work/batch/$field_window" \
  --field-root "$field_work/windows/$field_window"
```

- `--batch_root` is the scenario result folder; `--field-root` is the cut
  window.
- Only nodes with traces on **both** sides are compared.
- The default metrics are `snr`, `rcpi` and `mcs`. `--metrics snr` limits the
  run to one.
- `--window N` keeps only the first N seconds of both sides.

**Checkpoint:** one `wrote validation/pngs/<node>/hist_<metric>__<node>_to_neighbors.png`
line per compared node and metric, and these files:

| Output | Expected |
|---|---|
| `validation/metrics.csv` and `validation_summary.csv` | One row per compared (node, metric), with positive `n_sim` and `n_field` and finite `ks_statistic`, `abs_diff_medians` and `abs_diff_means`. |
| `validation/pngs/<node>/hist_*.png` | One overlay per (node, metric): simulator in orange, field in blue. |
| `summary/heatmap_*.png` | Heatmaps of the statistics across nodes, one file per metric and statistic. |

The command exits 0 even when it compares nothing. A missing row, or a row of
NaN values, means that node and metric were not compared.

From the practice bundle: 12 histograms (4 nodes × 3 metrics), then

```
    wrote validation/metrics.csv

summary: .../batch/1500-1520/validation_summary.csv

batch heatmaps:
  wrote summary/heatmap_snr_dmedian.png
  wrote summary/heatmap_snr_dmean.png
  wrote summary/heatmap_snr_KS.png
  ...
```

### 4.1 The main result

One histogram per node and metric. **What to look for:** whether the orange
and blue piles overlap, and how far apart the dotted median lines are.

\image html field-hist-snr.png "validation/pngs/unit-b/hist_snr__unit-b_to_neighbors.png: unit-b's SNR, simulator (orange, 5 seeds averaged) against the practice bundle (blue)."

The two piles barely overlap: the simulator is about 17.5 dB higher. The
orange pile is the five seeds averaged row by row, not joined, which narrows
it a little
(\ref mesh_sim_field_data_assumptions "Transforms and assumptions", section 7.3).
\ref mesh_sim_field_data_read "Read the comparison" reads this figure and the
others in detail.

## 5\. Going further

- \ref mesh_sim_field_data_read "Read the comparison": what the numbers and
  plots mean.
- \ref scripts_validation "scripts/validation": `validate_days`, which runs
  sections 3 and 4 for many days at once.

Previous: \ref mesh_sim_field_data_scenario "Build a scenario from field data" · Next: \ref mesh_sim_field_data_read "Read the comparison"
