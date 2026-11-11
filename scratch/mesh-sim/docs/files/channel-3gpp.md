# 3GPP model {#files_channel_3gpp}

[TOC]

`channel_model = 3gpp` uses the path-loss and LOS formulas of 3GPP TR 38.901,
as implemented in ns-3. \ref files_channel_models "Channel models" follows one
request through it; this page has every scenario.

\htmlonly
<div class="ms-find" data-noun="scenario"><div class="ms-find-field"><svg class="ms-find-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg><input type="search" placeholder="Search scenarios, e.g. RMa, breakpoint, InF" aria-label="Search scenarios"><kbd class="ms-find-kbd">/</kbd></div><span class="ms-find-count"></span></div>
<script src="key-find.js"></script>
\endhtmlonly

## 1\. How it works

3GPP built TR 38.901 from many companies' measurement campaigns and fit one
formula per environment and LOS state. Each is a straight line in log
distance. UMi LOS, for example:

\f[ PL = 32.4 + 21\log_{10} d_{3D} + 20\log_{10} f_{\mathrm{GHz}} \quad \text{dB} \f]

- Past a breakpoint distance set by the two antenna heights, the slope gets
  steeper. For mesh heights the breakpoint is usually kilometres away.
- NLOS takes the larger of the two formulas:
  \f$ PL_{NLOS} = \max(PL_{LOS},\, PL'_{NLOS}) \f$.
- A shadowing draw is added on top (\ref files_channel_los "LOS, NLOS and shadowing").
- The formulas are in TR 38.901 Table 7.4.1-1, the LOS probabilities in
  Table 7.4.2-1, building penetration in Section 7.4.3 and shadowing
  correlation in Table 7.5-6. ns-3 implements V15.0.0.

## 2\. In the simulator

- `src/setup/topology-builder.cc` creates the `ThreeGpp…PropagationLossModel`
  for `scenario` and calls `SetFrequency(frequency_ghz × 1e9)`.
- Every other ns-3 attribute keeps its default: shadowing on,
  `EnforceParameterRanges = false`, building penetration loss on.
- Each tick ns-3 returns the TR 38.901 LOS or NLOS loss, plus shadowing, plus
  outdoor-to-indoor loss when the condition is O2I. NLOS loss is the larger of
  the LOS and NLOS formulas.
- The higher node of a pair is the base station (BS), the lower one the user
  terminal (UT).
- Out-of-range distances and heights only log an ns-3 warning, which is off
  unless ns-3 logging is enabled; the formula is extrapolated. The heights
  are the usual misfit for a mesh: `UMa` wants a 25 m BS, so a 1.5–20 m mesh
  is always out of range, and `RMa` wants the higher node at 10 m or more. Outside
  0.5–100 GHz a debug build aborts with
  `Frequency should be between 0.5 and 100 GHz but is <Hz>`.

## 3\. Scenarios

<div class="ms-keys ms-c-purple">
<div class="ms-key ms-key-head"><div>scenario</div><div>What it models</div><div>Valid range</div></div>
<div class="ms-key">
<div class="ms-key-name">`UMi`<span class="ms-key-def">urban micro</span></div>
<div class="ms-key-what">A street canyon with the BS below rooftops. Shadowing σ 4 dB LOS, 7.82 dB NLOS.<div class="ms-key-note">The BS is exactly 10 m: a node at z = 10 m is taken as BS. Beyond a breakpoint set by the two heights the slope steepens: two peers at 10 m reach it only after 30 km, two ground nodes at 1.5 m at 93 m. Classes: `ThreeGppUmiStreetCanyonPropagationLossModel`, `ThreeGppUmiStreetCanyonChannelConditionModel`.</div></div>
<div class="ms-key-vals">0.5–100 GHz<br>10 m–5 km (2D)<br>BS 10 m, UT 1.5 to &lt; 10 m</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`UMa`<span class="ms-key-def">urban macro</span></div>
<div class="ms-key-what">A city with the BS above rooftops. Shadowing σ 4 dB LOS, 6 dB NLOS.<div class="ms-key-note">Has a breakpoint set by the two heights. Classes: `ThreeGppUmaPropagationLossModel`, `ThreeGppUmaChannelConditionModel`.</div></div>
<div class="ms-key-vals">0.5–100 GHz<br>10 m–5 km (2D)<br>BS 25 m, UT 1.5–22.5 m</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`RMa`<span class="ms-key-def">rural macro</span></div>
<div class="ms-key-what">Open rural land. Shadowing σ 4 dB LOS (6 dB past the breakpoint), 8 dB NLOS.<div class="ms-key-note">Uses a 5 m average building height and a 20 m street width. Two peers at 10 m reach the breakpoint after 59 km. Above 30 GHz a debug build aborts with `NS_ASSERT failed, cond="m_frequency <= 30.0e9", msg="RMa scenario is valid for frequencies between 0.5 and 30 GHz."` Classes: `ThreeGppRmaPropagationLossModel`, `ThreeGppRmaChannelConditionModel`.</div></div>
<div class="ms-key-vals">0.5–30 GHz<br>LOS 10 m–10 km, NLOS 10 m–5 km (2D)<br>BS 10–150 m, UT 1–10 m</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`InH`<span class="ms-key-def">indoor office</span></div>
<div class="ms-key-what">An indoor office. Shadowing σ 3 dB LOS, 8.03 dB NLOS.<div class="ms-key-note">The LOS probability assumes a 3 m BS. Classes: `ThreeGppIndoorOfficePropagationLossModel`, `ThreeGppIndoorOpenOfficeChannelConditionModel`.</div></div>
<div class="ms-key-vals">0.5–100 GHz<br>1–150 m (3D)</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`InF`<span class="ms-key-def">indoor factory</span></div>
<div class="ms-key-what">No 3GPP model here: the run exits.<div class="ms-key-note">The validator accepts it; the setup stops with `Unknown 3GPP scenario 'InF'. Valid: UMi, UMa, RMa, InH, InH-Mixed, InH-Open.` Use `channel_model = nyu`, or `InH`.</div></div>
<div class="ms-key-vals">none</div>
</div>
</div>

## 4\. Related

- \ref files_channel_models "Channel models": one request through 3GPP and NYU
- \ref files_channel_nyu "NYU model": the other `channel_model`
- \ref files_channel_los "LOS, NLOS and shadowing": how LOS is decided and the random term
- ns-3 source: `src/propagation/model/three-gpp-propagation-loss-model.cc`, `channel-condition-model.cc`

Previous: \ref files_channel_models "Channel models" · Up: \ref files_channel_models "Channel models" · Next: \ref files_channel_nyu "NYU model"
