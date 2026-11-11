# summary.json {#files_summary_json}

[TOC]

`summary.json` holds one seed's results as time averages: per node, per flow
and for the whole network, over every simulation tick after `warmup_s`,
including ticks the CSVs skip. The simulator writes it once per seed to
`<output-dir>/seed-N/summary.json`, with or without `--no-viz`. The plotting,
sweep, placement-baseline and RL evaluation scripts and the regression
snapshot read it.

\htmlonly
<div class="ms-find" data-noun="key"><div class="ms-find-field"><svg class="ms-find-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg><input type="search" placeholder="Search keys, e.g. connectivity, latency_ms, wall" aria-label="Search keys"><kbd class="ms-find-kbd">/</kbd></div><span class="ms-find-count"></span></div>
<script src="key-find.js"></script>
\endhtmlonly

## 1\. Anatomy

`outputs/examples/07-three-node-relay/seed-1/summary.json`: three nodes in a
line 500 m apart, a 10 Mbps flow between every pair, 51 ticks (0 to 5 s, no
warmup). At `t = 0` every flow is routed; from `t = 0.1` the `relay`–`node-c`
link is at −9.7 dB, so the two flows to `node-c` are unroutable for 50 of the
51 ticks. Two entries are cut to `{ ... }`.

\htmlonly
<div class="ms-ini">
<div class="ms-ini-row ms-c-blue">
<pre class="ms-ini-code">{
  "duration_s": 5.0,</pre>
<div class="ms-ini-note"><strong>Top level</strong>A 5 s run. Keys are in alphabetical order, so the rest of the top-level keys follow the three objects.</div>
</div>
<div class="ms-ini-row ms-c-green">
<pre class="ms-ini-code">  <b>"network"</b>: {
    "connectivity": 0.33986928104575165,
    "flows_routed": 1.0392156862745099,
    "flows_unroutable": 1.9607843137254901,
    "mean_hop_count": 1.0188679245283019,
    "mean_sinr_db": -6.507960075100598,
    "sum_throughput_mbps": 10.392156862745098
  },</pre>
<div class="ms-ini-note"><strong>Whole network</strong>About one flow of three routed per tick, 10.4 Mbps delivered in total, and a third of node pairs connected.</div>
</div>
<div class="ms-ini-row ms-c-amber">
<pre class="ms-ini-code">  <b>"per_flow"</b>: {
    "node-a-&gt;node-c": {
      "delivered_mbps": 0.19607843137254902,
      "demand_mbps": 10.0,
      "hop_count": 0.0392156862745098,
      "latency_ms": 0.019673202614379087
    },
    "node-a-&gt;relay": {
      "delivered_mbps": 10.0,
      "demand_mbps": 10.0,
      "hop_count": 1.0,
      "latency_ms": 0.5016666666666662
    },
    "relay-&gt;node-c": { ... }
  },</pre>
<div class="ms-ini-note"><strong>Each flow</strong><code>node-a-&gt;relay</code> got its full 10 Mbps over one hop on every tick. <code>node-a-&gt;node-c</code> was routed on one tick of 51, so every mean is 1/51 of its routed value.</div>
</div>
<div class="ms-ini-row ms-c-purple">
<pre class="ms-ini-code">  <b>"per_node"</b>: {
    "node-a": {
      "max_sinr_db": 21.609056151272284,
      "mean_sinr_db": -5.138700571664704,
      "min_sinr_db": -31.954419463937057,
      "num_links": 1.0,
      "num_los_links": 1.0,
      "rx_throughput_mbps": 0.0,
      "tx_throughput_mbps": 10.196078431372548
    },
    "node-c": { ... },
    "relay": { ... }
  },</pre>
<div class="ms-ini-note"><strong>Each node</strong><code>node-a</code> kept one connected LOS link, to <code>relay</code>, all run. Its mean SINR averages that 21.6 dB link with the &minus;28 to &minus;32 dB link to <code>node-c</code>. It receives no traffic.</div>
</div>
<div class="ms-ini-row ms-c-blue">
<pre class="ms-ini-code">  "scenario": "07-three-node-relay",
  "seed": 1,
  "wall_clock_end": "2026-10-27T17:32:47Z",
  "wall_clock_start": "2026-10-27T17:32:47Z",
  "wall_elapsed_s": 0.027516,
  "warmup_s": 0.0
}</pre>
<div class="ms-ini-note"><strong>Top level, continued</strong>Scenario name and seed, the seed's wall-clock time (0.03 s), and no warmup.</div>
</div>
</div>
\endhtmlonly

**Format.** JSON, 2-space indent, keys in alphabetical order at every level.
Numbers are full double precision. The file is written after the seed's last
tick; a seed that crashes leaves none. A seed folder that cannot be written
leaves none either: the console shows `[MetricsWriter] ERROR: cannot write
<path>` and the run still exits 0.

**What the averages count.** Call the number of counted ticks <em>T</em>.

| Term | Meaning |
|---|---|
| Counted tick | Every simulation tick with `time_s >= warmup_s` (the tick at exactly `warmup_s` counts). `viz_tick_ms` does not apply. A run has `floor(duration_s / tick_s) + 1` ticks in all, starting at `t = 0`. |
| Valid SINR sample | A link sample with `sinr_db` above −900 dB. Links to a node after its `failure_at_s` carry the −999 dB sentinel and are skipped. |
| Connected link | `sinr_db >= -6.7` dB, the lowest SINR that gives non-zero capacity. |

## 2\. Top level

The run's identity and timing, plus the three objects in sections 3 to 5.

<div class="ms-keys ms-c-blue">
<div class="ms-key ms-key-head"><div>Key</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`duration_s`<span class="ms-key-def">s</span></div>
<div class="ms-key-what">`[scenario] duration_s`.</div>
<div class="ms-key-vals">&gt; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`scenario`<span class="ms-key-def">text</span></div>
<div class="ms-key-what">`[scenario] name`.</div>
<div class="ms-key-vals">any text</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`seed`<span class="ms-key-def">integer</span></div>
<div class="ms-key-what">The seed of this folder.</div>
<div class="ms-key-vals">&ge; 1</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`wall_clock_end`<span class="ms-key-def">UTC text</span></div>
<div class="ms-key-what">Wall clock after the last tick.</div>
<div class="ms-key-vals">`YYYY-MM-DDTHH:MM:SSZ`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`wall_clock_start`<span class="ms-key-def">UTC text</span></div>
<div class="ms-key-what">Wall clock just before the seed's topology was built.</div>
<div class="ms-key-vals">`YYYY-MM-DDTHH:MM:SSZ`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`wall_elapsed_s`<span class="ms-key-def">s</span></div>
<div class="ms-key-what">Wall time between the two.<div class="ms-key-note">The three `wall_*` keys are omitted when it is 0. The regression snapshot keeps every key except these three.</div></div>
<div class="ms-key-vals">&gt; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`warmup_s`<span class="ms-key-def">s</span></div>
<div class="ms-key-what">Ticks before this time are left out of every average in the file.</div>
<div class="ms-key-vals">0 to below `duration_s`</div>
</div>
</div>

## 3\. network

Whole-network averages over <em>T</em> counted ticks.

<div class="ms-keys ms-c-green">
<div class="ms-key ms-key-head"><div>Key</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`connectivity`<span class="ms-key-def">fraction</span></div>
<div class="ms-key-what">Connected node pairs summed over ticks, divided by N(N−1)/2 × <em>T</em>.<div class="ms-key-note">Low means many pairs below −6.7 dB. Multi-hop routing can still serve every flow.</div></div>
<div class="ms-key-vals">0 to 1</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`flows_routed`<span class="ms-key-def">flows</span></div>
<div class="ms-key-what">Routable flow observations divided by <em>T</em>: mean routed flows per tick.</div>
<div class="ms-key-vals">&ge; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`flows_unroutable`<span class="ms-key-def">flows</span></div>
<div class="ms-key-what">Unroutable flow observations divided by <em>T</em>.<div class="ms-key-note">Includes flows with zero demand this tick (an `on_off` OFF phase), which the router does not route, so `on_off` traffic shows a value above 0 even with every link strong. `demand_mbps` in \ref files_flows_csv "flows.csv" tells them apart.</div></div>
<div class="ms-key-vals">&ge; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`mean_hop_count`<span class="ms-key-def">hops</span></div>
<div class="ms-key-what">Mean `hop_count` over routable observations only. `0` when nothing was routed.<div class="ms-key-note">It skips unroutable observations; the `per_flow` means count them as 0, so the two disagree when flows lose their route.</div></div>
<div class="ms-key-vals">0, or 1 to N−1</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`mean_sinr_db`<span class="ms-key-def">dB</span></div>
<div class="ms-key-what">Mean of every valid SINR sample of every link (each link counted from both ends), over <em>T</em> ticks.<div class="ms-key-note">It includes links no flow uses, so long NLOS pairs can make it low or negative while every flow is served. `null` when no sample is valid.</div></div>
<div class="ms-key-vals">any number, or `null`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`sum_throughput_mbps`<span class="ms-key-def">Mbps</span></div>
<div class="ms-key-what">Sum of `delivered_mbps` over every flow observation, divided by <em>T</em>: the mean total traffic delivered per tick.</div>
<div class="ms-key-vals">&ge; 0</div>
</div>
</div>

## 4\. per_flow

One entry per source–destination pair, keyed `"<src id>-><dst id>"` with the
`nodes.json` ids. Two flows with the same pair (two `explicit_pairs` entries,
or Poisson arrivals) share one entry, so there can be fewer entries than flows;
\ref files_flows_csv "flows.csv" has the individual flows. Each value is a mean
over the pair's observations: one per flow per counted tick in which the flow
existed. For `constant` and `on_off` traffic that is <em>T</em>.

<div class="ms-keys ms-c-amber">
<div class="ms-key ms-key-head"><div>Key</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`delivered_mbps`<span class="ms-key-def">Mbps</span></div>
<div class="ms-key-what">Mean delivered rate after congestion scaling. Unroutable observations count as 0.</div>
<div class="ms-key-vals">0 to `demand_mbps`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`demand_mbps`<span class="ms-key-def">Mbps</span></div>
<div class="ms-key-what">Mean effective demand. `on_off` OFF phases count as 0.</div>
<div class="ms-key-vals">&ge; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`hop_count`<span class="ms-key-def">hops</span></div>
<div class="ms-key-what">Mean hop count. Unroutable observations count as 0.<div class="ms-key-note">Not a whole number when the route changed or the flow was unroutable part of the time; \ref files_routes_csv "routes.csv" has the paths.</div></div>
<div class="ms-key-vals">0 to N−1</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`latency_ms`<span class="ms-key-def">ms</span></div>
<div class="ms-key-what">Mean path latency. Unroutable observations count as 0.<div class="ms-key-note">A flow that is often unroutable shows a latency below its one-hop value of about 0.5 ms. Section 6 shows the mean over routed ticks only.</div></div>
<div class="ms-key-vals">&ge; 0</div>
</div>
</div>

## 5\. per_node

One entry per node, keyed by its `nodes.json` id. Averages over <em>T</em>
counted ticks.

<div class="ms-keys ms-c-purple">
<div class="ms-key ms-key-head"><div>Key</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`max_sinr_db`<span class="ms-key-def">dB</span></div>
<div class="ms-key-what">Highest valid SINR sample of this node's links.</div>
<div class="ms-key-vals">any number, or `null`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`mean_sinr_db`<span class="ms-key-def">dB</span></div>
<div class="ms-key-what">Mean of the dB values of every valid sample of this node's links to every other node, over <em>T</em> ticks. Averaged in dB.<div class="ms-key-note">`null`, like the min and max, when no sample is valid after warmup: check `warmup_s` and node failures.</div></div>
<div class="ms-key-vals">any number, or `null`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`min_sinr_db`<span class="ms-key-def">dB</span></div>
<div class="ms-key-what">Lowest valid SINR sample of this node's links.</div>
<div class="ms-key-vals">any number, or `null`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`num_links`<span class="ms-key-def">links</span></div>
<div class="ms-key-what">Connected links of this node, summed over ticks, divided by <em>T</em>.</div>
<div class="ms-key-vals">0 to N−1</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`num_los_links`<span class="ms-key-def">links</span></div>
<div class="ms-key-what">LOS links of this node, whatever their SINR, summed over ticks, divided by <em>T</em>.</div>
<div class="ms-key-vals">0 to N−1</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rx_throughput_mbps`<span class="ms-key-def">Mbps</span></div>
<div class="ms-key-what">Sum of `delivered_mbps` of every flow this node sinks, over all counted ticks, divided by <em>T</em>.</div>
<div class="ms-key-vals">&ge; 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`tx_throughput_mbps`<span class="ms-key-def">Mbps</span></div>
<div class="ms-key-what">Sum of `delivered_mbps` of every flow this node sources, over all counted ticks, divided by <em>T</em>. Several flows from one node add up.</div>
<div class="ms-key-vals">&ge; 0</div>
</div>
</div>

The per-tick values behind these averages: \ref files_links_csv "links.csv"
(SINR, LOS, capacity) and \ref files_flows_csv "flows.csv" (demand, delivered,
latency, hops, routable).

## 6\. Reading it

| Key | Healthy | Problem |
|---|---|---|
| `per_flow.*.delivered_mbps` | Equal to `demand_mbps` | Below it: unroutable ticks or a congested link. |
| `network.flows_unroutable` | `0.0` | Above 0: some flows had no path (or no demand) on some ticks. |
| `network.connectivity` | Near 1.0 for nodes a few hundred metres apart | Low: many pairs below −6.7 dB. |
| `per_node.*.mean_sinr_db` | Well above −6.7 dB | Near or below it: the node is mostly cut off. |
| `per_flow.*.latency_ms` | About 0.5 ms × hops | Below 0.5 ms: the flow was unroutable part of the time. |

How the anatomy's numbers come out of the 51 ticks:

| Key | Arithmetic | Reading |
|---|---|---|
| `per_flow["node-a->node-c"].delivered_mbps` | (10 × 1 tick + 0 × 50 ticks) / 51 = 0.196 | Served for one tick out of 51. |
| `per_flow["node-a->node-c"].latency_ms` | (1.003 × 1 + 0 × 50) / 51 = 0.0197 | Unroutable ticks count as 0 ms. The flow's 2-hop latency is 1.003 ms. |
| `per_flow["node-a->node-c"].hop_count` | (2 × 1 + 0 × 50) / 51 = 0.039 | Unroutable ticks count as 0 hops. |
| `network.mean_hop_count` | (51 × 1 + 1 × 2 + 1 × 1) / 53 routed observations = 1.019 | Unroutable observations are left out. |
| `network.connectivity` | (2 + 50 × 1) connected pairs / (51 × 3) pairs = 0.340 | |
| `network.flows_routed` | (3 + 50 × 1) / 51 = 1.039 | Mean routed flows per tick. |
| `per_node["node-c"].num_links` | 1 connected link at `t = 0`, then 0: 1 / 51 = 0.0196 | |

Averages of the CSV rows differ from these values: `summary.json` uses every
tick after `warmup_s`, while the CSVs hold every `viz_tick_ms` snapshot,
warmup included. To match them, filter the CSV to `time_s >= warmup_s` and set
`viz_tick_ms` to the tick length.

Rank flows by how much of their demand they got:

```python
import json
import pandas as pd

s = json.load(open("outputs/examples/07-three-node-relay/seed-1/summary.json"))
flows = pd.DataFrame(s["per_flow"]).T
flows["delivery_ratio"] = flows.delivered_mbps / flows.demand_mbps
print(flows.sort_values("delivery_ratio").round(3))
```

```text
                delivered_mbps  demand_mbps  hop_count  latency_ms  delivery_ratio
node-a->node-c           0.196         10.0      0.039       0.020            0.02
relay->node-c            0.196         10.0      0.020       0.010            0.02
node-a->relay           10.000         10.0      1.000       0.502            1.00
```

Network numbers across seeds:

```python
import glob, json
import pandas as pd

run = "outputs/examples/16-random-walk-urban"
net = pd.DataFrame({p.split("/")[-2]: json.load(open(p))["network"]
                    for p in sorted(glob.glob(f"{run}/seed-*/summary.json"))}).T
print(net.agg(["mean", "std"]))
```

Latency over only the ticks a flow was routed comes from `flows.csv`:

```python
f = pd.read_csv("outputs/examples/07-three-node-relay/seed-1/flows.csv")
print(f[f.routable == 1].groupby(["src", "dst"]).latency_ms.mean())
```

## 7\. Related

- \ref files_flows_csv "flows.csv": the per-tick flow rows behind `per_flow` and `network`.
- \ref files_links_csv "links.csv": the per-tick link rows behind `per_node` and the SINR averages.
- \ref files_figures "Figures": the per-node, per-flow, network and runtime plots made from this file, with the mean and 95% CI across seeds.
- \ref src_io_timing "Sampling and warmup": which ticks each output covers.
- \ref src_io_output "Output files": `MetricsWriter` in `src/io/metrics-writer.cc` writes this file: `AccumulateTick` every tick, `Write` once after the last tick.
- \ref src_routing "src/routing": routability, congestion scaling, latency.
- \ref scripts_sweep "scripts/sweep": `--resume` treats a point as done when every `seed-N/summary.json` exists.
- \ref scripts_baselines "scripts/baselines": reads it for per-seed status. `scripts/rl/policy/evaluate.py` records its path.
- \ref scripts_validation "scripts/validation": the regression snapshot keeps every key except `wall_*`.

Previous: \ref files_run_log "run.log" · Up: \ref mesh_sim_files "Input and output files" · Next: \ref files_links_csv "links.csv"
