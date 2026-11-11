# Build a scenario from field data {#mesh_sim_field_data_scenario}

[TOC]

Turn the time window from the previous page into a simulator scenario whose
nodes start where the field nodes started and move the way they moved.

## 1\. Before you start

- You finished \ref mesh_sim_field_data_traces "Prepare field traces", so
  `$field_work/windows/$field_window/` exists.
- The shell still has the values from section 2 of that page.
- Run every command from `scratch/mesh-sim/`.

## 2\. What the scenario takes from the field

A generated scenario mixes measured values with fixed defaults. Know which is
which before you read any comparison: a default that does not match the real
radios shifts every simulated value.

<!-- Field-vs-default figure. Styles: .ms-stack in theme/mesh-sim.css.
     Sources: scripts/validation/build_config_files.py (module constants,
     _load_channel_config, _load_day_gps, _create_ini) and build_waypoints.py. -->
<div class="ms-stack">
<div class="ms-stack-row ms-stack-head"><div>Setting</div><div>Where it comes from</div><div>Value</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer">Node names</div><div>Folder names in the raw bundle.</div><div class="ms-stack-same"><span class="ms-stack-tag">From the field</span>One node per name in the window's GPS trace.</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer">Start positions</div><div>Each node's first GPS fix in the window, in meters east and north of the day's mean fix (flat-earth frame).</div><div class="ms-stack-same"><span class="ms-stack-tag">From the field</span>x and y per node.</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer">Movement</div><div>The window's GPS track, added in section 4.</div><div class="ms-stack-same"><span class="ms-stack-tag">From the field</span>Up to 20 waypoints per node, on the node's own clock.</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer">Duration</div><div>The span of the window's GPS samples, unless you pass <code>&#45;&#45;time</code>.</div><div class="ms-stack-same"><span class="ms-stack-tag">From the field</span>Can be shorter than the clock window you asked for.</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer">Frequency, bandwidth, transmit power</div><div>The median, over nodes, of the first row of each <code>silvus/config.csv</code>.</div><div class="ms-stack-same"><span class="ms-stack-tag">From the field</span>Falls back to 2400 MHz, 20 MHz and 30 dBm when a column is missing everywhere.</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer">Antenna gains, noise figure</div><div>Generator defaults, changeable with <code>&#45;&#45;tx-gain</code>, <code>&#45;&#45;rx-gain</code>, <code>&#45;&#45;noise-figure</code>.</div><div class="ms-stack-replaced"><span class="ms-stack-tag">Default</span>6 dBi transmit, 6 dBi receive, 5 dB noise figure.</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer">Propagation</div><div>Generator defaults, changeable with <code>&#45;&#45;channel-scenario</code> and <code>&#45;&#45;condition-model</code>.</div><div class="ms-stack-replaced"><span class="ms-stack-tag">Default</span>3GPP RMa, always line of sight (<code>static_los</code>), no buildings.</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer">Capacity model</div><div>Generator default, changeable with <code>&#45;&#45;amc-model</code>.</div><div class="ms-stack-replaced"><span class="ms-stack-tag">Default</span>Silvus MCS table.</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer">Node height</div><div>Fixed by the generator.</div><div class="ms-stack-replaced"><span class="ms-stack-tag">Default</span>1.5 m for every node, unless <code>build_waypoints &#45;&#45;field-z</code> sets one.</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer">Time and traffic</div><div>Generator defaults; <code>&#45;&#45;tick</code> changes the tick.</div><div class="ms-stack-replaced"><span class="ms-stack-tag">Default</span>1 s tick, no warm-up, 1.25 Mbps between every pair of nodes.</div></div>
</div>

Traffic does not affect the comparison: SNR, RCPI and MCS do not depend on
load in the simulator, because nodes do not interfere with each other.

How each "from the field" row is computed (the duration, the flat-earth frame,
the waypoints, the static test) is worked through with equations on
\ref mesh_sim_field_data_assumptions "Transforms and assumptions", sections 5
and 6. What the "default" rows can do to the result is on
\ref mesh_sim_field_data_differences "Why the two sides differ".

## 3\. Build the scenario

```bash
.venv/bin/python -m scripts.validation.build_config_files \
  -i "$field_work/windows" --day "$field_window" \
  --csv-dir "$field_csv_root" --band sub-6 --mode node \
  --name field-data-example -o "$field_work/scenarios"
```

| Flag | Meaning |
|---|---|
| `-i` | The folder that holds the window folder. |
| `--day` | The window folder's name. For a cut window this is the window tag, not the date. `--all-days` builds one scenario per folder instead. |
| `--csv-dir` | The raw bundle, for the `silvus/config.csv` files. |
| `--band sub-6 --mode node` | Both required. These are the only values implemented for this pipeline. |
| `--name` | Sets `[scenario] name` in `run.ini`. The output folder is still named after the window. |
| `-o` | Where to write. Pass it: the default is `inputs/calfex`, inside the tracked tree. |

**Checkpoint:** from the practice bundle:

```
Loading node data ...
  csv dir: .../outputs/field-practice-bundle
  channel: 2.45 GHz  bw=10.0 MHz  tx=27.0 dBm  nf=5.0 dB  gain=6.0/6.0 dBi  [sub-6]
  wrote outputs/field-data-workflow/scenarios/1500-1520/nodes.json  (4 nodes)
  wrote outputs/field-data-workflow/scenarios/1500-1520/run.ini
  1500-1520: 4 nodes, duration=1199s
```

The `channel:` line shows which values came from the bundle (2.45 GHz, 10 MHz,
27 dBm, the medians of the nodes' `config.csv`) and which are defaults (5 dB
noise figure, 6 dBi gains). The duration is 1199 s, not 1200: it is the span
from the first to the last GPS fix in the window.

The generated `run.ini`, abridged:

```ini
[scenario]
name = field-example
duration_s = 1199.0
warmup_s = 0.0
tick_s = 1.0
nodes_file = nodes.json

[channel]
band = sub-6
frequency_ghz = 2.45
tx_power_dbm = 27.0
bandwidth_mhz = 10.0
noise_figure_db = 5.0
channel_model = 3gpp
scenario = RMa
condition_model = static_los
amc_model = silvus
tx_array_gain_dbi = 6.0
rx_array_gain_dbi = 6.0

[traffic]
model = constant
demand_mbps = 1.25
flow_topology = all_pairs
```

It also writes `[routing]`, `[output]` and an `[rl]` section with `enabled = false`
and x/y bounds around the tracks. Every key: \ref files_run_ini "run.ini".

Then check:

- The console names as many nodes as you expect.
- `$field_work/scenarios/$field_window/run.ini` and `nodes.json` exist.
- `nodes.json` lists the node names you expect, each with a finite start
  position (zero is allowed) and `waypoint` mobility with an empty
  `waypoints` list. The next section fills those lists.
- `run.ini` has `band = sub-6` under `[channel]` and a positive `duration_s`.

Every `run.ini` key the generator writes is described in
\ref files_run_ini "run.ini".

## 4\. Add field mobility

```bash
.venv/bin/python -m scripts.validation.build_waypoints node \
  -i "$field_work/scenarios/$field_window" \
  -f "$field_work/windows/$field_window/gps_all_nodes_trace.csv" \
  --all-nodes --time-mode raw
```

- It **edits `nodes.json` in place**. There is no separate waypoint file. To
  start over, rerun section 3.
- `-f` is the window's combined GPS file.
- `--time-mode raw` keeps each node's own field timing, starting at that node's
  first fix in the window. The other modes stretch (`scale`) or cut (`clip`)
  every track to `--duration` seconds; pair either with the same `--time` in
  section 3, or nodes stop moving early.
- Each track is reduced to at most 20 waypoints (`--n-waypoints`).
- A node whose whole track fits inside a 20 m box is written as `fixed` and
  reported `skipped: ... (static)`. That is correct for a node that did not
  move.
- `--anchor` and `--dry-run` do not behave as `--help` says; see
  \ref mesh_sim_field_data_extend "Extend the comparison", section 6.

**Checkpoint:** from the practice bundle:

```
  unit-a: skipped: field unit-a bbox 0.0 m <= 20 m (static)
  unit-b: patched: 20 waypoints, bbox 595x597 m, path 5965 m, t 0..1199 s
  unit-c: patched: 20 waypoints, bbox 947x189 m, path 1929 m, t 0..1199 s
  unit-d: patched: 20 waypoints, bbox 159x119 m, path 628 m, t 0..1199 s

summary: 3 patched, 1 skipped, 0 errors
```

`unit-a` never moved, so it stays `fixed`. The other three now follow their
GPS tracks. One entry of the patched `nodes.json`:

```json
{"id": "unit-b", "role": "peer", "mobility": "waypoint",
 "position": {"x": -63.4, "y": -175.1, "z": 1.5},
 "waypoints": [{"t": 0.0, "x": -63.4, "y": -175.1, "z": 1.5},
               {"t": 64.0, "x": 254.3, "y": -164.0, "z": 1.5},
               ...]}
```

Positions are meters east and north of the day's mean GPS fix; `t` is seconds
into the scenario. 20 waypoints over a 6-minute loop is coarse: between
waypoints the node moves in a straight line, so the simulated `unit-b` cuts
corners the real track did not, by up to 46 m
(\ref mesh_sim_field_data_assumptions "Transforms and assumptions", section 6.2,
draws it). Raise `--n-waypoints` to follow it more closely.

Then check:

- Every node line reads `<node>: patched ...` or `<node>: skipped ... (static)`.
- The last line is `summary: N patched, M skipped, 0 errors`.
- In `nodes.json`, each patched node has a non-empty `waypoints` list whose
  first `t` is 0, and each static node has `fixed` mobility.

## 5\. Going further

- \ref scripts_validation "scripts/validation", section 9: the generator's
  behavior notes and known issues.
- \ref files_nodes_json "nodes.json": how `waypoint` mobility moves a node
  between waypoints.

Previous: \ref mesh_sim_field_data_traces "Prepare field traces" · Next: \ref mesh_sim_field_data_compare "Run and compare"
