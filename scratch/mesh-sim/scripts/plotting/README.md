@page scripts_plotting scripts/plotting

@brief Post-simulation plotting: turns mesh-sim CSV/JSON outputs into figures.

Reads the `seed-N/` folders of a finished run, averages across seeds with 95%
confidence intervals (CI), and saves one image per enabled plot. It only reads
simulator output and never modifies it.

New here? \ref files_figures "Figures" walks through making the figures and
reading each one; this page is the reference it links to.

## 1\. Run

From `scratch/mesh-sim/`, with the Python environment set up once
(`python3 scripts/rl/bootstrap_venv.py`; it includes pandas, numpy and
matplotlib):

```bash
cp scripts/plotting/plot.example.ini my-plot.ini   # then set [output] data_dir
.venv/bin/python -m scripts.plotting.cli --config my-plot.ini
```

- `--config <path>` (required) is the plot INI file. Copy the example rather
  than editing it: its `data_dir` points at an old run.
- Figures go to `<data_dir>/figures/` (section 3).
- Plots whose input file is missing are skipped silently. The only hard failure
  is a `data_dir` with no `seed-N/` folders (exit 1).
- Sweeps can run this automatically after each point or at the end; see
  `auto_plot` in [scripts/sweep](@ref scripts_sweep).

## 2\. Configuration

| Section / key | Default | Meaning |
|---|---|---|
| `[output] data_dir` | required | Run folder containing `seed-N/` |
| `[output] format` | `png` | Image file extension |
| `[output] dpi` | `150` | Resolution (the example file sets 300) |
| `[plots] <toggle>` | `true` | Set `false` to skip a plot; toggles are listed in section 3 |

## 3\. Output

All files go to `<data_dir>/figures/`, named as below plus the image extension.

| Toggle | Output file(s) | Reads |
|---|---|---|
| `sinr_timeseries` | `sinr_timeseries` | `links.csv` |
| `rx_power_timeseries` | `rx_power_timeseries` | `rx-power.csv` |
| `capacity_timeseries` | `capacity_timeseries` | `links.csv` |
| `mcs_timeseries` | `mcs_timeseries` | `mcs.csv` |
| `throughput_timeseries` | `flow_throughput_timeseries`, `link_throughput_timeseries` | `flows.csv`, `links.csv` |
| `latency_timeseries` | `latency_timeseries` | `flows.csv` |
| `geometry` | `geometry` | `positions.csv` |
| `per_node_sinr` | `per_node_sinr` | `summary.json` |
| `per_node_throughput` | `per_node_tx_throughput`, `per_node_rx_throughput` | `summary.json` |
| `per_flow_throughput` | `per_flow_throughput` | `summary.json` |
| `per_flow_latency` | `per_flow_latency` | `summary.json` |
| `network_summary` | `network_summary` | `summary.json` |
| `sim_runtime` | `sim_runtime` | `summary.json` |

## 4\. Conventions

- Plot functions return a `matplotlib.Figure` and never call `savefig` or
  `plt.show`; `cli.py` saves and closes figures.
- Single-seed runs have no CI; multi-seed runs add CI bands or error bars.
- Loaders return `pd.DataFrame | None` (or `dict | None`); callers handle `None`.
- SINR and Rx power values at or below -900 are treated as placeholders and
  dropped before plotting.
- Time is rounded to 1 ms before grouping across seeds.
- t critical values come from `scripts/stats.py`.
- Comments use Doxygen `##` blocks above each function.

## 5\. Module layout

| File | Role |
|---|---|
| `cli.py` | Entry point: reads the INI, loads and aggregates data, saves figures |
| `loaders.py` | Finds `seed-N/` folders and loads each CSV/JSON file (returns `None` if missing) |
| `aggregation.py` | Mean and 95% CI across seeds for time series and `summary.json` |
| `plots_timeseries.py` | One function per time-series plot; each returns a `Figure` |
| `plots_summary.py` | Bar charts and tables from `summary.json`; each returns a `Figure` |
| `__init__.py` | Re-exports the loaders, aggregators and plot functions |
| `plot.example.ini` | Example config with every plot toggle |
| `CLAUDE.md` | Scope notes for AI assistants |

## 6\. Dependencies

- Python packages: `pandas`, `numpy`, `matplotlib`. No ns-3.
- `scripts/stats.py` (in this repo) for `sample_stats` and `t_critical_95`.
- A finished simulator run with `seed-N/` folders containing `summary.json` and
  the CSVs listed in section 3.
