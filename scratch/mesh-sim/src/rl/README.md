# RL bridge contract

C++ owns movement limits, action validity, and reward accumulation. Python
converts and validates messages; it never re-derives masks or clamps.

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
| Slots | `M = max_controlled_nodes` (`0` auto-sizes to the resolved count); slots beyond the resolved count are padding |
| Action meanings | `0 west (-x)`, `1 east (+x)`, `2 south (-y)`, `3 north (+y)`, `4 hold`; z is never changed |
| Hold | sets the slot's velocity to `(0,0,0)` until the next decision; it does not repeat the previous command |
| Mask order | flat `5*M` array of 0/1, `[slot0 W,E,S,N,H, slot1 …]`; padded slot is `[0,0,0,0,1]`; hold is always valid |
| Mask rule (clip-at-wall) | a direction is valid iff there is room > `1e-6` m to that bound, so a direction is valid exactly when realized displacement would be > 0 |
| Clamp | every tick, before the clock advances, each axis velocity is reduced so the node lands exactly on the bound instead of crossing it |
| Speed cap | `v_i = min(step_size_m / tick_s, MaxSpeedForType(node_type))`, fixed at construction and reported in `init.slot_speed_mps` |
| Cadence | decisions at ticks `0, k, 2k, …` with `k = decision_interval_ticks`; velocities persist between decisions; physics still advances every `tick_s` |
| Partial windows | `num_decisions = ceil(num_ticks / k)`; the last window may be shorter, and every `step` reports its `ticks_in_step` |
| Reward window | mean of the per-tick reward over the ticks in the window (`{0}` for the reset message), so `k = 1` equals the legacy per-tick value |
| Terminal message | emitted at `tick == num_ticks` with `done: true`; no action is read after it |

Observation layout per slot (`L = 4 + 2*(N-1)`, `obs_dim = M*L`):
`[active, x, y, z, sinr(i,j0), cap(i,j0), sinr(i,j1), cap(i,j1), …]` with peers
in node-index order skipping the slot's own node; a padded slot is all zeros.
The `-999` SINR sentinel is passed through unchanged.

## Message fields

- `init` (centralized, first line, once per process): `type`, `contract`,
  `dimensions`, `action_meanings`, `max_controlled_nodes`, `num_controlled`,
  `slot_node_ids` (`null` for padding), `slot_speed_mps` (`null` for padding),
  `num_mesh_nodes`, `obs_dim`, `mask_dim`, `tick_s`, `decision_interval_s`,
  `decision_interval_ticks`, `num_ticks`, `num_decisions`, `reward_type`,
  `reward_window`, `wall_policy`.
- `step` (centralized): `type`, `tick`, `time_s`, `decision` (from 0),
  `ticks_in_step`, `obs`, `mask`, `reward`, `done`, `revalidated_slots`.
- action (centralized): `{"action":[…]}` — exactly `M` integers in `[0,4]`;
  padded slots must be `4`.
- `step` (legacy, unchanged): `type`, `tick`, `time_s`,
  `obs.{controlled_pos,link_sinrs,link_capacities}`, `reward`, `done`,
  `action_type`; action `{"action":<int>}`.

`time_s` is simulated time, never wall clock, so identical inputs give identical
stdout.

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
