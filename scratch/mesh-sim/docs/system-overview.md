# System overview {#system_overview}

[TOC]

How the simulator, the files it writes and the visualizer fit together. The
numbered sections below follow the numbered bands in the diagram.

\image html system-overview.svg "Scenario files and Python tools feed the simulator, which writes run outputs that the visualizer reads"

For where each folder and file lives, and what uses what, see the
\ref mesh_sim_repo_map "Repository map".

## 1\. Scenario

A scenario is a folder under \ref Inputs "inputs/". The simulator reads it once
at the start of a run.

| File | Required | Holds |
|---|---|---|
| `run.ini` | yes | Run settings, in sections: scenario, channel (including band), traffic, routing, output, RL. |
| `nodes.json` | yes | The mesh nodes, with their positions and mobility. |
| `buildings.json` | no | Obstacles for the propagation model. |
| `jammers.json` | no | Jammers (used on the sub-6 band only). |

You can write a scenario by hand or have a Python tool build one, for example
from field data (see section 5). Every field of every file:
\ref mesh_sim_files "Input and output files".

## 2\. Simulator

`sim.cc` and the C++ modules in `src/`. A run has two parts.

**Once per run:**

1. Load `run.ini` and the JSON files, apply CLI overrides, and validate
   (`config/`, `cli/`).
2. Archive the inputs into the output folder and write `run.log` (`io/`).
3. For each seed, build the ns-3 nodes, mobility, buildings and propagation
   models (`setup/`).

**Every tick**, after advancing the ns-3 clock:

1. Evaluate every link for SINR, capacity and MCS (`eval/`, `jammer/`).
2. Update the flow-level traffic demands (`traffic/`).
3. Route the flows over multi-hop paths (`routing/`).
4. Write the per-tick outputs (`io/`).
5. In RL mode, exchange JSON with the Python environment over stdin/stdout
   (`rl/`).

More detail:

- \ref mesh_sim_run_flow "How a run works": each stage and the type that owns
  its data.
- \ref src "Simulator modules": one page per `src/` module.
- \ref mesh_sim_overview "Overview" and \ref readme_run "Run": module layout and
  commands.

## 3\. Run outputs

Results go to `<output-dir>/`, by default `outputs/YYYY-MM/DD/HH-MM-SS/` (see
\ref readme_where_output_lands "Output").

| Where | What | Written |
|---|---|---|
| Run folder | `inputs/` (archived scenario) and `run.log` | Once, before any seed runs |
| `seed-N/` | Six per-tick CSVs: positions, links, rx-power, mcs, flows, routes | Every `viz_tick_ms`; skipped with `--no-viz` |
| `seed-N/` | `summary.json` | Once, after the seed's last tick |

- `run.log` has a "Resolved config" block with the key values the run used, but
  not every setting. See \ref src_io_run_record "What a run records".
- RL training and evaluation artifacts are written by the Python tools to their
  own folders, not by the simulator. See \ref scripts_rl "RL workflows".
- Each file, column by column: \ref mesh_sim_files "Input and output files".
- File formats and schema versions are owned by \ref src_io "io",
  \ref src_rl "rl" and \ref Contributing "CONTRIBUTING".
- To read, graph or replay a run, see \ref mesh_sim_first_result "Understand the
  result": `scripts/plotting` turns a run folder into figures, and the
  visualizer replays it in 3D.

## 4\. Visualizer

The companion **ns3-mmwave-viz** is a browser app that reads run outputs and
never writes to them. It:

1. Finds the runs in a data folder you open.
2. Parses the CSV and JSON files and drives playback.
3. Renders the 3D scene and the RL experiment pages.

Start it with `npm install` and `npm run dev` in its checkout, then open
`http://localhost:5173`. Its own documentation covers loading, displays,
coordinates and missing data; it is linked from the \ref index "landing page".

## 5\. Python tools

The tools in `scripts/` never build the simulator. Those that run it take an
already-built binary with `--sim-binary <BIN>`. See \ref scripts "Python tools".

| Folder | Does |
|---|---|
| `arpo_data/` | Turns raw ARPO field data into per-day and per-scenario traces. |
| `validation/` | Builds scenarios from field data, batch-runs the simulator, and compares sim and field distributions. |
| `sweep/` | Runs parameter sweeps from a `sweep.ini`. |
| `rl/` | Gymnasium environment, training, evaluation and experiment tooling. |
| `baselines/` | Geometric and optimization placement planners. |
| `plotting/` | Plots from finished runs. |

## 6\. What the simulator can do

| Feature | Summary | Details |
|---|---|---|
| Link evaluation | SINR, capacity and MCS for every link, every tick, on mmWave or sub-6. | \ref src_eval "eval" |
| Mesh routing | Multi-hop routing of flow-level demands over the per-tick link table. | \ref src_routing "routing" |
| Field-data comparison | Build a scenario from field GPS and radio logs, run it, and compare SNR / RCPI / MCS with the field. | \ref mesh_sim_field_data_workflow "Field data workflow" |
| Jamming | Jammer power added to the SINR denominator on sub-6, driven by field-logged events. | \ref src_jammer "jammer" |
| Reinforcement learning | A Gymnasium environment over a stdin/stdout JSON bridge, with training and evaluation tools. | \ref scripts_rl "rl" |
| Placement baselines | Planners that score candidate layouts through the simulator's channel-query worker. | \ref scripts_baselines "baselines" |

## 7\. Maintaining this diagram

The figure is generated by `docs/diagrams/system-overview.py` into
`docs/diagrams/system-overview.svg`. Edit the script and re-run it from `docs/`:

```bash
python3 diagrams/system-overview.py
```

An identical copy of both files lives in the visualizer repository under
`docs/diagrams/`. Keep the two the same.
