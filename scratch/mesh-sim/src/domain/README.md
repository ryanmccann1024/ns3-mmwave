@page src_domain src/domain

@brief Plain-struct configuration and result types shared by every simulator layer.

The headers hold no logic and no ns-3 code. `SimConfig` is the root object: `ConfigLoader`
fills it from `run.ini` and the JSON files, `ValidateConfig` checks it, and every
other layer reads it. `LinkResult` carries one link's radio result for one tick.
Units are in each field's `///<` comment (dB, dBm, meters, seconds, MHz, Mbps).

## Module Layout

| File | Role |
|------|------|
| @ref sim-config.h "sim-config.h" | Root `SimConfig`, `RlConfig` (RL controller), `TimingInfo` (wall-clock run times). |
| @ref channel-config.h "channel-config.h" | `ChannelConfig` (frequency, power, gains, models) and `NyuChannelConfig`. |
| @ref mesh-config.h "mesh-config.h" | `TrafficConfig` (flow demand model and topology) and `RoutingConfig`. |
| @ref node-spec.h "node-spec.h" | `NodeSpec`, mobility parameters, `BuildingSpec`, `MaxSpeedForType()`. |
| @ref link-result.h "link-result.h" | `LinkResult`: distance, LOS, path loss, power, SINR, capacity, MCS. |
| @ref probe-spec.h "probe-spec.h" | `ProbeGrid`: receive-only coverage probe points for the channel query. |

## Run

Nothing runs on its own; these are header-only. To confirm they compile with plain
`g++` (no ns-3), run from `scratch/mesh-sim/`:

```bash
make -C tests/unit/config test
```

## Output

Nothing is written to disk. `TimingInfo` and `LinkResult` values are consumed by
`io/` writers, which produce the metrics JSON and viz CSV files.

## Conventions

- **Sub-structs are declared in their own header** and held as members of
  `SimConfig`.
- **Every field has a default.** The loader (`config/config-loader.cc`) passes its
  own fallback values, so the two sets are maintained separately and can drift;
  their parity has not been fully audited.
- **Resolved RL fields.** `RlConfig::control_mode`, `controlled_indices`,
  `num_slots`, `decision_interval_ticks` and `num_ticks` are never read from INI;
  `ApplyRlControl` (`config/rl-control.cc`) assigns them after validation.
- **Loaded but unconsumed.** `ChannelConfig::blockage_enabled` and
  `beamforming_model` are parsed and stored by the loader but have no native
  behavior consumer today.
- **Documentation.** Doxygen `/** */` blocks on types; fields use trailing `///<`
  with units and defaults.
- **Coordinates** are meters in an arbitrary local frame.
- **Strings select models** (for example `"3gpp"`, `"shannon"`). Allowed values
  are checked by `ValidateConfig` in `config/config-validator.cc`, not here, and
  not for every string: `amc_model` has no whitelist, so an unknown value is
  rejected by `SinrToCapacity` only for links at or above `SINR_MIN_DB` during
  the run (see @ref src_eval "eval").
- **No ns-3 includes.** `sim-config.h` includes `src/jammer/jammer-spec.h` for `JammerSpec`.

## Adding a field

A new `SimConfig` field is owned here (struct member with default and `///<`
comment) together with the loader, validator and `run.log` writer; the
update-together row for a `run.ini` or CLI option in @ref Contributing
"Contributing" names the layers to change. For a new value of an existing
selector, see @ref mesh_sim_add_capacity_model "Add a capacity model".

## Dependencies

- C++17 standard library only.
- `sim-config.h` needs `src/jammer/jammer-spec.h`, which needs `node-spec.h`.
