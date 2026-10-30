# Quickstart {#mesh_sim_quickstart}

[TOC]

Every command from a fresh build to a run you can graph and replay in 3D.
Each step links to the page that explains it.

\htmlonly
<div class="ms-gates">
<div class="ms-gate"><strong>2. Build</strong><span>once</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>3. Run</strong><span>under a second</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>4. Check</strong><span><code>summary.json</code></span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>5. Graph</strong><span><code>figures/</code></span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate ms-gate-end"><strong>6. Replay</strong><span>in 3D</span></div>
</div>
\endhtmlonly

## 1\. Before you start

| You need | Notes |
|---|---|
| Git, Python 3, CMake 3.13+, a C++20 compiler | Where these minimums come from: \ref mesh_sim_install_build "Install and build". |
| Node.js and npm | Only for step 6 (the 3D visualizer). |

Run every command from the ns3-mmwave repository root unless a step says
otherwise.

## 2\. Build

```bash
./ns3 configure --build-profile=debug \
  --enable-modules=core,network,mobility,propagation,buildings \
  --disable-examples --disable-tests -- -DNS3_WARNINGS_AS_ERRORS=OFF
./ns3 build scratch/mesh-sim/sim
```

This builds only the ns-3 modules Mesh-Sim needs. The binary is
`build/scratch/mesh-sim/ns3.42-sim-debug`. More:
\ref mesh_sim_install_build "Install and build".

## 3\. Run a scenario

```bash
./ns3 run scratch/mesh-sim/sim -- \
  --run-config=scratch/mesh-sim/inputs/baselines/01-static-los-baseline/run.ini \
  --seeds=1 \
  --output-dir=scratch/mesh-sim/outputs/getting-started/01-static-los-baseline
```

Two fixed nodes 100 m apart, one 10 Mbps flow, 5 s on a 28 GHz channel. What
happens inside: \ref mesh_sim_run_flow "How a run works". More:
\ref mesh_sim_first_run "Your first run".

## 4\. Check the result

```bash
ls scratch/mesh-sim/outputs/getting-started/01-static-los-baseline/seed-1
grep -A6 '"network"' scratch/mesh-sim/outputs/getting-started/01-static-los-baseline/seed-1/summary.json
```

You should see six CSVs plus `summary.json`, and network metrics like these:

| Metric | Expected |
|---|---|
| `mean_sinr_db` | about 34.7 |
| `sum_throughput_mbps` | 10.0 (the flow got all 10 Mbps it asked for) |
| `connectivity` | 1.0 |
| `flows_unroutable` | 0.0 |

More: \ref mesh_sim_first_result "Understand the result".

## 5\. Graph it

From `scratch/mesh-sim/`, set up the Python environment once, then plot the run:

```bash
cd scratch/mesh-sim
python3 scripts/rl/bootstrap_venv.py
sed 's|^data_dir.*|data_dir = outputs/getting-started/01-static-los-baseline|' \
    scripts/plotting/plot.example.ini > outputs/plot.ini
.venv/bin/python -m scripts.plotting.cli --config outputs/plot.ini
```

The figures land in `outputs/getting-started/01-static-los-baseline/figures/`:
SINR, capacity, MCS, throughput and latency over time, plus per-node and
per-flow charts. What each one shows: \ref files_figures "Figures".

## 6\. Replay it in 3D

With the **ns3-mmwave-viz** repository checked out beside `ns3-mmwave`, from
the folder that holds both:

```bash
cd ns3-mmwave-viz
npm install
npm run dev
```

Open `http://localhost:5173`, tick the run's folder on the **Folders** page,
then open **Simulation runs** and pick the seed. The visualizer's own guide,
[Replay your first run](../../../../../ns3-mmwave-viz/docs/html/viz_replay_a_run.html),
has the details; that link works once the visualizer's docs are generated.

## 7\. Next steps

- \ref mesh_sim_change_one_setting "Change one setting": ask for more traffic
  than the link can carry, or add a building.
- \ref mesh_sim_files "Input and output files": every file a run reads and writes.
- \ref mesh_sim_overview "User guide": flags and common tasks.
