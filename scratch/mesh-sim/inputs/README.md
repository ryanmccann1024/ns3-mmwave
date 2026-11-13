@page Inputs Scenario inputs

@brief Scenario definitions (`run.ini` + JSON files) that drive mesh-sim runs, plus RL experiment and sweep specs.

Each scenario is a directory holding the files that drive one simulation run.
Scenarios only describe inputs; run products go to `outputs/`.

\note New here? Run scenario 01 (section 2), then read
@ref inputs_baselines for what each numbered scenario tests and how to read its
graphs. Every `run.ini` key is in the
[run.ini reference](@ref src_config_run_ini_reference).

## 1\. What lives here

| Path | Contents | In Git? |
|---|---|---|
| `baselines/` | Numbered synthetic scenarios 01–16 and small test fixtures. See @subpage inputs_baselines | Yes |
| `sweeps/` | Parameter-sweep specs for `scripts.sweep.cli` | Only `example.ini` |
| `experiments/` | RL experiment matrices, a tuning study and a public batch example (section 5) | Yes |
| `calfex/` | Field-derived CalFEX sub-6 scenarios, one `<run>/` per day or `<HHMM-HHMM>` window (section 4) | No; regenerate from field data |
| `custom/sherpa/` | Local Spring Lake ARPO mmWave scenarios. Not in a clean checkout; ask the data owner. | No; read-only |
| `custom/<campaign>/` | Local campaign packages, each with its own README (section 8) | No |

The Sherpa and CalFEX inputs are separate field workflows: Sherpa describes
ARPO mmWave trials, CalFEX describes sub-6 field scenarios. Ignored folders are
listed in `inputs/.gitignore`.

## 2\. Run a scenario

Scenarios need no setup beyond a built simulator binary. From the ns3-mmwave
repo root:

```bash
./build/scratch/mesh-sim/ns3*-sim-* \
  --run-config=scratch/mesh-sim/inputs/baselines/01-static-los-baseline/run.ini
```

- Outputs go to a timestamped directory under `scratch/mesh-sim/outputs/`
  (section 6).
- The band resolves as `--band` > `[channel] band` in `run.ini` > default
  `mmwave`.

Sweeps and experiments need the project venv (see the top-level README). From
`scratch/mesh-sim/`:

```bash
.venv/bin/python -m scripts.sweep.cli --config inputs/sweeps/example.ini --dry-run
.venv/bin/python -m scripts.rl.experiment --help
.venv/bin/python -m scripts.rl.ops.tune --help
bash scripts/rl/run-experiments.sh --help
```

## 3\. Scenario files

| File | Required | Role |
|---|---|---|
| `run.ini` | yes | Simulation parameters. Keys and defaults: [run.ini reference](@ref src_config_run_ini_reference) |
| `nodes.json` | yes (path from `nodes_file`, default `nodes.json`) | Node positions and mobility; IDs unique, all `role: "peer"` |
| `buildings.json` | no (`buildings_file`) | Building geometry |
| `jammers.json` | no (`jammers_file`) | Jammers; only active when the band is `sub-6` |

- File paths inside `run.ini` are relative to the `run.ini` file.
- Every `run.ini` starts with a header comment explaining the scenario.
- Numbered baselines change one main knob from scenario 01, so you can diff
  back to see what changed.
- Scenario data (`run.ini` values, JSON) defines scenario identity; do not edit
  it for documentation work.

## 4\. Field scenarios

Only `calfex/` must be generated, and it needs the external per-node field
bundle. From `scratch/mesh-sim/`:

```bash
.venv/bin/python -m scripts.validation.build_config_files --help
```

All three tools are `scripts.validation` modules, run in this order:

| Tool | Effect |
|---|---|
| `build_config_files` | Writes `run.ini` and `nodes.json` to `<output>/<run>/` (default `inputs/calfex`; `-o` overrides) |
| `build_waypoints` | Then edits that `nodes.json` in place |
| `make_jammers` | Writes `jammers.json`; a scenario has one only if this tool wrote it |

- `build_config_files` requires `--band` and writes it to `[channel] band` in
  the generated `run.ini` (the field-data guide uses `sub-6`).
- Older hand-authored `calfex/` scenarios may not set `band`. For those, pass
  `--band sub-6` so jammers take effect, and check the generated file.

The end-to-end recipe, which writes its scenario under a fresh `outputs/`
workspace instead of `inputs/calfex`, is
[Compare the simulator with field data](@ref mesh_sim_field_data_workflow).

## 5\. RL experiment inputs

| File | Run with |
|---|---|
| `experiments/bypass-smoke-matrix.json` (matrix version 1) | `scripts.rl.experiment` |
| `experiments/bypass-smoke-study.json` (tuning study) | `scripts.rl.ops.tune` |
| `experiments/examples/coordination-smoke/` (batch, matrix version 2) | `scripts/rl/run-experiments.sh` |

`coordination-smoke` is the tracked, portable batch example and the starting
point for new configurations. It holds `batch.json`, `run.ini`, `nodes.json`,
`buildings.json`, `reference.json` and a short README; paths inside
`batch.json` resolve against that folder.

- It is a plumbing fixture (64 decisions per episode, 256 training
  decisions), not a mission-performance experiment.
- Its inputs pass static validation; a native smoke run has not been executed
  yet.

```bash
bash scripts/rl/run-experiments.sh validate \
  --matrix inputs/experiments/examples/coordination-smoke/batch.json
```

Workflow: [Experiments and operations](@ref mesh_sim_rl_experiments). Fields:
[batch experiment reference](@ref mesh_sim_rl_batch_reference).

## 6\. Output

| Step | Where |
|---|---|
| Simulator run | `outputs/YYYY-MM/DD/HH-MM-SS/` (override with `--output-dir`). The scenario files are archived once at that run root under `inputs/`, beside `run.log`; per-seed results go to `seed-N/` under it. See [What a run records](@ref src_io_run_record) |
| Sweep, experiment, batch, tuning | Written by the Python tool; see its README. Batch layout: [batch output layout](@ref mesh_sim_rl_batch_layout) |

The simulator writes nothing into `inputs/`. Only the field-data generators in
section 4 do.

## 7\. Related directories and dependencies

| Directory | Contents |
|---|---|
| `data/` | Local raw and derived field telemetry; read-only input to the validation generators; git-ignored. |
| `outputs/` | Disposable and git-ignored; never commit raw run products. |
| `tests/fixtures/regression/p0/` | Regression reference snapshots, external and untracked except `manifest.json`; never recapture them from changed code. |

- **Simulator runs** need a built mesh-sim binary (built by the user with
  ns-3; not covered here).
- **Sweeps, experiments and tuning** need Python 3.10+ with the project venv;
  tuning also needs `requirements-tuning.txt`.
- **`calfex/`** needs the per-node field bundle to regenerate (section 4).

## 8\. Historical campaigns under custom/

Dated experiments under `custom/` are local records, not portable examples.
Preserve their input and model directories when reviewing completed results.
Their old launchers call retired modules; to rerun one, convert it to a batch
and run it in a fresh output root with the
[shared launcher](@ref mesh_sim_rl_batch_commands).

| Commands | Status |
|---|---|
| `bash scripts/rl/run-experiments.sh <command>` (`validate`, `plan`, `run`, `status`, `resume`) | Current; the maintained batch launcher. |
| `scripts.rl.experiment` with a version 1 matrix, `scripts.rl.train`, `evaluate`, `compare`, `online`, `validate_config`, `inspect_model`, `preflight_campaign`, `scenario_check`, `scripts.rl.ops.*` | Current; supported standalone tools. |
| `custom/**/run-*.sh`, and the `campaign`, `adaptive_campaign`, `mission_*`, `phase_*` modules they call | Historical: immutable records of what was run, not supported launchers. The numbered runtime modules and duplicated campaign runners were removed on 2026-10-30; replacements are in [Retired commands](@ref mesh_sim_rl_batch_retired). |

<details>
<summary>Converting a historical campaign to a batch</summary>

To convert a campaign under `custom/<campaign>/`, write a **new** batch file
beside its original inputs: `custom/<campaign>/batch-v2.json`, or a distinct
name such as `batch-a-v2.json` when one campaign becomes several batches.
`custom/` is ignored by Git, so conversions are not committed.

- **Never overwrite or edit history.** A converter refuses an existing file
  and never edits a historical INI, JSON asset, model or output. Check each
  conversion against its original inputs and saved identities.
- **One scenario per physical case.** Do not merge distinct configurations or
  duplicate scenarios.
- **Map historical features to version 2 fields** (contracts in the
  [batch reference](@ref mesh_sim_rl_batch_fields)):
  - Rows with their own byte-distinct INIs: `rows[].configs`, including the
    `training` role, with `training_config_key` keeping the historical lookup
    key (such as `101`).
  - A gate shared across rows or scenarios: declared once with
    `checks[].applies_to`.
  - Historical case controls: run once per seed with
    `baselines.configs_scope: "scenario"`.
  - Placement controls: the `geometric`/`optimization` baseline policies with a
    recorded planning seed.
  - A version 1 `decision_record_seeds` restriction keeps its meaning on
    operations and baselines.
  - A profile selection over operations: `{row, operation}` candidates with an
    explicit `source_checkpoint`.
- **Curriculum schedules.** A converted curriculum row may reference a **new**
  schedule file beside the conversion,
  `custom/<campaign>/curriculum-<row>-v2.json`, whose provenance names the
  legacy schedule and its SHA-256. The legacy schedule content is copied
  unchanged.

</details>
