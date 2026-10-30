# Transforms and assumptions {#mesh_sim_field_data_assumptions}

[TOC]

Between the raw radio logs and the final K-S number, we change the data in a
dozen small ways. This page walks through each one in the order the pipeline
does it: what we do, why, what it costs us, and how to change it. It starts
with the question everyone asks first: why not just use the whole day?

<!-- Every figure and number on this page comes from the synthetic practice bundle
     run through the real tools by docs/diagrams/field-example.py on 2026-10-28,
     mesh-sim commit b54bfbe7 plus the working tree, binary SHA-256
     d7a2f4d1eb52c30abb0c6cecc8480aa29232afd12730fcc402caa0fc446c9fe2,
     window 1500-1520, seeds 1-5. Figures: docs/diagrams/field-transforms.py,
     which only reads that run's files. The bundle is invented. -->

## 1\. Before you start

- You have run, or read, \ref mesh_sim_field_data_traces "Prepare field traces"
  through \ref mesh_sim_field_data_compare "Run and compare".
- The figures and numbers come from the **practice bundle** (window
  `1500-1520`, seeds 1–5). Its "field" values are invented, so they show what
  each step does, not how well the simulator matches real radios.

## 2\. Why we cut out one window instead of using the whole day

The simulator compares **one test event**, and a day of logs is not one test
event:

1. **The simulator needs one scenario.** A run is one `run.ini` and one
   `nodes.json`: one set of nodes, one radio setting, and one starting spot and
   path per node. The radio numbers in the logs (SNR, RSSI, MCS) are not
   inputs at all; they are what we ask the simulator to predict.
2. **A day holds several events.** We usually run several tests back to back,
   often with different nodes, layouts or settings. A scenario built from the
   whole day would match none of them.
3. **Idle time would swamp the result.** The comparison is two histograms, and
   every sample counts the same. Hours of parked vehicles, or driving between
   sites, would outweigh a 20-minute test.
4. **The motion would be far too coarse.** We reduce each node's track to 20
   waypoints. Over a 20-minute window that is one every minute; over an
   8-hour day, one every 25 minutes, which follows nothing.
5. **Gaps would turn into simulated time.** A pause in the logs, or overnight,
   would be simulated as if the nodes were there the whole time, sliding in a
   straight line across the gap.

The cost: fewer samples, and you pick the window by hand. If a window
straddles two events, you are back to mixing setups.

## 3\. Every change at a glance

| Step | What we change | Side | Change it with |
|---|---|---|---|
| Daily traces | Average the four antennas into one RCPI (4.1) | Field | Code only |
| Daily traces | Drop neighbors heard fewer than 5 times (4.2) | Field | Code only |
| Window | Cut by UTC clock, restart time at 0 (5.1) | Field | `--start`, `--end` |
| Scenario | Run length = how long the GPS covers (5.2) | Sim | `--time` |
| Scenario | GPS to meters on a flat map (6.1) | Both | Code only |
| Mobility | 20 waypoints, straight lines between (6.2) | Sim | `--n-waypoints` |
| Mobility | Hold still if the track fits in 20 m (6.3) | Sim | Code only |
| Convert | One value per pair, copied to both nodes (7.1) | Sim | Code only |
| Convert | Drop warm-up (7.2) | Sim | `warmup_s` in `run.ini` |
| Compare | Average the seeds (7.3) | Sim | Run one seed |
| Compare | Cap MCS at 12 (8.1) | Both | Code only |
| Compare | Scale histograms to the same area (8.2) | Both | Code only |

We never smooth a GPS track or a radio time series. The only averaging is
across a radio's antennas (RCPI) and across simulator seeds.

## 4\. The field radio values

### 4.1 RCPI: the average of the antennas that were receiving

Each radio report has four signal-strength readings, one per antenna. We
average them into one number, RCPI. When an antenna is not receiving, the
radio logs −110 dBm or below for it, so we leave those readings out; a dead or
blocked antenna should not drag the average down.

\f[ \text{RCPI} = \frac{1}{\lvert A \rvert} \sum_{a \in A} \text{RSSI}_a, \qquad A = \{\, a \in 1..4 : \text{RSSI}_a > -110 \text{ dBm} \,\} \f]

If all four are at or below −110 dBm, that report has no RCPI (its SNR and MCS
are still used).

**What to look for:** the red crosses at −120 dBm, and how far the dashed line
would drop if we kept them.

\image html field-rcpi-antennas.svg "unit-d's reports of unit-a for 3 minutes of the practice bundle (raw/unit-d/silvus/network_status.csv). Grey: the four raw antenna values. Blue: the RCPI we keep."

In these 3 minutes, 19 of 90 reports have antenna 4 blocked. Keeping those
readings would have pulled those reports 8.4 dB lower.

**The catch:**
- A genuine reading at −110 dBm or below looks the same as a blocked antenna,
  so it is dropped too.
- We average the dB numbers directly. While the antennas roughly agree, that
  is within a fraction of a dB of averaging the power.
- A report with one working antenna counts as much as one with four.

**To change it:** the −110 is a constant in `_load_net_stat`
(`scripts/arpo_data/loaders.py`).

### 4.2 Neighbors heard fewer than five times

When we build a node's trace, we leave out any neighbor it heard fewer than 5
times that day. One or two stray reports would only add noise.

**The catch:**
- The count is over the **whole day**, not the window. A neighbor heard 5
  times in the day but once in your window keeps that one sample.
- It is counted per metric, so a neighbor can stay in SNR and drop out of RCPI.
- In the practice bundle it removes nothing: each node heard each neighbor 413
  to 597 times in the window.

**To change it:** `_MIN_SAMPLES_PER_PEER_MAC` in `scripts/arpo_data/plots/bh2.py`.

## 5\. The window

### 5.1 Cutting by the UTC clock

We keep the rows whose UTC time falls inside the window you ask for, and then
restart each file's elapsed-time column at 0.

We cut on the UTC time (`t_utc`) because it is the only time column that means
the same thing in every file. Each file's elapsed seconds count from that
device's own first row, so "second 500" is a different moment on different
nodes. Cutting GPS and radio files on UTC keeps them all on one clock.

\f[ s_{\text{start}} \le \tau(t_r) < s_{\text{end}}, \qquad \text{sec}'_r = \text{sec}_r - \min_{r' \in \text{kept}} \text{sec}_{r'} \f]

where \f$\tau\f$ is seconds since UTC midnight.

**What to look for:** only the shaded band survives, and the lower panel shows
each file's clock starting again at 0.

\image html field-window-cut.svg "unit-b's SNR trace before (daily/2026-03-14/) and after (windows/1500-1520/) split-scenario &#45;&#45;start 15.00 &#45;&#45;end 15.20."

1,755 of 3,505 samples survive. The end is exclusive, so the report at exactly
15:20:00 is left out.

**The catch:**
- You set the start and end by hand, to the minute.
- After the cut, each file restarts at its own first kept row, so 0 in the GPS
  file and 0 in a radio file are not always the same moment.

**To change it:** `--start` and `--end` on `split-scenario`.

### 5.2 How long the simulation runs

The scenario runs for as long as the window's GPS covers: from the first fix
to the last, across all nodes.

We use the GPS because it is what places the nodes in time. Past the last
fix, every node would just sit still, adding parked time the field never had.

\f[ T = \max_r s_r - \min_r s_r \f]

Here \f$T\f$ = 1199 s, not 1200: fixes come once a second, from 15:00:00 to
15:19:59.

**The catch:**
- If the GPS starts late or stops early, the radio samples outside it are
  still in the field histogram, but the simulator never covers that time.
- A node whose GPS stops early stands still for the rest of the run.

**To change it:** `--time` on `build_config_files`, with the same `--duration`
and `--time-mode scale` or `clip` on `build_waypoints`.

## 6\. Positions and motion

### 6.1 GPS to meters on a flat map

The simulator works in meters, so we turn each GPS fix into meters east and
north of the day's average position. We treat the ground as flat, which is
simple and accurate enough over a test site.

\f[ x_E = (\lambda - \bar\lambda)\,k\cos\bar\varphi, \qquad y_N = (\varphi - \bar\varphi)\,k, \qquad k = 111{,}320 \text{ m per degree} \f]

Every window of a day shares the same origin. GPS altitude is never used.

**How far off is it?** At the practice site, distances come out at most about
0.3% wrong: 3 m on a 1.2 km link, worth about 0.05 dB of path loss. That is far
below anything else on this page.

**The catch:** heights are thrown away. Every node is placed at 1.5 m
(\ref mesh_sim_field_data_differences "Why the two sides differ" explains why
that matters).

**To change it:** code only (`plot_gps_tracks` in `scripts/arpo_data/plots/gps.py`).

### 6.2 Waypoints: 20 points, straight lines between

We reduce each node's GPS track to 20 waypoints, evenly spaced in time, and
the simulator moves the node in a straight line at constant speed from one to
the next. Twenty waypoints keep `nodes.json` small and readable. Each waypoint
is a real GPS fix, not an average.

\f[ \tau_k = t_0 + k\,\frac{t_N - t_0}{n - 1}, \qquad \mathbf{p}(t) = \mathbf{p}_k + \frac{t - t_k}{t_{k+1} - t_k}\,(\mathbf{p}_{k+1} - \mathbf{p}_k) \f]

**What to look for:** how far the straight-line path strays from the GPS track
between waypoints.

\image html field-waypoints.svg "unit-b in window 1500-1520: the GPS track (windows/1500-1520/gps_all_nodes_trace.csv) against the 20 waypoints build_waypoints wrote to scenarios/1500-1520/nodes.json. Left: the first lap. Right: the distance between them over the whole window."

unit-b drives a 6-minute loop, but its waypoints are a minute apart, so each
lap becomes a rough hexagon. Between waypoints the simulated node cuts across
the inside of the circle: 29 m off on average, 46 m at worst. It also travels
5% less distance, so it is a little slower. A node that drives straight
(unit-c) is only 1.5 m off on average, except at its turnaround; a slow
walker (unit-d) is at most 3.5 m off.

**The catch:**
- Corners get cut, as above. The more a node turns, the worse it is.
- Waypoints are spread over time, not distance, so a node parked for half the
  window spends half its waypoints standing still.
- One bad GPS fix that happens to be picked goes straight into the path.

**To change it:** `--n-waypoints` (more points, tighter path), `--time-mode`,
`--duration`, `--field-z`.

### 6.3 Nodes that did not move

If a node's whole track in the window fits in a 20 m box, we hold it still
at its first GPS fix. GPS wanders by a few meters even when a node is parked,
and adding up those wanders would look like motion. Checking the size of the
box instead of the path length ignores that jitter.

\f[ \max\left(\max x - \min x,\ \max y - \min y\right) \le 20 \text{ m} \f]

**The catch:**
- A node that really moved a few meters, like a person shuffling around, is
  held still.
- It is held at its first fix, not its average spot, so it can be up to 28 m
  from where it spent most of the window.
- In the practice bundle, unit-a never moved, so it is held still.

**To change it:** code only (`_MOBILE_BBOX_M` in `build_waypoints.py`).

## 7\. The simulator's output

### 7.1 One value per pair, copied to both nodes

The simulator computes each link once, for the pair. Each field radio,
though, lists every neighbor it heard. So when we convert the simulator's
output, we write each link's value under both nodes; otherwise each node
would list only half its neighbors.

**The catch:**
- Each link appears in two nodes' histograms.
- Real radios can measure the two directions differently; the simulator
  cannot.

**To change it:** code only (`_convert_one` in `sim_to_traces.py`).

### 7.2 Warm-up

We drop the simulator rows before `warmup_s` and restart time at 0. Generated
scenarios set `warmup_s = 0`, so nothing is dropped. The field side has no
warm-up.

**To change it:** edit `warmup_s` in the generated `run.ini`.

### 7.3 Averaging the seeds

We run the scenario with several seeds, and each seed draws different random
shadowing. Before comparing, we average the seeds row by row into one
pile the size of a single run, so the result does not hinge on one lucky or
unlucky draw.

\f[ v_j = \frac{1}{S}\sum_{s=1}^{S} x_{s,j} \f]

(If the seeds' files ever had different lengths, `compare` would join them
end to end instead; generated scenarios always give equal lengths.)

**What to look for:** the blue average wanders less than any single seed; on
the right, unit-b's whole histogram narrows only a little.

\image html field-seed-average.svg "Left: links.csv sinr_db for unit-a to unit-b in seeds 1-5 of batch/1500-1520. Right: unit-b's SNR pile from sim_traces/, seed 1 alone against the 5-seed average that compare uses."

On one link, the seeds scatter about 5 dB around their average, and averaging
5 seeds cuts that to about 2.3 dB. unit-b's whole histogram narrows less, from
an IQR of 14.0 dB to 12.5 dB, because most of its spread comes from distance,
which every seed shares.

**The catch:**
- The simulated histogram ends up narrower than any one run, while the field
  histogram keeps all of its variation. That makes the spreads harder to
  compare.
- MCS is averaged too, so simulated MCS values can be fractions like 5.8.

**To change it:** to compare a single run, use one seed (`run_batch --seeds 1`).

## 8\. The comparison

### 8.1 MCS capped at 12

The field radios never report MCS above 12, so we cap both sides at 12 to
compare like with like.

**The catch:**
- With the default `silvus` model the simulator never goes above MCS 6
  anyway, so the cap only matters with other capacity models.
- Silvus MCS 8 to 14 are the two-stream levels, so a higher index does not
  always mean a better link. A histogram of MCS mixes the two.

**To change it:** `_MCS_FIELD_CAP` in `compare.py`.

### 8.2 Scaling both histograms to the same area

The simulator gave unit-b 3,600 samples and the field 1,755. To compare the
shapes, we scale both histograms to an area of 1, and draw a smooth curve
(a KDE) over each.

\f[ h_b = \frac{c_b}{n\,w} \f]

where \f$c_b\f$ is the count in bin \f$b\f$, \f$n\f$ the side's sample count
and \f$w\f$ the bin width. The bins are chosen from both sides together.

**The catch:** the smooth curve rounds off sharp edges and integer values such
as MCS, and can spill past real limits. Trust the bars over the curve.

### 8.3 The numbers: K-S D and the gaps in median and mean

For each node and metric, `compare` reports how far apart the two piles are:

- **K-S D:** line up both piles from low to high, and at every value, compare
  the share of each pile below it. D is the biggest difference: 0 means
  identical, 1 means no overlap at all.
- **The median gap and the mean gap**, \f$\lvert\Delta\text{median}\rvert\f$ and
  \f$\lvert\Delta\text{mean}\rvert\f$: how far apart the middles are, in the
  metric's own units.

\f[ D = \max_x \left| F_{\text{sim}}(x) - F_{\text{field}}(x) \right|, \qquad \lvert\Delta\text{median}\rvert = \lvert m_{\text{sim}} - m_{\text{field}} \rvert \f]

**What to look for:** the red bar is D; the arrow is the median gap.

\image html field-ks-cdf.svg "unit-b's SNR: the 5-seed average from batch/1500-1520/sim_traces/ against windows/1500-1520/. The same arithmetic as compare._ks_2samp."

At 21.2 dB, 81% of the field samples are below the line but only 4% of the
simulated ones, so D = 0.77. The medians are 13.0 and 30.5 dB, 17.5 dB apart.

We report no p-value. With thousands of samples, a p-value calls almost any
difference "significant", even one too small to matter.

**The catch:** D stops at 1. Once the piles stop overlapping, a 20 dB gap and
a 40 dB gap both give D = 1. Always read D together with the median gap, which
keeps the size in dB.

**To change it:** `--metrics` picks the metrics; `--window N` keeps only the
first N seconds.

## 9\. Going further

- \ref mesh_sim_field_data_differences "Why the two sides differ": what these
  steps cannot remove.
- \ref scripts_validation "scripts/validation" and
  \ref scripts_arpo_data "scripts/arpo_data": every flag.
- \ref research_field_calibration "Field calibration limits": what we know
  about real comparisons.

Previous: \ref mesh_sim_field_data_read "Read the comparison" · Next: \ref mesh_sim_field_data_differences "Why the two sides differ"
