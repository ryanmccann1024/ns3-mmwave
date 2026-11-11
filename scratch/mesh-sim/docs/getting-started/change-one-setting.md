# Change one setting {#mesh_sim_change_one_setting}

[TOC]

Copy the scenario from \ref mesh_sim_first_run "Your first run", ask for more
traffic than its link can carry, and see what the simulator does. Then add a
building between the two nodes and see what that does to the link.

## 1\. Before you start

- You finished \ref mesh_sim_first_run "Your first run", so
  `scratch/mesh-sim/outputs/getting-started/01-static-los-baseline/` exists.
- You read \ref mesh_sim_first_result "Understand the result". It showed the
  link has about **4,600 Mbps** of capacity while the flow asks for only
  **10 Mbps**.
- Run every command from the ns3-mmwave repository root.

## 2\. The change

`[traffic] demand_mbps` is the traffic each flow asks for, in Mbps. You will
raise it from `10.0` to `6000.0`, which is more than the link can carry.

You never edit the tracked scenario. You copy it into the git-ignored
`outputs/` folder, edit the copy, and run the copy into its own result folder:

```
scratch/mesh-sim/outputs/                 (ignored by Git)
├── my-scenarios/
│   ├── 01-demand-6000/                   your copy: edit run.ini here
│   │   ├── run.ini
│   │   └── nodes.json
│   └── 01-building/                      second copy, with a building (section 7)
└── getting-started/
    ├── 01-static-los-baseline/           results of your first run
    ├── 01-demand-6000/                   results of this run
    └── 01-building/                      results of the building run
```

## 3\. Copy the scenario

```bash
mkdir -p scratch/mesh-sim/outputs/my-scenarios
cp -R scratch/mesh-sim/inputs/baselines/01-static-los-baseline \
      scratch/mesh-sim/outputs/my-scenarios/01-demand-6000
```

Keep the copy inside `scratch/mesh-sim/`. A scenario outside that tree fails to
load with `Could not locate mesh-sim root`.

**Checkpoint:** `ls scratch/mesh-sim/outputs/my-scenarios/01-demand-6000` shows
`nodes.json` and `run.ini`.

## 4\. Edit one line

Open `scratch/mesh-sim/outputs/my-scenarios/01-demand-6000/run.ini`, find the
`[traffic]` section and change the `demand_mbps` line:

```ini
demand_mbps    = 6000.0
```

**Checkpoint:** comparing with the original shows exactly that one line:

```bash
diff scratch/mesh-sim/inputs/baselines/01-static-los-baseline/run.ini \
     scratch/mesh-sim/outputs/my-scenarios/01-demand-6000/run.ini
```

```
54c54
< demand_mbps    = 10.0
---
> demand_mbps    = 6000.0
```

## 5\. Run the copy

```bash
./ns3 run scratch/mesh-sim/sim -- \
  --run-config=scratch/mesh-sim/outputs/my-scenarios/01-demand-6000/run.ini \
  --seeds=1 \
  --output-dir=scratch/mesh-sim/outputs/getting-started/01-demand-6000
```

**Checkpoint:** `echo $?` prints `0`, and `run.log` shows the new value:

```bash
grep demand_mbps scratch/mesh-sim/outputs/getting-started/01-demand-6000/run.log
```

```
  traffic.demand_mbps = 6000
```

## 6\. Compare the two runs

\image html change-one-setting.svg "Mean demand, delivered rate and link capacity for the two runs (seed 1)."

The flow asked for 6,000 Mbps and got about 4,600: the link's full capacity.

| | First run | This run |
|---|---|---|
| `demand_mbps` | 10 | 6,000 |
| `delivered_mbps` (mean) | 10 | 4,606 (77% of demand) |
| Link capacity (mean) | 4,606 | 4,606 |
| Link SINR | 34.6 dB | 34.6 dB |
| Latency | 0.5 ms | 0.5 ms |

The rows of the two `flows.csv` files show it tick by tick:

```bash
head -n 3 scratch/mesh-sim/outputs/getting-started/01-demand-6000/seed-1/flows.csv
```

```
time_s,src,dst,demand_mbps,delivered_mbps,latency_ms,hop_count,routable
0.000000,0,1,6000.0,4729.1,0.500,1,1
0.100000,0,1,6000.0,4603.7,0.500,1,1
```

What this shows about the model:

- **Delivered traffic is capped by capacity.** When the flows on a link ask for
  more than it can carry, the router scales each flow by
  `capacity / total demand`. With one flow, that is exactly the link capacity.
  In `links.csv`, `delivered_mbps` now equals `capacity_mbps`: the link is full.
- **Link quality does not depend on traffic.** SINR and capacity are the same in
  both runs, because nodes do not interfere with each other.
- **Latency does not grow with load.** Mesh-Sim models flow rates, not packets
  or queues, so a full link adds no delay.

## 7\. Add a building

A building between the two nodes blocks the line of sight. Make a second copy
of the original scenario and give it a `buildings.json` with one 20 m wide,
20 m tall block halfway between the nodes:

```bash
cp -R scratch/mesh-sim/inputs/baselines/01-static-los-baseline \
      scratch/mesh-sim/outputs/my-scenarios/01-building
cat > scratch/mesh-sim/outputs/my-scenarios/01-building/buildings.json <<'JSON'
[
  {
    "id": "block",
    "bounds": {
      "x_min": 40.0, "x_max": 60.0,
      "y_min": -20.0, "y_max": 20.0,
      "z_min": 0.0, "z_max": 20.0
    }
  }
]
JSON
```

Then point the scenario at it. In the copy's `run.ini`, under `[scenario]`:

```ini
buildings_file = buildings.json
```

Run it:

```bash
./ns3 run scratch/mesh-sim/sim -- \
  --run-config=scratch/mesh-sim/outputs/my-scenarios/01-building/run.ini \
  --seeds=1 \
  --output-dir=scratch/mesh-sim/outputs/getting-started/01-building
```

**Checkpoint:** `run.log` shows `buildings = 1`, and every row of `links.csv`
says `NLOS,building`:

```bash
head -n 3 scratch/mesh-sim/outputs/getting-started/01-building/seed-1/links.csv
```

```
time_s,node_a,node_b,dist_m,sinr_db,condition,condition_reason,capacity_mbps,delivered_mbps,hop_count
0.000000,0,1,100.000000,33.653858,NLOS,building,4472.1,10.0,1
0.100000,0,1,100.000000,26.295725,NLOS,building,3495.5,10.0,1
```

| | First run | With the building |
|---|---|---|
| `condition` | `LOS` | `NLOS` |
| `condition_reason` | `probabilistic` | `building` |
| Link SINR | 34.6 dB | 26.3 dB |
| Link capacity | 4,604 Mbps | 3,496 Mbps |
| `delivered_mbps` | 10 | 10 |

The building sits on the straight line between the nodes, so the link is NLOS
and the channel model uses its higher NLOS path loss: SINR drops by 8 dB and
capacity by about a quarter. The flow still gets its 10 Mbps, because 3,496 Mbps
is far more than it asks for. Raise `demand_mbps` in this copy too and the cap
from section 6 comes back at the lower capacity.

Every building field, and what a building does to a link:
\ref files_buildings_json "buildings.json".

## 8\. Try another change

Each numbered scenario in \ref inputs_baselines "inputs/baselines" changes one
thing from the scenario you just copied. Good next steps:

| Scenario | What it changes | What to look at |
|---|---|---|
| `03-building-blockage` | One node starts behind a building and moves out from behind it | The link switching from `NLOS` to `LOS` partway through. |
| `02-distance-sweep` | Moves one node away over time | SINR and capacity falling with distance, until the link dies. |
| `06-mcs-table-mode` | Capacity from an MCS table instead of Shannon | `capacity_mbps` stepping between table rows. |
| `07-three-node-relay` | Three nodes in a line, 500 m apart | Whether the end-to-end flow takes two hops through the middle node (`routes.csv`), and latency adding up per hop. |
| `09-congestion-bottleneck` | Two flows share one relay link | Both flows scaled down on the shared link. |
| `10-on-off-traffic` | Flows switch on and off | `demand_mbps` going to zero and back. |

Run any of them the same way as your first run, pointing `--run-config` at its
`run.ini`. To change a setting yourself, copy the scenario as in step 3 and look
the key up in \ref files_run_ini "run.ini".

Previous: \ref mesh_sim_first_result "Understand the result" · Next: \ref mesh_sim_files "Input and output files"
