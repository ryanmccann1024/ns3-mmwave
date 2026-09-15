@mainpage Overview

Lightweight time-stepped mmWave / sub-6 mesh simulator built on ns3-mmwave.

The sim loads a scenario (@c run.ini + @c nodes.json), steps through time evaluating per-link SINR / capacity / MCS
against an ns-3 propagation model, routes traffic, and writes metrics. It also
supports an optional reinforcement-learning bridge and an optional jammer /
interference model.

@section build Build

All commands run from the **ns3-mmwave repo root** (two levels above this directory).

```bash
./ns3 clean
./ns3 configure --build-profile=debug -- -DCMAKE_OSX_ARCHITECTURES=arm64
./ns3 build
```

If @c "./ns3 clean" doesn't clear the cache fully, remove it manually first:

```bash
rm -rf cmake-cache build
```

## Python environment

The simulator itself needs no Python. The RL, sweep, validation, and plotting
scripts do. One command from `scratch/mesh-sim/` creates `.venv` and installs
`requirements.txt`:

```bash
python3 scripts/rl/bootstrap_venv.py
.venv/bin/python -m pytest scripts/rl/tests -q
```

On Windows the interpreter is `.venv\Scripts\python.exe`. `requirements.txt`
pins the direct dependencies at the versions tested on the implementer's
platform; it is not a universal lock file.

Use `python3 scripts/rl/bootstrap_venv.py --check` to verify imports and exact
installed versions without installing anything. CMake and a C++ compiler are
separate ns-3 build prerequisites; this helper does not install them.

@section run Run

Simulator commands below run from the **ns3-mmwave repo root**. Python
pipeline, validation, jammer-generation, and sweep commands run from
**scratch/mesh-sim**.

@subsection run_single Single scenario

```bash
./ns3 run scratch/mesh-sim/sim -- \
  --run-config=scratch/mesh-sim/inputs/calfex/06-25/1227-1413/run.ini \
  --band=sub-6 \
  --seeds=1,2,5,6,8,10 \
  --output-dir=scratch/mesh-sim/outputs/calfex/06-25/1227-1413
```

Key flags:

| Flag | Meaning |
|------|---------|
| @c --run-config | Path to the scenario's @c run.ini (the file, not the dir). |
| @c --band | @c sub-6 or @c mmwave. Interference/jammers only apply on @c sub-6. |
| @c --seeds | Comma-separated seeds; each gets its own @c seed-<N>/ output subdir. |
| @c --output-dir | Where results are written. |
| @c --rl-mode | Enable the RL bridge. |
| @c --debug-links | Verbose per-link (and per-jammer) log output. |

Output lands under @c --output-dir: a @c run.log (resolved config summary), the
archived input files, and @c seed-<N>/ metric folders. Always check @c run.log 's
"Resolved config" block shows the values you expect (frequency, duration,
bandwidth) before trusting a run.

`--band` is optional; omit it to let the scenario's `run.ini` decide.

@subsection run_pipeline Generating a scenario from field data

Scenario generation is ran from **scratch/mesh-sim** directory

```bash
# 1. plot raw per-node data into per-day traces
python -m scripts.arpo_data.cli plot --nodes --day 2026-06-25

# 2. slice one scenario window out of the day (UTC HH.MM)
python -m scripts.arpo_data.cli split-scenario \
  -i data/arpo_extracted/_plots/per_day/2026-06-25 --start 12.27 --end 14.13

# 3. build run.ini + nodes.json for that window
python -m scripts.validation.build_config_files \
  -i data/arpo_extracted/_plots/per_day/2026-06-25/scenarios \
  --day 1227-1413 --csv-dir data/arpo_extracted/csv \
  --band sub-6 --mode node --name jeddoc --tx-gain 1 --rx-gain 1

# 4. fill node trajectories from the sliced GPS trace
python -m scripts.validation.build_waypoints node \
  -i inputs/calfex/1227-1413 \
  -f data/arpo_extracted/_plots/per_day/2026-06-25/scenarios/1227-1413/gps_all_nodes_trace.csv \
  --all-nodes --time-mode raw
```

@subsection run_validate Validating against field data

```bash
python -m scripts.validation.validate_days \
  --day 1227-1413 \
  --field-root data/arpo_extracted/_plots/per_day/2026-06-25/scenarios \
  -t 6360
```

@subsection run_jammer Jammer / interference model (optional)

Run a scenario with field-logged electronic-warfare (jamming) events. See
@ref src/jammer for the full workflow; in brief:

```bash
python -m scripts.validation.make_jammers \
  --trials data/trials2.csv \
  --trace data/arpo_extracted/_plots/per_day/2026-06-24/scenarios/1602-1605/gps_all_nodes_trace.csv \
  --trial directional_stationary_mss_20_mss --beamwidth 60 \
  -o inputs/calfex/1602-1605/jammers.json \
  --run-ini inputs/calfex/1602-1605/run.ini

./ns3 run scratch/mesh-sim/sim -- \
  --run-config=scratch/mesh-sim/inputs/calfex/1602-1605/run.ini \
  --band=sub-6 --seeds=1,2,5,6,8,10 \
  --output-dir=scratch/mesh-sim/outputs/calfex/1602-1605-jammed
```

@subsection run_sweep Sweep

```bash
python -m scripts.sweep.cli --config inputs/custom/sherpa/1.1/sweep.ini
```

## Band selection

`[channel] band` accepts `mmwave` or `sub-6`. Resolution order:

1. `--band=<value>` on the simulator command line,
2. `[channel] band` in `run.ini`,
3. the legacy default `mmwave` when neither is set.

`run.log` records the resolved `band` and a `band_source` of `cli`, `run.ini`,
or `default`. `band` is a categorical switch over the interference path, not a
value derived from `frequency_ghz`: `sub-6` is the only mode in which
configured jammers contribute interference.

## RL reward types

`[rl] reward_type` accepts:

- `throughput` — sum of `delivered_mbps` across flows (default);
- `all_links_los` — `+1` when every peer link of the controlled node is LOS,
  `-1` otherwise.

`mean_sinr` is a deprecated alias for `all_links_los`. It still runs, prints one
warning on stderr, and is recorded in `run.log` as `rl.reward_alias`.
`[rl] z_min`/`z_max` are validated like the x and y bounds (`min < max`).

### MaskablePPO smoke run

Run from `scratch/mesh-sim/`, with global options before the `m-ppo`
subcommand:

```bash
.venv/bin/python -m scripts.rl.train \
  --sim-binary <BIN> \
  --run-config inputs/baselines/p0-smoke/run.ini \
  --output-dir outputs/p0-verification/rl \
  m-ppo --total-timesteps 16 --n-steps 16 --seed 1
```

`--band sub-6` may be added before `m-ppo`. Omitting `--seed` falls back to
`[scenario] seed` in the `run.ini`; either way every episode reuses that one
seed (a multi-seed training policy is a later TODO). Training refuses to start
if the output directory already contains `train_manifest.json` or
`maskable_ppo_mesh.zip`.

### Band in sweeps and validation batches

The generic sweep matrix already covers `band` — no band-specific syntax:

```ini
[sweep.override]
channel.band = sub-6

[sweep]
channel.band = mmwave, sub-6
```

```bash
python -m scripts.sweep.cli --config <sweep.ini>
python -m scripts.validation.run_batch ... [--band sub-6]
```

## Where output lands

| Invocation | Location and contents |
|---|---|
| Direct run | `<output-dir>/run.log`, `<output-dir>/inputs/` (archived scenario files), `<output-dir>/seed-N/{positions,links,rx-power,mcs,flows,routes}.csv` + `summary.json` |
| Sweep point / validation scenario | Same layout, plus `console.log` (launcher-captured stdout/stderr; absent for direct runs) |
| RL training | `<output-dir>/train_manifest.json`, `<output-dir>/maskable_ppo_mesh.zip`, and one `episode-NNNN/` per episode containing `run.log`, `inputs/`, `sim_stderr.log`, `rl_episode.json`, and `seed-<seed>/...` |

With no `[output] dir`, the simulator auto-generates
`outputs/YYYY-MM/DD/HH-MM-SS/`.

## Verify

From `scratch/mesh-sim/tests/`:

```bash
make test                                   # standalone unit tests
MESH_SIM_BIN=<BIN> make integration         # 8 real-binary CLI contracts
```

`make test` stops at the first failing suite. To inspect every suite despite a
failure, run `make -C unit/config test`, `make -C unit/eval test`,
`make -C unit/routing test`, and `make -C unit/traffic test` separately.

For a quick check without cloud reference data, run two tiny synthetic
simulations and check output contracts and same-seed repeatability:

```bash
python3 -m scripts.validation.smoke_check \
  --sim-binary <BIN> --out outputs/smoke-check/<new-name>
```

GitHub Actions runs Python contracts, builds mesh-sim, and runs CLI/synthetic
smoke checks on Linux and macOS for PRs into `arpo-main`. This is not a training
or cross-platform bit-identical-results claim.

The historical regression suite requires the approved cloud baseline bundle.
Ask the project team for it and unpack its reference JSON files under
`tests/fixtures/regression/p0/`; snapshots and gzip archives are not tracked.
The small tracked manifest retains the original hashes and scenario provenance:

```bash
python3 -m scripts.validation.regression_check verify-suite \
  --sim-binary <BIN> \
  --manifest tests/fixtures/regression/p0/manifest.json \
  --out outputs/p0-regression/<name>
```

See [`scripts/validation/README.md`](scripts/validation/README.md) for the
suite's cases, skip behavior, and exit codes.

@section docs Accessing the documentation

This documentation is generated by **Doxygen** into a static HTML site under
@c scratch/mesh-sim/docs/html/. It is a set of local files — there is no server
to start; you open the entry page directly in a browser.

@subsection docs_build Generating the site

From @c scratch/mesh-sim/ (where the @c Doxyfile lives):

```bash
cd scratch/mesh-sim
doxygen Doxyfile
```

This (re)builds @c docs/html/. Re-run it after changing source comments or these
README pages to regenerate. If @c doxygen isn't installed:

```bash
sudo apt install doxygen graphviz     # Linux (graphviz enables the diagrams)
brew install doxygen graphviz         # macOS
```

@subsection docs_open Opening the site

Open the generated entry page in any browser — it's a @c file:// URL, no server
needed:

```bash
# Linux
xdg-open scratch/mesh-sim/docs/html/index.html
# macOS
open scratch/mesh-sim/docs/html/index.html
# Windows
start scratch/mesh-sim/docs/html/index.html
```

Or paste the absolute path into the browser's address bar, e.g.
@c <tt>file:///home/[USER]/ns3-mmwave/scratch/mesh-sim/docs/html/index.html</tt>
(replace @c USER and the repo path with yours). This @c index.html is this
Overview page; use the navigation tree / search at the top to reach the module
pages and the per-file API docs.

@section about About

This sim is being worked on by the University of Massachusetts's ACNL.
