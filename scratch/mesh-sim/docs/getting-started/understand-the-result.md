# Understand the result {#mesh_sim_first_result}

[TOC]

What the run from \ref mesh_sim_first_run "Your first run" wrote, how to read
it, and how to graph it. The numbers and figures on this page come from that
exact run: scenario `01-static-los-baseline`, seed 1.

## 1\. What the run wrote

Everything is under the `--output-dir` you passed,
`scratch/mesh-sim/outputs/getting-started/01-static-los-baseline/`.

<!-- Output-folder figure. Styles: .ms-outtree in theme/mesh-sim.css.
     File list and readers follow src/io/README.md and scripts/plotting/README.md. -->
<div class="ms-outtree">
<div class="ms-ot-head"><span>File</span><span>What it holds</span><span>Read by</span></div>
<div class="ms-ot-row ms-ot-dir"><code>01-static-los-baseline/</code><span>The run folder: one per command.</span><span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>run.log</code><span>The settings the run actually used. <b>Check this first.</b></span><span><span class="ms-ot-tag ms-ot-you">you</span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>inputs/</code><span>A copy of the scenario files (<code>run.ini</code>, <code>nodes.json</code>).</span><span><span class="ms-ot-tag ms-ot-you">you</span></span></div>
<div class="ms-ot-row ms-ot-l1 ms-ot-dir"><code>seed-1/</code><span>Results for seed 1. Each seed gets its own folder.</span><span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>summary.json</code><span>Averages over the run: per node, per flow and for the whole network.</span><span><span class="ms-ot-tag ms-ot-you">you</span><span class="ms-ot-tag ms-ot-plot">plotting</span><span class="ms-ot-tag ms-ot-viz">visualizer</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>links.csv</code><span>Every node pair at every saved tick: distance, SINR, LOS/NLOS, capacity, traffic carried.</span><span><span class="ms-ot-tag ms-ot-plot">plotting</span><span class="ms-ot-tag ms-ot-viz">visualizer</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>flows.csv</code><span>Every flow at every saved tick: demand, delivered rate, latency, hops.</span><span><span class="ms-ot-tag ms-ot-plot">plotting</span><span class="ms-ot-tag ms-ot-viz">visualizer</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>positions.csv</code><span>Where every node is at every saved tick.</span><span><span class="ms-ot-tag ms-ot-plot">plotting</span><span class="ms-ot-tag ms-ot-viz">visualizer</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>rx-power.csv</code><span>Received power per node pair.</span><span><span class="ms-ot-tag ms-ot-plot">plotting</span><span class="ms-ot-tag ms-ot-viz">visualizer</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>mcs.csv</code><span>MCS index and spectral efficiency per node pair.</span><span><span class="ms-ot-tag ms-ot-plot">plotting</span><span class="ms-ot-tag ms-ot-viz">visualizer</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>routes.csv</code><span>The path each flow took, and its bottleneck capacity.</span><span><span class="ms-ot-tag ms-ot-viz">visualizer</span></span></div>
</div>

"Saved tick" means every `[output] viz_tick_ms` of simulated time. This
scenario saves every 100 ms, the same as its tick length, so every tick is in
the CSVs. Run without `--output-dir` and the folder is
`scratch/mesh-sim/outputs/YYYY-MM/DD/HH-MM-SS/` instead.

Each file has its own page, with every column and how to read it:
\ref mesh_sim_files "Input and output files".

## 2\. Check run.log first

`run.log` records the settings the simulator resolved from `run.ini` and the
command line. Confirm they are what you meant before reading any results:

```bash
sed -n '/Resolved config/,/rl\./p' scratch/mesh-sim/outputs/getting-started/01-static-los-baseline/run.log
```

From this run:

```
Resolved config:
  duration_s          = 5
  tick_s              = 0.1
  nodes               = 2
  channel_model       = 3gpp
  scenario            = RMa
  frequency_ghz       = 28
  bandwidth_mhz       = 400
  tx_power_dbm        = 30
  traffic.model       = constant
  traffic.demand_mbps = 10
  routing.algorithm   = shortest_path
  band                = mmwave
  band_source         = default
```

`band_source = default` means neither `--band` nor `run.ini` set the band, so
the default `mmwave` was used. Some settings, such as the AMC model and antenna
gains, are not in this block; \ref files_run_log "run.log" covers every line.

## 3\. The headline numbers

`summary.json` averages each metric over the run (after `warmup_s`, which is 0
here). From this run:

```json
"network": {
    "connectivity": 1.0,
    "flows_routed": 1.0,
    "flows_unroutable": 0.0,
    "mean_hop_count": 1.0,
    "mean_sinr_db": 34.66,
    "sum_throughput_mbps": 10.0
},
"per_flow": {
    "node-a->node-b": {
        "delivered_mbps": 10.0,
        "demand_mbps": 10.0,
        "hop_count": 1.0,
        "latency_ms": 0.50
    }
}
```

| Metric | This run | What it tells you |
|---|---|---|
| Link SINR | about 34.6 dB | Signal quality on the one link. A link carries nothing below −6.7 dB. |
| Link capacity | about 4,600 Mbps | The most the link could carry at that SINR. |
| MCS index | 15 (the top of the table) | The modulation and coding the link would use. |
| Demand / delivered | 10 / 10 Mbps | The flow got everything it asked for. |
| Latency | 0.5 ms | One hop: propagation plus a fixed 0.5 ms processing delay. |
| Connectivity | 1.0 | The fraction of node pairs with a usable link. |

`delivered_mbps` is a flow-level rate, since Mesh-Sim does not simulate packets.
When it is below `demand_mbps`, a link on the flow's path ran out of capacity.
Every key and how it is averaged: \ref files_summary_json "summary.json".

## 4\. Graph it

### What this run looks like

\image html first-result.svg "Seed 1 of 01-static-los-baseline: link SINR, capacity against traffic, MCS index and flow latency over the 5 s run."

Two fixed nodes 100 m apart give flat lines, which is the point of this
scenario: any drift would be a bug. The first saved tick (t = 0) is about 1 dB
higher than the rest; from 0.1 s on, every value is constant. The capacity
panel uses a log scale so the 10 Mbps demand and the ~4,600 Mbps capacity fit
on one plot. The gap between them is the link's headroom.

This figure is generated by `docs/diagrams/first-result.py` from the run's CSVs.

### Make the standard plots

`scripts/plotting` turns any run folder into a full set of figures. From
`scratch/mesh-sim/`, with the Python environment set up
(\ref readme_python_environment "Python environment"):

1. Make a plot config pointing at your run (in `outputs/`, which Git ignores):

   ```bash
   sed 's|^data_dir.*|data_dir = outputs/getting-started/01-static-los-baseline|' \
       scripts/plotting/plot.example.ini > outputs/plot.ini
   ```

2. Make the plots:

   ```bash
   .venv/bin/python -m scripts.plotting.cli --config outputs/plot.ini
   ```

3. Open `outputs/getting-started/01-static-los-baseline/figures/`.

| Figures | From | Shows |
|---|---|---|
| `sinr_timeseries`, `rx_power_timeseries`, `capacity_timeseries`, `mcs_timeseries` | the link CSVs | Each link over time. |
| `flow_throughput_timeseries`, `link_throughput_timeseries`, `latency_timeseries` | `flows.csv`, `links.csv` | Traffic and latency over time. |
| `geometry` | `positions.csv` | Elevation and azimuth between nodes over time. |
| `per_node_sinr`, `per_node_tx_throughput`, `per_node_rx_throughput` | `summary.json` | Per-node bar charts. |
| `per_flow_throughput`, `per_flow_latency` | `summary.json` | Per-flow bar charts. |
| `network_summary`, `sim_runtime` | `summary.json` | A table of the network metrics, and run time. |

Turn any figure off with `<name> = false` under `[plots]`. With several seeds,
the plots show the mean with 95% confidence intervals. How to read each figure,
and every `plot.ini` setting: \ref files_figures "Figures".

\image html plotting-capacity-timeseries.png "capacity_timeseries from scripts/plotting for the same run. The tool autoscales the y-axis, so the 0.1 s step looks large; it is about 3% (4,729 to 4,604 Mbps)."

### Watch it in the visualizer

The **ns3-mmwave-viz** app replays a run folder in 3D: nodes, links and routes over time. With
the visualizer repository checked out beside `ns3-mmwave`:

```bash
cd ns3-mmwave-viz
npm install
npm run dev
```

Open `http://localhost:5173`, tick the run's folder on the **Folders** page,
then open **Simulation runs** and pick the seed. The visualizer's own
documentation is linked from the \ref index "landing page".

\image html home-urban-jamming-9-peers.jpg "The visualizer replaying a larger scenario: nine peers in an urban area with jamming. Your first run shows two nodes and one link."

### Plot something yourself

The CSVs load directly into pandas. For example, link SINR over time:

```python
import pandas as pd
import matplotlib.pyplot as plt

links = pd.read_csv("outputs/getting-started/01-static-los-baseline/seed-1/links.csv")
for (a, b), link in links.groupby(["node_a", "node_b"]):
    plt.plot(link["time_s"], link["sinr_db"], label=f"{a}-{b}")
plt.xlabel("time (s)"); plt.ylabel("SINR (dB)"); plt.legend(); plt.show()
```

Use `.venv/bin/python`, which already has pandas and matplotlib.

## 5\. The raw CSVs

Each CSV has a header row, then one row per saved tick (per pair or per flow).
Node ids are zero-based indices in `nodes.json` order, so `0` is `node-a` and
`1` is `node-b`.

```bash
head -n 3 scratch/mesh-sim/outputs/getting-started/01-static-los-baseline/seed-1/links.csv
```

```
time_s,node_a,node_b,dist_m,sinr_db,condition,condition_reason,capacity_mbps,delivered_mbps,hop_count
0.000000,0,1,100.000000,35.588456,LOS,probabilistic,4729.1,10.0,1
0.100000,0,1,100.000000,34.644837,LOS,probabilistic,4603.7,10.0,1
```

| Column | Meaning |
|---|---|
| `dist_m` | Distance between the two nodes (m). |
| `sinr_db` | Link SINR (dB). |
| `condition`, `condition_reason` | `LOS` or `NLOS`, and whether buildings (`building`) or the channel model's probability (`probabilistic`) decided it. |
| `capacity_mbps` | What the link can carry at that SINR (Mbps). |
| `delivered_mbps`, `hop_count` | Total traffic routed over this link, and the longest path among those flows. |

```bash
head -n 3 scratch/mesh-sim/outputs/getting-started/01-static-los-baseline/seed-1/flows.csv
```

```
time_s,src,dst,demand_mbps,delivered_mbps,latency_ms,hop_count,routable
0.000000,0,1,10.0,10.0,0.500,1,1
0.100000,0,1,10.0,10.0,0.500,1,1
```

| Column | Meaning |
|---|---|
| `src`, `dst` | The flow's source and destination nodes. |
| `demand_mbps`, `delivered_mbps` | What the traffic model asked for, and what the route could carry (Mbps). |
| `latency_ms` | Path latency (ms). |
| `hop_count`, `routable` | Hops on the path; `routable` is `0` when the flow got no route (no path, a path longer than `max_hops`, or zero demand), and then `delivered_mbps` is 0. |

Every column of these and the other CSVs: \ref files_links_csv "links.csv",
\ref files_flows_csv "flows.csv", \ref files_routes_csv "routes.csv",
\ref files_positions_csv "positions.csv", \ref files_rx_power_csv "rx-power.csv"
and \ref files_mcs_csv "mcs.csv".

## 6\. Is this run correct?

For this scenario, yes, if all of these hold:

- `run.log` shows 2 nodes, 28 GHz, 400 MHz and 10 Mbps demand.
- SINR and capacity are flat from 0.1 s on.
- `delivered_mbps` equals `demand_mbps` (10) on every row of `flows.csv`.
- `routable` is `1` and `hop_count` is `1` throughout.
- `summary.json` shows `connectivity` 1.0 and `flows_unroutable` 0.

The other numbered scenarios in \ref inputs_baselines "inputs/baselines" each
change one setting from this one and describe what their graphs should show.

## 7\. Going further

- \ref mesh_sim_change_one_setting "Change one setting": ask for more traffic
  than the link can carry, rerun and compare the two runs.
- \ref scripts_plotting "scripts/plotting": every plot and config option.
- \ref mesh_sim_files "Input and output files": every input and output file
  in depth.
- \ref mesh_sim_repo_map "Repository map": where everything lives.

Previous: \ref mesh_sim_first_run "Your first run" · Next: \ref mesh_sim_change_one_setting "Change one setting"
