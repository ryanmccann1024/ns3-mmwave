# Research record: field calibration limits {#research_field_calibration}

<!-- TODO: encrypt this page with git-crypt before it is committed or pushed.
     Also encrypt evidence/research-slide-text.txt, have the Doxyfile skip both
     when the checkout is locked, and trim the field-calibration summaries on
     index.md and sources.md. Plan agreed 2026-10-27; not set up yet. -->

[TOC]

How we processed the ARPO field data, what we did not know about the radios,
and how close tuning got the simulator to the field measurements.

Back to \ref mesh_sim_research "Research records" · all decks:
\ref mesh_sim_research_sources "Research sources".

## 1\. Background

From May to June we compared simulated SNR and RCPI against field radio logs
and tuned the simulator configuration to match. This page covers how the field
data were reduced, which radio parameters were unknown, and the results.

## 2\. Processing the field data

Each radio in the source CSVs showed four MAC addresses, each with its own SNR,
MCS and so on. The simulator does not model this, so we reduced it
(R05 slide 2):

1. **Per-second maximum.** Take the greatest value across the four MACs each
   second, assuming one antenna is active. One-second windows give one value
   per second, like the simulator.
2. **30 s running median.** Smooth with a 30-second running median to reduce
   noise. A median because SNR can be heavily tailed.

Averaging was noted as a possible improvement, and the per-second maximum does
not model a switch between antennas well (R05 slide 2).

Today field RCPI is the mean of the four `rssi_ant*` columns (values at or
below −110 dBm are dropped), and traces keep their UTC timestamps. See
\ref field_data_interpretation "How to read the result".

## 3\. Simulation setup and unknowns

The setup used for the comparison (R07 slides 13–14):

- **Frequency:** 60–70 GHz (802.11ad/ay channel 4 in the radio config).
- **Channel model:** NYU, because the 3GPP model only goes to 20 GHz.
- **Motion:** a new feature that moves nodes from their GPS coordinates.
- **Power:** RSSI/RCPI come from the radio logs, but Tx power and the Tx/Rx
  array gains are unknown.
- **Noise figure:** could not be found.
- **Approximate:** building geometry and heights, antenna array gains, and
  device heights.

With this many unknowns, we swept only some of the variables (R07 slide 14).

## 4\. First comparison

After the first comparison, we listed what could be causing the mismatch
(R07 slide 21):

- Tx power, Tx/Rx array gains, noise figure and node heights.
- The NYU channel model. No channel model will match the field 100%.
- A LOS/NLOS probability issue, to be checked against the NYU model's
  assumptions and a visual.

We added per-node gains so each node can have its own array gain
(R07 slide 21). This is still how gains work; see \ref research_link_model.

## 5\. Tuning results

We tuned a "best config" and compared it on three simulated days from the old
dataset, since a bug in the new dataset script may have affected accuracy
(R08 slide 10). Results with the best config (R08 slide 14):

| Dataset | Average SNR mean difference | Average RCPI mean difference |
|---|---|---|
| Calfex | < 10 dB | ~10 dB |
| Jeddoc | ~14 dB | ~19 dB |

Accuracy was not consistent between datasets, and changing the noise and tick
values changed it (R08 slide 14).

## 6\. Splitting by time window

We wrote a script for the ARPO data that splits each day by UTC start and end
times, then simulated and compared four windows: 14:20–14:30, 14:46–14:58,
15:38–15:45 and 16:35–16:56 (R09 slide 2). The GeoTak box times did not match
the dataset times, so we assumed a +4-hour offset (R09 slide 2).

Results (R09 slide 12):

- The noise setting needed adjusting; the gain values could stay constant.
- Adjusting noise brought simulated SNR to within about 10 dB of the field.
- The config applies to every node, so windows where only some nodes are
  affected by noise compare poorly.

## 7\. Where this lives now

- \ref mesh_sim_field_data_workflow "Compare the simulator with field data":
  the current end-to-end workflow and how to read its results.
- \ref scripts_arpo_data "scripts/arpo_data": extraction, UTC splitting and
  column definitions.
- \ref scripts_validation "scripts/validation": scenario building, batch runs
  and distribution comparison.

## 8\. Sources

The original decks are on OneDrive. If you have a question about a specific
assumption, open the presentation and slide listed here. The slide text and
speaker notes are also in
<a href="research-slide-text.txt">research-slide-text.txt</a>.

| ID | Presentation | What it covers | Slides used here |
|---|---|---|---|
| R05 | 05-06.pptx | How the multi-MAC field data were reduced to one value per second and smoothed | 2 |
| R07 | 05-14 Update.pptx | Simulation setup for the field comparison, unknown radio parameters, and what could cause the mismatch | 13–14, 21 |
| R08 | June-16-2026.pptx | Tuning a best config and the resulting SNR/RCPI differences per dataset | 10, 14 |
| R09 | June-23-2026.pptx | Splitting days into UTC windows, the +4-hour offset, and noise tuning results | 2, 12 |
