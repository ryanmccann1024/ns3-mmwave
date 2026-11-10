@page src_rl_policy_inputs src/rl/policy-inputs

@brief Observation presets, reward components, and telemetry for centralized RL policies.

The simulator computes positions, links, traffic, and the per-tick reward in
C++, and every decision message includes those raw measurements as `facts`.
Python's `selection.py` chooses what the policy sees, which reward Gymnasium
returns, and whether to save decision records. These options do not change the
simulator's physics or action masks. Actions and timing are in the
[bridge contract](@ref src_rl); the Python modules are in the
[environment README](@ref scripts_rl_env).

## 1\. Quick start

1. Add these lines to the `[rl]` section of a centralized scenario's `run.ini`
   (one with `controlled_nodes`):

   ```ini
   observation_preset = local_links_v1
   reward_components = delivery_ratio, connectivity
   reward_weights = 1.0, 0.5
   telemetry = steps
   telemetry_every = 2
   ```

2. Run the training command in
   [Train a policy](@ref mesh_sim_rl_train).
3. Read the resolved values and their sources in `train_manifest.json` and in
   each `episode-NNNN/rl_episode.json`.

Omitting `reward_components` returns the C++ reward. Omitting `telemetry`
writes no `steps.jsonl`.

One policy step:

```text
sim.cc tick loop -> rl-bridge.cc step {obs, mask, reward, facts}
    -> mesh_env.py builds selected observation and reward
    -> MaskablePPO chooses one masked action per controlled position
    -> rl-bridge.cc applies those actions until the next decision
    -> episode.py optionally saves the decision in steps.jsonl
```

| Module (`scripts/rl/env/`) | Role |
| --- | --- |
| `observations/__init__.py` | Policy input layouts (presets) and their schemas. |
| `rewards/__init__.py` | Reward components and the composer. |
| `normalization.py` | Shared SINR normalization. |
| `recording/telemetry.py` | Writes and replays optional decision records. |
| `mesh_env.py` | Connects these modules to Gymnasium. |

## 2\. Selection keys and flags {#src_rl_policy_inputs_selection}

These `[rl]` keys are read by the Python env and `train.py`; the simulator
ignores them. They apply to centralized mode only.

| Key | CLI flag | Type | Default | Meaning |
|---|---|---|---|---|
| `observation_preset` | `--observation-preset` | preset name | `raw_links_v1` | Which observation the policy sees (section 3). |
| `observation_parameters` | `--observation-parameters` | JSON object | none | Normalization overrides for the preset (section 3). |
| `reward_components` | `--reward-components` | comma-separated names | absent (the C++ reward) | Components Python composes into the returned reward (sections 4–5). |
| `reward_weights` | `--reward-weights` | comma-separated floats | `1.0` per component | One weight per component, in the same order. |
| `reward_parameters` | `--reward-parameters` | JSON object | none | Per-component parameters (section 5). |
| `telemetry` | `--telemetry` | `none` or `steps` | `none` | `steps` writes `<episode-dir>/steps.jsonl`. |
| `telemetry_every` | `--telemetry-every` | positive int | `1` | Save every kth policy decision. Requires `telemetry = steps`. |

Run from `scratch/mesh-sim/`. The flags go before the `m-ppo` subcommand:

```bash
.venv/bin/python -m scripts.rl.train \
  --sim-binary <BIN> \
  --run-config inputs/baselines/centralized-multi-smoke/run.ini \
  --output-dir outputs/rl-multi-custom \
  --observation-preset local_links_v1 \
  --reward-components delivery_ratio,connectivity \
  --telemetry steps --telemetry-every 2 \
  m-ppo --total-timesteps 16 --n-steps 16 --seed 1
```

### Resolution and validation

- Each key resolves independently: CLI > `run.ini` > default. Both manifests
  record the resolved value and its source.
- `observation_parameters` and `reward_parameters` resolve as complete objects;
  objects are not merged across sources.
- These fail before the simulator starts:
  - an unknown preset or component;
  - a weight count that does not match the components;
  - any non-default value of these keys in legacy mode;
  - unknown, unused, non-numeric, or non-finite parameters.
- Centralized runs need a simulator binary that exports per-decision facts. An
  `init` without `facts_schema` is rejected before training starts.

### Reward authority

Naming any component makes Python the reward authority:

- `step()` returns the weighted total.
- `info["reward"]` holds the per-component values, validity flags, weights, and
  total.
- The C++ value stays available as `info["reward"]["legacy"]`.

### Schema fingerprints

Both manifests carry SHA-256 fingerprints of the observation and reward schema
descriptions. A loader uses them to detect a changed declared layout,
normalization, component set, or weights. They cover the declared schema only:
code or physics changes outside it, and the simulator binary, do not change
them. `manifest_version` labels the saved JSON format, not the model or
simulator version.

## 3\. What the observation contains {#src_rl_policy_inputs_observation}

An observation is the numeric vector passed to the policy. Every preset makes
one block per `max_controlled_nodes` slot (`M`); a padded slot is all zeros.
`N` is the total number of mesh nodes, including uncontrolled nodes, excluding
jammers. Observations use the instantaneous `facts.nodes` and `facts.links` at
the decision boundary. The reward instead summarizes the preceding ticks in
`facts.window`.

| Preset | Per-slot values | dtype | Width per slot |
| --- | --- | --- | --- |
| `raw_links_v1` (default) | `active, x, y, z`, then `SINR dB, capacity Mbps` for each other mesh node, in node-file order | `float64` | `4 + 2(N-1)` |
| `local_links_v1` | `active, x_n, y_n, z_n`, then `present, sinr_valid, sinr_n, cap_n` for each other mesh node | `float32` | `4 + 4(N-1)` |
| `geometry_v1` | Self xy and relative peer xy, with active/present flags | `float32` | `3 + 3(N-1)` |
| `service_v1` | Local links plus demand/delivery logs and delivery/connectivity/unroutable ratios | `float32` | `9 + 4(N-1)` |
| `full_facts_v1` | Service features plus relative peer xyz/velocity, LOS, and service gap | `float32` | `10 + 11(N-1)` |
| `mission_facts_v1` | Mission inputs ([missions](@ref src_config_mission_controls)) | `float32` | — |
| `mission_facts_v2` | `mission_facts_v1` plus obstacle ranges and goal offsets per slot, and two global team features | `float32` | — |
| `mission_compact_v1` | One node block, one unordered-link block, six globals (section 3.5) | `float32` | 57 total at three peers |
| `mission_coordination_v1` | Coordinated mission inputs (section 3.5) | `float32` | 102 / 216 / 357 total at 3 / 6 / 9 peers |
| `mission_bridge_v1` | `mission_coordination_v1` with whole-team radio support (section 3.5) | `float32` | Same as `mission_coordination_v1` |

For slot-based layouts, total length is `M ×` the per-slot width. With three mesh nodes and
`M = 3`, the raw vector has 24 values and the local vector has 36. If only two
nodes are controlled, the final 8 or 12 values are padding.

Each preset owns its ordered features, Box bounds, required facts, and
compatibility fields.

### 3.1 `local_links_v1` features

| Feature | How Python derives it from raw facts | Declared range |
| --- | --- | --- |
| `active`, `present`, `sinr_valid` | 0/1 indicators for slot occupancy, peer presence, and usable SINR/capacity | `[0,1]` |
| `x_n`, `y_n`, `z_n` | `clamp(2 × (position - axis_min) / (axis_max - axis_min) - 1, -1, 1)` using the `[rl]` movement bounds in meters | `[-1,1]` |
| `sinr_n` | `clamp((SINR_dB + 20) / 60, 0, 1)` for a valid link | `[0,1]` |
| `cap_n` | `clamp(log10(1 + capacity_Mbps) / 4, 0, 1)` for a valid link | `[0,1]` |

- Coordinates map each axis to `[-1, 1]` so their scales are comparable. A node
  at `x_max` has `x_n = 1` even if its raw x is 100 m.
- `present = 1` means the peer occupies that position in the node list. It says
  nothing about whether the radio link works.
- `sinr_valid = 0` for a non-finite SINR or capacity, the simulator's `-999`
  sentinel, or any SINR at or below `-900` dB. An invalid link has
  `sinr_n = cap_n = 0`.
- `sinr_clip_db: [-20, 40]` names the raw dB endpoints of the SINR formula:
  -20 dB becomes 0, 10 dB becomes 0.5, and 40 dB or higher becomes 1. These are
  feature-design limits, not physical SINR limits.
- Clipping and scaling apply to this policy vector only. C++ link calculations,
  raw `facts`, `raw_links_v1`, and rewards are unchanged.

### 3.2 Normalization parameters

`observation_parameters` is a JSON object. Example:

```ini
observation_preset = full_facts_v1
observation_parameters = {"capacity_log10_denominator": 6, "velocity_scale_mps": 60}
```

| Parameter | Default | Accepted by |
| --- | --- | --- |
| `sinr_min_db` | `-20` | Normalized link presets |
| `sinr_max_db` | `40` | Normalized link presets |
| `sinr_invalid_db` | `-900` | Normalized link presets |
| `capacity_log10_denominator` | `4` | Normalized link presets |
| `velocity_scale_mps` | `40` | `full_facts_v1` |

SINR parameters require invalid < min < max. Capacity and velocity denominators
must be positive. Raw and geometry presets accept no normalization overrides.

### 3.3 Schema and Box bounds

`observations/__init__.py` declares a schema for each preset: ordered feature names,
vector length, dtype, normalization rules, and `low`/`high` bounds for each
value in Gymnasium's `Box`.

- `low` and `high` declare allowed feature values. They do not normalize
  anything and are not observed minima or maxima.
- Raw features are unbounded (`-∞`/`+∞` in the Box, saved as JSON `null`).
- `local_links_v1` positions are `[-1,1]`; its flags and link features are
  `[0,1]`.
- The schema fingerprint lets a loader reject a saved policy whose input layout
  changed. For `local_links_v1`, changing the movement bounds changes the
  meaning of coordinates and fails the structural compatibility check.
- Changing a formula requires a new preset or schema; editing the displayed
  `low`/`high` arrays is not enough.

### 3.4 Service and geometry presets

`geometry_v1`, `service_v1`, and `full_facts_v1` use zero padding.
Service-window features use scored-tick sums; a window with zero scored ticks
has zero service values. Geometry and current link facts stay available during
warmup so decisions can settle.

### 3.5 Mission presets

- **`mission_compact_v1`.** One node block, one unordered-link block, and six
  globals: 57 features at three peers, versus 137 uncompacted. It keeps current
  target offsets and local obstacle ranges and has no future jammer
  information. Every roster peer gets position, service, and obstacle
  features, including peers outside the control roster. Normalized goal
  coordinates and offsets are clipped to [0, 1] for every mission preset.
- **`mission_coordination_v1`.** Includes direct per-peer target closeness,
  arrival flags, achieved motion, the previous requested action, and native
  peer-blocking and wall-contact feedback. Future failure timing and future
  jammer coordinates are never exposed. A peer without a control slot has
  zero movement, rejection, wall contact, and previous-action features.
- **`mission_bridge_v1`.** Replaces only the explicit demanded-path support
  feature of `mission_coordination_v1` with whole-team support, at the same
  vector width.

The coordinated presets and rewards declare a version-1 `coordination_v1`
derived-fact extension:

1. `MeshRlEnv` resets its processors each episode.
2. It advances them after the existing mission state and before building the
   observation and reward.
3. Telemetry keeps the derived facts so each record can replay.

Reward and observation schemas name the extension. Reward parameters pin its
mission and coverage goal. Compatibility
checks require both saved reward and observation identities. Jamming uses the
native mission kind `coverage`, with saved mission code `3` selecting the
interference-response objective in the derived extension.

Source: `mission_compact_v1` in `scripts/rl/env/observations/compact.py`,
`mission_coordination_v1` in `scripts/rl/env/observations/coordination.py`
and `mission_bridge_v1` in `scripts/rl/env/observations/radio.py`
The source relocation changed no preset ID, layout or schema hash.

Layouts are specified above; coefficients, physical scales and thresholds
are in the [mission reward reference](../../docs/rl/mission-rewards.md).

## 4\. One action, several ticks, one reward {#src_rl_policy_inputs_reward}

With `tick_s = 0.1` and `decision_interval_s = 0.5`:

1. The agent chooses an action at tick 0.
2. The simulator runs ticks 1–5 with it.
3. At tick 5 the agent sees the resulting state and one reward computed from
   those five ticks.
4. Ticks 6–10 form the next window.

The reset observation at tick 0 contains a one-tick measurement but
contributes **no** policy-step reward. The last window can be shorter;
`ticks_in_step` reports its length.

### 4.1 Window sums

Every tick, C++ adds the current flow demands and deliveries, connected and
line-of-sight link counts, and its own per-tick reward to `facts.window`
([field list](@ref src_rl_per_decision_facts)):

- `demand_mbps_sum` and `delivered_mbps_sum` are sums of Mbps readings over
  flows and ticks (Mbps·tick), not transferred bytes.
- `flow_ticks_with_demand` counts flow/tick pairs with positive demand;
  `unroutable_flow_ticks` counts those that could not be routed.
- `connected_pairs_sum` and `los_pairs_sum` sum node-pair counts over ticks.
  `scored_ticks = 5` with `connected_pairs_sum = 15` means three connected pairs
  in each of five ticks.
- `legacy_reward_sum` sums C++'s per-tick `reward_type` values. The C++ message
  reward is always `legacy_reward_sum / window.scored_ticks`.

### 4.2 Base components

When `reward_components` is set, Python computes the components from the
*same* window and returns the weighted sum to Gymnasium:

| Component | Value for one window |
| --- | --- |
| `delivery_ratio` | `delivered_mbps_sum / demand_mbps_sum`. Invalid, with zero contribution, if the demand sum is ≤ `1e-9`. |
| `connectivity` | `connected_pairs_sum / (window.scored_ticks × num_links)` |
| `throughput_mbps` | `delivered_mbps_sum / window.scored_ticks`. Unnormalized: its scale grows with node count and demand. |
| `legacy` | `legacy_reward_sum / window.scored_ticks`: the C++ reward. Unrelated to legacy control mode. |

Worked example: over five ticks, demand sums to 150, delivery to 120, and 12 of
the `5 × 3 = 15` pair/tick observations are connected. Delivery ratio is
`120/150 = 0.8`, connectivity is `12/15 = 0.8`, and weights `1.0, 0.5` return
`1.0×0.8 + 0.5×0.8 = 1.2`.

- There is no separate reward per controlled node.
- A zero-demand window does not count as successful delivery: its ratio is
  invalid and contributes zero.
- `info["reward"]` shows the component values, validity flags, weights, total,
  and the C++ reward.

### 4.3 Authority and averaging

The reward schema's `authority` names the value Gymnasium returns: `cpp` when no
components are selected, `python` for the composed sum. C++ calculates and
exports its base reward in both cases. `reward_window = mean` names the C++
averaging rule; Python components use the window sums above. Neither setting
changes how many ticks elapse per decision.

## 5\. Reward component catalog

Rules for every component:

- Each registered component owns its calculation, dependencies, validation,
  and schema. The composer and replay do not dispatch on component names.
- Each component has its own hashed identity. Formulas, dependencies, and
  tunable parameters are part of the reward schema hash. Adding a component
  never changes an existing component's meaning or identity.
- All components mask windows with zero scored ticks.
- Reward scales are independent of observation scales.
- Components run in Python on bridge facts and do not change the action,
  mask, or physics. A component that needs a fact the simulator does not emit
  (for example `facts.node_service` or `init.node_types`) needs a simulator
  build that emits it.

`reward_parameters` is a JSON object keyed by component:

```ini
reward_components = service_success, unmet_sinr_quality
reward_weights = 1, 0.2
reward_parameters = {"service_success": {"delivery_threshold": 0.9, "routable_threshold": 0.95}, "unmet_sinr_quality": {"delivery_threshold": 0.9}}
```

### 5.1 Service and delivery

| Component | Rule |
| --- | --- |
| `delivery_binary` | `+1` for any delivery, else `-1`. Zero demand is masked. |
| `signed_delivery_ratio` | `2*clip(delivered/demand,0,1)-1`. Zero demand is masked. |
| `service_success` | `+1` if delivery and routable fractions meet their thresholds, else `-1`. |
| `service_failure` | `1` on service failure, else `0`. |
| `throughput_log_mbps` | `ln(1 + delivered_mbps_sum / window.scored_ticks)`: a scale-compressed throughput utility. |
| `worst_node_delivery_fraction` | Minimum `delivered_mbps_sum / demand_mbps_sum` over positive-demand rows of `facts.node_service`. Range `[0,1]`. With no offered incident demand: value `0`, validity `0`. |
| `coverage_fraction` | `facts.coverage.fraction`: connected-core coverage at the decision endpoint. Range `[0,1]`. Requires `[rl] coverage_enabled = true` (section 5.6). |
| `fair_node_service` | Mean of `sqrt(clip(node incident delivered/offered, 0, 1))`, excluding nodes without demand. Masked when no node has demand. |

- Service components (`service_success`, `service_failure`) own
  `delivery_threshold` and `routable_threshold`, both default `0.95`, in
  `(0,1]`. A scored zero-demand window is a service failure.
- `worst_node_delivery_fraction` and `fair_node_service` need a simulator that
  emits `facts.node_service`. That table does not expose jammer state or change
  the observation.

### 5.2 Signal quality

| Component | Rule |
| --- | --- |
| `sinr_quality` | Mean normalized current link SINR. Invalid links score zero. |
| `unmet_sinr_quality` | SINR quality × `clip((delivery_threshold-delivery_ratio)/delivery_threshold,0,1)`. Zero demand uses delivery ratio `0`. |
| `active_sinr_quality_v1` | Mean of `clip((SINR+20)/60,0,1)` over available peer pairs only. Invalid active links score zero; no available pairs masks the component. |

SINR components own `sinr_min_db`, `sinr_max_db`, and `sinr_invalid_db`
(section 3.2). `unmet_sinr_quality` also owns `delivery_threshold`.

### 5.3 Movement and safety

| Component | Rule |
| --- | --- |
| `travel_fraction` | Mean controlled-slot endpoint xy distance divided by speed × elapsed duration. Also masks a mixed warmup window, because endpoint data cannot separate its scored movement. |
| `origin_fraction` | Mean controlled-slot distance from the reset position divided by the bounds' xy diagonal. A scored endpoint state cost, including any relocation during warmup. |
| `span_travel_fraction` | Mean over controlled slots of XY distance traveled this decision divided by a type-specific span: drone 500 m, pedestrian/vehicle 300 m. A soft cost, not a movement limit; an out-and-back trip is charged twice. Requires `node_types`. |
| `drone_travel_fraction`, `pedestrian_travel_fraction`, `vehicle_travel_fraction` | Sum of that type's normalized slot travel divided by the number of active controlled slots. Zero when the type is absent. |
| `decision_travel_v1` | Mean physical XY travel divided by slot speed × decision interval. Range `[0,1]`. |
| `adaptive_movement_cost` | `(0.02 + 0.08 * H_previous) * travel_fraction`, where `H = min(clipped delivery, fair_node_service, coverage)`. Requires `node_service` and live coverage facts. |
| `unsafe_proximity_fraction` | `facts.safety.unsafe_ticks / window.scored_ticks`. A tick is unsafe when any two mesh nodes are closer than `[rl] unsafe_separation_m` (default 1 m) in 3D. |
| `peer_cohesion` | Per controlled node: `(initial − current) / span`, where initial and current are the 3D distances to the nearest other mesh node at reset (fixed peer), each with a 20 m floor, and span is 500 m (drone) or 300 m (pedestrian/vehicle). Clip to `[-1,1]`, then average over controlled nodes. Rewards moving together without rewarding crowding below 20 m. Requires `node_types`. |

- `adaptive_movement_cost`: health `H` is zero on reset, updates after reward
  composition, and never carries between episodes. Its coefficients and lag are
  declared in the reward schema.
- Safety counts proximity at every simulator tick, including uncontrolled mesh
  nodes and excluding jammers. There is no collision physics. A scenario that
  starts with overlapping nodes can incur the penalty before the policy can
  move them; check the starting layout.
- `fair_node_service` and `adaptive_movement_cost` are the Dynamic Balance
  components.
- `collision_attempt_fraction` is described with the
  [building and peer checks](@ref src_rl_building_avoidance).

### 5.4 Mission rewards

These need `[mission]` facts ([missions](@ref src_config_mission_controls)).

| Component | Rule |
| --- | --- |
| `team_goal_proximity_v1` | `clip(1 - team distance / scale_m, 0, 1)`, `scale_m` default 400. Team distance is the mean distance outside the team radius plus the nearest peer's remaining distance outside the arrival radius. |
| `survivor_service_maintained_v1` | `1` at every post-failure decision that meets the survivor and weakest-peer service targets, `0` when service is lost. Separate from the latched `recovery_complete` bonus. |
| `available_team_closeness_v1` | Formula in the mission reward reference below. |
| `demanded_path_sinr_margin_v1` | Formula in the mission reward reference below. |
| `target_proximity_potential_v1` | Includes an unclipped terminal potential correction and a fixed discount of 0.99. |
| `available_target_arrival_fraction_v1` | Share of available peers inside the horizontal team-target radius at the completed decision. Pays while present, so a departure removes its share. Excludes forced and mixed windows; invalid with no available peers; independent of offered traffic. Separate from native team completion and dwell. |
| `coordinated_service_bridge_v1` | Coordinated service reward whose geometric-isolation term is replaced by a deficit in the weakest whole-team widest-path sigmoid SINR, excluding failed relays. |
| `coordinated_coverage_sufficient_v1` | Coverage area reward capped at the existing per-case target. |

The [mission reward reference](../../docs/rl/mission-rewards.md) gives the
exact closeness, demanded-path, progress and coordinated formulas, coefficient
ranges and stage transitions. Radio support comes from current native links
and does not measure delivery capacity.

Source owners: `scripts/rl/env/rewards/shaping.py` (individual primitives),
`coordination.py` (fixed and state-dependent combinations) and `radio.py`
(whole-team radio support and sufficient-area variants). Public component IDs,
descriptors, registration order and schema hashes remain unchanged.

**Phased rewards (`env/rewards/mission_terms.py`).** `team_approach_cost_v1`,
`investigation_setup_v1`, `investigation_service_deficit_v1`,
`recovery_deployment_cost_v1`, `recovery_response_deficit_v1`, and
`recovery_settle_v1`.

- Investigation approach combines mean and worst remaining team distance with
  the nearest inner-zone distance.
- Setup is rewarded only during current connected team arrival.
- Recovery keeps the reset deployment before measured failure, then scores the
  largest current service/coverage deficit and qualifying dwell.
- Losing a current phase condition returns scoring to the earlier objective.
- The approach scale and deployment scale are tunable.
- Weights, gates, seed roles, and runtime: `inputs/custom/10-16-4/README.md`.

**Guided rewards (`env/rewards/mission_terms.py`).** `team_distance_delta_v2`,
`service_gated_coverage_v2`, `coverage_target_maintained_v2`, four
mission-specific `*_settle_cost_v2` descriptors, `post_failure_service_v2`,
`post_failure_sinr_v2`, and `post_failure_coverage_deficit_v2`. They use
measured mission state and movement context, with no new actor observation and
no future-event information. Goal-dependent movement costs and coverage
thresholds are tunable. Formulas and weights: `inputs/custom/10-16-5/README.md`.

### 5.5 Level 0 objectives

`level0_coverage_v1`, `level0_investigation_v1`, `level0_recovery_v1`, and
`level0_jamming_v1` each return `+1` when their single success condition holds,
otherwise `-0.001`:

| Component | Success condition |
| --- | --- |
| `level0_coverage_v1` | Connected outdoor coverage ≥ per-case `target` (reward parameter, default 0.5). |
| `level0_investigation_v1` | Every available peer within the configured team radius of the target. No connectivity, local coverage, or dwell requirement. |
| `level0_recovery_v1` | Survivor critical-flow delivered/offered ≥ 0.90. |
| `level0_jamming_v1` | Aggregate delivered/offered ≥ 0.90 during the emitting interval. |

- Event rewards are zero during deployment waiting and in mixed boundary
  windows ([deployment gate](@ref src_rl_deployment_gate)).
- Zero offered traffic cannot produce success.
- There are no movement, fairness, SINR, or collision-attempt terms. Native
  building and peer collision constraints stay active.

### 5.6 Facts some components need {#src_rl_policy_inputs_facts}

- **Live coverage.** `[rl] coverage_enabled = true` measures
  `coverage_fraction` at each decision endpoint, using the same clipped-cell
  receiver grid and connected-core union as the placement planners. Grid cells,
  minimum resolution, probe height and gain, and SINR threshold come from the
  matching `[baseline]` keys. Probe evaluation follows mesh-link evaluation,
  node-major then probe-major, and shares the configured propagation model, so
  enabling coverage can change later random draws. Every compared policy must
  enable it. The reward schema stores the grid settings and the proximity
  threshold.
- **Proximity.** `[rl] unsafe_separation_m` is positive and defaults to 1 m.
- **Buildings.** With `[rl] avoid_buildings = true`, centralized masks reject
  axis-aligned XY paths that intersect a building within a decision; per-tick
  revalidation also prevents entry.
- **Node types.** Type-based components need a simulator that emits
  `init.node_types`.

These options add `init`/`facts` fields without changing the action shape.

## 6\. Save and inspect decisions

With `telemetry = steps`, each episode gains `steps.jsonl`:

| Line | Contents |
| --- | --- |
| First (header) | Run contract, chosen settings, observation and reward schemas. |
| Each later line | Decision number, tick, the action that produced the just-finished window, current mask, revalidated slots, raw facts and window, returned reward, C++ reward, and `obs_sha256` (observation fingerprint). |

- `telemetry_every = 2` saves reset (decision 0), every second policy decision,
  and the terminal decision even if it falls between samples.
- Unsaved decisions still affect training, `rl_episode.json` totals, and the
  final outcome. `rl_episode.json` is updated every decision regardless of
  `telemetry_every`.
- Records are buffered and flushed every 32 records and on stop, so a hard kill
  can lose up to 32 records.
- On the `centralized-multi-smoke` fixture a record is about 0.9 KB and the
  header about 3.5 KB.

From `scratch/mesh-sim/`, inspect or replay one episode:

```bash
head -n 2 outputs/rl-multi-custom/episode-0000/steps.jsonl
.venv/bin/python -c 'from scripts.rl.env.telemetry import replay_file; import sys; print(replay_file(sys.argv[1]))' outputs/rl-multi-custom/episode-0000/steps.jsonl
```

**Replay** rebuilds saved observations and Python-composed rewards from each
record's raw facts and reports mismatches. It does not rerun radio physics,
check unsaved decisions, or recheck a C++-authored reward. Telemetry v3 replay
uses the saved resolved parameters and, for movement rewards, the saved
previous/reset position inputs and elapsed ticks; it recomputes context instead
of trusting precomputed scores. The [test map](@ref src_rl_policy_input_tests)
lists the fake-simulator and real-binary checks.

**Decision records** are a separate opt-in (`--decision-records` on `train.py`
and `evaluate.py`) that joins each action to the preceding `steps.jsonl` record
and its outcome window; see [decision records](@ref src_rl_decision_records).

## 7\. Reading an RL output directory {#src_rl_reading_output}

Start with the [output-location table](@ref scripts_rl_output), then read these
files in order. The ordinary simulator CSV columns are in the
[I/O guide](@ref src_io).

| File | Question it answers |
| --- | --- |
| `train_manifest.json` or `eval_manifest.json` | Which scenario, seed roles, model, observation/reward selection, and schema did this run use? Did it complete? |
| `maskable_ppo_mesh.zip`, `best_model.zip`, or `checkpoints/*.zip` (when produced) | Which policy artifact was saved? Use the manifest's path and digest to identify the intended file. |
| `episode-NNNN/rl_episode.json` | Did this episode complete, how many policy steps occurred, and what was its cumulative reward? Filter incomplete or zero-step episodes before aggregating. |
| `episode-NNNN/steps.jsonl` (when telemetry is enabled) | Which raw facts, action, mask, and reward were recorded at each saved decision? |
| `episode-NNNN/run.log`, `inputs/`, and `seed-N/` | Which resolved simulator configuration and archived inputs produced the raw CSV outputs? |
| `episode-NNNN/sim_stderr.log` | What did the simulator print on stderr, including launch or runtime diagnostics? |

### 7.1 Decode the trace header

The header holds two observation lengths:

| Header field | Length of |
| --- | --- |
| `contract.obs_dim` | The **raw C++ `obs` message**. |
| `observation_schema.obs_dim` | The **selected vector passed to the policy**, built by Python from `facts`. |

With `N = 3` and `M = 3`, `raw_links_v1` has `M × [4 + 2(N-1)] = 24` values and
`local_links_v1` has `M × [4 + 4(N-1)] = 36`. A `local_links_v1` policy sees 36
values while the same header says `contract.obs_dim: 24`. Changing the preset,
`N`, or `M` can change the policy dimension; changing positions or the seed
does not. `slot_node_ids` maps slots to nodes, with `null` for padding; padding
does not shorten the vector.

Within `observation_schema`, `feature_names[i]`, `low[i]`, and `high[i]` give the
name and declared `Box` bounds of policy feature `i` (section 3.3). They are
saved with the preset, the `normalization` object (which conversions were
selected), the physical movement `bounds`, and a schema fingerprint. The raw
preset saves unbounded entries as JSON `null`. The `local_links_v1` derivations
are in section 3.1.

### 7.2 Decode the raw facts and decision records

`facts` is source data, not the policy vector. `contract.facts_columns` gives
the row order:

- `facts.nodes`: one row per `node_ids` entry, in `nodes.json` order:
  `[x, y, z, vx, vy, vz, slot]`, positions in meters, velocities in m/s,
  `slot = -1` for an uncontrolled node.
- `facts.links`: one row per unordered mesh-node pair, `i<j` order with the
  first index outer: `[sinr_db, capacity_mbps, is_los]`. With nodes A, B, C the
  rows are `(A,B)`, `(A,C)`, `(B,C)`; `is_los` is 0/1. Jammers have no rows.
- `facts.window`: sums over the ticks since the previous decision (section 4.1).
- `init.node_types` gives each node's type in `node_ids` order.

**Example.** The header maps slot 0 to node B and sets x bounds `0..100`, y
bounds `-50..100`, and z bounds `0..50`.

- Node-B row `[100,-5,10,0,-10,0,0]`: position `(100,-5,10)` m, y velocity
  -10 m/s, control slot 0. Policy position `(x_n,y_n,z_n) = (1,-0.4,-0.6)`.
- `(A,B)` link row `[40.62,5397.59,1]`: SINR 40.62 dB, capacity 5397.59 Mbps,
  LOS. Local features `present=1`, `sinr_valid=1`, `sinr_n=1` (clipped at
  40 dB), `cap_n≈0.933`.

The observation vector itself is not stored in each record: `obs_sha256`
fingerprints it, and replay rebuilds it from facts.

**Decision 0 and 1.**

- Decision 0 is the reset observation. No action has been sent, so
  `action_sent = null` and the policy `reward = null`. A nonzero
  `legacy_reward` there is the C++ tick-0 diagnostic, not a training reward.
- Decision 1 records the action sent after reset and the reward for the
  resulting window. Its action has one entry per slot, including a padded
  slot's required hold (`4`).
- Training may first reset only to learn the simulator-dependent spaces before
  PPO starts. That probe can be saved as `episode-0000` with
  `status=interrupted`, `stop_reason=reset`, and zero policy steps; no training
  action is lost.

## 8\. Training and evaluation options

| Option | Read by | Default | Effect |
| --- | --- | --- | --- |
| `[rl] manifest_every_decisions` | Python episode writer | `1` (positive int) | In-progress manifest write cadence (section 8.1). |
| `[rl] jammer_motion_profile` | `env/jammer_motion.py` | empty | `sweep_v1` or `arrive_hold_v1` jammer motion (section 8.2). |

### 8.1 Manifest cadence

Set `manifest_every_decisions = 50` to reduce in-progress manifest writes.
Reset and finalization still save complete totals. This does not sample
`steps.jsonl`; evaluation matrices require every decision. An abrupt OS kill
can leave up to cadence − 1 decisions missing from the disk snapshot.

### 8.2 Jammer arrival profile

`jammer_motion_profile = arrive_hold_v1` archives a reproducible road approach
for each training episode or evaluation seed: an arrival coordinate and a
60-second transit, then holding.

- Onset comes from the existing training or evaluation onset schedule, with the
  same index used by `EpisodeSession`'s CLI onset override.
- Routes use the open horizontal street `y=200` or vertical street `x=245` in
  the 400 m `inputs/custom/10-23` inputs. The profile is specific to those
  scenarios; it does not plan roads on arbitrary maps.
- Emission ends at `duration_s + tick_s`, so the last sampled tick is still
  jammed. The archived interval is used instead of the C++ `--jammer-onset-s`
  override, which ends at `duration_s` and is half-open.
- An empty profile and `sweep_v1` behave as before; old result files are not
  reinterpreted or overwritten.
- Details: `inputs/custom/10-23/README.md`.

### 8.3 Movement metrics in evaluation

Evaluation v4 streams telemetry through the accumulator each metric declares.

- Travel and displacement cover controlled nodes only.
- Travel is the sum of xy endpoint distances. Displacement is measured from the
  last unscored endpoint, or from reset. Initial baseline placement is
  excluded.
- Per-node maps stay in JSON; scalar travel is used in comparison and CSV
  export.
- Movement metrics are `null` with no scored windows, a mixed warmup window, a
  missing reset, or sparse records, because telemetry cannot supply a per-tick
  path length.

### 8.4 Curriculum environment

`CurriculumEnv` in `scripts/rl/env/curriculum.py` can load a supplied schedule
of scenario files that vary peer start positions for coordinated investigation.
The wrapper records the resets it uses in `curriculum.json`. The standard
training entry point has no curriculum option in this revision.
