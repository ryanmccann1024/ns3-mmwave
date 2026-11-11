# rx-power.csv {#files_rx_power_csv}

[TOC]

`rx-power.csv` has one row per node pair per saved tick: the power received
from the other node, before noise and jammers. Each seed writes its own, in
`seed-N/rx-power.csv`.

\htmlonly
<div class="ms-find" data-noun="column"><div class="ms-find-field"><svg class="ms-find-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg><input type="search" placeholder="Search columns, e.g. rx_power_dbm, node_a, time_s" aria-label="Search columns"><kbd class="ms-find-kbd">/</kbd></div><span class="ms-find-count"></span></div>
<script src="key-find.js"></script>
\endhtmlonly

## 1\. Anatomy

Three rows of `outputs/examples/03-building-blockage/seed-1/rx-power.csv`,
split by column group. Node 1 drives out from behind a building.

\htmlonly
<div class="ms-ini">
<div class="ms-ini-row ms-c-blue">
<pre class="ms-ini-code"><b>time_s,    node_a, node_b</b>
22.100000, 0,      1
22.200000, 0,      1
22.300000, 0,      1</pre>
<div class="ms-ini-note"><strong>Which pair, when</strong>The only pair, nodes 0 and 1, at three consecutive snapshots.</div>
</div>
<div class="ms-ini-row ms-c-purple">
<pre class="ms-ini-code"><b>rx_power_dbm</b>
-68.938656
-68.138520
-53.622316</pre>
<div class="ms-ini-note"><strong>The received power</strong>At <code>t = 22.3</code> the link turns LOS and the received power jumps 14.5 dB.</div>
</div>
</div>
\endhtmlonly

- Same rows, same order as \ref files_links_csv "links.csv":
  \f$ N(N-1)/2 \f$ per snapshot.
- A snapshot is written at t = 0 and then every `[output] viz_tick_ms`.
  `--no-viz` writes no file.
- Every number has 6 decimals.

## 2\. Which pair, when

The snapshot time and the two nodes of the pair.

<div class="ms-keys ms-c-blue">
<div class="ms-key ms-key-head"><div>Column</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`time_s`<span class="ms-key-def">s</span></div>
<div class="ms-key-what">Sim time of the snapshot.<div class="ms-key-note">A static pair's `t = 0` value differs from later rows; skip it for the steady value.</div></div>
<div class="ms-key-vals">0 to `duration_s`, 6 decimals</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`node_a`<span class="ms-key-def">integer</span></div>
<div class="ms-key-what">The node listed first in `nodes.json`, numbered from 0. It transmits.</div>
<div class="ms-key-vals">0 to N&minus;2</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`node_b`<span class="ms-key-def">integer</span></div>
<div class="ms-key-what">The node listed later. It receives.</div>
<div class="ms-key-vals">`node_a + 1` to N&minus;1</div>
</div>
</div>

## 3\. Received power

The mesh signal at `node_b`.

<div class="ms-keys ms-c-purple">
<div class="ms-key ms-key-head"><div>Column</div><div>What it means</div><div>Unit and range</div></div>
<div class="ms-key">
<div class="ms-key-name">`rx_power_dbm`<span class="ms-key-def">dBm</span></div>
<div class="ms-key-what">Transmit power minus path loss plus both antenna gains.<div class="ms-key-note">How it is worked out: \ref files_channel_models "Channel models". `-999` means a node on the link has dropped out.</div></div>
<div class="ms-key-vals">6 decimals; `-999` sentinel</div>
</div>
</div>

Example, `outputs/getting-started/01-static-los-baseline` at 100 m:
30 dBm + 12 dBi + 12 dBi &minus; 102.33 dB = &minus;48.33 dBm. Noise and jammer
power enter only `sinr_db` in \ref files_links_csv "links.csv".

## 4\. Reading it

| Normal | A problem |
|---|---|
| Static pairs constant from the second snapshot. | Strong received power with low `sinr_db`: a jammer (`sub-6` only). |
| A LOS/NLOS change shows as a step (14.5 dB in the anatomy). | `-999` rows: a node has dropped out (`active = 0` in \ref files_positions_csv "positions.csv"). |
| Without a jammer, a link has capacity at `rx_power_dbm` &ge; &minus;89.68 dBm (400 MHz, 5 dB noise figure). | |

`rx_power_dbm − sinr_db` is the noise-plus-jammer power at the receiver. It
equals the noise floor on every row without a jammer
(`outputs/examples/p0-jammer-smoke`, `sub-6`, one constant jammer):

```python
import math
import pandas as pd

d = "outputs/examples/p0-jammer-smoke/seed-1"
noise_dbm = -174 + 10 * math.log10(400e6) + 5.0          # bandwidth_mhz, noise_figure_db
m = pd.read_csv(f"{d}/rx-power.csv").merge(pd.read_csv(f"{d}/links.csv"),
                                           on=["time_s", "node_a", "node_b"])
m["jam_db"] = (m.rx_power_dbm - m.sinr_db) - noise_dbm   # 0 when no jammer
print(m[m.time_s == 0.1][["node_a", "node_b", "rx_power_dbm", "sinr_db", "jam_db"]].round(2))
```

```text
   node_a  node_b  rx_power_dbm  sinr_db  jam_db
3       0       1        -31.73     3.27   47.98
4       0       2        -23.23    -2.04   61.79
5       1       2        -23.04    -1.85   61.79
```

The jammer raises the interference-plus-noise level by 48 to 62 dB, turning
links with &minus;23 dBm of signal into &minus;2 dB SINR.

## 5\. Related

- \ref files_links_csv "links.csv": `sinr_db` and `capacity_mbps` for the same pairs
- \ref files_channel_models "Channel models": path loss, gains and the full link budget
- \ref files_nodes_json "nodes.json": per-node antenna gains
- \ref files_jammers_json "jammers.json": the jammers behind a low `sinr_db`

Previous: \ref files_positions_csv "positions.csv" · Up: \ref mesh_sim_files "Input and output files" · Next: \ref files_mcs_csv "mcs.csv"
