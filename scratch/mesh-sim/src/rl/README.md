# RL bridge contract

At each decision, the simulator sends Python what the policy can see (`obs`),
which moves are allowed (`mask`), its reward, and raw measurements (`facts`).
The Gymnasium environment validates that message, selects the configured
observation and reward, and passes them to MaskablePPO. The chosen joint action
returns through the bridge; the simulator applies it until the next decision.
A decision window is the simulator ticks between those chances to change
direction. Each tick still updates movement, links, traffic, and reward.

C++ owns movement limits, action validity, and base reward accumulation. Python
converts and validates messages; it never re-derives masks or clamps.
For a code walkthrough, start with the tick loop in `sim.cc`, then
`src/config/rl-control.cc` for the selected nodes and timing, then
`src/rl/rl-bridge.cc` for the messages, actions, and tick reward. Follow one
`step` into `scripts/rl/env/mesh_env.py` to see what Gymnasium returns.

On the Python side, `scripts/rl/env/mesh_env.py` owns the Gymnasium API,
`protocol.py` validates actions and messages, and `episode.py` owns the
simulator process, episode directories, diagnostics, and manifest.
`selection.py` resolves the observation/reward/telemetry selection and its
precedence, and validates it. `observations.py` owns the named observation
presets and their schema identity. `rewards.py` owns the reward components and
the composer. `telemetry.py` owns `steps.jsonl` records and their replay.

## Modes

| Mode | Selected by | Action space | Stream |
| --- | --- | --- | --- |
| legacy | `[rl] controlled_node_id` (or neither selector) | `Discrete(7)`: `0:-X 1:+X 2:-Y 3:+Y 4:-Z 5:+Z 6:Stay`, absolute clamped target | one `step` line per tick, no `init` |
| centralized | presence of `[rl] controlled_nodes` | `MultiDiscrete([5]*M)` | one `init` line, then one `step` line per decision |

`controlled_node_id` and `controlled_nodes` are mutually exclusive. There is no
automatic migration: legacy action `4` is `-Z`, centralized action `4` is hold.
`action_set` and `dimensions` are not configuration keys.

## Centralized contract (`mesh_move_2d_v1`)

| Item | Value |
| --- | --- |
| Slot order | resolved `controlled_nodes` order; `all` means every `nodes.json` entry in file order. Jammers are never controllable. |
| Slots | A slot is one fixed position in the policy's action/observation vector, assigned to one controlled node. `M = max_controlled_nodes` (`0` auto-sizes); unused positions are padding, not extra nodes. |
| Action meanings | `0 west (-x)`, `1 east (+x)`, `2 south (-y)`, `3 north (+y)`, `4 hold`; z is never changed |
| Hold | action `4` commands zero velocity until the next decision. The node stops moving; it does not repeat the previous direction. A node can also stop at a wall while a direction remains commanded. |
| Mask order | flat `5*M` array of 0/1, `[slot0 W,E,S,N,H, slot1 …]`; padded slot is `[0,0,0,0,1]`; hold is always valid |
| Mask rule (clip-at-wall) | a direction is valid iff there is room > `1e-6` m to that bound, so a direction is valid exactly when realized displacement would be > 0 |
| Clamp | every tick, before the clock advances, each axis velocity is reduced so the node lands exactly on the bound instead of crossing it |
| Speed cap | `v_i = min(step_size_m / tick_s, MaxSpeedForType(node_type))`, fixed at construction and reported in `init.slot_speed_mps`. `step_size_m` is nominal movement **per simulator tick**, not per RL decision. |
| Cadence | decisions at ticks `0, k, 2k, …` with `k = decision_interval_ticks`; velocities persist between decisions; physics still advances every `tick_s` |
| Partial windows | `num_decisions = ceil(num_ticks / k)`; the last window may be shorter, and every `step` reports its `ticks_in_step` |
| Reward window | mean of the per-tick reward over the ticks in the window (`{0}` for the reset message), so `k = 1` equals the legacy per-tick value |
| Terminal message | emitted at `tick == num_ticks` with `done: true`; no action is read after it |

The agent cannot interrupt a command halfway through a decision window. To
change direction more often, reduce `decision_interval_s` to an integer multiple
of `tick_s` (down to one tick). The ratio check allows a `1e-6`-tick tolerance
for floating-point rounding; it does not allow arbitrary fractions. A
wall-clipped or held node still participates in
link, traffic, and reward calculations every tick; there is no separate wall or
hold reward. `revalidated_slots` in the *next* `step` lists only action positions
whose invalid command C++ replaced with hold. It does not list deliberate hold
actions or every node that happens to be stationary.
With `all_links_los`, the reward still depends on the current links' LOS;
being at a boundary or choosing hold has no bonus or penalty by itself.

### Worked three-node example

`inputs/baselines/centralized-multi-smoke/run.ini` controls `node-b,node-c` and sets
`max_controlled_nodes = 3`, so action positions 0 and 1 belong to those nodes;
position 2 is padding. Node-a follows its own random walk. With `tick_s = 0.1`,
`decision_interval_s = 0.5`, and `step_size_m = 1`, each active node can move up
to 1 m per tick, or 5 m over a five-tick decision window (subject to its speed
cap and the arena wall).

| Time | Joint action just chosen | Result at next decision |
| --- | --- | --- |
| `0.0 s` | `[2,1,4]`: b south, c east, padding hold | At `0.5 s`, b moves `(100,0)` → `(100,-5)`; c moves `(97,50)` → `(100,50)` and clips at `x_max`. |
| `0.5 s` | `[4,0,4]`: b hold, c west, padding hold | At `1.0 s`, b stays `(100,-5)`; c reaches `(95,50)`. |

`[0,0,0]` would command **west**, not stop. Its padding action would be
revalidated to hold. `[4,4,4]` commands both active nodes to stop. Each decision
reward is the mean of the per-tick rewards since the prior decision. The
time-zero reward is shown in the reset message but is not a policy-step reward.

Observation layout per slot (`L = 4 + 2*(N-1)`, `obs_dim = M*L`):
`[active, x, y, z, sinr(i,j0), cap(i,j0), sinr(i,j1), cap(i,j1), …]` with peers
in node-index order skipping the slot's own node; a padded slot is all zeros.
The `-999` SINR sentinel is still passed through unchanged in this `obs`; the
Python observation presets treat `sinr_db < -900` or a non-finite value as invalid.

## Message fields

Centralized `init` is the first line, sent once per simulator process:

- Identity and actions: `type`, `contract`, `dimensions`, `action_meanings`.
- Node layout: `max_controlled_nodes`, `num_controlled`, `slot_node_ids`,
  `slot_speed_mps`, `num_mesh_nodes`, `obs_dim`, `mask_dim`. Padded entries in
  the two slot lists are `null`.
- Timing and reward: `tick_s`, `decision_interval_s`,
  `decision_interval_ticks`, `num_ticks`, `num_decisions`, `reward_type`,
  `reward_window`, `wall_policy`.
- Facts metadata: `facts_schema`, `facts_columns`, `node_ids`, `num_links`,
  `bounds`, `band`, `jammer_path_enabled`, `warmup_s` (see below).

Each centralized `step` contains `type`; `tick`, `time_s`, `decision` (from 0),
and `ticks_in_step`; `obs`, `mask`, and `reward`; then `done`,
`revalidated_slots`, and `facts`. The agent replies with `{"action":[…]}`:
exactly `M` integers in `[0,4]`, with `4` for every padded position.

Legacy `step` remains unchanged: `type`, `tick`, `time_s`,
`obs.{controlled_pos,link_sinrs,link_capacities}`, `reward`, `done`,
`action_type`; its reply is `{"action":<int>}`.

`time_s` is simulated time, never wall clock, so identical inputs give identical
stdout.

## Per-decision facts (`mesh_facts_v1`)

Every centralized `step` carries a `facts` object of raw simulator values; C++
does no clipping, scaling, or feature selection. Legacy mode emits no facts and
its stream is unchanged. `init.facts_schema = "mesh_facts_v1"` names this
schema, and `init.facts_columns` names the column order of both tables:

| Table | Rows | Columns | Units |
| --- | --- | --- | --- |
| `facts.nodes` | `N`, in `nodes.json` order | `x, y, z, vx, vy, vz, slot` | m, m/s; `slot` is the controlled slot index or `-1` |
| `facts.links` | `N(N-1)/2`, pairs `i<j` with `i` outer | `sinr_db, capacity_mbps, is_los` | dB, Mbps, 0/1 |

Node rows are instantaneous at the decision tick, the same instant as `obs`:
position from the mobility model and the velocity in effect after the per-tick
bounds clamp. Link rows come straight from the symmetric link table, so a pair
appears once; the `-999` SINR sentinel is possible in principle and Python
treats it as invalid. `init` also carries `node_ids` (the `N` ids in file
order), `num_links`, the movement `bounds` (`x_min`…`z_max`), `band`,
`jammer_path_enabled` (`band = sub-6` with at least one enabled jammer, exported
as metadata only), and `warmup_s` (metadata: the RL reward does not skip warmup).

`facts.window` holds sums over exactly the ticks of this decision window, the
same window as `reward`:

| Field | Meaning |
| --- | --- |
| `ticks` | ticks in the window; equals `ticks_in_step` |
| `demand_mbps_sum`, `delivered_mbps_sum` | Σ over ticks of Σ over flows (Mbps·tick) |
| `flow_ticks_with_demand` | count of (tick, flow) pairs with `demand_mbps > 0` |
| `unroutable_flow_ticks` | those of the above that were not routable; zero-demand flows are excluded because the router marks them unroutable |
| `connected_pairs_sum` | Σ of the connected-pair count per tick |
| `los_pairs_sum` | Σ over ticks of the LOS pair count over `i<j` |
| `legacy_reward_sum` | Σ of the per-tick `reward_type` value |

Invariant: `reward == legacy_reward_sum / ticks` (`0.0` when `ticks == 0`), so
the emitted `reward` is unchanged by the facts export. The reset message covers
tick 0 only, so its window has `ticks = 1`; that reward is observable but is not
a policy reward. C++ never emits NaN or infinity in `facts`.

## Invalid or missing actions

| Case | Centralized | Legacy |
| --- | --- | --- |
| EOF (stdin closed) | all slots hold for the rest of the episode, one `Warning: RL action stream closed; all controlled nodes hold.`; every tick and message still runs | Stay, one `Warning: RL action stream closed; holding position (Stay).` |
| Structural error (bad JSON, not a list, wrong length, non-integer, out of range) | all slots hold, one `Warning: malformed RL joint action; all controlled nodes hold.` | Stay, one `Warning: malformed RL action JSON; holding position (Stay).` (a non-integer `action`, e.g. a list, is malformed rather than fatal) |
| Semantic error (masked-out direction, non-hold in a padded slot) | only that slot holds, one `Warning: RL joint action revalidated; invalid slot actions replaced by hold.`, and the slot index appears in the next message's `revalidated_slots` | n/a |

A centralized run never accepts a scalar action; a legacy run never accepts a list.

## Compatibility envelope

A policy is structurally compatible with a run only when `contract`,
`action_meanings`, `max_controlled_nodes` (→ `nvec`) and `num_mesh_nodes`
(→ `obs_dim`) all match. Padding stabilizes shapes across the number of *active*
slots within one N-node scenario; it does not stabilize shapes across scenarios
with different `N`, and matching shapes are not evidence that a policy transfers.

A future loader must check, each with its own error class:

1. **Structural** — manifest `contract.contract`, `action_meanings`,
   `max_controlled_nodes`, `num_mesh_nodes`, `obs_dim`, `mask_dim` equal the live
   `init`. Space equality alone cannot detect same-shape/different-meaning models.
2. **Scenario identity** — `slot_node_ids` plus the `run.ini`/`nodes.json`
   SHA-256 digests; a different scenario is a warning, not a silent proceed.
3. **Transfer** — never inferred from 1–2.

## Random streams

Replacing a controlled node's mobility model with a `ConstantVelocityMobilityModel`
can renumber the automatic RNG streams of other random walkers. Repeated scripted
resets stay deterministic, but that alone does not make an RL-versus-baseline
comparison fair: confirm uncontrolled and jammer randomness is paired before any
such campaign.
