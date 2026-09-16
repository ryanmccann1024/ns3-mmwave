# setup/

## Scope
The only layer that creates ns-3 objects -- nodes, mobility models, buildings, and propagation models.
No EPC, RRC, MAC, or protocol stack -- only the components needed for direct propagation model calls.

## Files
- **topology-builder.h/cc** -- Installs per-node mobility models (`ConstantPositionMobilityModel`, `ConstantVelocityMobilityModel`, `RandomWalk2dMobilityModel`), creates `Building` objects, configures `PropagationLossModel` and `ChannelConditionModel`. Returns handles needed by `LinkEvaluator`.

## Dependencies
- Depends on: `domain/`, `config/rl-control` (`ControlledStartPosition`), ns-3 modules (mobility, propagation, buildings, mmwave)
- Depended on by: `sim.cc`

## Rules
- In centralized RL mode, nodes in `cfg.rl.controlled_indices` get a
  `ConstantVelocityMobilityModel` at their start position instead of their
  configured mobility model.
- Buildings must be created before `BuildingsHelper::Install()`.
- `MobilityBuildingInfo::IsIndoor()` lazily re-evaluates when position changes, so explicit consistency calls are not needed after mobility advances.
