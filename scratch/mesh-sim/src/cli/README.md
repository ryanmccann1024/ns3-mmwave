@page src_cli src/cli

@brief Command-line parsing and pre-simulation setup for mesh-sim.

This module parses the simulator's command-line flags, decides which seeds to
run, and copies the scenario files into the output folder. `sim.cc` calls it at
startup. You use it every time you run the simulator, and only edit it to add
or change a flag.

## 1\. Usage

Run from the ns3-mmwave repository root. Only `--run-config` is required:

```bash
./ns3 run scratch/mesh-sim/sim -- --run-config=scratch/mesh-sim/inputs/baselines/p0-smoke/run.ini
```

A fuller example:

```bash
./ns3 run scratch/mesh-sim/sim -- \
  --run-config=<path/to/run.ini> \
  --band=sub-6 \
  --seeds=1,2,3 \
  --output-dir=<dir>
```

Flags take the form `--name=value`. `--debug-links`, `--no-viz`, `--rl-mode`
and `--channel-query` also work with no value. A missing or invalid flag prints
`Error: ...` and exits with code 1 before anything runs.

## 2\. Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--run-config=<path>` | required | The scenario's `run.ini` (the file, not its folder). Must exist. |
| `--seeds=<list>` | seed from `run.ini` | Comma-separated seeds, e.g. `1,2,3`. Each runs in its own `seed-<N>/` folder. |
| `--seed=<int>` | seed from `run.ini` | Single-seed override. Ignored if `--seeds` is given. |
| `--run-id=<int>` | `run_id` from `run.ini` | Overrides `run_id`. Negative means not set. |
| `--output-dir=<path>` | `[output] dir`, else timestamped | Where results are written. |
| `--band=<band>` | `[channel] band`, else `mmwave` | Radio band: `mmwave` or `sub-6`. Jammers only apply on `sub-6`. |
| `--positions-override=<path>` | none | JSON file that patches node positions after `nodes.json` loads. Must exist if given. |
| `--no-viz` | off | Skips the six replay CSVs. `inputs/`, `run.log` and each `summary.json` are still written. |
| `--jammer-onset-s=<seconds>` | `-1` (off) | Starts every enabled jammer at this time (see below). |
| `--debug-links` | off | Verbose per-link (and per-jammer) logging. |
| `--rl-mode` | off | Enables the RL bridge: JSON observations and actions on stdin/stdout. |
| `--channel-query` | off | Serves channel queries on stdin/stdout instead of running a simulation ([contract](@ref src_query)). |

**`--jammer-onset-s`:** the value must be finite and in `[0, duration_s)`, and
the scenario must define at least one jammer; otherwise the simulator prints
`Error: ...` and exits 1 before archiving anything. Each enabled jammer's active
interval becomes `[onset, duration_s]`. Disabled jammers stay disabled, and the
band does not change.

**`--channel-query`:** seeds must resolve to exactly one. `--output-dir` has no
effect (it is silently ignored), and no output folder, archive or `run.log` is
written.

## 3\. Precedence

| Setting | Order (first one set wins) |
|---|---|
| Seeds | `--seeds`, then `--seed`, then `seed` in `run.ini` |
| Band | `--band`, then `[channel] band`, then `mmwave` |
| Output folder | `--output-dir`, then `[output] dir`, then `outputs/YYYY-MM/DD/HH-MM-SS/` |

In `--seeds`, empty items are skipped and a non-numeric item is an error.

## 4\. Output

This module writes only the scenario archive: it creates
`<output-dir>/inputs/` and copies every regular file from the `run.ini` folder
into it. Other modules (`sim.cc`, `src/io/`) write the rest:

```
<output-dir>/
  run.log          # resolved config summary
  inputs/          # copy of the scenario folder (run.ini, nodes.json, ...)
  seed-1/
    positions.csv  links.csv  rx-power.csv  mcs.csv  flows.csv  routes.csv  summary.json
  seed-2/
```

The archive holds the files that sat beside `run.ini`. Files referenced from
elsewhere, and some settings, are not recorded; see
@ref src_io_run_record "What a run records".

## 5\. Module layout

| File | Role |
|------|------|
| @ref cli-parser.h "cli-parser.h" | `CliArgs` struct and the public functions (`ParseCommandLine`, `ResolveSeeds`, `ResolveQuerySeed`, `ArchiveScenarioInputs`). |
| @ref cli-parser.cc "cli-parser.cc" | Implementations. The only file in `src/` that includes `ns3/command-line.h`. |
| `CLAUDE.md` | Scope and dependency notes for AI assistants. |
| `README.md` | This page. |

Flags are declared in `cli-parser.h` and parsed in `cli-parser.cc`. `sim.cc`
applies the overrides (including `--output-dir`, `--band`, `--no-viz` and
`--jammer-onset-s`) after the configuration loads.

## 6\. Behavior notes

- **Hard exits:** `ParseCommandLine` and `ResolveSeeds` print to stderr and call
  `std::exit(1)`; they never throw.
- **Files are only checked for existence:** `ConfigLoader` validates the
  contents of `--run-config` and `--positions-override`.
- **The archive copies the whole folder:** every regular file beside `run.ini`
  (not subfolders) is copied, including large ones, and existing files in
  `inputs/` are overwritten.
- **`--run-config` needs a folder in its path:** a bare `run.ini` has an empty
  parent path, so `ArchiveScenarioInputs` throws
  `std::filesystem::filesystem_error`; `sim.cc` catches it and exits 1.
- **`--channel-query` seed check happens later:** `src/query/` calls
  `ResolveQuerySeed` after the config loads, which rejects more than one seed
  with `Error: --channel-query needs exactly one seed`.

Unit tests: `make -C tests/unit/io-cli test` (from `scratch/mesh-sim/`) runs
`ParseCommandLine`, `ResolveSeeds`, `ResolveQuerySeed` and
`ArchiveScenarioInputs` against an ns-3 `CommandLine` stub. The real binary is
covered by `make integration` in `tests/`.

## 7\. Dependencies

- `ns3/command-line.h` (ns-3 core), in `cli-parser.cc` only.
- `src/domain/sim-config.h` (`SimConfig`, for `cfg.seed`).
- `src/util/string-utils.h` (`parseSeedList`).
- C++17 `<filesystem>`.
- Used by `sim.cc` and `src/query/` (`ResolveQuerySeed`).
