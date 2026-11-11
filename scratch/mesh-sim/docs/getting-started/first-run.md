# Your first run {#mesh_sim_first_run}

[TOC]

Run one tracked scenario with one seed and check that the output files appear.

## 1\. Before you start

- **Built binary:** `build/scratch/mesh-sim/ns3.42-sim-debug` exists (the last
  checkpoint in \ref mesh_sim_install_build "Install and build").
- **Working directory:** run every command from the ns3-mmwave repository root.

## 2\. The scenario

`scratch/mesh-sim/inputs/baselines/01-static-los-baseline/` is the simplest
scenario. Every other numbered baseline changes one setting from it.

| Setting | Value |
|---|---|
| Nodes | `node-a` at (0, 0, 10) and `node-b` at (100, 0, 10), both fixed |
| Time | 5.0 s in 0.1 s ticks |
| Channel | 28 GHz, 3GPP RMa, 400 MHz bandwidth |
| Traffic | Constant 10 Mbps between every node pair |
| Extras | No buildings, jammers or RL |

The settings come from the scenario's `run.ini` and the nodes from its
`nodes.json`. Every field of both: \ref files_run_ini "run.ini",
\ref files_nodes_json "nodes.json".

## 3\. Run it

```bash
./ns3 run scratch/mesh-sim/sim -- \
  --run-config=scratch/mesh-sim/inputs/baselines/01-static-los-baseline/run.ini \
  --seeds=1 \
  --output-dir=scratch/mesh-sim/outputs/getting-started/01-static-los-baseline
```

- `--run-config` is the `run.ini` file, not its folder.
- `--seeds=1` runs one seed and names the output folder `seed-1/`.
- `--output-dir` gives the run a fixed folder so the next page can refer to it.
  Without it, results go to a timestamped folder under
  `scratch/mesh-sim/outputs/`.

**Checkpoint:** the command finishes and `echo $?` prints `0`.

## 4\. Check the outputs

```bash
ls scratch/mesh-sim/outputs/getting-started/01-static-los-baseline
ls scratch/mesh-sim/outputs/getting-started/01-static-los-baseline/seed-1
```

**Checkpoint:** you see these files.

| Folder | Expected contents |
|---|---|
| Run folder | `inputs/`, `run.log`, `seed-1/` |
| `seed-1/` | `flows.csv`, `links.csv`, `mcs.csv`, `positions.csv`, `routes.csv`, `rx-power.csv`, `summary.json` |

## 5\. Going further

- \ref readme_run_single "Run a scenario" in the User guide: the key flags,
  including `--band` and multiple seeds.
- \ref src_cli "Command-line options": every flag the simulator accepts.
- \ref Inputs "Scenario inputs": running the built binary directly instead of
  through `./ns3 run`.

Previous: \ref mesh_sim_install_build "Install and build" · Next: \ref mesh_sim_first_result "Understand the result"
