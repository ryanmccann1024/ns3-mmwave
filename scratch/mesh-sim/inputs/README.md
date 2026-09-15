# inputs/

Scenario definitions for mesh-sim.  Each baseline scenario lives in its own
directory under `baselines/` and contains the configuration files that drive
a simulation run.

## Directory layout

```
inputs/
  baselines/          <-- validation scenarios (numbered 01-16)
    01-static-los-baseline/
      run.ini          simulation parameters (optional [channel] band)
      nodes.json       node positions and mobility
      buildings.json   (optional) building geometry
    ...
```

`run.ini` may also select the radio band via `[channel] band` (`mmwave` or
`sub-6`); the simulator's `--band` overrides it, and absent both the band
defaults to `mmwave`.

## Scenario families

| Path | Role | Git |
|---|---|---|
| `baselines/` | Small synthetic scenarios for deterministic simulator validation, including the `p0-smoke` and `p0-jammer-smoke` fixtures | Tracked |
| `custom/sherpa/` | Local Spring Lake ARPO mmWave scenarios | Ignored, read-only; ask the project team or data owner for the data |
| `calfex/` | Field-derived CalFEX sub-6 scenario configurations | Tracked |
| `sweeps/` | Parameter-sweep configurations | Tracked |

Sherpa and CalFEX are distinct field workflows, not two spellings of the same
dataset: the Sherpa inputs describe ARPO mmWave trials, the CalFEX inputs
describe sub-6 field scenarios.

Related directories outside `inputs/`:

- `data/` holds local raw and derived field telemetry and is read-only input to
  the validation generators; its contents are git-ignored (root `.gitignore`,
  `scratch/mesh-sim/data/*`) and not committed.
- `outputs/` is disposable and git-ignored — never commit raw run products.
- `tests/fixtures/regression/p0/` holds committed *normalized* regression
  snapshots (compact comparison values only, no raw logs or output trees).

## How to run a scenario

```bash
./build/scratch/mesh-sim/ns3*-sim-* \
  --run-config=scratch/mesh-sim/inputs/baselines/01-static-los-baseline/run.ini
```

Outputs are written to `scratch/mesh-sim/outputs/` in a timestamped directory.

## Design philosophy

The scenarios are ordered by complexity.  Each one changes **exactly one
knob** from the baseline (scenario 01), so you can always diff back to
understand what changed.  See `baselines/README.md` for the full scenario
table and a guide to interpreting the output graphs.
