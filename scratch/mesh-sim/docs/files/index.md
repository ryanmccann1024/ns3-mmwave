# Input and output files {#mesh_sim_files}

[TOC]

Every file a run reads and writes, end to end. Click any file for its full
reference: a real example, every field with its units and allowed values, what
to change, and how to read it.

## 1\. End to end

<!-- Input/output map. Styles: .ms-iomap in theme/mesh-sim.css. Each card links
     to the page with the same id; keep it in step with sections 2-4 below. -->
\htmlonly
<div class="ms-iomap">
<div class="ms-io-stage ms-io-in">
<div class="ms-io-head"><span class="ms-io-num">1</span>Scenario folder <code>inputs/&lt;name&gt;/</code><span class="ms-io-note">what you write</span></div>
<div class="ms-io-cards">
<a class="ms-io-file" href="files_run_ini.html"><span class="ms-io-name"><code>run.ini</code><span class="ms-io-badge">required</span></span><span class="ms-io-desc">Run settings: time, channel, traffic, routing, output.</span></a>
<a class="ms-io-file" href="files_channel_models.html"><span class="ms-io-name"><b>Channel models</b><span class="ms-io-badge">in run.ini</span></span><span class="ms-io-desc">3GPP and NYU: scenarios, LOS, weather, capacity.</span></a>
<a class="ms-io-file" href="files_traffic.html"><span class="ms-io-name"><b>Traffic</b><span class="ms-io-badge">in run.ini</span></span><span class="ms-io-desc">Which flows exist and how they change over time.</span></a>
<a class="ms-io-file" href="files_routing.html"><span class="ms-io-name"><b>Routing</b><span class="ms-io-badge">in run.ini</span></span><span class="ms-io-desc">How each flow gets a path, and what happens when a link overloads.</span></a>
<a class="ms-io-file" href="files_nodes_json.html"><span class="ms-io-name"><code>nodes.json</code><span class="ms-io-badge">required</span></span><span class="ms-io-desc">The mesh nodes: where they start and how they move.</span></a>
<a class="ms-io-file" href="files_buildings_json.html"><span class="ms-io-name"><code>buildings.json</code><span class="ms-io-badge">optional</span></span><span class="ms-io-desc">Buildings that block links.</span></a>
<a class="ms-io-file" href="files_jammers_json.html"><span class="ms-io-name"><code>jammers.json</code><span class="ms-io-badge">optional</span></span><span class="ms-io-desc">Jammers. Used on the sub-6 band only.</span></a>
</div>
</div>
<div class="ms-io-arrow">read once, at the start</div>
<div class="ms-io-stage ms-io-sim">
<div class="ms-io-head"><span class="ms-io-num">2</span>Simulator</div>
<div class="ms-io-cards">
<a class="ms-io-file ms-io-cat-sim" href="mesh_sim_run_flow.html"><span class="ms-io-name"><code>ns3.42-sim-debug</code></span><span class="ms-io-desc">Every tick: evaluates every link, routes the traffic and writes a row to each CSV.</span></a>
<div class="ms-io-file ms-io-plain ms-io-cat-sim"><span class="ms-io-name"><b>You choose</b></span><span class="ms-io-desc"><code>&#45;&#45;run-config</code>, <code>&#45;&#45;seeds</code>, <code>&#45;&#45;output-dir</code></span></div>
</div>
</div>
<div class="ms-io-arrow">writes</div>
<div class="ms-io-stage ms-io-out">
<div class="ms-io-head"><span class="ms-io-num">3</span>Run folder <code>&lt;output-dir&gt;/</code><span class="ms-io-note">what the run wrote</span></div>
<div class="ms-io-cards">
<a class="ms-io-file" href="files_run_log.html"><span class="ms-io-name"><code>run.log</code><span class="ms-io-badge">once</span></span><span class="ms-io-desc">The settings the run actually used.</span></a>
<div class="ms-io-file ms-io-plain"><span class="ms-io-name"><code>inputs/</code><span class="ms-io-badge">once</span></span><span class="ms-io-desc">A copy of the scenario folder from step 1.</span></div>
</div>
<div class="ms-io-folder">
<div class="ms-io-folder-head"><code>seed-N/</code>, one folder per seed</div>
<div class="ms-io-cards">
<a class="ms-io-file" href="files_summary_json.html"><span class="ms-io-name"><code>summary.json</code><span class="ms-io-badge">once</span></span><span class="ms-io-desc">Averages per node, per flow and for the network.</span></a>
<a class="ms-io-file" href="files_links_csv.html"><span class="ms-io-name"><code>links.csv</code><span class="ms-io-badge">every tick</span></span><span class="ms-io-desc">Every node pair: distance, SINR, LOS, capacity, traffic.</span></a>
<a class="ms-io-file" href="files_flows_csv.html"><span class="ms-io-name"><code>flows.csv</code><span class="ms-io-badge">every tick</span></span><span class="ms-io-desc">Every flow: demand, delivered rate, latency.</span></a>
<a class="ms-io-file" href="files_routes_csv.html"><span class="ms-io-name"><code>routes.csv</code><span class="ms-io-badge">every tick</span></span><span class="ms-io-desc">The path each flow took and its bottleneck.</span></a>
<a class="ms-io-file" href="files_positions_csv.html"><span class="ms-io-name"><code>positions.csv</code><span class="ms-io-badge">every tick</span></span><span class="ms-io-desc">Where every node is.</span></a>
<a class="ms-io-file" href="files_rx_power_csv.html"><span class="ms-io-name"><code>rx-power.csv</code><span class="ms-io-badge">every tick</span></span><span class="ms-io-desc">Received power per node pair.</span></a>
<a class="ms-io-file" href="files_mcs_csv.html"><span class="ms-io-name"><code>mcs.csv</code><span class="ms-io-badge">every tick</span></span><span class="ms-io-desc">MCS index and spectral efficiency per pair.</span></a>
</div>
</div>
</div>
<div class="ms-io-arrow">read by</div>
<div class="ms-io-stage ms-io-res">
<div class="ms-io-head"><span class="ms-io-num">4</span>Look at the results</div>
<div class="ms-io-cards">
<a class="ms-io-file ms-io-cat-tool" href="files_figures.html"><span class="ms-io-name"><code>scripts/plotting</code></span><span class="ms-io-desc">Reads <code>seed-N/</code> and writes the plots to <code>figures/</code> in the run folder.</span></a>
<a class="ms-io-file" href="files_figures.html"><span class="ms-io-name"><code>figures/</code></span><span class="ms-io-desc">SINR, capacity, MCS, throughput and latency plots.</span></a>
<a class="ms-io-file ms-io-cat-viz" href="mesh_sim_first_result.html"><span class="ms-io-name"><code>ns3-mmwave-viz</code></span><span class="ms-io-desc">Replays <code>seed-N/</code> in 3D: nodes, links and routes over time.</span></a>
</div>
</div>
</div>
<div class="ms-io-legend"><span class="ms-io-cat-file">File</span><span class="ms-io-cat-sim">Simulator</span><span class="ms-io-cat-tool">Python tool</span><span class="ms-io-cat-viz">Visualizer</span></div>
\endhtmlonly

"Every tick" means every `[output] viz_tick_ms` of simulated time. `--no-viz`
skips the six CSVs; `run.log`, `inputs/` and `summary.json` are still written.

## 2\. Inputs

| File | Required | Holds |
|---|---|---|
| \subpage files_run_ini "run.ini" | yes | Every run setting, in sections: scenario, output, channel, traffic, routing, RL. |
| \subpage files_channel_models "Channel models: 3GPP and NYU" | | The propagation settings in `run.ini`: scenarios, LOS, weather, capacity. |
| \subpage files_traffic "Traffic" | | The `[traffic]` settings in `run.ini`: which flows exist and when. |
| \subpage files_routing "Routing" | | The `[routing]` settings in `run.ini`: paths, congestion and latency. |
| \subpage files_nodes_json "nodes.json" | yes | Each node's id, start position and mobility. |
| \subpage files_buildings_json "buildings.json" | no | Box-shaped buildings that turn links NLOS. |
| \subpage files_jammers_json "jammers.json" | no | Jammer positions, power and timing (sub-6 only). |

## 3\. Outputs

| File | Written | Holds |
|---|---|---|
| \subpage files_run_log "run.log" | Once, before the first seed | The resolved settings and run details. |
| \subpage files_summary_json "summary.json" | Once per seed, at the end | Averages per node, per flow and for the network. |
| \subpage files_links_csv "links.csv" | Every saved tick | One row per node pair. |
| \subpage files_flows_csv "flows.csv" | Every saved tick | One row per flow. |
| \subpage files_routes_csv "routes.csv" | Every saved tick | One row per flow: its path. |
| \subpage files_positions_csv "positions.csv" | Every saved tick | One row per node. |
| \subpage files_rx_power_csv "rx-power.csv" | Every saved tick | One row per node pair. |
| \subpage files_mcs_csv "mcs.csv" | Every saved tick | One row per node pair. |

## 4\. Figures

| Page | Holds |
|---|---|
| \subpage files_figures "Figures" | Making the plots for any run, every `plot.ini` setting, and how to read each figure. |

## 5\. Examples on these pages

The examples on the file pages come from tracked scenarios in
\ref inputs_baselines "inputs/baselines", run into `outputs/examples/<name>/`.
To make the same folders, so every snippet on these pages runs as written, run
this from the ns3-mmwave repository root:

```bash
for s in 03-building-blockage 07-three-node-relay 09-congestion-bottleneck \
         10-on-off-traffic 12-gateway-topology 14-max-hops-limit p0-jammer-smoke; do
  ./ns3 run scratch/mesh-sim/sim -- \
    --run-config=scratch/mesh-sim/inputs/baselines/$s/run.ini \
    --seeds=1 --output-dir=scratch/mesh-sim/outputs/examples/$s
done
./ns3 run scratch/mesh-sim/sim -- \
  --run-config=scratch/mesh-sim/inputs/baselines/16-random-walk-urban/run.ini \
  --seeds=1,2,3 --output-dir=scratch/mesh-sim/outputs/examples/16-random-walk-urban
```

The pandas snippets run from `scratch/mesh-sim/` with `.venv/bin/python`.

Previous: \ref mesh_sim_change_one_setting "Change one setting" · Next: \ref files_run_ini "run.ini"
