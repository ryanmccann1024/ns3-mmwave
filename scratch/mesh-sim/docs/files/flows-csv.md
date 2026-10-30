# flows.csv {#files_flows_csv}

[TOC]

`flows.csv` has one row per traffic flow per saved tick: what the flow asked
for, what the mesh delivered, its latency and hop count, and whether it had a
route. Each seed writes its own, in `seed-N/flows.csv`.

\htmlonly
<div class="ms-find" data-noun="column"><div class="ms-find-field"><svg class="ms-find-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg><input type="search" placeholder="Search columns, e.g. routable, latency, demand" aria-label="Search columns"><kbd class="ms-find-kbd">/</kbd></div><span class="ms-find-count"></span></div>
<script src="key-find.js"></script>
\endhtmlonly

## 1\. Anatomy

The first snapshot of `outputs/examples/09-congestion-bottleneck/seed-1/flows.csv`.
`gateway` topology: every node sends 2000 Mbps to `dst` (node 3), and nodes 0
and 1 reach it only through `relay` (node 2). Each band shows some of the
columns of the same three rows:

\htmlonly
<div class="ms-ini">
<div class="ms-ini-row ms-c-blue">
<pre class="ms-ini-code"><b>time_s,   src, dst</b>
0.000000, 0,   3
0.000000, 1,   3
0.000000, 2,   3</pre>
<div class="ms-ini-note"><strong>Which flow, when</strong>Three flows into node 3 at 0 s, one row per flow, in the order the flows were created.</div>
</div>
<div class="ms-ini-row ms-c-green">
<pre class="ms-ini-code"><b>demand_mbps, delivered_mbps</b>
2000.0,      472.4
2000.0,      472.4
2000.0,      472.4</pre>
<div class="ms-ini-note"><strong>Asked for and delivered</strong>All three flows cross the <code>2&ndash;3</code> link (1417.1 Mbps), which is asked for 6000 Mbps, so each gets 2000 &times; 1417.1 / 6000 = 472.4 Mbps.</div>
</div>
<div class="ms-ini-row ms-c-amber">
<pre class="ms-ini-code"><b>latency_ms, hop_count, routable</b>
1.001,      2,         1
1.001,      2,         1
0.501,      1,         1</pre>
<div class="ms-ini-note"><strong>The path</strong>Nodes 0 and 1 take two hops through the relay, node 2 one. Each hop costs about 0.5 ms. Every flow has a route.</div>
</div>
</div>
\endhtmlonly

- One row per flow that exists at that tick, in the order the flows were
  created. Row *k* of a snapshot is row *k* of the same snapshot in
  \ref files_routes_csv "routes.csv".
- `[traffic]` decides which flows exist and when (\ref files_traffic "Traffic").
- A snapshot is written at t = 0 and then every `[output] viz_tick_ms`.
  `--no-viz` writes no file.
- `time_s` has 6 decimals, the Mbps columns 1, `latency_ms` 3.

## 2\. Which flow, when

The snapshot time and the flow's two ends.

<div class="ms-keys ms-c-blue">
<div class="ms-key ms-key-head"><div>Column</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`time_s`<span class="ms-key-def">s</span></div>
<div class="ms-key-what">Sim time of the snapshot.</div>
<div class="ms-key-vals">0 to `duration_s`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`src`<span class="ms-key-def">index</span></div>
<div class="ms-key-what">Source node, numbered from 0 in `nodes.json` order.</div>
<div class="ms-key-vals">0 to N−1</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`dst`<span class="ms-key-def">index</span></div>
<div class="ms-key-what">Destination node.</div>
<div class="ms-key-vals">0 to N−1, never `src`</div>
</div>
</div>

## 3\. Asked for and delivered

The flow's demand this tick and the rate the mesh carried.

<div class="ms-keys ms-c-green">
<div class="ms-key ms-key-head"><div>Column</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`demand_mbps`<span class="ms-key-def">Mbps</span></div>
<div class="ms-key-what">What the flow asks for this tick: 0 in an `on_off` OFF phase.<div class="ms-key-note">`[traffic] demand_mbps`, or each pair's own rate with `explicit_pairs`.</div></div>
<div class="ms-key-vals">&ge; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`delivered_mbps`<span class="ms-key-def">Mbps</span></div>
<div class="ms-key-what">What the mesh carried. 0 when unroutable.<div class="ms-key-note">Below `demand_mbps` when a link on the path is overloaded (\ref files_routing "Routing").</div></div>
<div class="ms-key-vals">0 to `demand_mbps`</div>
</div>
</div>

## 4\. The path

The route the router found, if any.

<div class="ms-keys ms-c-amber">
<div class="ms-key ms-key-head"><div>Column</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`latency_ms`<span class="ms-key-def">ms</span></div>
<div class="ms-key-what">One-way latency: about 0.5 ms per hop. 0 when unroutable.<div class="ms-key-note">Load does not change it. Light adds 0.0033 ms per km, so a 100 m hop reads `0.500` at 3 decimals (\ref files_routing "Routing").</div></div>
<div class="ms-key-vals">0, or &ge; 0.5 × `hop_count`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`hop_count`<span class="ms-key-def">hops</span></div>
<div class="ms-key-what">Links on the path. 0 when unroutable.</div>
<div class="ms-key-vals">0 to N−1</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`routable`<span class="ms-key-def">flag</span></div>
<div class="ms-key-what">`1` when the flow has a path.<div class="ms-key-note">`0` with demand: no path, or one longer than `max_hops`.</div></div>
<div class="ms-key-vals">`1`, `0`</div>
</div>
</div>

## 5\. How each row is built

\ref files_routing "Routing" explains how the router picks each path and
scales flows on an overloaded link. The anatomy rows, step by step:

\image html flow-accounting.svg "09-congestion-bottleneck at t = 0: link capacities and carried traffic (left), and how the router turns each 2000 Mbps demand into a path, a delivered rate and a latency (right)."

## 6\. Reading it

| Normal | A problem |
|---|---|
| `routable` 1, `delivered_mbps` equal to `demand_mbps`, about 0.5 ms per hop. | `delivered_mbps` below `demand_mbps`: congestion. The full link has `delivered_mbps` equal to `capacity_mbps` in \ref files_links_csv "links.csv". |
| 0 demand and `routable` 0: an `on_off` OFF phase. | `routable` 0 with demand: no path, or one longer than `max_hops`. |
| Static nodes: rates can change once, at t = 0.1, after the first shadowing draw. | A flow that drops in and out of `routable`: a link on its path near −6.7 dB. |

When did a flow lose its route
(`outputs/examples/07-three-node-relay`, the flow from 0 to 2):

```python
import pandas as pd

flows = pd.read_csv("outputs/examples/07-three-node-relay/seed-1/flows.csv")
f = flows[(flows.src == 0) & (flows.dst == 2)]
print(f[f.routable != f.routable.shift()][["time_s", "delivered_mbps", "latency_ms", "hop_count", "routable"]])
```

```text
   time_s  delivered_mbps  latency_ms  hop_count  routable
1     0.0            10.0       1.003          2         1
4     0.1             0.0       0.000          0         0
```

Each row is a change of state: routed at `t = 0`, unroutable from `t = 0.1`.

How much of its demand each flow got
(`outputs/examples/09-congestion-bottleneck`):

```python
flows = pd.read_csv("outputs/examples/09-congestion-bottleneck/seed-1/flows.csv")
flows["served"] = flows.delivered_mbps / flows.demand_mbps   # NaN in OFF phases
print(flows.groupby(["src", "dst"]).served.agg(["mean", "min"]).round(3))
```

```text
          mean    min
src dst
0   3    0.298  0.236
1   3    0.298  0.236
2   3    0.298  0.236
```

## 7\. Related

- \ref files_routes_csv "routes.csv": the path and bottleneck for each row
- \ref files_links_csv "links.csv": the capacities the router used
- \ref files_traffic "Traffic" and \ref files_routing "Routing": how flows are made and carried
- \ref files_summary_json "summary.json": per-flow and network averages of these rows
- \ref scripts_plotting "scripts/plotting": throughput and latency over time

Previous: \ref files_links_csv "links.csv" · Up: \ref mesh_sim_files "Input and output files" · Next: \ref files_routes_csv "routes.csv"
