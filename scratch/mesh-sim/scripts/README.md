# scripts

Python tools around the simulator: field data, validation, sweeps, plotting,
placement baselines and RL. Run them as modules from `scratch/mesh-sim/`, for
example `.venv/bin/python -m scripts.sweep.cli --help`, after setting up the
Python environment ([Install and build](../docs/getting-started/install-and-build.md),
step 5).

| Package | What it does |
| --- | --- |
| [arpo_data](arpo_data/README.md) | Turns raw field-test CSVs into per-day plots, GPS traces and per-scenario traces. |
| [validation](validation/README.md) | Checks simulator output against field data and against stored regression results. |
| [sweep](sweep/README.md) | Runs a grid of simulations from one sweep INI file into a single output folder. |
| [plotting](plotting/README.md) | Turns simulator CSV and JSON outputs into figures. |
| [baselines](baselines/README.md) | Plans geometric and optimization node placements before a run, scored by the simulator channel. |
| [rl](rl/README.md) | RL environment, training, evaluation, comparison and experiment batches. |

Shared helpers live beside the packages: `sim_support.py` (finding and launching
the simulator), `artifact_io.py` (atomic JSON and hashes) and `stats.py` (95%
confidence intervals).

The full documentation, including every package page, is the docs site; see
[Generating the docs](../docs/generating-the-docs.md).
