@page src_rl src/rl

@brief Wire contract for the stdin/stdout JSON bridge between the C++ simulator and the Python Gymnasium environment.

This module connects the simulator to the Python Gymnasium environment in
`scripts/rl/` when the simulator runs with `--rl-mode`. At each decision the
simulator sends one JSON line on stdout and reads one action line on stdin. This
page is the message and action contract both sides follow. Observation presets,
reward components, and telemetry are on the
[policy-input page](@ref src_rl_policy_inputs).

## 1\. Overview

At each decision, the simulator sends Python what the policy can see (`obs`),
which moves are allowed (`mask`), its reward, and raw measurements (`facts`).
The Gymnasium environment validates that message, selects the configured
observation and reward, and passes them to MaskablePPO. The chosen joint action
returns through the bridge, and the simulator applies it until the next
decision.

- A **decision window** is the simulator ticks between two chances to change
  direction. Each tick still updates movement, links, traffic, and reward.
- C++ owns movement limits, action validity, and base reward accumulation.
- Python converts and validates messages. It never re-derives masks or clamps.

One decision, end to end:

1. `sim.cc` runs the ticks of the window. Each tick, `rl-motion.cc` clamps
   velocities and `rl-bridge.cc` accumulates the tick's reward and facts.
2. At the decision tick, `rl-bridge.cc` writes a `step` message.
3. `scripts/rl/env/mesh_env.py` validates it, builds the selected observation
   and reward, and returns them from Gymnasium's `step()`.
4. MaskablePPO picks one masked action per slot; Python writes
   `{"action":[…]}`.
5. `rl-motion.cc` revalidates the action and applies it until the next decision.

## 2\. Configure control

RL control is set in the `[rl]` section of `run.ini`:

| Key | Meaning |
| --- | --- |
| `controlled_nodes` | Required. Comma-separated node IDs, or `all`. Sets the slot order (see section 3). |
| `max_controlled_nodes` | `M`, the number of slots. `0` auto-sizes to the number of controlled nodes. |
| `action_profile` | `move_2d`. |
| `decision_interval_s` | Time between decisions. Must be an integer multiple of `tick_s`, down to one tick; the ratio check allows a `1e-6`-tick tolerance for floating-point rounding. |
| `step_size_m` | Nominal movement **per simulator tick**, not per decision. Sets the speed cap. |
| `reward_type` | The C++ per-tick reward: `throughput` (default) or `all_links_los` (section 4). |
| `x_min` … `z_max` | Movement bounds, reported in `init.bounds`. |

One policy uses `MultiDiscrete([5]*M)`, including one-slot runs. Every RL run
requires a joint action list, including a single controlled node.

**Removed keys:** `controlled_node_id`, `action_type`, and
`arrival_threshold_m` are removed. A configuration that uses them fails with
migration guidance: replace the selector with `controlled_nodes` and use
`action_profile = move_2d`. Scalar actions and continuous targets are
unsupported; rebuild or retrain older policies instead of translating their
action indices.

Optional keys that add messages or fields are in section 8. The Python-side
selection keys are in
[Selection keys and flags](@ref src_rl_policy_inputs_selection).

## 3\. Contract `mesh_move_2d_v2` {#src_rl_contract}

The contract is the agreed C++/Python message and action format.
`mesh_move_2d_v2` identifies the current two-dimensional protocol with five
actions per slot. The simulator reports it in `init.contract`; it is not a
`run.ini` setting. Python rejects an unknown contract name.

| Item | Value |
| --- | --- |
| Slots | A slot is a zero-based position in the fixed-length action, mask, and observation arrays. An active slot maps to one controlled node; an unused slot is padding and must hold. `M = max_controlled_nodes`. |
| Slot order | Resolved `controlled_nodes` order. `all` means every `nodes.json` entry in file order. Jammers are never controllable. Selecting the active traffic gateway is an error, including through `all`; list the other nodes explicitly. |
| Action meanings | `0` west (−x), `1` east (+x), `2` south (−y), `3` north (+y), `4` hold. z never changes. |
| Hold | Action `4` commands zero velocity until the next decision. The node stops; it does not repeat the previous direction. |
| Mask order | Flat `5*M` array of 0/1: `[slot0 W,E,S,N,H, slot1 …]`. A padded slot is `[0,0,0,0,1]`. Hold is always valid. |
| Mask rule (clip-at-wall) | A direction is valid iff there is more than `1e-6` m of room to that bound, so a direction is valid exactly when its realized displacement would be > 0. |
| Clamp | Every tick, before the clock advances, each axis velocity is reduced so the node lands exactly on the bound instead of crossing it. |
| Speed cap | `v_i = min(step_size_m / tick_s, MaxSpeedForType(node_type))`, fixed at construction and reported in `init.slot_speed_mps`. |
| Cadence | Decisions at ticks `0, k, 2k, …` with `k = decision_interval_ticks`. Velocities persist between decisions; physics advances every `tick_s`. |
| Partial windows | `num_decisions = ceil(num_ticks / k)`. The last window may be shorter; every `step` reports its `ticks_in_step`. |
| Reward window | `mean`: one policy reward is the arithmetic mean of the scored per-tick rewards since the previous decision. |
| Warmup | `reward_warmup = exclude`: ticks with `time_s < warmup_s` are not scored (section 4). |
| Terminal message | Sent at `tick == num_ticks` with `done: true`. No action is read after it. |

### Action examples

- `[0,0,0]` commands **west** for every slot; it does not stop. Its padding
  entry is revalidated to hold.
- `[4,4,4]` stops both active nodes in a two-node, three-slot run.
- With two controlled nodes and a padded third slot, `[2,1,0]` runs as
  `[2,1,4]` (section 7).

## 4\. Decision windows, reward, and walls {#src_rl_reward_and_wall}

### Per-tick reward and the decision mean

At tick 0 the simulator evaluates links and traffic and sends an initial reward
in the reset message. Gymnasium's `reset()` does **not** return that reward as a
learning step. After the agent chooses an action, every tick recomputes links,
traffic, and the `[rl] reward_type` value:

| `reward_type` | Per-tick value |
| --- | --- |
| `throughput` | Sum of delivered Mbps across flows. |
| `all_links_los` | `+1` if each controlled node has at least one other mesh node and every evaluated peer path is line-of-sight, else `−1`. |

The per-tick value is one network reward, not a reward per controlled node or
per slot. At the next decision, `reward_window = mean` sends the arithmetic mean
of the scored ticks as **one** step reward. For tick rewards `+1, −1, +1`, the
step reward is `+1/3` (one agent step).

Example with `warmup_s = 0`, `tick_s = 0.1`, `decision_interval_s = 0.5`
(`k = 5`), and a 10-tick run:

| Simulator ticks | What Python receives |
| --- | --- |
| `0` | Initial observation and reward in `reset()`; this reward is not a training step. |
| `1–5` | First action stays in effect; `step()` at tick 5 returns `(r1 + r2 + r3 + r4 + r5) / 5` with `ticks_in_step = 5`. |
| `6–10` | Second action stays in effect; the final `step()` returns `(r6 + … + r10) / 5` with `done = true`. |

If the episode ended at tick 7 instead, the final mean would use ticks 6–7 and
report `ticks_in_step = 2`. The agent cannot interrupt a command partway through
a window; to change direction more often, reduce `decision_interval_s`.

### Warmup

- Decisions and movement start at tick 0, during warmup.
- Rewards and summary metrics exclude ticks with `time_s < warmup_s`. The
  boundary tick is included.
- A window entirely within warmup returns reward `0`. A window crossing the
  boundary averages only its scored ticks.
- `ticks_in_step` counts elapsed ticks; `scored_ticks` is the mean's
  denominator. With no warmup they are equal: usually `decision_interval_ticks`,
  fewer in a short final window.
- Example: `warmup_s = 0.3` and a first decision at `0.5 s` score ticks 3–5 and
  exclude ticks 1–2.
- `init` reports `warmup_s` and `reward_warmup = exclude`. Contract version 2
  makes this scoring explicit and rejects version 1 clients and policies.
- Zero-reward windows are ordinary RL transitions: early actions can earn later
  rewards by improving the post-warmup state.

Episode manifest version 6 records `scored_ticks` across returned Gymnasium
steps, excluding the reset sample. Summary metrics can include the tick-0 sample
when warmup is zero. `cumulative_reward` sums decision means, so it differs from
an average or total of summary-metric samples.

### Walls and hold

- `wall_policy = clip`: before each tick, the simulator shortens an x/y
  velocity that would cross a configured bound, so the node lands exactly on the
  wall. It does not bounce, wrap, or move past the bound. The outward direction
  is masked at the next decision.
- A node can stop at a wall mid-window while a direction remains commanded.
  Its other ticks still contribute to the network reward.
- A held or wall-clipped node takes part in link, traffic, and reward
  calculations every tick. Hold and clipping have no separate reward or
  penalty. With `all_links_los`, the reward depends only on the current links'
  LOS.

### Worked three-node example

`inputs/baselines/centralized-multi-smoke/run.ini` controls `node-b,node-c` and
sets `max_controlled_nodes = 3`, so slots 0 and 1 belong to those nodes and slot
2 is padding. Node-a follows its own random walk. With `tick_s = 0.1`,
`decision_interval_s = 0.5`, and `step_size_m = 1`, each active node can move up
to 1 m per tick, or 5 m per five-tick window, subject to its speed cap and the
arena wall.

| Time | Joint action chosen | Result at next decision |
| --- | --- | --- |
| `0.0 s` | `[2,1,4]`: b south, c east, padding hold | At `0.5 s`, b moves `(100,0)` → `(100,-5)`; c moves `(97,50)` → `(100,50)` and clips at `x_max`. |
| `0.5 s` | `[4,0,4]`: b hold, c west, padding hold | At `1.0 s`, b stays at `(100,-5)`; c reaches `(95,50)`. |

## 5\. Messages

The simulator writes one JSON object per line on stdout; Python writes one per
line on stdin. `time_s` is simulated time, never wall clock, so identical inputs
give identical stdout.

| Message | Direction | When |
| --- | --- | --- |
| `init` | C++ → Python | First line, once per simulator process. |
| `step` | C++ → Python | At tick 0 (the reset message) and at every decision tick. |
| `{"action":[…]}` | Python → C++ | After every `step` with `done: false`. |

### `init`

| Field | Meaning |
| --- | --- |
| `type` | Always `init`. |
| `contract` | `mesh_move_2d_v2` (section 3). |
| `dimensions` | `2`: actions move horizontally; z can still appear in observations. |
| `action_meanings` | `["west","east","south","north","hold"]`, for actions 0–4. |
| `num_mesh_nodes` | `N`: total mesh nodes in `nodes.json`, including uncontrolled nodes, excluding jammers. |
| `max_controlled_nodes` | `M`: fixed slot count, including padding. |
| `num_controlled` | Active controlled nodes; `1 <= num_controlled <= max_controlled_nodes`. |
| `obs_dim` | Raw observation length, `M * (4 + 2*(N-1))`. |
| `mask_dim` | Flat mask length, `5*M`. |
| `slot_node_ids` | Node ID for each slot, in order; `null` for padding. |
| `slot_speed_mps` | Speed cap for each slot in m/s; `null` for padding. |
| `tick_s` | Simulated seconds per tick. |
| `decision_interval_s` | Simulated seconds between decisions. |
| `decision_interval_ticks` | `k = decision_interval_s / tick_s`. |
| `num_ticks` | Total ticks in the episode. |
| `num_decisions` | `ceil(num_ticks / k)`. |
| `reward_type` | C++ per-tick reward from `[rl] reward_type`. |
| `reward_window` | `mean` (section 4). |
| `warmup_s`, `reward_warmup` | Scoring cutoff in seconds, and `exclude`. Decisions continue during warmup. |
| `wall_policy` | `clip` (section 4). |
| `facts_schema` | `mesh_facts_v2` (section 6). |
| `facts_columns` | Column names of `facts.nodes` and `facts.links`. |
| `node_ids` | The `N` node IDs in `nodes.json` order. |
| `node_types` | Node type of each node, in `node_ids` order. |
| `num_links` | `N(N-1)/2`. |
| `bounds` | Movement bounds `x_min`, `x_max`, `y_min`, `y_max`, `z_min`, `z_max` in meters. |
| `band` | Resolved radio band. |
| `jammer_path_enabled` | `true` when `band = sub-6` and at least one jammer is enabled. Metadata only. |
| `unsafe_separation_m` | Proximity threshold for `facts.safety` (section 6). |
| `avoid_buildings`, `avoid_node_collisions`, `navigation`, `node_service_columns`, `coverage`, `mission`, `deployment_gate`, `control_start_s` | Optional-feature fields (section 8). |

`contract`, `reward_window`, and `wall_policy` are reported by the simulator;
they are not `run.ini` settings.

**Episode signature.** Python keeps a dictionary of `init` values as the
episode signature and compares it on every later reset. Any change is an error,
because one Gymnasium environment must keep the same action and observation
layout and behavior. The signature holds `control_mode = "centralized"` (set by
Python), `nvec = (5,)*M` (Python's `MultiDiscrete` sizes), and these `init`
fields: `contract`, `dimensions`, `action_meanings`, `num_mesh_nodes`,
`facts_schema`, `node_ids`, `bounds`, `max_controlled_nodes`, `obs_dim`,
`mask_dim`, `slot_node_ids`, `slot_speed_mps`, `tick_s`, `decision_interval_s`,
`decision_interval_ticks`, `num_ticks`, `num_decisions`, `reward_type`,
`reward_window`, `warmup_s`, `reward_warmup`, `wall_policy`,
`unsafe_separation_m`, `avoid_buildings`, `avoid_node_collisions`,
`navigation`, `deployment_gate`, `control_start_s`, `coverage`, and `mission`.

### `step`

| Field | Meaning |
| --- | --- |
| `type` | Always `step`. |
| `tick`, `time_s` | Current tick and simulated time in seconds. The reset message is tick 0. |
| `decision` | Zero-based decision index. Reset is 0; the first action's result is 1. |
| `ticks_in_step` | Elapsed ticks in the window. Reset has 1. |
| `scored_ticks` | Ticks at or after warmup. The reward is their mean, or `0` if there are none. |
| `obs` | Flat observation, length `obs_dim` (layout below). |
| `mask` | Flat 0/1 valid-action array, five entries per slot, length `mask_dim`. |
| `reward` | Mean reward over this message's scored ticks. |
| `done` | `true` at the final tick; no action follows. |
| `revalidated_slots` | Slots from the previous action that C++ changed to hold (section 7). |
| `facts` | Raw node, link, and window measurements (section 6). |

**`obs` layout.** Per slot, `L = 4 + 2*(N-1)` values and `obs_dim = M*L`:
`[active, x, y, z, sinr(i,j0), cap(i,j0), sinr(i,j1), cap(i,j1), …]`. Peers are
in node-index order, skipping the slot's own node. A padded slot is all zeros.
The `-999` SINR sentinel passes through unchanged; the Python observation
presets treat `sinr_db < -900` or a non-finite value as invalid.

### Action reply

Python replies with `{"action":[…]}`: exactly `M` integers in `[0,4]`, with `4`
for every padded slot.

## 6\. Per-decision facts (`mesh_facts_v2`) {#src_rl_per_decision_facts}

Every `step` carries a `facts` object of raw simulator values. C++ does no
clipping, scaling, or feature selection, and never emits NaN or infinity in
`facts`. `init.facts_schema = "mesh_facts_v2"` names the schema, and
`init.facts_columns` gives the column order of both tables.

| Table | Rows | Columns | Units |
| --- | --- | --- | --- |
| `facts.nodes` | `N`, in `nodes.json` order | `x, y, z, vx, vy, vz, slot` | m, m/s; `slot` is the controlled slot index or `-1` |
| `facts.links` | `N(N-1)/2`, pairs `i<j` with `i` outer | `sinr_db, capacity_mbps, is_los` | dB, Mbps, 0/1 |

- Node rows are instantaneous at the decision tick, the same instant as `obs`:
  position from the mobility model and velocity after the per-tick bounds clamp.
- Link rows come from the symmetric link table, so each pair appears once. The
  `-999` SINR sentinel is possible; Python treats it as invalid.

### `facts.window`

Sums over the scored ticks of this decision window, the same window as
`reward`. Ticks before warmup add nothing.

| Field | Meaning |
| --- | --- |
| `scored_ticks` | Ticks at or after warmup; equals the step's `scored_ticks`. |
| `demand_mbps_sum`, `delivered_mbps_sum` | Σ over ticks of Σ over flows (Mbps·tick). |
| `flow_ticks_with_demand` | Count of (tick, flow) pairs with `demand_mbps > 0`. |
| `unroutable_flow_ticks` | Those pairs that were not routable. Zero-demand flows are excluded because the router marks them unroutable. |
| `connected_pairs_sum` | Σ of the connected-pair count per tick. |
| `los_pairs_sum` | Σ over ticks of the LOS pair count over `i<j`. |
| `legacy_reward_sum` | Σ of the per-tick `reward_type` value. |

Invariant: `reward == legacy_reward_sum / scored_ticks`, or `0.0` when
`scored_ticks == 0`. The facts export does not change `reward`. The reset
message covers tick 0 only, so its window has `scored_ticks = 1` only when
warmup is zero; that reward is observable but is not a policy reward.

### `facts.safety`

| Field | Meaning |
| --- | --- |
| `threshold_m` | `[rl] unsafe_separation_m` (positive, default 1 m). |
| `unsafe_ticks` | Scored ticks in the window with any mesh-node pair closer than the threshold in 3D. |
| `min_pair_distance_m` | Minimum 3D pair distance in meters; `null` at reset or with fewer than two mesh nodes. |
| `building_rejected_slots`, `peer_rejected_slots` | Unique slots of the preceding action rejected by building or peer-collision checks (section 8). |
| `boundary_contacted_slots` | Slots whose moving x/y axis reached a wall during the preceding window. Telemetry only; hold and motion parallel to a wall do not count. |

Safety counts proximity only; there is no collision physics. Jammers are
excluded.

### `facts.node_service`

`init.node_service_columns = ["demand_mbps_sum","delivered_mbps_sum"]` declares
this table. It has one row per `node_ids` entry. Routed flow demand and
delivered traffic are added at both endpoints, so each column sums to twice the
matching `facts.window` sum. The Python reader validates this table when `init`
declares it and accepts older simulators without it.

The safety and service facts are additive: they do not change the action or
observation vector.

## 7\. Invalid or missing actions {#src_rl_invalid_actions}

| Case | Result |
| --- | --- |
| EOF (stdin closed) | All slots hold for the rest of the episode; one warning; ticks and messages continue. |
| Bad JSON or action shape, non-integer, out of range | All slots hold; one malformed-action warning. |
| Masked direction, or non-hold padding | Only the invalid slots hold; one revalidation warning; their indices appear in the next `revalidated_slots`. |

`revalidated_slots` lists **zero-based slot positions**, not node IDs. C++
replaces each invalid position with hold (`4`) before movement; valid positions
keep their commands. Example: with two controlled nodes and a padded third
slot, `[2,1,0]` runs as `[2,1,4]`, and the *next* `step` reports
`"revalidated_slots":[2]`. The list is empty for a deliberate hold, for wall
clipping during movement, and for a malformed whole action (where all slots
hold instead).

Python rejects non-object JSON messages and invalid contracts or fields, then
reaps the simulator and finalizes the episode as failed.

## 8\. Optional features

Each feature below is opt-in. Unless stated, it adds `init` or `facts` fields
and keeps the `mesh_move_2d_v2` action meanings and raw observation shape.

### Joint collision avoidance

`[rl] avoid_node_collisions` checks continuous joint movement paths, splits
them at wall-arrival times, and holds unsafe moving slots before advancement.
Holding can change another slot's path, so the joint set is checked again.
Rejected slots appear in `revalidated_slots`, and their applied actions are
holds. Building masks still apply. Pure movement tests are in `tests/unit/rl`.

### Building avoidance and navigation {#src_rl_building_avoidance}

| Key | Effect |
| --- | --- |
| `[rl] avoid_buildings = true` | Masks reject axis-aligned XY paths that intersect a building within a decision; per-tick revalidation also prevents entry. |
| `[rl] mask_building_moves = false` | Permits a wall-directed proposal; physics rejects its entire decision path before movement. |
| `[rl] building_clearance_m` | Expands building walls and roofs for movement checks. |

Joint peer motion still uses swept 3D separation. `init.navigation` (version 1)
publishes the resolved building bounds, the wall clearance, the
building-mask setting, and the 20 m local sensing range.

`facts.safety.building_rejected_slots` and `peer_rejected_slots` list the
unique slots rejected in the preceding action. `collision_attempt_fraction`
charges the union of these slots divided by the controlled-peer count; windows
with zero scored ticks remain masked. Unsafe-proximity ticks are a separate
measure.

### Missions {#src_rl_missions}

The @ref src_config_mission_controls "mission configuration reference" lists
defaults and valid combinations. `[mission] kind = coverage|investigation|recovery`
adds `init.mission` and per-step `facts.node_available` in `node_ids` order.
`facts.mission` reports goal-region coverage (`goal_coverage_fraction`) at the
decision endpoint. It is zero outside investigation and for an empty goal region
when the coverage gate is disabled. Regular network coverage uses the full
retained outdoor grid.

Survivor demand and delivery sums count only flows whose two endpoints were
available on the scored tick. `survivor_node_service` has one demand and delivery
row per `node_ids` entry. Each column sums to twice its survivor total.

- **Dropped peer.** It keeps its slot but has a hold-only mask, zero velocity,
  zero link capacity, and no coverage contribution. Peer-motion collision checks
  skip it. Its original offered demand is still measured.
- **Mission state.** Python builds `mission_state` with previous distance and
  health, measured failure time, dwell counters, pre-failure coverage, and
  completion times. Telemetry keeps these measurements and replays them with the
  `mission_facts_v1` preset and reward schemas. Future dropout schedules never
  enter the policy observation.
- **Coverage domain.** Mission coverage is area-weighted over outdoor probe
  cells, excluding building-occupied centers (`coverage_domain =
  "outdoor_probe_cells"`). Older whole-field scenarios measure a different
  domain.
- **Metrics.** Mission metrics are optional registry entries in
  `policy/metrics.py`. Evaluation manifest version 7 records them; regenerate
  version 6 evaluations with current tooling before using them with current
  comparison readers.
- **Observations.** `mission_facts_v2` keeps the `mission_facts_v1` inputs and
  adds, per slot, four local obstacle ranges, goal offsets, and team arrival and
  connectivity measurements. The `mission_facts_v1` layout is unchanged.

The campaign formulas and launcher stages are in
`inputs/custom/10-16/README.md`.

**Team investigation (mission version 2).** With `team_investigation = true`,
`init.mission.version` is `2` and adds `team_radius_m` and
`team_delivery_target`. Completion requires, for the dwell duration:

1. every available peer within `team_radius_m`,
2. at least one peer within the arrival radius,
3. a connected team,
4. `team_delivery_target` survivor service, and
5. local coverage.

| Setting | Effect when zero |
| --- | --- |
| `[mission] recovery_coverage_ratio` | Disables the coverage-restoration gate. Delivery and weakest-survivor gates stay active. |
| `[mission] team_delivery_target` (investigation only) | Disables the secondary-service gate. Extension shapes are unchanged. |
| `[mission] goal_coverage_target` (investigation only) | Disables the goal-coverage gate. Extension shapes are unchanged. |

C++ and Python validators both accept zero for these. Native team completion
still requires a connected core. The independent scenario-check metric measures
all-peer radius and dwell.

### Deployment gate (version 1) {#src_rl_deployment_gate}

`[rl] control_start_s` defaults to `0`. A positive value:

- adds `init.deployment_gate = {"version":1,"source":"control_start_s"}` and
  `init.control_start_s`;
- makes every controlled-slot mask hold-only before that time; action
  application and the per-tick velocity clamp enforce the same rule, and actions
  unlock at the boundary;
- adds `facts.deployment` with `active` and `eligible_ticks` (scored samples
  strictly after the gate).

Level 0 event rewards are zero unless the full scored window is eligible, so
the event-boundary observation carries zero event reward. Raw timing is not
added to actor observations. Python protocol validation and telemetry replay
validate the advertised fields. Reward identity depends on the versioned
eligibility rule, not on the seed-specific onset. Without the gate, the contract
and facts layout are unchanged.

### Live coverage

`[rl] coverage_enabled = true` adds `init.coverage` (grid settings and
`measurement = "decision_endpoint_connected_core"`) and
`facts.coverage.fraction`. The measurement is described in
[Facts some components need](@ref src_rl_policy_inputs_facts).

## 9\. Saved-policy compatibility {#src_rl_compatibility_envelope}

A policy is structurally compatible with a run only when `contract`,
`action_meanings`, `max_controlled_nodes` (→ `nvec`), and `num_mesh_nodes`
(→ `obs_dim`) all match. Padding keeps shapes stable across the number of
*active* slots within one `N`-node scenario. Scenarios with a different `N`
have different shapes.

`scripts/rl/policy/compat.py` checks a saved model against the live run in
this order. Each step has its own error class, and the check stops at the first
failure:

1. **Structural.** Manifest `contract.contract`, `dimensions`,
   `action_meanings`, `max_controlled_nodes`, `num_mesh_nodes`, `obs_dim`,
   `mask_dim`, and `facts_schema` must equal the live `init`. Space equality
   alone cannot catch a model with the same shapes and different meanings.
2. **Observation schema.** The saved schema is compared with the live one.
   Structural fields are errors; scenario identity fields are warnings.
3. **Reward.** The saved `reward_schema` SHA-256 must equal the live one. A
   C++-authored or `legacy`-containing reward must also match `reward_type` and
   `reward_window`.
4. **Scenario identity.** `slot_node_ids`, `node_ids`, the SHA-256 digests of
   `run.ini`, `nodes.json`, `buildings.json`, and `jammers.json`, and the band.
   Only this step can be relaxed by an explicit override.
5. **Transfer.** Not checked. Steps 1–4 say nothing about how well a policy
   performs in another scenario.

### Saved scenario identity {#src_rl_saved_scenario_identity}

Training writes `scenario_identity` in `train_manifest.json`
(`read_scenario_identity` in `scripts/rl/env/config.py`):

| Field | Value |
| --- | --- |
| `run_config` | Absolute path to the supplied `run.ini`. |
| `run_ini_sha256` | SHA-256 of the `run.ini` contents. |
| `nodes_json_sha256` | SHA-256 of the nodes file: `[scenario] nodes_file`, resolved relative to `run.ini` unless absolute; default `nodes.json`. |
| `buildings_json_sha256` | SHA-256 of the buildings file; `null` when not configured. |
| `jammers_json_sha256` | SHA-256 of the jammers file; `null` when not configured. |

- The fingerprints do not change the simulation or the reward.
- Waypoints, a CLI band override, and the simulator binary are not
  fingerprinted. The band is compared separately in step 4.
- The selected node order and protocol settings are saved separately in the
  manifest's `contract` field.

When changing the protocol or a saved-file format, follow the
["update together" checklist](@ref Contributing).

## 10\. Module layout

| File | Role |
|------|------|
| `rl-bridge.h` / `rl-bridge.cc` | `RlBridge`: exchanges messages and accumulates decision-window facts. |
| `rl-motion.cc` / `joint-motion.h` | Builds action masks, applies velocities, and checks joint paths before advancing the simulator. |
| `reward-window.h` | `RewardWindow`: counts elapsed and scored ticks and averages post-warmup rewards. |
| `rl-agent.h` | Unused no-op placeholder. Only the rl-bridge unit test includes it. |
| `README.md` | This page: the message, mode, and action contract. |
| @ref src_rl_policy_inputs "policy-inputs.md" | Observation presets, reward components, telemetry. |
| @ref src_rl_decision_records "decision-records.md" | Opt-in per-episode decision records. |
| @ref src_rl_policy_input_tests "policy-input-tests.md" | Test map for centralized RL and policy inputs. |
| @ref src_rl_policy_lifecycle_tests "policy-lifecycle-tests.md" | Test map for the validate, train, inspect, evaluate lifecycle. |
| @ref src_rl_policy_comparison_tests "policy-comparison-tests.md" | Test map for policy comparison and experiment matrices. |

### Code walkthrough

1. The tick loop in [`sim.cc`](../../sim.cc) advances the ticks.
2. `src/config/rl-control.cc` resolves the selected nodes and timing.
3. [`rl-bridge.cc`](rl-bridge.cc) exchanges messages and accumulates the tick
   reward. [`rl-motion.cc`](rl-motion.cc) applies actions.
4. `scripts/rl/env/mesh_env.py` builds what Gymnasium returns for one `step`.

For training, follow [`train.py`](@ref rl/train.py) (CLI and model output) into
[`agents/mask_ppo.py`](@ref agents/mask_ppo.py) (MaskablePPO setup), then into
the environment.

### Python side

Documented in [`scripts/rl/README.md`](@ref scripts_rl),
[`scripts/rl/env/README.md`](@ref scripts_rl_env),
[`scripts/rl/policy/README.md`](@ref scripts_rl_policy), and
[`scripts/rl/tests/README.md`](@ref scripts_rl_tests).

| Python file (`scripts/rl/`) | Owns |
|-------------|------|
| `env/mesh_env.py` | The Gymnasium API. |
| `env/protocol.py` | Action and message validation. |
| `env/episode.py` | Simulator process cleanup and diagnostics. |
| `env/recording/artifacts.py` | Episode directories, manifests, and telemetry lifecycle. |
| `env/selection.py` | Observation, reward, and telemetry selection, precedence, and validation. |
| `env/observations/__init__.py` | Named observation presets and their schema identity. |
| `env/rewards/__init__.py` | Reward components and the composer. |
| `env/recording/telemetry.py` | `steps.jsonl` records and their replay. |
| `env/recording/decisions.py` | The opt-in [decision records](@ref src_rl_decision_records). |
| [`env/config.py`](../../scripts/rl/env/config.py) | Seed, movement bounds, and scenario fingerprints. |
| `train.py`, `agents/mask_ppo.py` | Training CLI and model output, then MaskablePPO setup. |

For a worked configuration, formulas, normalization, and trace inspection, see
the [policy-input guide](@ref src_rl_policy_inputs).

## 11\. Behavior notes

- **Random streams.** Replacing a controlled node's mobility model with a
  `ConstantVelocityMobilityModel` can renumber the automatic RNG streams of
  other random walkers. Repeated scripted resets stay deterministic. Before an
  RL-versus-baseline comparison, confirm that uncontrolled-node and jammer
  randomness is paired.

## 12\. Tests {#src_rl_tests}

Test maps (inputs and expected outputs):

- @ref src_rl_policy_input_tests -- centralized action contract, observations, rewards, telemetry.
- @ref src_rl_policy_lifecycle_tests -- validate, train, inspect, evaluate.
- @ref src_rl_policy_comparison_tests -- policy comparison, experiment matrix, evaluation pipeline.

The test files live in [`scripts/rl/tests/`](@ref scripts_rl_tests). C++
movement tests are in `tests/unit/rl` and `tests/unit/rl-bridge`.
