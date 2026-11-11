# Compare the simulator with field data {#mesh_sim_field_data_workflow}

[TOC]

What the ARPO field data is, why the simulator is compared against it, and the
pages that take one day of radio logs to a sim-versus-field comparison.

## 1\. What the field data is

ARPO field tests put real Silvus radios on vehicles, people and drones, and
logged two things on every node:

- **GPS**: where the node was, once per fix.
- **Radio statistics**: for each neighbor the radio heard, its reported SNR,
  per-antenna RSSI and MCS, plus throughput and packet error rate.

Each node's logs are a folder of CSV files. The current format, used by the
CalFEX tests, is the **per-node Silvus bundle**: one folder per node, each with
a `gps/` and a `silvus/` folder. Spring Lake, an earlier mmWave campaign, used
an older format (`bh2.csv` per node); these pages cover the sub-6 Silvus data
only.

The bundle is external and private. It is not in the repository and is
git-ignored if you copy it in; ask the data owner for it. To learn the
pipeline without it, use the synthetic practice bundle
(\ref mesh_sim_field_data_traces "Prepare field traces", section 2).

## 2\. Why compare

The simulator computes link quality from ns-3 propagation models and a few
radio settings. Field data shows what real radios measured in the same kind of
place. Comparing the two answers one question:

> For the same nodes moving the same way, does the simulator produce link
> quality in the same range as the radios reported?

The comparison is **distributional**. For each node and metric it draws the
simulated and the measured values as two histograms and measures how far apart
they are. It does not line up samples in time, and it does not say whether a
difference is acceptable. That judgment is yours;
\ref mesh_sim_field_data_read "Read the comparison" explains what the numbers
can and cannot show.

## 3\. The pipeline

Two Python packages do the work. `scripts/arpo_data` reads the raw logs;
`scripts/validation` builds and runs scenarios and compares them.

<!-- Pipeline figure. Styles: .ms-gates in theme/mesh-sim.css. Steps follow
     scripts/arpo_data/CLAUDE.md (data flow) and scripts/validation/CLAUDE.md
     (sim-vs-field pipeline). -->
\htmlonly
<div class="ms-gates">
<div class="ms-gate"><strong>1. Traces</strong><span>one day</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>2. Window</strong><span>one test event</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>3. Scenario</strong><span>settings and nodes</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>4. Mobility</strong><span>GPS waypoints</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>5. Run</strong><span>every seed</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>6. Convert</strong><span>sim to traces</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate ms-gate-end"><strong>7. Compare</strong><span>histograms</span></div>
\endhtmlonly

Steps 1 and 2 are subcommands of `scripts.arpo_data.cli`. Steps 3–7 are
modules of `scripts.validation`. Each runs as `python -m scripts.<package>.<module>`.

| Step | Command | Reads | Writes (under `$field_work`) |
|---|---|---|---|
| 1 | `plot --nodes` | Raw per-node bundle | `daily/<day>/`: per-node `IH_*` traces and `gps_all_nodes_trace.csv` |
| 2 | `split-scenario` | One `daily/<day>/` folder | `windows/<HHMM-HHMM>/`: the same layout, cut to a time window |
| 3 | `build_config_files` | The window, and the raw `silvus/config.csv` files | `scenarios/<HHMM-HHMM>/run.ini` and `nodes.json` |
| 4 | `build_waypoints node` | The scenario and the window's GPS | Edits `nodes.json` in place |
| 5 | `run_batch` | The scenario and your simulator binary | `batch/<HHMM-HHMM>/seed-N/`, one folder per seed |
| 6 | `sim_to_traces -m node` | The seed folders | `batch/<HHMM-HHMM>/sim_traces/`: simulator output in the field trace layout |
| 7 | `compare -m node` | Simulator traces and field traces | Histograms, `metrics.csv`, `validation_summary.csv`, heatmaps |

Step 6 is what makes step 7 simple. It rewrites the simulator's CSVs into
**exactly the same trace files** that step 1 writes for the field, so one
reader loads both sides.

Raw data is never written to. Everything derived goes under one workspace
folder in `outputs/`, which Git ignores.

Every step changes the data a little: it averages antennas, cuts a time
window, thins the GPS track to waypoints, averages seeds. Why the pipeline
compares one window rather than the whole day, and the equation and cost of
each change, are on \ref mesh_sim_field_data_assumptions "Transforms and assumptions".

## 4\. Terms used in this sequence

| Term | Meaning |
|---|---|
| **Node** | One radio. Its name is the name of its folder in the raw bundle, and that name is used everywhere downstream. |
| **Day** | One UTC calendar date of logs, `YYYY-MM-DD`. |
| **Window** | One stretch of clock time within a day, for example one test event. Its tag is `HHMM-HHMM` (start and end, UTC), and folders are named after it. |
| **Trace** | A CSV of one metric for one node over time, for example `IH_snr__rab1_to_neighbors_trace.csv`. `IH_` marks the current Silvus format. |
| **Workspace** | The folder, `$field_work`, that holds every derived file for one attempt. |
| **Scenario result folder** | `batch/<HHMM-HHMM>/`: the simulator's output for one scenario, holding `inputs/` and `seed-N/`. Steps 6 and 7 take this folder, not the batch root. |
| **Seed** | One simulator run of the scenario. The comparison pools all seeds. |

## 5\. What you will do

1. \subpage mesh_sim_field_data_traces "Prepare field traces": check the raw
   bundle, build per-day traces and cut one time window (steps 1–2).
2. \subpage mesh_sim_field_data_scenario "Build a scenario from field data":
   turn the window into a `run.ini` and a `nodes.json` that moves like the
   field nodes did (steps 3–4).
3. \subpage mesh_sim_field_data_compare "Run and compare": run the simulator
   over several seeds, convert its output and compare (steps 5–7).
4. \subpage mesh_sim_field_data_read "Read the comparison": what each number
   and plot means, and what the comparison cannot tell you.
5. \subpage mesh_sim_field_data_assumptions "Transforms and assumptions": why a
   window and not the whole day, and every change the pipeline makes to the
   data, with its equation, its reason and its cost.
6. \subpage mesh_sim_field_data_differences "Why the two sides differ": the
   channel model, the simulator's abstractions and the field measurement, and
   which way each pushes the result.
7. \subpage mesh_sim_field_data_jamming "Jammed windows": how to compare a
   window with a jamming trial in it, what the simulator assumes about the
   jammer, and why jammed results can still differ.
8. \subpage mesh_sim_field_data_extend "Extend the comparison" (optional):
   where every module lives, and how to add a metric, a day or a scenario.

Every page works without the private bundle. Page 1 shows how to make a
**synthetic practice bundle** with the same layout and invented values, and all
the output and figures in this sequence come from it.

## 6\. Going further

- \ref research_field_calibration "Field calibration limits": what is known
  about how simulator output compares with field data, and why.
- \ref scripts_arpo_data "scripts/arpo_data" and
  \ref scripts_validation "scripts/validation": every flag and output of the
  two packages.
- \ref mesh_sim_first_run "Your first run": run the simulator by hand if you
  have not yet.

Next: \ref mesh_sim_field_data_traces "Prepare field traces"
