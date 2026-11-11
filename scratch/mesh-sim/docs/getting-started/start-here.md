# Start here {#mesh_sim_start_here}

[TOC]

What Mesh-Sim is, the terms this sequence uses, and the four pages that take
you from a fresh checkout to a first result.

## 1\. What Mesh-Sim does

Mesh-Sim is a lightweight time-stepped mmWave / sub-6 mesh simulator built on
ns3-mmwave. It loads a scenario, steps through time evaluating every link's
SINR, capacity and MCS against an ns-3 propagation model, routes traffic over
the mesh and writes metrics.

## 2\. How Mesh-Sim differs from ns-3

A full ns3-mmWave simulation sends every packet through the whole protocol
stack. Mesh-Sim keeps ns-3's channel and mobility models, drops the protocol
stack and replaces the rest with simpler models that it evaluates once per
tick.

<!-- Layer comparison. Each row is one layer, top of the stack first. Sources:
     CLAUDE.md "Key differences from mmwave-sim", src/eval/link-evaluator.h
     (Evaluate steps), src/routing/mesh-router.h, src/traffic/, sim.cc tick loop,
     and research/flow-abstraction.md. Styles: .ms-stack in theme/mesh-sim.css. -->
<div class="ms-stack">
<div class="ms-stack-row ms-stack-head"><div>Layer</div><div>Full ns3-mmWave</div><div>Mesh-Sim</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer">Traffic</div><div>Applications send individual packets.</div><div class="ms-stack-replaced"><span class="ms-stack-tag">Replaced</span>A demand in Mbit/s for each flow. No packets.</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer">Transport and IP</div><div>TCP, UDP and IP.</div><div class="ms-stack-none"><span class="ms-stack-tag">Not modeled</span></div></div>
<div class="ms-stack-row"><div class="ms-stack-layer">Roles and routing</div><div>Base stations and UEs. UE traffic goes through a base station and the core network.</div><div class="ms-stack-replaced"><span class="ms-stack-tag">Replaced</span>Every node is a peer. Each flow takes a multi-hop path over the current links.</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer">Radio protocols</div><div>RRC, PDCP, RLC, MAC scheduling and HARQ retransmission.</div><div class="ms-stack-none"><span class="ms-stack-tag">Not modeled</span></div></div>
<div class="ms-stack-row"><div class="ms-stack-layer">Link quality</div><div>SINR for each transmission, including interference from other transmitters. Error models decide which packets are lost.</div><div class="ms-stack-replaced"><span class="ms-stack-tag">Replaced</span>One SINR per link per tick, from received power and noise. Capacity and MCS come from a formula or table. Fixed antenna gains stand in for ideal beamforming. Nodes do not interfere with each other; only jammers add interference.</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer">Channel</div><div>3GPP and NYU path-loss models, with line of sight decided by buildings.</div><div class="ms-stack-same"><span class="ms-stack-tag">Same ns-3 code</span>Mesh-Sim calls these models directly.</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer">Mobility and time</div><div>Mobility models. The event scheduler drives everything.</div><div class="ms-stack-same"><span class="ms-stack-tag">Same ns-3 code</span>The same mobility models. A fixed tick advances the ns-3 clock.</div></div>
</div>

**Why.** ns3-mmWave's cellular setup is not peer-to-peer and is too slow for
node-placement studies. Without the protocol stack, a tick costs one
propagation-model call per pair of nodes plus routing, however much traffic is
offered.

**What it cannot show.** Packet loss, queueing, retransmissions, MAC contention
and interference between nodes.

**Accuracy.** Link quality comes from ns-3's own propagation models, so it is as
accurate as those models and the scenario's radio settings.

Background:

- \ref research_flow_abstraction "Flow abstraction" and
  \ref research_link_model "Link model assumptions": why the stack was dropped
  and what the link model assumes.
- \ref research_field_calibration "Field calibration limits": how simulator
  output compares with field data.

## 3\. Terms used in this sequence

| Term | Meaning |
|---|---|
| **Node** | One radio in the mesh. Every node uses the same radio model. A scenario can name one node as the gateway that every other node sends to, which plays the part of a base station. |
| **Scenario** | A directory of input files that describes one simulation. The one you will run is `scratch/mesh-sim/inputs/baselines/01-static-los-baseline/`. |
| **`run.ini`** | The scenario's settings file: duration, tick length, channel, traffic and routing. You pass its path to the simulator with `--run-config`. |
| **`nodes.json`** | The scenario's node list: id, position and mobility for each node. `run.ini` names it; paths inside `run.ini` are relative to `run.ini` itself. |
| **Seed** | The random-number seed for one simulation. Each seed writes into its own `seed-<N>/` folder under the output directory. |
| **Tick** | One simulated time step (`tick_s` in `run.ini`). Every tick the simulator re-evaluates all links, generates demand and routes it. CSVs are saved at the `[output] viz_tick_ms` cadence (every tick in this scenario). |
| **Output directory** | Where a run writes `run.log`, an archived copy of its inputs and the per-seed result files. You choose it with `--output-dir`. |
| **Simulator binary** | The executable that `./ns3 build` produces under `build/scratch/mesh-sim/`. Python tools that launch it take `--sim-binary <BIN>`; none of them build it. |

## 4\. What you will do

1. \ref mesh_sim_install_build "Install and build": check prerequisites,
   configure, build, and confirm the binary exists.
2. \ref mesh_sim_first_run "Your first run": run the two-node baseline scenario
   with one seed and confirm the output files appear.
3. \ref mesh_sim_first_result "Understand the result": find the output, learn
   the key files and read one flow-level throughput metric.
4. \ref mesh_sim_change_one_setting "Change one setting" (optional): ask for
   more traffic than the link can carry in a copy of the scenario, then add a
   building between the nodes, and compare the runs.

## 5\. Going further

- \ref mesh_sim_files "Input and output files": every file a run reads and
  writes, each on its own page.
- \ref system_overview "System overview": how the simulator, its output files
  and the visualizer fit together, with the system diagram.
- \ref mesh_sim_overview "User guide": module layout, setup, every run mode and
  the output contracts.
- \ref readme_conventions "Conventions": working directories and the
  `--sim-binary <BIN>` rule for Python tools.

Next: \ref mesh_sim_install_build "Install and build"
