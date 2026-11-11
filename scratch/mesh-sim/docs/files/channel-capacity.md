# SINR and capacity {#files_channel_capacity}

[TOC]

The last steps for every link: path loss becomes received power and SINR, and
`amc_model` turns SINR into a rate and an MCS.

\htmlonly
<div class="ms-find" data-noun="step"><div class="ms-find-field"><svg class="ms-find-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg><input type="search" placeholder="Search, e.g. noise, silvus, CQI" aria-label="Search steps"><kbd class="ms-find-kbd">/</kbd></div><span class="ms-find-count"></span></div>
<script src="key-find.js"></script>
\endhtmlonly

## 1\. From path loss to SINR

`src/eval/link-evaluator.cc` runs these steps for each unordered node pair,
once per tick.

<div class="ms-keys ms-c-green">
<div class="ms-key ms-key-head"><div>Step</div><div>Rule</div><div>Set by</div></div>
<div class="ms-key">
<div class="ms-key-name">`path_loss_db`<span class="ms-key-def">dB</span></div>
<div class="ms-key-what">\f$ \max\big(PL_{model},\ FSPL\big) \f$, with \f$ FSPL = 20\log_{10} d + 20\log_{10} f_{\mathrm{Hz}} - 147.55 \f$ dB at \f$ d = \max(d_{3D}, 1\,\mathrm{m}) \f$.<div class="ms-key-note">A non-finite model value (d = 0) is replaced by the free-space loss. The floor binds on short links, NYU n = 2 LOS links and negative shadowing draws; SINR then equals the free-space value, the highest the link can reach.</div></div>
<div class="ms-key-vals">`channel_model`, `scenario`, `frequency_ghz`, `[nyu_channel]`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rx_power_dbm`<span class="ms-key-def">dBm</span></div>
<div class="ms-key-what">`tx_power_dbm` − `path_loss_db` + transmit gain + receive gain.<div class="ms-key-note">The gains are fixed peak gains: no pattern, pointing or misalignment. A node's own gains in \ref files_nodes_json "nodes.json" replace the `[channel]` ones. A pair is evaluated once, with the node listed earlier in `nodes.json` as transmitter: transmit gain of the earlier node plus receive gain of the later one, and both directions use that result.</div></div>
<div class="ms-key-vals">`tx_power_dbm`, `tx_array_gain_dbi`, `rx_array_gain_dbi`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">noise floor<span class="ms-key-def">dBm</span></div>
<div class="ms-key-what">\f$ -174 + 10\log_{10} B_{\mathrm{Hz}} + NF \f$ dBm, from `bandwidth_mhz` and `noise_figure_db` (table below).</div>
<div class="ms-key-vals">`bandwidth_mhz`, `noise_figure_db`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`sinr_db`<span class="ms-key-def">dB</span></div>
<div class="ms-key-what">`rx_power_dbm` − noise floor.<div class="ms-key-note">With `band = sub-6` and an active jammer, the jammer power received at the worse of the two ends joins the noise (\ref files_jammers_json "jammers.json").</div></div>
<div class="ms-key-vals">`band`, `jammers_file`</div>
</div>
</div>

| `bandwidth_mhz` | Noise floor at `noise_figure_db = 5` |
|---|---|
| 20 | −96.0 dBm |
| 100 | −89.0 dBm |
| 400 | −83.0 dBm |
| 800 | −80.0 dBm |

## 2\. amc_model: SINR to capacity and MCS

`SinrToCapacity`, `SinrToMcsIndex` and `SinrToSilvusMcsIndex` in
`src/eval/sinr-capacity.h` turn `sinr_db` into `capacity_mbps` and the MCS in
`mcs.csv`. The MCS is the highest entry whose SINR threshold is at or below the
link's SINR.

<div class="ms-keys ms-c-amber">
<div class="ms-key ms-key-head"><div>amc_model</div><div>capacity_mbps</div><div>MCS and maximum at 400 MHz</div></div>
<div class="ms-key">
<div class="ms-key-name">`shannon`<span class="ms-key-def">default</span></div>
<div class="ms-key-what">\f$ C = B\log_2\left(1 + 10^{SINR/10}\right) \f$.</div>
<div class="ms-key-vals">CQI 0–15<br>no maximum (5,300 Mbps at 40 dB)</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`table`</div>
<div class="ms-key-what">CQI spectral efficiency \f$ \times B \f$.<div class="ms-key-note">Thresholds and efficiencies follow 3GPP TS 38.214 Table 5.1.3.1-1, as in ns3-mmwave's `MmWaveAmc`. At 34.6 dB: 2,492 Mbps where `shannon` gives 4,604.</div></div>
<div class="ms-key-vals">CQI 0–15<br>2,492 Mbps (6.23 b/s/Hz)</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`silvus`</div>
<div class="ms-key-what">Silvus single-stream PHY rate \f$ \times B / 20\,\mathrm{MHz} \f$.<div class="ms-key-note">The rates are the radio's spec sheet; its SINR thresholds are matched to the nearest CQI entry.</div></div>
<div class="ms-key-vals">Silvus MCS 0–6<br>1,170 Mbps (58.5 Mbps × 20)</div>
</div>
</div>

- Below −6.7 dB every model gives 0 Mbps and MCS 0, and routing ignores the
  link.
- Any other `amc_model` passes validation and stops the run at the first link
  at or above −6.7 dB with
  `[LinkEvaluator] Unknown amc_model '<value>'; expected 'shannon', 'table', or 'silvus'`.

| CQI | SINR ≥ (dB) | b/s/Hz | | CQI | SINR ≥ (dB) | b/s/Hz |
|---|---|---|---|---|---|---|
| 0 | −6.7 | 0.15 | | 8 | 10.3 | 2.41 |
| 1 | −4.7 | 0.23 | | 9 | 11.7 | 2.73 |
| 2 | −2.3 | 0.38 | | 10 | 14.1 | 3.32 |
| 3 | 0.2 | 0.60 | | 11 | 16.3 | 3.90 |
| 4 | 2.4 | 0.88 | | 12 | 18.7 | 4.52 |
| 5 | 4.3 | 1.18 | | 13 | 21.0 | 5.12 |
| 6 | 5.9 | 1.48 | | 14 | 22.7 | 5.55 |
| 7 | 8.1 | 1.91 | | 15 | 25.0 | 6.23 |

| Silvus MCS | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|
| SINR ≥ (dB) | −6.7 | 2.4 | 5.9 | 8.1 | 11.7 | 16.3 | 18.7 |
| Mbps at 20 MHz | 6.5 | 13 | 19.5 | 26 | 39 | 52 | 58.5 |

\image html amc-capacity.svg "Capacity against SINR for the three amc_model values at 400 MHz, drawn from the tables in src/eval/sinr-capacity.h by docs/diagrams/amc-capacity.py."

## 3\. Related

- \ref files_channel_models "Channel models": one request through both models
- \ref files_links_csv "links.csv" (`sinr_db`, `capacity_mbps`), \ref files_rx_power_csv "rx-power.csv", \ref files_mcs_csv "mcs.csv": where the results land
- \ref files_jammers_json "jammers.json": jammer power in sub-6 mode
- \ref src_eval "src/eval": the link evaluator and capacity tables
- \ref mesh_sim_add_capacity_model "Add a capacity model": extending `amc_model`

Previous: \ref files_channel_los "LOS, NLOS and shadowing" · Up: \ref files_channel_models "Channel models" · Next: \ref files_traffic "Traffic"
