@page scripts_rl_ops Experiment operations

@brief Run, benchmark, tune, submit to SLURM, and fetch an experiment plan.

These tools work on an existing `experiment_plan.json`, created by
`scripts.rl.experiment plan` (see
\ref scripts_rl_comparing_policies "Comparing policies and running an experiment matrix").
Create the plan before executing or measuring a task. They run the plan's tasks
on this host, measure one task and estimate a larger matrix, tune PPO
hyperparameters with Optuna, run the plan as SLURM jobs, and copy results to
another machine. Run every command from `scratch/mesh-sim/`.

Sections 2–9 cover version 1 plans (plan v2). Version 2 batches (plan v3), run
with `scripts/rl/run-experiments.sh`, execute locally as described in
[section 10](@ref scripts_rl_ops_batch).

## 1\. Overview

| Command | What it does |
|---|---|
| `scripts.rl.ops.run_task` | Runs one task, or the comparison step, on this host. |
| `scripts.rl.ops.benchmark run` | Runs one task and records wall-clock time and peak memory. |
| `scripts.rl.ops.benchmark estimate` | Scales a benchmark onto a target matrix. Runs nothing. |
| `scripts.rl.ops.tune` | Runs an Optuna study over one matrix row and training seed. |
| `scripts.rl.ops.cluster` | Plans, submits, tracks, resumes and cancels SLURM jobs for a plan, and runs its comparison. |
| `scripts.rl.ops.fetch` | Copies selected results from an output root to this machine with rsync. Computes nothing. |

### Task unit

A task is one `(row, training seed)` pair: its `train` step followed by its
`evaluate` step, run serially. On a cluster, one task is one array element.

- **Task index:** the 0-based position of the train step among the plan's train
  steps. The task table follows train-step order in `experiment_plan.json`.
- **Task id:** the train step id without its `train/` prefix, for example
  `local-delivery/train-seed-101`.
- **Pairing:** `build_tasks` pairs each train step with the evaluate step whose
  `needs` names it, and raises `ValueError` when a pair or the compare step is
  missing.
- **Comparison:** one separate step after all tasks (one separate job on a
  cluster).

An evaluation needs only its own training run, and evaluation seeds cannot be
split across tasks (`scripts.rl.compare` requires one manifest per label with
sorted seeds), so each task is self-contained.

### Common exit codes {#scripts_rl_ops_exit_codes}

| Code | Meaning |
|---|---|
| `0` | The command did what was asked. |
| `1` | Refusal or error; the reason is on stderr. |
| `130` / `143` | Interrupted by SIGINT / SIGTERM. Launched process groups are stopped and reaped first. |

Each command section lists its own differences.

## 2\. Typical workflow {#scripts_rl_ops_workflow}

Placeholders: `<BIN>` is a simulator binary you built, `M` a matrix file, `R` an
output root, `C` a cluster config, `<venv>` the cluster's prepared venv.

1. **Plan a small benchmark** (one representative row):
   ```bash
   .venv/bin/python -m scripts.rl.experiment plan \
     --matrix inputs/experiments/bypass-smoke-matrix.json \
     --output-root outputs/bench/bypass-smoke --sim-binary <BIN> --rows local-delivery
   ```
2. **Benchmark** one task ([section 4](@ref scripts_rl_ops_benchmark)):
   ```bash
   .venv/bin/python -m scripts.rl.ops.benchmark run \
     --output-root outputs/bench/bypass-smoke --task-index 0
   ```
3. **Estimate** the target matrix:
   ```bash
   .venv/bin/python -m scripts.rl.ops.benchmark estimate \
     --benchmark outputs/bench/bypass-smoke/benchmark/task-0000.json \
     --target-matrix <matrix.json> --safety-factor 2.0 \
     --output outputs/bench/bypass-smoke/benchmark/estimate.json
   ```
4. **Tune** (optional; [section 5](@ref scripts_rl_ops_tune)), then copy the chosen
   training block into a new matrix by hand:
   ```bash
   .venv/bin/python -m scripts.rl.ops.tune --study inputs/experiments/bypass-smoke-study.json \
     --output-root outputs/tune/bypass-smoke --sim-binary <BIN>
   ```
5. **Plan on the cluster**, on the plan's final shared filesystem, with a
   human-built binary and a prepared venv. Do not copy a laptop plan: it embeds
   absolute paths.
   ```bash
   <venv>/bin/python -m scripts.rl.experiment plan --matrix M --output-root R --sim-binary /abs/BIN
   ```
6. **Preview the cluster jobs** after editing `cluster-config.example.json` for
   the site's partition, project, limits and resource requests
   ([section 6](@ref scripts_rl_ops_cluster_runs)):
   ```bash
   <venv>/bin/python -m scripts.rl.ops.cluster plan --output-root R --cluster-config C
   ```
7. **Submit one canary task** without comparison:
   ```bash
   <venv>/bin/python -m scripts.rl.ops.cluster submit --output-root R --cluster-config C --tasks 0 --no-compare
   ```
   Wait for task 0 to finish, then inspect its train/evaluation manifests and
   `cluster/logs/0001/slurm-<array>_0.out`. A completed training step does not
   mean the evaluation completed.
8. **Submit the rest** (this also queues the comparison job):
   ```bash
   <venv>/bin/python -m scripts.rl.ops.cluster submit --output-root R --cluster-config C
   ```
9. **Check status, and resume** failed, canceled or uncertain submissions and
   any missing comparison:
   ```bash
   <venv>/bin/python -m scripts.rl.ops.cluster status --output-root R --json
   <venv>/bin/python -m scripts.rl.ops.cluster resume --output-root R --cluster-config C
   ```
   If every task is already covered but the comparison is missing, use
   `cluster submit-compare --output-root R --cluster-config C` instead. A failed
   or `unknown` task needs the receipt and scheduler checks in
   [section 9](@ref scripts_rl_ops_cluster_states); populated step directories are
   never removed for you.
10. **Fetch** results on your laptop into a separate destination
    ([section 7](@ref scripts_rl_ops_fetch)):
    ```bash
    .venv/bin/python -m scripts.rl.ops.fetch --remote user@login:/absolute/R \
      --dest outputs/fetched/my-study --select comparison,manifests
    ```

After step 9:

- Inspect `comparison/comparison.json`, the comparison tables and
  `cluster/records/NNNN/compare.json`.
- The scheduled comparison refuses missing or partial evaluations. For a
  deliberately partial comparison, first settle every task, then run
  `cluster compare --allow-incomplete` on the cluster.
- Use `resume --no-compare` when recording assertions before a local
  comparison.

### Run the tasks without a scheduler

Create a plan, inspect it, run its first task, and inspect the resulting
training and evaluation manifests:

```bash
.venv/bin/python -m scripts.rl.experiment plan \
  --matrix inputs/experiments/bypass-smoke-matrix.json \
  --output-root outputs/ops-walkthrough --sim-binary <BIN>
.venv/bin/python -m scripts.rl.experiment status --output-root outputs/ops-walkthrough
.venv/bin/python -m scripts.rl.ops.run_task --output-root outputs/ops-walkthrough \
  --task-index 0 --record outputs/ops-walkthrough/task-0000.json
.venv/bin/python -m scripts.rl.experiment status --output-root outputs/ops-walkthrough
```

Run the remaining task indices the same way, then run
`scripts.rl.ops.run_task --output-root outputs/ops-walkthrough --compare` and
inspect `comparison/comparison.json` and `comparison/episodes.csv`. Incomplete
prerequisites are refused unless explicitly allowed. A task record keeps raw
exit codes even when a health-counter exit `2` is tolerated.

## 3\. Run a task: run_task

```bash
.venv/bin/python -m scripts.rl.ops.run_task --output-root R --task-index I [--record PATH]
.venv/bin/python -m scripts.rl.ops.run_task --output-root R --compare [--allow-incomplete] [--record PATH]
.venv/bin/python -m scripts.rl.ops.run_task --output-root R --step ID --attempt A   # plan v3 worker
```

| Flag | Default | Description |
|---|---|---|
| `--output-root R` | required | Directory holding `experiment_plan.json`. |
| `--task-index I` | none | Run task `I`. Exactly one of `--task-index` or `--compare` is required. |
| `--compare` | off | Run the compare step. |
| `--allow-incomplete` | off | With `--compare` only: compare even when an evaluation is missing or partial. |
| `--record PATH` | none | Write an execution record ([section 8](@ref scripts_rl_ops_task_record)). |
| `--step ID --attempt A` | none | Plan v3 worker entry point, launched by the batch scheduler; cannot be combined with the other options ([section 10](@ref scripts_rl_ops_batch)). |

### Task mode

1. Train `done` is skipped. `pending` is executed as a fresh
   `python -m <module> <args>` process from the mesh root. Any other state
   prints the step's own retry detail and exits 1 without touching the
   directory.
2. A train exit code that is not tolerated exits 1; the evaluation is not
   attempted.
3. Evaluate `done` exits 0. `partial` or `blocked` prints the detail and exits 1.
   `pending` is executed; a tolerated exit gives 0, anything else 1.

Rerunning a task skips its finished steps. It does not resume a training
checkpoint: use `scripts.rl.train --resume` for that, then rerun the task so
evaluation follows the completed training.

### Compare mode

- **Default:** when any evaluation is missing or partial, it prints each
  offending step id, **writes nothing at all (no comparison output and no
  `--record` file)**, and exits 1.
- **With `--allow-incomplete`:** it executes the compare step and prints the step
  id, the raw exit code, and the state read back from `comparison.json`.

### Exit-code tolerance

`tolerated(kind, code)` matches the tolerated codes of the underlying CLIs:

| Step kind | Tolerated exit codes |
|---|---|
| `train` | `0` |
| `evaluate` | `0`, `2` |
| `compare` | `0`, `2` |

A `2` means health counters or a not-held-out evaluation. A tolerated `2` makes
the runner exit 0, so `sacct` does not show a healthy task as `FAILED`; the raw
code is kept in the record.

Steps run in managed process groups. An interruption, a wait failure, or a
failure to record after launch stops and reaps the group before returning.

## 4\. Benchmark and estimate: benchmark {#scripts_rl_ops_benchmark}

`benchmark run` executes one planned train step and its evaluation, and records
wall-clock time and sampled memory. `benchmark estimate` scales that measurement
onto a target matrix. Measure a small representative task first. The estimate
does not measure the target matrix and does not predict queue wait time.

```bash
.venv/bin/python -m scripts.rl.ops.benchmark run --output-root R --task-index I [--sample-interval-s S]
.venv/bin/python -m scripts.rl.ops.benchmark estimate --benchmark FILE --target-matrix M \
  --safety-factor F --output FILE
```

Steps 1 to 3 of the [typical workflow](@ref scripts_rl_ops_workflow) are a complete
example.

### benchmark run

| Flag | Default | Description |
|---|---|---|
| `--output-root` | required | Directory holding `experiment_plan.json`. |
| `--task-index` | required | 0-based position among the plan's train steps. |
| `--sample-interval-s` | `0.5` | Seconds between `ps` samples. Must be > 0. |

Refusals (exit 1, nothing run):

| Condition | Result |
|---|---|
| `--task-index` outside the task table | Refused. |
| `--sample-interval-s` ≤ 0 | Refused. |
| `benchmark/task-NNNN.json` already exists | Refused; move it aside to measure again. |
| Either step directory is not `pending` | Refused; lists the steps. |

Behavior:

- Each step runs in its own process group with the same exit tolerance as the
  runner. A train step that is not tolerated stops the benchmark (the
  evaluation is not run) and the command exits 1; the benchmark file is still
  written.
- A sampler thread takes one sample immediately after spawn, then every
  `--sample-interval-s` seconds. It parses `ps -A -o pid=,ppid=,rss=`, walks the
  parent chain from the step's pid, and keeps the peak summed RSS, the peak
  process count, and the largest single-process RSS over the tree. The whole
  tree is sampled because a training step can have the Python process and up to
  two simulator subprocesses alive at once.
- RSS (*resident set size*) is memory currently resident in RAM, in KiB.
  `peak_tree_rss_kb` is the largest sampled sum over the task's Python process
  and its descendants. Shared pages may be counted more than once.
- **Sampling misses spikes shorter than the interval.** The record says so in
  `sampling.note`; the estimate's safety factor covers it.
- A `ps` failure sets the three memory fields to `null` and records
  `measurement_error`. Timing is still measured and the file is still written.

Output: `<output-root>/benchmark/task-NNNN.json`, benchmark schema 2
([section 8](@ref scripts_rl_ops_benchmark_record)).

### benchmark estimate

`estimate` runs nothing; it is arithmetic only.

| Flag | Default | Description |
|---|---|---|
| `--benchmark` | required | A `benchmark/task-NNNN.json` file. |
| `--target-matrix` | required | Matrix JSON file to estimate. |
| `--safety-factor` | required | Multiplier applied to measured seconds and memory. Must be > 0. |
| `--output` | required | Estimate JSON to write. |

The benchmark must satisfy all of these, or the estimate is refused:

- `benchmark_version` is 2. Schema 1 measurements must be repeated.
- Both steps have tolerated exits and `completed` manifests.
- The evaluation completed all expected episodes.
- `seconds_per_timestep` and `seconds_per_episode` are positive numbers.

Each target row is estimated only when:

| Check | Compared by | If it differs |
|---|---|---|
| Same scenario | The `*_sha256` fields of `scenario_identity` (`run.ini` paths differ between machines) | `per_task_seconds: null`, `reason: "different scenario"` |
| Same cadence | `n_steps`, `eval_every_steps` and `eval_episodes` | `per_task_seconds: null`, `reason: "different cadence"` |

For a matching row:

```
per_task_seconds = seconds_per_timestep × effective target timesteps
                 + seconds_per_episode × policies × held-out seeds
```

A row whose observation or reward selection differs, but whose scenario and
cadence match, is still estimated, with `selection_differs: true` and a warning
that its Python and agent work was not measured.

The command prints one line per row and the serial total, then writes the
estimate ([section 8](@ref scripts_rl_ops_estimate_output)).

## 5\. Tune hyperparameters: tune {#scripts_rl_ops_tune}

`tune` runs an Optuna study: each trial trains one configuration of one matrix
row on one training seed and scores it on the model-selection seed. Optuna is
installed separately:

```bash
.venv/bin/python -m pip install -r requirements-tuning.txt

.venv/bin/python -m scripts.rl.ops.tune --study inputs/experiments/bypass-smoke-study.json \
  --output-root outputs/tune/bypass-smoke --sim-binary <BIN> --dry-run

.venv/bin/python -m scripts.rl.ops.tune --study inputs/experiments/bypass-smoke-study.json \
  --output-root outputs/tune/bypass-smoke --sim-binary <BIN>
```

| Flag | Default | Description |
|---|---|---|
| `--study` | required | Study spec JSON ([section 8](@ref scripts_rl_ops_study_spec)). |
| `--output-root` | new `outputs/YYYY-MM/DD/HH-MM-SS-<name>/` | Study records and recovery checkpoint. The default needs the study `name` to be a lowercase slug. Required with `--resume`. |
| `--sim-binary` | required | Simulator executable. Must be an existing executable file unless `--dry-run`. |
| `--dry-run` | off | Preview the startup candidates; creates nothing. |
| `--resume` | off | Continue this study from its checkpoint. Cannot be combined with `--dry-run`. |

| Exit | Meaning |
|---|---|
| `0` | Every trial produced an objective. |
| `1` | A refusal, or at least one trial failed. Records are still written for failed trials. |
| `130` / `143` | Interrupted by SIGINT / SIGTERM. |

An `--output-root` that already holds `study-checkpoint.bin`,
`study_manifest.json` or `trials/` is refused for a fresh run; use `--resume` to continue it.

### Trials

- The sampled values replace the same keys in a copy of the matrix's `training`
  block, and the copy's `seeds.training` becomes just the study's training seed.
  `build_plan` supplies the train step; only its module, args and output
  directory are used, and no plan file is written.
- The trial command is therefore byte-for-byte the command a matrix with those
  values would run, carrying `--eval-seed <model_selection>`.
- A command that names a held-out seed is refused. The guard reads only the value
  after each `--seed`, `--eval-seed` and `--eval-seeds` flag, not every token.
- Trials run sequentially as subprocesses.
- `n_trials` is the total attempt budget. Failed and interrupted trials consume
  an attempt.

### Objective

The objective is `train_manifest.json`'s `best_mean_reward`, maximized. A
non-zero training exit, an unreadable manifest, a manifest whose status is not
`completed`, or a non-finite or `null` value fails that trial with a recorded
reason, and the study continues.

### Sampler and dry run

- The sampler is TPE with the resolved spec settings, which are recorded in the
  manifest. Until `n_startup_trials` completed objectives exist, draws are
  startup samples, so the three-trial example does no adaptive search.
- `--dry-run` asks the sampler `min(n_trials, n_startup_trials)` times without
  telling it results, and prints exactly those parameter sets and commands. For
  a larger `n_trials` it says that the remaining trials depend on earlier
  objectives.
- A dry run creates no output directory, record, training process or simulator
  process.

### Seed roles

| Seed | Role |
|---|---|
| `training_seed` (study) | Fixes PPO and training-scenario randomness for every trial in the study. |
| `sampler.seed` (study) | Fixes Optuna's sequence of candidate hyperparameters. Not passed to PPO or the simulator. |
| `seeds.model_selection` (matrix) | Scores each trial. |
| `seeds.held_out` (matrix) | Not used for tuning. |

### Using a result

- Trials are different configurations, not replicate seeds of one comparison
  group. `scripts.rl.compare` builds an across-runs group from several training
  seeds of one configuration.
- To use a result, copy `best.training` from `study_manifest.json` into a new
  experiment matrix by hand and freeze it. Train it on several independent
  training seeds and evaluate it on held-out seeds. Nothing edits a matrix
  automatically.
- Rows with different reward definitions produce returns on different scales,
  so each needs its own study.
- Cadence and training budgets stay fixed within a study. Resolved runtime
  hyperparameters are kept in each training manifest.
- The example study is a plumbing smoke. Its objective uses one deterministic
  episode on one model-selection seed at a smoke budget (the configured
  `eval_episodes` is recorded in the objective). Its values in
  `inputs/experiments/bypass-smoke-study.json` exercise the code path on the
  smoke fixture; they are not recommended ranges.

### Resume a study

```bash
.venv/bin/python -m scripts.rl.ops.tune \
  --study inputs/experiments/bypass-smoke-study.json \
  --output-root outputs/tune/bypass-smoke --sim-binary <BIN> --resume
```

- The checkpoint (`study-checkpoint.bin`) atomically saves the Optuna study,
  seeded sampler, pending trial, records and best configuration before the JSON
  mirrors are refreshed. Recovery loads that locally created checkpoint and
  repairs the mirrors.
- Completed trials are kept and not re-executed. A pending trial whose training
  completed is reconciled; otherwise it is recorded as failed and the remaining
  attempts run.
- The tuner does not resume a training checkpoint or overwrite an interrupted
  training directory. A completed study launches nothing on resume.
- The checkpoint holds Python/Optuna serialized state from this run. Keep it with
  its JSON records and a matching environment; the JSON records alone cannot
  restore seeded sampler continuation. See
  [Optuna's persistence guide](https://optuna.readthedocs.io/en/v5.0.0/tutorial/20_recipes/001_rdb.html).

Resume refusals:

| Condition | Action |
|---|---|
| Another writer holds the file lock | Refused; one writer at a time. |
| An interrupted trial's saved process group may still exist | Refused until it is stopped. Resume on that trial's original host. |
| Inputs, scenario hashes, simulator bytes, Python/dependency versions or the Optuna pin differ | Refused. Changed settings need a fresh study. |
| Version 1 (JSON-only) study with no sampler checkpoint | Cannot be resumed. |
| `--resume` with `--dry-run` | Refused. |
| `--resume` without `--output-root` | Refused. |

## 6\. Cluster runs {#scripts_rl_ops_cluster_runs}

`scripts.rl.ops.cluster` runs a plan as SLURM array jobs of tasks plus one
dependent compare job. Run it on the cluster after the human has built the
binary and prepared the venv.

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

| Command | What it does |
|---|---|
| `plan` | Validates, writes `cluster/tasks.json` and previews the submission (below). Submits nothing. |
| `submit` | Submits tasks whose state is `unsubmitted`, optionally narrowed by `--tasks`. Naming a task in any other state is refused and points at `resume`. |
| `status` | Prints every task's state ([section 9](@ref scripts_rl_ops_cluster_states)). Writes nothing. |
| `resume` | Submits every `unsubmitted`, `failed` or `canceled` task whose remaining step directories are clean. Unless `--no-compare`, it also queues a missing comparison when no tasks need submission and every task is covered. |
| `submit-compare` | Queues the comparison alone (below). Never submits training or evaluation. |
| `cancel` | Cancels active jobs recorded in the receipts. Requires exactly one of `--submission` or `--tasks`. |
| `compare` | Runs the compare step on the current host. |

| Flag | Commands | Description |
|---|---|---|
| `--output-root R` | all | Required. Directory holding `experiment_plan.json`. |
| `--cluster-config C` | `plan`, `submit`, `resume`, `submit-compare` | Required. Cluster JSON ([Cluster config](@ref scripts_rl_ops_cluster_config)). |
| `--tasks LIST` | `submit` | Comma-separated task indices. Default: every unsubmitted task. |
| `--tasks LIST` | `cancel` | Comma-separated task indices; cancels exact array elements. |
| `--submission NNNN` | `cancel` | Receipt number; cancels its whole active array and its compare job. |
| `--no-compare` | `submit`, `resume` | Do not queue the comparison job. |
| `--dry-run` | `submit`, `resume`, `submit-compare`, `cancel` | Preview only (see below). |
| `--json` | `status` | Machine-readable output, `status_version: 2`. |
| `--inactive-job ID` | `resume` | Repeatable. Asserts that this known job id is no longer active. |
| `--abandon-intent NNNN:tasks` or `NNNN:compare` | `resume` | Repeatable. Asserts that this no-ID submission never reached SLURM. |
| `--allow-incomplete` | `compare` | Compare even when an evaluation is missing or partial. |
| `--record PATH` | `compare` | Write an execution record. |

- **`plan` preview:** prints the task table, the `sbatch` argv and the
  rendered scripts, with a marked provisional receipt number `NNNN` and a
  `meshops-<random>-tasks` placeholder name.
- **`submit-compare`:** queues once every task is completed, partial, or
  covered by an active array. A complete comparison or an active compare job
  means nothing new is submitted; an unresolved intent or an unknown prior
  writer is a refusal.
- **Exit codes** follow [section 1](@ref scripts_rl_ops_exit_codes), except that `status`
  exits 0 whenever it could render, including when tasks failed.

### Ownership

Use one OS/SLURM user per output root.

- Before any receipt, task-table or comparison mutation, every receipt is
  checked against the account from the OS user database (not `USER`/`LOGNAME`).
  A different owner is a refusal before any scheduler call or write; use the
  owning account or another output root.
- The SLURM resource `account` is a billing/project choice and plays no part
  in ownership.
- Read-only `status` queries each receipt's recorded owner; limited scheduler
  visibility shows as `unknown`.
- Version 1 receipts with an owner remain readable. Ownerless or unsupported
  receipts require human repair.

### Shared refusals

`plan`, `submit`, `resume` and `submit-compare` all refuse when:

| Condition | Fix |
|---|---|
| The plan's own root differs from `--output-root` | The plan was copied from another filesystem; regenerate it here. |
| `sim_binary` is not absolute, missing, or not executable | Re-plan with a valid absolute binary. |
| A row's `run_config` is missing | Restore the file or re-plan. |
| The task count exceeds `max_array_size` | Split the matrix or raise the limit. |
| The cluster config is invalid | Fix the config ([Cluster config](@ref scripts_rl_ops_cluster_config)). |
| `sbatch` is not on `PATH` (non-dry-run `submit` or `resume` only) | Run on a submit host. |

### Dry run

`--dry-run` on `submit`, `resume` and `submit-compare` prints the state table
and, when something would be submitted, the provisional argv and scripts.

- It takes no lock and writes no receipt, script or `tasks.json`.
- It **does not query the scheduler**: the state table uses an offline
  snapshot, so every receipt-covered task reads as `unknown`.
- A compare-only preview does not report the tasks as covered; actual
  submission checks the scheduler.

`--dry-run` on `cancel` prints the `scancel` argv and cancels nothing.

### Cluster config {#scripts_rl_ops_cluster_config}

`cluster-config.example.json` is the schema. Every key is required and the key
set is closed. There is no free-form `sbatch` option, because a value outside the
schema could override the array id, log path, dependency, or the
`--no-requeue` safety flag; a site-required option needs a reviewed addition to
the schema.

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

| Key | Rule |
|---|---|
| any string | A value starting with `<` is refused as a leftover placeholder, so the example cannot be used unedited. |
| `venv` | Absolute and contains `bin/python`. Prepare it with `python3 scripts/rl/bootstrap_venv.py --venv <path>`. |
| `setup_lines` | A possibly empty list of shell lines (for example `module load …`), emitted verbatim near the top of each job script. |
| `time` | Matches `[D-]H:MM:SS`. |
| `mem` | A digit string with an optional `K`/`M`/`G`/`T` suffix. |
| `cpus_per_task`, `max_array_size`, `max_concurrent_tasks` | Integer ≥ 1. |
| `partition`, `account`, `qos`, `constraint`, `max_concurrent_tasks` | The only keys that accept `null`, which omits the flag and takes the site default. |
| `compare` | Inherits `partition`, `account`, `qos` and `constraint` from `task`; only its `time`, `mem` and `cpus_per_task` are its own. |

The validated config and its SHA-256 are copied into every receipt, so
submissions may differ (for example, more memory after an out-of-memory
failure). The config is not part of the immutable plan.

### Job scripts

Each job script:

1. runs `set -euo pipefail` and the configured `setup_lines`;
2. exports `OMP_NUM_THREADS` and `MKL_NUM_THREADS` equal to `cpus_per_task`, and
   an empty `CUDA_VISIBLE_DEVICES`;
3. `cd`s to the mesh root recorded at submit time;
4. runs `bootstrap_venv.py --venv <venv> --check`, so a pin mismatch fails
   before any step starts;
5. `exec`s the runner: `ops.run_task` for task scripts, and
   `ops.cluster compare --scheduled-job "$SLURM_JOB_ID" --record ...` for compare
   scripts.

- Every interpolated path is quoted with `shlex.quote`.
- Jobs are submitted with `--no-requeue`. A requeued task would restart into a
  dirty directory and be refused anyway, so an explicit failure is preferred to
  a silent scheduler retry.
- The scheduled comparison validates its receipt and takes the same operation
  lock as a local comparison, ignoring only its own recorded job as a blocker.
  It waits up to 30 seconds for an in-progress operation to release the lock,
  then refuses if it is still held. This wait does not resume any training.

### cluster compare versus fetch

`cluster compare` computes statistics where the plan lives. It runs the compare
step in a managed child process on the current host and transfers nothing.

- With every evaluation done it runs directly. Otherwise it needs
  `--allow-incomplete`, and even then refuses while any task is `pending`,
  `running` or `unknown`.
- It prints one line for the comparison outcome plus the raw exit code:

| Outcome | Raw exit code |
|---|---|
| `complete` | `0` |
| `complete with health counters or seed overlap` | `2` |
| `incomplete` | `1` |

`fetch` copies files to another machine and computes nothing.

## 7\. Fetch results: fetch {#scripts_rl_ops_fetch}

`fetch` uses SSH/rsync to copy selected files from an output root, typically
from the Unity cluster's transfer host. The host, username and absolute output
path come from your Unity setup. Fetch does not query SLURM, load modules or
choose a partition. It also accepts a local source directory, for testing and
local copies. It does not train, submit jobs or recompute the comparison.

```bash
.venv/bin/python -m scripts.rl.ops.fetch --remote user@host:/abs/output-root \
  --dest outputs/fetched/bypass-first --select comparison,manifests

# Preview the same transfer without creating output or contacting the host.
.venv/bin/python -m scripts.rl.ops.fetch --remote user@host:/abs/output-root \
  --dest outputs/fetched/bypass-first --select comparison,manifests --dry-run
```

| Flag | Default | Description |
|---|---|---|
| `--remote` | required | rsync source: `[user@host:]/abs/output-root`. |
| `--dest` | required | Local destination directory. Nothing existing is overwritten. |
| `--select` | none | Comma list of categories (below). Unknown categories are refused. |
| `--update` | off | Required for a non-empty destination. Adds missing files only. |
| `--dry-run` | off | Prints the rsync argv and exits without transferring. |

| Exit | Meaning |
|---|---|
| `0` | Transfer and manifest succeeded, or dry run printed. |
| `1` | Refusal, missing rsync, or nonzero rsync exit. |

### Categories

Every fetch copies `experiment_plan.json`, `cluster/tasks.json` and
`cluster/receipts/*.json`. Without `--select`, only those are copied.

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

- `retrieval.CATEGORY_INCLUDES` holds the exact patterns.
- Episode patterns include callback evaluations under `train/` and standalone
  evaluations under `eval/`.
- Baseline metadata lives beside the episode directories under
  `eval/<row>/train-seed-<S>/<method>/baseline/`, with its plan at
  `effective-inputs/baseline-plan.json`. Selecting whole episodes does not
  include that sibling baseline tree; use `manifests,inputs` for its metadata
  and source/effective inputs.
- Use `models,manifests` when retained checkpoint metadata is needed alongside
  its ZIP. Fetching files does not rebase or validate a model bundle for
  recovery.

### Add missing files or take a fresh snapshot

Every transfer uses `rsync -a --prune-empty-dirs --ignore-existing` with the
include rules followed by `--include='*/' --exclude='*'`. Existing local files
are never replaced.

`--update` **adds missing files only**. It does not refresh a running manifest,
append to a growing trace, or replace an incomplete comparison, so it can mix
old files with newly arrived ones. The command prints a reminder and records
`files_may_be_stale`. To add missing categories to a first copy:

```bash
.venv/bin/python -m scripts.rl.ops.fetch --remote user@host:/abs/output-root \
  --dest outputs/fetched/bypass-first --select models,manifests --update
```

For fresh results after the remote run finishes, use a new destination; the
first directory stays intact:

```bash
.venv/bin/python -m scripts.rl.ops.fetch --remote user@host:/abs/output-root \
  --dest outputs/fetched/bypass-finished --select comparison,manifests,inputs
```

A new destination is still a file-by-file copy, not an atomic snapshot of a
changing remote run. Fetch after completion for a consistent finished result.
Fetched trees belong under the git-ignored `outputs/` directory.

### Destination rules and failures

| Condition | Result |
|---|---|
| Destination is a filesystem root, a home directory, the mesh-sim root, or an existing non-directory | Refused. |
| Local source and destination trees overlap, in either direction (checked after resolving symlinks) | Refused. |
| Non-empty destination without `--update` | Refused. |
| rsync missing, or rsync exits nonzero | Exit 1. No new fetch manifest is published or rotated, but rsync may have left partial files. Retry into a new destination; `--update` keeps existing partial files. |

The fetch manifest is described in [section 8](@ref scripts_rl_ops_fetch_manifest).

## 8\. File schemas

### Task record {#scripts_rl_ops_task_record}

Written by `run_task --record` (and `cluster compare --record`):

```json
{"record_version": 1, "mode": "task|compare", "task_index": 0, "task_id": "row/train-seed-101",
 "host": "...", "started_at": "...", "ended_at": "...",
 "steps": [{"id": "...", "kind": "train", "action": "executed|skipped",
            "exit_code": 2, "tolerated": true}],
 "exit_code": 0}
```

- `task_index` and `task_id` are `null` in compare mode.
- A skipped step records `exit_code: null` and `tolerated: null`.

### Benchmark record {#scripts_rl_ops_benchmark_record}

`benchmark/task-NNNN.json`, `benchmark_version: 2`:

| Field | Content |
|---|---|
| `benchmark_version`, `measured_at` | Schema version and time. |
| `host` | `system`, `machine`, `cpu_count`, `python_version`. |
| `plan` | `root`, `matrix_name`, `matrix_sha256`. |
| `task_index`, `task_id` | The measured task. |
| `sampling` | `method: ps-process-tree`, `interval_s`, `note`. |
| `package_versions` | Installed package versions. |
| `steps` | One entry per step (below). |

Every step has `id`, `kind`, `exit_code`, `tolerated`, `manifest_status`,
`wall_seconds`, `peak_tree_rss_kb`, `peak_process_count`,
`peak_single_process_rss_kb` and `samples` (plus `measurement_error` when `ps`
failed).

Train steps add:

| Field | Meaning |
|---|---|
| `requested_timesteps`, `n_steps`, `effective_timesteps` | `effective = ceil(requested / n_steps) * n_steps`, because rollouts run whole. |
| `seconds_per_timestep` | Wall ÷ effective timesteps. **Includes** the model-selection evaluations and the PPO updates. |
| `scenario_identity`, `selection`, `eval_every_steps`, `eval_episodes` | Used by `estimate` to match target rows. |
| `training_episodes`, `selection_episodes`, `episode_seconds_sum` | From the episode manifests. |
| `non_episode_seconds` | Wall − episode sum, which combines Python start-up, PPO updates and the gaps between simulator launches. Do not report it as launch overhead. |

Evaluate steps add `episodes_expected`, `episodes_completed` and
`seconds_per_episode`.

### Estimate output {#scripts_rl_ops_estimate_output}

`estimate_version: 2`:

| Field | Content |
|---|---|
| `created_at` | Time written. |
| `benchmark` | `task_id`, `task_index`, `measured_at`, `seconds_per_timestep`, `seconds_per_episode`. |
| `target_matrix` | `path`, `sha256`, `name`. |
| `safety_factor` | As given. |
| `task_count`, `estimated_task_count` | All tasks, and tasks in estimated rows. |
| `rows` | Per row: `name`, `tasks`, `per_task_seconds`, `reason`, `selection_differs`, `warning`, `per_task_with_safety_seconds`, `per_task_with_safety_hms` (`HH:MM:SS`). |
| `memory` | `peak_tree_rss_kb` is the largest measured `peak_tree_rss_kb` over the benchmark's steps; `with_safety_kb` is that times the safety factor. Both are `null` only when no step's memory was measured. |
| `totals` | `serial_seconds`, `serial_with_safety_seconds`, `serial_with_safety_hms`. |
| `assumptions` | `{"linear_in_timesteps": true, "measured_on": "<system> <machine>", "is_cluster_estimate": false}` |

`is_cluster_estimate` is always `false`; a measurement taken on a laptop (for
example on macOS) does not describe the cluster. The output has no queue, ETA or
throughput figure.

### Study spec {#scripts_rl_ops_study_spec}

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

Every key is validated before anything is launched. Unknown keys at any level
are refused, naming the valid ones.

| Key | Rule |
|---|---|
| `study_version` | `1`. |
| `name` | Non-empty string. |
| `matrix` | Path to a matrix; a relative path is resolved against the mesh root. The matrix must set `seeds.model_selection` and `training.total_timesteps`, and satisfy `0 < training.eval_every_steps <= total_timesteps` (otherwise no model selection runs and every objective is `null`). |
| `row` | Must exist in the matrix. |
| `training_seed` | One of the matrix's `seeds.training`, which `load_matrix` has already checked is disjoint from the model-selection and held-out seeds. |
| `trainer` | Default `maskable_ppo`; unsupported trainers are refused. |
| `sampler.type` | `tpe`. |
| `sampler.seed` | Integer in [0, 2**32 - 1]. |
| `sampler.n_startup_trials`, `sampler.n_ei_candidates` | Positive integers; defaults 10 and 24. |
| `sampler.multivariate` | Boolean; default `false`. |
| `n_trials` | Positive total attempt budget. No fixed cap (such as 50) is imposed. |
| `search_space` | Non-empty; keys from the table below. |

Search-space entries are `{"type": "categorical", "choices": [...]}` or
`{"type": "int"|"float", "low", "high", "log"}`:

- Choices are a non-empty list of distinct scalars.
- Ranges need finite `low < high`; `int` ranges need integer bounds;
  `log: true` requires `low > 0`.
- Each choice and each range bound must pass the parameter's own value rule.
- `total_timesteps` is refused with its own message: the budget is fixed per
  study and comes from the matrix.
- Any other name is refused as not wired to the trainer; the message lists the
  searchable parameters.

Searchable parameters (`agents.config.PPO_SEARCH_PARAMETERS`):

| Parameter | Types | Value rule |
|---|---|---|
| `n_steps` | `int`, `categorical` | Integer ≥ 2. |
| `batch_size` | `int`, `categorical` | Integer ≥ 2. |
| `n_epochs` | `int`, `categorical` | Integer ≥ 1. |
| `gamma` | `float` | Range inside `(0, 1]`. |
| `ent_coef` | `float` | `low ≥ 0`. |
| `ent_coef_final` | `float` | ≥ 0. |
| `learning_rate` | `float` | > 0. |
| `target_kl` | `float` | > 0. |
| `gae_lambda` | `float` | > 0 and ≤ 1. |
| `clip_range` | `float` | > 0 and ≤ 1. |

Network architecture (`net_arch`) is not searchable; it remains an explicit
matrix setting.

### Trial and study records

```
<output-root>/study_manifest.json
<output-root>/study-checkpoint.bin
<output-root>/trials/trial-0000/trial.json
<output-root>/trials/trial-0000/train/<row>/train-seed-<S>/   (train.py's own output)
```

`trial.json`, `trial_version: 2`:

- `number`, `params`, the configured `training` block, `module`, `args`,
  `train_dir`, `state` (`running`/`complete`/`failed`), `objective`, `failure`,
  `exit_code`, `started_at`, `ended_at`, and the launched process identity.
- Before command construction, `training` is empty and the command and path
  fields are unset. A construction failure keeps that record with its reason.

`study_manifest.json`, `study_manifest_version: 2`, rewritten atomically after
every trial:

| Field | Content |
|---|---|
| `status` | `running`, `completed`, `failed` or `interrupted`. |
| `spec` | Path, sha256, body. |
| `matrix` | Path, sha256, name. |
| `row` | Tuned row. |
| `seed_roles` | `training`, `model_selection`, `held_out_used: false`. |
| `objective`, `sampler`, `fixed_training` | Objective description, resolved sampler settings, fixed training values. |
| `optuna_version`, `package_versions`, `python_version`, `platform`, `sim_binary` | Environment. |
| trial records, `best` | Per-trial records and the best trial. `best.training` is the matrix training block with sampled values, ready to copy by hand into a new matrix file. |
| `started_at`, `ended_at`, `resume_events` | Timing and resume history. |

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

`cluster/` sits outside every guarded step directory, so nothing written there
can block a train or evaluate run.

`cluster/tasks.json` is `{"tasks_version": 1, "plan_sha256", "tasks": [{index,
id, train_id, evaluate_id}]}`. An existing file describing a different plan is
refused, not overwritten.

### Receipt

One receipt per submission, `cluster/receipts/NNNN.json`:

```json
{"receipt_version": 2, "kind": "tasks", "submission": "0001", "state": "submitting|submitted|submit_uncertain|abandoned",
 "created_at": "...", "host": "...", "user": "...",
 "job_name": "meshops-<32 hex chars>-tasks", "indices": [0, 1],
 "array_spec": "0-1", "plan_sha256": "...", "cluster_config": {…},
 "cluster_config_sha256": "...", "script": "...", "argv": [ … ],
 "job_id": null, "compare": null, "cancel_requests": [], "human_assertions": []}
```

- `compare`, when present, holds `{"job_name", "job_id", "state", "created_at",
  "script", "argv", "depends_on"}` with the same state values and its own random
  job name.
- Compare-only submissions use `kind: "compare"`, `indices: []`, a null array
  job, job name and script, and top-level `state: "not_applicable"`. Their job
  intent is in `compare`. They keep the same config and plan provenance.
- `cancel_requests` gains an entry only after a successful `scancel`.
- `human_assertions` records each `--inactive-job` and `--abandon-intent`
  assertion with the asserting account and time.

### Fetch manifest {#scripts_rl_ops_fetch_manifest}

`<dest>/fetch_manifest.json`, version 2:

```json
{"fetch_manifest_version": 2, "remote": "...", "selection": ["manifests"],
 "argv": [], "fetched_at": "...", "transfer_mode": "new_destination",
 "files_may_be_stale": false, "inventory_scope": "destination",
 "state_basis": "local_manifests",
 "files": [{"path": "...", "bytes": 0, "sha256": "..."}],
 "tasks": [{"index": 0, "id": "...", "state": "running"}],
 "comparison": "not_fetched", "snapshot_of_incomplete_run": true}
```

| Field | Meaning |
|---|---|
| `transfer_mode` | `new_destination` or `add_missing`. |
| `fetched_at` | When this inspection was recorded, not the transfer time of each file. |
| `files` | Inventory of the whole destination, including files kept from earlier copies, excluding current and rotated fetch manifests. |
| `tasks` | Per-task state from the copied local manifests (below). |
| `comparison` | `not_fetched` unless selected; then `absent`, `complete`, `incomplete` or `unreadable`. `absent` refers to the local inventory only. |
| `snapshot_of_incomplete_run` | `null` when task state cannot be inspected; otherwise whether any copied task is not completed. |

A successful update keeps the previous manifest as `fetch_manifest.<n>.json`;
older version-1 history stays intact. Inspection rebases step output paths in
memory without changing the copied plan.

Task states describe **copied local manifests**, not live scheduler state:

| State | Meaning |
|---|---|
| `completed` / `partial` | Copied evaluation reports that status. |
| `running` | Copied training or evaluation reports running; it may be stale. |
| `failed` | Copied training or evaluation explicitly reports failed/interrupted. |
| `missing` | Neither step directory exists locally. |
| `incomplete` | Other unfinished, unreadable, or unrecognized copied state. |
| `not_fetched` | The current transfer did not select `manifests`. |

## 9\. Cluster submission and states {#scripts_rl_ops_cluster_states}

### Receipts and the submission protocol

`submit`, `resume` and `submit-compare` follow the same order:

1. **Lock.** Create `cluster/submit.lock` with `O_CREAT|O_EXCL`. An existing lock
   is a refusal that prints the holder's pid, host and time. Ownership is checked
   before locking and again under the lock. `plan`, cancellation, and local and
   scheduled comparison use this lock too. The lock is released in a `finally`
   block. Remove a stale lock by hand after confirming no submit is running.
2. **Reconcile.** Recover any no-ID intents by exact job name, take a scheduler
   snapshot, apply any `--inactive-job` / `--abandon-intent` assertions,
   reconcile, and compute the indices. With no task indices, `resume` checks
   whether it can queue the comparison (`--no-compare` leaves it alone).
   `submit-compare` never computes a new task submission. A fresh scheduler
   check confirms coverage before a comparison is submitted.
3. **Write the intent.** Allocate `NNNN` by exclusive creation of the receipt
   file, then write the intent, including a random 128-bit job name
   (`meshops-<token>-tasks`), *before* `sbatch` runs, so an accepted job is
   never nameless.
4. **Submit.** Render the script, create the log and record directories, and run
   `sbatch --parsable …`. A parsed job id finalizes the receipt as `submitted`.
   A non-zero exit, an interruption, or an unparseable response may still follow
   scheduler acceptance, so the receipt is left as a `submit_uncertain` no-ID
   intent with a stderr excerpt, and the command exits 1. **It is never retried
   or abandoned automatically.**
5. **Queue the comparison.** Unless `--no-compare`, and only when every task is
   finished or covered by an active job, queue the compare job with
   `--dependency=afterany:<every active array job id>`; with all tasks finished
   it has no dependency flag. When some tasks are uncovered (for example after a
   `--tasks 0` canary) the command says so and queues no compare job.

If the array succeeds but the compare submission is refused or uncertain,
inspect `status`. `resume` recovers an accepted compare job by exact name and
does not duplicate it. An unaccepted no-ID compare stays blocked until the owning
user confirms it never reached SLURM and runs
`resume --abandon-intent NNNN:compare`. `submit-compare` can then queue the
comparison alone once every task is covered.

The `sbatch` argv is:

```
sbatch --parsable --no-requeue --job-name=J [--array=SPEC] --output=<log pattern>
[--dependency=…] [--partition=] [--account=] [--qos=] [--constraint=] --time= --mem=
--cpus-per-task= <script>
```

Each `null` config value omits its flag. `SPEC` is the compressed index list
(`0-7`, `1,3`), plus `%N` when `max_concurrent_tasks` is set.

### No-ID recovery

A no-ID intent is recovered by exact job name only:

- `squeue --name=…` and `sacct --name=…` are filtered for exact equality and
  their matches are merged.
- Accounting queries use an explicit start date before the intent's creation
  date, so recovery also searches prior days; unknown timestamps fall back to
  epoch. Slurm otherwise limits name-only searches to today (see its
  [accounting time-window documentation](https://slurm.schedmd.com/sacct.html#SECTION_DEFAULT-TIME-WINDOW)).

| Matches across both queries | Result |
|---|---|
| Exactly one | The job id is written back, even if the other query failed. |
| Several | Reported as ambiguous; nothing is written. |
| Zero | The intent stays unresolved and keeps blocking resubmission. An empty or failed query does not show that `sbatch` failed. |

### Human assertions

Two `resume` assertions can clear a blocker. Both are recorded in the receipt
with the asserting account and time.

| Assertion | Meaning | Refused when |
|---|---|---|
| `--inactive-job <job id>` | A known-id job is no longer active. | No receipt holds that id, or the scheduler still shows it active. |
| `--abandon-intent NNNN:tasks` or `NNNN:compare` | A no-ID submission never reached SLURM. | That element is not an unresolved no-ID intent, or the job name still matches a job. |

Neither assertion overrides a positive active-job observation or a populated
step directory; the filesystem rules still apply afterward. `status` never
writes anything.

### Reported states

Eight states; the first matching rule wins. `unsubmitted` (never submitted) is
separate from `pending` (queued).

| State | Rule |
|---|---|
| `pending` | a covering receipt's element is `PENDING`, `CONFIGURING`, or `REQUEUED` |
| `running` | a covering receipt's element is in another active state (`RUNNING`, `COMPLETING`, `SUSPENDED`, `RESIZING`, `SIGNALING`, `STAGE_OUT`) |
| `completed` | train `done` and evaluate `done` |
| `partial` | train `done` and evaluate `partial` |
| `unknown` | Any of the cases listed below the table |
| `canceled` | the latest covering receipt's element is `CANCELLED` in accounting |
| `failed` | Any of the cases listed below the table |
| `unsubmitted` | no receipt covers the task and both step directories are `pending` |

A task is **`unknown`** when:

- a receipt covers it and the queue query failed;
- an unresolved no-ID intent covers it;
- a submitted element is absent from the queue and accounting holds no
  terminal record for it;
- accounting says `COMPLETED` while the filesystem is incomplete; or
- no receipt covers it and its train manifest says `running`.

A task is **`failed`** when:

- the latest covering receipt's element has an explicit terminal failure in
  accounting;
- no receipt covers it and a step directory is `blocked`; or
- every known job id of an otherwise-`unknown` task carries a recorded
  `--inactive-job` assertion (the row then also reports
  `asserted_inactive: true`).

- Each row carries a `detail`: the scheduler state and reason, the blocked
  directory's `move or delete <dir> to retry` message, or why it is unknown. A
  queued row adds the scheduler's estimated start when it is not `N/A`.
- A recorded cancellation request alone does not count as termination.
- Unrecognized scheduler states stay `unknown`.
- Array elements are reconciled only by exact `<array_job_id>_<index>` records; a
  parent-array accounting row does not mark elements finished, so they stay
  `unknown`.
- JSON status uses `status_version: 2` for these rules.

The compare row uses the same active/terminal logic over the latest compare job,
plus the state inside `comparison.json`: `complete` maps to `completed`,
`incomplete` to `partial`, and absent with no compare job to `unsubmitted`.

### Resume rules

A task is resubmitted only when all of these hold:

- its state is `unsubmitted`, `failed` or `canceled`;
- no element of it is active in any receipt;
- every step the runner would execute is `pending` on disk. Train `done` plus
  evaluate `pending` qualifies, because the runner skips the finished train.

A task blocked by a dirty directory is listed as not submitted with
`move or delete <dir> to retry`. This tool never deletes or renames anything.
`unknown` is never resubmitted without one of the recorded human assertions.

### Cancellation

- `cancel --tasks 2,5` resolves the selection to exact
  `<array_job_id>_<index>` element ids from the receipts and never passes a
  parent array id, so sibling tasks are untouched.
- `cancel --submission 0001` targets that receipt's whole active array plus its
  compare job.
- Jobs absent from the receipts are never selected.
- A failed `scancel` is reported on stderr with exit 1 and **no cancellation is
  recorded**; only a successful call appends to `cancel_requests`.
- A failed queue query is a refusal with exit 1, including under `--dry-run`,
  because active elements cannot be resolved without it. Nothing is canceled or
  recorded.

### Only one writer of comparison.json

- Local and scheduled comparisons hold the operation lock from their receipt
  checks until their managed child process has stopped and been reaped.
  Cancellation cannot race receipt recovery, and two cooperating comparison
  commands cannot write together.
- If a compare response is lost after the array is queued, the unresolved intent
  blocks another submission; use the recovery paths above.
- Before a new compare job is queued (by `submit` or `resume`), an earlier
  compare job that is still active is canceled. The `scancel` call must succeed
  and a fresh queue snapshot must show no remaining blocker; otherwise the new
  compare job is refused.
- `submit-compare` and local comparison refuse existing writers instead of
  canceling them.

A compare job blocks both of these while it is active, while it is an
unresolved no-ID intent, or (for any non-abandoned compare job with a job id)
until there is evidence it has terminated:

- a recognized terminal state in the queue/accounting snapshot: `COMPLETED`,
  `CANCELLED`, `FAILED`, `TIMEOUT`, `NODE_FAIL`, `OUT_OF_MEMORY`, `PREEMPTED`,
  `BOOT_FAIL`, `DEADLINE` or `REVOKED`; or
- a recorded `resume --inactive-job <compare job id>` assertion.

A successful `scancel` records a request and is not terminal evidence. Unknown
states stay blockers. A failed queue query blocks on its own once any compare
element exists. Where `sacct` accounting is unavailable, a compare job that has
left the queue keeps blocking until the human asserts it inactive.

## 10\. Local batch execution {#scripts_rl_ops_batch}

Version 2 batches (plan v3) are executed locally by `local.py` and resumed
through `recovery.py`. This is implemented and covered by `test_ops_local.py`
and `test_ops_recovery.py` on the fake simulator; no native batch has been run. The commands above keep operating on version 1 plans
(plan v2) and their cluster callers are unchanged. Cluster execution of
version 3 task kinds is deferred.

| Owner | Responsibility |
| --- | --- |
| `local.py` | The only local queue/scheduler for plan v3: bounded workers, per-task attempt logs, 30-second progress and `campaign_status.json`. Reuses `process.py` and `measurement.py`. |
| `batch_processes.py` | The root lock, owned process groups and the optional shared slot pool (`execution.resource_pool`). |
| `batch_receipts.py` | Task receipts under `state/steps/`, accepted-output verification and write-once model bindings. |
| `batch_identity.py` | Runtime identity pinning and checks. |
| `recovery.py` | Attempt selection and recovery proposals under `state/recovery/`; checkpoint recovery from verified post-update checkpoints only. |
| `tasks.py`, `task_execution.py`, `run_task.py` | Legacy pair mode unchanged. Plan v3 steps run by ID from an allowlisted dispatch table (`tasks.STEP_MODULES`: `scripts.rl.train`, `scripts.rl.operate`, `scripts.rl.compare`). `run_task --step <id> --attempt <A>` is the worker entry point the scheduler launches. `task_execution.run_step` substitutes placeholders as whole arguments and holds the pool slot while the child runs. |

Records written (version numbers are in [Contributing](@ref Contributing)):

| Record | Path |
| --- | --- |
| Runtime identity (`RUNTIME_IDENTITY_VERSION`) | `runtime_identity.json` |
| Receipts (`BATCH_STEP_VERSION`) | `state/steps/<key>.json` |
| Bindings, written once through `policy/bundle.py` `bind_model` | `state/bindings/<producer-key>-<checkpoint>.json` |
| Recovery proposals (`BATCH_RECOVERY_VERSION`) | `state/recovery/<id>.json` |
| Batch status (`CAMPAIGN_VERSION`) | `campaign_status.json` |
| Resource samples | `resources.jsonl` |
| Attempt logs and leases | `local/<key>/attempt-<A>.{log,lease.json}` |
| Shared pool (`RESOURCE_POOL_VERSION`) | `pool.json` with `slot-<i>` locks, in the pool directory |

The receipt states, batch states, resume procedure and worker limits are
specified once, in the
[batch experiment reference](@ref mesh_sim_rl_batch_states).

## 11\. Internals

### Module map

| Owner | Responsibility |
| --- | --- |
| `tasks.py` | Task mapping and filesystem state; imports the experiment policy owner. |
| `task_execution.py` | Execute tasks/comparison and write operational records. |
| `process.py` | Launch, stop and reap experiment process groups, including descendants. |
| `measurement.py` | Task timing, process-tree sampling and completion evidence. |
| `estimation.py` | Estimate eligible matrices from complete measurements. |
| `retrieval.py` | Fetch categories (`CATEGORY_INCLUDES`), transfer and fetch manifest. |
| `local.py`, `recovery.py`, `batch_*.py` | Plan v3 batch execution; see [section 10](@ref scripts_rl_ops_batch). |
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

- `run_task.py`, `benchmark.py`, `tune.py`, `cluster.py` and `fetch.py` parse
  commands and delegate. Writing an operational record belongs in the operation
  owners, not in argument parsing.
- `ops/slurm.py`, `ops/receipts.py` and `ops/reconcile.py` delegate to the
  cluster owners for existing callers. The command paths and existing
  task/tuning helper imports remain available.

### Why the compare job depends with afterany

The comparison is one separate job submitted with
`--dependency=afterany:<every active array job id>`. Correctness comes from a
filesystem prerequisite check inside the compare runner, not from scheduler exit
codes: `afterok` on an array with one failed element never clears, even after
that element is resubmitted as part of a later array. `afterany` only orders the
jobs; `compare_prerequisites` decides whether a comparison may be written.

### Optuna pin

Optuna is pinned in `requirements-tuning.txt` and kept out of
`requirements.txt`. Training manifests record the direct dependency set, so
adding a tuner there would change every manifest and make the cluster venv carry
a package no job imports. The study owner imports Optuna lazily; a missing
install or a version other than the pin is a refusal naming both versions and the
install command. Nothing else in this package imports Optuna, and no cluster job
does.

### Add a trainer or parameter

- **Trainer.** The generic driver asks a trainer adapter to build a trial and
  read its objective; `MaskablePpoTrainer` is the available implementation.
  Another algorithm needs an actual trainer/command and an adapter declaring its
  searchable parameter types, validation, objective name/direction and command
  construction. Register it in `get_trainer`; do not add algorithm-name branches
  to the CLI or driver.
- **PPO parameter.** First wire the constructor, config validation, train CLI,
  training provenance, compatibility/comparison grouping and matrix translation.
  Then add the parameter to `agents.config.PPO_SEARCH_PARAMETERS`. A study JSON
  supplies ranges and choices only; it cannot make an unimplemented constructor
  parameter tunable.

### Extend retrieval

- Keep new artifact rules in `retrieval.py`, and document the category and its
  output owner on this page.
- Check the writer's actual directory layout first, including callback
  evaluation nesting.
- Update the local-rsync fixture with a small example and an expected
  selected/unselected result.
- Do not add a second category table to the CLI or repeat production rules in
  fake tests.
- When fetch manifest meanings change, update its version, the schema in
  [section 8](@ref scripts_rl_ops_fetch_manifest), and the state/history tests.

### Tests

The [operations test map](../tests/ops-tests.md) lists every task, benchmark,
tuning, cluster, fetch and batch test with its input and expected behavior.
Cluster commands are tested against a fake scheduler; live-site checks of flags,
permissions, filesystem locking and accounting latency are tracked in
`TODO-RL-OPS-1`.
