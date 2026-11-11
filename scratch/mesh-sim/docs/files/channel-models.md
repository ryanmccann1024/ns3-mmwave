# Channel models: 3GPP and NYU {#files_channel_models}

[TOC]

Every tick the simulator works out how strong each link is. The channel model,
`channel_model = 3gpp` or `nyu` in \ref files_run_ini "run.ini", turns the
positions of two nodes into a path loss in dB. The rest of the chain turns that
loss into SINR, a rate and a route. This page follows one request through the
chain, once with each model.

## 1\. The example

Three fixed nodes and one request: `radio` sends 200 Mbps to `gw`. `drone` can
relay.

\htmlonly
<div class="ms-flow-art ms-scene ms-c-blue"><svg viewBox="0 0 640 230" role="img" aria-label="Three nodes: gw on a 10 m mast at x 0, drone at 30 m at x 300, radio at 1.5 m at x 600. One request from radio to gw.">
<line class="ms-faint" x1="20" y1="200" x2="620" y2="200"/>
<line class="ms-ink" x1="60" y1="200" x2="60" y2="154"/>
<line class="ms-ink ms-thin" x1="60" y1="154" x2="330" y2="62"/>
<line class="ms-ink ms-thin" x1="330" y1="62" x2="600" y2="193"/>
<line class="ms-ink ms-thin" x1="60" y1="154" x2="600" y2="193"/>
<circle class="ms-dot" cx="60" cy="154" r="7"/><circle class="ms-dot" cx="330" cy="62" r="7"/><circle class="ms-dot" cx="600" cy="193" r="7"/>
<text x="60" y="138" text-anchor="middle" class="ms-strong">gw</text><text x="60" y="218" text-anchor="middle">x 0, z 10 m</text>
<text x="330" y="44" text-anchor="middle" class="ms-strong">drone</text><text x="330" y="28" text-anchor="middle">x 300, z 30 m</text>
<text x="600" y="176" text-anchor="middle" class="ms-strong">radio</text><text x="600" y="218" text-anchor="middle">x 600, z 1.5 m</text>
<text x="180" y="98">300 m</text><text x="470" y="118">300 m</text><text x="330" y="188" text-anchor="middle">600 m</text>
<text x="620" y="22" text-anchor="end" class="ms-strong">Request: radio &rarr; gw, 200 Mbps</text>
</svg></div>
\endhtmlonly

| Node | x, y, z | |
|---|---|---|
| `gw` | 0, 0, 10 m | the destination, on a 10 m mast |
| `drone` | 300, 0, 30 m | a possible relay |
| `radio` | 600, 0, 1.5 m | the source, on the ground |

```ini
[scenario]
seed          = 5
tick_s        = 0.1
[channel]
scenario      = RMa
channel_model = 3gpp     ; second run: nyu
frequency_ghz = 28.0
bandwidth_mhz = 400.0
tx_power_dbm  = 30.0     ; plus 12 dBi of antenna gain at each end (default)
[traffic]
flow_topology = explicit_pairs
pairs         = [{"src":"radio","dst":"gw","demand_mbps":200}]
[routing]
algorithm     = shortest_path
```

The two runs differ only in `channel_model`. With 3GPP the request goes
straight to `gw`; with NYU it goes through `drone`. Sections 2–8 show why, with
the numbers from tick 0.1 s (nothing moves, so every later tick repeats them).

## 2\. Measure each link

\htmlonly
<div class="ms-flow-step ms-step-card ms-c-grey">
<div class="ms-flow-art"><svg viewBox="0 0 140 92" aria-hidden="true"><line class="ms-faint" x1="4" y1="76" x2="136" y2="76"/><line class="ms-faint" x1="112" y1="16" x2="112" y2="76"/><line class="ms-faint" x1="28" y1="52" x2="28" y2="76"/><line class="ms-ink" x1="28" y1="52" x2="112" y2="16"/><line class="ms-ink" x1="28" y1="76" x2="112" y2="76"/><circle class="ms-dot" cx="28" cy="52" r="6"/><circle class="ms-dot" cx="112" cy="16" r="6"/><text x="62" y="26">3D</text><text x="70" y="89" text-anchor="middle">2D</text><text x="120" y="20">BS</text><text x="8" y="48">UT</text></svg></div>
<div class="ms-flow-body"><p>Three nodes make three links. For each one the simulator measures the distance along the ground and in a straight line, and notes which node is higher: the higher one plays the base station (BS), the lower one the user (UT).</p></div>
</div>
\endhtmlonly

\f[ d_{2D} = \sqrt{\Delta x^2 + \Delta y^2} \qquad d_{3D} = \sqrt{d_{2D}^2 + \Delta z^2} \f]

| Link | \f$ d_{2D} \f$ | \f$ d_{3D} \f$ | \f$ h_{BS} \f$ | \f$ h_{UT} \f$ |
|---|---|---|---|---|
| gw–drone | 300 m | 300.7 m | 30 m | 10 m |
| gw–radio | 600 m | 600.1 m | 10 m | 1.5 m |
| drone–radio | 300 m | 301.4 m | 30 m | 1.5 m |

3GPP puts \f$ d_{3D} \f$ into its formula and NYU puts \f$ d_{2D} \f$. Both
use the heights.

## 3\. Flip the LOS coin

\htmlonly
<div class="ms-flow-step ms-step-card ms-c-blue">
<div class="ms-flow-art"><svg viewBox="0 0 140 92" aria-hidden="true"><rect class="ms-soft" x="56" y="26" width="28" height="54" rx="2"/><line class="ms-faint" x1="4" y1="80" x2="136" y2="80"/><line class="ms-ink" x1="16" y1="16" x2="124" y2="16"/><line class="ms-bad" x1="16" y1="54" x2="124" y2="54"/><circle class="ms-dot" cx="16" cy="16" r="5"/><circle class="ms-dot" cx="124" cy="16" r="5"/><circle class="ms-dot" cx="16" cy="54" r="5"/><circle class="ms-dot" cx="124" cy="54" r="5"/><text x="70" y="10" text-anchor="middle">LOS</text><text x="104" y="70" text-anchor="middle">NLOS</text></svg></div>
<div class="ms-flow-body"><p>With no buildings, LOS is a weighted coin. The longer the link, the less likely a clear line of sight. Each link is flipped once, at its first tick, and keeps the result for the whole run.</p></div>
</div>
\endhtmlonly

In `RMa` both models use the same probability:

\f[ P_{LOS} = e^{-(d_{2D} - 10)/1000} \f]

The simulator draws a random number \f$ u \f$ between 0 and 1; the link is LOS
when \f$ u \le P_{LOS} \f$. These are the draws ns-3 made (seed 5):

| Link | \f$ P_{LOS} \f$ | 3GPP draw \f$ u \f$ | NYU draw \f$ u \f$ | Result |
|---|---|---|---|---|
| gw–drone | 0.75 | 0.020 | 0.241 | LOS in both |
| gw–radio | 0.55 | 0.371 | 0.030 | LOS in both |
| drone–radio | 0.75 | 0.307 | 0.410 | LOS in both |

The two models draw different numbers, but here all six land on LOS, so the
rest compares LOS with LOS. Buildings and `static_los` replace the coin:
\ref files_channel_los "LOS, NLOS and shadowing".

## 4\. Path loss: where the models differ

\htmlonly
<div class="ms-flow-step ms-step-card ms-c-purple">
<div class="ms-flow-art"><svg viewBox="0 0 140 92" aria-hidden="true"><circle class="ms-dot" cx="18" cy="46" r="6"/><path class="ms-ink" d="M34 30 A 23 23 0 0 1 34 62"/><path class="ms-ink" style="opacity:.7" d="M52 20 A 43 43 0 0 1 52 72"/><path class="ms-ink" style="opacity:.45" d="M70 12 A 62 62 0 0 1 70 80"/><path class="ms-ink" style="opacity:.25" d="M88 6 A 81 81 0 0 1 88 86"/><circle class="ms-dot" cx="124" cy="46" r="6"/><text x="124" y="68" text-anchor="middle">&minus;dB</text></svg></div>
<div class="ms-flow-body"><p>The path-loss formula turns distance and frequency into dB lost between the antennas. This is the one step that differs between the models.</p></div>
</div>
\endhtmlonly

**3GPP** (`RMa` LOS, TR 38.901), with \f$ f \f$ in GHz and an average building
height \f$ h = 5 \f$ m:

\f[ \begin{aligned} PL_{3GPP} = {} & \underbrace{20\log_{10}\frac{40\pi\, d_{3D}\, f}{3}}_{\text{free-space loss}} \\ & + \underbrace{0.03\,h^{1.72}\log_{10} d_{3D} - 0.044\,h^{1.72} + 0.002\log_{10}(h)\, d_{3D}}_{\text{about } 1.5 \text{ dB here}} \end{aligned} \f]

The first term is free-space loss, so over these distances 3GPP `RMa` LOS is
free space plus about 1.5 dB. The formula steepens past a breakpoint distance,
which here is 8.8 km or more.

**NYU** (`RMa` LOS, close-in model):

\f[ PL_{NYU} = \underbrace{20\log_{10}\frac{4\pi \cdot 1\,\mathrm{m}}{\lambda}}_{61.4 \text{ dB at 28 GHz}} + 10\,n\log_{10} d_{2D}, \qquad n = 2.31\left(1 - 0.03\,\frac{h_{BS} - 35}{35}\right) \f]

\f$ n \f$ is 2.32 for the 30 m drone and 2.36 for the 10 m mast. Free space is
\f$ n = 2 \f$, so NYU loses about 7.1 dB per doubling of distance where free
space loses 6.0 dB.

| Link | 3GPP | NYU | NYU − 3GPP |
|---|---|---|---|
| gw–drone | 111.9 dB | 118.9 dB | 7.0 dB |
| gw–radio | 118.4 dB | 126.9 dB | 8.5 dB |
| drone–radio | 111.9 dB | 118.9 dB | 7.0 dB |

The 600 m link takes the biggest hit: it is the longest, and its BS is the low
mast, which gives the steepest \f$ n \f$.

## 5\. Add shadowing, then apply the floor

\htmlonly
<div class="ms-flow-step ms-step-card ms-c-purple">
<div class="ms-flow-art"><svg viewBox="0 0 140 92" aria-hidden="true"><line class="ms-faint" x1="10" y1="76" x2="130" y2="76"/><rect class="ms-soft" x="28" y="20" width="30" height="56"/><rect class="ms-soft" x="82" y="32" width="30" height="44"/><line class="ms-ink" x1="16" y1="32" x2="124" y2="32" stroke-dasharray="5 4"/><text x="43" y="89" text-anchor="middle">model</text><text x="97" y="89" text-anchor="middle">free space</text><text x="70" y="12" text-anchor="middle">larger wins</text></svg></div>
<div class="ms-flow-body"><p>A random shadowing offset stands in for terrain and clutter the formula does not see. The result is never allowed below free-space loss.</p></div>
</div>
\endhtmlonly

\f[ PL = \max\big(PL_{\text{formula}} + X,\ FSPL(d_{3D})\big), \qquad X \sim \mathcal{N}(0, \sigma^2) \f]

\f$ \sigma \f$ is 4 dB for 3GPP `RMa` LOS and 1.7 dB for NYU. Free-space loss
\f$ FSPL \f$ is 111.0 dB at 300 m and 117.0 dB at 600 m.

| Link | 3GPP \f$ X \f$ | 3GPP \f$ PL \f$ | NYU \f$ X \f$ | NYU \f$ PL \f$ |
|---|---|---|---|---|
| gw–drone | +4.7 dB | 116.6 dB | +0.8 dB | 119.7 dB |
| gw–radio | below −1.5 dB | 117.0 dB (floor) | +3.5 dB | 130.4 dB |
| drone–radio | −0.1 dB | 111.8 dB | −4.6 dB | 114.3 dB |

The 3GPP gw–radio draw pushed the loss below free space, so the floor set it
to 117.0 dB. The NYU gw–radio draw went the other way and added 3.5 dB. The
gap on the direct link is now 13.4 dB.

## 6\. Received power and SINR

\htmlonly
<div class="ms-flow-step ms-step-card ms-c-green">
<div class="ms-flow-art"><svg viewBox="0 0 140 92" aria-hidden="true"><line class="ms-ink" x1="30" y1="12" x2="70" y2="12"/><line class="ms-ink" x1="50" y1="14" x2="50" y2="38"/><path class="ms-ink" d="M45 33 L50 38 L55 33"/><line class="ms-ink" x1="30" y1="42" x2="70" y2="42"/><line class="ms-faint" x1="30" y1="76" x2="70" y2="76"/><path class="ms-ink" d="M26 44 L20 44 L20 74 L26 74"/><text x="76" y="15">tx + gains</text><text x="76" y="45">received</text><text x="76" y="79">noise</text><text x="56" y="29">&minus; loss</text><text transform="translate(14 59) rotate(-90)" text-anchor="middle">SINR</text></svg></div>
<div class="ms-flow-body"><p>Received power is what is left of the transmit power after the antennas and the path. SINR compares it with the receiver noise.</p></div>
</div>
\endhtmlonly

\f[ P_{rx} = P_{tx} + G_{tx} + G_{rx} - PL = 30 + 12 + 12 - PL \quad \text{dBm} \f]

\f[ N = -174 + 10\log_{10}(400 \times 10^6) + 5 = -83.0 \text{ dBm} \qquad SINR = P_{rx} - N \f]

| Link | 3GPP \f$ P_{rx} \f$ | 3GPP SINR | NYU \f$ P_{rx} \f$ | NYU SINR |
|---|---|---|---|---|
| gw–drone | −62.6 dBm | 20.4 dB | −65.7 dBm | 17.3 dB |
| gw–radio | −63.0 dBm | 20.0 dB | −76.4 dBm | 6.6 dB |
| drone–radio | −57.8 dBm | 25.2 dB | −60.3 dBm | 22.7 dB |

There are no jammers at 28 GHz, so SINR is signal over noise.

## 7\. Capacity

\htmlonly
<div class="ms-flow-step ms-step-card ms-c-amber">
<div class="ms-flow-art"><svg viewBox="0 0 140 92" aria-hidden="true"><path class="ms-faint" d="M14 78 L132 78 M14 78 L14 8"/><path class="ms-ink" d="M14 78 L34 78 L34 68 L48 68 L48 58 L62 58 L62 46 L76 46 L76 36 L92 36 L92 24 L108 24 L108 14 L130 14"/><text x="132" y="90" text-anchor="end">SINR</text><text x="18" y="8">Mbps</text></svg></div>
<div class="ms-flow-body"><p><code>amc_model</code> turns SINR into a rate. The default, <code>shannon</code>, is the Shannon limit over the full bandwidth.</p></div>
</div>
\endhtmlonly

\f[ C = B\log_2\left(1 + 10^{SINR/10}\right), \qquad B = 400 \text{ MHz} \f]

| Link | 3GPP | NYU |
|---|---|---|
| gw–drone | 2,717 Mbps (CQI 12) | 2,312 Mbps (CQI 11) |
| gw–radio | 2,667 Mbps (CQI 12) | 990 Mbps (CQI 6) |
| drone–radio | 3,346 Mbps (CQI 15) | 3,019 Mbps (CQI 13) |

\image html amc-capacity.svg "Capacity against SINR for the three amc_model values at 400 MHz, from src/eval/sinr-capacity.h."

The CQI is the MCS row the SINR reaches. `table` and `silvus` give the stepped
rates: \ref files_channel_capacity "SINR and capacity".

## 8\. Route the request

`shortest_path` adds up \f$ 1/C \f$ over each path's links and takes the
smallest total, so one weak link costs more than two strong ones. In
\f$ 1/\text{Gbps} \f$:

| Path | 3GPP cost | NYU cost |
|---|---|---|
| radio → gw | **0.375** | 1.010 |
| radio → drone → gw | 0.299 + 0.368 = 0.667 | **0.331 + 0.432 = 0.764** |

\htmlonly
<div class="ms-flow-split ms-routes">
<div class="ms-flow-art ms-c-purple"><svg viewBox="0 0 260 120" aria-hidden="true"><line class="ms-faint" x1="30" y1="80" x2="130" y2="28"/><line class="ms-faint" x1="130" y1="28" x2="230" y2="96"/><line class="ms-ink ms-thick" x1="30" y1="80" x2="230" y2="96"/><circle class="ms-dot" cx="30" cy="80" r="6"/><circle class="ms-dot" cx="130" cy="28" r="6"/><circle class="ms-dot" cx="230" cy="96" r="6"/><text x="30" y="104" text-anchor="middle">gw</text><text x="130" y="14" text-anchor="middle">drone</text><text x="230" y="116" text-anchor="middle">radio</text><text x="130" y="112" text-anchor="middle" class="ms-strong">3GPP: direct</text></svg></div>
<div class="ms-flow-art ms-c-pink"><svg viewBox="0 0 260 120" aria-hidden="true"><line class="ms-faint" x1="30" y1="80" x2="230" y2="96"/><line class="ms-ink ms-thick" x1="30" y1="80" x2="130" y2="28"/><line class="ms-ink ms-thick" x1="130" y1="28" x2="230" y2="96"/><circle class="ms-dot" cx="30" cy="80" r="6"/><circle class="ms-dot" cx="130" cy="28" r="6"/><circle class="ms-dot" cx="230" cy="96" r="6"/><text x="30" y="104" text-anchor="middle">gw</text><text x="130" y="14" text-anchor="middle">drone</text><text x="230" y="116" text-anchor="middle">radio</text><text x="130" y="112" text-anchor="middle" class="ms-strong">NYU: through the drone</text></svg></div>
</div>
\endhtmlonly

| | 3GPP | NYU |
|---|---|---|
| Path | radio → gw | radio → drone → gw |
| Hops | 1 | 2 |
| Bottleneck | 2,667 Mbps | 2,312 Mbps |
| Delivered | 200 of 200 Mbps | 200 of 200 Mbps |
| Latency | 0.502 ms | 1.002 ms |

Both deliver the full request. Under NYU the direct link is too weak to be the
cheapest path, so the request takes an extra hop. These numbers are in
\ref files_links_csv "links.csv", \ref files_routes_csv "routes.csv" and
\ref files_flows_csv "flows.csv".

## 9\. 3GPP and NYU compared

| | `3gpp` | `nyu` |
|---|---|---|
| Basis | 3GPP TR 38.901 | NYU WIRELESS measurements (NYUSIM) |
| Frequency | 0.5–100 GHz; `RMa` 0.5–30 GHz | 0.5–150 GHz; parameters fixed below 28 GHz |
| Scenarios | `UMi`, `UMa`, `RMa`, `InH` | `UMi`, `UMa`, `RMa`, `InH`, `InF` |
| Distance in the formula | 3D (2D for the range check and breakpoint) | 2D |
| Path-loss form | Floating intercept, breakpoint for outdoor scenarios | Close-in, 1 m free-space reference, one slope |
| NLOS loss | max(LOS, NLOS) | NLOS formula alone |
| Shadowing | Always on | `shadowing_enabled` |
| Weather | None | `atmospheric_loss_enabled`, `rain_rate_mm_hr`, `humidity_pct`, `temperature_c`, `pressure_mbar` |
| Foliage | None | `foliage_loss_enabled`, `foliage_loss_db_m` |
| O2I loss | From the building's wall type | From `o2i_loss_type` |
| Range checks | Logged warnings only; `RMa` above 30 GHz aborts (debug) | Weather and foliage values abort when out of range (debug) |

## 10\. Common changes

| To | Set | What you'll see |
|---|---|---|
| Compare the two families | `channel_model = nyu` | RMa at 500 m: NYU LOS 11.9 dB, 3GPP LOS 21.6 dB; an NYU NLOS draw kills the link. Example: `04-nyu-vs-3gpp`. |
| Add rain | `[nyu_channel]` `atmospheric_loss_enabled = true`, `rain_rate_mm_hr = 25.0` | −2.1 dB over 500 m. Example: `05-nyu-atmosphere`. |
| Use discrete MCS rates | `amc_model = table` | 2,492 Mbps instead of 4,604 at 34.6 dB. Example: `06-mcs-table-mode`. |
| See random LOS/NLOS | `scenario = UMi`, run `--seeds=1,2,...,10` | 3 of 10 seeds LOS (29.7–35.6 dB), 7 NLOS (9.2–26.3 dB). Example: `15-umi-los-probability`. |
| Remove the LOS lottery | `condition_model = static_los` | Every link LOS. Example: `p0-jammer-smoke`. |
| Block links by geometry | `buildings_file = buildings.json` | LOS/NLOS changes as nodes move; `condition_reason = building`. Example: `03-building-blockage`. |
| Flat, repeatable NYU links | `shadowing_enabled = false` | Constant SINR from tick 0. Example: `04-nyu-vs-3gpp`. |
| Move to 60 GHz | `frequency_ghz = 60.0`, `channel_model = nyu`, `atmospheric_loss_enabled = true` | Oxygen absorption: −7.2 dB over 500 m. 3GPP `RMa` refuses above 30 GHz. |
| Model a 20 MHz radio | `bandwidth_mhz = 20.0`, `amc_model = silvus` | Noise floor −96 dBm (13 dB lower), capacity 6.5–58.5 Mbps. |
| Model a sub-6 link | `band = sub-6`, `frequency_ghz = 2.4` | Lower path loss; jammers in `jammers.json` count. Example: `p0-jammer-smoke`. |
| Give one node a weaker antenna | `"tx_array_gain_dbi": 0, "rx_array_gain_dbi": 0` in that node's `nodes.json` entry | Up to 24 dB less SINR on its links. |

## 11\. Reference pages

| Page | What it covers |
|---|---|
| \subpage files_channel_3gpp "3GPP model" | Every `scenario` with its formula notes and valid ranges |
| \subpage files_channel_nyu "NYU model" | Every `scenario`, and the `[nyu_channel]` weather, foliage and wall settings |
| \subpage files_channel_los "LOS, NLOS and shadowing" | Buildings, `static_los` and the coin; LOS probability by distance; shadowing |
| \subpage files_channel_capacity "SINR and capacity" | The free-space floor, noise, SINR, and the three `amc_model` tables |

## 12\. Papers and specifications

| Covers | Source | Link |
|---|---|---|
| 3GPP path loss (Table 7.4.1-1), LOS probability (Table 7.4.2-1), building penetration (7.4.3), shadowing correlation (Table 7.5-6) | 3GPP TR 38.901, *Study on channel model for frequencies from 0.5 to 100 GHz*. ns-3 implements V15.0.0. | [3GPP specification page](https://portal.3gpp.org/desktopmodules/Specifications/SpecificationDetails.aspx?specificationId=3173) |
| How ns-3 implements the 3GPP models | T. Zugno et al., *Implementation of a Spatial Channel Model for ns-3*, WNS3 2020 | [arXiv:2002.09341](https://arxiv.org/abs/2002.09341) |
| NYU LOS probability (NYU squared, Tables I–III) and the path-loss models compared with 3GPP (Section IV) | T. S. Rappaport et al., *Overview of Millimeter Wave Communications for Fifth-Generation (5G) Wireless Networks—With a Focus on Propagation Models*, IEEE Trans. Antennas Propag., vol. 65, no. 12, 2017 | [arXiv:1708.02557](https://arxiv.org/abs/1708.02557) |
| Close-in model versus the 3GPP floating-intercept form | S. Sun et al., *Investigation of Prediction Accuracy, Sensitivity, and Parameter Stability of Large-Scale Propagation Path Loss Models for 5G Wireless Communications*, IEEE Trans. Veh. Technol., vol. 65, no. 5, 2016 | [arXiv:1603.04404](https://arxiv.org/abs/1603.04404) |
| How ns-3 implements the NYU models: LOS probability, path-loss exponents, foliage, 28–140 GHz interpolation | H. Poddar et al., *Full-Stack End-to-End mmWave Simulations Using 3GPP and NYUSIM Channel Model in ns-3*, IEEE ICC 2023 | [arXiv:2302.12385](https://arxiv.org/abs/2302.12385) |
| NYUSIM, including weather loss (dry air, water vapour, rain) | S. Sun et al., *A Novel Millimeter-Wave Channel Simulator and Applications for 5G Wireless Communications*, IEEE ICC 2017 | [arXiv:1703.08232](https://arxiv.org/abs/1703.08232) |
| CQI table used by `amc_model = table` (Table 5.1.3.1-1) | 3GPP TS 38.214, *Physical layer procedures for data* | [3GPP specification page](https://portal.3gpp.org/desktopmodules/Specifications/SpecificationDetails.aspx?specificationId=3216) |

Previous: \ref files_run_ini "run.ini" · Up: \ref mesh_sim_files "Input and output files" · Next: \ref files_channel_3gpp "3GPP model"
