# buildings.json {#files_buildings_json}

[TOC]

`buildings.json` places box-shaped buildings in the scene. With at least one
building, geometry decides LOS for every link: a link is NLOS when the straight
line between the antennas passes through a box. A node inside a box loses
extra signal through the walls. `[scenario] buildings_file` in `run.ini` names
the file, relative to `run.ini`; blank means no buildings.

\htmlonly
<div class="ms-find" data-noun="field"><div class="ms-find-field"><svg class="ms-find-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg><input type="search" placeholder="Search fields, e.g. ext_walls, z_max, n_floors" aria-label="Search fields"><kbd class="ms-find-kbd">/</kbd></div><span class="ms-find-count"></span></div>
<script src="key-find.js"></script>
\endhtmlonly

## 1\. Anatomy

`inputs/baselines/03-building-blockage/buildings.json`, one building, part by
part:

\htmlonly
<div class="ms-ini">
<div class="ms-ini-row ms-c-blue">
<pre class="ms-ini-code">[
  {
    "id": "wall",
    "bounds": {
      "x_min": 90.0,  "x_max": 110.0,
      "y_min": -20.0, "y_max": 20.0,
      "z_min": 0.0,   "z_max": 20.0
    },</pre>
<div class="ms-ini-note"><strong>The box</strong>A 20 &times; 40 &times; 20 m block centered on (100, 0), standing on the ground. Its 20 m roof is above both nodes' 10 m antennas.</div>
</div>
<div class="ms-ini-row ms-c-purple">
<pre class="ms-ini-code">    "type":      "Office",
    "ext_walls": "ConcreteWithWindows",</pre>
<div class="ms-ini-note"><strong>Walls and use</strong>Low-loss walls for any node inside. The use, <code>Office</code>, is stored and changes nothing.</div>
</div>
<div class="ms-ini-row ms-c-green">
<pre class="ms-ini-code">    "n_floors":  3,
    "n_rooms_x": 2,
    "n_rooms_y": 4
  }
]</pre>
<div class="ms-ini-note"><strong>Floors and rooms</strong>3 floors of 2 &times; 4 rooms. They give an indoor node a floor and room and do not change loss.</div>
</div>
</div>
\endhtmlonly

The file is a JSON array with one object per box, even for a single building.
Keys the loader does not know are ignored.

## 2\. The box

All six bounds are required, in meters, in the
\ref nodes_json_coordinates "nodes.json frame".

<div class="ms-keys ms-c-blue">
<div class="ms-key ms-key-head"><div>Field</div><div>What it does</div><div>Allowed values</div></div>
<div class="ms-key">
<div class="ms-key-name">`id`<span class="ms-key-def">default `""`</span></div>
<div class="ms-key-what">A name, shown only in error messages.</div>
<div class="ms-key-vals">any string</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`bounds.x_min`, `x_max`<span class="ms-key-def">required</span></div>
<div class="ms-key-what">The west and east walls.</div>
<div class="ms-key-vals">numbers, min &lt; max</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`bounds.y_min`, `y_max`<span class="ms-key-def">required</span></div>
<div class="ms-key-what">The south and north walls.</div>
<div class="ms-key-vals">numbers, min &lt; max</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`bounds.z_min`, `z_max`<span class="ms-key-def">required</span></div>
<div class="ms-key-what">The floor and the roof. Use `z_min = 0` for a building on the ground.<div class="ms-key-note">Antennas above `z_max` see over the box.</div></div>
<div class="ms-key-vals">numbers, min &lt; max</div>
</div>
</div>

The bounds may also sit directly in the entry, without `bounds`. Boxes must
not overlap where a node or jammer can be: a node inside two boxes stops the
run.

## 3\. Walls, use, floors and rooms

Only `ext_walls` changes results, and only for a node inside the box.

<div class="ms-keys ms-c-purple">
<div class="ms-key ms-key-head"><div>Field</div><div>What it does</div><div>Allowed values</div></div>
<div class="ms-key">
<div class="ms-key-name">`ext_walls`<span class="ms-key-def">default `ConcreteWithWindows`</span></div>
<div class="ms-key-what">The wall class: how much signal an indoor node loses getting out (section 6). 3GPP models only.<div class="ms-key-note">`Wood` and `ConcreteWithWindows` are low loss; `ConcreteWithoutWindows` and `StoneBlocks` are high loss. An unknown value becomes `ConcreteWithWindows`.</div></div>
<div class="ms-key-vals">`Wood`, `ConcreteWithWindows`, `ConcreteWithoutWindows`, `StoneBlocks`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`type`<span class="ms-key-def">default `Residential`</span></div>
<div class="ms-key-what">The building's use. Stored, never used by mesh-sim.</div>
<div class="ms-key-vals">`Residential`, `Office`, `Commercial`</div>
</div>
<div class="ms-key">
<div class="ms-key-name">`n_floors`, `n_rooms_x`, `n_rooms_y`<span class="ms-key-def">default `1` each</span></div>
<div class="ms-key-what">Divide the box into floors and rooms, giving an indoor node a floor and room number. No effect on loss.<div class="ms-key-note">Keep them at 1 or more if a node can be inside: 0 stops the run.</div></div>
<div class="ms-key-vals">integers 1–255</div>
</div>
</div>

## 4\. What a building does to a link

Any building in the file switches **every** link to geometric LOS, whatever
`[channel] condition_model` says. Each tick, for each pair of antennas:

\htmlonly
<div class="ms-flow-split ms-routes ms-routes-5">
<div class="ms-flow-art ms-panel ms-c-green"><svg viewBox="0 0 200 120" aria-hidden="true"><line class="ms-faint" x1="6" y1="108" x2="194" y2="108"/><rect class="ms-bldg" x="70" y="44" width="60" height="64" rx="2"/><line class="ms-ink" x1="20" y1="24" x2="180" y2="24"/><circle class="ms-dot" cx="20" cy="24" r="6"/><circle class="ms-dot" cx="180" cy="24" r="6"/></svg><div class="ms-panel-cap"><strong>LOS</strong>Both outside; the line clears the roof.</div></div>
<div class="ms-flow-art ms-panel ms-c-amber"><svg viewBox="0 0 200 120" aria-hidden="true"><line class="ms-faint" x1="6" y1="108" x2="194" y2="108"/><rect class="ms-bldg" x="70" y="44" width="60" height="64" rx="2"/><line class="ms-bad" x1="20" y1="80" x2="180" y2="80"/><circle class="ms-dot" cx="20" cy="80" r="6"/><circle class="ms-dot" cx="180" cy="80" r="6"/></svg><div class="ms-panel-cap"><strong>NLOS</strong>Both outside; the line passes through a box.</div></div>
<div class="ms-flow-art ms-panel ms-c-amber"><svg viewBox="0 0 200 120" aria-hidden="true"><line class="ms-faint" x1="6" y1="108" x2="194" y2="108"/><rect class="ms-bldg" x="70" y="44" width="60" height="64" rx="2"/><line class="ms-bad" x1="100" y1="80" x2="180" y2="80"/><circle class="ms-dot" cx="100" cy="80" r="6"/><circle class="ms-dot" cx="180" cy="80" r="6"/></svg><div class="ms-panel-cap"><strong>NLOS + wall loss</strong>One node inside a box.</div></div>
<div class="ms-flow-art ms-panel ms-c-green"><svg viewBox="0 0 200 120" aria-hidden="true"><line class="ms-faint" x1="6" y1="108" x2="194" y2="108"/><rect class="ms-bldg" x="50" y="44" width="100" height="64" rx="2"/><line class="ms-ink" x1="75" y1="88" x2="125" y2="62"/><circle class="ms-dot" cx="75" cy="88" r="6"/><circle class="ms-dot" cx="125" cy="62" r="6"/></svg><div class="ms-panel-cap"><strong>LOS</strong>Both inside the same box.</div></div>
<div class="ms-flow-art ms-panel ms-c-amber"><svg viewBox="0 0 200 120" aria-hidden="true"><line class="ms-faint" x1="6" y1="108" x2="194" y2="108"/><rect class="ms-bldg" x="14" y="44" width="60" height="64" rx="2"/><rect class="ms-bldg" x="126" y="44" width="60" height="64" rx="2"/><line class="ms-bad" x1="44" y1="80" x2="156" y2="80"/><circle class="ms-dot" cx="44" cy="80" r="6"/><circle class="ms-dot" cx="156" cy="80" r="6"/></svg><div class="ms-panel-cap"><strong>NLOS</strong>Inside two different boxes. 3GPP adds wall loss.</div></div>
</div>
\endhtmlonly

- The test is in 3-D: antennas above the roof see over it.
- A node is inside when it is within the box, walls included. This is checked
  every tick, so a moving node can walk in and out.
- NLOS uses the channel model's NLOS formula (\ref files_channel_models "Channel models").
- Jammers follow the same rules on their paths to each receiver.
- In \ref files_links_csv "links.csv", `condition_reason` reads `building`
  on every link once the file has a building.

## 5\. Example: a node walks out from behind a wall

In `03-building-blockage`, `node-a` is fixed at (0, 0, 10) and `node-b` starts
at (200, 0, 10) and moves south at 2 m/s. The 20 m wall stands between them
until the line clears its corner at (90, −20). That happens at t = 22.2 s, when
`node-b` reaches y = −44.4 m.

\image html buildings-blockage.svg "03-building-blockage, seed 1. Left: the scene from above; the amber part of node-b's path is NLOS, the green part LOS. Right: link SINR with the building, and the same run with buildings_file blank and condition_model = static_los."


| Ticks | LOS | Mean SINR | Mean capacity |
|---|---|---|---|
| t = 0–22.2 s | NLOS | 13.7 dB | 1,845 Mbps |
| t = 22.3–30 s | LOS | 26.9 dB | 3,574 Mbps |
| Same run, no building, `static_los` | LOS | 28.9 dB | 3,836 Mbps |

At the corner SINR jumps from 14.8 to 29.4 dB in one tick. The 10 Mbps flow
gets through the whole time: 13.7 dB still carries 1.8 Gbps.

## 6\. Wall loss for a node inside

With a 3GPP channel model (TR 38.901 §7.4.3), a node inside a box adds:

\f[ PL_{O2I} = PL_{wall} + 0.5\, d_{in} + X, \qquad X \sim \mathcal{N}(0,\ \sigma^2) \f]

The wall term mixes glass and concrete, with \f$ f \f$ in GHz:

\f[ \begin{aligned}
\text{low loss:}\quad PL_{wall} &= 5 - 10\log_{10}\!\left(0.3 \cdot 10^{-L_{glass}/10} + 0.7 \cdot 10^{-L_{concrete}/10}\right) \\
\text{high loss:}\quad PL_{wall} &= 5 - 10\log_{10}\!\left(0.7 \cdot 10^{-L_{IRRglass}/10} + 0.3 \cdot 10^{-L_{concrete}/10}\right)
\end{aligned} \f]

\f[ L_{glass} = 2 + 0.2f, \qquad L_{IRRglass} = 23 + 0.3f, \qquad L_{concrete} = 5 + 4f \f]

| | Low loss (`Wood`, `ConcreteWithWindows`) | High loss (`ConcreteWithoutWindows`, `StoneBlocks`) |
|---|---|---|
| \f$ PL_{wall} \f$ at 28 GHz | 17.8 dB | 37.9 dB |
| \f$ PL_{wall} \f$ at 2.4 GHz | 12.1 dB | 23.7 dB |
| \f$ \sigma \f$ | 2.1 dB | 2.55 dB |

- \f$ d_{in} \f$ is how far inside the node is: the smaller of two random
  draws from 0–25 m (UMi, UMa) or 0–10 m (RMa). InH has no indoor term.
- `RMa` always uses low loss.
- The loss is drawn once per pair and kept while the pair stays indoor.
- ns-3 sets the variance of \f$ X \f$ to 4.4 and 6.5, so \f$ \sigma \f$ is
  2.1 and 2.55 dB. TR 38.901 gives \f$ \sigma \f$ = 4.4 and 6.5 dB.
- NYU ignores `ext_walls` and uses `[nyu_channel] o2i_loss_type`
  (\ref files_channel_nyu "NYU model").

Measured: a node at the center of a 20 × 20 × 20 m box, another outdoors 100 m
away, 28 GHz, `condition_model = static_los`, seed 1, mean `sinr_db`:

| Channel | No building | `ext_walls = Wood` | `ext_walls = StoneBlocks` |
|---|---|---|---|
| 3GPP UMi | 32.7 dB | −8.7 dB | −26.8 dB |
| 3GPP UMa | 35.5 dB | −1.5 dB | −19.6 dB |
| 3GPP RMa | 34.6 dB | 6.0 dB | 6.0 dB |
| 3GPP InH | 35.6 dB | −13.4 dB | −31.6 dB |
| NYU UMi | 35.6 dB | 5.5 dB | 5.5 dB |

The indoor node loses both the wall and LOS: the link becomes NLOS too.

## 7\. Common changes

| To | Set | What you'll see |
|---|---|---|
| Block a link | A box across the line between two antennas, roof above both | That link turns NLOS; about 13 dB less SINR in `03-building-blockage`. |
| Block it for longer | A wider box, e.g. `"y_min": -40.0` in 03 | NLOS for the whole 30 s run. |
| See over the building | Antennas above the roof, e.g. `"z": 25.0` in 03 | LOS throughout, 28.9 dB. |
| Heavier walls | `"ext_walls": "StoneBlocks"` | About 18 dB less SINR for an indoor node (3GPP UMi, UMa, InH; section 6). |
| Put a node indoors | Its `position` inside a box | All its links NLOS, plus wall loss. |
| Go back to probabilistic LOS | `buildings_file =` (blank) | LOS follows `condition_model` again. |
| Keep RL nodes out | `[rl] avoid_buildings = true` and `building_clearance_m` | Controlled nodes stay outside the boxes plus the clearance. |

## 8\. Related

- \ref files_nodes_json "nodes.json": the coordinate frame
- \ref files_channel_los "LOS, NLOS and shadowing": the other ways LOS is decided
- \ref files_links_csv "links.csv": `condition` and `condition_reason`
- \ref inputs_baselines "inputs/baselines": 03, 09 and 16 use buildings

Previous: \ref files_nodes_json "nodes.json" · Up: \ref mesh_sim_files "Input and output files" · Next: \ref files_jammers_json "jammers.json"
