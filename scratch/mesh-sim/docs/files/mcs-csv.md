# mcs.csv {#files_mcs_csv}

[TOC]

`mcs.csv` has one row per node pair per saved tick: the highest modulation
and coding scheme (MCS) index the link's SINR supports. Traffic load does not
change it. Each seed writes its own, in `seed-N/mcs.csv`.

\htmlonly
<div class="ms-find" data-noun="column"><div class="ms-find-field"><svg class="ms-find-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg><input type="search" placeholder="Search columns, e.g. mcs_index, spectral_eff, node_b" aria-label="Search columns"><kbd class="ms-find-kbd">/</kbd></div><span class="ms-find-count"></span></div>
<script src="key-find.js"></script>
\endhtmlonly

## 1\. Anatomy

Three rows of `outputs/examples/14-max-hops-limit/seed-1/mcs.csv` at
`t = 0.1`, split by column group: five nodes in a line 200 m apart,
`amc_model` left at its default (`shannon`).

\htmlonly
<div class="ms-ini">
<div class="ms-ini-row ms-c-blue">
<pre class="ms-ini-code"><b>time_s,   node_a, node_b</b>
0.100000, 0,      1
0.100000, 0,      3
0.100000, 0,      4</pre>
<div class="ms-ini-note"><strong>Which pair, when</strong>Node 0 to its neighbour 200 m away, to node 3 at 600 m, and to node 4 at 800 m.</div>
</div>
<div class="ms-ini-row ms-c-purple">
<pre class="ms-ini-code"><b>mcs_index, spectral_eff</b>
7,         1.91
1,         0.23
0,         0.15</pre>
<div class="ms-ini-note"><strong>The MCS level</strong>9.57 dB SINR gives CQI 7, 16QAM. &minus;3.55 dB gives CQI 1, still usable at 211.1 Mbps. &minus;28.07 dB has no capacity and still reads <code>0</code>.</div>
</div>
</div>
\endhtmlonly

- Same rows, same order as \ref files_links_csv "links.csv":
  \f$ N(N-1)/2 \f$ per snapshot.
- A snapshot is written at t = 0 and then every `[output] viz_tick_ms`.
  `--no-viz` writes no file.
- `spectral_eff` has 2 decimals, `time_s` 6.

## 2\. Which pair, when

The snapshot time and the two nodes.

<div class="ms-keys ms-c-blue">
<div class="ms-key ms-key-head"><div>Column</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`time_s`<span class="ms-key-def">s</span></div>
<div class="ms-key-what">Sim time of the snapshot.<div class="ms-key-note">A static pair's `t = 0` index can differ from later rows; skip it for the steady value.</div></div>
<div class="ms-key-vals">0 to `duration_s`, 6 decimals</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`node_a`<span class="ms-key-def">integer</span></div>
<div class="ms-key-what">The node listed first in `nodes.json`, numbered from 0.</div>
<div class="ms-key-vals">0 to N&minus;2</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`node_b`<span class="ms-key-def">integer</span></div>
<div class="ms-key-what">The node listed later.</div>
<div class="ms-key-vals">`node_a + 1` to N&minus;1</div>
</div>
</div>

## 3\. MCS level

The index `sinr_db` in \ref files_links_csv "links.csv" reaches, on the ladder
`amc_model` selects.

<div class="ms-keys ms-c-purple">
<div class="ms-key ms-key-head"><div>Column</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`mcs_index`<span class="ms-key-def">integer</span></div>
<div class="ms-key-what">The highest level whose SINR threshold `sinr_db` reaches.<div class="ms-key-note">`0` also means no link: check `capacity_mbps` in `links.csv`.</div></div>
<div class="ms-key-vals">0&ndash;15 (`shannon`, `table`); 0&ndash;6 (`silvus`)</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`spectral_eff`<span class="ms-key-def">bit/s/Hz</span></div>
<div class="ms-key-what">The 3GPP CQI efficiency at row `mcs_index`, for every `amc_model`.<div class="ms-key-note">Under `silvus` the Silvus table below gives the real rate.</div></div>
<div class="ms-key-vals">0.15&ndash;6.23, 2 decimals</div>
</div>
</div>

\image html mcs-ladder.svg "mcs_index against sinr_db for the two index ladders. Below −6.7 dB the index stays 0 while capacity is 0."

### 3GPP CQI table (`amc_model = shannon` or `table`)

From 3GPP TS 38.214 Table 5.1.3.1-1, the same thresholds as ns3-mmwave's AMC.

| `mcs_index` | Modulation | SINR threshold (dB) | `spectral_eff` |
|---|---|---|---|
| 0 | QPSK | −6.7 | 0.15 |
| 1 | QPSK | −4.7 | 0.23 |
| 2 | QPSK | −2.3 | 0.38 |
| 3 | QPSK | 0.2 | 0.60 |
| 4 | QPSK | 2.4 | 0.88 |
| 5 | QPSK | 4.3 | 1.18 |
| 6 | 16QAM | 5.9 | 1.48 |
| 7 | 16QAM | 8.1 | 1.91 |
| 8 | 16QAM | 10.3 | 2.41 |
| 9 | 16QAM | 11.7 | 2.73 |
| 10 | 64QAM | 14.1 | 3.32 |
| 11 | 64QAM | 16.3 | 3.90 |
| 12 | 64QAM | 18.7 | 4.52 |
| 13 | 64QAM | 21.0 | 5.12 |
| 14 | 64QAM | 22.7 | 5.55 |
| 15 | 256QAM | 25.0 | 6.23 |

With `table`, `capacity_mbps` in `links.csv` = `spectral_eff` × bandwidth.
With `shannon`, capacity is B·log2(1 + SINR) and the index is reported
alongside it.

### Silvus table (`amc_model = silvus`)

Single-stream levels of the Silvus radio. Each SINR threshold is the 3GPP
threshold of the nearest spectral efficiency.

| `mcs_index` | Modulation, code rate | SINR threshold (dB) | PHY rate at 20 MHz (Mbps) | Silvus bit/s/Hz | `spectral_eff` written |
|---|---|---|---|---|---|
| 0 | BPSK 1/2 | −6.7 | 6.5 | 0.50 | 0.15 |
| 1 | QPSK 1/2 | 2.4 | 13 | 1.00 | 0.23 |
| 2 | QPSK 3/4 | 5.9 | 19.5 | 1.50 | 0.38 |
| 3 | 16QAM 1/2 | 8.1 | 26 | 2.00 | 0.60 |
| 4 | 16QAM 3/4 | 11.7 | 39 | 3.00 | 0.88 |
| 5 | 64QAM 2/3 | 16.3 | 52 | 4.00 | 1.18 |
| 6 | 64QAM 3/4 | 18.7 | 58.5 | 4.50 | 1.48 |

`capacity_mbps` = PHY rate × bandwidth / 20 MHz.

## 4\. Reading it

| Normal | A problem |
|---|---|
| The index tracks `sinr_db` step for step. | `0` with `capacity_mbps > 0`: a weak but usable link (&minus;6.7 to &minus;4.7 dB for CQI, &minus;6.7 to 2.4 dB for Silvus). |
| Static pairs hold one index from the second snapshot. | `0` with `capacity_mbps = 0`: no link, or a node has dropped out. |
| Long or NLOS pairs sit at `0`; short LOS pairs at `15`. | Sim index above field MCS: the sim reports the SINR ceiling, field radios pick MCS by load. |

Join with `links.csv` to tell the two kinds of `0` apart, and count how often
each pair sat at each index (`outputs/examples/14-max-hops-limit`):

```python
import pandas as pd

d = "outputs/examples/14-max-hops-limit/seed-1"
m = pd.read_csv(f"{d}/mcs.csv").merge(pd.read_csv(f"{d}/links.csv"),
                                      on=["time_s", "node_a", "node_b"])
m["usable"] = m.capacity_mbps > 0
print(m.groupby(["node_a", "node_b"]).agg(mcs=("mcs_index", "median"),
                                          usable=("usable", "mean")))
print(m.groupby(["node_a", "node_b"]).mcs_index.value_counts(normalize=True)
       .unstack(fill_value=0).round(2))
```

```text
               mcs  usable
node_a node_b
0      1       7.0     1.0
       2       4.0     1.0
       3       1.0     1.0
       4       0.0     0.0
...
mcs_index        0     1     2     3     4     5     6     7
node_a node_b
0      1       0.0  0.00  0.00  0.00  0.00  0.00  0.00  1.00
       2       0.0  0.00  0.00  0.02  0.98  0.00  0.00  0.00
...
```

## 5\. Related

- \ref files_links_csv "links.csv": `sinr_db` and `capacity_mbps` for the same pairs
- \ref files_channel_capacity "SINR and capacity": `amc_model` and the CQI cut-off
- \ref files_run_ini "run.ini": `[channel] amc_model` and `bandwidth_mhz`
- \ref files_figures "Figures": the `mcs_timeseries` plot

Previous: \ref files_rx_power_csv "rx-power.csv" · Up: \ref mesh_sim_files "Input and output files" · Next: \ref files_figures "Figures"
