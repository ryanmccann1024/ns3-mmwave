@page src_io src/io

@brief Writes the simulator's output files: per-tick CSVs, a per-seed JSON summary, a run log, and stderr progress.

This module writes the simulator's result files. `sim.cc` creates one
`VizWriter` and one `MetricsWriter` per seed, calls `WriteRunLog` once per
batch, and calls `ProgressLogger::Tick` every tick. The **ns3-mmwave-viz**
visualizer and the Python plotting and validation tools read the CSVs. Unit
tests for `MetricsWriter`, `WriteRunLog` and `VizWriter` run with
`make -C tests/unit/io-cli test` from `scratch/mesh-sim/`.

# 1\. Output files {#src_io_output}

```
<output_dir>/
  run.log          # WriteRunLog, once before the seed loop
  inputs/          # scenario archive (written by src/cli)
  seed-N/
    positions.csv  links.csv  rx-power.csv  mcs.csv  flows.csv  routes.csv
    summary.json
```

| File | Folder | Written | Writer |
|------|--------|---------|--------|
| `run.log` | `<output_dir>/` (batch root, not per seed) | Once, before the seed loop | `WriteRunLog` |
| `positions.csv`, `links.csv`, `rx-power.csv`, `mcs.csv`, `flows.csv`, `routes.csv` | `<output_dir>/seed-N/` | `VizWriter::Open` creates them; `VizWriter::WriteTick` appends rows every `viz_tick_ms` ms of sim time. Skipped with `--no-viz`. | `VizWriter` |
| `summary.json` | `<output_dir>/seed-N/` | Once, after the step loop | `MetricsWriter::Write` |
| Progress line | stderr | Every tick: sim time, wall time and ETA | `ProgressLogger::Tick` |

## CSV columns

| File | Columns |
|------|---------|
| `positions.csv` | `time_s,node_id,x,y,z,node_type,active` after a `# key=value` metadata block (`scenario`, `frequency`, `txPower`, `numNodes`, `simDuration`, `tickMs`, `dimensions`, `rainRate`, `channelModel`, `flowTopology`, `trafficModel`) |
| `links.csv` | `time_s,node_a,node_b,dist_m,sinr_db,condition,condition_reason,capacity_mbps,delivered_mbps,hop_count` |
| `rx-power.csv` | `time_s,node_a,node_b,rx_power_dbm` |
| `mcs.csv` | `time_s,node_a,node_b,mcs_index,spectral_eff` |
| `flows.csv` | `time_s,src,dst,demand_mbps,delivered_mbps,latency_ms,hop_count,routable` |
| `routes.csv` | `time_s,src,dst,path,bottleneck_mbps,hop_count,routable` |

- Node ids are zero-based indices.
- `links.csv`, `rx-power.csv` and `mcs.csv` have one row per unordered pair
  (`node_a < node_b`).
- `path` is semicolon-separated, for example `0;2;3`.
- `node_type` in `positions.csv` is the physical type (`drone`, `vehicle` or
  `pedestrian`), not the role label `peer`.
- In mission recovery scenes, `active` becomes 0 at `failure_at_s`. The failed
  node's stationary coordinates stay in the file for replay. Link and traffic
  rows keep their original endpoint indices and offered demand.

## summary.json keys

`scenario`, `seed`, `duration_s`, `warmup_s`, optional `wall_clock_start`,
`wall_clock_end`, `wall_elapsed_s`, then `per_node`, `per_flow` (keys like
`A->B`) and `network`. Field details are in `metrics-writer.h`.

# 2\. Sampling and warmup {#src_io_timing}

| Output | Ticks covered | Warmup period |
|--------|---------------|---------------|
| CSVs | A snapshot each time `time_s` reaches the next multiple of `viz_tick_ms`; the first is at `t = 0`. | Included; nothing on the CSV path is filtered by `warmup_s`. |
| `summary.json` | Every tick (`MetricsWriter::AccumulateTick` is called each tick). | Excluded; observations with `time_s < warmup_s` are skipped. |

- `VizWriter::WriteTick` is called every tick, so the CSVs hold a subset of
  ticks when `viz_tick_ms` exceeds the tick length.
- Every `summary.json` average covers only post-warmup ticks and is computed
  from the per-tick observations, not from the sampled CSV rows.
- `--no-viz` disables CSV writing only (`VizWriter` is never opened). The
  archived inputs, `run.log` and `summary.json` are still written.

# 3\. What a run records {#src_io_run_record}

<!-- Canonical statement of what a completed run preserves and what it does not.
     Other pages link here instead of repeating it. -->

**Written by a completed run:**

- `inputs/` (the scenario archive) and `run.log` at the batch root, once before
  the seed loop.
- `summary.json` per seed.
- The six CSVs in the @ref src_io_output "Output" table per seed, only when
  visualization writing is enabled. `links.csv` and `mcs.csv` are two of those
  six; `--no-viz` disables all of them.

A failure after archiving (for example an uncaught exception from
`TopologyBuilder::Build` or from the evaluation loop) can leave the archive,
and `run.log` if it opened, beside incomplete seed folders. See
@ref src_io_failures "Failure behavior".

**Not in `run.log`:**

- The "Resolved config" block omits, among other values, the AMC model
  (`amc_model`), noise figure, array gains, `condition_model`, `viz_tick_ms`
  and jammer intervals (including the effect of `--jammer-onset-s`).
- The "CLI overrides" block does not list `--no-viz` or `--jammer-onset-s`.
  `output.viz_enabled` in the resolved block reflects `--no-viz` indirectly.
- Band, seeds, run ID and the `--positions-override` path are logged.

**Not in the archive:**

- `ArchiveScenarioInputs` copies the regular files beside `run.ini`, without
  recursion. Files in subdirectories and files referenced by path from outside
  that directory are not copied. This includes an override file outside that
  directory: its path is logged, its bytes are not.
- The value of any INI key you omitted. That value came from the source default
  at the time of the run. An `amc_model` you wrote explicitly survives in the
  copied `run.ini`; an omitted one does not.

**To reproduce a run, keep separately:**

- The exact command line.
- The source identity (commit and any local changes).
- The build and environment identity.
- The bytes of every external input or override file. A logged path alone is
  not enough.

# 4\. Failure behavior {#src_io_failures}

Each writer fails differently; `sim.cc` does not normalize them.

| Failure | Result |
|---------|--------|
| Input archive (`ArchiveScenarioInputs`) fails | Caught in `main`, which returns 1. |
| Per-seed directory creation fails | Caught in `main`, which returns 1. |
| `create_directories` in `WriteRunLog` fails | Throws; not caught in `main`. |
| `run.log` cannot be opened (directory exists) | `WriteRunLog` returns silently. |
| `VizWriter::Open` fails | Throws `std::runtime_error`; not caught in `main`. |
| `summary.json` cannot be opened | `MetricsWriter::Write` prints `[MetricsWriter] ERROR` to stderr and returns. This alone does not make `main` return nonzero. |

# 5\. Module layout

| File | Role |
|------|------|
| `viz-writer.h` | `VizWriter` declaration; documents the six CSV schemas. |
| `viz-writer.cc` | Opens the CSVs, rate-limits writes to `viz_tick_ms`, aggregates per-edge flow load for `links.csv`. |
| `metrics-writer.h` | `MetricsWriter` declaration; documents the `summary.json` schema. |
| `metrics-writer.cc` | `AccumulateTick` (post-warmup running sums) and `Write` (time-averaged JSON). |
| `progress-logger.h` | Header-only `ProgressLogger`: sim time, wall time and ETA on stderr. |
| `run-logger.h` | Header-only `WriteRunLog`: seeds, CLI overrides and resolved config. |

# 6\. Behavior notes

- **Two-phase `MetricsWriter`:** `AccumulateTick` runs every tick; `Write` runs
  once. Ticks before `warmup_s` are skipped.
- **SINR sentinel:** links with `sinr_db <= -900` (the -999.0 sentinel) are
  excluded from SINR statistics.
- **Connectivity:** `network.connectivity` uses `LinkTable::IsConnected` with
  its default -6.7 dB threshold.
- **Header-only:** `ProgressLogger` and `WriteRunLog` have no `.cc` file.
- **Comments:** Doxygen `/** ... */` blocks with `@fn`, `@brief`, `@param`,
  `@return`.

# 7\. Dependencies

| Dependency | Reason |
|------------|--------|
| `src/domain/`, `src/eval/`, `src/routing/` | `SimConfig`, `LinkTable`, `MCS_TABLE`, `FlowResult`. |
| `src/cli/cli-parser.h`, `src/util/string-utils.h` | `run-logger.h` reads `CliArgs`; `toIso8601`. |
| `ns3/mobility-model.h` | `VizWriter` reads node positions. |
| `third_party/json.hpp` | `MetricsWriter::Write` serializes JSON. |
