# Configure an RL scenario {#mesh_sim_rl_configure}

[TOC]

Every setting that shapes an RL run, who reads it and what it defaults to,
with the reward formulas worked on the tutorial's real run, then a pre-flight
check that the simulator and Python agree.

## 1\. Before you start

- You read \ref mesh_sim_rl_how_it_works "How a decision works".
- Working directory: `scratch/mesh-sim/`, with `SIM_BIN`, `RUN_CONFIG` and
  `OUT` set as on \ref mesh_sim_rl_example "The example scenario".

## 2\. Who reads which setting

\htmlonly
<div class="ms-gates">
<div class="ms-gate"><strong>run.ini [rl]</strong><span>one file, two readers</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>C++ keys</strong><span>movement, masks, reward type</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>Python keys</strong><span>observation, reward mix, files</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate ms-gate-end"><strong>Manifest</strong><span>records value and source</span></div>
</div>
\endhtmlonly

The `[rl]` section is read twice. The simulator reads the keys in section 3
when it loads the scenario; a bad value stops it before the first tick. The
Python tools read the keys in sections 4 to 6; the simulator ignores them.

The Python selection keys resolve each on its own, in this order:

1. a flag on `train` or `evaluate`, such as `--observation-preset` or
   `--reward-components` (placed **before** the `m-ppo` subcommand);
2. the `[rl]` key in `run.ini`;
3. the built-in default.

Both manifests record the resolved value and where it came from
(`cli`, `run.ini` or `default`). `evaluate --run-dir` takes the selection from
the training manifest and refuses selection flags, so a model is always
evaluated with the inputs it was trained on.

## 3\. Simulator settings

Defaults are the values the C++ loader uses when the key is absent
(`src/config/config-loader.cc`).

| Key | Default | Example value | What it does |
|---|---|---|---|
| `enabled` | `false` | `true` | Turns the bridge on. `--rl-mode` on the command line also turns it on; the Python tools always pass it. |
| `controlled_nodes` | none: required | `node-b` | The nodes the policy moves, in slot order, or `all`. Jammers and the active traffic gateway cannot be listed. A controlled node's own mobility is replaced by constant velocity, starting at its `nodes.json` position (first waypoint for a waypoint node). |
| `max_controlled_nodes` | `0` | `1` | Number of slots. `0` sizes it to the controlled nodes; the maximum is 64. Set it higher to keep one policy shape across scenarios with fewer controlled nodes; extra slots are padding. |
| `action_profile` | `move_2d` | `move_2d` | The only profile: four horizontal moves plus hold. `move_3d` is refused. |
| `decision_interval_s` | `0` | `1.0` | Time between decisions. Must be a whole number of ticks; `0` means every tick. |
| `step_size_m` | `50` | `2.0` | Meters **per tick**, not per decision. The speed is `min(step_size_m / tick_s, top speed)`. |
| `reward_type` | `throughput` | `all_links_los` | The built-in per-tick reward (section 6). `mean_sinr` is a deprecated spelling of `all_links_los` and prints a warning. |
| `x_min`, `x_max` | −1000, 2000 | 0, 250 | Movement bounds in meters. Every controlled node must start inside them. |
| `y_min`, `y_max` | −1000, 1000 | −100, 100 | |
| `z_min`, `z_max` | 0, 100 | 0, 50 | Checked against start positions and used for observation scaling. Nothing moves in z. |
| `unsafe_separation_m` | `1` | default | Distance below which two nodes count as unsafe in `facts.safety`. |
| `avoid_buildings`, `building_clearance_m`, `mask_building_moves` | `false`, `0`, `true` | default | Stop movement into buildings and mask such moves (section 8). |
| `avoid_node_collisions` | `false` | default | Hold joint moves that would bring two nodes closer than `unsafe_separation_m`. |
| `coverage_enabled` | `false` | default | Add a live area-coverage fraction to the facts. The grid comes from `[baseline]` keys. |
| `control_start_s` | `0` | default | Hold every controlled node until this time. Must fall on a decision boundary. |

`controlled_node_id`, `action_type` and `arrival_threshold_m` belonged to the
removed single-node mode. The simulator rejects them and prints
`rl.<key> is no longer supported; use rl.controlled_nodes and rl.action_profile=move_2d`.

Every key, with limits: \ref src_config_run_ini_reference "run.ini reference, section 5"
(see \ref mesh_sim_rl_assumptions "Every assumption", section 12, for the
stale rows in that reference).

## 4\. What the policy sees: observation presets

Python reads `[rl] observation_preset` (default `raw_links_v1`) and builds the
policy's input from the facts. There are 10 registered presets; the general
ones are:

| Preset | Per slot | Scaling | Use it when |
|---|---|---|---|
| `raw_links_v1` (default) | Active flag, x, y, z, then SINR (dB) and capacity (Mbps) for each peer | None: the simulator's own `obs` vector | You want raw numbers |
| `local_links_v1` | Active flag, x, y, z scaled to ±1 by the bounds, then present, valid-SINR flag, scaled SINR and scaled capacity per peer | Fixed ranges | A good general default |
| `geometry_v1` | Own x and y, and each peer's relative x and y | ±1 | Geometry-only experiments |
| `service_v1` | `local_links_v1` plus demand, delivery and routability for the window | Fixed ranges | The reward is about traffic delivery |
| `full_facts_v1` | `service_v1` plus relative 3D position, velocity, LOS and service gap per peer | Fixed ranges | Richest single-network input |
| `mission_*` | Mission and coordination inputs | | Mission campaigns only |

On the example (one slot, one peer) `raw_links_v1` has 6 values and
`local_links_v1` has 8. A padded slot is all zeros in every preset.

- **Scale overrides.** `observation_parameters` takes a JSON object. For the
  link presets the keys are `sinr_min_db` (−20), `sinr_max_db` (40),
  `sinr_invalid_db` (−900) and `capacity_log10_denominator` (4);
  `full_facts_v1` adds `velocity_scale_mps` (40). Unknown keys are refused.
- **Presets never change.** A changed formula needs a new `_vN` preset. Each
  preset's schema (features, bounds, scales) is hashed into the training
  manifest, and a saved model is refused if the live schema differs.

The worked numbers for `local_links_v1` are on \ref mesh_sim_rl_how_it_works "How a decision works",
section 4. Every feature of every preset:
\ref src_rl_policy_inputs_observation "What the observation contains".

## 5\. What the policy learns from: rewards

### The built-in C++ reward

Without `reward_components`, the policy learns from the C++ `reward_type`,
averaged over each decision window's scored ticks:

\f[ r_{\text{step}} = \frac{1}{\lvert S \rvert} \sum_{t \in S} r_t \qquad S = \text{ticks in the window with } t \ge \mathtt{warmup\_s} \f]

and \f$r_{\text{step}} = 0\f$ when \f$S\f$ is empty. Per tick:

| `reward_type` | \f$r_t\f$ |
|---|---|
| `throughput` (default) | \f$\sum_f \text{delivered}_f\f$: total delivered Mbps over all flows |
| `all_links_los` | +1 if every controlled node has at least one peer and every link from it is LOS; otherwise −1 |

**Worked, decision 3 of the tutorial's trace.** 8 LOS ticks and 2 NLOS ticks:
\f$r_{\text{step}} = (8 \cdot 1 + 2 \cdot (-1)) / 10 = 0.6\f$, exactly the
`reward` of that step line.

### Composed Python rewards

Naming components makes Python compute the step reward instead, from the same
window's facts:

```ini
reward_components = delivery_ratio, connectivity
reward_weights    = 1.0, 0.5
```

\f[ r_{\text{step}} = \sum_i w_i \, c_i \qquad \text{over components } i \text{ whose value is valid in this window} \f]

A window with no scored ticks makes every component invalid, so it adds 0. The
base components, with \f$W\f$ the window's `facts.window` sums and \f$n\f$ =
`scored_ticks`:

| Component | Formula | Invalid when |
|---|---|---|
| `delivery_ratio` | \f$W_{\text{delivered}} / W_{\text{demand}}\f$ | Nothing was demanded |
| `connectivity` | \f$W_{\text{connected pairs}} / (n \cdot \mathtt{num\_links})\f$; a pair is connected at SINR ≥ −6.7 dB | Never (0 links gives 0) |
| `throughput_mbps` | \f$W_{\text{delivered}} / n\f$: mean delivered Mbps | |
| `legacy` | \f$W_{\text{legacy reward}} / n\f$: the C++ reward itself, to mix with others | |
| `travel_fraction` | Mean over slots of \f$\min(1,\ d / (v \cdot \Delta t))\f$: the share of the possible distance actually moved, \f$d\f$ the xy distance between decisions | A window only partly scored |
| `sinr_quality` | Mean over links of \f$(\text{SINR} + 20) / 60\f$, clipped to [0, 1] | |

**Worked, seed 14.** On held-out seed 14 the trained model's link dropped below
−6.7 dB for one tick of decision 3's window (t = 2.2 s), so the flow was
unroutable for that tick. Rescoring that window with the two components
above: `delivered` 90 of `demand` 100 Mbps-ticks, 9 of 10 pair-ticks
connected:

\f[ r_{\text{step}} = 1.0 \times \frac{90}{100} + 0.5 \times \frac{9}{10 \cdot 1} = 0.9 + 0.45 = 1.35 \f]

**Worked, a movement penalty.** Section 6 of \ref mesh_sim_rl_how_it_works "How a decision works"
showed the trained model moving every decision for no reward. Rescoring its
seed-11 episode with `legacy` at weight 1 and `travel_fraction` at weight −0.5:
every full 20 m move costs 0.5, so decision 3 becomes
\f$0.6 - 0.5 \times 1.0 = 0.1\f$ and the episode's return drops from 15.6 to
5.85. A policy trained on that reward would be paid to stop once it is LOS.
(This is a rescoring of the recorded episode with `RewardComposer`, not a
training run.)

88 components are registered. Beyond the base ones they cover service
thresholds (`service_success`), fairness (`fair_node_service`,
`worst_node_delivery_fraction`), movement and safety (`span_travel_fraction`,
`unsafe_proximity_fraction`), coverage (`coverage_fraction`) and mission
objectives. A negative weight turns a component into a penalty. Per-component
settings go in `reward_parameters` as JSON keyed by component name. The full
catalog: \ref src_rl_policy_inputs "Policy inputs, section 5". To list every
name:

```bash
.venv/bin/python -c "from scripts.rl.env.rewards import COMPONENTS; print(len(COMPONENTS)); print(sorted(COMPONENTS)[:6])"
```

**Checkpoint:**

```
88
['active_sinr_quality_v1', 'adaptive_movement_cost', 'available_peer_travel_fraction_v1', 'available_target_arrival_fraction_v1', 'available_team_closeness_v1', 'boundary_contact_fraction_v1']
```

## 6\. What gets recorded

| Key | Default | What it does |
|---|---|---|
| `telemetry` | `none` | `steps` writes `steps.jsonl` in every episode folder: one header, then one record per saved decision with the action, mask, facts, reward and an observation fingerprint. |
| `telemetry_every` | `1` | Save every kth decision. Totals in `rl_episode.json` still count every decision. |
| `compact_training` | `false` | Training episodes skip the visualizer CSVs (`--no-viz`). |
| `record_validation_telemetry` | `false` | With `compact_training`, still write `steps.jsonl` for model-selection episodes. |
| `manifest_every_decisions` | `1` | How often an episode rewrites its `rl_episode.json` while running. |

Evaluation always records every decision, because its metrics come from
`steps.jsonl`. `--decision-records` on `train` or `evaluate` adds a separate,
richer per-decision file (\ref src_rl_decision_records "Decision records").

## 7\. The tutorial's resolved settings

Nothing in the tutorial is set on the command line except the seeds, so the
selection is: `observation_preset = local_links_v1` (source `run.ini`), no
reward components (C++ `all_links_los` reward, source `default`), telemetry
`none` for training. You will see exactly this in the pre-flight output below
and again in `inspect_model` on \ref mesh_sim_rl_train "Train a policy".

## 8\. Optional features

Each is off unless you set it. Most add fields to the facts without changing
the action or observation shapes.

| Setting | What it adds | More |
|---|---|---|
| `[rl] avoid_buildings`, `building_clearance_m`, `mask_building_moves` | Stops a node at a building wall and masks moves whose path enters a building | \ref src_rl_building_avoidance "Building avoidance" |
| `[rl] avoid_node_collisions` | Holds joint moves that would bring two nodes closer than `unsafe_separation_m` | \ref src_rl "src/rl, section 8" |
| `[rl] coverage_enabled` | Live area-coverage fraction each decision, for coverage rewards | \ref src_rl_policy_inputs_facts "Facts some components need" |
| `[rl] control_start_s` | Holds every controlled node until that time | \ref src_rl_deployment_gate "Deployment gate" |
| `[mission] kind` | Coverage, investigation or recovery missions with their own facts and metrics | \ref src_rl_missions "Missions" |
| `[rl] training_jammer_onsets_s`, `evaluation_jammer_onsets_s`, `jammer_motion_profile` | Jammers that switch on later or move along a route, varied per episode | \ref scripts_rl_env "scripts/rl/env" |

## 9\. Check the scenario before training

`validate_config` checks the files, the selection, the seed, the bounds, the
binary and the Python packages. With `--launch` it also starts the simulator
once, reads the `init` message and resets once. It never finishes an episode.

```bash
.venv/bin/python -m scripts.rl.validate_config \
  --sim-binary "$SIM_BIN" --run-config "$RUN_CONFIG" \
  --output-dir "$OUT/preflight" --launch --json
```

**Checkpoint:** exit code 0 in under a second, and the JSON ends with
`"status": "ok"`. Its `launch` block:

```json
"launch": {
  "output_dir": ".../outputs/rl-tutorial/preflight/validate",
  "control_mode": "centralized",
  "contract": "mesh_move_2d_v2",
  "num_mesh_nodes": 2,
  "max_controlled_nodes": 1,
  "num_decisions": 20,
  "cpp_obs_dim": 6,
  "cpp_mask_dim": 5,
  "preset_obs_dim": 8,
  "observation_schema_sha256": "5f3f34f19b8640316cf9bf70a9e7cb67033ac7474040b78575a087bcecaeee12",
  "reward_schema_sha256": "12d179c6251f16261c3314aa2feb6ea68df85bc872edd4fa772015c84b06c73d"
},
"status": "ok"
```

- **The `control_mode` check says `warning`.** That is expected. Without
  `--launch`, the static checks cannot confirm the mode; the launch check
  confirms it.
- **`package_versions` says `installed versions match requirements.txt`.**
  The training manifest records the same versions.
- **`cpp_obs_dim` against `preset_obs_dim`.** 6 is the simulator's raw vector;
  8 is what `local_links_v1` hands the policy.
- **The two `sha256` values** identify the observation and reward definitions.
  The training manifest records the same two values, and evaluation compares
  them.

| Exit | Meaning |
|---|---|
| 0 | Every check passed or warned. |
| 1 | A check failed; the failing checks are repeated on stderr. |

## 10\. Going further

- \ref src_rl_policy_inputs "Policy inputs": every preset and component, with
  tests.
- \ref mesh_sim_rl_extend "Change or extend RL": add your own component or
  preset.

<!-- Provenance: validate_config output in outputs/rl-tutorial/logs/validate.log,
     2026-10-28, binary build/scratch/mesh-sim/ns3.42-sim-debug (sha256
     d7a2f4d1...6c9fe2), mesh-sim commit b54bfbe7 plus the working tree.
     Worked rewards: rescored from outputs/rl-tutorial/eval/model/episode-0000
     (seed 11) and episode-0003 (seed 14) steps.jsonl with
     scripts.rl.env.rewards.RewardComposer. -->

Previous: \ref mesh_sim_rl_how_it_works "How a decision works" · Next: \ref mesh_sim_rl_train "Train a policy"
