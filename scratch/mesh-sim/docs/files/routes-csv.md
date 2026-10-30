# routes.csv {#files_routes_csv}

[TOC]

`routes.csv` has one row per flow per saved tick: the path the flow took and
the weakest link capacity on it. Each seed writes its own, in
`seed-N/routes.csv`.

\htmlonly
<div class="ms-find" data-noun="column"><div class="ms-find-field"><svg class="ms-find-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg><input type="search" placeholder="Search columns, e.g. path, routable, bottleneck_mbps" aria-label="Search columns"><kbd class="ms-find-kbd">/</kbd></div><span class="ms-find-count"></span></div>
<script src="key-find.js"></script>
\endhtmlonly

## 1\. Anatomy

The first snapshot of `outputs/examples/12-gateway-topology/seed-1/routes.csv`,
split by column group. Three nodes 150 m from the gateway `gw` (node 0) each
send 100 Mbps to it.

\htmlonly
<div class="ms-ini">
<div class="ms-ini-row ms-c-blue">
<pre class="ms-ini-code"><b>time_s,   src, dst</b>
0.000000, 1,   0
0.000000, 2,   0
0.000000, 3,   0</pre>
<div class="ms-ini-note"><strong>Which flow, when</strong>Three flows at <code>t = 0</code>, one per sender, all to node 0.</div>
</div>
<div class="ms-ini-row ms-c-green">
<pre class="ms-ini-code"><b>path,  bottleneck_mbps, hop_count, routable</b>
1;0,   3750.6,          1,         1
2;3;0, 3354.9,          2,         1
3;0,   4261.3,          1,         1</pre>
<div class="ms-ini-note"><strong>The route</strong>Flow <code>2 &rarr; 0</code> relays through node 3, because 1/3354.9 + 1/4261.3 is less than 1 / the capacity of the direct link <code>2&ndash;0</code>. At <code>t = 0.1</code> the capacities change and it goes direct.</div>
</div>
</div>
\endhtmlonly

- Same rows as \ref files_flows_csv "flows.csv": row *k* of a snapshot here
  is row *k* of the same snapshot there.
- A snapshot is written at t = 0 and then every `[output] viz_tick_ms`.
  `--no-viz` writes no file.
- `bottleneck_mbps` has 1 decimal, `time_s` 6.

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
<div class="ms-key-name">`src`<span class="ms-key-def">integer</span></div>
<div class="ms-key-what">Source node, numbered from 0 in `nodes.json` order.</div>
<div class="ms-key-vals">0 to N&minus;1</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`dst`<span class="ms-key-def">integer</span></div>
<div class="ms-key-what">Destination node.</div>
<div class="ms-key-vals">0 to N&minus;1</div>
</div>
</div>

## 3\. The route

The path the router chose this tick and the capacity it offers.

<div class="ms-keys ms-c-green">
<div class="ms-key ms-key-head"><div>Column</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`path`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">The nodes the flow passes through, source first, separated by `;`. Empty when `routable` is `0`.</div>
<div class="ms-key-vals">`src;…;dst`, or empty</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`bottleneck_mbps`<span class="ms-key-def">Mbps</span></div>
<div class="ms-key-what">The smallest `capacity_mbps` among the path's links.<div class="ms-key-note">Other flows on those links are not subtracted.</div></div>
<div class="ms-key-vals">&ge; 0; `0.0` when unroutable</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`hop_count`<span class="ms-key-def">integer</span></div>
<div class="ms-key-what">Links on the path: the nodes in `path` minus 1.</div>
<div class="ms-key-vals">0 to N&minus;1; `0` when unroutable</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`routable`<span class="ms-key-def">flag</span></div>
<div class="ms-key-what">`1` when the flow has a path.<div class="ms-key-note">`0` with no path, a path longer than `max_hops`, or zero demand this tick.</div></div>
<div class="ms-key-vals">`1`, `0`</div>
</div>
</div>

At `t = 0.1` in `outputs/examples/07-three-node-relay`, two of the three flows
have no route:

```text
0.100000,0,1,0;1,2875.3,1,1
0.100000,0,2,,0.0,0,0
0.100000,1,2,,0.0,0,0
```

The router picks every path fresh each tick; \ref files_routing "Routing"
shows how each `algorithm` chooses and how `max_hops` applies.

## 4\. Reading it

| Normal | A problem |
|---|---|
| Static nodes: one path per flow from the second snapshot. | Empty paths: no route. |
| `bottleneck_mbps` well above the flow's demand. | `bottleneck_mbps` below the demand. |
| Paths change when nodes move. | Paths that flip every few ticks: two routes of almost equal cost, or a link near &minus;6.7 dB. |

When each flow's route changed (`outputs/examples/12-gateway-topology`):

```python
import pandas as pd

routes = pd.read_csv("outputs/examples/12-gateway-topology/seed-1/routes.csv",
                     dtype={"path": str}, keep_default_na=False)   # keep "" for unroutable
prev = routes.groupby(["src", "dst"]).path.shift()
print(routes[prev.notna() & (routes.path != prev)])
```

```text
   time_s  src  dst path  bottleneck_mbps  hop_count  routable
4     0.1    2    0  2;0           4261.3          1         1
```

Which links carry the most routes over the run
(`outputs/examples/14-max-hops-limit`, five nodes in a 200 m-spaced line):

```python
routes = pd.read_csv("outputs/examples/14-max-hops-limit/seed-1/routes.csv",
                     dtype={"path": str}, keep_default_na=False)
hops = routes[routes.routable == 1].path.str.split(";").apply(lambda p: list(zip(p, p[1:])))
edges = hops.explode().apply(lambda e: tuple(sorted(map(int, e))))
print(edges.value_counts().head(3))
```

```text
path
(2, 3)    305
(3, 4)    203
(1, 2)    155
```

## 5\. Related

- \ref files_flows_csv "flows.csv": demand, delivered rate and latency for the same rows
- \ref files_links_csv "links.csv": the capacities the router used
- \ref files_routing "Routing": the three algorithms and `max_hops`
- \ref files_run_ini "run.ini": the `[routing]` keys

Previous: \ref files_flows_csv "flows.csv" · Up: \ref mesh_sim_files "Input and output files" · Next: \ref files_positions_csv "positions.csv"
