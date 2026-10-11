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
- **rl-bridge.h/cc** -- `RlBridge` class with `Step()` (IPC) and `ApplyAction()` (physics).
- **reward-window.h** -- Counts elapsed/scored ticks and averages post-warmup rewards.
- **README.md** -- Mode/message/mask/action contract shared with the Python env.
- **rl-agent.h** -- Legacy placeholder (no-op). Superseded by rl-bridge.

## Dependencies
- Depends on: `domain/`, `eval/link-table`, `routing/mesh-router`, `third_party/json.hpp`, ns-3 mobility
- Depended on by: `sim.cc`
