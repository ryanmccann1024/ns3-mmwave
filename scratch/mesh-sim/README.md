@page mesh_sim_overview User guide

@brief Lightweight time-stepped mmWave / sub-6 mesh simulator built on ns3-mmwave.

\note New here? [Start here](docs/getting-started/start-here.md) walks through
a first run; [Quickstart](docs/getting-started/quickstart.md) has every command
on one page. This guide is the reference for everyday tasks. The full
documentation is a site you build locally: see
[Generating the docs](docs/generating-the-docs.md).

Mesh-Sim loads a scenario, steps through time working out every link's SINR,
capacity and MCS, routes traffic over the mesh and writes the results
(\ref mesh_sim_run_flow "How a run works"). Jammers and a reinforcement-learning
(RL) bridge are optional.

Mesh-Sim is being developed in Dr. Vinod Vokkarane's Advanced Communication
Networks Laboratory (ACNL) at the University of Massachusetts Lowell, in
collaboration with Sherpa 6.

# 1\. Set up {#readme_setup}

## Build {#readme_build}

From the **ns3-mmwave repo root**, build only the modules Mesh-Sim needs (the
same build CI uses):

```bash
./ns3 configure --build-profile=debug \
  --enable-modules=core,network,mobility,propagation,buildings \
  --disable-examples --disable-tests -- -DNS3_WARNINGS_AS_ERRORS=OFF
./ns3 build scratch/mesh-sim/sim
```

The binary is `build/scratch/mesh-sim/ns3.42-sim-debug`; Python tools take it
as `--sim-binary <BIN>` and never build it. To build all of ns-3 instead, on
Apple silicon:

```bash
./ns3 clean
./ns3 configure --build-profile=debug -- -DCMAKE_OSX_ARCHITECTURES=arm64
./ns3 build
```

Step by step: \ref mesh_sim_install_build "Install and build".

## Python environment {#readme_python_environment}

The simulator needs no Python; the plotting, sweep, validation and RL tools
need Python 3.10 or newer.
From `scratch/mesh-sim/`:

```bash
python3 scripts/rl/bootstrap_venv.py          # creates .venv
python3 scripts/rl/bootstrap_venv.py --check  # checks versions only
```

On Windows the interpreter is `.venv\Scripts\python.exe`. RL tuning also needs
`requirements-tuning.txt` (\ref scripts_rl "scripts/rl").

# 2\. Run a scenario {#readme_run}

Simulator commands run from the **ns3-mmwave repo root**; Python commands from
**scratch/mesh-sim**.

## Single scenario {#readme_run_single}

```bash
./ns3 run scratch/mesh-sim/sim -- \
  --run-config=scratch/mesh-sim/inputs/baselines/01-static-los-baseline/run.ini \
  --seeds=1 \
  --output-dir=scratch/mesh-sim/outputs/getting-started/01-static-los-baseline
```

Give every run its own `--output-dir`: reusing one overwrites it.

| Everyday flag | Does |
|---|---|
| `--run-config` | The scenario's `run.ini` (the file, not the folder). |
| `--seeds` | Seeds to run, comma-separated; each gets its own `seed-<N>/`. |
| `--output-dir` | Where results go. |
| `--band` | `sub-6` or `mmwave`, overriding `run.ini`. Jammers count only on `sub-6`. |
| `--no-viz` | Skip the six CSVs; keep `run.log`, `inputs/` and `summary.json`. |

| Less often | Does |
|---|---|
| `--seed`, `--run-id` | Override the single seed or run id in `run.ini`. |
| `--positions-override` | A JSON file of start positions (\ref files_nodes_json "nodes.json"). |
| `--jammer-onset-s` | Start every enabled jammer at this time (\ref files_jammers_json "jammers.json"). |
| `--debug-links` | Log every link and jammer calculation. |
| `--rl-mode` | Run with the RL bridge. |
| `--channel-query` | Answer channel queries for the placement baselines instead of running (\ref src_query "contract"). |

All flags: \ref src_cli "CLI guide". After a run, the *Resolved config* block
in `run.log` shows what was actually used (\ref files_run_log "run.log").

# 3\. Common tasks {#readme_tasks}

<div class="ms-cards">
<div class="ms-card">
<div class="ms-card-title">Look at the results</div>
<ul>
<li>\ref files_figures "Graph a run": `scripts.plotting.cli`</li>
<li>\ref mesh_sim_first_result "Replay it in 3D": `npm run dev` in `ns3-mmwave-viz`</li>
<li>\ref mesh_sim_files "Read the output files"</li>
</ul>
</div>
<div class="ms-card">
<div class="ms-card-title">Change the scenario</div>
<ul>
<li>\ref mesh_sim_change_one_setting "Change one setting"</li>
<li>\ref files_run_ini "run.ini", \ref files_nodes_json "nodes.json", \ref files_buildings_json "buildings.json", \ref files_jammers_json "jammers.json"</li>
<li>\ref src_jammer "Make jammers from trial data": `scripts.validation.make_jammers`</li>
</ul>
</div>
<div class="ms-card">
<div class="ms-card-title">Run experiments</div>
<ul>
<li>\ref scripts_sweep "Sweep a parameter": `scripts.sweep.cli`</li>
<li>\ref mesh_sim_field_data_workflow "Build a scenario from field data and compare"</li>
<li>\ref scripts_baselines "Plan placement baselines": `scripts.baselines.runner`</li>
</ul>
</div>
<div class="ms-card">
<div class="ms-card-title">Reinforcement learning</div>
<ul>
<li>\ref mesh_sim_rl_start "RL in Mesh-Sim": the end-to-end guide</li>
<li>\ref mesh_sim_rl_train "Train a policy" and \ref mesh_sim_rl_evaluate "Evaluate and compare"</li>
<li>\ref scripts_rl "Experiment matrices", \ref scripts_rl_ops "benchmarks, tuning and clusters"</li>
<li>Reference: \ref src_config_run_ini_reference "[rl] keys", \ref src_rl "the bridge contract", \ref src_rl_policy_inputs "observations and rewards"</li>
</ul>
</div>
</div>

# 4\. Verify {#readme_verify}

From `scratch/mesh-sim/tests/`:

```bash
make test                               # unit tests; stops at the first failing suite
MESH_SIM_BIN=<BIN> make integration     # CLI checks against a built binary
```

From `scratch/mesh-sim/`:

```bash
# Output format and same-seed repeatability, on two small runs
python3 -m scripts.validation.smoke_check --sim-binary <BIN> --out outputs/smoke-check/<new-name>

# RL training end to end
.venv/bin/python -m scripts.rl.train --sim-binary <BIN> \
  --run-config inputs/baselines/p0-smoke/run.ini \
  --output-dir outputs/rl-smoke-verification/rl \
  m-ppo --total-timesteps 16 --n-steps 16 --seed 1
```

- One unit suite: `make -C unit/<suite> test`, for any suite listed in
  `UNIT_DIRS` in `tests/Makefile`.
- The regression suite needs the reference files from the project's cloud
  baseline bundle under `tests/fixtures/regression/p0/`; then
  `python3 -m scripts.validation.regression_check verify-suite`
  (\ref scripts_validation "scripts/validation").
- CI runs the Python tests, the build, and the CLI and smoke checks on Linux and
  macOS for pushes and pull requests to `develop` and `arpo-main`.
- Every RL test, with its input and expected output: \ref scripts_rl_tests "RL test map".

# 5\. Output {#readme_where_output_lands}

| Run | Writes |
|---|---|
| The simulator | `run.log`, `inputs/`, and per seed `seed-N/` with six CSVs and `summary.json` |
| A sweep point or validation scenario | The same, plus `console.log` |
| RL training and evaluation | Manifests, models and `episode-NNNN/` folders (\ref scripts_rl_output "scripts/rl") |

Without `--output-dir` or `[output] dir`, results go to
`outputs/YYYY-MM/DD/HH-MM-SS/`. Every file and column:
\ref mesh_sim_files "Input and output files".

# 6\. Conventions {#readme_conventions}

- Run Python tools as modules from `scratch/mesh-sim/`:
  `python -m scripts.<pkg>.<module>`.
- Scenario files beside `run.ini` are copied into every output folder; files
  elsewhere are not.
- `outputs/` and `docs/html/` are not tracked by Git.
- Comments use Doxygen style: `##` blocks in Python, `/** ... */` in C++.
- Changing configuration, the RL protocol or saved results: follow the
  \ref Contributing "contributor checklist".
- Where everything lives: \ref mesh_sim_repo_map "Repository map". `sim.cc`
  is the entry point; the code is in \ref src "src" and \ref scripts "scripts".

## Dependencies {#readme_dependencies}

| For | You need |
|---|---|
| The simulator | ns3-mmwave, CMake and a C++ compiler |
| Python tools | Python 3.10+ and `requirements.txt`; `requirements-tuning.txt` for tuning |
| Field data and regression | Field data under `data/`; the cloud baseline bundle |
| These docs | `doxygen`, and `graphviz` for diagrams |

# 7\. Documentation {#readme_docs}

The docs are a static Doxygen site. From `scratch/mesh-sim/docs/`:

```bash
./build.sh                  # stages the Python sources, then runs Doxygen
open html/index.html        # macOS; xdg-open on Linux, start on Windows
```

`build.sh` copies the `.py` files into the ignored `docs/.api-src/` before
running `doxygen Doxyfile`, so Python modules are named `scripts.<package>...`
in the API reference. Running `doxygen Doxyfile` alone still builds the guides,
but the Python API pages then come from whatever `.api-src/` last held.

Install the tools with `brew install doxygen graphviz` (macOS) or
`sudo apt install doxygen graphviz` (Linux). Versions and theme details:
\ref generating_the_docs "Generating the docs".
