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

`reward_type` is the reward the simulator computes. In centralized mode Python
can instead compose the reward from named components — see
[Selecting observations, rewards, and telemetry](#selecting-observations-rewards-and-telemetry).

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

### Centralized multi-node control

Setting `[rl] controlled_nodes` switches the bridge from the legacy
single-node mode to centralized mode, where one MaskablePPO policy moves a
fixed set of mesh nodes. The keys below apply only when `[rl] enabled = true`;
all other `[rl]` keys keep their existing meaning.

| Key | Type / unit | Default | Mode |
|---|---|---|---|
| `controlled_nodes` | `all` or comma-separated node ids | absent (legacy mode) | centralized selector |
| `max_controlled_nodes` | int, slot count `M` | `0` (auto-size to the resolved count), max `64` | centralized |
| `action_profile` | enum | `move_2d` (only accepted value) | centralized |
| `decision_interval_s` | seconds | `0` (means `tick_s`); must be an integer multiple of `tick_s` | centralized |

`controlled_nodes` and the legacy `controlled_node_id` are mutually exclusive:
setting both is a configuration error. The legacy key keeps `Discrete(7)` with
`6:Stay`; `controlled_nodes` opts into `MultiDiscrete([5]*M)` with `4:hold`.

`all` means every node listed in `nodes.json`, in file order. Jammers live in
`jammers.json`, are never mesh nodes, and can never be controlled — even if a
jammer's `id` equals a node's `id`.

In centralized mode `reward_type = all_links_los` is the conjunction over every
controlled node (`+1` only if each one has at least one peer link and all of
them are LOS), and the reward reported per decision is the mean of the per-tick
rewards in that decision window.

`action_set` and `dimensions` are **not** accepted keys. The loader ignores
unknown keys silently, so either spelling has no effect; `dimensions` is
derived metadata reported in the `init` message.

Training on the bundled centralized fixture:

```bash
.venv/bin/python -m scripts.rl.train \
  --sim-binary <BIN> \
  --run-config inputs/baselines/centralized-multi-smoke/run.ini \
  --output-dir outputs/rl-multi \
  m-ppo --total-timesteps 16 --n-steps 16 --seed 1
```

#### Selecting observations, rewards, and telemetry

These `[rl]` keys are *read by the Python env and `train.py`; the simulator
ignores them*. They apply to centralized mode only.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `observation_preset` | preset name | `raw_links_v1` | which observation the policy sees |
| `reward_components` | comma-separated names | absent (the C++ reward) | components Python composes into the returned reward |
| `reward_weights` | comma-separated floats | `1.0` per component | one weight per component, in the same order |
| `telemetry` | `none` or `steps` | `none` | `steps` writes `<episode-dir>/steps.jsonl` |
| `telemetry_every` | positive int | `1` | save every kth policy decision (requires `telemetry = steps`) |

`train.py` takes the same five as `--observation-preset`, `--reward-components`,
`--reward-weights`, `--telemetry`, and `--telemetry-every`, all before the
`m-ppo` subcommand:

```bash
.venv/bin/python -m scripts.rl.train \
  --sim-binary <BIN> \
  --run-config inputs/baselines/centralized-multi-smoke/run.ini \
  --output-dir outputs/rl-multi-custom \
  --observation-preset local_links_v1 \
  --reward-components delivery_ratio,connectivity \
  --telemetry steps --telemetry-every 2 \
  m-ppo --total-timesteps 16 --n-steps 16 --seed 1
```

Each key resolves independently with precedence CLI > `run.ini` > default, and
both manifests record the resolved value and its source. An unknown preset or
component, a weight count that does not match the components, or any non-default
value of these keys in legacy mode fails before the simulator starts.

Observation presets:

- `raw_links_v1` — the flat vector as C++ emits it: raw positions and
  per-peer SINR/capacity, `float64`, unbounded.
- `local_links_v1` — per slot `[active, x, y, z]` normalized to `[-1, 1]` with
  the `[rl]` bounds, then `[present, sinr_valid, sinr_n, cap_n]` per peer;
  `float32`, SINR clipped to [-20, 40] dB, capacity as `log10(1 + Mbps) / 4`.
  Clipping keeps extreme values from dominating the policy input; the raw
  simulator measurement remains available in `facts`.

Reward components, each computed from the sums over one decision window:

- `delivery_ratio` — delivered / demanded Mbps. A window with no meaningful
  demand (`≤ 1e-9` in the accumulated values) is *masked*: the component is
  reported invalid and contributes 0, avoiding division by zero.
- `connectivity` — connected node pairs as a fraction of all pairs per tick.
- `throughput_mbps` — delivered Mbps per tick (unnormalized; scale grows with
  node count and demand).
- `legacy` — the simulator's own `reward_type` value for the window. This is a
  reward component name, not a switch to legacy single-node control.

Naming any component makes Python the reward authority: `step()` returns the
weighted total, `info["reward"]` holds the per-component values, validity, and
weights, and the C++ value remains available as `info["reward"]["legacy"]`.

With `telemetry = steps` each episode directory also gets a `steps.jsonl`: a
header line (contract, selection, observation schema, reward schema) followed
by one record per saved decision — the reset observation, every kth policy
decision, and always the terminal one. Records are buffered and flushed every
32 records and on stop, so a hard kill can lose up to 32 records. The separate
`rl_episode.json` is updated every decision regardless of `telemetry_every`;
that setting only reduces `steps.jsonl` records. On the
`centralized-multi-smoke` fixture a record measures about 0.9 KB and the header about
3.5 KB. `scripts.rl.env.telemetry.replay_file` rebuilds every saved
observation and recomputes Python-composed rewards from the stored facts and
schema. For the default C++ reward it checks the observation only. Replay
does not verify simulator physics, the next state, or unsaved decisions.

Both manifests carry SHA-256 fingerprints of the observation and reward schema
descriptions. These let a loader detect changed declared layouts,
normalization, components, or weights; they do not detect every code or physics
change and are not evidence that a policy transfers between scenarios. When
recorded during verification, a compiled-binary hash answers a different
question: which executable was tested. `manifest_version` labels the saved JSON
format, not the model or simulator version. Centralized runs need a simulator
binary that exports per-decision facts: an `init` without `facts_schema` is
rejected before training starts.

The full contract — slot order, action meanings, mask layout, decision cadence,
reward window, wall clipping, speed caps, and the `init`/`step`/action schemas —
lives in [`src/rl/README.md`](src/rl/README.md).

C++ owns the simulation because ns-3 mobility, propagation, link evaluation,
and routing already live there and must stay deterministic and testable without
Python; the bridge exposes only observations, masks, and rewards over
stdin/stdout. Python provides the Gymnasium/SB3 integration because
MaskablePPO, vectorized rollouts, and model persistence are Python libraries.
Movement limits and action validity are therefore decided once, in C++, and
Python never re-derives them.

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
| RL training | `<output-dir>/train_manifest.json`, `<output-dir>/maskable_ppo_mesh.zip`, and one `episode-NNNN/` per episode containing `run.log`, `inputs/`, `sim_stderr.log`, `rl_episode.json`, `steps.jsonl` (optional), and `seed-<seed>/...` |

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
