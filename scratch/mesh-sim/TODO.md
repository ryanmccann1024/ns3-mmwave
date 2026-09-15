# TODO — Future Possibilities

P0 validation results are recorded in
[`docs/rl-program/p0-baseline/baseline-test-results.md`](docs/rl-program/p0-baseline/baseline-test-results.md).
The human accepted these results and is the final PR reviewer; no separate
completion report is required for P0.

## RL Enhancements

### Multi-Node Control
RL currently controls one node. Future: control all node positions via
multi-agent RL or a centralized controller. Each node already has its own
max speed from `node_type`.

### Continuous Desired-Position Actions with SB3
The discrete left/right/stay action space is a v0 simplification. The
continuous action type (`action_type = continuous`) is already implemented
and outputs absolute target (x, y) coordinates. Next step: integrate
Stable Baselines 3 (PPO/SAC) using the Gymnasium env which already supports
both discrete and continuous spaces.

### Richer Reward Shaping
Currently supports `throughput` (sum delivered_mbps) and `all_links_los`
(`mean_sinr` is a deprecated alias for it). Future: weighted combinations of
throughput, fairness (min-link capacity), latency, coverage area, or energy
cost.

### 3D Movement for Drones
The discrete action space already includes +/-Z alongside +/-X, +/-Y and Stay;
the continuous action type still emits a 2-D target only. Remaining work:
per-node-type constraints so aerial nodes (drones) control altitude while
ground nodes (vehicles, pedestrians) stay 2-D constrained, and a verified 3-D
continuous action space.

### Larger Discrete Action Spaces
Add 4-direction (up/down in y-axis) and 8-direction (diagonals) as
additional `action_type` options.

### TODO-RL-SEEDS-1 — Multi-seed training policy
P0 trains with one fixed seed (`m-ppo --seed`, else `[scenario] seed`) reused by
every episode. Deciding whether episodes should vary the seed, and how the
model/manifest should record that, is deferred.
Owner: team — status: open.

## Jammer model decisions (P0, unresolved)

P0 deliberately froze the current jammer behavior and changed no physics. The
following questions must be answered by the team before any change; do not
infer answers from the code.

- **TODO-JAM-1 — Link failure / 0 dB floor.** Jammed SINR is currently floored
  at 0 dB. Should 0 dB make the link unusable, or should the floor be removed so
  SINR can fall below the -6.7 dB link threshold?
  Owner: team/Kyle/jammer developer — status: open.
- **TODO-BAND-1 — Default band.** Should newly generated scenarios default to
  `sub-6` while existing scenarios keep `mmwave`, or should one global default
  apply?
  Owner: team/Kyle/jammer developer — status: open.
- **TODO-BAND-2 — Band versus frequency.** Should `band` stay an explicit
  scenario choice, be renamed to describe its actual jammer-interference role,
  or eventually be derived from / validated against `frequency_ghz`?
  Owner: team/Kyle/jammer developer — status: open.
- **TODO-JAM-2 — Endpoint rule.** Interference is computed at both link
  endpoints and the worse value is used. Is that correct?
  Owner: team/Kyle/jammer developer — status: open.
- **TODO-JAM-3 — Frequency overlap.** Should a jammer affect a channel whenever
  the frequency ranges overlap, instead of the current carrier-center test?
  Owner: team/Kyle/jammer developer — status: open.
- **TODO-JAM-4 — Recorded motion.** Which Sherpa file is the authoritative
  jammer trajectory, and should it become waypoints or another recorded-motion
  form?
  Owner: team/Kyle/jammer developer — status: open.
- **TODO-JAM-5 — Receive antenna effects.** Should the receiving node's antenna
  direction/gain alter jammer interference, in addition to the jammer's own
  pointing direction?
  Owner: team/Kyle/jammer developer — status: open.
- **TODO-JAM-6 — Duty cycle.** Should constant and random jammers keep
  interpreting duty cycle differently?
  Owner: team/Kyle/jammer developer — status: open.

## Data provenance

### TODO-DATA-1 — EW-trials source table and generated jammers.json
No EW-trials source CSV and no field-generated `jammers.json` exist anywhere
under `scratch/mesh-sim/`. The synthetic
`inputs/baselines/p0-jammer-smoke/jammers.json` is P0's only jammer coverage and
is not field data. `scripts/validation/make_jammers.py` is the generator: it
reads an EW trial log CSV plus a scenario's `gps_all_nodes_trace.csv` and emits
a `jammers.json` aligned to that scenario, but no input table for it is present
here. Identify the owner and location of the real EW trials table, confirm how
it drives `make_jammers.py`, and decide whether generated jammer input belongs
in `inputs/calfex/` or stays local.
Owner: team — status: open.

## Beam Codebook Model

mesh-sim currently uses ideal beamforming (fixed gain = 2 x 10*log10(N) dB).
In ns3-mmwave, beam management is handled by `MmWaveBeamforming` which uses a
discrete beam codebook, performs beam sweeping, selects optimal TX/RX beam
pairs, and triggers beam switches.

Adding a simplified codebook model would enable:
- **Beam index** (TX/RX beam pair per link per tick)
- **Beam switch events** (timestamp + old/new beam pair)
- **Per-beam RSRP** (received power per beam direction)
- Beam tracking lag and angular dead zone detection

Approach: define N beam directions per node (e.g., 64-element codebook),
compute array factor gain per direction, pick best pair per link based on
geometry, track indices over time.

## Packet-Level Loss

mesh-sim uses flow-level traffic abstraction (demand_mbps / delivered_mbps).
There are no packets, so true packet loss percentage cannot be computed.

Possible proxies:
- **Undelivered fraction**: `1 - (delivered_mbps / demand_mbps)` per flow
- **Link outage fraction**: fraction of ticks where a link's SINR is below
  the minimum MCS threshold (-6.7 dB)

Adding a packet-level model would require replacing the traffic matrix with
a packet generator and tracking per-packet delivery, which is a fundamental
architecture change.

## Interference Modeling

Currently assumes orthogonal channels between all node pairs (no
inter-node interference). This is reasonable for narrow mmWave beams with
high spatial isolation, but underestimates interference in dense deployments.

Full interference modeling would require:
- Joint scheduling + routing layer
- Per-link interference calculation from all active concurrent transmissions
- SINR = signal / (interference + noise) instead of signal / noise

A simpler alternative: configurable interference margin (e.g., subtract 3 dB
from SINR) as a conservative estimate.

## IMU / Attitude Modeling

Nodes are modeled as dimensionless points with position and velocity.
Physical UAV attitude (roll, pitch, yaw) is not tracked. This matters for
real radios because antenna patterns depend on platform orientation.

Would become relevant if beam codebook model is added, since physical tilt
changes the effective beam direction.

## LOS/NLOS Condition Tracking

Currently `condition_reason` in links.csv reports whether the channel
condition model is building-based (deterministic geometry) or probabilistic
(3GPP/NYU statistical model). This is a per-run property.

Future enhancement: per-link per-tick tracking of which specific building
caused NLOS, or the probability value from the statistical model.
