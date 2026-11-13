# rl/

## Scope
C++ side of centralized 2D `MultiDiscrete([5]*M)` control, including one-slot
runs. Owns JSON IPC, masks, speed caps, per-tick clamping, action revalidation,
and post-warmup reward means. Keep the Python protocol, contract docs, and
fake/real simulator tests consistent with message or reward changes.

The bridge exports raw node/link facts and scored-window sums; Python owns
observation normalization, reward composition, and schema metadata. Keep
component rules with their definitions and artifact bookkeeping out of the
process lifecycle.

## Files
- **rl-bridge.h/cc** -- `RlBridge` state, `Step()` (IPC), and decision-window facts.
- **rl-motion.cc** -- `RlBridge` masks, velocity clamping, and `ApplyAction()`.
- **joint-motion.h** -- Pure geometry for building intersection and peer separation.
- **reward-window.h** -- Counts elapsed/scored ticks and averages post-warmup rewards.
- **README.md** -- Message/mask/action contract shared with the Python env. The
  other pages here: `policy-inputs.md` (presets, rewards, telemetry),
  `decision-records.md`, and the `policy-*-tests.md` test maps.
- **rl-agent.h** -- Unused no-op placeholder; only a unit-test support header includes it.

## Dependencies
- Depends on: `domain/`, `eval/link-table`, `routing/mesh-router`, `third_party/json.hpp`, ns-3 mobility
- Depended on by: `sim.cc`
