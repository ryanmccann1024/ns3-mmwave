# Experiment operations

Tools around an existing `experiment_plan.json`. Create the plan before executing a task or measuring it.

## Module map

- `tasks.py`: task mapping and filesystem state
- `run_task.py`: execute one task or comparison
- `benchmark.py`: measure one task and scale resource estimates
- `tune.py`: Optuna smoke experiments

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

### Why the compare job depends with `afterany`

The comparison is one separate job submitted with
`--dependency=afterany:<every active array job id>`. Correctness comes from a
filesystem prerequisite check inside the compare runner, not from scheduler
exit codes: `afterok` on an array with one failed element never clears, even
after that element is resubmitted as part of a later array. `afterany` only
orders the jobs; `compare_prerequisites` decides whether a comparison may be
written at all.

## Runner: `run_task.py`

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
- The objective is one deterministic episode on one model-selection seed at a
  smoke budget. **It ranks nothing reliably and is no evidence of learning.**
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
  "sampler": {"type": "tpe", "seed": 7},
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
  and `ent_coef` — the only knobs that reach `MaskablePPO` today.
  `total_timesteps` gets its own message: the budget is fixed per study and
  comes from the matrix. Any other name is reported as not wired, pointing at
  the open `TODO-RL-TUNE-1`.
- `n_steps` is `int` or `categorical` with distinct integer choices ≥ 2;
  `gamma` is a float range inside `(0, 1]`; `ent_coef` is a float range with
  `low ≥ 0`; `log: true` requires `low > 0`; every range needs `low < high`.
- `row` must exist in the matrix and `training_seed` must be one of the
  matrix's `seeds.training`, which `load_matrix` has already proven disjoint
  from the model-selection and held-out seeds.
- The matrix must set `seeds.model_selection` and `training.total_timesteps`,
  and satisfy `0 < training.eval_every_steps <= total_timesteps` — otherwise no
  model selection ever runs and every objective would be `null`.
- `sampler.type` must be `tpe` with an integer `seed`; `1 <= n_trials <= 50`.
- An `--output-root` already holding `study_manifest.json` or `trials/` is
  refused: studies are not resumed, so choose a new root.
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

The sampler is `TPESampler(seed=<spec seed>, n_startup_trials=10)`, and that
constant is recorded in the manifest. With ten or fewer trials every draw is an
objective-independent startup draw, so `--dry-run` asks `min(n_trials, 10)`
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
<output-root>/trials/trial-0000/trial.json
<output-root>/trials/trial-0000/train/<row>/train-seed-<S>/   (train.py's own output)
```

`trial.json` holds `trial_version`, `number`, `params`, the resolved full
`training` block, `module`, `args`, `train_dir`, `state`
(`complete`/`failed`), `objective`, `failure`, `exit_code`, `started_at`, and
`ended_at`.

`study_manifest.json` is rewritten atomically after every trial with
`study_manifest_version`, `status` (`running`/`completed`/`failed`), the `spec`
(path, sha256, body), the `matrix` (path, sha256, name), `row`, `seed_roles`
(`training`, `model_selection`, `held_out_used: false`), the `objective`
description, `sampler`, `fixed_training`, `optuna_version`,
`package_versions`, `python_version`, `platform`, `sim_binary`, the per-trial
summaries, `best`, `started_at`, and `ended_at`. `best.training` is a full
resolved training block, ready to be copied by hand into a new matrix file —
nothing edits a matrix automatically.

### Optuna pin

Optuna is pinned in `requirements-tuning.txt` and deliberately kept out of
`requirements.txt`: the training manifests record the direct dependency set, so
adding a tuner there would change every manifest and force the cluster venv to
carry a package no job imports. `tune.py` imports Optuna lazily; a missing
install or a version other than the pin is a refusal naming both versions and
the install command. Nothing else in this package imports Optuna, and no
cluster job does.

