# TODO — Future Possibilities

## RL Enhancements

### Multi-node control
`[rl] controlled_nodes` gives one MaskablePPO
policy a fixed set of mesh nodes with the 2-D `move_2d` profile. Remaining:

- **3-D `move_3d` profile.** `nvec = [7]*M` with `down`/`up` added and hold at
  index 6, contract id `mesh_move_3d_v1`. Rejected today with an explicit
  "reserved and not implemented" error. Owner: team — status: open.
- **Coupled and collision constraints.** Per-slot masks cannot express
  minimum separation, collision avoidance, or any joint constraint between
  controlled nodes. Owner: team — status: open.
- **Transfer and evaluation loader.** Landed. `scripts/rl/policy/compat.py`
  checks a saved model against the live `init` in a fixed order — structural
  contract fields, observation schema, reward schema, then scenario identity —
  and `scripts/rl/evaluate.py` loads and evaluates a bundle only after those
  checks pass. Transfer across scenarios is still never implied by matching
  shapes. Owner: team — status: landed.

### Centralized-control questions (temporary assumptions in effect)
Each item below records the assumption the landed code implements. Confirm or
change it; do not infer the answer from the code.

- **TODO-RL-CONTROL-1 — Waypoint start.** Should an RL-controlled waypoint node start
  at its first waypoint and ignore the rest? Assumed yes: a controlled
  waypoint node is placed at `waypoints.front()` and RL then owns its motion.
  Owner: team — status: open.
- **TODO-RL-CONTROL-2 — `all` eligibility.** Should `all` exclude any node class (for
  example a traffic gateway)? Assumed no exclusions: `all` is every entry of
  `nodes.json`. Owner: team — status: open.
- **TODO-RL-CONTROL-3 — Per-slot speed.** Is `step_size_m / tick_s` capped by node
  type the right per-slot speed, or is a `speed_mps` key wanted? Assumed the
  former, which keeps current movement for existing configs.
  Owner: team — status: open.
- **TODO-RL-CONTROL-4 — 3-D ground types.** In a 3-D profile, should vehicles and
  pedestrians have down/up masked off? Deferred with 3-D.
  Owner: team — status: open.
- **TODO-RL-CONTROL-5 — Observing uncontrolled nodes.** Should uncontrolled-node
  positions be observable by the agent? Currently excluded from
  `local_links_v1`; tracked with the other candidate features in TODO-P2-4.
  Owner: team — status: open.
- **TODO-TIME-1 — Tick-count unification.** Legacy and non-RL runs keep the
  truncating `duration_s / tick_s` count; centralized runs use a robust count
  (snap to the nearest integer within 1e-6, else truncate). Unifying them
  would change existing scenarios' tick counts, so it needs a separately
  approved regression-fixture review. Owner: team — status: open.

### P2 observation/reward/telemetry follow-ups

- **TODO-P2-1 — Jammer 0 dB SINR clamp.** `src/eval/link-evaluator.cc` (the `jamWatt != 0` branch of `EvaluateLink`, ~lines 199-206)
  clamps SINR to at least 0 dB whenever a jammer contributes power, so a jammed
  link can never fall below the connectivity threshold and a weak link can even
  become *connected* when a jammer turns on. Jamming enters SINR only when
  `band = sub-6`. No jamming-aware claim, reward experiment, or jammer feature
  should be made until this is decided; removing the clamp needs its own
  regression review. Owner: team — status: open.
- **TODO-P2-2 — RL reward ignores `warmup_s`.** `MetricsWriter::AccumulateTick`
  skips ticks before `warmup_s`, but `RlBridge::AccumulateTick` accumulates
  every tick, so RL rewards and facts windows include warmup ticks while
  `summary.json` does not. `init.warmup_s` is exported as metadata only.
  Aligning them would change existing RL rewards. Owner: team — status: open.
- **TODO-P2-3 — Peer padding across node counts.** `local_links_v1` sizes its
  peer block from the live `num_mesh_nodes`, so an observation from one N does
  not fit another. The `present` bits are already reserved for a padded preset
  keyed on a `max_mesh_nodes` bound; until then `check_schema` rejects a
  different N rather than implying transfer. Owner: team — status: open.
- **TODO-P2-4 — Candidate observation features.** The facts already carry every
  node's velocity and position, including uncontrolled nodes, and jammer
  interference could be added; none of them is in `local_links_v1`. Each needs
  a leakage review (what a real node could actually know) before becoming a
  preset feature, and any jammer feature also depends on TODO-P2-1.
  Owner: team — status: open.

### Continuous Desired-Position Actions with SB3
Continuous control needs a separate action profile, protocol version, and
verified Python/C++ implementation before it can be enabled.

### Richer Reward Shaping
Currently supports `throughput` (sum delivered_mbps) and `all_links_los`
(`mean_sinr` is a deprecated alias for it). Future: weighted combinations of
throughput, fairness (min-link capacity), latency, coverage area, or energy
cost.

### 3D Movement for Drones
Current control moves only in x/y. Future 3D support needs
per-node-type constraints so aerial nodes (drones) control altitude while
ground nodes (vehicles, pedestrians) stay 2-D constrained, and a verified 3-D
continuous action space.

### Larger Discrete Action Spaces
Add 4-direction (up/down in y-axis) and 8-direction (diagonals) as
additional versioned action profiles.

### TODO-RL-SEEDS-1 — Multi-seed training policy
Training currently uses one fixed seed (`m-ppo --seed`, else `[scenario] seed`) reused by
every episode. Deciding whether episodes should vary the seed, and how the
model/manifest should record that, is deferred.
That one integer also sets both the PPO initialization and the training scenario,
so the across-training-runs interval in `scripts.rl.compare` conflates the two
sources of randomness and cannot attribute run-to-run spread to either.
Separately, `--eval-episodes > 1` appears to replay the same evaluation seed
rather than sampling new ones — unverified.
Owner: team — status: open.

### TODO-RL-RESUME-1 — Resume from checkpoint
Training always starts a fresh model. `checkpoints/` and `best_model.zip` are
provenance and evaluation inputs only; there is no `--resume`. Adding one needs
`MaskablePPO.load` plus `learn(reset_num_timesteps=False)` handling and a
decision about manifest continuity (one manifest extended across runs, or a new
manifest that links to its parent). Owner: team — status: open.

### TODO-RL-LEARNING-1 — Learning signal beyond the diagnostic smoke
`inputs/baselines/building-bypass-smoke/` is a diagnostic fixture: it makes a
directional reward difference visible on a tiny run, and it is not evidence that
training converges or that a policy is useful. A real learning-signal study —
scenario set, seeds, budgets, baselines, and success criteria — belongs to a
separately approved campaign phase. Owner: team — status: open.

### TODO-RL-BASELINE-1 — Greedy baseline
`scripts.rl.evaluate` offers `hold` and seeded `random_valid`, which bracket "do
nothing" and "valid noise" but not "a sensible hand-written controller". A greedy
baseline cannot be added as just another policy: a policy sees only `obs`, whose
layout differs per observation preset (`raw_links_v1` is raw, `local_links_v1` is
normalized), so it needs either a facts-access contract of its own or a decoder
per preset, plus its own validation, because a greedy baseline becomes the de
facto benchmark everything else is judged against. `scripts.rl.compare` accepts
any baseline name present in a manifest, so adding one later needs no change to
the comparison harness. Owner: team — status: open.

### TODO-RL-EVAL-1 — Simulator-summary metrics in policy comparisons
Every statistic in `scripts.rl.compare` comes from the RL telemetry window, and
each output states `metric_source` accordingly. A run's `summary.json` carries
richer per-seed metrics but excludes warmup ticks while the RL window does not,
so the two cannot be mixed in one table whenever `warmup_s > 0`. Using
`summary.json` metrics requires resolving that warmup mismatch first (see the
RL-reward warmup entry above). Owner: team — status: open.

### TODO-RL-EVAL-2 — Merging evaluations of one model across output directories
An evaluation is compared as a single `eval_manifest.json`, so baselines are
re-run inside every evaluation and a per-seed cluster array (each seed in its own
output directory) cannot be assembled into one comparison. A merge needs an
explicit rule set, sketched as: a `completed` record supersedes a `failed` one
for the same seed, and two `completed` records for one seed must agree on
`actions_sha256` or the merge is refused. Owner: team — status: open.

### TODO-RL-OPS-1 — Live-cluster validation of the scheduler adapter
`scripts/rl/ops/cluster.py` and its `squeue`/`sacct`/`sbatch`/`scancel` parsers
are exercised against a fake scheduler only, so their state names, array-element
id forms, and accepted flags are unproven on a real site. Whether the site
exposes a meaningful start estimate or a queue position at all is likewise
unknown; the local benchmark supports no completion ETA, and a laptop
measurement is never a cluster estimate. Record each live finding here rather
than inferring site behavior from the code. Verify `sacct --array` explicitly;
the fake scheduler cannot reject unsupported flags. Owner: team — status: open.

### TODO-RL-OPS-2 — Oversized arrays and blocked-directory archiving
A plan with more tasks than the configured `max_array_size` is refused rather
than chunked across several arrays. A task blocked by a populated step directory
is reported with `move or delete <dir> to retry` and is never moved, renamed, or
deleted by the tooling; an archive helper that does it safely is not
implemented. Submitting a compare-only SLURM job after task submission succeeds
but compare submission is refused is also deferred; `resume` with no pending
tasks does not queue one. Owner: team — status: open.

### TODO-RL-TUNE-1 — Training budget search
The PPO constructor, CLI, manifests and tuner now share `agents/config.py` for
learning rate, batch size, GAE lambda, clipping, epochs, target KL and entropy
settings. Architecture is explicit in matrices. Study resume is implemented by
the persisted tuning owner; training budget remains fixed per study.
