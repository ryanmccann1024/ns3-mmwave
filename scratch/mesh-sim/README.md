@mainpage Overview

@brief Lightweight time-stepped mmWave / sub-6 mesh simulator built on ns3-mmwave.

The sim loads a scenario (@c run.ini + @c nodes.json), steps through time evaluating per-link SINR / capacity / MCS
against an ns-3 propagation model, routes traffic, and writes metrics. It also
supports an optional reinforcement-learning (RL) bridge and an optional jammer /
interference model.

For changes to configuration, the RL protocol, or saved results, see the
[contributor checklist](@ref Contributing).

## Module Layout

| File | Role |
|------|------|
| `sim.cc` | Simulator entry point: parses the CLI, loads the scenario, runs the per-tick loop. |
| `CMakeLists.txt` | Source list for the ns-3 build. |
| [src](@ref src) | C++ modules (config, eval, routing, jammer, traffic, io, rl, ...). |
| [scripts](@ref scripts) | Python tools: field-data pipeline, validation, sweeps, RL, baselines, plotting. |
| [inputs](@ref Inputs) | Scenario definitions (`run.ini` + JSON files), sweeps, experiment matrices. |
| [tests](@ref tests) | C++ unit tests, CLI integration script, regression fixtures. |
| `docs/` | `Doxyfile` and `topics.dox` for this documentation site. |
| [CONTRIBUTING.md](@ref Contributing) | "Update together" checklist for user-visible changes. |
| `requirements.txt` | Pinned Python dependencies. |
| `requirements-tuning.txt` | Optuna pin, used only by the tuning smoke. |
| `TODO.md` | Open work items. |
| `data/`, `outputs/`, `third_party/` | Field data, generated results (git-ignored), vendored code. |

## Setup {#readme_setup}

### Build {#readme_build}

You build the simulator yourself; none of the tools here build it. All commands
run from the **ns3-mmwave repo root** (two levels above this directory).

```bash
./ns3 clean
./ns3 configure --build-profile=debug -- -DCMAKE_OSX_ARCHITECTURES=arm64
./ns3 build
```

If `./ns3 clean` does not clear the cache fully, remove it manually first:

```bash
rm -rf cmake-cache build
```

### Python environment {#readme_python_environment}

The simulator itself needs no Python. The RL, sweep, validation, and plotting
scripts do. One command from `scratch/mesh-sim/` creates `.venv` and installs
`requirements.txt`:

```bash
python3 scripts/rl/bootstrap_venv.py
.venv/bin/python -m pytest scripts/rl/tests -q
```

- On Windows the interpreter is `.venv\Scripts\python.exe`.
- `requirements.txt` pins the direct dependencies at the versions tested on the
  implementer's platform; it is not a universal lock file.
- `python3 scripts/rl/bootstrap_venv.py --check` verifies imports and exact
  installed versions without installing anything.
- Tuning needs Optuna from a separate file; see [scripts/rl](@ref scripts_rl).

## Run {#readme_run}

Simulator commands run from the **ns3-mmwave repo root**. Python commands run
from **scratch/mesh-sim**.

### Single scenario {#readme_run_single}

```bash
./ns3 run scratch/mesh-sim/sim -- \
  --run-config=scratch/mesh-sim/inputs/calfex/1602-1605/run.ini \
  --band=sub-6 \
  --seeds=1,2,5,6,8,10 \
  --output-dir=scratch/mesh-sim/outputs/calfex/1602-1605
```

Key flags (the full list is in the [CLI guide](@ref src_cli)):

| Flag | Meaning |
|------|---------|
| @c --run-config | Path to the scenario's @c run.ini (the file, not the dir). |
| @c --band | @c sub-6 or @c mmwave. Interference/jammers only apply on @c sub-6. Optional. |
| @c --seeds | Comma-separated seeds; each gets its own `seed-<N>/` output subdir. |
| @c --output-dir | Where results are written. |
| @c --rl-mode | Enable the RL bridge. |
| @c --seed / @c --run-id | Override the single seed or the run id from @c run.ini (@c --seeds takes precedence for multi-seed runs). |
| @c --positions-override | Optional JSON file overriding node start positions. |
| @c --debug-links | Verbose per-link (and per-jammer) log output. |
| @c --channel-query | Serve candidate-layout channel queries on stdin/stdout for the placement baselines ([contract](@ref src_query)); needs exactly one seed and writes no outputs. |

The band resolves as `--band`, then `[channel] band` in `run.ini`, then the
default `mmwave` (see the [run.ini reference](@ref src_config_run_ini_reference)).
After a run, check the "Resolved config" block in `run.log` (frequency,
duration, bandwidth, band) before trusting the results.

### Generating a scenario from field data {#readme_run_pipeline}

Run from **scratch/mesh-sim**. Each step needs the output of the one before it.

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

### Validating against field data {#readme_run_validate}

```bash
python -m scripts.validation.validate_days \
  --day 1227-1413 \
  --field-root data/arpo_extracted/_plots/per_day/2026-06-25/scenarios \
  -t 6360
```

See [scripts/validation](@ref scripts_validation) for the other validation tools.

### Jammer / interference model (optional) {#readme_run_jammer}

Run a scenario with field-logged electronic-warfare (jamming) events. The full
workflow is in the [jammer model](@ref src_jammer); in brief:

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

### Sweep {#readme_run_sweep}

```bash
python -m scripts.sweep.cli --config inputs/sweeps/example.ini
```

Sweep format and flags, including sweeping `band`, are in
[scripts/sweep](@ref scripts_sweep).

### Reinforcement learning {#readme_run_rl}

Smoke training run from **scratch/mesh-sim** (replace `<BIN>` with your built
simulator binary):

```bash
.venv/bin/python -m scripts.rl.train \
  --sim-binary <BIN> \
  --run-config inputs/baselines/p0-smoke/run.ini \
  --output-dir outputs/rl-smoke-verification/rl \
  m-ppo --total-timesteps 16 --n-steps 16 --seed 1
```

Where to go next:

| Topic | Page |
|-------|------|
| `[rl]` keys, reward types, centralized control | [run.ini reference](@ref src_config_run_ini_reference) |
| Message, mode, mask, and action contract | [src/rl](@ref src_rl) |
| Observation, reward, and telemetry selection | [policy inputs](@ref src_rl_policy_inputs) |
| Train, inspect, evaluate, compare, experiment matrices | [scripts/rl](@ref scripts_rl) |
| Benchmark, tuning, SLURM, fetch | [scripts/rl/ops](@ref scripts_rl_ops) |

### Placement baselines {#readme_run_baselines}

| Key | Type / unit | Default | Mode |
|---|---|---|---|
| `controlled_nodes` | `all` or comma-separated node ids | required when RL is enabled | centralized selector |
| `max_controlled_nodes` | int, slot count `M` | `0` (auto-size to the resolved count), max `64` | centralized |
| `action_profile` | enum | `move_2d` (only accepted value) | centralized |
| `decision_interval_s` | seconds | `0` (means `tick_s`); must be an integer multiple of `tick_s` | centralized |

`controlled_nodes` selects `MultiDiscrete([5]*M)` with `4:hold`.
Obsolete `controlled_node_id`, `action_type`, and `arrival_threshold_m` keys are
configuration errors.

`all` selects eligible nodes in file order, excluding the active traffic gateway. Jammers live in
`jammers.json`, are never mesh nodes, and can never be controlled — even if a
jammer's `id` equals a node's `id`.

In centralized mode `reward_type = all_links_los` is the conjunction over every
controlled node (`+1` only if each one has at least one peer link and all of
them are LOS), and the reward reported per decision is the mean of the per-tick
rewards over scored ticks in that decision window. Decisions continue during
warmup; scoring starts at `time_s >= warmup_s`, and an unscored window returns zero.

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
component, a weight count that does not match the components, or invalid input
parameters fails before the simulator starts. Configurable scales and thresholds
are documented in [policy-inputs.md](src/rl/policy-inputs.md#configurable-service-and-geometry-inputs).

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
In centralized mode, movement limits and action validity are therefore decided
once, in C++, and Python never re-derives them. (Legacy single-node mode builds
its `Discrete(7)` mask in Python from the `[rl]` bounds.)

#### Model lifecycle

Four commands cover a centralized run from configuration to evaluation. Run
them from `scratch/mesh-sim/`. All but `inspect_model` need a built simulator binary.
Validation checks the proposed run; training saves a model and its manifest;
inspection checks those saved files; evaluation loads the model and runs new
episodes. The [lifecycle test map](src/rl/policy-lifecycle-tests.md) gives the
purpose and expected result of each focused check.

Check a configuration before spending simulator time. Without `--launch` every
check is static (no simulator process); `--launch` additionally starts the
simulator under `<output-dir>/validate/`, resets once, and reports the live
contract. It does not complete an episode:

```bash
.venv/bin/python -m scripts.rl.validate_config \
  --sim-binary <BIN> \
  --run-config inputs/baselines/building-bypass-smoke/run.ini \
  --output-dir outputs/bypass-validate --launch --json
```

Train with bounded checkpoints and a masked during-training evaluation:

```bash
.venv/bin/python -m scripts.rl.train \
  --sim-binary <BIN> \
  --run-config inputs/baselines/building-bypass-smoke/run.ini \
  --output-dir outputs/bypass-train \
  m-ppo --total-timesteps 1024 --n-steps 128 --seed 1 \
  --checkpoint-every-steps 512 --keep-checkpoints 2 \
  --eval-every-steps 256 --eval-episodes 1 --eval-seed 2
```

`--checkpoint-every-steps 0` (the default) disables checkpoints,
`--eval-every-steps 0` (the default) disables the evaluation callback, and
`--keep-checkpoints` (default 3) prunes the oldest checkpoints. `--eval-seed`
defaults to the training seed + 1. The units are SB3 timesteps, which equal
policy decisions here because training uses one environment.
[`callbacks.py`](scripts/rl/agents/callbacks.py) wires SB3's checkpoint
callback (with bounded retention) and `MaskableEvalCallback` (masked,
deterministic evaluation on a separate environment and seed). The latter saves
`best_model.zip` when mean evaluation reward improves; neither callback
changes the training reward or action rules.

Summarize a finished (or failed) run without loading the model:

```bash
.venv/bin/python -m scripts.rl.inspect_model --run-dir outputs/bypass-train
```

Add `--json` if you need machine-readable output. This command reads the
manifest and saved files; it does not load or run the policy. It prints status,
seed and seed source, control mode, the contract shape, selection, observation
and reward schema digests, scenario digests, every model
file with `exists`/`digest_ok`, the evaluation settings, and recorded versus
installed package versions. Exit 0 means the manifest is readable and every
recorded model file is present with a matching digest; exit 2 means a model file
is missing or its digest differs; exit 1 means the manifest is missing or
unreadable.

Evaluate a saved model against the `hold` and seeded `random_valid` baselines:

```bash
.venv/bin/python -m scripts.rl.evaluate \
  --sim-binary <BIN> \
  --run-dir outputs/bypass-train \
  --output-dir outputs/bypass-eval \
  --seeds 11,12,13 --policies model,hold,random_valid
```

`model` uses deterministic MaskablePPO predictions under the live action mask;
`hold` stops every controlled node; `random_valid` chooses uniformly among
each position's valid actions, restarting its random generator from each
episode seed. [`bundle.py`](scripts/rl/policy/bundle.py) treats the training
manifest plus a chosen final, best, or checkpoint ZIP as a saved model bundle,
not a new archive.
It checks run status and the selected ZIP's recorded digest before loading;
[`compat.py`](scripts/rl/policy/compat.py) then checks the live scenario and
policy contract.
`geometric` and `optimization` are placement baselines: `hold` on a layout
planned once before any episode runs (see
[Placement baselines](#placement-baselines)). They are not in the default
`--policies` list, and they require `[baseline] movable_nodes` and `[rl]
controlled_nodes` to name the same nodes (or both `all`), so no RL slot outside
the plan is frozen; otherwise preparation fails and no episode runs.

`--model` selects `final` (default), `best`, or `checkpoints/<file>.zip`. With
`--run-dir` the run config, band, and selection come from the training manifest;
`--run-config`/`--band` may override them. The scenario check always runs for
the model; an override may cause a mismatch.
`--seeds` accepts comma-separated seeds and inclusive ranges, so
`--seeds 301-303,310` is the same as `--seeds 301,302,303,310`. `--label <name>`
names the experiment row an evaluation belongs to, which is how
`scripts.rl.compare` recognizes evaluations of independently trained models as
one group.
Evaluation writes `eval_manifest.json` plus one `<policy>/episode-NNNN/`
directory per policy and seed, and refuses an `--output-dir` inside the training
run. The manifest is rewritten after every episode, so a seed whose simulator
dies mid-episode leaves the records of the seeds before and after it intact; its
own record keeps the episode directory and the partial return but reports every
metric as `null`, because a partial window spans less time than a full episode.
Manifest `status` is `completed` when every expected episode completed,
`partial` when at least one episode completed and at least one did not, and
`failed` when the evaluation aborted or nothing completed.
Exit 0 means every episode completed with no revalidated slots and no
masked actions, exit 2 means the episodes completed but one of those counters is
non-zero, and exit 1 means an error or an episode that did not complete.

`eval_manifest.json` is version 2. Beyond the version-1 fields it records
`label`; `seed_roles` (training seed, model-selection seed, held-out seeds, any
overlap, whether the overlap was allowed, and whether the result is held out);
`training`, copied from the training manifest (algorithm, seeds, scenario
digests, hyperparameters); `metric_source`; and `episodes_expected` /
`episodes_completed`. Every policy now holds exactly one record per requested
seed in seed order, with `status` `completed`, `failed`, or `not_run` (a seed the
evaluation never reached), and each record adds `error`,
`metrics.unroutable_fraction`, and a `summary_json` path that is only a pointer
and is never parsed.
Inspect `eval_manifest.json` for returns, per-seed metrics, and action
validity counts; each episode's `steps.jsonl` has the decision trace.

`train_manifest.json` is version 6. Besides the existing run identity it
records `status`/`error`, `algorithm`, `seed` and `seed_source`, `control_mode`,
the live `contract`, the resolved `selection`, `observation_schema` and
`reward_schema` (with their SHA-256), `scenario_identity` (SHA-256 of the
`run.ini`, `nodes.json`, and — when configured — `buildings.json` and
`jammers.json`), `model_path`/`model_sha256`, `best_model_path`/
`best_model_sha256`/`best_mean_reward`, a `checkpoints` list of
`{path, sha256, num_timesteps}`, the `evaluation` block (cadence, episodes,
seed, output dir, log path) or `null`, `hyperparameters`, `package_versions`,
`python_version`, and `platform`. Models trained with older tooling carry an
older `manifest_version` and are not loadable: retrain with the current tooling.

Seed discipline: keep the training seed, the during-training evaluation seed,
and the standalone evaluation seeds disjoint. With `model` among `--policies`,
`scripts.rl.evaluate` refuses to start when a requested seed is the training
seed or the recorded model-selection seed, naming each seed and its role.
`--allow-seed-overlap` downgrades that refusal to a stderr `WARNING:` line and
records `seed_roles.held_out: false`, which marks the evaluation as not held out
and excludes it from across-run aggregates.
The during-training evaluation runs in its own environment, seed, and output
directory (`<output-dir>/eval/`)
and contributes no gradient steps. Standalone evaluation never informs model
selection — only the during-training callback writes `best_model.zip`.

Loading a model checks compatibility in a fixed order and stops at the first
failure: structural contract fields, then the observation schema, then the
reward schema, then scenario identity. `--allow-different-scenario` relaxes only
the last step, including differences in scenario-input file digests. It never
bypasses the model ZIP's digest, structural, observation-schema, or reward
checks, and the evaluation manifest records the run as `overridden`. Checks
that pass mean the shapes and declared meanings match; they are never evidence
that a policy transfers to another scenario.

`inputs/baselines/building-bypass-smoke/` is a diagnostic fixture: two drones
with one building between them. Going north or south around it is the fastest
route to LOS. Action masks check bounds, not buildings, so moving west through
the building also reaches LOS once x < 90. Its `run.ini` header records the
geometry and the expected hold and north-moving numbers. It is a smoke fixture
for the lifecycle tools, not a benchmark or a training campaign.

#### Comparing policies and running an experiment matrix

`scripts.rl.compare` turns finished evaluations into paired
model-minus-baseline statistics, and `scripts.rl.experiment` expands a named
matrix into the train, evaluate, and compare steps that produce them.

```bash
.venv/bin/python -m scripts.rl.compare \
  --eval-dirs outputs/bypass-eval --output-dir outputs/bypass-compare

.venv/bin/python -m scripts.rl.experiment plan \
  --matrix inputs/experiments/bypass-smoke-matrix.json \
  --output-root outputs/bypass-matrix --sim-binary <BIN>

.venv/bin/python -m scripts.rl.experiment run \
  --matrix inputs/experiments/bypass-smoke-matrix.json \
  --output-root outputs/bypass-matrix --sim-binary <BIN>

.venv/bin/python -m scripts.rl.experiment status --output-root outputs/bypass-matrix
```

`compare` takes exactly one of `--eval-dirs DIR [DIR …]` or `--plan
experiment_plan.json`, plus a required `--output-dir` that must not already
contain a training or evaluation manifest. `--baselines a,b` restricts the
baselines (the default is every non-`model` policy present) and `--json` prints
`comparison.json` instead of the summary lines. It reads only
`eval_manifest.json` files, refuses version-1 manifests, and writes
`episodes.csv` (one row per evaluation directory, policy, and seed — the raw
record every aggregate traces back to) and `comparison.json`. Neither file
carries a timestamp, so repeating the same command reproduces byte-identical
output. A listed directory without a readable manifest becomes a
`missing_evaluations` entry instead of a crash.

The matrix names the scenario in `run_config`, lists independent training,
model-selection, and held-out evaluation seeds under `seeds`, and specifies
training and evaluation budgets. Each `rows` entry chooses one observation
preset, action profile, and weighted reward; rows are explicit combinations,
not an automatic Cartesian product. Add `--rows local-delivery` to both `plan`
and `run` to select just that row; they must use the same filter for one output
root.

`experiment` writes `experiment_plan.json` under `--output-root` and keeps the
runs beside it: `train/<row>/train-seed-<S>/`, `eval/<row>/train-seed-<S>/`, and
`comparison/{episodes.csv,comparison.json}`. `--rows` selects named rows. `run`
executes the pending steps sequentially in fresh processes and always runs
`compare` last, so a missing run is reported rather than hidden. Each step's
state comes from its manifest alone — `pending`, `done`, `partial`, or `blocked`
— and a blocked step is never re-run automatically: move or delete its
directory. Re-planning the same `--output-root` with a different matrix, binary,
or `--rows` is refused; use a new root.

Two kinds of interval are reported, and they never share a label. The first is
across evaluation seeds for one saved model: the model and a baseline are paired
seed by seed inside one evaluation, and the interval describes how the paired
difference varies over held-out scenario seeds with the model held fixed. The
second is across independently trained models: evaluations that share a `--label`
contribute one mean difference each, over the seeds common to all of them, and
the interval describes run-to-run variation — where the training seed currently
sets both the PPO initialization and the training scenario seed, so the two
cannot be separated (TODO-RL-SEEDS-1). A single evaluation seed, or a single
training run, yields a value and no interval, with `interval_omitted` saying
why.

Every comparison reports `n_expected` (the requested seeds) beside `n_used` (the
pairs that both policies completed), and lists each dropped seed with a reason
per side, such as `model:failed`, `hold:metric_null`, or `random_valid:not_run`.
A `null` metric is never read as zero. `zero_variance` marks a zero-width
interval so a deterministic scenario is not mistaken for certainty. Exit 0 means
every expected evaluation was found, complete, held out, and free of health
counters; exit 2 means the outputs are complete but a health counter is non-zero
or an evaluation is not held out; exit 1 means the comparison is incomplete
(outputs are still written) or was refused (nothing is written).

`delivery_ratio` is the primary metric; `connectivity`, `los_fraction`, and
`unroutable_fraction` follow. `return` is compared only inside one evaluation,
where every policy shares one reward definition, and is flagged
`comparable_across_reward_definitions: false` — two rows with different reward
components produce returns on different scales, so comparing them would be
meaningless.

All statistics come from the RL telemetry window, which every output states as
`metric_source`. Nothing is read from a run's `summary.json`, because that file
excludes warmup ticks while the RL window does not; until that mismatch is
resolved (see the RL-reward warmup entry in `TODO.md`), mixing the two sources in
one table would be wrong whenever `warmup_s > 0`. The intervals are t intervals
that assume approximately normal paired differences; on a bounded ratio with few
seeds they are approximate, not exact.

`inputs/experiments/bypass-smoke-matrix.json` is diagnostic, not a benchmark:
four explicit rows around one anchor on the bypass fixture with smoke-sized
budgets. It exercises the harness; it is not evidence that a policy learns.
For the purpose, input, and expected output of each comparison and matrix test,
see [Policy comparison tests](src/rl/policy-comparison-tests.md).

#### Benchmarking, tuning smoke, and cluster runs

`scripts.rl.ops` runs a planned matrix elsewhere: it measures one
`(row, training seed)` task, searches the PPO knobs that are already wired,
submits the plan as a SLURM array plus one comparison job, and copies results
back. Every schema, state, and refusal is documented in
[`scripts/rl/ops/README.md`](scripts/rl/ops/README.md); the cluster commands are
validated against a fake scheduler only, and `fetch` against a fake `rsync`.

Benchmarking is a timed dress rehearsal: `run` actually trains and evaluates
one planned `(row, training seed)` task, measuring elapsed time and the memory
used by its Python and simulator processes. `estimate` scales those measurements
to a target matrix without running it. Plan into a fresh output root first;
the estimate is arithmetic on the measured machine and records
`is_cluster_estimate: false`:

```bash
.venv/bin/python -m scripts.rl.experiment plan \
  --matrix inputs/experiments/bypass-smoke-matrix.json \
  --output-root outputs/bench/bypass-smoke --sim-binary <BIN> --rows local-delivery

.venv/bin/python -m scripts.rl.ops.benchmark run \
  --output-root outputs/bench/bypass-smoke --task-index 0

.venv/bin/python -m scripts.rl.ops.benchmark estimate \
  --benchmark outputs/bench/bypass-smoke/benchmark/task-0000.json \
  --target-matrix inputs/experiments/bypass-smoke-matrix.json \
  --safety-factor 2.0 --output outputs/bench/bypass-smoke/benchmark/estimate.json
```

Run a small Optuna study over `n_steps`, `gamma`, and `ent_coef` for one matrix
row and training seed, after installing `requirements-tuning.txt`. Its objective
is one deterministic episode on the model-selection seed at a smoke budget, so
it exercises the plumbing and ranks nothing reliably:

```bash
.venv/bin/python -m scripts.rl.ops.tune \
  --study inputs/experiments/bypass-smoke-study.json \
  --output-root outputs/tune/bypass-smoke --sim-binary <BIN> --dry-run
```

Remove `--dry-run` only when ready to execute the trials; the preview launches
no training or simulator process.

Submit an already-planned output root to SLURM, one array element per
`(row, training seed)` plus one dependent comparison job. All cluster settings
come from a required config file (`scripts/rl/ops/cluster-config.example.json`),
and `status` only reads:

```bash
<venv>/bin/python -m scripts.rl.ops.cluster plan   --output-root R --cluster-config C
<venv>/bin/python -m scripts.rl.ops.cluster submit --output-root R --cluster-config C --dry-run
<venv>/bin/python -m scripts.rl.ops.cluster status --output-root R
<venv>/bin/python -m scripts.rl.ops.cluster resume --output-root R --cluster-config C
```

The `submit` line previews without submitting; remove `--dry-run` only after
checking the task table and rendered script. Add `--tasks 0` to start with a
single array task, or `--json` to `status` for machine-readable state. The
cluster [operations guide](scripts/rl/ops/README.md#cluster-runs) explains
receipts, recovery, cancellation, and each command's refusal rules.

Copy selected results from the run to this machine. Nothing local is ever
overwritten, and `fetch_manifest.json` records what arrived, marking unselected
categories `not_fetched` rather than missing:

```bash
.venv/bin/python -m scripts.rl.ops.fetch --remote user@host:/abs/output-root \
  --dest outputs/fetched/bypass-smoke --select comparison,manifests
```

### Placement baselines

`scripts/baselines/` plans the gateway-free geometric (greedy) and
optimization (annealing) placement baselines once, before the simulation,
selected by a `[baseline]` INI section or by the `geometric` and
`optimization` evaluation policies. Every candidate layout is scored by the
same binary's `--channel-query` mode, so planning uses the scenario's own
band, gains, buildings and jammers; no extra Python packages are needed.
Standalone:

```bash
.venv/bin/python -m scripts.baselines.runner \
  --sim-binary <BIN> --run-config <INI> --seeds 1,2
```

The [zero-cost/penalized walkthrough](scripts/baselines/walkthrough.md) includes
training, held-out evaluation, comparison and saved diagnostics. Active placement
requires a dedicated `planning_seed`, separate from evaluation seeds.

The [placement-baseline guide](scripts/baselines/README.md) covers the keys
(including movement penalties in m²), the optional mapping file, the objective,
the evaluation ownership rule, the direct-run guard, outputs, migration from
the gateway/RF-file version, the rectangle-only geofence limit, and which files
may not be committed.

## Verify {#readme_verify}

From `scratch/mesh-sim/tests/`:

```bash
make test                                   # standalone unit tests
MESH_SIM_BIN=<BIN> make integration         # 19 real-binary CLI checks (see tests/README.md)
```

`make test` stops at the first failing suite. To inspect every suite despite a
failure, run `make -C unit/config test`, `make -C unit/eval test`,
`make -C unit/routing test`, and `make -C unit/traffic test` separately.
The [RL test map](@ref scripts_rl_tests) lists each centralized-control
test, its input, and its expected output.

For a quick check without cloud reference data, run two tiny synthetic
simulations and check output contracts and same-seed repeatability. Run from
`scratch/mesh-sim/`:

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
  --out outputs/baseline-regression/<name>
```

See [scripts/validation](@ref scripts_validation) for the suite's cases, skip
behavior, and exit codes.

## Output {#readme_where_output_lands}

| Invocation | Where |
|---|---|
| Direct run | `<output-dir>/run.log`, `<output-dir>/inputs/` (archived scenario files), `<output-dir>/seed-N/{positions,links,rx-power,mcs,flows,routes}.csv` + `summary.json` |
| Sweep point / validation scenario | Same layout, plus `console.log` (launcher-captured stdout/stderr; absent for direct runs) |
| RL training and evaluation | Manifests, models, and `episode-NNNN/` folders; see [scripts/rl](@ref scripts_rl_output) |

With no `[output] dir`, the simulator auto-generates
`outputs/YYYY-MM/DD/HH-MM-SS/`. For the direct-run CSV columns, see the
[I/O guide](@ref src_io_output).

## Conventions {#readme_conventions}

- Python tools run as modules from `scratch/mesh-sim/`
  (`python -m scripts.<pkg>.<module>`) because they use package-relative imports.
- Python tools that launch the simulator take `--sim-binary <BIN>`; they never
  build it.
- `run.log` "Resolved config" is the source of truth for what a run used.
- Scenario inputs are archived into every output folder for reproducibility.
- Generated `outputs/` and `docs/html/` are git-ignored.
- Code comments follow Doxygen style; Python uses `##` blocks and C++ uses
  `/** ... */`.

## Dependencies {#readme_dependencies}

- **Simulator:** ns3-mmwave, CMake, and a C++ compiler (not installed by the
  helper scripts).
- **Python tools:** Python 3 and the packages in `requirements.txt`; Optuna from
  `requirements-tuning.txt` only for tuning.
- **Data:** field data under `data/` for the scenario pipeline; the cloud baseline
  bundle for the regression suite.
- **Docs:** `doxygen` (and `graphviz` for diagrams).

## Accessing the documentation {#readme_docs}

This documentation is generated by **Doxygen** into a static HTML site under
@c scratch/mesh-sim/docs/html/. It is a set of local files; there is no server
to start.

### Generating the site {#readme_docs_build}

From @c scratch/mesh-sim/docs/ (where the @c Doxyfile lives; its input paths are
relative to that directory):

```bash
cd scratch/mesh-sim/docs
doxygen Doxyfile
```

This (re)builds @c docs/html/. Re-run it after changing source comments or these
README pages. If @c doxygen is not installed:

```bash
sudo apt install doxygen graphviz     # Linux (graphviz enables the diagrams)
brew install doxygen graphviz         # macOS
```

### Opening the site {#readme_docs_open}

Open the generated entry page in any browser:

```bash
# Linux
xdg-open scratch/mesh-sim/docs/html/index.html
# macOS
open scratch/mesh-sim/docs/html/index.html
# Windows
start scratch/mesh-sim/docs/html/index.html
```

Or paste the absolute path into the browser's address bar, for example
`/home/<USER>/ns3-mmwave/scratch/mesh-sim/docs/html/index.html`
(replace @c USER and the repo path with yours). This @c index.html is this
Overview page; use the navigation tree / search at the top to reach the module
pages and the per-file API docs.

## About {#readme_about}

This sim is being worked on by the University of Massachusetts's ACNL.

The simulator-scored placement engine and its owned parameter sections are
documented in the [engine workflow](scripts/baselines/planners/README.md). Its
API is available in this review; baseline CLI integration follows in #26.
