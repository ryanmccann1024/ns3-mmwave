@page scripts_arpo_data scripts/arpo_data

@brief Turns raw ARPO Spring Lake field-test CSVs into per-day plots, GPS traces, and per-scenario traces.

Tooling for the **ARPO Spring Lake** mmWave-mesh field-test dataset (CSV
exports from outdoor radio deployments). It is read-only with respect to the
source CSVs. Everything is driven from one CLI (`cli.py`) with subcommands
for unzipping, plotting, day-vs-day comparison, and trace splitting.

## Module Layout

| File | Role |
|------|------|
| @ref cli.py "cli" | Subcommand parser (`extract`, `plot`, `multi-day`, `split-day`, `split-scenario`); the only place figures are saved |
| @ref paths.py "paths" | Filesystem constants and `DatasetPaths`; list of known-bad scenarios |
| @ref extract.py "extract" | `extract` subcommand: unzip the bundle, skipping OS junk files |
| @ref loaders.py "loaders" | Per-node loaders for `bh2`, `mcm`, GPS, and Silvus RF CSVs; day filters |
| @ref topology.py "topology" | MAC to rab label resolution and plot colors |
| @ref topology_audit.py "topology_audit" | Standalone report of label collisions in the (rab, netdev) scheme |
| @ref multi_day.py "multi_day" | `multi-day` subcommand: histogram overlays and K-S tests across days |
| @ref multiday_variance.py "multiday_variance" | Variance tables over `_pairwise_ks.csv` |
| @ref split_trace_by_day.py "split_trace_by_day" | Split a combined GPS trace CSV into one file per day |
| @ref split_trace_by_scenario.py "split_trace_by_scenario" | Slice a per-day trace directory to one wall-clock window |
| @ref bh2.py "plots/bh2" | Per-radio metric plots (`plot_bh2_*`, `plot_silvus_*`), one figure per (src, peer) |
| @ref gps.py "plots/gps" | GPS track plot for one scenario |
| @ref common.py "plots/common" | Caption, crashed-scenario suffix, and trace-concat helpers for the plots |

## Setup

Two inputs are distinct:

- **Legacy zip for `extract`.** `extract` unzips the configured Spring Lake
  bundle, by default `scratch/mesh-sim/data/arpo_spring_lake_data.zip`, into
  `data/arpo_extracted/csv/<scenario>/<node>/`. Its contents are not verified
  here, and it is not known to contain any particular CalFEX/JEDDOC day.
- **Per-node CSV root for `plot --nodes`.** Any directory with one subdirectory
  per node, supplied with `-i`. The Silvus flow discovers a node only if it is a
  directory (other than `sdwan`) holding both `gps/` and `silvus/`, and its
  `silvus/config.csv` first row has a readable `node_id`; otherwise it is skipped
  with a warning. GPS comes from `gps/gps_position.csv` or the fallback
  `<node>/gps_position.csv`, with `latitude`, `longitude` and `time`;
  optional `callsign`/`uid` supplies a label (otherwise the node name is used).
  Discovery still requires the `gps/` directory. RF from `silvus/network_status.csv`
  (`node_id`, `neighbor`, `snr`, `mcs`, `mcs_rx`, `rssi_ant1..4`), optionally
  merged with `local_stats.csv` and `config.csv`. Directory names become the
  node labels; numeric Silvus `node_id`/`neighbor` values are mapped to those
  names through `config.csv`, and neighbors outside the discovered set are
  dropped. The metric plot writer also omits neighbor-MAC groups with fewer
  than five usable samples; their rows do not enter the exported trace. The older
  bh2 flow reads `bh2.csv` per node.

The end-to-end recipe that consumes these outputs is
[Compare the simulator with field data](@ref mesh_sim_field_data_workflow).

## Run

Run from `scratch/mesh-sim/`. Each command below is `python -m scripts.arpo_data.<module>`.

### Extract and plot

```bash
python -m scripts.arpo_data.cli extract                        # unzip; -i <zip> to override
python -m scripts.arpo_data.cli plot --scenario <name>         # one scenario dir under csv/
python -m scripts.arpo_data.cli plot --all                     # every scenario dir
python -m scripts.arpo_data.cli plot --nodes -i <csv_root> -o <out_dir> [--day YYYY-MM-DD] # per-day GPS + RF plots, one subdir per day
```

`plot --scenario` / `--all` currently fail with a `TypeError` on Silvus data; only `plot --nodes` works (see `CLAUDE.md`, Known issues).

`plot` takes `-i/--input` (CSV root, default `data/arpo_extracted/csv`) and
`-o/--output` (default `data/arpo_extracted/_plots/per_day`). `--nodes` is a
switch, not a node list. Run `extract` first only if the data comes from the
zip; a per-node root obtained elsewhere is passed with `-i` directly.
`--day` keeps rows whose UTC calendar date matches; without it every day found
is written to its own subdirectory, and an absent day lists the available ones
and exits 1. Day filtering does not reset the RF `__sec__` clock: it stays
elapsed from each node's first RF sample in the whole file.

### Split traces

```bash
python -m scripts.arpo_data.cli split-day -i <gps_all_nodes_trace.csv> -o <out_dir> [--prefix P]
python -m scripts.arpo_data.cli split-day -i <gps_all_nodes_trace.csv> --summary
python -m scripts.arpo_data.cli split-scenario -i <day_trace_dir> --start 9.05 --end 10.15 [-o <out_dir>] [--prefix P]
```

- `split-day` needs the combined trace written by `plot --nodes` (step before it).
- `split-scenario` takes `Hour.Minute` floats (`9.05` means 09:05, UTC; not decimal hours). `-i` is one day directory (`<out>/<YYYY-MM-DD>/`). Output defaults to `data/arpo_extracted/_plots/per_scenario/`; pass explicit `-i`/`-o` roots so previous products are not mixed in (it scans recursively and only excludes its own output subtree).
- `split-scenario` selects GPS and current `IH_*` metric traces by their `t_utc` time of day: the plot writer preserves that UTC column. The selected elapsed-time column is then re-zeroed. Only older files with `sec` but neither `t_utc` nor `sec_since_origin` are anchored to the GPS start, assuming radio/GPS co-start and producing a stderr note. Do not expect the note for UTC-bearing traces. The module docstring still says sec-only files are skipped; the implementation handles them with this fallback when a GPS offset is available.
- `split_trace_by_day` and `split_trace_by_scenario` can also be run directly as modules with the same flags. Their `-o` default differs: the direct `split_trace_by_scenario` defaults to `<input>/scenarios`.

### Compare days

```bash
python -m scripts.arpo_data.cli multi-day [--family <fam>] [--audit]
python -m scripts.arpo_data.multiday_variance [--metric snr|rcpi|mcs|per|throughput] [--family F] [--top N] [--csv out.csv] [--ks-csv path]
python -m scripts.arpo_data.topology_audit
```

- `multi-day` only matches `bh2_*` trace names, so it finds nothing in the `IH_*` output of the current Silvus flow.
- `multiday_variance` reads the `_pairwise_ks.csv` that `multi-day` writes, so run `multi-day` first.
- `topology_audit` takes no flags and reads the extracted `bh2.csv` files.

## Output

| Step | Where |
|------|-------|
| `extract` | `data/arpo_extracted/csv/<scenario>/<node>/` |
| `plot --scenario` / `--all` | `data/arpo_extracted/_plots/per_day/<scenario>/{pngs,csvs}/...` |
| `plot --nodes` | `<output>/<YYYY-MM-DD>/<node>/` plus `<YYYY-MM-DD>/gps_all_nodes.png` and `gps_all_nodes_trace.csv` |
| `split-day` | `<out_dir>/<prefix>_<YYYY-MM-DD>.csv` |
| `split-scenario` | `<out_dir>/[<prefix>_]<HHMM-HHMM>/` mirroring the input layout |
| `multi-day` | `data/arpo_extracted/_plots/multi_day/<family>/pngs/<src>/`, `_per_day_stats.csv`, `_pairwise_ks.csv` |
| `multiday_variance --csv` | the path you give |

Each `plot` figure has a matching trace CSV. `multi-day` pools traces by
scenario family and draws one normalized histogram (plus KDE curve) per day
for each (family, link, metric); areas integrate to 1 and a dotted line marks
each median. The subtitle gives the largest median difference between days
and the K-S statistic. `--audit` prints raw-CSV vs parsed row counts and maxima
to reveal NaN-coerce drops.

## Conventions

- Plot functions return a `matplotlib.Figure` (or `(src, peer, fig, trace)` tuples); only `cli.py` calls `savefig`.
- Loaders return `pd.DataFrame | None`; `None` means no usable data.
- Node clocks are skewed, so comparisons use `__sec__` (session-relative seconds), not raw UTC.
- Loader columns use `__name__` style (`__node__`, `__t__`, `__sec__`, `__lat__`, `__lon__`).
- Comments use Doxygen style (`##` or `##<`) so `@` commands work.

## Dependencies

- `pandas`, `numpy`, and `matplotlib` (Agg backend). No `scipy`; K-S and KDE are implemented in numpy.
- Data that must exist: the zip above (for `extract`), a per-node CSV tree from `extract` or supplied with `-i` (for `plot`, `topology_audit`), and `_plots/per_day` output (for `multi-day`).
