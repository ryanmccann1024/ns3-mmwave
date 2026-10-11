# Experiment operations

Tools around an existing `experiment_plan.json`. Create the plan before executing a task or measuring it.

## Module map

| Owner | Responsibility |
| --- | --- |
| `tasks.py` | Task mapping and filesystem state; imports the experiment policy owner. |
| `task_execution.py` | Execute tasks/comparison and write operational records. |
| `process.py` | Launch, stop and reap experiment process groups, including descendants. |
| `measurement.py` | Task timing, process-tree sampling and completion evidence. |
| `estimation.py` | Estimate eligible matrices from complete measurements. |
| `../tuning/config.py` | Study settings and distributions. |
| `../tuning/trainer.py` | Supported trainer adaptation and model-selection objective. |
| `../tuning/study.py` | Pinned Optuna sampling and seeded sampler state. |
| `../tuning/driver.py` | Trial execution and explicit recovery. |
| `../tuning/artifacts.py` | Versioned trial/study records and atomic checkpoints. |
| `../cluster/config.py` | Cluster resource validation. |
| `../cluster/jobs.py` | Scheduler arguments and rendered scripts. |
| `../cluster/slurm.py` | Scheduler access and response parsing. |
| `../cluster/receipts.py` | Receipt layout, account ownership and operation locks. |
| `../cluster/reconcile.py` | Filesystem/scheduler state and termination evidence. |
| `../cluster/recovery.py` | No-ID recovery and checked assertions. |
| `../cluster/submission.py` | Task and compare-only submission workflows. |
| `../cluster/operations.py` | Status, cancellation and local/scheduled comparison. |
| `../cluster/plan.py`, `reporting.py` | Cluster preflight, task table and previews. |
| `../../artifact_io.py` | Shared atomic JSON I/O, content hashes and UTC timestamps. |

`run_task.py`, `benchmark.py`, `tune.py`, and `cluster.py` parse commands and delegate.
The old `ops/slurm.py`, `receipts.py` and `reconcile.py` imports delegate to
the cluster owners for existing callers. Writing
an operational record belongs in operations; it is not part of argument parsing.
The command paths and existing task/tuning helper imports remain available.

## Task unit

One array task is one `(row, training seed)` pair: its `train` step followed by
its `evaluate` step, serially, in one array element. The task index is the
0-based position of the train step among the plan's train steps, and the task
id is the train step id without its `train/` prefix, for example
`local-delivery/train-seed-101`. `build_tasks` pairs each train step with the
evaluate step whose `needs` names it and raises `ValueError` when a pair or the
compare step is missing.

An evaluation needs only its own training run, and evaluation seeds cannot be
split across tasks (`scripts.rl.compare` requires one manifest per label with
sorted seeds), so one element per pair keeps each task self-contained.

### Why the compare job depends with afterany

The comparison is one separate job submitted with
`--dependency=afterany:<every active array job id>`. Correctness comes from a
filesystem prerequisite check inside the compare runner, not from scheduler
exit codes: `afterok` on an array with one failed element never clears, even
after that element is resubmitted as part of a later array. `afterany` only
orders the jobs; `compare_prerequisites` decides whether a comparison may be
written at all.

## Runner: run_task.py

```bash
.venv/bin/python -m scripts.rl.ops.run_task --output-root R --task-index I [--record PATH]
.venv/bin/python -m scripts.rl.ops.run_task --output-root R --compare [--allow-incomplete] [--record PATH]
```

Exactly one of `--task-index` or `--compare` is required;
`--allow-incomplete` applies to `--compare` only.

Task mode, in order:

1. Train `done` is skipped. `pending` is executed as a fresh
   `python -m <module> <args>` process from the mesh root. Any other state
   prints the step's own retry detail and exits 1 without touching the
   directory.
2. A train exit code that is not tolerated exits 1; the evaluation is not
   attempted.
3. Evaluate `done` exits 0. `partial` or `blocked` prints the detail and exits
   1. `pending` is executed; a tolerated exit gives 0, anything else 1.

Compare mode refuses by default when any evaluation is missing or partial: it
prints each offending step id, **writes nothing at all — no comparison output
and no `--record` file** — and exits 1. With `--allow-incomplete` it executes
the compare step and prints the step id, the raw exit code, and the state read
back from `comparison.json`.

### Exit-code mapping

`tolerated(kind, code)` accepts `0` for train, `0` and `2` for evaluate, and
`0` and `2` for compare, matching the tolerated codes of the corresponding CLIs
(a `2` means health counters or a not-held-out evaluation, not a failure).
A tolerated `2` therefore makes the runner exit 0, so `sacct` does not show a
healthy task as FAILED, while the raw code survives in the record.

Task steps run in managed process groups. Interruption, wait failure, and
post-launch recording failure stop/reap the group before returning. SIGINT and
SIGTERM return 130 and 143. Task resume skips finished steps; it does not resume
a training checkpoint. Use the documented `scripts.rl.train --resume` workflow
for that, then rerun the task so evaluation can follow completed training.

### Record schema (`--record`)

```json
{"record_version": 1, "mode": "task|compare", "task_index": 0, "task_id": "row/train-seed-101",
 "host": "...", "started_at": "...", "ended_at": "...",
 "steps": [{"id": "...", "kind": "train", "action": "executed|skipped",
            "exit_code": 2, "tolerated": true}],
 "exit_code": 0}
```

`task_index` and `task_id` are `null` in compare mode. A skipped step records
`exit_code: null` and `tolerated: null`.

## First task through comparison

From `scratch/mesh-sim/`, create a plan using a previously built `<BIN>`, inspect
it, execute its first task, and inspect the resulting training/evaluation manifests:

```bash
.venv/bin/python -m scripts.rl.experiment plan \
  --matrix inputs/experiments/bypass-smoke-matrix.json \
  --output-root outputs/ops-walkthrough --sim-binary <BIN>
.venv/bin/python -m scripts.rl.experiment status --output-root outputs/ops-walkthrough
.venv/bin/python -m scripts.rl.ops.run_task --output-root outputs/ops-walkthrough \
  --task-index 0 --record outputs/ops-walkthrough/task-0000.json
.venv/bin/python -m scripts.rl.experiment status --output-root outputs/ops-walkthrough
```

The task table follows train-step order in `experiment_plan.json`. Execute the
remaining task indices, then run `scripts.rl.ops.run_task --output-root
outputs/ops-walkthrough --compare`. Inspect `comparison/comparison.json` and
`comparison/episodes.csv`; incomplete prerequisites are refused unless explicitly
allowed. A task record preserves raw exits even when health-counter exit 2 is
tolerated. None of these examples claims that a smoke model has learned.

## Benchmark

This is a measurement run, not a dry run: it executes one planned train step
and its evaluation, then records wall-clock time and sampled memory. Use a
small representative task first; the estimate does not measure the target
matrix or predict queue wait time.

```bash
.venv/bin/python -m scripts.rl.experiment plan \
  --matrix inputs/experiments/bypass-smoke-matrix.json \
  --output-root outputs/bench/bypass-smoke --sim-binary <BIN> --rows local-delivery

.venv/bin/python -m scripts.rl.ops.benchmark run \
  --output-root outputs/bench/bypass-smoke --task-index 0

.venv/bin/python -m scripts.rl.ops.benchmark estimate \
  --benchmark outputs/bench/bypass-smoke/benchmark/task-0000.json \
  --target-matrix <matrix.json> --safety-factor 2.0 \
  --output outputs/bench/bypass-smoke/benchmark/estimate.json
```

`run` writes benchmark schema 2 with each step's manifest status. `estimate`
requires schema 2, tolerated exits, completed train/evaluation manifests, and all
expected evaluation episodes. Failed/partial measurements cannot produce an
estimate; schema 1 measurements must be repeated. Estimates use schema 2 and
the configured evaluation cadence, including `eval_episodes`.

`run` needs both step directories `pending`, refuses an existing
`benchmark/task-NNNN.json`, launches each step in its own process group, applies
the same exit tolerance as the runner, and stops after a train that is not
tolerated. While a step runs, a sampler thread takes one sample immediately
after spawn and then every `--sample-interval-s` (default 0.5) seconds: it
parses `ps -A -o pid=,ppid=,rss=`, walks the parent chain from the step's pid,
and keeps the peak summed RSS, the peak process count, and the largest single
process RSS over the tree. Process-tree sampling is used because a training step
can have the Python process and up to two simulator subprocesses alive at once.

RSS means *resident set size*: memory currently resident in RAM, reported here
in KiB. `peak_tree_rss_kb` is the largest sampled sum across the task's Python
process and its descendants, not a precise peak of unique memory; shared pages
may be counted more than once.

**Sampling misses spikes shorter than the interval**; the record says so in
`sampling.note`, and the safety factor of the estimate is the human's lever for
that. A `ps` failure sets the three memory fields to `null` and records
`measurement_error`; timing is still measured and the benchmark file is still
written.

`benchmark/task-NNNN.json` carries `benchmark_version`, `measured_at`, `host`
(`system`, `machine`, `cpu_count`, `python_version`), `plan`
(`root`, `matrix_name`, `matrix_sha256`), `task_index`, `task_id`, `sampling`
(`method: ps-process-tree`, `interval_s`, `note`), `package_versions`, and one
entry per step with `id`, `kind`, `exit_code`, `tolerated`, `wall_seconds`,
`peak_tree_rss_kb`, `peak_process_count`, `peak_single_process_rss_kb`, and
`samples`. Train steps add:

- `requested_timesteps`, `n_steps`, and `effective_timesteps`
  (`ceil(requested / n_steps) * n_steps`, because rollouts run whole);
- `seconds_per_timestep` = wall ÷ effective, which **includes** the
  model-selection evaluations and the PPO updates;
- `scenario_identity`, `selection`, `eval_every_steps`, `eval_episodes`;
- `training_episodes` / `selection_episodes` and `episode_seconds_sum` from the
  episode manifests;
- `non_episode_seconds` = wall − episode sum. This is Python start-up, PPO
  updates, and the gaps between simulator launches together; **it is not a
  launch-overhead figure** and must not be labelled as one.

Evaluate steps add `episodes_expected`, `episodes_completed`, and
`seconds_per_episode`.

`estimate` runs nothing and is arithmetic only; `--safety-factor` and
`--output` are required. A target row is estimated only when its scenario
matches the benchmarked one — compared by the `*_sha256` fields of
`scenario_identity`, because `run.ini` paths differ between machines — and its
`n_steps` and evaluation cadence match the measured ones. Otherwise the row gets
`per_task_seconds: null` with `reason` `"different scenario"` or
`"different cadence"`. For a matching row:

```
per_task_seconds = seconds_per_timestep × effective target timesteps
                 + seconds_per_episode × policies × held-out seeds
```

A row whose observation or reward selection differs but whose scenario and
cadence match is still estimated, with `selection_differs: true` and a warning
that its Python and agent work was not measured. The output also records the
per-row safety-scaled seconds and `HH:MM:SS`, the task count, the summed serial
seconds, the memory estimate — `memory.peak_tree_rss_kb` is the largest measured
`peak_tree_rss_kb` over the benchmark's steps, and `with_safety_kb` is that value
times the safety factor; both are `null` only when no step's memory was measured
— and the assumptions as data:
`{"linear_in_timesteps": true, "measured_on": "<system> <machine>",
"is_cluster_estimate": false}`. A measurement taken on a laptop, for example on
macOS, is never a cluster estimate; there is no queue, ETA, or throughput
figure anywhere in the output.

## Tuning smoke

```bash
.venv/bin/python -m pip install -r requirements-tuning.txt

.venv/bin/python -m scripts.rl.ops.tune --study inputs/experiments/bypass-smoke-study.json \
  --output-root outputs/tune/bypass-smoke --sim-binary <BIN> --dry-run

.venv/bin/python -m scripts.rl.ops.tune --study inputs/experiments/bypass-smoke-study.json \
  --output-root outputs/tune/bypass-smoke --sim-binary <BIN>
```

Exit 0 means every trial produced an objective; exit 1 means a refusal, or that
at least one trial failed — records are still written in that case.

### What a trial is, and what it is not

- Distinct trials are **different configurations, not replicate seeds** of one
  comparison group. `scripts.rl.compare` builds an across-runs group from
  several training seeds of *one* configuration; the way to use a tuning result
  is to freeze one configuration by hand, then train it on several training
  seeds through a matrix and evaluate it on held-out seeds.
- The example objective uses one deterministic episode on one model-selection
  seed at a smoke budget; configured `eval_episodes` is recorded in the objective. **It ranks nothing reliably and is no evidence of learning.**
- Rows with different reward definitions produce returns on different scales, so
  each needs its own study.
- The numbers in `inputs/experiments/bypass-smoke-study.json` exist to exercise
  the code path on the smoke fixture. They are not recommended ranges.

### Study spec

```json
{
  "study_version": 1,
  "name": "bypass-smoke-study",
  "description": "Plumbing smoke: three tiny trials; values are not recommendations.",
  "matrix": "inputs/experiments/bypass-smoke-matrix.json",
  "row": "local-delivery",
  "training_seed": 101,
  "trainer": "maskable_ppo",
  "sampler": {"type": "tpe", "seed": 7, "n_startup_trials": 10,
              "n_ei_candidates": 24, "multivariate": false},
  "n_trials": 3,
  "search_space": {
    "n_steps":  {"type": "categorical", "choices": [32, 64]},
    "gamma":    {"type": "float", "low": 0.90, "high": 0.99},
    "ent_coef": {"type": "float", "low": 0.001, "high": 0.05, "log": true}
  }
}
```

These are different seeds: `training_seed` fixes the PPO and training-scenario
randomness for every trial in this study. `sampler.seed` fixes Optuna's sequence
of candidate hyperparameters; it is **not** passed to PPO or the simulator.
The matrix's `model_selection` seed scores each trial, and held-out seeds are
not used for tuning. Vary training seeds later to test whether the selected
configuration is robust, rather than treating Optuna trials as independent
training-seed replicates.

Every key is validated before anything is launched:

- Unknown keys at any level are refused, naming the valid ones. A relative
  `matrix` path is resolved against the mesh root.
- `search_space` must be non-empty and its keys a subset of `n_steps`, `gamma`,
  and `ent_coef` — the supported search parameters declared by the trainer owner today.
  `total_timesteps` gets its own message: the budget is fixed per study and
  comes from the matrix. Any other name is reported as not wired, pointing at
  the constructor and validation owner in `agents/config.py`.
- `n_steps` is `int` or `categorical` with distinct integer choices ≥ 2;
  `gamma` is a float range inside `(0, 1]`; `ent_coef` is a float range with
  `low ≥ 0`; `log: true` requires `low > 0`; every range needs `low < high`.
- `row` must exist in the matrix and `training_seed` must be one of the
  matrix's `seeds.training`, which `load_matrix` has already proven disjoint
  from the model-selection and held-out seeds.
- The matrix must set `seeds.model_selection` and `training.total_timesteps`,
  and satisfy `0 < training.eval_every_steps <= total_timesteps` — otherwise no
  model selection ever runs and every objective would be `null`.
- `trainer` defaults to `maskable_ppo`; unsupported trainers are refused.
- `sampler.type` is `tpe`; seed is an integer in [0, 2**32 - 1]. Startup/candidate
  counts are positive integers; `multivariate` is boolean. Defaults are 10,
  24, and false. `n_trials` is a positive total attempt budget; no fixed cap of
  50 is imposed. Failed/interrupted trials consume an attempt too.
- An `--output-root` already holding `study_manifest.json` or `trials/` is
  refused for a fresh run; explicit `--resume` loads the recovery checkpoint.
- `--sim-binary` is always required, and must be an existing executable file
  unless `--dry-run`.

### Trials, objective, and sampler

For each trial the sampled values replace the same keys in a copy of the
matrix's `training` block, the copy's `seeds.training` becomes just the study's
training seed, and `build_plan` supplies the train step. Only that step's
module, args, and output directory are used; no plan file is written. The trial
command is therefore byte-for-byte the command a matrix with those values would
run, carrying `--eval-seed <model_selection>`; a command whose `--seed` or
`--eval-seed` value is a held-out seed is refused — the guard reads only the
value following each of those two flags, not every token of the command. Trials run sequentially as subprocesses.

The sampler uses the resolved spec settings recorded in the manifest. Until
`n_startup_trials` completed objectives exist, draws are startup samples. The
three-trial example remains a plumbing smoke, not adaptive search. `--dry-run`
asks `min(n_trials, n_startup_trials)`
times without telling and prints exactly those parameter sets and commands; for
a larger `n_trials` it says the remaining trials depend on earlier objectives.
A dry run creates no output directory, record, training process, or simulator
process.

The objective is `train_manifest.json`'s `best_mean_reward`, maximized. A
non-zero training exit, an unreadable manifest, or a non-finite or `null` value
fails that trial with a recorded reason and the study continues.

### Outputs

```
<output-root>/study_manifest.json
<output-root>/study-checkpoint.bin
<output-root>/trials/trial-0000/trial.json
<output-root>/trials/trial-0000/train/<row>/train-seed-<S>/   (train.py's own output)
```

`trial.json` uses `trial_version: 2` and holds `number`, `params`, the configured
`training` block, `module`, `args`, `train_dir`, `state`
(`running`/`complete`/`failed`), `objective`, `failure`, `exit_code`, `started_at`, and
`ended_at`, and the launched process identity. Before command construction,
`training` is empty and command/path fields are unset; a construction failure
keeps that record with its reason.

`study_manifest.json` is rewritten atomically after every trial with
`study_manifest_version: 2`, `status` (`running`/`completed`/`failed`/`interrupted`), the `spec`
(path, sha256, body), the `matrix` (path, sha256, name), `row`, `seed_roles`
(`training`, `model_selection`, `held_out_used: false`), the `objective`
description, `sampler`, `fixed_training`, `optuna_version`,
`package_versions`, `python_version`, `platform`, `sim_binary`, the per-trial
records, `best`, `started_at`, `ended_at`, and `resume_events`. `best.training`
is the matrix training block with sampled values, ready to be copied by hand
into a new matrix file. Nothing edits a matrix automatically.

### Optuna pin

Optuna is pinned in `requirements-tuning.txt` and deliberately kept out of
`requirements.txt`: the training manifests record the direct dependency set, so
adding a tuner there would change every manifest and force the cluster venv to
carry a package no job imports. The study owner imports Optuna lazily; a missing
install or a version other than the pin is a refusal naming both versions and
the install command. Nothing else in this package imports Optuna, and no
cluster job does.


### Resume a study

```bash
.venv/bin/python -m scripts.rl.ops.tune \
  --study inputs/experiments/bypass-smoke-study.json \
  --output-root outputs/tune/bypass-smoke --sim-binary <BIN> --resume
```

The checkpoint atomically saves the Optuna study, seeded sampler, pending trial,
records and best configuration before refreshing JSON mirrors. Recovery loads
that locally created checkpoint and repairs mirrors. It preserves completed
trials and does not re-execute them. A pending trial with completed training is
reconciled; otherwise it is recorded as failed and the remaining attempts run.
The tuner does not automatically resume a training checkpoint or overwrite an
interrupted training directory. Completed studies launch nothing on resume.

A file lock permits one writer. If an interrupted trial's saved process group
may still exist, recovery refuses until it is stopped; resume runs on that
trial's original host. Inputs, scenario hashes, simulator bytes, Python/dependency
versions, and the Optuna pin must match. Changed settings require a fresh study.
Version 1 JSON-only studies have no sampler checkpoint and cannot be resumed.
`--resume` and `--dry-run` cannot be combined.

The checkpoint contains Python/Optuna serialized state from this run; retain it
with its JSON records and matching environment. JSON records alone cannot
restore seeded sampler continuation. See [Optuna's persistence guide](https://optuna.readthedocs.io/en/v5.0.0/tutorial/20_recipes/001_rdb.html).

### Add a trainer or parameter

The generic driver asks a trainer adapter to build a trial and read its objective.
`MaskablePpoTrainer` is the implementation available today. Another algorithm
needs an actual trainer/command and an adapter declaring its searchable parameter
types, validation, objective name/direction, and command construction. Register
it in `get_trainer`; do not add algorithm-name branches to the CLI/driver.

For more PPO parameters, wire the constructor, config validation, train CLI,
training provenance, compatibility/comparison grouping, and matrix translation
first. Then add the parameter to `agents.config.PPO_SEARCH_PARAMETERS`. The
existing separate study JSON provides ranges and choices; it cannot make an
unimplemented constructor parameter tunable. Cadence and training budgets stay
fixed within a study. Resolved runtime hyperparameters remain in each training
manifest.

Keep tuning/model-selection seeds separate from final evaluation. Copy the
selected training block into a new experiment matrix, freeze it, and use
independent training and held-out evaluation seeds. Trials of different
configurations are not replicate training runs.

See [the operations test map](../tests/ops-tests.md) for recovery, adaptive search,
process cleanup and estimate eligibility checks and their evidence limits.

## Cluster runs

Use one OS/SLURM user per output root. Before any receipt, task-table or
comparison mutation, the tool checks every receipt against the account obtained
from the OS user database, rather than `USER`/`LOGNAME`. A different owner is
a refusal before scheduler calls or writes; use that owning account or another
output root. The SLURM resource `account` is a billing/project choice and is not
this user identity. Read-only status queries each receipt's recorded owner;
limited scheduler visibility remains `unknown`. Version 1 receipts with an
owner remain readable; ownerless or unsupported receipts require human repair.

### Commands

```bash
# on the cluster, after the human built the binary and prepared the venv
<venv>/bin/python -m scripts.rl.experiment plan --matrix M --output-root R --sim-binary /abs/BIN
<venv>/bin/python -m scripts.rl.ops.cluster plan   --output-root R --cluster-config C
<venv>/bin/python -m scripts.rl.ops.cluster submit --output-root R --cluster-config C [--tasks 0] [--no-compare] [--dry-run]
<venv>/bin/python -m scripts.rl.ops.cluster status --output-root R [--json]
<venv>/bin/python -m scripts.rl.ops.cluster resume --output-root R --cluster-config C [--inactive-job ID] [--abandon-intent NNNN:tasks] [--no-compare] [--dry-run]
<venv>/bin/python -m scripts.rl.ops.cluster submit-compare --output-root R --cluster-config C [--dry-run]
<venv>/bin/python -m scripts.rl.ops.cluster cancel --output-root R (--submission 0001 | --tasks 2,5) [--dry-run]
<venv>/bin/python -m scripts.rl.ops.cluster compare --output-root R [--allow-incomplete]
```

`--inactive-job` and `--abandon-intent` are repeatable; each occurrence names
one job id or one `NNNN:tasks` / `NNNN:compare` token. Exit 0 means the command
did what was asked; exit 1 is a refusal or an error, with the reason on stderr.
`status` exits 0 whenever it could render, including when tasks failed.

- **plan** validates, writes `cluster/tasks.json`, prints the task table, and
  prints the `sbatch` argv and rendered scripts with a clearly marked
  provisional receipt number `NNNN` and a `meshops-<random>-tasks` placeholder
  name. It submits nothing.
- **submit** submits tasks whose state is `unsubmitted`, optionally narrowed by
  `--tasks`; naming a task in any other state is refused and points at `resume`.
- **resume** submits every `unsubmitted`, `failed`, or `canceled` task whose
  remaining step directories are clean. Unless `--no-compare`, it also queues
  missing comparison when no tasks need submission and every task is covered.
- **submit-compare** queues comparison alone, after every task is completed,
  partial, or covered by an active array. It never submits training/evaluation.
  A complete comparison or active compare job requires no new submission; an
  unresolved intent or unknown prior writer is a refusal.
- **cancel** requires exactly one of `--submission` or `--tasks`.
- **compare** runs the compare step on the current host.

Validation shared by `plan`, `submit`, `resume`, and `submit-compare`, all refusals: the plan's
own root differs from `--output-root` (the plan was copied from another
filesystem — regenerate it here instead); `sim_binary` is not absolute, missing,
or not executable; a row's `run_config` is missing; the task count exceeds
`max_array_size`; the config is invalid; and, for a non-dry-run `submit` or
`resume`, `sbatch` is not on `PATH`.

`--dry-run` on `submit`/`resume`/`submit-compare` prints the state table and, when something
would be submitted, the provisional argv and scripts. It takes no lock, writes
no receipt, script, or `tasks.json`, and **does not query the scheduler** — its
state table is computed against an offline snapshot, so every receipt-covered
task reads as `unknown` there. A compare-only preview does not claim that the
tasks are covered; actual submission checks the scheduler. Dry runs touch no
lock or artifacts, even when previewing a comparison.

### Cluster config

`cluster-config.example.json` is the schema. Every key is required and the key
set is closed; there is no free-form `sbatch` option, because a value outside
the schema could override the array id, log path, dependency, or the
`--no-requeue` safety flag. A site-required option therefore needs a reviewed
addition to the schema.

```json
{
  "cluster_config_version": 1,
  "name": "<REQUIRED label for receipts>",
  "venv": "<REQUIRED absolute path to the prepared venv>",
  "setup_lines": [],
  "task":    {"partition": null, "account": null, "qos": null, "constraint": null,
              "time": "<REQUIRED HH:MM:SS>", "mem": "<REQUIRED e.g. 4G>",
              "cpus_per_task": "<REQUIRED integer>"},
  "compare": {"time": "<REQUIRED HH:MM:SS>", "mem": "<REQUIRED>", "cpus_per_task": 1},
  "max_array_size": "<REQUIRED integer: site MaxArraySize>",
  "max_concurrent_tasks": null
}
```

- `null` is accepted only for `partition`, `account`, `qos`, `constraint`, and
  `max_concurrent_tasks`; it means "omit the flag and take the site default".
- Any string starting with `<` is refused as a leftover placeholder, so the
  example file cannot be used unedited.
- `time` must match `[D-]H:MM:SS`, `mem` a digit string with an optional
  `K`/`M`/`G`/`T` suffix, and `cpus_per_task` / `max_array_size` /
  `max_concurrent_tasks` an integer ≥ 1.
- `setup_lines` is a possibly empty list of shell lines, for example
  `module load …`, emitted verbatim near the top of each job script.
- `compare` inherits `partition`, `account`, `qos`, and `constraint` from
  `task`; only its `time`, `mem`, and `cpus_per_task` are its own.
- `venv` must be absolute and contain `bin/python`; prepare it with
  `python3 scripts/rl/bootstrap_venv.py --venv <path>`.

The validated config and its SHA-256 are copied into every receipt, so
submissions may legitimately differ — for example more memory after an
out-of-memory failure. The config is not part of the immutable plan.

Job scripts run `set -euo pipefail`, the configured `setup_lines`, export
`OMP_NUM_THREADS` and `MKL_NUM_THREADS` equal to `cpus_per_task` and an empty
`CUDA_VISIBLE_DEVICES`, `cd` to the mesh root recorded at submit time, run
`bootstrap_venv.py --venv <venv> --check` so a pin mismatch fails before any
step starts, and then `exec` the runner. Task scripts use `ops.run_task`; compare scripts
use `ops.cluster compare --scheduled-job "$SLURM_JOB_ID" --record ...`. The
scheduled comparison validates its receipt and takes the same operation lock
as local comparison, ignoring only its own recorded job as a blocker. It waits
up to 30 seconds for an in-progress operation to release that lock, then
refuses if still held; this wait does not resume any training. Every interpolated path is quoted with
`shlex.quote`. Jobs are submitted with `--no-requeue`: a requeued task would
restart into a dirty directory and be refused anyway, so a silent scheduler
retry is worse than an explicit failure.

### Layout under the output root

```
<root>/experiment_plan.json                    existing, immutable, never written here
<root>/train/… <root>/eval/… <root>/comparison/ existing, guarded step directories
<root>/cluster/tasks.json                      deterministic task table
<root>/cluster/submit.lock                     held during every mutation and comparison execution
<root>/cluster/receipts/0001.json
<root>/cluster/scripts/0001-tasks.sh  0001-compare.sh
<root>/cluster/logs/0001/slurm-%A_%a.out  compare-%j.out
<root>/cluster/records/0001/task-0003.json  compare.json
```

`cluster/` sits outside every guarded step directory, so nothing written here
can block a train or evaluate run. `cluster/tasks.json` is
`{"tasks_version": 1, "plan_sha256", "tasks": [{index, id, train_id,
evaluate_id}]}`; an existing file describing a different plan is refused rather
than overwritten.

### Receipts and the submission protocol

One receipt per submission, `cluster/receipts/NNNN.json`:

```json
{"receipt_version": 2, "kind": "tasks", "submission": "0001", "state": "submitting|submitted|submit_uncertain|abandoned",
 "created_at": "...", "host": "...", "user": "...",
 "job_name": "meshops-<32 hex chars>-tasks", "indices": [0, 1],
 "array_spec": "0-1", "plan_sha256": "...", "cluster_config": {…},
 "cluster_config_sha256": "...", "script": "...", "argv": [ … ],
 "job_id": null, "compare": null, "cancel_requests": [], "human_assertions": []}
```

`compare`, when present, holds `{"job_name", "job_id", "state", "created_at",
"script", "argv", "depends_on"}` with the same state values and its own random
job name.

Compare-only submissions use `kind: "compare"`, `indices: []`, a null array
job/name/script, and top-level `state: "not_applicable"`. Their actual job intent
is in `compare`. They retain the same config and plan provenance without
inventing a training submission.

`submit`, `resume`, and `submit-compare` follow the same order:

1. Create `cluster/submit.lock` with `O_CREAT|O_EXCL`. An existing lock is a
   refusal that prints the holder's pid, host, and time; ownership is checked
   before locking and again under the lock. `plan`, cancellation, and local
   and scheduled comparison use this lock too. A stale lock is removed
   by hand after confirming no submit is running. The lock is released in a
   `finally` block.
2. Recover any no-ID intents by exact job name, take a scheduler snapshot,
   apply any `--inactive-job` / `--abandon-intent` assertions, reconcile, and
   compute the indices. With no task indices, `resume` checks whether it can
   queue comparison; `--no-compare` leaves it alone. `submit-compare` never
   computes a new task submission. A fresh scheduler check confirms coverage
   before comparison submission.
3. Allocate `NNNN` by exclusive creation of the receipt file, then write the
   **intent** — including a random 128-bit job name
   (`meshops-<token>-tasks`) — *before* `sbatch` runs, so an accepted job is
   never nameless.
4. Render the script, create the log and record directories, and run
   `sbatch --parsable …`. A non-zero exit, an interruption, or an unparseable
   response may still follow scheduler acceptance, so the receipt is left as a
   `submit_uncertain` no-ID intent with a stderr excerpt and the command exits
   1. **It is never retried automatically and never abandoned automatically.**
   A parsed job id finalizes the receipt as `submitted`.
5. Unless `--no-compare`, and only when every task is finished or covered by an
   active job, queue the compare job (below). When some tasks are uncovered —
   for example after a `--tasks 0` canary — the command says so and queues no
   compare job. If the array succeeds but compare submission is refused or
   uncertain, inspect `status`. `resume` recovers an accepted compare by exact
   name and does not duplicate it. A truly unaccepted no-ID compare remains
   blocked until the owning user confirms it never reached SLURM and uses
   `resume --abandon-intent NNNN:compare`. `submit-compare` can queue comparison
   alone once uncertainty is cleared and every task is covered. Its dependency
   includes every currently active array; with all tasks finished, it has no
   dependency flag.

The `sbatch` argv is
`sbatch --parsable --no-requeue --job-name=J [--array=SPEC] --output=<log pattern>
[--dependency=…] [--partition=] [--account=] [--qos=] [--constraint=] --time= --mem=
--cpus-per-task= <script>`, with each `null` config value omitting its flag.
`SPEC` is the compressed index list (`0-7`, `1,3`) plus `%N` when
`max_concurrent_tasks` is set.

Recovery of a no-ID intent is by exact job name only: `squeue --name=…` and
`sacct --name=…` are filtered for exact equality, and their matches are merged.
Accounting queries use an explicit start date before the intent's creation date,
so recovery also searches prior days; unknown timestamps fall back to epoch.
Slurm otherwise defaults name-only searches to today, as described in its
[accounting time-window documentation](https://slurm.schedmd.com/sacct.html#SECTION_DEFAULT-TIME-WINDOW).
An id is written back **only when exactly one job matches across the two
queries** — one exact match is a positive observation even if the other query
failed. Several matches are reported as too ambiguous and nothing is written.
Zero matches leaves the intent unresolved, because an empty or failed query is
*not* proof that `sbatch` failed; it keeps blocking resubmission.

Two human assertions can clear that, both recorded in the receipt with the
asserting account and time:

- `resume --inactive-job <job id>` asserts that a known-id job is no longer
  active. It is refused when no receipt holds that id or when the scheduler
  still shows the job active.
- `resume --abandon-intent NNNN:tasks` (or `NNNN:compare`) asserts that a no-ID
  submission never reached SLURM. It is refused when that element is not an
  unresolved no-ID intent, or when the job name still matches a job.

Neither assertion can bypass a positive active-job observation or a populated
step directory; the filesystem rules still apply afterwards. `status` never
writes anything.

### Reported states

Eight states, first match wins. `unsubmitted` is separate from `pending` so
"never submitted" and "queued" are not the same word.

| State | Rule |
|---|---|
| `pending` | a covering receipt's element is `PENDING`, `CONFIGURING`, or `REQUEUED` |
| `running` | a covering receipt's element is in another active state (`RUNNING`, `COMPLETING`, `SUSPENDED`, `RESIZING`, `SIGNALING`, `STAGE_OUT`) |
| `completed` | train `done` and evaluate `done` |
| `partial` | train `done` and evaluate `partial` |
| `unknown` | a receipt covers the task and the queue query failed; or an unresolved no-ID intent covers it; or a submitted element is absent from the queue and accounting holds no terminal record for it; or accounting says `COMPLETED` while the filesystem is incomplete; or no receipt covers the task and its train manifest says `running` |
| `canceled` | the latest covering receipt's element is `CANCELLED` in accounting |
| `failed` | the latest covering receipt's element has an explicit terminal failure in accounting; or no receipt covers the task and a step directory is `blocked`; or every known job id of an otherwise-`unknown` task carries a recorded `--inactive-job` assertion (the row then also reports `asserted_inactive: true`) |
| `unsubmitted` | no receipt covers the task and both step directories are `pending` |

Each row carries a `detail` — the scheduler state and reason, the blocked
directory's `move or delete <dir> to retry` message, or why it is unknown — and
a queued row adds the scheduler's own estimated start when it is not `N/A`.
A recorded cancellation request alone cannot prove termination. Unrecognized
scheduler states remain `unknown`, and JSON status uses `status_version: 2`
to distinguish these stricter evidence rules.
A parent-array accounting row is not evidence that each element finished:
elements are reconciled by exact `<array_job_id>_<index>` records, or left
`unknown`.

The compare row uses the same active/terminal logic over the latest compare job
plus the state inside `comparison.json`: `complete` maps to `completed`,
`incomplete` to `partial`, and absent with no compare job to `unsubmitted`.

### Resume rules

A task is resubmitted only when its state is `unsubmitted`, `failed`, or
`canceled`, **and** no element of it is active in any receipt, **and** every
step the runner would execute is `pending` on disk. Train `done` plus evaluate
`pending` qualifies, because the runner skips the finished train.

A task blocked by a dirty directory is listed as not submitted with
`move or delete <dir> to retry`; nothing is ever deleted or renamed by this
tool. `unknown` is never resubmitted without one of the recorded human
assertions above.

### Cancellation

`cancel --tasks 2,5` resolves the selection to exact
`<array_job_id>_<index>` element ids taken from the receipts and never passes a
parent array id, so sibling tasks are untouched. `cancel --submission 0001`
deliberately targets that receipt's whole active array plus its compare job.
Jobs absent from the receipts are never selected. `--dry-run` prints the
`scancel` argv and cancels nothing. A failed `scancel` is reported on stderr
with exit 1 and **no cancellation is recorded**; only a successful call appends
to `cancel_requests`. A failed queue query is a refusal with exit 1 — including
under `--dry-run` — because active elements cannot be resolved without it;
nothing is cancelled and nothing is recorded.

### Only one writer of `comparison.json`

If a compare response is lost after the array is queued, an unresolved intent
blocks another submission. Use the recovery paths above. Local and scheduled
comparisons hold the operation lock from their receipt checks until their
managed child process has stopped and been reaped. Cancellation cannot race
receipt recovery, and two cooperating comparison commands cannot write together.

Before queuing a new compare job, an earlier compare job that is still active is
cancelled, the `scancel` call must have succeeded, and a fresh queue snapshot
must show no remaining blocker; otherwise the new compare job is refused rather
than risking two writers. Compare-only submission and local comparison refuse
existing writers rather than canceling them.

A compare job blocks both of them while it is active, while it is an unresolved
no-ID intent, or — for any non-abandoned compare job carrying a job id — while
nothing has been observed that proves it can no longer write. Evidence of
termination is a recognized terminal state in the queue/accounting snapshot
(`COMPLETED`, `CANCELLED`, `FAILED`, `TIMEOUT`, `NODE_FAIL`, `OUT_OF_MEMORY`,
`PREEMPTED`, `BOOT_FAIL`, `DEADLINE`, or `REVOKED`) or a recorded
`resume --inactive-job <compare job id>` assertion. Successful `scancel` records
a request; it is not terminal evidence. Unknown states remain blockers. A failed
queue query blocks on its own once any compare element
exists. The consequence: where `sacct` accounting is unavailable, a compare job
that has simply left the queue keeps blocking until the human asserts it
inactive.

### `cluster compare` versus `fetch`

`cluster compare` computes statistics **where the plan lives**: it runs the
compare step in a managed child process on the current host, and transfers nothing. With every
evaluation done it may simply run; otherwise it needs `--allow-incomplete`, and
even then refuses while any task is `pending`, `running`, or `unknown`. It
prints one line from the comparison outcome plus the raw exit code:
`complete` (0), `complete with health counters or seed overlap` (2), or
`incomplete` (1).

`fetch` copies files **to another machine** and computes nothing.


### First task through results

Run from `scratch/mesh-sim` on the cluster, using a human-built binary and a
prepared venv. Edit the example cluster JSON for the site's partition, project,
limits and resource requests. Generate the plan on its final shared filesystem;
do not copy a laptop plan with embedded absolute paths.

```bash
<venv>/bin/python -m scripts.rl.experiment plan --matrix M --output-root R --sim-binary /abs/BIN
<venv>/bin/python -m scripts.rl.ops.cluster plan --output-root R --cluster-config C
<venv>/bin/python -m scripts.rl.ops.cluster submit --output-root R --cluster-config C --tasks 0 --no-compare
<venv>/bin/python -m scripts.rl.ops.cluster status --output-root R --json
```

Wait for task 0 to finish, then inspect its train/evaluation manifests and
`cluster/logs/0001/slurm-<array>_0.out`. Completed training is not evidence of
completed evaluation. A failed or unknown task needs the receipt/scheduler
checks described above; populated step directories are never removed for you.
Once the first task is satisfactory, queue the rest:

```bash
<venv>/bin/python -m scripts.rl.ops.cluster submit --output-root R --cluster-config C
<venv>/bin/python -m scripts.rl.ops.cluster status --output-root R
# If tasks are already covered but comparison is missing:
<venv>/bin/python -m scripts.rl.ops.cluster submit-compare --output-root R --cluster-config C
# Recover tasks/uncertain submission responses and any missing comparison:
<venv>/bin/python -m scripts.rl.ops.cluster resume --output-root R --cluster-config C
```

Inspect `comparison/comparison.json`, the comparison tables and
`cluster/records/NNNN/compare.json`. The strict scheduled comparison refuses
missing/partial evaluations. For a deliberately partial local comparison,
first settle every task, then use `cluster compare --allow-incomplete`.
Use `resume --no-compare` when recording assertions before a local comparison.

Result retrieval is supplied by the next stacked PR #11. Once that entry point
is present, run on your laptop with a separate destination:

```bash
.venv/bin/python -m scripts.rl.ops.fetch --remote user@login:/absolute/R \
  --dest outputs/fetched/my-study --select comparison,manifests
```

Retrieval copies saved artifacts; it does not train, submit jobs or recompute
comparison. Keep the independent training/model-selection/held-out seed roles
from the experiment matrix. Offline fake-scheduler tests do not verify the
site's flags, permissions, filesystem locking or accounting latency. Live-site
validation stays in `TODO-RL-OPS-1` and requires a separate cluster exercise.

## Fetch

The intended cluster workflow is Unity with SLURM. Scheduler settings come from
the required cluster config; this command uses SSH/rsync to retrieve files from
the chosen transfer host. The host, username, and absolute output path must come
from your Unity setup. Fetch does not query SLURM, load modules, or choose a
partition; it also accepts a local source directory for testing and local copies.

```bash
.venv/bin/python -m scripts.rl.ops.fetch --remote user@host:/abs/output-root \
  --dest outputs/fetched/bypass-first --select comparison,manifests

# Preview the same transfer without creating output or contacting the host.
.venv/bin/python -m scripts.rl.ops.fetch --remote user@host:/abs/output-root \
  --dest outputs/fetched/bypass-first --select comparison,manifests --dry-run
```

`--remote` and `--dest` are required. Without `--select`, only the
always-included files are copied: `experiment_plan.json`, `cluster/tasks.json`,
and `cluster/receipts/*.json`. Unknown categories are refused.

| Category | Included |
|---|---|
| `comparison` | `comparison/comparison.json`, `comparison/episodes.csv` |
| `manifests` | Train/evaluation manifests, episode manifests, decision-record manifests, evaluation baseline manifests/plans, `cluster/records/**`, `benchmark/**` |
| `models` | Final and best PPO ZIPs, plus retained `train/**/checkpoints/*.zip` |
| `selection-logs` | `train/**/evaluations.npz` |
| `inputs` | Episode input snapshots and evaluation baselines' `source-inputs/` and `effective-inputs/` trees |
| `telemetry` | Episode `steps.jsonl` files |
| `decision-records` | Episode `policy_decisions.jsonl` traces; explicit opt-in |
| `episode-data` | Whole episode trees, including decision traces; potentially large |
| `logs` | `cluster/logs/**`, `eval/**/baseline/planner.log` |

`retrieval.CATEGORY_INCLUDES` holds the exact patterns. Episode patterns include
callback evaluations under `train/` as well as standalone evaluations under
`eval/`. Baseline metadata lives beside episode directories under
`eval/<row>/train-seed-<S>/<method>/baseline/`, with its plan at
`effective-inputs/baseline-plan.json`; selecting whole episodes alone
does not include that sibling baseline tree. Use `manifests,inputs` for its
metadata and source/effective inputs. Use `models,manifests` when retained
checkpoint metadata is needed alongside its ZIP; fetching files does not itself
rebase or validate a model bundle for recovery.

### Add missing files or take a fresh snapshot

Every transfer uses `rsync -a --prune-empty-dirs --ignore-existing` with include
rules followed by `--include='*/' --exclude='*'`. Existing local files are never
replaced. A non-empty destination requires `--update`, which **adds missing
files only**. It does not refresh a running manifest, append a growing trace, or
replace an incomplete comparison. It can therefore mix old files with newly
arrived files. The command prints a reminder and records `files_may_be_stale`.

To add missing categories to the first copy:

```bash
.venv/bin/python -m scripts.rl.ops.fetch --remote user@host:/abs/output-root \
  --dest outputs/fetched/bypass-first --select models,manifests --update
```

After the remote run finishes, use a new destination for fresh results:

```bash
.venv/bin/python -m scripts.rl.ops.fetch --remote user@host:/abs/output-root \
  --dest outputs/fetched/bypass-finished --select comparison,manifests,inputs
```

The first directory stays intact. Even a new destination is a file-by-file
copy, not an atomic snapshot of an actively changing remote run; fetch after
completion for a consistent finished result.

Destinations cannot be a filesystem root, a home directory, the mesh-sim root,
or an existing non-directory. Local source and destination trees must not
overlap in either direction; symlinks are checked after resolution. A missing
rsync or nonzero transfer exit gives exit 1. On transfer failure, no new fetch
manifest is published or rotated, but rsync may have left partial files. Use a
new destination for a fresh retry; `--update` retains any existing partial files.

### Fetch manifest

`<dest>/fetch_manifest.json` uses version 2:

```json
{"fetch_manifest_version": 2, "remote": "...", "selection": ["manifests"],
 "argv": [], "fetched_at": "...", "transfer_mode": "new_destination",
 "files_may_be_stale": false, "inventory_scope": "destination",
 "state_basis": "local_manifests",
 "files": [{"path": "...", "bytes": 0, "sha256": "..."}],
 "tasks": [{"index": 0, "id": "...", "state": "running"}],
 "comparison": "not_fetched", "snapshot_of_incomplete_run": true}
```

`transfer_mode` is `new_destination` or `add_missing`. `fetched_at` is the time
this inspection was recorded; it is not the transfer time of every listed file.
`files` inventories the destination, including files retained from earlier
copies, excluding current and rotated fetch manifests. It is not a count of new
files transferred. A successful update keeps the previous manifest as
`fetch_manifest.<n>.json`; older version-1 history stays intact.

Task states describe **copied local manifests**, not live scheduler state:

| State | Meaning |
|---|---|
| `completed` / `partial` | Copied evaluation reports that status |
| `running` | Copied training or evaluation reports running; it may be stale |
| `failed` | Copied training or evaluation explicitly reports failed/interrupted |
| `missing` | Neither step directory exists locally |
| `incomplete` | Other unfinished, unreadable, or unrecognized copied state |
| `not_fetched` | The current transfer did not select `manifests` |

`snapshot_of_incomplete_run` is null when task state cannot be inspected, and
otherwise says whether any copied task is not completed. `comparison` is
`not_fetched` unless selected, then `absent`, `complete`, `incomplete`, or
`unreadable`. Selected-but-absent means absent in the local inventory; it does
not prove what currently exists remotely. Inspection rebases step output paths
in memory without changing the copied plan. Fetched trees belong under the
git-ignored `outputs/` directory.

### Extending retrieval and testing it

Keep new artifact rules in `retrieval.py`, with the category and output owner
documented here. Check the writer's actual directory layout first, including
callback evaluation nesting. Update the local-rsync fixture with a small example
and an expected selected/unselected result. Do not add a second category table
to the CLI or repeat production rules in fake tests. When fetch manifest meanings
change, update its version, this schema description, and the state/history tests.

```bash
.venv/bin/python -m pytest -q scripts/rl/tests/test_ops_fetch.py \
  scripts/rl/tests/test_ops_fetch_local.py scripts/rl/tests/test_ops_tasks.py
```

| Tests | What they verify |
|---|---|
| `test_ops_fetch.py` | CLI/category refusals, argv, destination and symlink checks, copied task/comparison states, local inventory/digests, manifest history, dry-run and transfer failures |
| `test_ops_fetch_local.py` | Installed rsync's real include/exclude behavior for every category, checkpoint/baseline/decision artifacts, unchanged local files on update, fresh destination refresh, and malformed copied states |
| `test_ops_tasks.py` | Shared plan/task mapping and comparison outcomes used during inspection |

The fake transfer tool stages controlled fixtures and failures without network
access; it does not implement rsync filtering. Real transfer tests use only
pytest's temporary local directories and skip if rsync is unavailable. They do
not verify SSH, Unity transfer-host permissions, or live SLURM behavior.


The integrated local work wires learning rate, batch size, GAE lambda, clipping, epoch count, target KL and final entropy coefficient through the same validated PPO settings and tuning boundary. Network architecture remains an explicit matrix setting.
