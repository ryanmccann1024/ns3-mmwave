# Read the comparison {#mesh_sim_field_data_read}

[TOC]

What each number and plot from `compare` means, read on the practice run from
\ref mesh_sim_field_data_compare "Run and compare": why the two sides differ,
how to test one reason, and what the comparison cannot tell you.

<!-- Every number and figure on this page comes from the synthetic practice bundle
     run through the real tools by docs/diagrams/field-example.py on 2026-10-28,
     binary SHA-256 d7a2f4d1eb52c30abb0c6cecc8480aa29232afd12730fcc402caa0fc446c9fe2,
     window 1500-1520, seeds 1-5. The bundle is invented, so the gaps here say
     nothing about the simulator against real radios. -->

## 1\. Before you start

- You have a `validation/` folder from
  \ref mesh_sim_field_data_compare "Run and compare", or you are reading
  someone else's.
- The examples are from the **practice bundle**. Its "field" values are
  invented by a simple path-loss formula, so the gaps below teach how to read
  a comparison; they say nothing about how the simulator matches real radios.
  What is known about that is in
  \ref research_field_calibration "Field calibration limits".

## 2\. One row of the result

`validation/metrics.csv` and `validation_summary.csv` hold one row per
compared node and metric. The row for `unit-b`'s SNR:

| Column | `unit-b`, `snr` | Meaning |
|---|---|---|
| `scenario`, `src_rab`, `metric` | `1500-1520`, `unit-b`, `snr` | Which scenario, node and metric the row is about. `peer_rab` is always `neighbors` in node mode. |
| `n_sim`, `n_field` | 3,600 and 1,755 | How many samples each side contributed (section 5 explains why they differ). |
| `sim_median`, `field_median` | 30.51 and 13.00 dB | The middle value of each side. |
| `abs_diff_medians` | 17.51 dB | How far apart the medians are. |
| `sim_mean`, `field_mean`, `abs_diff_means` | 33.43, 14.22, 19.21 dB | The same for the mean. |
| `sim_iqr`, `field_iqr` | 12.50 and 11.05 dB | The spread of each side: the width of its middle 50%. |
| `ks_statistic` | 0.77 | The two-sample Kolmogorov-Smirnov D: the largest gap between the two cumulative distributions, from 0 (identical) to 1 (no overlap). |

Read it as: the simulator puts `unit-b`'s links about 17.5 dB higher than the
field, with about the same spread, and the two piles overlap little (D = 0.77).

There is no p-value and no pass or fail. With thousands of samples, a p-value
would call almost any difference significant, so the tool reports only how big
the difference is. Deciding how big is too big is up to you, for your
question.

## 3\. One plot per node and metric

`validation/pngs/<node>/hist_<metric>__<node>_to_neighbors.png` overlays the
two distributions for one node and metric. Every plot has the same parts:

- The simulator is orange, the field is blue.
- Both histograms are scaled to area 1, so the shapes compare directly even
  though the simulator has twice as many samples.
- A smooth curve (KDE) sits over each histogram, and a dotted line marks each
  median.
- The subtitle repeats the row: K-S D, the median gap and the mean gap.
- The legend gives each side's sample count, median and mean.

The binning, the curve and the statistics are defined with equations on
\ref mesh_sim_field_data_assumptions "Transforms and assumptions", section 8,
which also draws K-S D as the gap between two cumulative curves.

### 3.1 SNR: a shift, not a change of shape

**What to look for:** whether the two curves have the same width, and how far
apart the dotted medians are.

\image html field-hist-snr.png "hist_snr__unit-b_to_neighbors.png: unit-b's SNR, simulator (orange) against the practice bundle (blue)."

The two curves have about the same shape and width, but one is shifted right
by about 17.5 dB. A **shift with the same shape** usually means a constant
offset: a gain, a loss, a noise figure or a transmit power that differs
between the two sides. Section 6 tests exactly that. A difference in
**width** would point elsewhere, for example to fading the simulator does not
model.

Read the shape, not only the numbers. Two distributions can have the same
median and a large D, for example when one is much wider.

### 3.2 RCPI: the same story, without the noise figure

**What to look for:** the size of the gap, compared with SNR's.

\image html field-hist-rcpi.png "hist_rcpi__unit-b_to_neighbors.png: unit-b's received power."

The gap is 15.5 dB instead of 17.5. RCPI is received power, so the noise
figure, which only affects SNR, plays no part in it. A gap that differs
between SNR and RCPI by a constant points at the noise figure.

### 3.3 MCS: the table's ceiling

**What to look for:** where the orange bars sit, compared with the spread of
the blue ones.

\image html field-hist-mcs.png "hist_mcs__unit-b_to_neighbors.png: unit-b's MCS index."

The simulator's bars all sit at or just below MCS 6. The generated scenario
uses the `silvus` capacity model, whose table is the radio's single-stream
MCS 0–6, so MCS 6 is as high as the simulator can go; values just below 6 are
seed averages, not real MCS levels. The field radios report up to MCS 12 here,
and the comparison clips both sides at 12. Whenever the simulated SNR is
high, this histogram measures the table's ceiling more than the channel.

### 3.4 Every node at once

The heatmaps in `summary/` put one statistic for one metric across all nodes.
**What to look for:** whether one node stands out, or all are off together.

\image html field-heatmap-snr.png "summary/heatmap_snr_dmedian.png: |Δmedian| of SNR for every node."

Every node is off by 15–20 dB, so the gap is not one bad node or one bad
track. `unit-d`, the one carried by a person, is furthest off. The practice
bundle gives handheld radios 6 dB of body loss that the simulator has no way
to know about.

## 4\. The two sides measure different things {#field_data_interpretation}

The metrics share names but are not the same quantity:

<!-- Metric comparison figure. Styles: .ms-stack in theme/mesh-sim.css.
     Sources: scripts/arpo_data/loaders.py (RCPI from rssi_ant1..4),
     scripts/validation/sim_to_traces.py (_METRIC_SPECS_NODE),
     compare.py (_METRICS, _MCS_FIELD_CAP) and src/eval/sinr-capacity.h (silvus table). -->
<div class="ms-stack">
<div class="ms-stack-row ms-stack-head"><div>Metric</div><div>Field</div><div>Simulator</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer"><code>snr</code> (dB)</div><div>The SNR the Silvus radio reported for each neighbor.</div><div class="ms-stack-replaced"><span class="ms-stack-tag">Related, not equal</span>Computed SINR per link (<code>links.csv</code> <code>sinr_db</code>), from a propagation model and the radio defaults.</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer"><code>rcpi</code> (dBm)</div><div>The mean of <code>rssi_ant1</code>–<code>rssi_ant4</code>; antennas at −110 dBm or below are dropped as "no signal" markers.</div><div class="ms-stack-replaced"><span class="ms-stack-tag">Related, not equal</span>Received power per link, including array gain (<code>rx-power.csv</code> <code>rx_power_dbm</code>).</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer"><code>mcs</code></div><div>The MCS the radio transmitted with, clipped at 12.</div><div class="ms-stack-replaced"><span class="ms-stack-tag">Different ceilings</span>The MCS index from the capacity model (<code>mcs.csv</code> <code>mcs_index</code>). With the generated <code>silvus</code> model it never exceeds 6.</div></div>
</div>

Beyond the names, two kinds of difference sit under every row:

- **What the pipeline did to the data.** Antennas averaged, one window cut,
  the track thinned to waypoints, one value per pair copied to both ends,
  seeds averaged. Each is on
  \ref mesh_sim_field_data_assumptions "Transforms and assumptions".
- **What the two sides cannot share.** The channel model, the simulator's
  abstractions (no interference, fixed gains, 1.5 m heights, always line of
  sight) and how the radios measure and which links they log. Each, with the
  direction it pushes the result, is on
  \ref mesh_sim_field_data_differences "Why the two sides differ".

The comparison ignores time: it compares two piles of values, not two time
series.

## 5\. Why the sample counts differ

In the example row, `n_sim` is 3,600 and `n_field` is 1,755:

- **Simulator:** 1,199 s at a 1 s tick, so 1,200 ticks, times 3 neighbors,
  gives 3,600. The 5 seeds all have that length, so they are averaged into
  one pile of 3,600, not joined into 18,000
  (\ref mesh_sim_field_data_assumptions "Transforms and assumptions", section 7.3).
- **Field:** `unit-b` reported each neighbor every 2 s, so about 600 reports
  per neighbor. Some were never heard (SNR too low), leaving 1,755.

Different counts are normal. The histograms are scaled to area 1, so they
still compare. A field count far below what the logging rate predicts means
links that were rarely heard.

## 6\. Test one reason: a controlled change

A gap shows that the two sides differ, not why. To test one reason, change one
setting, rerun, and see how much of the gap moves.

The practice bundle's radios have **4 dBi** antennas and a **7 dB** noise
figure, but the generator assumed 6 dBi and 5 dB. Rebuild the scenario with
the bundle's values into a separate `matched/` folder:

```bash
.venv/bin/python -m scripts.validation.build_config_files \
  -i "$field_work/windows" --day "$field_window" \
  --csv-dir "$field_csv_root" --band sub-6 --mode node \
  --name field-example-matched --tx-gain 4 --rx-gain 4 --noise-figure 7 \
  -o "$field_work/matched/scenarios"
```

**Checkpoint:** the `channel:` line now reads
`nf=7.0 dB  gain=4.0/4.0 dBi`.

Then repeat the rest on `matched/`: `build_waypoints` on
`$field_work/matched/scenarios/$field_window`, `run_batch` with
`--scenarios-dir "$field_work/matched/scenarios" --out "$field_work/matched/batch"`,
and `sim_to_traces` and `compare` on `$field_work/matched/batch/$field_window`,
with the same `--field-root` as before.

Expected change: 2 dB less gain at each end and 2 dB more noise is
\f$-2 - 2 - 2 = -6\f$ dB of SNR, and \f$-4\f$ dB of RCPI. What `unit-b` showed:

| `unit-b` | Defaults | Matched | Change |
|---|---|---|---|
| SNR median, sim | 30.51 dB | 24.51 dB | −6.00 dB |
| SNR \|Δmedian\| | 17.51 dB | 11.51 dB | −6.00 dB |
| SNR K-S D | 0.77 | 0.59 | −0.18 |
| RCPI \|Δmedian\| | 15.48 dB | 11.48 dB | −4.00 dB |

**What to look for:** the orange pile against its position in section 3.1.

\image html field-hist-snr-matched.png "The same SNR histogram with matched gains and noise figure: the orange pile moved 6 dB left."

The settings explain exactly the 6 dB they should, and no more. The 11.5 dB
left over is the propagation model: the simulator's 3GPP RMa line-of-sight
loss against the practice bundle's steeper, shadowed path loss. The next
controlled change would be `--channel-scenario` or `--condition-model`.

With real field data the same method applies, but the answer is not known in
advance. Change one setting at a time, keep each run in its own workspace, and
record what moved.

## 7\. Is this comparison usable?

Before drawing any conclusion, check:

- Every node you meant to compare has a row for each metric.
- No row is NaN, and `n_sim` and `n_field` are both large enough to draw a
  histogram from.
- The scenario's `duration_s` covers the window you meant; it is the span of
  the GPS samples, which can be shorter.
- Every moving node was `patched`, not `skipped`.
- Your run record (\ref mesh_sim_field_data_compare "Run and compare",
  section 2) names the binary, the bundle and the scenario.

## 8\. What it cannot tell you

The comparison shows how far apart two distributions are. It cannot tell you
why. A gap can come from the propagation model, a default radio setting,
missing buildings, which links each side counts, or the field radios' own
measurement method; \ref mesh_sim_field_data_differences "Why the two sides differ"
lists them. Section 6 is the way to separate them: one controlled change at a
time.

What we know so far about how the simulator compares with real field data,
and why, is in
\ref research_field_calibration "Field calibration limits". Read it before you
report a result.

## 9\. Follow-up tools

| Tool | Use it to |
|---|---|
| `scripts.validation.compare_runs` | Draw heatmaps across batches; it finds every `validation_summary.csv` under `outputs/`. |
| `scripts.validation.scenario_fidelity -m node` | Check that the scenario's moving and static nodes and starting distances match the field GPS. It prints tables and writes nothing. |
| `scripts.validation.compare_baseline` | Compare several scenarios against one baseline scenario, node by node, with signed differences. |
| `scripts.validation.validate_days` | Run the convert, compare and fidelity steps for many days, then `compare_runs` across them. Its `--time` flag is required but unused. |

Commands and flags: \ref scripts_validation "scripts/validation", section 2.

## 10\. Going further

- \ref mesh_sim_field_data_assumptions "Transforms and assumptions": every
  change the pipeline makes to the data, with equations.
- \ref mesh_sim_field_data_differences "Why the two sides differ": why the
  simulator may not line up, and in which direction.
- \ref research_link_model "Link model assumptions": what the simulator's link
  model includes and leaves out.

Previous: \ref mesh_sim_field_data_compare "Run and compare" · Next: \ref mesh_sim_field_data_assumptions "Transforms and assumptions"
