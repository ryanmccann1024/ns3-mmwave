@page src_setup src/setup

@brief Creates the ns-3 nodes, mobility models, buildings, and propagation models for a run.

`TopologyBuilder` is the only place in mesh-sim that creates ns-3 objects. It
reads a validated `SimConfig`, builds one node per mesh node and per jammer,
and hands the mobility models and the propagation and channel-condition
models to the rest of the simulator through getters. `sim.cc` builds one per
seed.

## 1\. Module layout

| File | Role |
|------|------|
| @ref topology-builder.h "topology-builder.h" | `TopologyBuilder` class; header tables map config values to ns-3 classes. |
| @ref topology-builder.cc "topology-builder.cc" | Mobility install, building creation, propagation model setup. |
| `CLAUDE.md` | Scope and invariants for AI assistants. |

## 2\. Setup

This code needs a built ns-3 tree (mobility, propagation, buildings, mmwave
modules). It cannot be compiled standalone and has no unit-test suite. The user
handles builds; do not run `./ns3 build` from here.

## 3\. Run

There is no executable here. `sim.cc` uses the class in this order:

```cpp
TopologyBuilder tb(cfg);   // cfg must outlive tb
tb.Build();                // once, before any getter
auto mobility = tb.GetMobilityModels();       // cfg.nodes order
auto jammers  = tb.GetJammerMobilityModels(); // cfg.jammers order
auto loss     = tb.GetPropagationModel();
auto cond     = tb.GetConditionModel();
```

The channel query (`src/query/`) also calls `tb.SetProbes(grid)` before
`Build()` and reads `tb.GetProbeMobilityModels()`. Probe nodes are appended
after the jammers (mesh and jammer node IDs are unchanged), get a directly
created `ConstantPositionMobilityModel`, and are included in
`BuildingsHelper::Install`. They are created without `MobilityHelper`, whose
constructor allocates random position allocators and would consume automatic
RNG stream indices before the propagation model is created. Coverage-enabled live RL runs also request these probes.

## 4\. Output

| Step | Where |
|------|-------|
| `Build()` | In-memory ns-3 objects only; no files written. |
| Getters | Return ns-3 smart pointers owned jointly with the builder. |

## 5\. Conventions

- Behavior depends only on the `SimConfig` passed in.
- Unknown mobility or propagation scenario strings throw `std::runtime_error`.
- **Scenario names differ between validator and builder.**
  - `ValidateConfig` accepts `UMi`, `UMa`, `RMa`, `InH` and `InF` for
    `[channel] scenario`, without looking at `channel_model`.
  - The NYU branch of `ConfigurePropagationModel` accepts exactly those five.
  - The 3GPP branch rejects `InF`, and also recognizes `InH-Mixed` and
    `InH-Open`, which the validator rejects.
  - So `channel_model = 3gpp` with `scenario = InF` passes validation and then
    fails in `Build()`.
- **When `Build()` fails.**
  - `sim.cc` calls `topo.Build()` inside the per-seed loop, after the inputs are
    archived and `run.log` has been attempted. The call is not inside a
    `try`/`catch`, so there is no handled `return 1` path for it.
  - The failing seed has not opened its CSV writer or written `summary.json`,
    so it adds nothing to its `seed-<N>/` folder. Earlier seeds, or a reused
    output directory, may already hold results, and `run.log` may have failed
    to open silently.
  - Expect possibly partial output; no exit code or message is documented for
    this case. What a run preserves is listed in
    @ref src_io_run_record "What a run records".
- Comments use Doxygen `/** */` blocks; full docs live in the header.

## 6\. Dependencies

- `src/domain/` (`SimConfig`, `NodeSpec`, `JammerSpec`, `BuildingSpec`).
- `src/config/rl-control.h` for `ControlledStartPosition`.
- `src/domain/probe-spec.h` (`ProbeGrid`) for optional query probes.
- ns-3 modules: core, mobility, propagation, buildings, and the NYU propagation models from ns3-mmwave.
