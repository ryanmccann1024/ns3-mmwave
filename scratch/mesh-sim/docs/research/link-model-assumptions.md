# Research record: link model assumptions {#research_link_model}

[TOC]

The assumptions behind how Mesh-Sim evaluates each link (received power,
noise, capacity) and routes flows over the result.

Back to \ref mesh_sim_research "Research records" · all decks:
\ref mesh_sim_research_sources "Research sources".

## 1\. Background

When we bootstrapped Mesh-Sim in April (see \ref research_flow_abstraction),
we walked through how a link is evaluated and how traffic is routed
(R03 slides 13–23). Distance, LOS/NLOS and path loss still come from the ns-3
propagation models (3GPP or NYU), the same as before (R03 slide 13). The
assumptions below are what Mesh-Sim adds on top.

## 2\. Received power and beamforming gain

Received power is TX power, minus path loss, plus beamforming gain
(R03 slide 15).

Beamforming gain is modeled as ideal: perfectly aligned and symmetric, with no
uplink/downlink distinction, since that involves time-domain resources. We chose
this because it is easier and faster for now; penalties can be added later
(R03 slide 14). Ideas for later were DFT-based beamforming, the ns-3 phased-array
model, and per-node array sizes (R03 slide 14).

Today the gain is the TX node's `tx_array_gain_dbi` plus the RX node's
`rx_array_gain_dbi`. Each node can override the channel default in
`nodes.json`, which covers per-node array sizes.

## 3\. Noise and SINR

Noise is thermal (Nyquist) noise, which grows with bandwidth. There is no
inter-node interference, so SINR is signal over the noise floor (R03 slide 16).

Today:

- Noise floor: `-174 + 10·log10(bandwidth_Hz) + noise_figure_dB` dBm.
- Path loss is never below free-space path loss at `max(distance, 1 m)`.
- In sub-6, jammer power is added to the denominator (see
  \ref research_jammer_model).

## 4\. Capacity

Two ways to turn SINR into capacity (R03 slides 16–17):

- **Shannon–Hartley:** the theoretical maximum rate for the computed SINR,
  `B·log2(1+SINR)`.
- **MCS table:** pick the highest row whose minimum SINR is met and multiply
  its spectral efficiency by the bandwidth. For example, CQI 14 gives
  5.55 bits/s/Hz, so 555 Mbps at 100 MHz.

Today `[channel] amc_model` selects `shannon`, `table`, or `silvus` (Silvus
single-stream MCS 0–6, scaled to the configured bandwidth). Any SINR below
−6.7 dB gives 0 Mbps.

## 5\. Routing

Three routing algorithms (R03 slide 21):

- **Shortest path** with edge weight `1/capacity_mbps`, which prefers
  high-capacity links and penalizes extra hops. This is the default.
- **Max throughput:** find each path's weakest link and pick the path whose
  weakest link is best.
- **Min hop:** fewest hops, ignoring link quality.

When a link is overloaded, no flow is blocked. Instead, each flow on that link
is scaled down. We chose this for fairness (R03 slides 21 and 23). Today each
flow on an overloaded edge is scaled by `capacity / total_demand`, and a flow
keeps the smallest factor across its hops.

Processing latency is a constant (R03 slide 22). Today each hop adds
propagation delay plus a fixed 0.5 ms processing delay.

## 6\. Where this lives now

- \ref src_eval "src/eval": received power, noise floor, array gains and
  capacity models (`link-evaluator.cc`, `sinr-capacity.h`).
- \ref src_routing "src/routing": routing algorithms, congestion scaling and
  latency (`mesh-router.cc`).

## 7\. Sources

The original decks are on OneDrive. If you have a question about a specific
assumption, open the presentation and slide listed here. The slide text and
speaker notes are also in
<a href="research-slide-text.txt">research-slide-text.txt</a>.

| ID | Presentation | What it covers | Slides used here |
|---|---|---|---|
| R03 | 04-02 mmWave Mesh.pptx | The Mesh-Sim bootstrap: link evaluation (path loss, beamforming gain, noise, capacity) and flow routing (algorithms, latency, congestion scaling) | 13–17, 21–23 |
