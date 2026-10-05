# Experiment operations

Tools around an existing `experiment_plan.json`. Create the plan before executing a task or measuring it.

## Module map

- `tasks.py`: task mapping and filesystem state
- `run_task.py`: execute one task or comparison
- `benchmark.py`: measure one task and scale resource estimates

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

