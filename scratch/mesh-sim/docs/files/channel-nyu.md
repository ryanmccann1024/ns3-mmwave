# NYU model {#files_channel_nyu}

[TOC]

`channel_model = nyu` uses the NYU WIRELESS close-in model, as implemented in
ns-3, plus optional weather, foliage and wall loss from `[nyu_channel]`.
\ref files_channel_models "Channel models" follows one request through it.

\htmlonly
<div class="ms-find" data-noun="setting"><div class="ms-find-field"><svg class="ms-find-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg><input type="search" placeholder="Search scenarios and settings, e.g. RMa, rain, foliage" aria-label="Search settings"><kbd class="ms-find-kbd">/</kbd></div><span class="ms-find-count"></span></div>
<script src="key-find.js"></script>
\endhtmlonly

## 1\. How it works

NYU WIRELESS fit this model to its measurements at 28, 38, 73 and 140 GHz. The
loss starts at the free-space value 1 m from the transmitter and grows with
one slope, the path-loss exponent \f$ n \f$:

\f[ PL = \underbrace{20\log_{10}\frac{4\pi \cdot 1\,\mathrm{m}}{\lambda}}_{\text{free space at 1 m}} + 10\,n\log_{10} d_{2D} + X_\sigma \quad \text{dB} \f]

- \f$ n = 2 \f$ is free space; a larger \f$ n \f$ is a cluttered path. Each
  doubling of distance adds \f$ 3.01\,n \f$ dB.
- One number per state sets the slope, which keeps the fit stable across
  frequencies (Sun et al. 2016).
- The LOS probability is the NYU squared model: the 3GPP form squared, which
  falls faster with distance.
- Weather, foliage and wall loss are added on top when enabled (section 4).

## 2\. In the simulator

- The setup creates the `NYU<scenario>PropagationLossModel` and
  `NYU<scenario>ChannelConditionModel` (for example
  `NYUUmiPropagationLossModel`), calls `SetFrequency`, and sets nine
  attributes from `[nyu_channel]`: `ShadowingEnabled`, `Pressure`, `Humidity`,
  `Temperature`, `RainRate`, `AtmosphericLossEnabled`, `FoliageLossEnabled`,
  `FoliageLoss`, `O2ILosstype`.
- `NYUChannelModel` is never created, so `rf_bandwidth_mhz` is unused.
- Parameters are given at 28 GHz and below. Between 28 and 140 GHz they move
  linearly to the 140 GHz values; above 140 GHz they hold. Outside 0.5–150 GHz
  a debug build aborts with
  `Frequency should be between 0.5 and 150 GHz but is <Hz>`.
- The ns-3 model checks no distance or height range. Height enters only the
  `RMa` exponent and the `UMa` LOS probability.
- A node directly above another (2D distance 0) gets the free-space loss of the
  3D distance.
- For `UMi` and `UMa` LOS links (n = 2) the loss is exactly free-space loss at
  the 2D distance. Any height difference puts the free-space floor at the 3D
  distance above it, so the floor sets the loss. Negative shadowing draws fall
  below the floor and are clipped, so LOS shadowing only ever adds loss.

## 3\. Scenarios

<div class="ms-keys ms-c-pink">
<div class="ms-key ms-key-head"><div>scenario</div><div>Path-loss exponent and LOS probability</div><div>Valid range and σ</div></div>
<div class="ms-key">
<div class="ms-key-name">`UMi`<span class="ms-key-def">urban micro</span></div>
<div class="ms-key-what">n = 2.0 LOS, 3.2 NLOS.<div class="ms-key-note">LOS probability: 1 up to 22 m, then \f$ \left(\tfrac{22}{d}\left(1 - \tfrac{22}{d}\right) + e^{-d/100}\right)^2 \f$. The paper has \f$ \tfrac{22}{d}\left(1 - e^{-d/100}\right) \f$ in the first term; ns-3 gives 0.29 at 100 m where the paper gives 0.26, and 0.78 at 25 m where the paper gives 0.95.</div></div>
<div class="ms-key-vals">0.5–150 GHz<br>any distance, height not used<br>σ 4.0 dB LOS, 7.0 dB NLOS</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`UMa`<span class="ms-key-def">urban macro</span></div>
<div class="ms-key-what">n = 2.0 LOS, 2.9 NLOS.<div class="ms-key-note">LOS probability (NYU fit): 1 up to 20 m; it depends on height.</div></div>
<div class="ms-key-vals">0.5–150 GHz<br>any distance; height in the LOS probability<br>σ 4.0 dB LOS, 7.0 dB NLOS</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`RMa`<span class="ms-key-def">rural macro</span></div>
<div class="ms-key-what">LOS \f$ n = 2.31\left(1 - 0.03\,\tfrac{h_{BS} - 35}{35}\right) \f$, NLOS \f$ n = 3.07\left(1 - 0.049\,\tfrac{h_{BS} - 35}{35}\right) \f$.<div class="ms-key-note">LOS probability: the same formula as 3GPP `RMa`.</div></div>
<div class="ms-key-vals">0.5–150 GHz<br>any distance; BS height sets n<br>σ 1.7 dB LOS, 6.7 dB NLOS</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`InH`<span class="ms-key-def">indoor office</span></div>
<div class="ms-key-what">n = 1.2 LOS (1.8 at 1 GHz), 2.7 NLOS.<div class="ms-key-note">LOS probability: the 5GCM indoor formula.</div></div>
<div class="ms-key-vals">0.5–150 GHz<br>any distance, height not used<br>σ 3.0 dB LOS, 9.8 dB NLOS</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`InF`<span class="ms-key-def">indoor factory</span></div>
<div class="ms-key-what">n = 1.7 LOS, 3.1 NLOS. With `condition_model = auto` every link is NLOS.<div class="ms-key-note">`NYUInFChannelConditionModel` takes \f$ (-d)^{0.16} \f$, which is NaN. Use `condition_model = static_los` or buildings for LOS links.</div></div>
<div class="ms-key-vals">0.5–150 GHz<br>any distance, height not used<br>σ 3.0 dB LOS, 7.0 dB NLOS</div>
</div>
</div>

## 4\. NYU settings {#files_channel_models_nyu}

The measured effect of each `[nyu_channel]` setting on `04-nyu-vs-3gpp` (RMa,
LOS, 500 m, 28 GHz, shadowing off, SINR 11.91 dB). Definitions and defaults:
\ref files_run_ini "run.ini".

- Weather loss is an attenuation rate in dB/m from the Liebe millimeter-wave
  propagation model (MPM) times the 2D distance.
- The ranges are `NS_ASSERT` checks: a debug build aborts at the start of the
  seed with the message on the card; an optimized build skips them and uses
  the value.

<div class="ms-keys ms-c-pink">
<div class="ms-key ms-key-head"><div>Setting</div><div>Effect</div><div>Change in SINR at 500 m</div></div>
<div class="ms-key">
<div class="ms-key-name">`shadowing_enabled`<span class="ms-key-def">default `true`</span></div>
<div class="ms-key-what">Adds the shadowing term.<div class="ms-key-note">`false` gives a constant SINR from tick 0.</div></div>
<div class="ms-key-vals">Seed 1: +2.5 dB from tick 0.1 s on (tick 0: −1.0 dB)</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`atmospheric_loss_enabled`<span class="ms-key-def">default `false`</span></div>
<div class="ms-key-what">Turns on oxygen, water-vapor, fog and rain absorption.</div>
<div class="ms-key-vals">Dry, 50% humidity: −0.06 dB<br>At 60 GHz: −7.2 dB (oxygen)</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rain_rate_mm_hr`<span class="ms-key-def">default `0.0`</span></div>
<div class="ms-key-what">The rain term, only with `atmospheric_loss_enabled = true`; with it off, rain has no effect.<div class="ms-key-note">Outside 0–150: `Rain rate should be between 0 to 150 mm/hr but is <value>`.</div></div>
<div class="ms-key-vals">25 mm/h: −2.1 dB<br>100 mm/h: −9.0 dB<br>25 mm/h, atmospheric loss off: 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`humidity_pct`<span class="ms-key-def">default `50.0`</span></div>
<div class="ms-key-what">Water-vapor absorption; above 99.5 % also fog.<div class="ms-key-note">Outside 0–100: `Humidity should be between 0 to 100 but is <value>`.</div></div>
<div class="ms-key-vals">100 %: −0.33 dB</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`temperature_c`<span class="ms-key-def">default `20.0`</span></div>
<div class="ms-key-what">Air temperature; at 0 °C or below the model uses ice.<div class="ms-key-note">Outside −100 to 50: `Temperature should be between -100 to 50 celcius but is <value>`.</div></div>
<div class="ms-key-vals">60 °C: run aborts</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`pressure_mbar`<span class="ms-key-def">default `1013.25`</span></div>
<div class="ms-key-what">Air pressure.<div class="ms-key-note">Above 1013.25: `Barometric pressure should be between 1e-5 mbar to 1013.5 mbar but is 1020`.</div></div>
<div class="ms-key-vals">1020 mbar: run aborts</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`foliage_loss_enabled`<span class="ms-key-def">default `false`</span></div>
<div class="ms-key-what">Adds `foliage_loss_db_m` \f$ \times\, \mathcal{U}(0, d_{2D}) \f$: a new random foliage depth, up to the full link length, every tick.<div class="ms-key-note">SINR jumps by tens of dB from tick to tick. Lower `foliage_loss_db_m` or turn foliage off for a steady link.</div></div>
<div class="ms-key-vals">0.4 dB/m: median −97 dB, from −189 to −0.1 dB<br>0.1 dB/m: median −24 dB</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`foliage_loss_db_m`<span class="ms-key-def">default `0.4`</span></div>
<div class="ms-key-what">Foliage loss per meter of depth.<div class="ms-key-note">Outside 0–10: `foilage loss should be between 0 dB/m and 10 dB/m but is <value>`.</div></div>
<div class="ms-key-vals">see `foliage_loss_enabled`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`o2i_loss_type`<span class="ms-key-def">default `Low Loss`</span></div>
<div class="ms-key-what">O2I links only. `Low Loss`: \f$ 10\log_{10}(5 + 0.03 f^2) + \mathcal{N}(0, 4^2) \f$ dB. `High Loss`: \f$ 10\log_{10}(10 + 5 f^2) + \mathcal{N}(0, 6^2) \f$ dB, with \f$ f \f$ in GHz.<div class="ms-key-note">Any other text stops the run at the first O2I link with `Unknown O2I Loss Type` (NS_FATAL). Write the exact text, without quotes.</div></div>
<div class="ms-key-vals">No buildings: 0</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`rf_bandwidth_mhz`<span class="ms-key-def">default `800.0`</span></div>
<div class="ms-key-what">Parsed, never applied.</div>
<div class="ms-key-vals">0</div>
</div>
</div>

## 5\. Related

- \ref files_channel_models "Channel models": one request through 3GPP and NYU
- \ref files_channel_3gpp "3GPP model": the other `channel_model`
- \ref files_run_ini "run.ini": `[nyu_channel]` defaults and ranges
- ns-3 source: `src/propagation/model/nyu-propagation-loss-model.cc`, `nyu-channel-condition-model.cc`

Previous: \ref files_channel_3gpp "3GPP model" · Up: \ref files_channel_models "Channel models" · Next: \ref files_channel_los "LOS, NLOS and shadowing"
