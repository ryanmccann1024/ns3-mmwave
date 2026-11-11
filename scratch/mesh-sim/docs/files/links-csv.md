# links.csv {#files_links_csv}

[TOC]

`links.csv` has one row per node pair per saved tick: distance, SINR, LOS or
NLOS, capacity and the traffic routed over the link. Each seed writes its own,
in `seed-N/links.csv`.

\htmlonly
<div class="ms-find" data-noun="column"><div class="ms-find-field"><svg class="ms-find-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg><input type="search" placeholder="Search columns, e.g. sinr_db, capacity, LOS" aria-label="Search columns"><kbd class="ms-find-kbd">/</kbd></div><span class="ms-find-count"></span></div>
<script src="key-find.js"></script>
\endhtmlonly

## 1\. Anatomy

The first two snapshots of `outputs/examples/07-three-node-relay/seed-1/links.csv`.
Nodes `0` (`node-a`), `1` (`relay`) and `2` (`node-c`) sit in a line 500 m
apart, with a 10 Mbps flow between every pair. Each band shows some of the
columns of the same six rows:

\htmlonly
<div class="ms-ini">
<div class="ms-ini-row ms-c-blue">
<pre class="ms-ini-code"><b>time_s,   node_a, node_b, dist_m</b>
0.000000, 0,      1,      500.000000
0.000000, 0,      2,      1000.000000
0.000000, 1,      2,      500.000000
0.100000, 0,      1,      500.000000
0.100000, 0,      2,      1000.000000
0.100000, 1,      2,      500.000000</pre>
<div class="ms-ini-note"><strong>Which pair, when</strong>Two snapshots, 0.1 s apart, of the three node pairs. Each pair appears once per snapshot, lower node index first.</div>
</div>
<div class="ms-ini-row ms-c-purple">
<pre class="ms-ini-code"><b>sinr_db,    condition, condition_reason</b>
21.609056,  LOS,       probabilistic
-28.488349, NLOS,      probabilistic
12.510942,  NLOS,      probabilistic
21.609056,  LOS,       probabilistic
-31.954419, NLOS,      probabilistic
-9.681627,  NLOS,      probabilistic</pre>
<div class="ms-ini-note"><strong>Radio state</strong>Pair <code>0,1</code> is a strong LOS link. Pair <code>0,2</code> is 1000 m NLOS, far below &minus;6.7 dB. Pair <code>1,2</code> is NLOS but usable at 12.5 dB until a shadowing redraw takes it to &minus;9.7 dB at 0.1 s.</div>
</div>
<div class="ms-ini-row ms-c-green">
<pre class="ms-ini-code"><b>capacity_mbps, delivered_mbps, hop_count</b>
2875.3,        20.0,           2
0.0,           0.0,            0
1693.9,        20.0,           2
2875.3,        10.0,           1
0.0,           0.0,            0
0.0,           0.0,            0</pre>
<div class="ms-ini-note"><strong>Capacity and traffic</strong>At 0 s, pair <code>0,1</code> carries 20 Mbps: the flow from 0 to 1 plus the flow from 0 to 2 relayed through node 1, so <code>hop_count</code> is 2. Pair <code>1,2</code> carries the flow from 1 to 2 and the same relayed flow. At 0.1 s, pair <code>1,2</code> has no capacity, both flows into node 2 lose their route, and <code>0,1</code> carries only its own 10 Mbps.</div>
</div>
</div>
\endhtmlonly

- Every snapshot lists every pair once, lower node index first:
  \f$ N(N-1)/2 \f$ rows.
- A snapshot is written at t = 0 and then every `[output] viz_tick_ms`.
  `--no-viz` writes no file.
- Capacities and traffic have 1 decimal; everything else 6.

## 2\. Which pair, when

The snapshot time and the two nodes of the pair.

<div class="ms-keys ms-c-blue">
<div class="ms-key ms-key-head"><div>Column</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`time_s`<span class="ms-key-def">s</span></div>
<div class="ms-key-what">Sim time of the snapshot. Every row of one snapshot has the same value.</div>
<div class="ms-key-vals">0 to `duration_s`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`node_a`<span class="ms-key-def">index</span></div>
<div class="ms-key-what">The node listed first in `nodes.json`, numbered from 0.<div class="ms-key-note">Its transmit gain applies to this link (\ref files_nodes_json "nodes.json").</div></div>
<div class="ms-key-vals">0 to N−2</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`node_b`<span class="ms-key-def">index</span></div>
<div class="ms-key-what">The node listed later. Its receive gain applies.</div>
<div class="ms-key-vals">`node_a + 1` to N−1</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`dist_m`<span class="ms-key-def">m</span></div>
<div class="ms-key-what">3-D distance between the two nodes.</div>
<div class="ms-key-vals">&ge; 0</div>
</div>
</div>

## 3\. Radio state

The link's SINR and its LOS/NLOS state.

<div class="ms-keys ms-c-purple">
<div class="ms-key ms-key-head"><div>Column</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`sinr_db`<span class="ms-key-def">dB</span></div>
<div class="ms-key-what">Signal over noise, plus jammers in `sub-6`. Other mesh links do not interfere.<div class="ms-key-note">How it is worked out: \ref files_channel_models "Channel models". `-999` means a node on the link has dropped out.</div></div>
<div class="ms-key-vals">any number, or `-999.000000` for a failed node</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`condition`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">Whether the pair has a clear line of sight.<div class="ms-key-note">Without buildings it is a coin flip per pair, kept for the whole run even when the nodes move (\ref files_channel_los "LOS, NLOS and shadowing").</div></div>
<div class="ms-key-vals">`LOS`, `NLOS`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`condition_reason`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">What decided `condition`: `building` on every row when the scenario has any building, otherwise `probabilistic`.</div>
<div class="ms-key-vals">`building`, `probabilistic`</div>
</div>
</div>

## 4\. Capacity and traffic

What the link can carry and what the router put on it.

<div class="ms-keys ms-c-green">
<div class="ms-key ms-key-head"><div>Column</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`capacity_mbps`<span class="ms-key-def">Mbps</span></div>
<div class="ms-key-what">What the link can carry, from its SINR and `amc_model`.<div class="ms-key-note">0 below −6.7 dB (\ref files_channel_capacity "SINR and capacity").</div></div>
<div class="ms-key-vals">&ge; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`delivered_mbps`<span class="ms-key-def">Mbps</span></div>
<div class="ms-key-what">The traffic on the link: all flows crossing it, both directions.<div class="ms-key-note">Equal to `capacity_mbps` on an overloaded link (\ref files_routing "Routing").</div></div>
<div class="ms-key-vals">0 to `capacity_mbps`; 0 when no flow uses the pair</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`hop_count`<span class="ms-key-def">hops</span></div>
<div class="ms-key-what">The longest path, in hops, among the flows on this link. A direct link reads 2 when a relayed flow uses it.</div>
<div class="ms-key-vals">0 to N−1; 0 when no flow uses the pair</div>
</div>
</div>

## 5\. Reading it

| Normal | A problem |
|---|---|
| Static nodes: every value constant from the second snapshot (t = 0 takes a first shadowing draw). | A link on a route close to −6.7 dB. |
| Moving nodes: SINR changes every tick. | `delivered_mbps` equal to `capacity_mbps`: a bottleneck. |
| `capacity_mbps` is 0 only below −6.7 dB. | `-999` rows: a node has dropped out (`active = 0` in \ref files_positions_csv "positions.csv"). |

Which link is the bottleneck at each snapshot
(`outputs/examples/09-congestion-bottleneck`, three 2000 Mbps flows into
`dst` through `relay`):

```python
import pandas as pd

links = pd.read_csv("outputs/examples/09-congestion-bottleneck/seed-1/links.csv")
used = links[links.delivered_mbps > 0].copy()
used["util"] = used.delivered_mbps / used.capacity_mbps
worst = used.loc[used.groupby("time_s").util.idxmax()]
print(worst[["time_s", "node_a", "node_b", "capacity_mbps", "delivered_mbps", "util"]].head(3))
```

```text
    time_s  node_a  node_b  capacity_mbps  delivered_mbps  util
5      0.0       2       3         1417.1          1417.1   1.0
11     0.1       2       3         1795.7          1795.7   1.0
17     0.2       2       3         1795.7          1795.7   1.0
```

When a pair changed between LOS and NLOS
(`outputs/examples/03-building-blockage`, node 1 driving out from behind a
building):

```python
links = pd.read_csv("outputs/examples/03-building-blockage/seed-1/links.csv")
pair = links[(links.node_a == 0) & (links.node_b == 1)]
print(pair[pair.condition != pair.condition.shift()][["time_s", "dist_m", "sinr_db", "condition"]])
```

```text
     time_s      dist_m    sinr_db condition
0       0.0  200.000000  21.516329      NLOS
223    22.3  204.912567  29.357084       LOS
```

## 6\. Related

- \ref files_rx_power_csv "rx-power.csv" and \ref files_mcs_csv "mcs.csv": the same pairs, same row order
- \ref files_flows_csv "flows.csv" and \ref files_routes_csv "routes.csv": the flows behind `delivered_mbps`
- \ref files_channel_models "Channel models": how each value is worked out
- \ref scripts_plotting "scripts/plotting": plots of SINR, capacity and throughput over time

Previous: \ref files_summary_json "summary.json" · Up: \ref mesh_sim_files "Input and output files" · Next: \ref files_flows_csv "flows.csv"
