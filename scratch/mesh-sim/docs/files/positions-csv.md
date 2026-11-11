# positions.csv {#files_positions_csv}

[TOC]

`positions.csv` has one row per node per saved tick: its position, its type
and whether it is online. A block of `#` lines with run settings sits on top.
Each seed writes its own, in `seed-N/positions.csv`.

\htmlonly
<div class="ms-find" data-noun="column"><div class="ms-find-field"><svg class="ms-find-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg><input type="search" placeholder="Search columns, e.g. active, node_type, tickMs" aria-label="Search columns"><kbd class="ms-find-kbd">/</kbd></div><span class="ms-find-count"></span></div>
<script src="key-find.js"></script>
\endhtmlonly

## 1\. Anatomy

The top of `outputs/examples/03-building-blockage/seed-1/positions.csv`:
`node-a` fixed at the origin, `node-b` driving south at 2 m/s.

\htmlonly
<div class="ms-ini">
<div class="ms-ini-row ms-c-grey">
<pre class="ms-ini-code"># scenario=03-building-blockage
# frequency=28000000000
# txPower=30
# numNodes=2
# simDuration=30000
# tickMs=100
# dimensions=3
# rainRate=0
# channelModel=3gpp
# flowTopology=all_pairs
# trafficModel=constant</pre>
<div class="ms-ini-note"><strong>Run metadata</strong>A 28 GHz, 30 dBm, two-node, 30 s run with a row every 100 ms. The visualizer reads these lines; Python loaders skip them.</div>
</div>
<div class="ms-ini-row ms-c-blue">
<pre class="ms-ini-code"><b>time_s,   node_id</b>
0.000000, 0
0.000000, 1
0.100000, 1</pre>
<div class="ms-ini-note"><strong>Which node, when</strong>One row per node per snapshot, in node order.</div>
</div>
<div class="ms-ini-row ms-c-green">
<pre class="ms-ini-code"><b>x,          y,          z</b>
0.000000,   0.000000,   10.000000
200.000000, 0.000000,   10.000000
200.000000, -0.200000,  10.000000</pre>
<div class="ms-ini-note"><strong>Where it is</strong>Node 0 stays at the origin. Node 1 moves 0.2 m in <code>y</code> per 0.1 s snapshot, 10 m up.</div>
</div>
<div class="ms-ini-row ms-c-amber">
<pre class="ms-ini-code"><b>node_type, active</b>
drone,     1
drone,     1
drone,     1</pre>
<div class="ms-ini-note"><strong>What it is and whether it is online</strong>Neither node sets <code>node_type</code> in <code>nodes.json</code>, so both are <code>drone</code>. Both stay online.</div>
</div>
</div>
\endhtmlonly

- 11 `# key=value` lines, then a header row, then one row per node per
  snapshot, in node order.
- A snapshot is written at t = 0 and then every `[output] viz_tick_ms`.
  `--no-viz` writes no file.
- `time_s`, `x`, `y` and `z` have 6 decimals.

## 2\. Metadata block

Run settings for the visualizer, one `# key=value` line each, copied from
`run.ini` and `nodes.json`:

| Key | From | Unit |
|---|---|---|
| `scenario` | `[scenario] name` | |
| `frequency` | `[channel] frequency_ghz` × 10⁹ | Hz |
| `txPower` | `[channel] tx_power_dbm` | dBm |
| `numNodes` | entries in `nodes.json` | |
| `simDuration` | `[scenario] duration_s` × 1000 | ms |
| `tickMs` | `[output] viz_tick_ms`: the snapshot interval, not the simulation tick | ms |
| `dimensions` | always `3` | |
| `rainRate` | `[nyu_channel] rain_rate_mm_hr`, `0` unless set | mm/h |
| `channelModel` | `[channel] channel_model` | |
| `flowTopology` | `[traffic] flow_topology` | |
| `trafficModel` | `[traffic] model` | |

## 3\. Which node, when

The snapshot time and the node.

<div class="ms-keys ms-c-blue">
<div class="ms-key ms-key-head"><div>Column</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`time_s`<span class="ms-key-def">s</span></div>
<div class="ms-key-what">Sim time of the snapshot.</div>
<div class="ms-key-vals">0 to `duration_s`, 6 decimals</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`node_id`<span class="ms-key-def">integer</span></div>
<div class="ms-key-what">The node's place in `nodes.json`, numbered from 0, as in the other CSVs.</div>
<div class="ms-key-vals">0 to N&minus;1</div>
</div>
</div>

## 4\. Where it is

The node's position in the scenario frame.

<div class="ms-keys ms-c-green">
<div class="ms-key ms-key-head"><div>Column</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`x`, `y`<span class="ms-key-def">m</span></div>
<div class="ms-key-what">Horizontal position.</div>
<div class="ms-key-vals">any, 6 decimals</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`z`<span class="ms-key-def">m</span></div>
<div class="ms-key-what">Height.</div>
<div class="ms-key-vals">any, 6 decimals</div>
</div>
</div>

## 5\. Type and state

What kind of node it is and whether it is online.

<div class="ms-keys ms-c-amber">
<div class="ms-key ms-key-head"><div>Column</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`node_type`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">`node_type` from \ref files_nodes_json "nodes.json"; `drone` when not set.</div>
<div class="ms-key-vals">`drone`, `vehicle`, `pedestrian`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`active`<span class="ms-key-def">flag</span></div>
<div class="ms-key-what">`0` from the node's `failure_at_s` on, else `1`.<div class="ms-key-note">Only mission recovery scenarios set `failure_at_s`.</div></div>
<div class="ms-key-vals">`1`, `0`</div>
</div>
</div>

A failed node stays in the file at its last position. Its links read `-999`
in \ref files_links_csv "links.csv".

## 6\. Reading it

| Normal | A problem |
|---|---|
| `fixed` nodes keep the same coordinates on every row. | A node stops partway with `active = 0`: it passed its `failure_at_s`. |
| Moving nodes step by speed &times; snapshot interval. | A node stops with `active = 1`: a waypoint or the RL policy stopped it. |
| `active` is `1` throughout outside recovery missions. | `read_csv` fails on the first line: pass `comment="#"`. |

Run metadata and each node's mean speed
(`outputs/examples/03-building-blockage`):

```python
import pandas as pd

p = "outputs/examples/03-building-blockage/seed-1/positions.csv"
meta = dict(line[2:].strip().split("=", 1) for line in open(p) if line.startswith("#"))
pos = pd.read_csv(p, comment="#").sort_values(["node_id", "time_s"])
step = pos.groupby("node_id")[["x", "y", "z"]].diff()
pos["speed_mps"] = (step ** 2).sum(axis=1) ** 0.5 / pos.groupby("node_id").time_s.diff()
print(meta["tickMs"], pos.groupby("node_id").speed_mps.mean().round(2).to_dict())
```

```text
100 {0: 0.0, 1: 2.0}
```

When each node went offline (a nine-node mission recovery run,
`failure_at_s = 10` for three drones):

```python
pos = pd.read_csv(".../seed-201/positions.csv", comment="#")
print(pos[pos.active == 0].groupby("node_id").time_s.min())
```

```text
node_id
1    10.0
4    10.0
7    10.0
```

## 7\. Related

- \ref files_nodes_json "nodes.json": start positions, mobility, `node_type`, `failure_at_s`
- \ref files_links_csv "links.csv": distance and LOS between these positions
- \ref files_figures "Figures": the `geometry` plot made from this file

Previous: \ref files_routes_csv "routes.csv" · Up: \ref mesh_sim_files "Input and output files" · Next: \ref files_rx_power_csv "rx-power.csv"
