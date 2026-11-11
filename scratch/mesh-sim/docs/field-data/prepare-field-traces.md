# Prepare field traces {#mesh_sim_field_data_traces}

[TOC]

Check the raw bundle, turn one day of it into per-node traces, and cut those
traces down to one time window.

## 1\. Before you start

- **Field bundle.** You have the per-node Silvus bundle on disk
  (\ref mesh_sim_field_data_workflow "Compare the simulator with field data",
  section 1), or you will make the synthetic practice bundle in section 2.
- **Python.** The `.venv` from
  \ref readme_python_environment "Python environment". The tools need Python
  3.10 or newer, `pandas`, `numpy` and `matplotlib`.
- **Working directory.** Run every command from `scratch/mesh-sim/`. The tools
  run as `python -m scripts.<package>.<module>`.

## 2\. Set the values once

<!-- Every output on these pages comes from the synthetic practice bundle made by
     docs/diagrams/field-example.py, run through the real tools on 2026-10-28 with
     binary SHA-256 d7a2f4d1eb52c30abb0c6cecc8480aa29232afd12730fcc402caa0fc446c9fe2.
     The bundle is invented: no node, place or value in it comes from field data. -->

**No bundle? Make the practice one.** It has the exact layout of a real
bundle, but every value is invented: four nodes, `unit-a` to `unit-d`, on a
made-up site, logging from 14:50 to 15:30 UTC on 2026-03-14. Its radio values
come from a simple path-loss formula, deliberately not the simulator's model.
Every output on these pages comes from it.

```bash
.venv/bin/python docs/diagrams/field-example.py --bundle-only outputs/field-practice-bundle
```

**Checkpoint:** it prints `wrote the synthetic bundle: .../outputs/field-practice-bundle`.

Now set these in the shell you will use for every page of this sequence. With
your own bundle, set `field_csv_root` to its absolute path and pick a day and
window it covers.

```bash
SIM_BIN="$(cd ../.. && pwd)/build/scratch/mesh-sim/ns3.42-sim-debug"
field_csv_root="$PWD/outputs/field-practice-bundle"
field_day="2026-03-14"
field_start="15.00"
field_end="15.20"
field_window="1500-1520"
field_work="outputs/field-data-workflow"
```

| Value | Meaning |
|---|---|
| `SIM_BIN` | Your built simulator, as an absolute path (\ref mesh_sim_install_build "Install and build"). The same name the placement and RL guides use. |
| `field_csv_root` | The raw bundle: one folder per node. |
| `field_day` | The UTC date to use. |
| `field_start`, `field_end` | The window's UTC start and end, written `HH.MM`: `15.20` means 15:20, not 15.2 hours. |
| `field_window` | The window's tag, `HHMM-HHMM`. Later steps name folders with it. |
| `field_work` | A new workspace folder for this attempt. |

Change the day, start, end and window tag **together**. The tag must be
exactly what the splitter derives from start and end, or later steps will not
find the folder.

Make the workspace:

```bash
mkdir -p outputs && mkdir "$field_work"
```

**Checkpoint:** the second `mkdir` succeeds. It has no `-p` on purpose: if the
workspace already exists, it fails. Pick a new `field_work` name rather than
reusing, deleting or overwriting earlier results.

## 3\. Check the raw data

`$field_csv_root` must hold one folder per node:

```
per-node-csv-root/
├── rab1/
│   ├── gps/gps_position.csv
│   └── silvus/
│       ├── config.csv
│       ├── network_status.csv
│       └── local_stats.csv       (optional)
├── rab2/
└── ...
```

| File | Needs |
|---|---|
| `gps/` and `silvus/` | Both folders present. A node missing either is skipped. |
| `gps/gps_position.csv` | `latitude`, `longitude` and `time` columns. `<node>/gps_position.csv` is accepted as a fallback, but `gps/` must still exist. |
| `silvus/config.csv` | A `node_id` in its first row. It also supplies the frequency, bandwidth and transmit power used in the next page. |
| `silvus/network_status.csv` | The radio statistics: `node_id`, `neighbor`, `snr`, `mcs`, `rssi_ant1`–`rssi_ant4`. |

The folder names become the node names everywhere downstream. The radio logs
identify nodes by Silvus numeric `node_id`; `config.csv` maps those numbers to
folder names. A neighbor the radio heard that is not one of the discovered
nodes is dropped. A folder named `sdwan` is ignored.

What the three files look like, from the practice bundle's `unit-b`:

```bash
head -n 3 "$field_csv_root/unit-b/gps/gps_position.csv"
cat "$field_csv_root/unit-b/silvus/config.csv"
head -n 3 "$field_csv_root/unit-b/silvus/network_status.csv"
```

```
time,latitude,longitude,callsign
1773499800000000000,39.5017966,-104.4918507,UNIT-B
1773499801000000000,39.5018437,-104.4918513,UNIT-B
time,node_id,virtual_ip,freq,bw,power_dBm
1773499800000000000,3102,10.0.0.2,2450,10,27
time,node_id,virtual_ip,neighbor,snr,mcs,mcs_rx,rssi_ant1,rssi_ant2,rssi_ant3,rssi_ant4
1773499800000000000,3102,10.0.0.2,3101,10.0,3,3,-85.5,-86.3,-86.1,-88.4
1773499800000000000,3102,10.0.0.2,3103,9.9,3,3,-86.4,-87.7,-89.4,-86.8
```

- `time` is UTC in nanoseconds since 1970.
- `unit-b` is radio `3102`. Its `network_status.csv` has one row per report
  and neighbor: here it heard `3101` (`unit-a`) at 10.0 dB SNR and `3103`
  (`unit-c`) at 9.9 dB.
- RCPI is not a column. The tools compute it as the mean of the four
  `rssi_ant` values, ignoring any at −110 dBm or below
  (\ref mesh_sim_field_data_assumptions "Transforms and assumptions",
  section 4).

**Checkpoint:** each node you want compared has both `gps/` and `silvus/`.

## 4\. Build daily traces

```bash
.venv/bin/python -m scripts.arpo_data.cli plot --nodes \
  -i "$field_csv_root" -o "$field_work/daily" --day "$field_day"
```

- `--nodes` is a switch; it takes no value.
- `--day` keeps rows whose UTC date matches. If the day is not in the bundle,
  the tool lists the days it found and exits 1. Without `--day`, every day is
  written to its own folder.

What it writes, per day:

<!-- Daily output figure. Styles: .ms-outtree in theme/mesh-sim.css. Layout
     follows scripts/arpo_data/cli.py (_plot_nodes_for_day, _save_pairs). -->
<div class="ms-outtree">
<div class="ms-ot-head"><span>File</span><span>What it holds</span><span>Read by</span></div>
<div class="ms-ot-row ms-ot-dir"><code>daily/&lt;day&gt;/</code><span>One UTC day.</span><span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>gps_all_nodes_trace.csv</code><span>Every node's GPS fixes for the day, in one file.</span><span><span class="ms-ot-tag ms-ot-plot">build_config_files</span><span class="ms-ot-tag ms-ot-plot">build_waypoints</span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>gps_all_nodes.png</code><span>All tracks on one map.</span><span><span class="ms-ot-tag ms-ot-you">you</span></span></div>
<div class="ms-ot-row ms-ot-l1 ms-ot-dir"><code>&lt;node&gt;/</code><span>One folder per node.</span><span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>gps_track_trace.csv</code><span>That node's GPS fixes, with a <code>.png</code> beside it.</span><span><span class="ms-ot-tag ms-ot-you">you</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>csvs/&lt;node&gt;/IH_snr__…</code><span>SNR the radio reported, per sample. Also <code>IH_rcpi</code>, <code>IH_mcs</code>, <code>IH_throughput</code>, <code>IH_per</code>.</span><span><span class="ms-ot-tag ms-ot-plot">compare</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>pngs/&lt;node&gt;/IH_snr__…</code><span>A plot of each trace.</span><span><span class="ms-ot-tag ms-ot-you">you</span></span></div>
</div>

Each trace file is named `IH_<metric>__<node>_to_neighbors_trace.csv`: one
file per node and metric, holding the samples for every neighbor that node
heard.

**Checkpoint:** one `wrote` line per file, for every node. The practice
bundle starts:

```
[2026-03-14]
    wrote .../daily/2026-03-14/unit-a/gps_track.png
    wrote .../daily/2026-03-14/unit-a/gps_track_trace.csv
    wrote .../daily/2026-03-14/unit-a/pngs/unit-a/IH_snr__unit-a_to_neighbors.png
```

and:

- `$field_work/daily/$field_day/gps_all_nodes_trace.csv` exists.
- For each node you want, `$field_work/daily/$field_day/<node>/csvs/<node>/`
  holds non-empty `IH_snr__*`, `IH_rcpi__*` and `IH_mcs__*` files.
- Read every `WARNING: ... skipping` line on stderr. A node with no GPS or no
  radio data that day is missing from every later step, even though the
  command exits 0.

Two plots from this step give a quick look at the day before you pick a
window.

### 4.1 Where the nodes went

**What to look for:** which nodes moved, and when. Color is time since the
first fix of the day.

\image html field-gps.png "gps_all_nodes.png for the practice bundle: every node's track over the whole day, colored by time."

`unit-a` is a single point: it never moved. `unit-b` drives a 300 m loop,
`unit-c` drives out and back, and `unit-d` walks around a small area. Axes are
meters east and north of the mean of every fix that day, the same frame the
scenario uses later. With real data, this plot is where you see parked
periods and travel between sites that a window should leave out.

### 4.2 What one node heard

**What to look for:** one colored series per neighbor, and when each one
appears or drops out.

\image html field-trace-snr.png "pngs/unit-b/IH_snr__unit-b_to_neighbors.png: the SNR unit-b reported for each neighbor over the day, with MCS thresholds on the right."

`unit-b` heard all three neighbors throughout. Each series rises and falls as
the nodes move toward and away from each other. A report exists only when the
radio heard that neighbor, so moments when a link was too weak to hear are
missing from the field side of every later comparison
(\ref mesh_sim_field_data_differences "Why the two sides differ", section 5.2).

## 5\. Cut one window

A day often holds several test events. Cut out the one you want to compare.
Why the comparison uses a window rather than the whole day, and exactly how
the cut works: \ref mesh_sim_field_data_assumptions "Transforms and assumptions",
sections 2 and 5.

```bash
.venv/bin/python -m scripts.arpo_data.cli split-scenario \
  -i "$field_work/daily/$field_day" \
  -o "$field_work/windows" --start "$field_start" --end "$field_end"
```

- `-i` is the **day folder**, not the `daily/` root.
- Pass `-o` explicitly. The default output is under `data/`, and the tool scans
  its input recursively, so a shared output folder can mix in older results.
- Traces from section 4 carry a `t_utc` column, so the splitter selects rows by
  UTC time of day and then restarts each file's elapsed-time column at 0.
- Older traces with only a `sec` column are anchored to the GPS start instead,
  which assumes every device started logging together. The tool prints a note
  when it does this. Traces from section 4 never need it.

**Checkpoint:** one line per file, with its row count. From the practice
bundle (first lines):

```
  gps_all_nodes_trace.csv: 4800 rows, 4 nodes
  unit-a/csvs/unit-a/IH_mcs__unit-a_to_neighbors_trace.csv: 1748 rows
  unit-a/csvs/unit-a/IH_rcpi__unit-a_to_neighbors_trace.csv: 1748 rows
  unit-a/csvs/unit-a/IH_snr__unit-a_to_neighbors_trace.csv: 1748 rows
...
Scenario generated (29748 rows across sliced files)
```

4,800 GPS rows is 20 minutes of one fix per second for 4 nodes. Then:

- `$field_work/windows/$field_window/` exists, with `gps_all_nodes_trace.csv`
  and the same `<node>/csvs/<node>/IH_*` files as the day.
- The per-file `rows` lines show non-zero counts for the nodes and metrics you
  need. If no sample falls in the window, the command exits 1.
- A window can have as many rows as the day, when all of the day's data
  already falls inside it.

## 6\. Going further

- \ref scripts_arpo_data "scripts/arpo_data": every subcommand, including
  `split-day`, `multi-day` and the legacy Spring Lake loaders.

Previous: \ref mesh_sim_field_data_workflow "Compare the simulator with field data" · Next: \ref mesh_sim_field_data_scenario "Build a scenario from field data"
