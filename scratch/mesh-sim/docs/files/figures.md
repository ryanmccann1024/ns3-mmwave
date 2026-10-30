# Figures {#files_figures}

[TOC]

`scripts/plotting` turns a finished run into figures: links and traffic over
time, per-node and per-flow bar charts, node geometry and a summary table.
They go into the run's `figures/` folder. With several seeds each figure shows
the mean and a 95% confidence interval.

## 1\. Make the figures

From `scratch/mesh-sim/`, with the Python environment set up once
(`python3 scripts/rl/bootstrap_venv.py`):

1. Copy the example settings and point them at your run:

   ```bash
   sed 's|^data_dir.*|data_dir = outputs/examples/16-random-walk-urban|' \
       scripts/plotting/plot.example.ini > outputs/plot.ini
   ```

2. Run the tool as a module:

   ```bash
   .venv/bin/python -m scripts.plotting.cli --config outputs/plot.ini
   ```

   ```text
   Found 3 seed(s) in outputs/examples/16-random-walk-urban
   Generating plots...
     saved outputs/examples/16-random-walk-urban/figures/sinr_timeseries.png
     ...
   Done. Figures written to outputs/examples/16-random-walk-urban/figures/
   ```

3. Open the `figures/` folder. A rerun overwrites files of the same name.

Each call plots one run. For a sweep, set `auto_plot = each` (or `all`) and
`plot_config` under `[sweep.meta]` and it plots every point itself
(\ref scripts_sweep "scripts/sweep").

## 2\. plot.ini

`scripts/plotting/plot.example.ini`, without its comments:

\htmlonly
<div class="ms-ini">
<div class="ms-ini-row ms-c-blue">
<pre class="ms-ini-code"><b>[output]</b>
data_dir = outputs/2026-04/02/09-28-34
format = png
dpi = 300</pre>
<div class="ms-ini-note"><strong>Which run, and what kind of image</strong>Plot the run in that folder as PNG at 300 dpi, into its <code>figures/</code> folder. Step 1 below swaps <code>data_dir</code> for your run.</div>
</div>
<div class="ms-ini-row ms-c-green">
<pre class="ms-ini-code"><b>[plots]</b>
sinr_timeseries = true
rx_power_timeseries = true
capacity_timeseries = true
mcs_timeseries = true
throughput_timeseries = true
latency_timeseries = true
geometry = true</pre>
<div class="ms-ini-note"><strong>Figures over time, from the CSVs</strong>Seven toggles, eight files: <code>throughput_timeseries</code> makes one figure for flows and one for links.</div>
</div>
<div class="ms-ini-row ms-c-amber">
<pre class="ms-ini-code">per_node_sinr = true
per_node_throughput = true
per_flow_throughput = true
per_flow_latency = true
network_summary = true
sim_runtime = true</pre>
<div class="ms-ini-note"><strong>Bar charts and a table, from <code>summary.json</code></strong>Six toggles, seven files: <code>per_node_throughput</code> makes a TX chart and an RX chart. All 13 toggles on gives 15 files.</div>
</div>
</div>
\endhtmlonly

<div class="ms-keys ms-c-blue">
<div class="ms-key ms-key-head"><div>Key</div><div>What it does</div><div>Allowed values</div></div>
<div class="ms-key">
<div class="ms-key-name">`data_dir`<span class="ms-key-def">required</span></div>
<div class="ms-key-what">The run to plot: the folder holding its `seed-N/` folders. Every seed in it is pooled.<div class="ms-key-note">Relative to where you run the command. Not a `seed-N/` folder itself, and for a sweep one `point-NNN/`.</div></div>
<div class="ms-key-vals">a folder with `seed-N/` folders</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`format`<span class="ms-key-def">default `png`</span></div>
<div class="ms-key-what">Image type. `svg` and `pdf` stay sharp at any size, for papers and slides.</div>
<div class="ms-key-vals">`png`, `svg`, `pdf`, `jpg`, …</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`dpi`<span class="ms-key-def">default `150`</span></div>
<div class="ms-key-what">Resolution. A time series is 10 &times; 5 in, so `150` gives about 1,500 &times; 750 px.</div>
<div class="ms-key-vals">an integer</div>
</div>
</div>

**`[plots]`** has one `true`/`false` per figure (section 3 lists them). A
toggle left out counts as `true`, so to make only a few figures, list all 13
and set the rest to `false`. A misspelled toggle is ignored. Comments go on
their own line: `true  # on` is not a valid value.

## 3\. The figures

| Figure | Reads | Toggle |
|---|---|---|
| `sinr_timeseries`, `rx_power_timeseries`, `capacity_timeseries` | `links.csv`, `rx-power.csv` | its own name |
| `mcs_timeseries` | `mcs.csv` | `mcs_timeseries` |
| `flow_throughput_timeseries`, `link_throughput_timeseries` | `flows.csv`, `links.csv` | `throughput_timeseries` |
| `latency_timeseries` | `flows.csv` | `latency_timeseries` |
| `geometry` | `positions.csv` | `geometry` |
| `per_node_sinr`, `per_node_tx_throughput`, `per_node_rx_throughput`, `per_flow_throughput`, `per_flow_latency`, `network_summary`, `sim_runtime` | `summary.json` | its own name; both per-node throughputs use `per_node_throughput` |

- The time series use every saved tick, warmup included, and label links
  `a-b` and flows `a→b` by node number. A `--no-viz` run has no CSVs, so they
  are skipped.
- The bar charts and table use `summary.json`: averages after `warmup_s`,
  labelled by node id.
- The examples are the baseline scenarios run into
  `outputs/examples/<name>`: `03-building-blockage` (one link that leaves a
  building's shadow at 22.3 s), `16-random-walk-urban` (three walkers, three
  seeds), `09-congestion-bottleneck` (three flows through one full link),
  `10-on-off-traffic` and `07-three-node-relay` (a relay hop that fails).

### sinr_timeseries

\image html figures-sinr-timeseries.png "sinr_timeseries, 03-building-blockage, seed 1. SINR sits at 10 to 16 dB while the building blocks the link, then jumps to 29 dB at 22.3 s when node-b clears it."
\image html figures-sinr-timeseries-3-seeds.png "sinr_timeseries, 16-random-walk-urban, seeds 1, 2 and 3. Lines are the mean over the seeds; bands are the 95% CI."

- **Shows:** each link's `sinr_db` over time. Above −6.7 dB a link can carry traffic.
- **Normal:** flat lines for fixed nodes; moving nodes drift with shadowing and step at LOS/NLOS changes. The t = 0 point can sit apart; read from 0.1 s on.
- **A problem:** a link that stays below −6.7 dB is out of the mesh. Very weak pairs stretch the axis; plot a subset from Python (section 5).
- **From** `links.csv`; toggle `sinr_timeseries`.

### rx_power_timeseries

\image html figures-rx-power-timeseries.png "rx_power_timeseries, 03-building-blockage, seed 1. Received power is −73 to −66 dBm behind the building and −58 to −54 dBm in the clear."

- **Shows:** each link's received power, without noise or jammers: the channel alone.
- **Normal:** the same shape as `sinr_timeseries`, shifted by the noise floor. The 15 dB step at 22.3 s is the link turning LOS.
- **A problem:** SINR falls while received power holds: interference, on `sub-6` a jammer (\ref files_jammers_json "jammers.json").
- **From** `rx-power.csv`; toggle `rx_power_timeseries`.

### capacity_timeseries

\image html figures-capacity-timeseries.png "capacity_timeseries, 03-building-blockage, seed 1. Capacity is 1,350 to 2,200 Mbps behind the building and 3,400 to 3,900 Mbps in the clear."

- **Shows:** what each link could carry at its SINR.
- **Normal:** it follows SINR; `shannon` at 400 MHz gives about 4,700 Mbps at 35 dB. The axis autoscales, so read the values before calling a step large.
- **A problem:** a line at 0: routing cannot use that link.
- **From** `links.csv`; toggle `capacity_timeseries`.

### mcs_timeseries

\image html figures-mcs-timeseries.png "mcs_timeseries, 03-building-blockage, seed 1. MCS 7 to 11 behind the building, 15 in the clear."
\image html figures-mcs-timeseries-3-seeds.png "mcs_timeseries, 16-random-walk-urban, seeds 1, 2 and 3. The mean index takes fractional values and the CI band reaches 19, above the top of the 0 to 15 table."

- **Shows:** each link's MCS index, as steps: 0–15, or 0–6 with `silvus` (\ref files_mcs_csv "mcs.csv").
- **Normal:** steps that follow SINR; a link pinned at the top has SINR to spare.
- **A problem:** with several seeds the line is a mean and the band is not clipped, so it can pass 15 (19 below). Read the mean line.
- **From** `mcs.csv`; toggle `mcs_timeseries`.

### flow_throughput_timeseries

\image html figures-flow-throughput-timeseries.png "flow_throughput_timeseries, 10-on-off-traffic, seed 1. One 100 Mbps flow; ON and OFF periods have random lengths around a 2 s mean."

- **Shows:** the rate each flow actually got. Demand is not drawn.
- **Normal:** `constant` traffic sits flat at its demand; `on_off` is a square wave.
- **A problem:** flat below demand: an overloaded link on the path. A drop to 0 while ON: no route. Identical lines overlap and only the last color shows.
- **From** `flows.csv`; toggle `throughput_timeseries`.

### link_throughput_timeseries

\image html figures-link-throughput-timeseries.png "link_throughput_timeseries, 09-congestion-bottleneck, seed 1. Link 2-3 (relay to dst) carries all three flows at its 1,796 Mbps capacity."

- **Shows:** the traffic on each link, all flows through it added up.
- **Normal:** lines well below each link's capacity.
- **A problem:** a line at the link's capacity is the bottleneck: here link `2-3` carries 1,796 Mbps, all it can, and the three flows share it.
- **From** `links.csv`; toggle `throughput_timeseries`.

### latency_timeseries

\image html figures-latency-timeseries.png "latency_timeseries, 09-congestion-bottleneck, seed 1. One-hop flow 2→3 at 0.50 ms; two-hop flows 0→3 and 1→3 at 1.00 ms."
\image html figures-latency-timeseries-broken-relay.png "latency_timeseries, 07-three-node-relay, seed 1. Flows 0→2 and 1→2 lose their route at 0.1 s; latency 0 means no route."

- **Shows:** each flow's latency: 0.5 ms per hop plus travel time. Load does not change it.
- **Normal:** steps of 0.5 ms per hop; a route change changes the level.
- **A problem:** a drop to 0: no route at that tick, or an OFF period. Below, two flows lose their relay after the first tick.
- **From** `flows.csv`; toggle `latency_timeseries`.

### geometry

\image html figures-geometry.png "geometry, 16-random-walk-urban, seed 1. The gateway (0) at 30 m looks down at the walkers (1, 2) at −12 to −16 degrees; the walkers are level with each other."

- **Shows:** for every pair, the direction from one node to the other: elevation on top, compass bearing below.
- **Normal:** flat lines for fixed nodes. Here the 30 m gateway looks down at the walkers at about −14°.
- **A problem:** 0° elevation between nodes that should differ in height: a wrong `z` in `nodes.json`. With several seeds positions are averaged first, a path no seed took; use one seed.
- **From** `positions.csv`; toggle `geometry`.

### per_node_sinr

\image html figures-per-node-sinr.png "per_node_sinr, 16-random-walk-urban, seeds 1, 2 and 3. Bars are the mean over the seeds; error bars are the 95% CI."

- **Shows:** each node's SINR averaged over all its links and ticks, unusable links included.
- **Normal:** nodes with short, clear links score highest.
- **A problem:** one node far below the rest is badly placed or blocked. A low mean can hide one good link; check `links.csv`.
- **From** `summary.json`; toggle `per_node_sinr`.

### per_node_tx_throughput, per_node_rx_throughput

\image html figures-per-node-tx-throughput.png "per_node_tx_throughput, 09-congestion-bottleneck, seed 1. Each source sends 596 Mbps."
\image html figures-per-node-rx-throughput.png "per_node_rx_throughput, 09-congestion-bottleneck, seed 1. dst receives all three flows, 1,788 Mbps."

- **Shows:** traffic each node sends as a source and receives as a destination. Relayed traffic is not counted.
- **Normal:** with `flow_topology = gateway`, the gateway has all the RX and no TX.
- **A problem:** a source sending less than its flows ask for: congestion or missing routes. The per-flow charts show which flow.
- **From** `summary.json`; toggle `per_node_throughput`.

### per_flow_throughput

\image html figures-per-flow-throughput.png "per_flow_throughput, 09-congestion-bottleneck, seed 1. Three flows that each ask for 2,000 Mbps get 596 Mbps."

- **Shows:** each flow's average delivered rate after warmup. No-route and OFF ticks count as 0.
- **Normal:** every bar at its demand under `constant` traffic; below it for `on_off` and `poisson`.
- **A problem:** bars below demand under `constant` traffic. Here three flows ask for 2,000 Mbps and get 596.
- **From** `summary.json`; toggle `per_flow_throughput`.

### per_flow_latency

\image html figures-per-flow-latency.png "per_flow_latency, 07-three-node-relay, seed 1. The two failed flows show near-zero latency because ticks with no route count as 0 ms."

- **Shows:** each flow's average latency. No-route and OFF ticks add 0 ms.
- **Normal:** 0.5 ms per hop.
- **A problem:** a bar well below 0.5 ms: the flow had no route most of the time, not a fast one.
- **From** `summary.json`; toggle `per_flow_latency`.

### network_summary

\image html figures-network-summary.png "network_summary, 16-random-walk-urban, seeds 1, 2 and 3."

- **Shows:** a table of the network averages: SINR, total throughput, connectivity, hops, routed and unroutable flows, runtime.
- **Normal:** connectivity 1.0, `Flows Unroutable` 0, total throughput equal to total demand.
- **A problem:** unroutable flows above 0 or connectivity well below 1: part of the mesh is cut off. `N/A` everywhere: the run stopped before writing `summary.json`.
- **From** `summary.json`; toggle `network_summary`.

### sim_runtime

\image html figures-sim-runtime.png "sim_runtime, 16-random-walk-urban, seeds 1, 2 and 3. Wall-clock time per seed; the dashed line is the mean."

- **Shows:** how long each seed took on your machine.
- **Normal:** seeds of one scenario take about the same time; time grows with node count and tick count.
- **A problem:** none really: wall-clock time depends on the machine, so compare only runs made together.
- **From** `summary.json`; toggle `sim_runtime`.

## 4\. Several seeds and the 95% CI

| Figure type | One seed | Several seeds |
|---|---|---|
| Time series (`*_timeseries`) | One line per link or flow | Mean line per link or flow, with a band of mean ± CI at each saved tick |
| `geometry` | Angles from that seed's positions | Angles from positions averaged over the seeds; no band |
| Per-node and per-flow bars | Bars, no error bars | Mean bars with ± CI error bars |
| `network_summary` | `value  [n=1]` | `mean +/- CI (CI95)` for mean SINR, total throughput and connectivity; `mean +/- std (std)` for mean hop count, flows routed and flows unroutable |
| `sim_runtime` | One bar | One bar per seed and a dashed mean line |

The band or error bar is the mean ± the CI half-width:

\f[ \text{CI} = t_{n-1} \cdot \frac{s}{\sqrt{n}} \f]

where \f$ n \f$ is the number of seeds, \f$ s \f$ their sample standard
deviation and \f$ t_{n-1} \f$ the two-tailed 95% Student t value. When every
seed gives the same value, \f$ s = 0 \f$ and nothing is drawn.

| Seeds | `t` | Half-width |
|---|---|---|
| 2 | 12.706 | 8.98 × std |
| 3 | 4.303 | 2.48 × std |
| 5 | 2.776 | 1.24 × std |
| 10 | 2.262 | 0.72 × std |
| 30 | 2.045 | 0.37 × std |

Two or three seeds give a wide band even when they agree closely; use five or
more when the band matters. Example, `network_summary` for three seeds of
`16-random-walk-urban`, whose mean SINRs are 29.44, 31.92 and 29.83 dB:

\f[ \bar{x} = 30.40, \quad s = 1.34, \quad \text{CI} = 4.303 \cdot \frac{1.34}{\sqrt{3}} = 3.32 \text{ dB} \f]

The table shows `30.397 +/- 3.320 (CI95)  [n=3]`.

## 5\. Custom plots from Python

`plot.ini` has no time window, link subset, titles or axis limits. For those,
call the plot functions directly; each returns a matplotlib figure:

```python
from scripts.plotting import (aggregate_timeseries, discover_seed_dirs,
                              load_links_csv, plot_sinr_timeseries)

run = "outputs/examples/16-random-walk-urban"
agg = aggregate_timeseries(discover_seed_dirs(run), load_links_csv, "links.csv",
                           "time_s", ["node_a", "node_b"], ["sinr_db"])
one = agg[(agg.node_a == 1) & (agg.node_b == 2)]      # walker-a <-> walker-b only
fig = plot_sinr_timeseries(one, title="walker-a to walker-b, 3 seeds")
fig.axes[0].set_ylim(0, 50)                          # fixed axis for side-by-side runs
fig.savefig(f"{run}/figures/sinr_1-2.png", dpi=150, bbox_inches="tight")
```

## 6\. Related

- \ref mesh_sim_first_result "Understand the result": the first run's figures
- \ref files_summary_json "summary.json" and the CSV pages: what each figure reads
- \ref scripts_plotting "scripts/plotting": the plotting code

Previous: \ref files_mcs_csv "mcs.csv" · Up: \ref mesh_sim_files "Input and output files" · Next: \ref mesh_sim_files "Input and output files"
