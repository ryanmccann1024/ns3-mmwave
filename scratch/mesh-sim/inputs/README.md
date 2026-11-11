@page Inputs Scenario inputs

@brief Scenario definitions (`run.ini` + JSON files) that drive mesh-sim runs, plus RL experiment and sweep specs.

Each scenario is a directory holding the files that drive one simulation run.
Scenarios only describe inputs; run products go to `outputs/`.
Per-scenario details live in @ref inputs_baselines; `run.ini` keys live in the
[run.ini reference](@ref src_config_run_ini_reference).

## 1\. Layout

| Path | Role | Git |
|---|---|---|
| `baselines/` | Numbered synthetic scenarios 01-16 for deterministic validation, plus fixtures `p0-smoke`, `p0-jammer-smoke`, `rl-test`, `centralized-multi-smoke`, `building-bypass-smoke`. See @subpage inputs_baselines | Tracked |
| `calfex/` | Field-derived CalFEX sub-6 scenarios, one `<run>/` per day or `<HHMM-HHMM>` window (section 5) | Ignored (`inputs/.gitignore`); regenerate from field data |
| `sweeps/` | Parameter-sweep specs for `scripts.sweep.cli` | Only `example.ini` |
| `experiments/` | RL experiment matrix version 1 (`bypass-smoke-matrix.json`, run by `scripts.rl.experiment`), tuning study (`bypass-smoke-study.json`, run by `scripts.rl.ops.tune`), and public batch examples under `examples/` (section 11) | Tracked |
| `custom/sherpa/` | Local Spring Lake ARPO mmWave scenarios. Not in a clean checkout; ask the data owner. | Ignored, read-only |
| `custom/<campaign>/` | Local campaign packages. Each has its own README; its `run-*.sh` files are historical records (section 11). | Ignored |

The Sherpa and CalFEX inputs are separate field workflows: Sherpa describes
ARPO mmWave trials, CalFEX describes sub-6 field scenarios.

## 2\. Scenario files

| File | Required | Role |
|---|---|---|
| `run.ini` | yes | Simulation parameters. Keys and defaults: [run.ini reference](@ref src_config_run_ini_reference) |
| `nodes.json` | yes (path from `nodes_file`, default `nodes.json`) | Node positions and mobility; IDs unique, all `role: "peer"` |
| `buildings.json` | no (`buildings_file`) | Building geometry |
| `jammers.json` | no (`jammers_file`) | Jammers; only active when the band is `sub-6` |

- File paths inside `run.ini` are relative to the `run.ini` file.
- Every `run.ini` starts with a header comment explaining the scenario.

## 3\. Band selection

The band resolves as `--band` > `[channel] band` in `run.ini` > default `mmwave`.

- `build_config_files` requires `--band` and writes that choice to
  `[channel] band` in the generated `run.ini` (the field-data guide uses
  `sub-6`).
- Older hand-authored `calfex/` scenarios may not set `band`. For those, pass
  `--band sub-6` so jammers take effect. Check the generated file.

## 4\. Run

Scenarios need no setup beyond a built simulator binary. From the ns3-mmwave
repo root:

```bash
./build/scratch/mesh-sim/ns3*-sim-* \
  --run-config=scratch/mesh-sim/inputs/baselines/01-static-los-baseline/run.ini
```

Outputs go to a timestamped directory under `scratch/mesh-sim/outputs/`.

Sweeps and experiments need the venv (see the top-level README). From
`scratch/mesh-sim/`:

```bash
python -m scripts.sweep.cli --config inputs/sweeps/example.ini --dry-run
python -m scripts.rl.experiment --help
python -m scripts.rl.ops.tune --help
bash scripts/rl/run-experiments.sh --help
```

## 5\. Generate field scenarios

Only `calfex/` must be generated. From `scratch/mesh-sim/`:

```bash
python -m scripts.validation.build_config_files --help
```

| Tool | Effect |
|---|---|
| `scripts.validation.build_config_files` | Writes `run.ini` and `nodes.json` to `<output>/<run>/` (default `inputs/calfex`; `-o` overrides) |
| `scripts.validation.build_waypoints` | Then edits that `nodes.json` in place |
| `scripts.validation.make_jammers` | Writes `jammers.json`; a scenario has one only if this tool wrote it |

The end-to-end field recipe, which writes its generated scenario under a fresh
`outputs/` workspace instead of `inputs/calfex`, is
[Compare the simulator with field data](@ref mesh_sim_field_data_workflow).

## 6\. Output

| Step | Where |
|---|---|
| Simulator run | `outputs/YYYY-MM/DD/HH-MM-SS/` (override with `--output-dir`). The scenario files are archived once at that run root under `inputs/`, beside `run.log`; per-seed results go to `seed-N/` under it. See [What a run records](@ref src_io_run_record) |
| Sweep, experiment, batch, tuning | Written by the Python tool; see its README. Batch layout: [batch output layout](@ref mesh_sim_rl_batch_layout) |

The simulator writes nothing into `inputs/`. Only the field-data generators in
section 5 do.

## 7\. Conventions

- Numbered baselines change exactly one knob from scenario 01, so you can diff
  back to see what changed. See [Baseline Scenarios](@ref inputs_baselines) for
  the full table and how to read the output graphs.
- Scenario data (`run.ini` values, JSON) defines scenario identity; do not edit
  it for documentation work.

## 8\. Related directories

| Directory | Contents |
|---|---|
| `data/` | Local raw and derived field telemetry; read-only input to the validation generators; git-ignored. |
| `outputs/` | Disposable and git-ignored; never commit raw run products. |
| `tests/fixtures/regression/p0/` | Regression reference snapshots, external and untracked except `manifest.json`; never recapture them from changed code. |

## 9\. Dependencies

- A built mesh-sim binary (built by the user with ns-3; not covered here).
- Python 3 with the project venv for `scripts.sweep.cli`,
  `scripts.rl.experiment` and `scripts.rl.ops.tune` (tuning also needs
  `requirements-tuning.txt`).
- `calfex/` needs the per-node field bundle (external) to regenerate; see
  [Compare the simulator with field data](@ref mesh_sim_field_data_workflow).

## 10\. Private research inputs

Dated experiments under `custom/` are local records and are not portable
examples. Preserve their input/model directories when reviewing completed
results. Their old launchers call retired modules; use a converted batch in a
fresh output root with the [shared launcher](@ref mesh_sim_rl_batch_commands).
The tracked example below is the starting point for new configurations.

## 11\. RL batch inputs

### 11.1 Public example

`experiments/examples/coordination-smoke/` is the tracked, portable batch
example: `batch.json` (matrix version 2), `run.ini`, `nodes.json`,
`buildings.json`, `reference.json` and a short README. Paths inside
`batch.json` resolve against that folder. It is a plumbing fixture (64
decisions per episode, 256 training decisions), not a mission-performance
experiment. Its static validation was executed; its native smoke is a human-run
check and is BLOCKED until executed. Workflow:
[Experiments and operations](@ref mesh_sim_rl_experiments); fields:
[batch experiment reference](@ref mesh_sim_rl_batch_reference).

```bash
bash scripts/rl/run-experiments.sh validate --matrix inputs/experiments/examples/coordination-smoke/batch.json
```

### 11.2 Converted private campaigns

A historical campaign under `custom/<campaign>/` is converted by writing a
**new** batch file beside its original inputs, named
`custom/<campaign>/batch-v2.json` (or a distinct name such as
`batch-a-v2.json` when one campaign becomes several batches). A converter must
refuse an existing file rather than overwrite it, and must never edit a
historical INI, JSON asset, model or output. A conversion must be checked against its original inputs and saved identities.
`custom/` is ignored by Git; private conversions are not committed.

A conversion keeps one scenario per physical case and does not merge distinct
configurations or duplicate scenarios. Where historical rows used their own
byte-distinct INIs, the batch carries them as `rows[].configs` (including the
`training` role, with `training_config_key` keeping the historical lookup key,
such as `101`, per row); a gate shared across rows or scenarios is declared once
with `checks[].applies_to`; historical case controls run once per seed with
`baselines.configs_scope: "scenario"`; placement controls use the
`geometric`/`optimization` baseline policies with a recorded planning seed;
a v1 `decision_record_seeds` restriction keeps its meaning on operations and
baselines; and a profile selection over operations uses `{row, operation}`
candidates with an explicit `source_checkpoint`. Field contracts are in the
[batch reference](@ref mesh_sim_rl_batch_fields). A converted curriculum row may
reference a **new** schedule file written beside the conversion,
`custom/<campaign>/curriculum-<row>-v2.json`, whose provenance names the legacy
schedule and its SHA-256; the legacy schedule content is copied unchanged and
the historical JSON is not edited.

Worked instances in this checkout (private, ignored; listed by path only, their
contents are not reproduced here): ten batch files —
`custom/10-23/phase-1/batch-v2.json`, `custom/10-23-1/batch-v2.json`,
`custom/10-23-2/batch-v2.json` and `custom/10-23-2/batch-escape-v2.json`,
`custom/10-23-3/batch-v2.json`, `custom/10-23-4/batch-v2.json`,
`custom/10-23-6/batch-v2.json`, `custom/10-30/batch-a-v2.json`,
`custom/10-30/batch-b-v2.json` and `custom/10-30/phase-9/batch-v2.json` — and
eight curriculum schedules `custom/10-23-6/curriculum-*-v2.json`. Another
checkout may have none of them.

### 11.3 Current versus historical commands

| Commands | Status |
|---|---|
| `bash scripts/rl/run-experiments.sh validate\|plan\|run\|status\|resume` | Current; the maintained batch launcher. |
| `scripts.rl.experiment` with a version 1 matrix, `scripts.rl.train`, `evaluate`, `compare`, `online`, `validate_config`, `inspect_model`, `preflight_campaign`, `scenario_check`, `scripts.rl.ops.*` | Current; supported standalone tools. |
| `custom/**/run-*.sh`, and the `campaign`, `adaptive_campaign`, `mission_*`, `phase_*` modules they call | Historical. The scripts are immutable records of what was run, not supported launchers; the numbered runtime modules and duplicated campaign runners were removed on 2026-10-30. The replacement for each family is in [Retired commands](@ref mesh_sim_rl_batch_retired). |

Section 10's Phase 9 commands are historical in this sense: that campaign
finished with the code it started with and is never resumed by the batch
runner.
