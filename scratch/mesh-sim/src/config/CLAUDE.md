# config/

## Scope
Loads `run.ini` + referenced `nodes.json` / `buildings.json` into a `SimConfig`.
No ns-3 headers -- can be compiled and tested independently of the ns-3 build.

## Files
- **config-loader.h/cc** -- `ConfigLoader::Load()` parses INI sections and JSON files into `SimConfig`. Also parses mesh-specific sections (`[traffic]`, `[routing]`).
- **rl-control.h/cc** -- `ResolveRlControl()` turns the `[rl]` selectors into controlled-node slots, decision cadence, and tick count; shared by the validator and `sim.cc`.
- **config-validator.h/cc** -- `ValidateConfig()` checks a loaded `SimConfig` for invalid or inconsistent values. Returns all errors at once so the user can fix them in one pass.

## Dependencies
- Depends on: `domain/`, `util/`, `third_party/json.hpp`
- Depended on by: `sim.cc`
