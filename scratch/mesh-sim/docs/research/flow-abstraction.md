# Research record: flow abstraction {#research_flow_abstraction}

[TOC]

Why Mesh-Sim models the mesh as identical peers exchanging flow-level traffic
instead of running the full ns3-mmWave protocol stack.

Back to \ref mesh_sim_research "Research records" · all decks:
\ref mesh_sim_research_sources "Research sources".

## 1\. Background

In March we were working with ns3-mmWave's cellular setup. That setup models a
cellular path: every UE attaches to the closest base station at the start of
the simulation and stays there. Base stations can be moved, but how that plays
out end to end was unclear (R02 slide 54).

We looked for sidelink or mesh modules that might fit better: Millicar (models
only vehicles), WiGig, Sionna and mmMesh (R02 slide 55). We also listed what
dropping ns-3 or ns3-mmWave would cost, layer by layer (R02 slide 56):

- **ns-3:** IP networking stack, mobility framework, buildings/obstacle
  modeling, packet-level simulation.
- **ns3-mmWave:** PHY and MAC layers, beam management, adaptive MCS/HARQ, RLC,
  multi-cell mmWave interference, 3GPP.

The question that came out of this was how much each layer affects a
positioning algorithm (R02 slide 56).

## 2\. Why we built Mesh-Sim

Two problems with ns3-mmWave for this work (R03 slide 5):

- **It is not a mesh.** There are no relays, sidelinks or device-to-device
  (UE-to-UE) links, and every node must attach to a base station at the start
  of the simulation.
- **It is extremely slow.**

So in April we bootstrapped Mesh-Sim around one question: for a positioning
algorithm, what can be abstracted? (R03 slide 9)

## 3\. What Mesh-Sim abstracts

Mesh-Sim drops the following (R03 slide 10):

- EPC, RRC, MAC, HARQ, RLC, PDCP, TCP, UDP and IP.
- Packets. Traffic is flow-level demand.
- Base station and UE roles. All nodes are identical peers.
- Inter-node interference. SINR is signal over the noise floor.

It still uses ns-3 for mobility, buildings and the propagation/channel models.

## 4\. The simulation loop

Each tick (R03 slides 11–12):

1. Advance the ns-3 clock. The mobility and channel-condition models read
   simulation time, so the clock has to move even though the ns-3 event loop
   does not drive control flow.
2. Evaluate every link.
3. Update traffic.
4. Route flows over the evaluated links.
5. Write output.

The current loop in `sim.cc` runs the same steps in the same order, with an RL
step added after the write when RL mode is on. See \ref mesh_sim_run_flow.

## 5\. What is and isn't modeled

As of April (R03 slide 25):

| Modeled | Not modeled |
|---|---|
| Position (x, y, z) | Beam index and beam-switch events |
| RSSI/RSRP | Packet loss |
| SNR | UAV heading |
| MCS index and effective rate | IMU data |
| Approximate throughput | Route convergence time |
| Approximate latency | Reconnection time |
| Distance | Session-state preservation |
| Route table | QoS |
| | Queue depth and drops |
| | Neighbor-discovery timing |

## 6\. Where this lives now

- \ref system_overview "System overview": where the simulator sits and what it
  writes.
- \ref mesh_sim_run_flow "How a run works": the per-tick stages and their owners.
- `src/traffic/README.md`: flow-level traffic (no packets).
- `src/eval/README.md`: link evaluation (no inter-node interference; jammer
  power is the only added interference, sub-6 only).

## 7\. Sources

The original decks are on OneDrive. If you have a question about a specific
assumption, open the presentation and slide listed here. The slide text and
speaker notes are also in
<a href="research-slide-text.txt">research-slide-text.txt</a>.

| ID | Presentation | What it covers | Slides used here |
|---|---|---|---|
| R02 | 03-26 ns3 Continued.pptx | Working with ns3-mmWave's cellular setup, its limits for a mesh, alternative modules, and what each ns-3 / ns3-mmWave layer provides | 54–56 |
| R03 | 04-02 mmWave Mesh.pptx | Why we moved off ns3-mmWave, the Mesh-Sim bootstrap, the tick loop, and what is and isn't modeled | 5, 9–12, 25 |
