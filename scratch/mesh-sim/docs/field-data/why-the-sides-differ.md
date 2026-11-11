# Why the two sides differ {#mesh_sim_field_data_differences}

[TOC]

Even with every step on \ref mesh_sim_field_data_assumptions "Transforms and assumptions"
done right, the simulator and the field will not line up exactly. This page
lists why, in three groups: the channel model, the shortcuts the simulator
takes, and how the real radios measure. For each one it says which way it
pushes the simulated numbers, when we can tell, and what to do about it.

<!-- Sources: src/eval/link-evaluator.cc (EvaluateLink), src/eval/sinr-capacity.h,
     src/setup/topology-builder.cc, ns-3 src/propagation/model/
     three-gpp-propagation-loss-model.cc (RMa), docs/files/channel-*.md,
     scripts/validation/build_config_files.py, sim_to_traces.py, compare.py,
     scripts/arpo_data/loaders.py. Numbers: the practice-bundle run of
     docs/diagrams/field-example.py on 2026-10-28 (binary SHA-256
     d7a2f4d1eb52c30abb0c6cecc8480aa29232afd12730fcc402caa0fc446c9fe2);
     figure: docs/diagrams/field-transforms.py. -->

## 1\. Before you start

- You have a comparison you want to explain, from
  \ref mesh_sim_field_data_read "Read the comparison".
- "Higher" and "lower" below always mean the **simulated** value compared
  with the field. A direction tells you which way to look, not how big the
  effect is; to measure that, make one controlled change
  (\ref mesh_sim_field_data_read "Read the comparison", section 6).
- The practice-bundle numbers are only illustrations. Its "field" values are
  invented.

## 2\. The list at a glance

| What differs | Effect on the simulator | Section |
|---|---|---|
| The path-loss formula | Depends on the real site | 3.1 |
| Antennas at 1.5 m | Lower on long links, if real antennas sit higher | 3.1, 4.6 |
| Always line of sight | Higher where real links were blocked | 3.2 |
| Shadowing, averaged over seeds | Narrower | 3.3 |
| The free-space floor | Short links can't get better than free space | 3.4 |
| No fast fading | Narrower | 3.5 |
| No interference between nodes | Higher, if real SNR includes interference | 4.1 |
| MCS from signal alone, capped at 6 | Depends | 4.2 |
| One value per pair | Narrower | 4.3 |
| The same antenna gain in every direction | Higher, if real gain is below 6 dBi | 4.4 |
| The default noise figure | SNR off by the difference | 4.5 |
| Flat ground | Depends on the terrain | 4.6 |
| Straight-line motion | Depends on the paths | 4.7 |
| One radio setting for all nodes | Depends | 4.8 |
| Every pair counted, heard or not | Has a low tail the field can't have | 4.9 |
| How the radio estimates SNR | Unknown | 5.1 |
| Only heard links are logged | Field looks better, so the simulator looks lower | 5.2 |
| Body loss on carried radios | Higher | 5.3 |
| Antenna mounting | Depends | 5.4 |

## 3\. The channel model

### 3.1 The path-loss formula, and why antenna height matters

The generator sets up the 3GPP **RMa** (rural macro) model, always line of
sight. 3GPP fitted that formula to measurements of a tall base station
talking to a phone, but our nodes are peers, both down at 1.5 m. ns-3 runs the
formula anyway; it is the best fit we have for open rural ground, but it is
being used outside the setup it was measured for.

The formula has a **breakpoint**: up to a certain distance, loss grows like
free space; past it, loss grows twice as fast (40 dB per tenfold distance
instead of 20). The breakpoint depends on how high the two antennas are:

\f[ d_{BP} = \frac{2\pi\, h_A h_B f}{c} = \frac{2\pi \times 1.5 \times 1.5 \times 2.45\times10^{9}}{3\times10^{8}} = 116 \text{ m} \f]

With both antennas at 1.5 m that is only 116 m, so nearly every link in a
real test is past it, on the steep part.

**What to look for:** where the blue line leaves the free-space line, and the
gap to the amber line over 170–710 m, where most of unit-b's links are.

\image html field-pathloss.svg "Path loss against distance. Blue line: ns-3's RMa line-of-sight formula at 2.45 GHz with both nodes at 1.5 m. Blue dots: seed 1 of batch/1500-1520, every pair and tick. Amber: the formula field-example.py invented for the practice bundle."

At 500 m the simulator loses 107.4 dB and the practice bundle 118.5 dB, an
11.1 dB gap. That matches the 11.5 dB left after the controlled change on
\ref mesh_sim_field_data_read "Read the comparison". With real data you don't
know the field's curve in advance, but this is how to reason about one.

- **Effect:** depends on how the real site compares with RMa.
- **Height matters a lot.** Raise both antennas to 2 m and the breakpoint
  moves out to 205 m; a 500 m link then loses 4.8 dB less. If the real antennas
  sit higher than 1.5 m, the simulator reads low on long links.
- **To change it:** `--channel-scenario` (`UMi`, `UMa`, `InH`),
  `build_waypoints --field-z` for heights, or `channel_model = nyu` in
  `run.ini` (\ref files_channel_models "Channel models").

### 3.2 Always line of sight

`static_los` makes every link line of sight for the whole run. There is no
terrain, and no buildings unless you add a `buildings.json`, so nothing ever
blocks a link.

- **Effect:** higher, wherever real links were blocked by hills, buildings,
  vehicles or trees.
- **To change it:** `--condition-model auto` picks line of sight or not per
  pair by distance; a `buildings.json` decides it by geometry
  (\ref files_channel_los "LOS, NLOS and shadowing").

### 3.3 Shadowing

The 3GPP model adds random **shadowing**: a slowly changing up-or-down offset
on each link, as if passing obstacles too small to model. It is 4 dB typical
inside the breakpoint and 6 dB beyond, and each seed draws it fresh. In the
figure above, the dots scatter about 6 dB around the line, as expected.

- **Effect:** none on the middle (it averages to zero), but the histogram is
  narrower once `compare` averages the seeds
  (\ref mesh_sim_field_data_assumptions "Transforms and assumptions", section 7.3).

### 3.4 The free-space floor

We never let a link's loss drop below free-space loss, the best a link can
physically do:

\f[ PL = \max\left(PL_{\text{model}},\ 20\log_{10} d + 20\log_{10} f - 147.55\right) \f]

Up to the breakpoint, RMa sits right on free space, so any lucky shadowing
draw on a short link gets cut off. Short links therefore only ever get worse
than the formula, never better. In the figure, no dot falls below the dashed
line.

- **Effect:** on short links, the simulator is a little lower and narrower than
  the formula alone. Against the field: depends.

### 3.5 No fast fading

Real signals flicker many times a second as reflections add up and cancel
(multipath fading). The simulator has no such term: each tick's value is the
steady average a link would have.

- **Effect:** the simulated histogram is narrower. Whether the middle moves
  depends on how much the radio averages before it reports SNR, which we don't
  know (5.1).

## 4\. The simulator's shortcuts

### 4.1 No interference between nodes

The simulator's SINR is the signal over the radio's own noise:

\f[ \text{SINR} = P_{rx} - N, \qquad N = -174 + 10\log_{10} B + \text{NF} \ \text{(dBm)} \f]

with \f$B\f$ the bandwidth in Hz and NF the noise figure. Other nodes'
transmissions never add to it. Jammers do, but only in `sub-6` with a
`jammers.json` (\ref mesh_sim_field_data_jamming "Jammed windows").

- **Effect:** higher, if the radios' reported SNR includes interference from
  other nodes or outside sources.

### 4.2 MCS: chosen from the signal alone, and capped at 6

The simulator reports the best MCS the SINR allows. Real radios also adapt to
traffic: with little to send, they often use a lower MCS than the link could
take. We model traffic as flows, not packets
(\ref research_flow_abstraction "Flow abstraction"), so there is no rate
adaptation. And with the default `silvus` model, MCS stops at 6, the top
single-stream level; we don't model two-stream (MIMO) operation.

- **Effect:** two pulls in opposite directions. No rate adaptation makes
  simulated MCS **higher**; the cap at 6 makes it **lower** whenever the radios
  use the two-stream levels 8–14.
- **What to do:** read MCS last, after SNR.

### 4.3 One value per pair

The simulator computes each link once and copies it to both nodes. Real
radios measure each direction separately, each with its own antenna, noise
and surroundings.

- **Effect:** narrower. Direction-to-direction differences only show up as
  extra spread on the field side.

### 4.4 The same antenna gain in every direction

Every link gets the same transmit and receive gain, 6 dBi each by default:

\f[ P_{rx} = P_{tx} - PL + G_{tx} + G_{rx} \f]

Real antennas are stronger in some directions than others, and a vehicle's
body shades them.

- **Effect:** higher, if the real gain is below 6 dBi. In the practice bundle
  the radios have 4 dBi, which accounts for 4 dB of the gap.
- **To change it:** `--tx-gain`, `--rx-gain`.

### 4.5 The noise figure

The generator uses a 5 dB noise figure, which sets the noise \f$N\f$ in 4.1.
We treat it as a property of our radios, not a setting to tune per run.

- **Effect:** for every dB the real receivers are noisier than 5 dB, the
  simulated SNR reads that much higher. RCPI is not affected.
- **To change it:** `--noise-figure`.

### 4.6 Heights and flat ground

Every node is at 1.5 m unless `build_waypoints --field-z` sets another height,
and the ground is flat. We don't use GPS altitude.

- **Effect:** see 3.1: if real antennas are higher, the simulator reads low on
  long links. Hills and dips aren't modeled at all.

### 4.7 Straight-line motion, sampled once a second

Nodes move in straight lines between waypoints, and the simulator samples
them once per 1 s tick. On the practice bundle's loop, unit-b's simulated
position is 29 m off its GPS track on average and 46 m at worst
(\ref mesh_sim_field_data_assumptions "Transforms and assumptions", section 6.2).

- **Effect:** depends. Cutting a corner brings a node closer to one neighbor
  and farther from another.
- **To change it:** `--n-waypoints`, `--tick`.

### 4.8 One radio setting for every node

Frequency, bandwidth and transmit power are each the median across nodes of
their `config.csv`. If settings changed during the day, or differed between
nodes, they become one value.

- **Effect:** depends.
- **What to do:** check the `channel:` line `build_config_files` prints
  against the radios' logs.

### 4.9 Every pair counts, every tick

The simulated histogram includes every pair at every tick, however weak, even
links no real radio would have heard.

- **Effect:** the simulated histogram can have a low tail that the field
  histogram can't have (5.2).

## 5\. How the real radios measure

### 5.1 How the radio works out SNR

We take the radio's `snr` column as it comes. We don't know exactly how the
radio estimates it: which signals it measures, across which antennas, or how
it averages.

- **Effect:** unknown.

### 5.2 Only heard links are logged

A radio only logs a neighbor it actually heard. Weak links drop out of the
field data, so the field histogram is missing its bottom. (The practice
bundle, for example, logs nothing below −2 dB.)

- **Effect:** the field looks better than its links really were, so the
  simulator looks **lower** next to it.

### 5.3 Body loss

A radio carried by a person loses signal into the body. The simulator has no
such loss.

- **Effect:** higher for carried radios. The practice bundle gave unit-d 6 dB
  of body loss, and unit-d has the biggest SNR gap (20.0 dB against 15.5–17.7 dB
  for the others).

### 5.4 Antenna mounting

Where an antenna is mounted (roof or bumper, how high, which way it faces)
changes what a real radio receives. The simulator puts every antenna at one
height with one gain.

- **Effect:** depends; 3.1 and 4.4 cover the two parts we can reason about.

## 6\. From a gap to a cause

| The comparison shows | Look first at |
|---|---|
| Same shape, just shifted | Gains, noise figure, transmit power, body loss (4.4, 4.5, 5.3) |
| A gap that grows with distance | The path-loss formula and the heights (3.1, 4.6) |
| The simulator narrower | Seed averaging, no fast fading, one value per pair (3.3, 3.5, 4.3) |
| RCPI matches but SNR doesn't | The noise figure (4.5) |
| MCS off while SNR matches | Rate adaptation and the MCS 6 cap (4.2) |

Then test the likely cause with one controlled change
(\ref mesh_sim_field_data_read "Read the comparison", section 6).

## 7\. Going further

- \ref research_field_calibration "Field calibration limits": what we know
  about real comparisons. Read it before reporting a result.
- \ref research_link_model "Link model assumptions": what the link model
  includes and leaves out.
- \ref files_channel_capacity "SINR and capacity": the noise floor and the MCS
  tables.

Previous: \ref mesh_sim_field_data_assumptions "Transforms and assumptions" · Next: \ref mesh_sim_field_data_jamming "Jammed windows"
