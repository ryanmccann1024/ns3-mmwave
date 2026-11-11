# Traffic {#files_traffic}

[TOC]

Traffic in Mesh-Sim is a list of flows. A flow is a source, a destination and
a rate in Mbps, with no packets. `[traffic]` in \ref files_run_ini "run.ini"
decides which flows exist (`flow_topology`) and how they change over time
(`model`). Each tick the router then tries to carry every flow
(\ref files_routing "Routing"). This page runs the same small network under
each setting.

## 1\. The example

Four fixed nodes, `a` to `d`, on the corners of a 100 m square. Every link is
LOS and carries at least 4,329 Mbps, so every flow below gets through in full
and only the traffic settings change what happens.

```ini
[channel]
channel_model     = nyu
condition_model   = static_los
[nyu_channel]
shadowing_enabled = false
[traffic]
demand_mbps       = 100.0
; plus the settings in each section below
```

## 2\. Which flows exist: flow_topology

`flow_topology` sets the flows at t = 0. The drawings show the four settings
on the square, from each run's first row of \ref files_flows_csv "flows.csv".

\htmlonly
<div class="ms-flow-split ms-routes ms-routes-4">
<div class="ms-flow-art ms-c-blue"><svg viewBox="0 0 140 112" aria-hidden="true"><defs><marker id="ah-all_pairs" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs><line class="ms-ink" x1="43.0" y1="84.0" x2="96.0" y2="84.0" marker-end="url(#ah-all_pairs)"/><line class="ms-ink" x1="40.8" y1="78.1" x2="98.4" y2="28.5" marker-end="url(#ah-all_pairs)"/><line class="ms-ink" x1="34.0" y1="75.0" x2="34.0" y2="32.0" marker-end="url(#ah-all_pairs)"/><line class="ms-ink" x1="106.0" y1="75.0" x2="106.0" y2="32.0" marker-end="url(#ah-all_pairs)"/><line class="ms-ink" x1="99.2" y1="78.1" x2="41.6" y2="28.5" marker-end="url(#ah-all_pairs)"/><line class="ms-ink" x1="97.0" y1="22.0" x2="44.0" y2="22.0" marker-end="url(#ah-all_pairs)"/><circle class="ms-dot" cx="34" cy="84" r="6"/><text x="22" y="88" text-anchor="middle">a</text><circle class="ms-dot" cx="106" cy="84" r="6"/><text x="118" y="88" text-anchor="middle">b</text><circle class="ms-dot" cx="106" cy="22" r="6"/><text x="118" y="26" text-anchor="middle">c</text><circle class="ms-dot" cx="34" cy="22" r="6"/><text x="22" y="26" text-anchor="middle">d</text><text x="70" y="108" text-anchor="middle" class="ms-strong">all_pairs</text></svg></div>
<div class="ms-flow-art ms-c-purple"><svg viewBox="0 0 140 112" aria-hidden="true"><defs><marker id="ah-gateway" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs><line class="ms-ink" x1="97.0" y1="84.0" x2="44.0" y2="84.0" marker-end="url(#ah-gateway)"/><line class="ms-ink" x1="99.2" y1="27.9" x2="41.6" y2="77.5" marker-end="url(#ah-gateway)"/><line class="ms-ink" x1="34.0" y1="31.0" x2="34.0" y2="74.0" marker-end="url(#ah-gateway)"/><circle class="ms-dot" cx="34" cy="84" r="6"/><text x="22" y="88" text-anchor="middle">a</text><circle class="ms-dot" cx="106" cy="84" r="6"/><text x="118" y="88" text-anchor="middle">b</text><circle class="ms-dot" cx="106" cy="22" r="6"/><text x="118" y="26" text-anchor="middle">c</text><circle class="ms-dot" cx="34" cy="22" r="6"/><text x="22" y="26" text-anchor="middle">d</text><text x="70" y="108" text-anchor="middle" class="ms-strong">gateway</text></svg></div>
<div class="ms-flow-art ms-c-pink"><svg viewBox="0 0 140 112" aria-hidden="true"><defs><marker id="ah-random_pairs" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs><line class="ms-ink" x1="40.8" y1="78.1" x2="98.4" y2="28.5" marker-end="url(#ah-random_pairs)"/><line class="ms-ink" x1="97.0" y1="84.0" x2="44.0" y2="84.0" marker-end="url(#ah-random_pairs)"/><line class="ms-ink" x1="106.0" y1="31.0" x2="106.0" y2="74.0" marker-end="url(#ah-random_pairs)"/><circle class="ms-dot" cx="34" cy="84" r="6"/><text x="22" y="88" text-anchor="middle">a</text><circle class="ms-dot" cx="106" cy="84" r="6"/><text x="118" y="88" text-anchor="middle">b</text><circle class="ms-dot" cx="106" cy="22" r="6"/><text x="118" y="26" text-anchor="middle">c</text><circle class="ms-dot" cx="34" cy="22" r="6"/><text x="22" y="26" text-anchor="middle">d</text><text x="70" y="108" text-anchor="middle" class="ms-strong">random_pairs</text></svg></div>
<div class="ms-flow-art ms-c-amber"><svg viewBox="0 0 140 112" aria-hidden="true"><defs><marker id="ah-explicit" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs><line class="ms-ink" x1="97.0" y1="84.0" x2="44.0" y2="84.0" marker-end="url(#ah-explicit)"/><text x="70" y="79" text-anchor="middle" class="ms-strong">250</text><line class="ms-ink" x1="43.0" y1="22.0" x2="96.0" y2="22.0" marker-end="url(#ah-explicit)"/><text x="70" y="17" text-anchor="middle" class="ms-strong">40</text><circle class="ms-dot" cx="34" cy="84" r="6"/><text x="22" y="88" text-anchor="middle">a</text><circle class="ms-dot" cx="106" cy="84" r="6"/><text x="118" y="88" text-anchor="middle">b</text><circle class="ms-dot" cx="106" cy="22" r="6"/><text x="118" y="26" text-anchor="middle">c</text><circle class="ms-dot" cx="34" cy="22" r="6"/><text x="22" y="26" text-anchor="middle">d</text><text x="70" y="108" text-anchor="middle" class="ms-strong">explicit_pairs</text></svg></div>
</div>
\endhtmlonly

| Setting | Flows at t = 0 (seed 1) | Count |
|---|---|---|
| `flow_topology = all_pairs` | a → b, a → c, a → d, b → c, b → d, c → d | 6 |
| `flow_topology = gateway`, `gateway_node_id = a` | b → a, c → a, d → a | 3 |
| `flow_topology = random_pairs`, `random_pair_count = 3` | a → c, b → a, c → b | 3 |
| `flow_topology = explicit_pairs`, two `pairs` | b → a (250 Mbps), d → c (40 Mbps) | 2 |

- `all_pairs` sends one flow per pair, from the node listed first in
  `nodes.json` to the later one: \f$ N(N-1)/2 \f$ flows.
- `random_pairs` draws each source and destination uniformly; the same pair
  can appear twice. The draw depends on `seed`.
- `explicit_pairs` gives each flow its own rate and needs `model = constant`.

## 3\. constant: always on

Two nodes, `flow_topology = all_pairs`: one flow, `a` → `b`, at 100 Mbps.

\htmlonly
<div class="ms-flow-art ms-scene ms-timeline ms-c-green"><svg viewBox="0 0 640 74" aria-hidden="true"><text x="86" y="24" text-anchor="end" class="ms-strong">a → b</text><rect class="ms-soft" x="96.0" y="10" width="525.2" height="20" rx="2"/><line class="ms-faint" x1="96" y1="42" x2="616" y2="42"/><text x="96" y="58" text-anchor="middle">0 s</text><text x="200" y="58" text-anchor="middle">2 s</text><text x="304" y="58" text-anchor="middle">4 s</text><text x="408" y="58" text-anchor="middle">6 s</text><text x="512" y="58" text-anchor="middle">8 s</text><text x="616" y="58" text-anchor="middle">10 s</text></svg></div>
\endhtmlonly

With `model = constant` the flow asks for 100 Mbps on every one of the 101
ticks from 0 to 10 s.

## 4\. on_off: switching between sending and silent

The same flow with `model = on_off`, `on_time_s = 1.0`, `off_time_s = 1.0`.

\htmlonly
<div class="ms-flow-art ms-scene ms-timeline ms-c-green"><svg viewBox="0 0 640 74" aria-hidden="true"><text x="86" y="24" text-anchor="end" class="ms-strong">a → b</text><rect class="ms-soft" x="96.0" y="10" width="46.8" height="20" rx="2"/><rect class="ms-soft" x="158.4" y="10" width="52.0" height="20" rx="2"/><rect class="ms-soft" x="252.0" y="10" width="20.8" height="20" rx="2"/><rect class="ms-soft" x="298.8" y="10" width="10.4" height="20" rx="2"/><rect class="ms-soft" x="371.6" y="10" width="72.8" height="20" rx="2"/><rect class="ms-soft" x="454.8" y="10" width="57.2" height="20" rx="2"/><rect class="ms-soft" x="564.0" y="10" width="15.6" height="20" rx="2"/><rect class="ms-soft" x="616.0" y="10" width="5.2" height="20" rx="2"/><line class="ms-faint" x1="96" y1="42" x2="616" y2="42"/><text x="96" y="58" text-anchor="middle">0 s</text><text x="200" y="58" text-anchor="middle">2 s</text><text x="304" y="58" text-anchor="middle">4 s</text><text x="408" y="58" text-anchor="middle">6 s</text><text x="512" y="58" text-anchor="middle">8 s</text><text x="616" y="58" text-anchor="middle">10 s</text></svg></div>
\endhtmlonly

Every flow starts ON. Each phase lasts a random time drawn from an exponential
distribution with mean \f$ \mu \f$ (`on_time_s` or `off_time_s`):

\f[ P(T > t) = e^{-t/\mu} \f]

Short phases are common and long ones rare: in this run the phases ran from
0.2 s to 1.4 s. Each tick the simulator checks whether the current phase has
ended and flips it, so phases snap to the 0.1 s tick grid. The flow was ON for
54 of 101 ticks.

During an OFF tick the flow stays in \ref files_flows_csv "flows.csv" with
`demand_mbps` = 0, `delivered_mbps` = 0 and `routable` = 0. The router skips
it; it does not mean the path broke.

## 5\. poisson: random arrivals

`model = poisson`, `flow_topology = gateway` (`gateway_node_id = a`),
`arrival_rate_hz = 2.0`, `holding_time_s = 1.0`, over 10 s. Each row is one
flow; dots mark the flows that arrived during the run.

\htmlonly
<div class="ms-flow-art ms-scene ms-timeline ms-c-green"><svg viewBox="0 0 640 325" aria-hidden="true"><text x="86" y="18" text-anchor="end">b → a</text><rect class="ms-soft" x="96.0" y="8" width="52.0" height="11" rx="2"/><text x="86" y="33" text-anchor="end">c → a</text><rect class="ms-soft" x="96.0" y="23" width="52.0" height="11" rx="2"/><text x="86" y="48" text-anchor="end">d → a</text><rect class="ms-soft" x="96.0" y="38" width="52.0" height="11" rx="2"/><text x="86" y="63" text-anchor="end">b → d</text><rect class="ms-soft ms-arrival" x="163.6" y="53" width="182.0" height="11" rx="2"/><circle class="ms-dot" cx="163.6" cy="58" r="3"/><text x="86" y="78" text-anchor="end">a → d</text><rect class="ms-soft ms-arrival" x="194.8" y="68" width="130.0" height="11" rx="2"/><circle class="ms-dot" cx="194.8" cy="73" r="3"/><text x="86" y="93" text-anchor="end">d → c</text><rect class="ms-soft ms-arrival" x="226.0" y="83" width="176.8" height="11" rx="2"/><circle class="ms-dot" cx="226.0" cy="88" r="3"/><text x="86" y="108" text-anchor="end">c → a</text><rect class="ms-soft ms-arrival" x="241.6" y="98" width="15.6" height="11" rx="2"/><circle class="ms-dot" cx="241.6" cy="103" r="3"/><text x="86" y="123" text-anchor="end">b → c</text><rect class="ms-soft ms-arrival" x="246.8" y="113" width="130.0" height="11" rx="2"/><circle class="ms-dot" cx="246.8" cy="118" r="3"/><text x="86" y="138" text-anchor="end">c → d</text><rect class="ms-soft ms-arrival" x="267.6" y="128" width="26.0" height="11" rx="2"/><circle class="ms-dot" cx="267.6" cy="133" r="3"/><text x="86" y="153" text-anchor="end">c → b</text><rect class="ms-soft ms-arrival" x="288.4" y="143" width="109.2" height="11" rx="2"/><circle class="ms-dot" cx="288.4" cy="148" r="3"/><text x="86" y="168" text-anchor="end">b → d</text><rect class="ms-soft ms-arrival" x="298.8" y="158" width="62.4" height="11" rx="2"/><circle class="ms-dot" cx="298.8" cy="163" r="3"/><text x="86" y="183" text-anchor="end">b → c</text><rect class="ms-soft ms-arrival" x="371.6" y="173" width="104.0" height="11" rx="2"/><circle class="ms-dot" cx="371.6" cy="178" r="3"/><text x="86" y="198" text-anchor="end">b → d</text><rect class="ms-soft ms-arrival" x="382.0" y="188" width="26.0" height="11" rx="2"/><circle class="ms-dot" cx="382.0" cy="193" r="3"/><text x="86" y="213" text-anchor="end">c → a</text><rect class="ms-soft ms-arrival" x="397.6" y="203" width="10.4" height="11" rx="2"/><circle class="ms-dot" cx="397.6" cy="208" r="3"/><text x="86" y="228" text-anchor="end">d → a</text><rect class="ms-soft ms-arrival" x="434.0" y="218" width="67.6" height="11" rx="2"/><circle class="ms-dot" cx="434.0" cy="223" r="3"/><text x="86" y="243" text-anchor="end">a → d</text><rect class="ms-soft ms-arrival" x="486.0" y="233" width="135.2" height="11" rx="2"/><circle class="ms-dot" cx="486.0" cy="238" r="3"/><text x="86" y="258" text-anchor="end">c → d</text><rect class="ms-soft ms-arrival" x="486.0" y="248" width="31.2" height="11" rx="2"/><circle class="ms-dot" cx="486.0" cy="253" r="3"/><text x="86" y="273" text-anchor="end">c → b</text><rect class="ms-soft ms-arrival" x="491.2" y="263" width="62.4" height="11" rx="2"/><circle class="ms-dot" cx="491.2" cy="268" r="3"/><text x="86" y="288" text-anchor="end">b → d</text><rect class="ms-soft ms-arrival" x="564.0" y="278" width="57.2" height="11" rx="2"/><circle class="ms-dot" cx="564.0" cy="283" r="3"/><line class="ms-faint" x1="96" y1="299" x2="616" y2="299"/><text x="96" y="315" text-anchor="middle">0 s</text><text x="200" y="315" text-anchor="middle">2 s</text><text x="304" y="315" text-anchor="middle">4 s</text><text x="408" y="315" text-anchor="middle">6 s</text><text x="512" y="315" text-anchor="middle">8 s</text><text x="616" y="315" text-anchor="middle">10 s</text></svg></div>
\endhtmlonly

Each tick the number of new flows \f$ k \f$ is drawn from a Poisson
distribution with mean \f$ \lambda \f$ = `arrival_rate_hz` × `tick_s`:

\f[ P(k) = \frac{\lambda^k e^{-\lambda}}{k!}, \qquad \lambda = 2.0 \times 0.1 = 0.2 \f]

So 82% of ticks add nothing, 16% add one flow and 2% add two.

- Each new flow joins two different random nodes, whatever `flow_topology`
  says, at `demand_mbps`.
- Each new flow lasts a random time, exponential with mean `holding_time_s`.
- The three `gateway` flows from t = 0 last exactly `holding_time_s`: they
  ended at t = 1.0 s, and the network had no flows at all until the first
  arrival at 1.3 s.
- Expected arrivals over the run: \f$ 2.0 \times 10 = 20 \f$. Seed 1 made 16.
  At most 6 flows were active at once.

## 6\. What the router sees each tick

\htmlonly
<div class="ms-flow-step ms-step-card ms-c-grey">
<div class="ms-flow-art"><svg viewBox="0 0 140 92" aria-hidden="true"><rect class="ms-soft" x="10" y="14" width="36" height="24" rx="3"/><rect class="ms-soft" x="52" y="14" width="36" height="24" rx="3"/><rect class="ms-soft" x="94" y="14" width="36" height="24" rx="3"/><text x="28" y="30" text-anchor="middle">end</text><text x="70" y="30" text-anchor="middle">flip</text><text x="112" y="30" text-anchor="middle">add</text><line class="ms-ink" x1="10" y1="62" x2="130" y2="62"/><text x="70" y="82" text-anchor="middle">then route</text></svg></div>
<div class="ms-flow-body"><p>Each tick the traffic step runs before routing: flows past their end time are removed, <code>on_off</code> flows flip phase where due, and <code>poisson</code> adds its new flows. The router then gets the list.</p></div>
</div>
\endhtmlonly

| Flow state | Demand the router sees | In flows.csv |
|---|---|---|
| Active, ON (or `constant`, `poisson`) | its `demand_mbps` | one row per tick |
| `on_off`, OFF | 0, not routed | a row with 0 demand and `routable` = 0 |
| Past its holding time | none | no row from that tick on |

`holding_time_s = 0` (the default) means flows never end.

## 7\. Common changes

| To | Set | What you'll see |
|---|---|---|
| Send to one sink | `flow_topology = gateway`, `gateway_node_id = <id>` | N − 1 flows into that node. Example: `12-gateway-topology`. |
| Choose exact flows and rates | `flow_topology = explicit_pairs`, `pairs = [...]` | Only those flows, each at its own rate. |
| Bursty traffic | `model = on_off` | Flows drop to 0 Mbps during OFF phases. Example: `10-on-off-traffic`. |
| Flows that come and go | `model = poisson`, `holding_time_s > 0` | The flow count changes from tick to tick. Example: `11-poisson-arrivals`. |
| Load the network harder | Raise `demand_mbps` | Links overload and `delivered_mbps` falls below `demand_mbps` (\ref files_routing "Routing" section 7). |

## 8\. Related

- \ref files_routing "Routing": how each flow gets a path, and what happens when links overload
- \ref files_run_ini "run.ini": every `[traffic]` key with its range and default
- \ref files_flows_csv "flows.csv": one row per flow per tick
- \ref src_traffic "src/traffic": the traffic code

Previous: \ref files_channel_capacity "SINR and capacity" · Up: \ref mesh_sim_files "Input and output files" · Next: \ref files_routing "Routing"
