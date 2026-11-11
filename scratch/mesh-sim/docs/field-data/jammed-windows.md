# Jammed windows {#mesh_sim_field_data_jamming}

[TOC]

How to compare a window that had a jamming trial in it: how to spot one, how to
give the simulator the same jammer, what the simulator assumes about it, and
why a jammed comparison can still differ from the field. Everything on
\ref mesh_sim_field_data_differences "Why the two sides differ" still applies;
this page covers only what jamming adds.

<!-- Every output on this page comes from day 2 of the synthetic practice bundle
     (2026-03-15, window 1000-1020, trial ew-1 at 10:05-10:15), run through the
     real tools by docs/diagrams/field-example.py on 2026-10-28, binary SHA-256
     d7a2f4d1eb52c30abb0c6cecc8480aa29232afd12730fcc402caa0fc446c9fe2, seeds 1-5.
     The jammer, the trial log and every "field" value are invented. Figures:
     docs/diagrams/field-jamming.py. -->

## 1\. Before you start

- You know the normal sequence, from
  \ref mesh_sim_field_data_traces "Prepare field traces" to
  \ref mesh_sim_field_data_read "Read the comparison".
- You have the trial log for the day: one row per jamming trial, with its
  start and end time, jammer type, position, heading, power and band.
- Jammers only affect the simulator in the `sub-6` band, which is what the
  field scenarios use.

The practice bundle has a second day for this page: 2026-03-15, a 20-minute
event (10:00–10:20) with one 10-minute directional jamming trial in the middle
(10:05–10:15). The practice script also writes its trial log,
`ew_trials.csv`, next to the bundle.

## 2\. Why a jammed window needs its own step

`build_config_files` never adds a jammer. It builds the scenario from GPS
tracks and radio settings only. So if you run a jammed window the normal way,
the simulator models a quiet channel while the field was being jammed, and the
comparison blames the jammer's effect on the channel model.

**What to look for:** how much each node's gap moves once the simulator gets
the jammer.

\image html field-jam-gaps.svg "Each node's SNR median gap in window 1000-1020 of the practice bundle: the scenario as generated (grey) against the same scenario with the trial's jammers.json (red). 5 seeds each."

unit-a, which sits in the jammer's beam, goes from a 17.4 dB gap to 7.2 dB.
Without the jammer, most of that 17 dB would look like a model error. The
other nodes move less, because the beam misses them most of the time.

## 3\. Spot a jammed window

Check the trial log first: any trial whose start and end overlap your window
affects it. The field data shows it too. A jammed radio's reports have a
distinctive signature:

- **SNR collapses while RSSI rises.** RSSI measures all the energy at the
  antenna, jammer included, so it goes **up** while the link quality goes
  down. In the practice bundle, unit-a's median SNR drops from 12.9 dB outside
  the trial to 3.0 dB during it, while its median RCPI rises from −84.2 to
  −76.3 dBm.
- **Reports thin out.** Links the radio can no longer hear stop being logged.
  unit-a logged 896 reports in the 10 minutes outside the trial and only 203
  in the 10 minutes during it.

If you see that pattern with no trial in the log, something unlogged was
interfering, and the window is not a clean comparison.

## 4\. Give the simulator the same jammer

Build the window's scenario as usual, then turn the trial log into a
`jammers.json` for it:

```bash
.venv/bin/python -m scripts.validation.make_jammers \
  --trials ew_trials.csv \
  --trace "$field_work/windows/$field_window/gps_all_nodes_trace.csv" \
  -o "$field_work/scenarios/$field_window/jammers.json" \
  --run-ini "$field_work/scenarios/$field_window/run.ini"
```

`--trace` is the window's GPS file; `make_jammers` uses it to line up time and
position with the scenario. `--run-ini` adds `jammers_file = jammers.json` to
the scenario. Then run, convert and compare as usual.

**Checkpoint:**

```
wrote .../scenarios/1000-1020/jammers.json  (1 jammer spec(s))
  ew-1: 33.01 dBm  az=258.0  bw=60.0  t=[300.0,900.0)s  pos=(381.49,32.14)
  patched .../scenarios/1000-1020/run.ini: jammers_file = jammers.json
```

One jammer per trial that overlaps the window. If it prints `0 jammer
spec(s)`, no trial overlaps the window's time.

### What `make_jammers` assumes

Each trial in the log becomes one jammer:

| Trial log | Becomes | What we assume |
|---|---|---|
| `start`, `end` (UTC) | `intervals`, in seconds from the window's first GPS fix | The jammer is on for exactly that span and off outside it. |
| `ew_strength (W)` | `tx_power_dbm` | Full power the whole time: `constant`, duty cycle 1. |
| `ew_gain (dBi)` | `tx_array_gain_dbi` | 12 dBi if the log leaves it blank (`--gain`). |
| `ew_approx_lat`, `ew_approx_lon` | `position` x, y | Placed in the scenario's meters by a fit to the window's own GPS columns; 2 m up (`--z`). |
| `ew_type` | `beamwidth_deg` | Directional means a 60° cone (`--beamwidth`); anything else, all directions. |
| `ew_approx_heading` | `azimuth_deg` | The cone points along the heading, level with the ground (`--zenith 90`). |
| `ew_band_range` | `target_freq` | The jammer hits our carrier if the carrier is inside that band. |

The power conversion is the usual one:

\f[ P_{\text{dBm}} = 10\log_{10}(P_{\text{W}}) + 30 \qquad 2 \text{ W} \rightarrow 33.0 \text{ dBm} \f]

The written `jammers.json`, for reference:

```json
{"id": "ew-1", "enabled": true, "type": "constant", "duty_cycle": 1.0,
 "tx_power_dbm": 33.01, "tx_array_gain_dbi": 10.0, "target_freq": [2440.0, 2460.0],
 "beamwidth_deg": 60.0, "azimuth_deg": 258.0, "zenith_deg": 90.0, "max_range_m": 0.0,
 "position": {"x": 381.49, "y": 32.14, "z": 2.0},
 "intervals": [{"start": 300.0, "end": 900.0}]}
```

Every field is described on \ref files_jammers_json "jammers.json".

## 5\. How the simulator applies the jammer

Each tick, every receiving node adds up the jammer power reaching it: the
jammer's power plus gain, minus the path loss from the jammer, using the
**same** channel model as the mesh links. The jammer's power goes into the
noise side of SINR, and each link takes the worse of its two ends:

\f[ J_r = 10^{\,(P_{tx} + G_{tx} - PL_{j \to r})/10}, \qquad \text{SINR} = \frac{S}{N + \max(J_a,\ J_b)} \f]

SINR can go far below zero; there is no floor.

**What to look for:** which nodes sit inside the simulator's red cone, and how
the practice bundle's own beam fades off axis instead.

\image html field-jam-map.svg "Window 1000-1020 from above: the node tracks, jammer ew-1, the simulator's hard 60-degree cone (red dashed) and the practice bundle's smooth beam (amber)."

unit-a sits inside the cone the whole time. unit-b's loop drives through it,
and right past the jammer. unit-c and unit-d stay mostly outside.

### What it looks like on one link

**What to look for:** the red line falling during the trial, and the blue field
dots thinning out.

\image html field-jam-timeline.svg "The unit-a and unit-b link through window 1000-1020: the simulator without the jammer (grey), with it (red, seed 1), and unit-a's field reports of unit-b (blue)."

- **Outside the trial,** the two simulator lines agree; the jammer is off.
- **During the trial,** the red line drops by about 25 dB and lands in the
  same range as the field reports. The grey line doesn't move, which is the
  mistake section 2 warns about.
- **The two deep dips,** to about −50 and −60 dB, are unit-b driving right
  past the jammer, 37 m from it at 711 s. The field shows no reports there at
  all: the radio heard nothing, so it logged nothing (section 6).

## 6\. Why a jammed window can still differ

These come on top of everything on
\ref mesh_sim_field_data_differences "Why the two sides differ".

| What differs | Effect on the simulator |
|---|---|
| **The beam is a hard cone.** Full power inside 60°, nothing outside. A real antenna fades off axis and leaks behind. | Higher SNR just outside the cone, lower near its edges. In the practice bundle, a node 45° off axis still gets jammed in the field but not in the simulator. |
| **The jammer path is always line of sight**, with `static_los`, and has no free-space floor. Real trials have terrain, vehicles and trees in between. | Lower SNR (more jamming) where the real path was blocked. |
| **Full power, all trial long.** The log gives one power per trial; any pulsing, sweeping or ramping is lost. | Lower SNR if the real jammer was off part of the time. |
| **Approximate position, heading and power.** The log says "approx", and a few degrees of heading moves the cone edge by tens of meters at range. | Depends; check nodes near the cone edge. |
| **Band in or out.** If our carrier is inside `ew_band_range`, the jammer counts at full power, however wide its band. A real jammer spread over a wide band puts less power into our channel. | Lower SNR for wideband jammers. |
| **The worse of the two ends.** Each link takes the larger jammer power of its two nodes. A real radio pair can see the jammer differently at each end. | Lower SNR for links where only one end is jammed. |
| **What the radio reports.** We compare the simulator's SINR with the radio's `snr`. Whether the radio's number includes the jammer, and how the radio fights interference (filtering, changing channel), we can't see from the logs. | Unknown. |
| **RSSI counts the jammer; our RCPI does not.** The simulator's received power is the wanted signal only. | RCPI lower than the field during a trial. Compare RCPI only outside trials. |
| **Only heard reports are logged,** and jamming silences the most. | The field histogram is missing its worst moments, so the simulator looks lower. In the practice bundle, unit-a lost three quarters of its reports during the trial. |

The practical upshot: compare **SNR**, keep the trial's time span in mind
when you read the histograms, and treat RCPI and MCS from a jammed window
with care.

## 7\. Going further

- \ref files_jammers_json "jammers.json": every jammer field, with worked numbers.
- \ref src_jammer "src/jammer": how the simulator computes jammer power.
- \ref research_jammer_model "Jammer model": why the jammer is modeled this way.

Previous: \ref mesh_sim_field_data_differences "Why the two sides differ" · Next: \ref mesh_sim_field_data_extend "Extend the comparison"
