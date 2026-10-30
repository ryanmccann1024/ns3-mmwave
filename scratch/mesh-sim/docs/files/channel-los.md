# LOS, NLOS and shadowing {#files_channel_los}

[TOC]

Before the path-loss formula runs, each link is LOS or NLOS. After it, a
random shadowing term is added. Both work the same way under `3gpp` and `nyu`.

\htmlonly
<div class="ms-find" data-noun="setting"><div class="ms-find-field"><svg class="ms-find-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg><input type="search" placeholder="Search, e.g. static_los, building, auto" aria-label="Search settings"><kbd class="ms-find-kbd">/</kbd></div><span class="ms-find-count"></span></div>
<script src="key-find.js"></script>
\endhtmlonly

## 1\. LOS and NLOS

Which condition model decides LOS, and what `condition_reason` in `links.csv`
then reads.

<div class="ms-keys ms-c-blue">
<div class="ms-key ms-key-head"><div>Setting</div><div>How LOS is decided</div><div>Reason in links.csv</div></div>
<div class="ms-key">
<div class="ms-key-name">`auto`<span class="ms-key-def">default `condition_model`</span></div>
<div class="ms-key-what">The loss model's own condition model draws LOS with probability \f$ P_{LOS}(d_{2D}) \f$, once per node pair at its first evaluation, and keeps it for the rest of the seed.<div class="ms-key-note">The draw never updates (ns-3 `UpdatePeriod = 0`), so a moving link never changes state: in `02-distance-sweep` seeds 1–6 stay LOS on all 241 ticks out to 2,450 m, where the RMa LOS probability is 0.09. The draw depends on `seed` and `run_id`: in `15-umi-los-probability` (`UMi`, 100 m, \f$ P_{LOS} = 0.23 \f$) seeds 1–10 gave 3 LOS and 7 NLOS links.</div></div>
<div class="ms-key-vals">`probabilistic`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`static_los`<span class="ms-key-def">`condition_model`</span></div>
<div class="ms-key-what">Every link is LOS. A `BuildingsChannelConditionModel` with no buildings replaces the loss model's own.<div class="ms-key-note">`condition_reason` still reads `probabilistic`: the label only tracks whether buildings exist. `condition` is always `LOS`.</div></div>
<div class="ms-key-vals">`probabilistic`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`buildings_file`<span class="ms-key-def">any building</span></div>
<div class="ms-key-what">A `BuildingsChannelConditionModel` decides every tick from geometry, whatever `condition_model` says: NLOS when the straight 3D segment between the nodes crosses a building box, or when one node is inside a building.<div class="ms-key-note">A segment that passes over a roof is LOS. Only buildings make a link O2I (one node inside a building). 3GPP then adds TR 38.901 penetration loss: low for `Wood` and `ConcreteWithWindows` walls, high for the others, always low for `RMa`, also between two different buildings. NYU adds the `o2i_loss_type` loss. Without buildings no link is ever O2I.</div></div>
<div class="ms-key-vals">`building`</div>
</div>
</div>

\f$ P_{LOS} \f$ from the ns-3 formulas at a few 2D distances, for nodes at 10 m. With
`auto`, this is the share of seeds in which a pair at that distance is LOS.

| `scenario` | 10 m | 25 m | 50 m | 100 m | 250 m | 500 m | 1 km |
|---|---|---|---|---|---|---|---|
| `UMi` 3GPP | 1.00 | 0.86 | 0.52 | 0.23 | 0.07 | 0.04 | 0.02 |
| `UMi` NYU | 1.00 | 0.78 | 0.73 | 0.29 | 0.03 | 0.00 | 0.00 |
| `UMa` 3GPP | 1.00 | 0.91 | 0.65 | 0.35 | 0.09 | 0.04 | 0.02 |
| `UMa` NYU | 1.00 | 0.94 | 0.70 | 0.39 | 0.07 | 0.01 | 0.00 |
| `RMa` 3GPP and NYU | 1.00 | 0.99 | 0.96 | 0.91 | 0.79 | 0.61 | 0.37 |
| `InH` 3GPP | 0.93 | 0.75 | 0.54 | 0.42 | 0.21 | 0.06 | 0.01 |
| `InH` NYU | 0.29 | 0.18 | 0.08 | 0.02 | 0.00 | 0.00 | 0.00 |
| `InF` NYU | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

`UMa` uses the lower node's height; above 13 m it raises the probability. `InF` is always
NLOS because of the NaN in its condition model (\ref files_channel_nyu "NYU model").

## 2\. Shadowing

- A log-normal term with the σ on each scenario card. 3GPP shadowing is
  always on; NYU shadowing follows `shadowing_enabled`.
- Both models correlate a pair's next value with its last, so a moving link
  changes smoothly:
  \f[ X_{new} = R\,X_{old} + \sqrt{1 - R^2}\;\sigma\,\mathcal{N}(0, 1), \qquad R = e^{-\Delta d / d_{corr}} \f]
  where \f$ \Delta d \f$ is how far the pair's relative position moved. A change of
  LOS/NLOS state draws a fresh value.
- From tick 0.1 s on, a static link keeps one value. Tick 0 differs: ns-3
  stores a zero displacement with the first draw, so the second evaluation sees
  the full node separation as movement and draws a nearly fresh value. In
  `01-static-los-baseline` the first draw put the loss below free space, the
  floor capped SINR at 35.6 dB (the free-space ceiling for 100 m), and later
  ticks read 34.6 dB.

| `scenario` | \f$ d_{corr} \f$ LOS / NLOS (both models) |
|---|---|
| `UMi` | 10 / 13 m |
| `UMa` | 37 / 50 m |
| `RMa` | 37 / 120 m |
| `InH` | 10 / 6 m |
| `InF` (NYU) | 10 / 10 m |

## 3\. Related

- \ref files_channel_models "Channel models": one request through both models, with the real draws
- \ref files_buildings_json "buildings.json": geometry LOS/NLOS and O2I
- \ref files_links_csv "links.csv": `condition` and `condition_reason`

Previous: \ref files_channel_nyu "NYU model" · Up: \ref files_channel_models "Channel models" · Next: \ref files_channel_capacity "SINR and capacity"
