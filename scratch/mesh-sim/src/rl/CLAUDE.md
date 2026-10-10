# rl/

## Scope
C++ side of centralized 2D `MultiDiscrete([5]*M)` control, including one-slot
runs. Owns JSON IPC, masks, speed caps, per-tick clamping, action revalidation,
and post-warmup reward means. Keep the Python protocol, contract docs, and
fake/real simulator tests consistent with message or reward changes.

## Files
- **rl-bridge.h/cc** -- `RlBridge` class with `Step()` (IPC) and `ApplyAction()` (physics).
- **reward-window.h** -- Counts elapsed/scored ticks and averages post-warmup rewards.
- **README.md** -- Mode/message/mask/action contract shared with the Python env.
- **rl-agent.h** -- Legacy placeholder (no-op). Superseded by rl-bridge.

## Dependencies
- Depends on: `domain/`, `eval/link-table`, `routing/mesh-router`, ns-3 mobility
- Depended on by: `sim.cc`
