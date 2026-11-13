@page scripts_sweep scripts/sweep

@brief Runs a grid of mesh-sim simulations from one sweep INI file and collects them in a single output folder.

A sweep takes a base scenario (`run.ini` + `nodes.json`), changes chosen
`run.ini` values, and runs the simulator once per combination of values (a
"point") for a list of seeds. The points are the cartesian product of every
line in the `[sweep]` section. It can also plot each point.

## 1\. Usage

Run from `scratch/mesh-sim/`. Build the simulator first (this tool never builds
it) and create the Python environment once:

```bash
python3 scripts/rl/bootstrap_venv.py
```

Preview the points (starts no simulations, needs no binary):

```bash
.venv/bin/python -m scripts.sweep.cli --config inputs/sweeps/example.ini --dry-run
```

Run the sweep:

```bash
.venv/bin/python -m scripts.sweep.cli --config inputs/sweeps/example.ini --sim-binary <BIN>
```

## 2\. Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--config` | required | Path to the sweep INI. |
| `--dry-run` | off | Print the sweep matrix and exit. |
| `--resume` | off | Skip points whose `seed-<N>/summary.json` files all exist. In practice nothing is skipped (section 5). |
| `--sim-binary` | first `ns3*-sim-*` under `<ns3>/build/scratch/mesh-sim/` | Simulator binary. |

## 3\. Sweep INI

`inputs/sweeps/example.ini` runs 3 frequencies x 3 TX powers = 9 points, with 3
seeds each:

```ini
[sweep.meta]
base_scenario = inputs/baselines/01-static-los-baseline
seeds = 1, 2, 3
auto_plot = all
plot_config = scripts/plotting/plot.example.ini
label = freq-power-sweep

[sweep.override]
scenario.duration_s = 2.0

[sweep]
channel.frequency_ghz = 28.0, 39.0, 60.0
channel.tx_power_dbm  = 20.0, 25.0, 30.0
```

| Section | Required | Contents |
|---|---|---|
| `[sweep.meta]` | yes | Sweep settings (table below). |
| `[sweep.override]` | no | `section.key = value` constants applied to every point. |
| `[sweep]` | yes | `section.key = v1, v2, ...`. Each key is a `run.ini` section and key. |

Precedence: sweep values win over overrides, and overrides win over the base
`run.ini`.

`[sweep.meta]` keys:

| Key | Default | Description |
|-----|---------|-------------|
| `base_scenario` | required | Scenario directory (must hold `run.ini`), relative to the mesh-sim root. |
| `seeds` | `1` | Seeds per point; comma list and `A-B` ranges. |
| `auto_plot` | `none` | `each` (after every successful point), `all` (after the sweep), or `none`. |
| `plot_config` | empty | Plot INI relative to the mesh-sim root; empty uses the default plots. |
| `label` | `sweep` | Used in each point's `[scenario] name` (`<label>_point-NNN`) and the console summary. |

### Sweeping the band

`band` is an ordinary `run.ini` key and needs no special syntax. Jammer
interference applies only to `sub-6` points, and the sweep does not copy
`jammers.json` (section 5).

```ini
[sweep]
channel.band = mmwave, sub-6
```

To pin every point to one band, put `channel.band = sub-6` under
`[sweep.override]` instead. The validation batch runner takes the same setting
as a flag: `python -m scripts.validation.run_batch ... [--band sub-6]`.

## 4\. Output

| What | Where |
|------|-------|
| Sweep folder | `outputs/YYYY-MM/DD/HH-MM-SS/` under the mesh-sim root (new every run). |
| Copy of the sweep INI | `<sweep folder>/sweep.ini` |
| Manifest (rewritten after each point) | `<sweep folder>/sweep_manifest.json` |
| Per-point inputs | `<sweep folder>/point-NNN/run.ini`, `nodes.json`, optional buildings file |
| Per-point simulator output | `<sweep folder>/point-NNN/seed-<N>/`, plus the simulator's `run.log` |
| Simulator stdout/stderr | `<sweep folder>/point-NNN/console.log` |
| Plots (if enabled) | `<sweep folder>/point-NNN/plot.ini` and the plotting CLI's output |

- Points are numbered from 1 in cartesian-product order; the last `[sweep]` line
  varies fastest.
- A failed point is recorded as `failed` in the manifest, and the sweep
  continues.
- Each point's `run.ini` is rewritten with `configparser`: the base file's
  comments are dropped and keys are lowercased. `[output] dir` is set to the
  point folder and `[scenario] name` to `<label>_point-NNN`.
- Swept values are passed through as strings; the simulator validates each
  generated `run.ini` itself.

## 5\. Known issues

- **`--resume` never skips anything.** Every run creates a new timestamped
  folder, so no finished points are found.
- **`jammers.json` is not copied** into the point folders; only the nodes and
  buildings files are.
- **A `scenario.buildings_file` in `[sweep.override]` is ignored** when choosing
  which file to copy. `nodes_file` overrides, and per-point `[sweep]` values of
  either key, are honored.

## 6\. Module layout

| File | Role |
|------|------|
| `cli.py` | Command-line entry point (`--config`, `--dry-run`, `--resume`, `--sim-binary`). |
| `config.py` | Parses and validates the sweep INI into `SweepConfig` / `SweepDimension`. |
| `ini_writer.py` | Writes each point's `run.ini` and copies `nodes.json` and the buildings file. |
| `runner.py` | Builds the point matrix, launches the simulator, writes the manifest, triggers plots. |
| `__init__.py` | Empty package marker. |

Each function has a Doxygen `##` comment block above it.

## 7\. Dependencies

- Python 3.10+ (uses `X | None` type hints); standard library only.
- `scripts/sim_support.py` (binary lookup, seed parsing) and `scripts/plotting/`
  (only for `auto_plot`).
- A built simulator binary, except with `--dry-run`.
