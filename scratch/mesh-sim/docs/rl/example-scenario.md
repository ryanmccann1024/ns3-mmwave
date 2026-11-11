# The example scenario {#mesh_sim_rl_example}

[TOC]

The one scenario this tutorial uses from start to finish,
`inputs/baselines/building-bypass-smoke`: what is in it, why a policy can learn
it in minutes, and every line of its `[rl]` section.

## 1\. Before you start

- You read \ref mesh_sim_rl_start "RL in Mesh-Sim" and its terms table.
- Working directory: `scratch/mesh-sim/`. Set these three variables in your
  shell; every later page uses them:

```bash
SIM_BIN="$(cd ../.. && pwd)/build/scratch/mesh-sim/ns3.42-sim-debug"
RUN_CONFIG=inputs/baselines/building-bypass-smoke/run.ini
OUT=outputs/rl-tutorial
```

`SIM_BIN` must be an absolute path to a binary you built. `OUT` is under
`outputs/`, which Git ignores. The tools refuse to write into a folder that
already holds a run, so pick a new `OUT` if you repeat the tutorial.

**Checkpoint:** `ls "$SIM_BIN"` prints the path, and
`ls inputs/baselines/building-bypass-smoke` prints

```
buildings.json
nodes.json
run.ini
```

## 2\. Why this scenario

It is a tiny scenario built so that learning is easy to see. It is a smoke
fixture, not a benchmark.

- **One decision matters.** The only way to score well is to leave the
  building's shadow, and the only thing the policy controls is where one node
  goes.
- **It is fast.** Two nodes, one link, 20 decisions per episode. One training
  decision costs about 0.05 s here, so 8,192 decisions train in about
  6 minutes.
- **The answer is known.** Holding still scores −20. The best possible return
  is +15.6 (section 5). You can check a trained policy against both.

## 3\. The layout

\image html rl-example-map.svg "building-bypass-smoke from above. node-a is fixed; node-b is controlled and moves 20 m per decision. The shaded wedge is where the building blocks the line to node-a. Bounds, building and nodes come from the scenario's files and the init message of the evaluation run in outputs/rl-tutorial/eval (seed 11)."

| Element | Value | From |
|---|---|---|
| `node-a` | Fixed at (0, 0, 10), a drone | `nodes.json` |
| `node-b` | Starts at (200, 0, 10), a drone. Controlled. | `nodes.json`, `[rl] controlled_nodes` |
| Building `wall` | x 90 to 110, y −20 to 20, z 0 to 30 m: taller than both nodes | `buildings.json` |
| Movement bounds | x 0 to 250, y −100 to 100 | `[rl]` |
| Radio | 28 GHz, 400 MHz, 30 dBm, 3GPP RMa, buildings decide LOS | `[channel]` |
| Traffic | One 10 Mbps flow between the two nodes (`all_pairs` with two nodes is one pair) | `[traffic]`; `facts.window.demand_mbps_sum` is 10 per tick |
| Time | 20 s in 0.1 s ticks: 200 ticks | `[scenario]` |

**Why the link starts NLOS.** Both nodes are at 10 m and the building is 30 m
tall, so the building blocks any line that crosses its footprint. The line
from `node-a` at the origin to a point (x, y) east of the building first meets
the building at x = 90. It clears the corner when

\f[ \lvert y \rvert \cdot \frac{90}{x} > 20 \qquad\Rightarrow\qquad \lvert y \rvert > \frac{20x}{90} \f]

At `node-b`'s x = 200 that is \f$\lvert y \rvert > 44.4\f$ m. The shaded wedge
in the figure is everything that fails this test.

**What the radio does in the shadow.** NLOS does not mean disconnected. Holding
still on held-out seed 11, the link's SINR stayed between 6.6 and 12.4 dB and
its capacity between 992 and 1,685 Mbps, far above the 10 Mbps demand. That is
why delivery cannot tell a good policy from a bad one here (\ref mesh_sim_rl_evaluate "Evaluate and compare").

## 4\. The [rl] section, line by line

```bash
sed -n '/^\[rl\]/,/^$/p' "$RUN_CONFIG"
```

**Checkpoint:**

```ini
[rl]
enabled               = true
controlled_nodes      = node-b
max_controlled_nodes  = 1
action_profile        = move_2d
decision_interval_s   = 1.0
reward_type           = all_links_los
step_size_m           = 2.0
x_min                 = 0.0
x_max                 = 250.0
y_min                 = -100.0
y_max                 = 100.0
z_min                 = 0.0
z_max                 = 50.0
observation_preset    = local_links_v1
```

| Key | Value | What it does here | Read by |
|---|---|---|---|
| `enabled` | `true` | Turns the RL bridge on. The training tools also pass `--rl-mode`. | C++ |
| `controlled_nodes` | `node-b` | `node-b` is slot 0. `node-a` keeps its fixed mobility. | C++ |
| `max_controlled_nodes` | `1` | One slot, so the action is one integer and the mask is 5 flags. | C++ |
| `action_profile` | `move_2d` | West, east, south, north or hold. Height never changes. The only profile. | C++ and Python |
| `decision_interval_s` | `1.0` | A decision every 10 ticks, so 20 decisions in 20 s. | C++ |
| `reward_type` | `all_links_los` | Per tick, +1 if every link of every controlled node is LOS, else −1. | C++ |
| `step_size_m` | `2.0` | Meters per **tick**. At 0.1 s ticks that is 20 m/s, the drone's top speed, so a decision moves `node-b` 20 m. | C++ |
| `x_min`, `x_max`, `y_min`, `y_max` | `0`, `250`, `−100`, `100` | The box `node-b` may move in, in meters. Moves are clipped at its edges and masked once a node touches one. | C++ (and the observation's scaling) |
| `z_min`, `z_max` | `0`, `50` | Checked against the start position and used to scale z in the observation. Nothing moves in z. | C++ and Python |
| `observation_preset` | `local_links_v1` | The policy sees 8 numbers, each scaled to a fixed range (\ref mesh_sim_rl_how_it_works "How a decision works", section 4). | Python only |

Every other `[rl]` key is at its default. \ref mesh_sim_rl_configure "Configure an RL scenario"
lists them all.

## 5\. What a perfect policy scores

Each tick scores +1 if the link is line of sight and −1 if not, and a
decision's step reward is the average of its 10 ticks. The fastest way out of
the shadow is straight north or south, 2 m per tick from y = 0:

| Decision | Ticks | node-b y at the end (m) | LOS ticks | NLOS ticks | Step reward |
|---|---|---|---|---|---|
| 1 | 1–10 | ±20 | 0 | 10 | −1.0 |
| 2 | 11–20 | ±40 | 0 | 10 | −1.0 |
| 3 | 21–30 | ±60 | 8 | 2 | +0.6 |
| 4–20 | 31–200 | stays LOS | 10 | 0 | +1.0 each |

In decision 3 the link clears the building at tick 23, when node-b reaches
y = ±46 m.

The best return is −1 − 1 + 0.6 + 17 = **+15.6**. Holding still keeps the link
NLOS every tick: **−20**. These are exactly the returns the trained model and
`hold` score in \ref mesh_sim_rl_evaluate "Evaluate and compare". Going west
past the building also reaches LOS, but only once x < 90, which takes 5.5
decisions.

## 6\. Going further

- \ref files_buildings_json "buildings.json": how a building decides LOS.
- \ref mesh_sim_change_one_setting "Change one setting": what a building does
  to a link, without RL.

<!-- Provenance: scenario files at mesh-sim commit b54bfbe7 plus the working
     tree, run.ini sha256 7fe68026...ab686e. SINR and capacity ranges from
     outputs/rl-tutorial/eval/hold/episode-0000/seed-11/links.csv, 2026-10-28,
     binary ns3.42-sim-debug sha256 d7a2f4d1...6c9fe2. -->

Previous: \ref mesh_sim_rl_start "RL in Mesh-Sim" · Next: \ref mesh_sim_rl_how_it_works "How a decision works"
