# jammers.json {#files_jammers_json}

[TOC]

`jammers.json` places jammers in the scene: where each one is, how strong it
is, which carrier it targets, where it points and when it is on. In a `sub-6`
run their power adds to the noise on every link they reach.
`[scenario] jammers_file` in `run.ini` names the file, relative to `run.ini`;
blank means no jammers. `scripts.validation.make_jammers` can build it from an
EW trials CSV.

\htmlonly
<div class="ms-find" data-noun="field"><div class="ms-find-field"><svg class="ms-find-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg><input type="search" placeholder="Search fields, e.g. zenith, target_freq, intervals" aria-label="Search fields"><kbd class="ms-find-kbd">/</kbd></div><span class="ms-find-count"></span></div>
<script src="key-find.js"></script>
\endhtmlonly

## 1\. Anatomy

`inputs/baselines/p0-jammer-smoke/jammers.json`, whose `run.ini` sets
`[channel] band = sub-6` and `frequency_ghz = 2.4`, part by part:

\htmlonly
<div class="ms-ini">
<div class="ms-ini-row ms-c-blue">
<pre class="ms-ini-code">[
  {
    "id": "jammer-0",
    "enabled": true,
    "type": "constant",</pre>
<div class="ms-ini-note"><strong>On, off and timing</strong>The jammer is on. With no <code>intervals</code>, it transmits for the whole run.</div>
</div>
<div class="ms-ini-row ms-c-purple">
<pre class="ms-ini-code">    "target_freq": [2400.0],</pre>
<div class="ms-ini-note"><strong>Target band</strong>A spot target, 2400 &plusmn; 2.5 MHz. The 2.4 GHz carrier is inside it.</div>
</div>
<div class="ms-ini-row ms-c-green">
<pre class="ms-ini-code">    "tx_power_dbm": 30.0,
    "tx_array_gain_dbi": 12.0,
    "duty_cycle": 1.0,
    "max_range_m": 0.0,</pre>
<div class="ms-ini-note"><strong>Power and reach</strong>42 dBm EIRP, at full power all the time, with no range cutoff.</div>
</div>
<div class="ms-ini-row ms-c-amber">
<pre class="ms-ini-code">    "beamwidth_deg": 360.0,
    "azimuth_deg": 0.0,
    "zenith_deg": 90.0,</pre>
<div class="ms-ini-note"><strong>Beam</strong>Omnidirectional, so the two pointing angles are unused.</div>
</div>
<div class="ms-ini-row ms-c-grey">
<pre class="ms-ini-code">    "position": {"x": 50.0, "y": 0.0, "z": 10.0}
  }
]</pre>
<div class="ms-ini-note"><strong>Position and motion</strong>Stationary at (50, 0, 10): midway between <code>node-a</code> (0, 0, 10) and <code>node-b</code> (100, 0, 10), and 50 m south of <code>relay</code> (50, 50, 10).</div>
</div>
</div>
\endhtmlonly

The file is a JSON array with one object per jammer. Every key is optional.

\note Jammers count only when the band is `sub-6` (`--band`, else
`[channel] band`, else `mmwave`). In an `mmwave` run they are loaded and
logged but add nothing. `run.log` shows whether they are live:

```text
  jammers.configured  = 1
  jammers.enabled     = 1
  jammer_path_enabled = true

Jammers:
  jammer-0: enabled=true type=constant target_freq_mhz=[2400] tx_power_dbm=30 tx_array_gain_dbi=12 duty_cycle=1 max_range_m=0 beamwidth_deg=360 azimuth_deg=0 zenith_deg=90 motion=static
```

## 2\. How a jammer reaches a link

Each tick, for each receiving node, every enabled jammer passes through these
checks in order. A jammer that fails one adds nothing to that node:

\htmlonly
<div class="ms-gates"><div class="ms-gate"><strong>Time</strong><span><code>intervals</code></span></div><span class="ms-gate-arrow">&rarr;</span><div class="ms-gate"><strong>On/off</strong><span><code>random</code> type</span></div><span class="ms-gate-arrow">&rarr;</span><div class="ms-gate"><strong>Frequency</strong><span><code>target_freq</code></span></div><span class="ms-gate-arrow">&rarr;</span><div class="ms-gate"><strong>Range</strong><span><code>max_range_m</code></span></div><span class="ms-gate-arrow">&rarr;</span><div class="ms-gate"><strong>Beam</strong><span><code>beamwidth_deg</code></span></div><span class="ms-gate-arrow">&rarr;</span><div class="ms-gate ms-gate-end"><strong>Power</strong><span>EIRP &minus; path loss</span></div></div>
\endhtmlonly

A jammer that passes adds its EIRP minus the path loss to the node, using the
same channel model as the mesh links, buildings included. The powers add up:

\f[ J_r = \sum_{j} d_j \cdot 10^{\,(P_{tx,j} + G_{tx,j} - PL_{j \to r})/10} \f]

where \f$ d_j \f$ is `duty_cycle` for a `constant` jammer and 1 for a
`random` one. A link takes the larger total of its two ends:

\f[ SINR = \frac{S}{N + \max(J_a,\ J_b)} \f]

The file in section 1 at t = 0.3 s, seed 1. The jammer sits 50 m from every
node:

| Link | Signal \f$ S \f$ | Noise \f$ N \f$ | Jammer \f$ \max(J_a, J_b) \f$ | SINR |
|---|---|---|---|---|
| `node-a`–`node-b` | −31.7 dBm | −83.0 dBm | −35.0 dBm | 3.3 dB |
| `node-a`–`relay` | −23.2 dBm | −83.0 dBm | −21.2 dBm (at `relay`) | −2.0 dB |
| `node-b`–`relay` | −23.0 dBm | −83.0 dBm | −21.2 dBm (at `relay`) | −1.9 dB |

- The jammer is 48–62 dB above the noise, so SINR is close to
  \f$ S - J \f$ in dB. Without it these links run at 51–60 dB.
- Jammer paths have no free-space floor. Here a shadowing draw puts
  −21.2 dBm into `relay` from 50 m, 10.8 dB more than free space allows
  (−32.0 dBm).
- Under 1 m a jammer adds its full EIRP.
- SINR can go negative; below −6.7 dB a link carries nothing.

## 3\. On, off and timing

<div class="ms-keys ms-c-blue">
<div class="ms-key ms-key-head"><div>Field</div><div>What it does</div><div>Allowed values</div></div>
<div class="ms-key">
<div class="ms-key-name">`id`<span class="ms-key-def">default `""`</span></div>
<div class="ms-key-what">The name in `run.log`. It also seeds the `random` on/off pattern.</div>
<div class="ms-key-vals">any string</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`enabled`<span class="ms-key-def">default **`false`**</span></div>
<div class="ms-key-what">Turns the jammer on.<div class="ms-key-note">A jammer without this key does nothing.</div></div>
<div class="ms-key-vals">`true`, `false`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`type`<span class="ms-key-def">default `constant`</span></div>
<div class="ms-key-what">How `duty_cycle` applies: `constant` scales the power, `random` switches the jammer fully on or off each second (section 5).</div>
<div class="ms-key-vals">`constant`, `random`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`intervals`<span class="ms-key-def">default `[]`, always on</span></div>
<div class="ms-key-what">Time windows when the jammer may transmit, in seconds. A tick counts when its time is at or after `start` and before `end`.<div class="ms-key-note">A window ending at `duration_s` leaves the run's last tick clean.</div></div>
<div class="ms-key-vals">`[{start, end}, ...]`, `start` &ge; 0, `end` &gt; `start`<span class="ms-key-cli">or <code>&#45;&#45;jammer-onset-s=&lt;t&gt;</code>: every enabled jammer on from t to the end</span></div>
</div>
</div>

## 4\. Target band

<div class="ms-keys ms-c-purple">
<div class="ms-key ms-key-head"><div>Field</div><div>What it does</div><div>Allowed values</div></div>
<div class="ms-key">
<div class="ms-key-name">`target_freq`<span class="ms-key-def">default `[]`, every carrier</span></div>
<div class="ms-key-what">Which carriers the jammer hits, in MHz, compared with `[channel] frequency_ghz`.<div class="ms-key-note">One value: within ± 2.5 MHz of it. Two or more: anywhere from the lowest to the highest.</div></div>
<div class="ms-key-vals">MHz: none, one, or several</div>
</div>
</div>

Against the 2400 MHz carrier of section 1:

\htmlonly
<div class="ms-flow-art ms-scene ms-c-purple"><svg viewBox="0 0 620 210" aria-hidden="true"><line class="ms-faint" x1="150" y1="168" x2="610" y2="168"/><text x="150" y="186" text-anchor="middle">2250</text><text x="227" y="186" text-anchor="middle">2300</text><text x="303" y="186" text-anchor="middle">2350</text><text x="380" y="186" text-anchor="middle">2400</text><text x="457" y="186" text-anchor="middle">2450</text><text x="533" y="186" text-anchor="middle">2500</text><text x="610" y="186" text-anchor="middle">2550</text><text x="610" y="204" text-anchor="end">MHz</text><text x="140" y="29" text-anchor="end" class="ms-strong">[]</text><rect class="ms-soft" x="150.0" y="14" width="460.0" height="20" rx="2"/><text x="160" y="29">every carrier</text><text x="140" y="67" text-anchor="end" class="ms-strong">[2400]</text><rect class="ms-soft" x="376.2" y="52" width="7.7" height="20" rx="2"/><text x="394" y="67">2400 ± 2.5 MHz</text><text x="140" y="105" text-anchor="end" class="ms-strong">[2300, 2500]</text><rect class="ms-soft" x="226.7" y="90" width="306.7" height="20" rx="2"/><text x="237" y="105">2300 to 2500 MHz</text><text x="140" y="143" text-anchor="end" class="ms-strong">[5800]</text><text x="160" y="143">5800 ± 2.5 MHz: misses</text><line class="ms-bad" x1="380.0" y1="6" x2="380.0" y2="168"/><text x="386.0" y="162" class="ms-strong">carrier 2400</text></svg></div>
\endhtmlonly

## 5\. Power and reach

<div class="ms-keys ms-c-green">
<div class="ms-key ms-key-head"><div>Field</div><div>What it does</div><div>Allowed values</div></div>
<div class="ms-key">
<div class="ms-key-name">`tx_power_dbm`<span class="ms-key-def">default `25` dBm</span></div>
<div class="ms-key-what">Transmit power.</div>
<div class="ms-key-vals">dBm</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`tx_array_gain_dbi`<span class="ms-key-def">default `12` dBi</span></div>
<div class="ms-key-what">Antenna gain, added to `tx_power_dbm` to give the EIRP. The receiving node adds no gain.</div>
<div class="ms-key-vals">dBi</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`duty_cycle`<span class="ms-key-def">default `1`</span></div>
<div class="ms-key-what">`constant`: a power scale. `random`: the chance of being on in each whole second.</div>
<div class="ms-key-vals">0 to 1</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`max_range_m`<span class="ms-key-def">default `0`, no limit</span></div>
<div class="ms-key-what">Nodes farther than this, in 3-D, get nothing from this jammer.</div>
<div class="ms-key-vals">m; 0 or less for no limit</div>
</div>
</div>

`duty_cycle = 0.5` both ways, from a 10 s run of section 1's file:

\htmlonly
<div class="ms-flow-art ms-scene ms-c-green"><svg viewBox="0 0 620 130" aria-hidden="true"><line class="ms-faint" x1="150" y1="104" x2="600" y2="104"/><text x="150" y="122" text-anchor="middle">0 s</text><text x="236" y="122" text-anchor="middle">2 s</text><text x="321" y="122" text-anchor="middle">4 s</text><text x="407" y="122" text-anchor="middle">6 s</text><text x="493" y="122" text-anchor="middle">8 s</text><text x="579" y="122" text-anchor="middle">10 s</text><text x="140" y="34" text-anchor="end" class="ms-strong">constant, 0.5</text><rect class="ms-soft" x="150" y="28" width="450" height="12" rx="2"/><text x="140" y="80" text-anchor="end" class="ms-strong">random, 0.5</text><rect class="ms-soft" x="150.0" y="64" width="42.9" height="24" rx="2"/><rect class="ms-soft" x="235.7" y="64" width="42.9" height="24" rx="2"/><rect class="ms-soft" x="407.1" y="64" width="128.6" height="24" rx="2"/><rect class="ms-soft" x="578.6" y="64" width="21.4" height="24" rx="2"/></svg></div>
\endhtmlonly

- **`constant`** transmits all the time at half power: 3 dB less jamming.
  `node-a`–`node-b` reads 6.3 dB instead of 3.3 dB.
- **`random`** transmits at full power in about half of the seconds. Seed 1
  picked seconds 0, 2, 6–8 and 10: `node-a`–`node-b` reads 3.3 dB in those
  and 51.3 dB in the rest. The pattern comes from `id`, the seed and the
  second, so the same seed repeats it.

## 6\. Beam

A node inside the cone gets the jammer's full power; outside it, none.

<div class="ms-keys ms-c-amber">
<div class="ms-key ms-key-head"><div>Field</div><div>What it does</div><div>Allowed values</div></div>
<div class="ms-key">
<div class="ms-key-name">`beamwidth_deg`<span class="ms-key-def">default `360`&deg;</span></div>
<div class="ms-key-what">The cone's full width. `360` means every direction.</div>
<div class="ms-key-vals">above 0, up to 360</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`azimuth_deg`<span class="ms-key-def">default `0`&deg;</span></div>
<div class="ms-key-what">The compass direction it points.</div>
<div class="ms-key-vals">`0` north, `90` east, `180` south, `270` west</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`zenith_deg`<span class="ms-key-def">default **`0`**&deg;</span></div>
<div class="ms-key-what">The tilt from straight up.<div class="ms-key-note">The default points a narrow beam at the sky and misses ground nodes. Use `90` for a beam along the ground.</div></div>
<div class="ms-key-vals">`0` up, `90` horizontal, `180` down</div>
</div>
</div>

\image html jammer-beam.svg "p0-jammer-smoke from above with a 60-degree beam pointed east (azimuth_deg = 90, zenith_deg = 90). Link labels: seed-1 SINR at t = 0.3 s with no jammer, the tracked omni jammer, and the east beam."


With the beam pointed east only `node-b` is inside the cone. Both links that
touch `node-b` stay jammed, because a link takes the worse of its two ends;
`node-a`–`relay` is clean.

## 7\. Position and motion

Same frame as \ref nodes_json_coordinates "nodes.json". Jammers do not appear
in `positions.csv`; `run.log` shows each one's motion.

<div class="ms-keys ms-c-grey">
<div class="ms-key ms-key-head"><div>Field</div><div>What it does</div><div>Allowed values</div></div>
<div class="ms-key">
<div class="ms-key-name">`position`<span class="ms-key-def">default `{0, 0, 0}` m</span></div>
<div class="ms-key-what">Where a fixed jammer sits, or where a moving one starts.<div class="ms-key-note">Keep z ≥ 1 m with `scenario = RMa`, as for nodes.</div></div>
<div class="ms-key-vals">`{x, y, z}` in m</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`velocity`<span class="ms-key-def">default `{0, 0, 0}` m/s</span></div>
<div class="ms-key-what">Moves the jammer in a straight line when any part is nonzero.</div>
<div class="ms-key-vals">`{vx, vy, vz}` in m/s</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`waypoints`<span class="ms-key-def">default `[]`</span></div>
<div class="ms-key-what">A timed path. When set, `position` and `velocity` are ignored.</div>
<div class="ms-key-vals">`[{t, x, y, z}, ...]`, `t` increasing</div>
</div>
</div>

A `random_walk` block is read but never used: jammers do not wander.

## 8\. Common changes

`p0-jammer-smoke`, seed 1, `sinr_db` at t = 0.3 s, one change at a time:

| Change | Set | `node-a`–`node-b` | `node-a`–`relay` | `node-b`–`relay` |
|---|---|---|---|---|
| none (the file in section 1) | | 3.3 dB | −2.0 dB | −1.9 dB |
| No jammer | `"enabled": false`, or `--band=mmwave` | 56.1 dB | 56.1 dB | 56.7 dB |
| Target another band | `"target_freq": [5800.0]` | 56.1 dB | 56.1 dB | 56.7 dB |
| Target a range that includes the carrier | `"target_freq": [2300.0, 2500.0]` | 3.3 dB | −2.0 dB | −1.9 dB |
| Half power | `"duty_cycle": 0.5` | 6.3 dB | 1.0 dB | 1.2 dB |
| 10 dB weaker | `"tx_power_dbm": 20.0` | 13.3 dB | 8.0 dB | 8.1 dB |
| Shorter reach than any node | `"max_range_m": 40` | 56.1 dB | 56.1 dB | 56.7 dB |
| Point it east | `"beamwidth_deg": 60, "azimuth_deg": 90` | 6.1 dB | 59.9 dB | 10.1 dB |
| Start it at 0.2 s | `"intervals": [{"start": 0.2, "end": 1.0}]` or `--jammer-onset-s=0.2` | 3.5 dB | 2.0 dB | 2.6 dB |

Links shift by a few dB between rows even where the jammer is the same:
jammer paths take shadowing draws from the same random stream as the links,
so any change to the jammers changes later draws. The late start is clean at
t = 0 and 0.1 s and reads 3.5 / 2.0 / 2.6 dB at 0.3 s, not the first row's
values.

## 9\. Related

- \ref src_jammer "src/jammer": the jammer model and the `make_jammers` generator
- \ref files_run_ini "run.ini": `jammers_file`, `band`, `frequency_ghz`
- \ref files_buildings_json "buildings.json": buildings block jammer paths too
- \ref files_run_log "run.log": the `Jammers:` block

Previous: \ref files_buildings_json "buildings.json" · Up: \ref mesh_sim_files "Input and output files" · Next: \ref files_run_log "run.log"
