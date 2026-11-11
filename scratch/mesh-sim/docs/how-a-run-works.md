# How a run works {#mesh_sim_run_flow}

[TOC]

What the simulator does between starting and finishing, in order, followed
on a small run whose route changes halfway through.

## 1\. The whole run

\htmlonly
<div class="ms-iomap">
<div class="ms-io-stage ms-io-in">
<div class="ms-io-head"><span class="ms-io-num">1</span>Once per run<span class="ms-io-note">section 3</span></div>
<div class="ms-io-cards">
<div class="ms-io-file ms-io-plain"><span class="ms-io-name"><b>Read</b></span><span class="ms-io-desc"><code>run.ini</code>, <code>nodes.json</code>, and the buildings and jammers files, plus command-line options.</span></div>
<div class="ms-io-file ms-io-plain"><span class="ms-io-name"><b>Check</b></span><span class="ms-io-desc">Every setting is validated; a bad one stops the run here.</span></div>
<div class="ms-io-file ms-io-plain"><span class="ms-io-name"><b>Record</b></span><span class="ms-io-desc">Copy the inputs to <code>inputs/</code> and write <code>run.log</code>.</span></div>
</div>
</div>
<div class="ms-io-arrow">then, for each seed</div>
<div class="ms-io-stage ms-io-sim">
<div class="ms-io-head"><span class="ms-io-num">2</span>Set up the seed<span class="ms-io-note">section 4</span></div>
<div class="ms-io-cards">
<div class="ms-io-file ms-io-plain ms-io-cat-sim"><span class="ms-io-name"><b>Build the scene</b></span><span class="ms-io-desc">Nodes, their motion, buildings, jammers and the channel model, with this seed's random numbers.</span></div>
<div class="ms-io-file ms-io-plain ms-io-cat-sim"><span class="ms-io-name"><b>Create the flows</b></span><span class="ms-io-desc">The traffic that exists at t = 0.</span></div>
</div>
</div>
<div class="ms-io-arrow">then, every tick from t = 0 to <code>duration_s</code></div>
<div class="ms-io-stage ms-io-sim ms-loop">
<div class="ms-io-head"><span class="ms-io-num">3</span>The tick loop<span class="ms-io-note">section 5</span></div>
<div class="ms-io-cards ms-loop-steps">
<div class="ms-io-file ms-io-plain ms-io-cat-sim"><span class="ms-io-name"><b>a. Move</b></span><span class="ms-io-desc">Advance the clock one <code>tick_s</code>; nodes move.</span><span class="ms-io-badge">positions.csv</span></div>
<div class="ms-io-file ms-io-plain ms-io-cat-sim"><span class="ms-io-name"><b>b. Evaluate links</b></span><span class="ms-io-desc">Every pair: LOS, path loss, SINR, capacity.</span><span class="ms-io-badge">links.csv</span></div>
<div class="ms-io-file ms-io-plain ms-io-cat-sim"><span class="ms-io-name"><b>c. Update traffic</b></span><span class="ms-io-desc">Flows end, switch on or off, or arrive.</span></div>
<div class="ms-io-file ms-io-plain ms-io-cat-sim"><span class="ms-io-name"><b>d. Route</b></span><span class="ms-io-desc">Each flow gets a path; overloaded links scale it.</span><span class="ms-io-badge">routes.csv</span></div>
<div class="ms-io-file ms-io-plain ms-io-cat-sim"><span class="ms-io-name"><b>e. Record</b></span><span class="ms-io-desc">Write this tick's rows; add it to the totals.</span><span class="ms-io-badge">flows.csv</span></div>
</div>
<div class="ms-loop-back">&#8635; next tick</div>
</div>
<div class="ms-io-arrow">after the last tick</div>
<div class="ms-io-stage ms-io-res">
<div class="ms-io-head"><span class="ms-io-num">4</span>Finish the seed<span class="ms-io-note">section 6</span></div>
<div class="ms-io-cards">
<div class="ms-io-file ms-io-plain ms-io-cat-viz"><span class="ms-io-name"><code>summary.json</code></span><span class="ms-io-desc">Averages over every tick after <code>warmup_s</code>.</span></div>
</div>
</div>
</div>
\endhtmlonly

Every value in the outputs comes from the tick loop. Links and routes are
worked out fresh each tick from where the nodes are at that moment; nothing
carries over except node motion, flow state and the channel's random draws.

## 2\. The example

`mover` drives east at 20 m/s and sends 500 Mbps to `gw`. At first it can
reach `gw` directly. Halfway through, a building comes between them, and the
traffic has to go through `relay`.

\htmlonly
<div class="ms-flow-split ms-routes">
<div class="ms-flow-art ms-panel ms-c-blue"><svg viewBox="0 0 440 320" aria-hidden="true"><rect class="ms-bldg" x="280" y="60" width="80" height="80" rx="2"/><line class="ms-faint" x1="10" y1="160" x2="436" y2="160"/><line class="ms-ink ms-thick" x1="40" y1="40" x2="320" y2="160"/><circle class="ms-dot" cx="40" cy="40" r="7"/><text x="40" y="26" text-anchor="middle" class="ms-strong">gw</text><circle class="ms-dot" cx="340" cy="280" r="7"/><text x="340" y="308" text-anchor="middle" class="ms-strong">relay</text><circle class="ms-dot" cx="320" cy="160" r="7"/><text x="320" y="186" text-anchor="middle" class="ms-strong">mover</text></svg><div class="ms-panel-cap"><strong>Up to t = 2.0 s: direct</strong>The line from <code>mover</code> to <code>gw</code> passes the building.</div></div>
<div class="ms-flow-art ms-panel ms-c-purple"><svg viewBox="0 0 440 320" aria-hidden="true"><rect class="ms-bldg" x="280" y="60" width="80" height="80" rx="2"/><line class="ms-faint" x1="10" y1="160" x2="436" y2="160"/><line class="ms-bad" x1="40" y1="40" x2="400" y2="160"/><line class="ms-ink ms-thick" x1="400" y1="160" x2="340" y2="280"/><line class="ms-ink ms-thick" x1="340" y1="280" x2="40" y2="40"/><circle class="ms-dot" cx="40" cy="40" r="7"/><text x="40" y="26" text-anchor="middle" class="ms-strong">gw</text><circle class="ms-dot" cx="340" cy="280" r="7"/><text x="340" y="308" text-anchor="middle" class="ms-strong">relay</text><circle class="ms-dot" cx="400" cy="160" r="7"/><text x="400" y="186" text-anchor="middle" class="ms-strong">mover</text></svg><div class="ms-panel-cap"><strong>From t = 2.5 s: through relay</strong>The line to <code>gw</code> runs through the building (drawn at t = 4 s).</div></div>
</div>
\endhtmlonly

```ini
[scenario]
duration_s     = 4.0
tick_s         = 0.5
buildings_file = buildings.json   ; the block, 20 m tall
[channel]
scenario       = UMi
channel_model  = nyu
[nyu_channel]
shadowing_enabled = false          ; so every number repeats exactly
[traffic]
flow_topology  = explicit_pairs
pairs          = [{"src":"mover","dst":"gw","demand_mbps":500}]
[output]
viz_tick_ms    = 500               ; a CSV row every tick
```

## 3\. Once per run: read, check, record

- **Read:** `run.ini` and the files it names, then the command-line options
  on top (`--seeds`, `--band`, `--output-dir` and others).
- **Check:** every setting is validated before anything runs. A bad value
  stops the run with a message and no output.
- **Record:** the inputs are copied to `<output>/inputs/` and
  \ref files_run_log "run.log" is written. Its *Resolved config* block is the
  final word on what the run used:

```text
Resolved config:
  duration_s          = 4
  tick_s              = 0.5
  nodes               = 3
  buildings           = 1
  channel_model       = nyu
  scenario            = UMi
  traffic.pair = mover,gw,500
  routing.algorithm   = shortest_path
```

## 4\. Once per seed: set up

Each seed is a full, independent repeat of the run with different random
numbers: shadowing, LOS coin flips, random walks and traffic draws. It writes
to its own `seed-<N>/` folder. `--seeds=1,2,3` runs three.

For each seed the simulator builds the scene (nodes, their motion, buildings,
jammers, the channel model) and creates the flows that exist at t = 0. Here
that is one flow, `mover` → `gw`.

## 5\. Every tick

The loop starts at t = 0 and includes t = `duration_s`, so there are
`duration_s / tick_s + 1` ticks: here \f$ 4.0 / 0.5 + 1 = 9 \f$. One row per tick, for the link that matters:

| t | `mover` x | Direct link `mover`–`gw` | Route | Delivered | Latency |
|---|---|---|---|---|---|
| 0.0 s | 100 m | LOS, 34.3 dB, 4,552 Mbps | mover → gw | 500 Mbps | 0.500 ms |
| 0.5 s | 110 m | LOS, 33.6 dB, 4,469 Mbps | mover → gw | 500 Mbps | 0.500 ms |
| 1.0 s | 120 m | LOS, 33.0 dB, 4,390 Mbps | mover → gw | 500 Mbps | 0.500 ms |
| 1.5 s | 130 m | LOS, 32.5 dB, 4,315 Mbps | mover → gw | 500 Mbps | 0.500 ms |
| 2.0 s | 140 m | LOS, 31.9 dB, 4,244 Mbps | mover → gw | 500 Mbps | 0.501 ms |
| 2.5 s | 150 m | NLOS, 4.9 dB, 816 Mbps | mover → relay → gw | 500 Mbps | 1.001 ms |
| 3.0 s | 160 m | NLOS, 4.1 dB, 739 Mbps | mover → relay → gw | 500 Mbps | 1.001 ms |
| 3.5 s | 170 m | NLOS, 3.4 dB, 669 Mbps | mover → relay → gw | 500 Mbps | 1.001 ms |
| 4.0 s | 180 m | NLOS, 2.7 dB, 606 Mbps | mover → relay → gw | 500 Mbps | 1.001 ms |

The five steps, at t = 2.5 s, the tick where the route changes:

**a. Move.** The clock moves on 0.5 s and every node moves with it. `mover` is
now at x = 150 m. \ref files_positions_csv "positions.csv" gets one row per
node.

**b. Evaluate links.** Each of the 3 node pairs is worked out from scratch:
LOS or NLOS, path loss, SINR, capacity
(\ref files_channel_models "Channel models"). At x = 150 m the line from
`mover` to `gw` passes through the building, so that link is now NLOS. Its
capacity falls from 4,244 to 816 Mbps. These are the three rows
\ref files_links_csv "links.csv" gets:

```text
time_s,node_a,node_b,dist_m,sinr_db,condition,condition_reason,capacity_mbps,delivered_mbps,hop_count
2.500000,0,1,192.093727,29.918193,LOS,building,3976.0,500.0,2
2.500000,0,2,161.554944,4.928219,NLOS,building,815.7,0.0,0
2.500000,1,2,60.000000,40.025431,LOS,building,5318.5,500.0,2
```

**c. Update traffic.** Flows that have ended are removed, `on_off` flows
switch, `poisson` flows arrive (\ref files_traffic "Traffic"). Here the one
`constant` flow just carries on at 500 Mbps.

**d. Route.** Each flow gets the path with the lowest total
\f$ 1/C \f$ (\ref files_routing "Routing"). In \f$ 1/\text{Gbps} \f$:

| Path | t = 2.0 s | t = 2.5 s |
|---|---|---|
| mover → gw | **0.236** | 1.226 |
| mover → relay → gw | 0.440 | **0.440** |

One tick earlier the direct link was cheapest; now the relay is. Nothing
remembers the old route: each tick chooses again.

**e. Record.** \ref files_routes_csv "routes.csv" and
\ref files_flows_csv "flows.csv" get this tick's rows: 2 hops, 500 Mbps
delivered, 1.001 ms latency (0.5 ms per hop plus travel time). The tick is
also added to the running totals for `summary.json`, unless it falls before
`warmup_s`. CSV rows are written every `viz_tick_ms`; `--no-viz` skips them.

## 6\. Finish: summary.json

After the last tick each seed writes \ref files_summary_json "summary.json",
averaged over the ticks after `warmup_s`. From this run:

```text
per_flow.mover->gw.delivered_mbps = 500.0
per_flow.mover->gw.hop_count      = 1.444   (5 ticks at 1 hop, 4 at 2: 13 / 9)
per_flow.mover->gw.latency_ms     = 0.723
per_node.gw.min_sinr_db           = 2.69    (the blocked link at t = 4 s)
network.mean_hop_count            = 1.444
```

## 7\. In the code

For changing the simulator. `sim.cc` runs every step in this order; each
module page holds the details.

| Step | Code | Module |
|---|---|---|
| Read, check | `ParseCommandLine`, the config loader, `ValidateConfig` | \ref src_cli "cli", \ref src_config "config" |
| Record | `ArchiveScenarioInputs`, `WriteRunLog` | \ref src_io "io" |
| Build the scene | `TopologyBuilder` | \ref src_setup "setup" |
| a. Move | `Simulator::Stop` + `Run`: the ns-3 clock only, no events | ns-3 |
| b. Evaluate links | `LinkEvaluator::EvaluateAll` → `LinkTable` | \ref src_eval "eval", \ref src_jammer "jammer" |
| c. Update traffic | `TrafficMatrix::Tick` | \ref src_traffic "traffic" |
| d. Route | `MeshRouter::Route` | \ref src_routing "routing" |
| e. Record | `VizWriter`, `MetricsWriter` | \ref src_io "io" |

- **RL runs** (`--rl-mode`) add a step after e: the simulator sends an
  observation and reads an action, which moves the controlled nodes before
  the next tick (\ref src_rl "rl").
- **Channel-query mode** (`--channel-query`) stops after *check* and answers
  link queries instead of running ticks (\ref src_query "query").
- A node past its `failure_at_s` drops out at the start of step b.

## 8\. Related

- \ref system_overview "System overview": what the simulator models and leaves out
- \ref mesh_sim_setting_trace "Follow a setting": one `run.ini` value through these steps
- \ref mesh_sim_files "Input and output files": every file named on this page
