# Batch experiment reference {#mesh_sim_rl_batch_reference}

[TOC]

The single detailed reference for RL experiment batches: the matrix version 2
fields, path rules, commands, launcher, plan and task identity, output layout,
task and batch states, recovery, operation protocols, schedules, selection
rules, worker limits, and the replacements for the retired campaign commands.
The worked workflow is \ref mesh_sim_rl_experiments "Experiments and
operations". Saved-file schema versions are owned by
\ref Contributing "Contributing"; this page names the version fields but does
not restate their current numbers except where a value is something you write
into a matrix.

Paths are relative to `scratch/mesh-sim/`.

## 1\. Implementation status

This page is written from the source and from actual `--help` output of every
subcommand (re-read 2026-10-29 for the second documentation pass). It
describes the implemented batch contract. Source inspection and
the owners' synthetic tests are not native execution: no version 2 batch has
been run against the real simulator.

| Area | Owner | Status |
|---|---|---|
| Matrix v1 and v2 validation, plan v3, task keys, destinations | `scripts/rl/experiments/{config,plan,selection}.py` | Implemented; documented from source. |
| `validate`, `plan`, `run`, `status`, `resume` parsers | `scripts/rl/experiment.py` | Implemented; flags checked against `--help`. |
| Launcher | `scripts/rl/run-experiments.sh` | Implemented; `--help`, `validate` and `--dry-run` executed. |
| Training options | `scripts/rl/train.py m-ppo` | Implemented; flags checked against `--help`. |
| Operations, schedules, online protocols, replay gate, reward audit, scripted baselines | `scripts/rl/policy/{operation,online_adaptation,schedules,replay_gate,reward_audit,scripted}.py` | Implemented library owners; documented from source. |
| Operation CLI that plan tasks call | `scripts/rl/operate.py` | Implemented; every subcommand's flags checked against `--help` (section 10.4). The standalone `preflight` subcommand probes one seed and INI (section 6.9). |
| Local scheduler, status, root lock and shared worker pool | `scripts/rl/ops/local.py` and `batch_processes.py` | Implemented; documented from source (constants, states, file names, exit codes). |
| Identity checks, task receipts and recovery | `scripts/rl/ops/batch_identity.py`, `batch_receipts.py` and `recovery.py` | Implemented; documented from source. |
| Curves, reviews, comparison views, scenario index, reward summaries, selection evidence | `scripts/rl/experiments/reporting.py` | Implemented; documented from source. |

No native simulator run of a version 2 batch has been executed. The public
example's native smoke is a human-run check and is BLOCKED until executed.

## 2\. Commands {#mesh_sim_rl_batch_commands}

`scripts.rl.experiment` (or the launcher in section 3) has five subcommands:

```text
validate --matrix M [--rows R]
plan     --matrix M [--output-root O] [--sim-binary B] [--rows R]
run      --matrix M [--output-root O] [--sim-binary B] [--rows R] [execution flags]
status   --output-root O [--json]
resume   --output-root O [--sim-binary B] [--prepare-only] [execution flags]
```

| Subcommand | What it does | Needs a binary | Writes |
|---|---|---|---|
| `validate` | Validates the matrix, its assets and contracts, and prints the exact task expansion (one line per task with its short key). | No | Nothing. |
| `plan` | Validates, hashes the binary and every input without launching anything, refuses a stale binary, and writes the immutable `experiment_plan.json`. | Yes | The plan only. |
| `run` | `plan`, then hands the root to the local scheduler. | Yes | Plan and results. |
| `status` | Reports every task's state. Plan v3 roots ask the scheduler's status owner; plan v2 roots use the legacy step state. | No | Nothing. |
| `resume` | Plan v3 roots only: recovery for an interrupted batch. A legacy plan v2 root is refused and keeps its "move or delete `<dir>` to retry" rule. | The recorded one | A recovery proposal, then new attempts. |

**Flags** (from `--help`):

| Flag | Subcommands | Meaning |
|---|---|---|
| `--matrix M` | `validate`, `plan`, `run` | Matrix JSON file. Required. Its `matrix_version` (1 or 2) selects the validator. |
| `--rows R` | `validate`, `plan`, `run` | Comma-separated row names; omitted means every row. Version 2 refuses unknown names and a filter that splits the candidates of a selection stage. |
| `--output-root O` | `plan`, `run` (optional); `status`, `resume` (required) | Root for the plan and results. Omitted on `plan`/`run`: a fresh `outputs/<YYYY-MM>/<DD>/<HH-MM-SS>-<name>/` (with `-<row>` when exactly one row is selected), printed as `Experiment output: ...`. |
| `--sim-binary B` | `plan`, `run`, `resume` | An existing simulator executable. On `resume` it means the same binary identity at another path; omitted means the recorded binary. |
| `--json` | `status` | Machine-readable status. |
| `--prepare-only` | `resume` | Write the recovery proposal and launch nothing. |
| `--workers N` | `run`, `resume` | Concurrent tasks; default 1. |
| `--threads-per-worker N` | `run`, `resume` | Numerical threads per task; default 1. |
| `--failure-policy <policy>` | `run`, `resume` | `continue` (default) finishes independent tasks; `stop` dispatches no more. |
| `--nice N` | `run`, `resume` | Child niceness 0–19; default 0. |

**Execution settings** resolve CLI > matrix `execution` > defaults (1 worker,
1 thread, `continue`, nice 0), and the resolved value records its source
(`cli`, `matrix` or `default`). Execution flags are refused for a version 1
matrix, whose plan always runs sequentially. `recovery` and `resource_pool`
come only from the matrix.

**Binary precedence.** `--sim-binary` > `MESH_SIM_BIN` > error (`no simulator
binary: pass --sim-binary or set MESH_SIM_BIN`). No tool guesses a binary or
builds one. For version 2, `plan` and `run` require an existing executable
file and refuse a binary older than any of `sim.cc`, `src/**/*.cc` or
`src/**/*.h`, naming one stale source. Rebuilding is a human action, from the
`ns3-mmwave` root: `./ns3 build scratch/mesh-sim/sim`. A version 1 `plan`/`run`
also accepts `MESH_SIM_BIN` but, as before, does not check that the path
exists.

A missing binary argument keeps the version 1 argparse exit code 2; version 2
reports a validation error with exit code 1.

**Exit codes.**

| Code | Meaning |
|---|---|
| `0` | Success. |
| `1` | Validation, input or I/O error, or a missing scheduler owner; the reason is printed as `<ErrorType>: <message>` on stderr. |
| `2` | Command-line usage error (argparse). |
| Scheduler code | `run` and `resume` return the scheduler's code (`ops/local.py`): `0` when the batch ends `completed` or `completed_with_warnings`, `130` when it ends `interrupted` (after SIGINT/SIGTERM, once owned process groups are stopped and reaped), `1` otherwise (a failed batch, an identity refusal, a held root lock, or a conflicting pool capacity). `resume --prepare-only` returns `0` after writing the proposal. |

Exit code 2 from an `evaluate`, operation or `compare` child is a recorded
warning, not a failure; see section 9.

## 3\. The launcher: run-experiments.sh {#mesh_sim_rl_batch_launcher}

`bash scripts/rl/run-experiments.sh [--dry-run] <command> [options]` is the
maintained entry point. It is Bash 3.2 compatible and does only this:

1. With no arguments, prints usage and exits 1; with `-h`/`--help` as the
   first argument, prints usage and exits 0 without needing the venv or a
   binary. `<command> --help` is forwarded to Python.
2. Makes `--matrix`, `--output-root` and `--sim-binary` values absolute
   against the **invoking** directory, in both `--flag value` and
   `--flag=value` forms, preserving spaces and other characters. It does the
   same for an environment `MESH_SIM_BIN` and `MESH_SIM_ROOT`. No other
   argument and no JSON content is reinterpreted.
3. Finds the mesh root from the script's own location (the first ancestor with
   `sim.cc` and `scripts/rl/`), or from `MESH_SIM_ROOT`, which must name a
   valid root.
4. Requires `<mesh-root>/.venv/bin/python`; if it is missing, exits 1 and
   names `python3 scripts/rl/bootstrap_venv.py`.
5. `cd`s to the mesh root and `exec`s
   `.venv/bin/python -u -m scripts.rl.experiment <arguments>`, so Ctrl-C and
   the exit code reach the Python command directly.

`--dry-run` (anywhere in the arguments) prints `Preview only; command not
executed:` and the shell-escaped `cd -- <root> && [MESH_SIM_BIN=...] <python>
-u -m scripts.rl.experiment ...` line, then exits 0 without starting Python.
The launcher never builds, schedules, retries, sets thread variables, or
chooses scientific settings.

## 4\. Matrix versions

| `matrix_version` | Plan written | Owner | Reference |
|---|---|---|---|
| 1 | Experiment plan v2: sequential train/evaluate/compare steps, state from step directories | `policy/experiment.py` (facade) and `experiments/config.py` helpers | \ref scripts_rl_comparing_policies "Comparing policies and running an experiment matrix" |
| 2 | Experiment plan v3: task graph with SHA-256 task keys and receipts | `experiments/{config,plan,selection}.py` | This page |

Version 1 behavior, public helper names and cluster callers are unchanged. The
rest of this page describes version 2.

## 5\. Path resolution {#mesh_sim_rl_batch_paths}

| Path | Resolves against |
|---|---|
| CLI `--matrix`, `--output-root`, `--sim-binary`, `MESH_SIM_BIN` | The invoking directory (the launcher normalizes them before changing directory; direct Python runs from the mesh root). |
| Version 2 matrix fields: `run_config`, `configs`, `rows[].configs`, `reference.path`, `baselines.import_from`, `history_sources`, `curriculum`, `continue_from.run_dir`, `model_source.run_dir`, check `source.path`, `execution.resource_pool.directory` | The **matrix file's directory**. `~` is expanded; absolute paths are kept. |
| Version 1 matrix paths | The mesh root, as before. |
| `nodes_file`, `buildings_file`, `jammers_file` inside an INI | The INI's own directory (native INI rule). Conversion never rewrites an INI. |

Input paths must exist (a file, or a directory for run directories and
history sources). `execution.resource_pool.directory` is an output path: a
relative path containing `..` is refused as unsafe. The plan records each
resolved path, its SHA-256 and the original reference text.

## 6\. Matrix version 2 fields {#mesh_sim_rl_batch_fields}

Unknown keys, duplicate names, a list where a single value is required
("rows are explicit; no product expansion"), and inconsistent settings fail
validation with the offending path, for example `row raw-delivery.training`.
Names (`name`, scenario slugs, row, profile, operation, check, stage and
candidate names) match `[a-z0-9][a-z0-9-]*`.

### 6.1 Top level

| Key | Required | Contract |
|---|---|---|
| `matrix_version` | yes | `2`. |
| `name` | yes | Slug; also the automatic output-root label. |
| `description` | no | String. |
| `kind` | yes | `train`, `checks` or `evaluate` (section 6.12). |
| `scenarios` | yes | Slug → scenario object; at least one. |
| `seeds` | no | Seed roles; missing roles normalize to empty. |
| `training` | `train` only | Shared training settings; refused for other kinds. |
| `evaluation` | `train`, `evaluate` | `{operations, comparison?}`; refused for `checks`. |
| `checks` | no | Registered checks. |
| `stages` | no | Finite named stages and optional selection. |
| `execution` | no | Worker, failure, nice, recovery and shared-pool settings. |
| `rows` | `train`, `evaluate` | Explicit rows; at least one. Optional for `checks`. |

### 6.2 `scenarios.<slug>`

| Key | Required | Contract |
|---|---|---|
| `run_config` | yes | The scenario INI. Also the explicit fallback when no `configs` entry matches. |
| `band` | no | `mmwave`, `sub-6` or null (native resolution). |
| `configs` | no | `{<seed role>: {"<seed>": <ini path>}}`. A seed's INI is looked up by role and key: the row's own `configs` first (section 6.12), then these, then `run_config`. The plan records `config_source` (`row`, `scenario` or `run_config`) and marks the last `fallback: true`. |
| `case` | no | Case metadata (section 6.3). |
| `reference` | no | `{kind, path}` (section 6.4). |
| `baselines` | no | Baseline policies (section 6.5). |
| `history_sources` | no | Array of existing directories; recorded by path for the reporting owner. |

### 6.3 `case`

| Key | Required | Contract |
|---|---|---|
| `mission`, `environment` | yes | Slugs. |
| `peers` | yes | Integer ≥ 1. |
| `coverage_target` | no | In (0, 1]. Supplies a coverage schedule's target when the schedule omits it; a conflicting value is refused. |
| `reviewed_exception`, `exception_reason` | no | A reviewed exception needs a nonempty reason, and a reason needs the flag. |
| `seeds` | no | `{"<seed>": {"gate_s": <s>}}` assertions. Each gate must lie in `[0, duration_s)` of the INI that seed resolves to, on a decision boundary, and not before `control_start_s`. Metadata never overrides physics or scoring. |

### 6.4 `reference`

| `kind` | File format | Checks |
|---|---|---|
| `scenario_routes_v1` | `reference_version` 1: `routes: {node_id: [[x, y, z], ...]}`, optional `description`. Version 2 also allows `targets` (`{node_id: [x, y]}` or `[x, y, z]`), `reference_only` (boolean) and `radio_feasibility` (string). | Unknown keys are refused per version. Node IDs exist in the INI's nodes file; every point is finite and inside explicit `[rl]` bounds. |
| `mission_waypoints_v1` | `waypoints` (2-D or 3-D points), `node_order`, `start_after_failure`, optional `start_after_s` (≥ 0), `start_below_delivery` (in [0, 1]), `parallel` (boolean), `description` and `reference_version` (1, 2 or 3) — the fields `policy/scripted.py` `ScriptedMissionPolicy` reads. | Same node/bounds checks; `node_order` lists distinct waypoint nodes. |

The plan's reference record keeps the file's `version`.

No waypoint is guessed. Route legality in the native simulator is not proved
by validation; the replay gate or a separately run physical preflight checks it.

### 6.5 `baselines`

| Key | Required | Contract |
|---|---|---|
| `policies` | yes | Distinct entries from `hold`, `random_valid`, `scripted`, `geometric`, `optimization`. `scripted` needs a scenario `reference`. `geometric` and `optimization` are the existing placement planners (`policy/evaluate.py` `PLACEMENT_POLICIES`), run through the unchanged evaluate placement path. |
| `seed_role` | yes | `model_selection`, `diagnostic` or `held_out`; must have seeds. |
| `decision_records` | no | Boolean, default false. |
| `decision_record_seeds` | no | Optional seed list (needs `decision_records: true`): only these baseline seeds record decisions, as for operations (section 6.8). Hashed into the baseline's physical digest only when declared. |
| `import_from` | no | A file of verified imported controls; hashed into the plan. Never supplies placement baselines. |
| `planning_seed` | no | Placement policies only: the dedicated channel-planning seed, passed as `--planning-seed` (overrides the INI's `[baseline] planning_seed`, as `evaluate` does). Resolved before the episode by `scripts/baselines` and recorded separately from simulator and evaluation seeds. |
| `allow_seed_overlap` | no | Placement policies only; default false. Without it a planning seed equal to a declared seed is refused ("use a dedicated seed"). |
| `configs_scope` | no | `rows` (default): one baseline per distinct resolved INI across the scenario's rows. `scenario`: one baseline per declared seed on the scenario's own `configs`/`run_config`, as the historical campaigns ran their case controls; rows compare against those. Checks that source a baseline follow the same scope. |

Baselines run once per physical case, policy and seed, not once per reward row.
A placement baseline's physical digest also covers its planning seed and the
hash of the planner settings (`[baseline]` and engine sections plus the mapping
file bytes); its initial relocation to the plan stays distinct from scored
travel, as in `evaluate`.

### 6.6 `seeds`

Arrays (or seed-spec strings such as `"301-303"`) for `training`,
`model_selection`, `diagnostic` and `held_out`. Each list is distinct and all
roles are mutually disjoint; a row's own training seeds are also checked
against every evaluation role. Diagnostic seeds are not held out.
Model-selection data is never relabeled as confirmation data.

### 6.7 `training`

The validated PPO fields (`total_timesteps`, `n_steps`, `gamma`, `ent_coef`,
`learning_rate`, `batch_size`, `gae_lambda`, `clip_range`, `n_epochs`,
`target_kl`, `net_arch`, `ent_coef_final`) plus:

| Key | Contract |
|---|---|
| `eval_every_steps` | In-training validation cadence; > 0 needs `seeds.model_selection`. Required for a `best` selector. |
| `checkpoint_every_steps`, `keep_checkpoints` | Checkpoint cadence and retention (default retention 3). A numeric `at_steps` selector must be retained until its consumers finish. |
| `checkpoint_timing` | `standard` (default) or `after_update`. |
| `decisions_per_episode` | Optional assertion; must equal the decisions derived from the INI (`ceil(ticks / ticks_per_decision)`, mirroring the native loader). Never changes episode length. |
| `total_episodes` | Optional assertion: `total_episodes × decisions == total_timesteps`. |

`total_timesteps` is required for `train` and, for a continuation, includes
the parent's steps. `after_update` timing requires `eval_every_steps` 0, a
positive cadence that is a multiple of `n_steps` and of the episode length, a
budget that is a multiple of the cadence, and a parent count on a rollout
boundary; an impossible schedule is refused, never extended. Rows may override
any key in `training`.

With `standard` timing, validation refuses a remaining budget that SB3 would
overshoot to complete a rollout. Non-mission runs need a whole number of
`n_steps` rollouts. A native mission's exact-budget callback permits a partial
last rollout when its total budget is not a multiple of `n_steps`; that tail
is collected without an optimizer update. Validation does not silently extend
the requested training budget.

### 6.8 `evaluation`

`operations` is a non-empty array of operations with unique `id`:

| Key | Contract |
|---|---|
| `id` | Slug. |
| `mode` | `frozen_deterministic`, `frozen_sampled`, `online_gated_v1` or `online_sb3_v1` (section 10). |
| `seed_role` | `model_selection`, `diagnostic` or `held_out`; must have seeds. |
| `at_steps` | `train` only: distinct `final`, `best` or retained cumulative timesteps. Refused for `evaluate` (the row's `model_source` names the model). |
| `schedule` | Frozen modes only: `{kind, settings}` (section 11). |
| `online` | Required for online modes, refused otherwise (section 10.2). |
| `decision_records` | Boolean, default false. |
| `decision_record_seeds` | Optional seed list (needs `decision_records: true`); each seed must belong to the operation's seed role. Only those seeds record decisions, preserving the matrix version 1 `decision_record_seeds` meaning; omitted means every seed. |

Each operation gets a configuration digest over `{mode, schedule, online,
decision_records}`, plus `decision_record_seeds` only when it is declared (so
existing digests are unchanged). An online `n_steps` larger than any evaluation seed's
native episode is refused.

`comparison` (optional) is `{operation, allow_incomplete?}`. The named
operation must be an unscheduled frozen operation. `allow_incomplete: true`
lets the comparison run once its sources are terminal, as an explicitly
recorded incomplete view.

### 6.9 `checks`

| `kind` | Keys | Contract |
|---|---|---|
| `preflight` | Reserved; not accepted | Run the single-case capability probe with `python -m scripts.rl.operate preflight` and see the [policy operations guide](../../scripts/rl/policy/README.md) for arguments. Use `preflight_campaign` for campaign difficulty checks. |
| `replay_gate` | `id`, `scenario`, `seeds`, `source`, `applies_to?`, `comparison?`, `parent?`, `case?`, `contact_audit?` | Replays a saved trajectory; `source` is `{baseline, seed}` (a planned baseline) or `{path}` (an existing directory, which then accepts exactly one seed). See the replay contract below. |
| `reward_audit` | `id`, `scenario`, `method`, `row`, `source`, `applies_to?` | Reconstructs a reward; `row` must be a row of that scenario with a reward selection. |

For a replay gate, `comparison` defaults to `strict_v1` (identical fact keys).
`pre_contact_source_v1` ignores only the replay's new
`safety.boundary_contacted_slots` field when the saved source predates it.
`parent` uses the completed `model_source` format (`run_dir`, `model`): its ZIP
and training manifest are verified and hashed, and the live environment must
pass parent compatibility. Omitted, no parent is supplied. `case` uses the
scenario case format and defaults to that scenario's case; it preserves mission
and jammer-timing validation. `contact_audit` defaults to false; true preserves
the legacy boundary-contact evidence. Gate variant, case and audit flag enter
the task's existing `operation_digest`; the parent enters `model_source`.
The record is `replay_gate.json` version 2, with parent, case, compatibility,
boundary and event-timing evidence. `gate_passed` still reads versions 1 and 2.

`applies_to` is `{rows?, scenarios?}` (at least one, known names): the rows
and/or scenarios whose `train` and `operate` tasks need the check. Omitted, the
check gates every row of its own scenario. A check still runs once, in its own
scenario with its own seed configurations; dependents elsewhere reference the
same task, and declared check order is kept. A batch cannot depend on another
batch's check: a gate shared by two batches is declared in both.

Replay-gate checks expand to one task per checked seed. Every
check seed must be declared in some seed role. A failed check blocks dependent
training and operations. No free-form commands are accepted.

### 6.10 `stages` and selection

A stage is `{name, rows, needs?, selection?}`. Rows belong to at most one
stage, and once stages exist every row must belong to one. `needs` names
earlier stages only. `selection` is:

| Key | Contract |
|---|---|
| `rule` | `legacy-validation-profile-v1`, `legacy-mission-profile-v1`, `legacy-online-profile-v1` or `replay` (section 12). |
| `candidates` | At least two candidate names, each → a list of rows of this stage **or** a list of `{row, operation}` entries naming declared operations of those rows (on the row's one trained model; no training task is added). One selection never mixes the two forms. |
| `branches` | Candidate name → rows, or `{row, operation}` entries, of a later stage that needs this one, in the candidates' form. A row or entry is the branch of at most one selection. |
| `source_operation` | Row candidates under the mission and online rules only: the ranked operation. Refused for `{row, operation}` candidates, which use their own operations. Candidate operations never use `held_out` seeds and share one seed role; the online rule needs online modes. |
| `source_checkpoint` | Mission and online rules: `final` (default), `best` or a step count. The one checkpoint whose results feed the selection; it must be an operated checkpoint of every candidate. The `select` task sources exactly that checkpoint. |
| `normalization_decisions` | Validation rule only; that rule accepts row candidates only and takes no `source_operation`/`source_checkpoint`. |
| `retain` | Mission rule only: candidates kept independently of the winner; at least one candidate must still compete. |
| `winners`, `provenance` | `replay` only: the recorded winners and where they came from. |

### 6.11 `execution`

| Key | Contract |
|---|---|
| `workers`, `threads_per_worker` | Integers ≥ 1. |
| `failure_policy` | `continue` or `stop`. |
| `nice` | 0–19. |
| `recovery` | `none` (default) or `checkpoint`. `checkpoint` requires `after_update` training checkpoints. |
| `resource_pool` | `{directory, capacity}`: a shared slot pool across batches (section 15). |

### 6.12 `rows` and kind requirements

| Row key | `train` | `evaluate` | `checks` | Contract |
|---|---|---|---|---|
| `name`, `scenario` | required | required | required | Unique row name; declared scenario. |
| `profile` | required | optional | optional | Slug used in task identity. |
| `observation_preset`, `action_profile`, `reward_components`, `reward_weights`, `observation_parameters`, `reward_parameters` | required | optional (must match the parent's selection) | required | Existing selection validators and weight semantics; `action_profile` must equal the INI's. |
| `operations` | optional | optional | — | Subset of declared operation IDs; default all. |
| `training`, `seeds.training` | optional | — | — | Overrides; a row with no training seed is refused. |
| `configs` | optional | optional | — | Per-row INIs `{<role>: {"<seed or key>": <ini path>}}`, matrix-relative and hashed individually. `train` rows accept `training`, `model_selection`, `diagnostic` and `held_out`; `evaluate` rows the three operation roles. Seed keys must be declared seeds of that role; `training` keys must match `training_config_key` or the row's training seeds. Two rows with byte-distinct INIs stay two rows of one scenario. |
| `training_config_key` | optional | — | — | Chooses the training INI independently of the PPO seed: the row's `configs.training["<key>"]` first, then the scenario's. The recorded lookup key is this key; the actual INI path and SHA-256 are recorded separately. |
| `continue_from` | optional | — | — | `{run_dir, model}`; exactly one training seed, equal to the parent's seed. |
| `curriculum` | optional | — | — | Existing, hashed curriculum schedule file. |
| `model_source` | — | required | — | `{run_dir, model}`. |
| `labels` | optional | optional | optional | `reward_label`, `ppo_label`, `comparison` (strings), `source_phase` (integer or null), `tags` (strings). Labels never set scientific identity. |

`continue_from` and `model_source` take `model` = `final` (default), `best` or
`checkpoints/checkpoint_<N>_steps.zip`. The parent must be a `completed`
training run whose model file matches its recorded SHA-256; counters are read
from the ZIP. A continuation must exceed the parent's step count, keep its PPO
settings and selection, and use the same training INI bytes.

| Kind | Required | Refused / not required |
|---|---|---|
| `train` | `training.total_timesteps`; at least one row and one effective training seed per row; `evaluation.operations`; model-selection seeds when training validation is on. | `model_source`; a non-increasing continuation budget. |
| `checks` | At least one registered check or baseline policy, and the seeds those need. | `training`, `seeds.training`, `evaluation`; no dummy training seeds. |
| `evaluate` | Rows with `model_source`; `evaluation.operations` with seeds. | `training`, `seeds.training`, continuation, curriculum, `at_steps`. |

A `best` selector needs training validation (`eval_every_steps > 0`) for a new
model, or a verified best ZIP for an existing one.

## 7\. Plan v3 and task identity {#mesh_sim_rl_batch_identity}

`experiment_plan.json` (field `experiment_plan_version`) holds the matrix path,
reference and SHA-256; the binary path, reference and SHA-256; the output root;
the row filter; resolved seeds, scenarios (each INI with its node, building and
jammer assets hashed), rows, operations, comparison, checks and stages; the
declared execution settings; the key dimensions; the placeholders; every input
file's hash; and the task list. `plan` writes it once. Re-planning a root with
different bytes is refused ("plans are immutable, use a new --output-root");
identical bytes are accepted.

**Task key.** The full SHA-256 of a canonical object over these dimensions, in
this order; a dimension a task does not use is null:

`task_kind`, `scenario`, `row`, `profile`, `training_seed`, `model_source`,
`checkpoint`, `operation`, `operation_digest`, `protocol`, `schedule_digest`,
`seed_role`, `seed`, `policy`, `physical_digest`, `check`, `stage`.

The first 10 hexadecimal characters are the readable suffix `K` used in
destinations. Duplicate IDs, keys or output directories, and one destination
nested inside another, are refused before anything is written. Two training
seeds × two checkpoints × two online protocols × two evaluation seeds therefore
give 16 distinct operation tasks; an extra schedule gets its own operation ID
and digest.

**Task kinds and IDs.**

| Kind | Task ID | Runs | Needs |
|---|---|---|---|
| `baseline` | `baseline/<scenario>/<policy>/<role>/seed-<E>`, plus `/config-<digest12>` for each non-default physical variant | `scripts.rl.operate baseline` | — |
| `replay_gate` | `check/<scenario>/<check>/seed-<S>` | `scripts.rl.operate replay-gate` | The source baseline, if planned. |
| `reward_audit` | `check/<scenario>/<check>` | `scripts.rl.operate reward-audit` | The source baseline, if planned. |
| `train` | `train/<scenario>/<row>/train-seed-<S>` | `scripts.rl.train ... m-ppo` | Every check that applies to the row (section 6.9); earlier stages; the selection, if a branch. |
| `operate` | `operate/<scenario>/<row>/<train-seed-S or model-<digest>>/checkpoint-<C>/<operation>/<role>/seed-<E>` | `scripts.rl.operate model` | Its producer train task (or none for an imported model); checks; stage and selection. |
| `select` | `select/<stage>` | Selection handler | Every candidate's source tasks. |
| `curves` | `curves/<scenario>` | Reporting handler | The scenario's train tasks (terminal). |
| `compare` | `compare/<scenario>/<operation>/checkpoint-<C>` | `scripts.rl.compare` | The compared operation tasks and the baselines (completed, or terminal with `allow_incomplete`). |
| `review` | `review/<scenario>` | Reporting handler | Operations and baselines (terminal). |
| `index` | `index/<scenario>` | Reporting handler | Curves, comparisons and review (terminal). |

Baseline identity uses a physical digest over the INI and asset hashes, the
reference (scripted only), band and gate, not a reward row; placement policies
add the planning seed and planner-settings hash, and declared baseline
`decision_record_seeds` add whether the seed records. Baselines with identical
resolved INIs are shared across rows. Imported-model operations use the
model-source digest instead of a training seed. Operate tasks do not carry a
physical digest: row-specific INIs stay distinct through the `row` dimension
and the hashed `config` record.

Every `operate` and `baseline` task records `config` (`path`, `sha256`,
`config_source`), and a placement baseline also records `planning`
(`planning_seed`, `planning_seed_source`, `planner_settings_sha256`,
`mapping_file`).

**Arguments and placeholders.** Each process task stores its module and exact
argument list. The scheduler substitutes `{attempt_dir}`, `{binding_run_dir}`,
`{binding_model}`, `{binding_path}`, `{accepted_dirs}` and
`{accepted_dir:<task-id>}` at dispatch, each as a whole argument; a leftover
placeholder is an error. Nothing is imported or executed from matrix JSON.
`{binding_path}` is the receipt's pinned binding file, re-hashed before
substitution; every `operate` task on a trained checkpoint passes it as
`--binding`, so an ancestor-milestone checkpoint from a recovered run is read
through `policy/bundle.py` `read_bound_checkpoint`. Accepted exit
codes are `[0, 2]` for `operate` and `compare`, `[0]` for every other task.

**Bindings.** An operation on a checkpoint that does not exist at plan time
records a logical selector and its producer. When the producer completes, a
write-once binding at `state/bindings/<producer-key>-<checkpoint>.json` records
`model_binding_version`, `run_dir`, `model_selection`, `model_path`,
`model_sha256`, `optimizer_sha256`, `num_timesteps`, `n_updates`,
`train_manifest_path` and `train_manifest_sha256` (`policy/bundle.py`
`bind_model`). `read_bound_checkpoint` re-verifies the manifest bytes, model
SHA-256, counters and optimizer digest, and never rewrites anything. Replacing
a bound ZIP invalidates the consumer. The scheduler writes bindings when a
producer completes (`ops/batch_receipts.py` `write_bindings`, following the accepted
training lineage for a retained checkpoint) and verifies them at dispatch; an
existing binding with different content is a problem, never overwritten.
`operate model --binding` accepts only a scheduler binding under
`state/bindings/`; arbitrary standalone binding paths are refused. These files
are trusted local scheduler records, not signed credentials or a security
boundary against someone who can write the batch's state directory.

## 8\. Output layout {#mesh_sim_rl_batch_layout}

Only version 2 batches use this layout; legacy results stay where they are.
`K` is the 10-character key suffix, `KEY` the full key, `S` a training seed,
`E` an evaluation seed, `C` a checkpoint selector (`final`, `best` or a step
count).

Task output directories as written into the plan, and the files the scheduler
and reporting owners write (`ops/local.py`, `ops/recovery.py`,
`experiments/reporting.py`):

```text
<root>/experiment_plan.json
<root>/preflight/<scenario>/<check>-<K>/                    preflight, replay_gate, reward_audit
<root>/baselines/<scenario>/<policy>-<K>/<role>/seed-<E>/
<root>/models/<scenario>/<row>/train/train-seed-<S>/
<root>/operations/<scenario>/<row>/<train-seed-S|model-<digest12>>/checkpoint-<C>/<operation>-<K>/<role>/seed-<E>/
<root>/analysis/<scenario>/{curves,reviews,comparisons}/<KEY>/
<root>/analysis/_batch/selections/<KEY>/                    selection receipts
<root>/main/<scenario>/                                     scenario index (projection)
<task output dir>/attempt-<A>/...                           append-only attempts

<root>/runtime_identity.json
<root>/campaign_status.json
<root>/campaign.lock                                        root lock (OS lock)
<root>/resources.jsonl                                      resource samples
<root>/state/steps/<KEY>.json                               task receipts
<root>/state/bindings/<producer-key>-<checkpoint>.json
<root>/state/recovery/<proposal-id>.json
<root>/local/<KEY>/attempt-<A>.log                          child output
<root>/local/<KEY>/attempt-<A>.lease.json                   pool lease of that attempt
<root>/main/<scenario>/{mission_scenario.json,mission_review.json,phase_comparison.json?,reward_comparison.{csv,json}}
<root>/main/<scenario>/assets/<sha12>/...                   copied INI/node/building/jammer/mapping assets
<root>/main/reward_comparison.{csv,json}                    batch-wide reward summary
<pool directory>/{pool.json,pool.lock,slot-<i>.lock,slot-<i>.json}
```

A comparison attempt also holds `view/` (one merged evaluation view per model)
and `view_sources.json`.

Every task except `index` appends attempts under its output directory; `index`
is a projection rewritten in place by the reporting owner after accepted
results change. Expected outputs per task: `train_manifest.json` and
`maskable_ppo_mesh.zip` (plus `post_update_checkpoints.json` with
`after_update` timing); `eval_manifest.json` (frozen operations, baselines) or
`online_manifest.json` (online operations); `check_result.json` (checks);
`selection_receipt.json`; `training_curve_sources.json`; `mission_review.json`;
`comparison.json`; `mission_scenario.json`.

## 9\. Task and batch states {#mesh_sim_rl_batch_states}

The scheduler and status reader live in `ops/local.py`. Task receipts, output
validation and model bindings live in `ops/batch_receipts.py`.

**Receipts, not directory existence.** `state/steps/<KEY>.json` is a versioned
receipt (`batch_step_version`) with fields `task_id`, `task_key`, `kind`,
`identity`, `inputs` (`files` with their SHA-256, the pinned `binding`, the
`selection` branch), `state`, `detail`, `exit_code`, `warnings`, `logs`,
`attempts[]` (`attempt`, `attempt_dir`, `log`, `state`, `started_at`,
`ended_at`, raw `exit_code`, `worker` pid/pgid, `resume` recovery parent,
`inputs`, `resource_pool`, `sim_binary`, `outputs` with hashes, `warnings`,
`detail`),
`accepted_attempt`, `outputs`, `invalidated[]`, `created_at` and `updated_at`.
Only the scheduler writes task state; a child writes only its own artifacts.
A receipt with a defect is treated as `blocked`.

| Task state | Meaning |
|---|---|
| `pending` | Not yet run. |
| `running` | An attempt is in progress. |
| `completed` | The kind-specific validator passed and artifact hashes match. |
| `partial` | Finished with some required output missing. |
| `failed` | The attempt failed. |
| `interrupted` | Stopped by a signal or crash. |
| `blocked` | Cannot run or cannot be verified; includes an existing directory with no valid receipt. |
| `skipped_dependency` | A needed task failed or was blocked. |
| `skipped_selection` | An unselected selection branch; not a failure. |

Completion is validated per kind and never by exit code alone
(`recovery.validate_attempt`): training needs a completed train manifest, the
expected model SHA-256 and `num_timesteps` equal to both the ZIP counter and
the requested budget (a ZIP alone is not completion); operations and baselines
need a completed evaluation and/or version 5 online manifest for the requested
seed and protocol, with local episode directories; checks need
`check_result.json` that `policy/operation.py` `check_result_passed` accepts
(for the replay gate also `policy/replay_gate.py` `gate_passed`), failing
closed when it is missing; `compare` maps `complete` to `completed` and
`incomplete` to `partial`, keeping its warning exit 2; curves, reviews,
selections and the index need readable outputs and their source receipts'
hashes, without an invented status field.

**Batch status.** `campaign_status.json` (`campaign_version`; legacy statuses
remain readable data) holds `state`, `updated_at`, the plan path and SHA-256,
the `runtime_identity` file name, `counts` for every task state, `incomplete`
and `blocked` task lists, `execution` (resolved settings and their source),
`invocations[]` (command, start time, pid, host, execution, binary, recovery
proposal), `refusal`, `recovery_proposal` and `receipts` (task ID → receipt
path). Batch states: `running`, `completed`, `completed_with_warnings`
(a completed task recorded warnings), `failed`, `interrupted`. The batch is
completed only when every task is `completed` or `skipped_selection`; an
optional incomplete comparison does not make it successful, and a partially
populated index is labeled incomplete.

The `status` subcommand reads the receipts without taking the lock
(`local.batch_status`) and prints `Batch <state>` and one line per state count,
or with `--json` the full object: `campaign_version`, `state`,
`recorded_state`, `counts`, `tasks` (state, detail, accepted attempt, receipt
path per task), `execution`, `refusal` and `recovery_proposal`. Its `state` is
`running` while a supervisor holds the lock and `not_started` before any run;
otherwise it is derived from the receipts. A task directory with content but no
receipt counts as `blocked`.

## 10\. Operation protocols {#mesh_sim_rl_batch_protocols}

An operation runs one checkpoint on one evaluation seed. Online protocols
reload the parent model and optimizer independently for every seed; no
learning carries from one evaluation seed to another. Implemented by
`policy/operation.py` `run_operation` behind the `operate.py` CLI (section 10.4).

| Mode | What runs | Records written |
|---|---|---|
| `frozen_deterministic` | Deterministic masked policy; parameter and optimizer digests must be unchanged. | `eval_manifest.json`, `weight_audit.json`; plus `online_manifest.json` when scheduled. |
| `frozen_sampled` | Sampled masked policy; digests unchanged. Optional schedule (section 11). | `eval_manifest.json`, `online_manifest.json`, `weight_audit.json`. |
| `online_gated_v1` | Manual eligible-window PPO updates (`policy/online_adaptation.py` `OnlinePolicy`). | `eval_manifest.json`, `online_manifest.json`, `weight_audit.json`, `weight_updates.json`, `adapted_model.zip`. |
| `online_sb3_v1` | SB3 `learn()` for one native episode budget. | `online_manifest.json`, `weight_audit.json`, `weight_updates.json`, `adapted_model.zip`, reward matrix. No `eval_manifest.json`. |

A frozen operation that changes the policy or optimizer state fails. An
operation refuses a non-empty output directory and a seed outside its declared
evaluation seeds; `online_sb3_v1` refuses the parent's training seed.

### 10.1 Preserved protocol defaults

**`online_gated_v1`.** Inherits `learning_rate`, `gamma`, `gae_lambda`,
`n_epochs`, `ent_coef`, `clip_range` and `target_kl` from the parent's
recorded hyperparameters (a missing one is refused) and takes explicit
`n_steps` and `batch_size` (integers ≥ 2). `target_kl` must be null. A window
is eligible when it has scored ticks (recovery and jamming also need an active
deployment gate with eligible ticks equal to scored ticks). An ineligible
window raises only while an unflushed eligible buffer exists. The final partial
rollout is flushed, except a singleton, which is skipped and counted as an
untrained tail decision. Before adaptation, the loaded model's inherited PPO
settings must match those recorded in the parent; a mismatch is refused.

**`online_sb3_v1`.** `learning_rate = min(parent learning rate, 1e-4)` (parent
fallback 3e-4 when unrecorded), `ent_coef = 0.001`, `target_kl = 0.02`, each
overridable. `batch_size` must divide `n_steps`. The budget is the native
episode's decisions; `budget % n_steps` decisions after the last full rollout
are not trained (`MissionBudgetCallback` stops at the exact budget). Batch
operations use the seed-specific INI passed to that operation; standalone
`online` uses the parent's training INI. For this protocol, null `target_kl`
means the default 0.02, not disabling KL early stopping.

The standalone `scripts.rl.online` CLI keeps its own defaults (from source:
`--seeds 401-405`, `--n-steps 120`, `--batch-size 60`, `--ent-coef 0.001`,
`--target-kl 0.02`, `--model best`, `--modes fixed_sampled online`;
learning rate unset → the SB3 rule above).

### 10.2 `online` settings in a matrix

| Mode | Allowed keys | Required |
|---|---|---|
| `online_gated_v1` | `n_steps`, `batch_size`, `target_kl` (must be null) | `n_steps`, `batch_size` |
| `online_sb3_v1` | `n_steps`, `batch_size`, `learning_rate`, `ent_coef`, `target_kl` | `n_steps`, `batch_size`; omitted or null keys take the defaults above |

`batch_size` may not exceed `n_steps`. A schedule cannot be combined with an
online mode.

### 10.3 Online record versions

The batch writer stamps `online_manifest.json` with the batch
`online_experiment_version` (number in \ref Contributing "Contributing") and an
explicit `protocol`. Its fields: `protocol`, `status` (`running`, `completed`,
`failed`, `interrupted`), `started_at`, `ended_at`, `error`, `label`, `seed`,
`seed_role`, `evaluation_seeds`, `settings`, `schedule`,
`allow_different_scenario`, `parent` (run directory, model selection, model
path and SHA-256, timesteps, train-manifest SHA-256), `run_config`,
`scenario_identity`, `binary_sha256`, `model` (initial/final parameter digests,
adapted model and its SHA-256), `optimizer` (initial/final digests),
`accounting` (update cycles, optimizer steps/epochs, eligible, trained,
excluded-prefix and untrained-tail decisions, tail rule, budget and actual
decisions, schedule events), `evaluation` (relative `eval_manifest`,
`episode_dir`, `decisions`, `weight_audit`, `steps_sha256`) and `episodes`.

The standalone CLI keeps its legacy envelope. Those legacy versions are
ambiguous: one of them was written both for non-default standalone mode
subsets and orders **and** by the gated campaign writers, so the version alone
never identifies the protocol. Only the batch record's `protocol` field does.
Old files are never relabeled; see the online-manifest row in
\ref Contributing "Contributing".

### 10.4 The operation CLI

`scripts.rl.operate` is what plan tasks call; the plan writes its arguments
(`experiments/plan.py`), so a person rarely runs it by hand. Every result is
written under `--output-dir`. Exit codes: `0` success, `2` evaluation health
warnings (revalidated slots or mask violations), `1` for any error,
**including usage errors** (observed: a missing required flag exits 1). Other
RL commands exit 2 on usage errors; `operate` does not, so a usage error is
never mistaken for a tolerated warning. The three checks write
`check_result.json` (`check_result_version`, `check_id`, `kind`, `status`
`passed`/`failed`, `passed`, `evidence`, `warnings`, `written_at`) even when
they fail.

Flags, from each subcommand's `--help`:

| Subcommand | Required | Optional |
|---|---|---|
| `model` | `--sim-binary`, `--run-dir`, `--model` (`final`, `best` or `checkpoints/<name>.zip`), `--mode`, `--operation-id`, `--seed`, `--seed-role` (`model_selection`, `diagnostic`, `held_out`), `--run-config`, `--output-dir`, `--protocol-settings-json` | `--band`, `--schedule-json`, `--gate-s`, `--binding` (scheduler binding JSON; required for a bound checkpoint whose training manifest is unfinished), `--mission` (required by gated and sampling-schedule operations; never inferred from `run.ini`), `--coverage-target`, `--decision-records`, `--decision-records-every`, `--decision-records-max-bytes`, `--decision-records-obs-vector {auto,always}`, `--decision-records-preferences {auto,off}` |
| `baseline` | `--sim-binary`, `--policy` (`hold`, `random_valid`, `scripted`, `geometric`, `optimization`), `--seed`, `--seed-role` (also `training`), `--run-config`, `--output-dir` | `--band`, `--reference-kind`, `--reference`, `--gate-s`, `--mission`, `--coverage-target`, the five decision-record flags, `--import-from`, `--planning-seed` (placement; overrides `[baseline] planning_seed`), `--allow-seed-overlap` (placement only) |
| `preflight` | `--check-id`, `--sim-binary`, `--seed-configs-json`, `--output-dir` | `--band`, `--requirements`, `--reference-kind`, `--reference`. Pass comma-separated capability names with `--requirements`. |
| `replay-gate` | `--check-id`, `--sim-binary`, `--seed-configs-json`, `--source` (episode directory), `--output-dir` | `--band`, `--comparison {strict_v1,pre_contact_source_v1}` (default `strict_v1`), `--parent-run-dir`, `--parent-model` (default `final`; requires parent directory), `--case-json` (object, default `{}`), `--contact-audit` |
| `reward-audit` | `--check-id`, `--source` (evaluation or episode directory), `--method`, `--run-config`, `--observation-preset`, `--reward-components`, `--reward-weights`, `--observation-parameters`, `--reward-parameters`, `--output-dir` | — |

A `baseline` for `geometric` or `optimization` runs the existing evaluate
placement path; the plan never passes it `--import-from`, `--reference*`,
`--mission` or `--coverage-target`.

## 11\. Frozen schedules {#mesh_sim_rl_batch_schedules}

A schedule is an optional `{kind, settings}` on a frozen operation. It never
updates the optimizer or resets the policy; every switch is logged with its
decision and reason (`policy/schedules.py`). Settings have no research
defaults.

| Kind | Required settings | Behavior |
|---|---|---|
| `initial-sampling` | `initial_sample_decisions` | Sample for the first N eligible decisions, then act deterministically. |
| `stall-burst` | `progress_window`, `rejected_window`, `rejected_threshold`, `movement_threshold_m`, `progress_threshold`, `burst_decisions`, `cooldown_decisions`, `max_bursts` | Deterministic; sample a burst when a slot keeps being rejected without moving or progress stalls; cool down; at most `max_bursts`. `rejected_threshold ≤ rejected_window`; `movement_threshold_m ≥ 0`; `cooldown_decisions` may be 0. |
| `sample-then-deterministic`, `sample-then-hold` | `coverage_target` (from the schedule or the scenario case) | Sample until coverage service qualifies for 30 s, then act deterministically or hold; fall back to sampling after a 5 s relapse or a severe service loss. |

The 30 s qualification, 5 s relapse and service thresholds are versioned
constants of the coverage schedule (`COVERAGE_RULES`). The policy owner's
validator is stricter than the matrix validator: it also requires
`rejected_window ≤ progress_window + 1`.

## 12\. Named selection rules {#mesh_sim_rl_batch_selection}

The default batch has no selection. Selection is finite and declared: the plan
contains every branch before execution, and unselected branches become
`skipped_selection`. Missing data blocks selection; held-out evidence is
refused. The receipt (`selection_receipt.json`, `selection_receipt_version`,
written under `analysis/_batch/selections/<KEY>/`) records the rule, tie rule,
seed role, sources with hashes, sample counts, ranking, selected candidates,
and selected and skipped branches.

The plan's select task carries `source_kind`: `training_validation` (the
validation rule; train attempts), `operation` (mission and online rules;
operate results at exactly `source_checkpoint`, for row or `{row, operation}`
candidates) or `none` (`replay`). `experiments/reporting.py`
`selection_evidence` reads only the declared sources: each item names its
source task, accepted attempt, manifest path and SHA-256, seed role, case and
`samples` (never invented), plus `best_mean_reward` and `checkpoint_means`
(validation rule) or `values`, `row`, `operation` and `checkpoint` (mission and
online rules). A missing or undeclared source, a source at another checkpoint,
or a held-out seed role blocks the selection.

| Rule | Ranking (`experiments/selection.py`) |
|---|---|
| `legacy-validation-profile-v1` | Highest mean of `best_mean_reward / normalization_decisions` across cases; then lower mean population SD of the last three checkpoint means; then candidate name. Model-selection seeds. |
| `legacy-mission-profile-v1` | Highest mean mission score; lower sample SD; then name. The best non-retained candidate wins; `retain` candidates are kept too. |
| `legacy-online-profile-v1` | Highest mean online mission score; lower sample SD; then name. |
| `replay` | Recorded `winners` pinned explicitly with `provenance`; no ranking; labeled a replay, not a new selection. |

## 13\. Identity and resume {#mesh_sim_rl_batch_resume}

Runtime identity lives in `ops/batch_identity.py`. Checkpoint recovery and
resume proposals live in `ops/recovery.py`.

At first run the batch writes `runtime_identity.json` once
(`runtime_identity_version`, `created_at`, `plan` path and SHA-256, `matrix`
path/reference/SHA-256, `inputs`, `parent_models`, `sim_binary`,
`python_sources` — every non-test `scripts/**/*.py` file, so additions and
removals count —, `package_versions`, and `registry`: a per-ID digest of the
reward and observation registry descriptors). Execution overrides are appended
to `campaign_status.json` as invocations. Before resume and before each
dispatch, a changed code file, input, binary, dependency or registry entry is
refused (`IdentityChanged`, listing at most 20 changed items, "use a new
--output-root"); a binding is re-verified at dispatch. There is no
warning-only mode and no hash replacement; a deliberate code change needs a new
output root.

Resume procedure:

1. Take the root lock; load the plan and identity; verify every accepted
   receipt and binding; inventory attempts read-only.
2. Build the whole recovery proposal (`state/recovery/<proposal-id>.json`,
   `batch_recovery_version`) before changing anything. Blockers are listed;
   nothing is half-applied.
3. Completed tasks keep their accepted attempt. Resume verifies and writes missing
   checkpoint bindings from completed training before dispatch. Pending tasks
   stay pending. An interrupted operation, baseline or check retries in a new
   attempt.
4. Interrupted training with `recovery: checkpoint` restarts from the latest
   verified post-update checkpoint of that task: timing event, ZIP SHA-256,
   cumulative `num_timesteps`, `_n_updates`, optimizer state, complete-episode
   boundary and matching inputs.
5. The new attempt records its parent attempt and checkpoint, restored and
   remaining decisions, accepted episode ranges and the excluded tail. The
   interrupted directory is never rewritten.
6. With no safe checkpoint, or a terminal budget without a final manifest, the
   task is `blocked` for human review; it never restarts from zero silently.
7. `--prepare-only` writes the proposal and exits; a later `resume`
   revalidates it, appends attempts and runs only eligible tasks. Repeating
   either never duplicates accepted work or changes plan bytes.

The proposal (`batch_recovery_version`) holds `plan_sha256`,
`runtime_identity_sha256`, `recovery`, `sim_binary` (given and recorded),
`receipts` (task ID → receipt SHA-256), `tasks`, `blockers`, `proposal_id`
(the first 16 hexadecimal characters of the content hash, so an identical
proposal is written once), `summary` (count per action) and `created_at`. Each
task entry has an `action`:

| Action | When |
|---|---|
| `keep` | A completed task whose accepted outputs and binding still verify, or a terminal task left as it is. |
| `pending` | Not started, or skipped because of a dependency. |
| `retry` | An interrupted operation, baseline, check or report task: one new attempt of that task only. |
| `resume_checkpoint` | Interrupted training with `recovery: checkpoint` and a verified post-update checkpoint. Records `parent_attempt`, `parent_dir`, `checkpoint`, `restored_steps`, `restored_decisions`, `remaining_decisions`, `accepted_episode_ranges`, `excluded_tail` and the training `args`. |
| `accept` | The interrupted training attempt actually finished with a valid final manifest. |
| `blocked` | Owned processes still running; accepted outputs changed; `recovery: none`; curriculum training (no checkpoint recovery); terminal budget without a final manifest; no verified checkpoint. Never a restart from zero. |

`resume` (without `--prepare-only`) first reaps verified owned leftover
processes; if any remain it exits 1 without resuming.

A missing evaluation of a finished model uses same-root `resume` or a new
`kind: evaluate` batch; neither retrains. Legacy Phase 9 recovery is a
separate historical protocol and is never adopted.

## 14\. Training options for checkpoints and continuation

`train.py m-ppo` options used by batch training tasks (from `--help`; existing
options keep their meaning):

| Option | Contract |
|---|---|
| `--continue-from-run-dir DIR` | Continue a verified completed run; exclusive with `--resume-run-dir`. |
| `--continue-model SELECTOR` | `final` (default), `best`, or `checkpoints/<file>.zip` of that run. |
| `--checkpoint-timing <timing>` | `standard` or `after-update`. `after-update` saves only after an optimizer update, without in-training validation; `post_update_checkpoints.json` records each event. Default `standard`. |
| `--decisions-per-episode N` | Asserts the simulator's decisions per episode; checked against the native `init` contract before any update; never changes it. |
| `--curriculum-schedule PATH` | Existing curriculum schedule JSON for the training environment only; evaluation keeps the original configuration. |

`--resume-run-dir`/`--resume-checkpoint` remain the recovery path for an
interrupted run's verified checkpoint. `train_manifest.json` keeps its version;
optional `checkpoint_timing`, `decisions_per_episode`, `curriculum` and
`continuation` keys appear only when the option is used.

## 15\. Workers, threads and shared pools {#mesh_sim_rl_batch_workers}

Worker and thread limits apply per launcher process. Two terminals running two
batches without a shared pool **add** their workers (the launcher's help says
so). There is no memory-based automatic increase, and no fixed worker count is
claimed safe on every machine.

`ops/batch_processes.py` uses `campaign.lock` to refuse a second supervisor
for the same root. `execution.resource_pool` gives
cooperating batches one cross-terminal cap: the first batch records
`pool.json` (`resource_pool_version`, `capacity`, `created_at`) under
`pool.lock`, and a batch declaring another capacity is refused. Each task
worker takes one `slot-<i>.lock` with an OS lock and passes it to its child,
so a slot lives as long as either; a supervisor crash does not free a slot
while its worker is alive. Orphans are reaped only when their command line is
verified as owned; child tasks take no nested slots. Each process task's
environment sets the usual numerical thread variables to the resolved
`threads_per_worker`. With several workers, child output goes
to `local/<task-key>/attempt-<A>.log` and progress prints every 30 seconds.
`continue` finishes independent tasks after a failure and blocks dependents;
`stop` dispatches nothing new. SIGINT/SIGTERM stops and reaps owned process
groups, records interrupted tasks, releases slots and exits 130.

## 16\. Examples by kind

### 16.1 `train`: the public example

`inputs/experiments/examples/coordination-smoke/batch.json` trains one row on
seed 101 for 256 decisions (4 episodes of 64 decisions) with after-update
checkpoints at 128 and 256, runs a scripted replay gate (no preflight check,
section 6.9), three baselines on diagnostic seeds 201 and 202, and four
operations (both frozen modes and both online protocols) at checkpoint 128 and
`final`. Static validation, re-executed 2026-10-29 for the second
documentation pass on the working tree of commit `b54bfbe7` (no simulator
launched; exit 0):

```bash
bash scripts/rl/run-experiments.sh validate --matrix inputs/experiments/examples/coordination-smoke/batch.json
```

```text
matrix coordination-smoke (kind train): 27 tasks
  baseline 6, replay_gate 1, train 1, operate 16, curves 1, review 1, index 1
```

followed by one line per task and its key suffix.

### 16.2 `checks`

Proposed and unverified: never validated. Placed beside the example (paths
are relative to the matrix directory):

```json
{
  "matrix_version": 2,
  "name": "coordination-checks",
  "kind": "checks",
  "scenarios": {
    "rural-coverage-3-peers": {
      "run_config": "run.ini", "band": "sub-6",
      "reference": {"kind": "scenario_routes_v1", "path": "reference.json"},
      "baselines": {"policies": ["scripted", "hold"], "seed_role": "diagnostic"}
    }
  },
  "seeds": {"diagnostic": [201, 202]},
  "checks": [
    {"id": "scripted-replay", "kind": "replay_gate", "scenario": "rural-coverage-3-peers",
     "seeds": [201], "source": {"baseline": "scripted", "seed": 201}}
  ]
}
```

No `training`, `evaluation` or training seeds; rows are optional.

### 16.3 `evaluate`

Proposed and unverified: never validated. Evaluates an existing completed run
with new operations, without retraining:

```json
{
  "matrix_version": 2,
  "name": "coordination-evaluate",
  "kind": "evaluate",
  "scenarios": {"rural-coverage-3-peers": {"run_config": "run.ini", "band": "sub-6"}},
  "seeds": {"held_out": [301, 302, 303]},
  "evaluation": {"operations": [
    {"id": "frozen-deterministic", "mode": "frozen_deterministic", "seed_role": "held_out"}
  ]},
  "rows": [
    {"name": "raw-delivery", "scenario": "rural-coverage-3-peers",
     "model_source": {"run_dir": "/absolute/path/to/completed/train-run", "model": "final"}}
  ]
}
```

No `at_steps`: the row's `model_source` names the model. Selection fields, if
given, must match the parent's saved selection.

## 17\. Retired commands and their replacements {#mesh_sim_rl_batch_retired}

The duplicated campaign/phase runners and env aliases were removed on
2026-10-30. The maintained tests are mapped in \ref scripts_rl_tests "RL tests"; the
command table below gives the supported replacements.

| Former command or family | Replacement |
|---|---|
| `experiment plan/run/status` with matrix v1 | Unchanged contract; the launcher is optional. Public helper imports and cluster/tuning callers are kept. |
| `campaign --config`, `adaptive_campaign`, `mission_campaign`, and the mission screen/pilot/focused/foundation/targeted runners | Version 2 matrices with explicit stages and checks, named selection where it was used, baseline imports and derived summary outputs. No second queue. |
| `phase_one` … `phase_nine` package commands | Version 2 batches express settings, seeds, budgets and schedules. Ten available 10-23/10-30 batches validate; the historical 10-23-5 same-batch continuation has no equivalent single-batch conversion. Use an existing completed parent for continuation. New runs use new roots. |
| Phase 8 A/B in two terminals | Two batches that declare the same `execution.resource_pool` directory and capacity. |
| Phase 9 prepare/restart/resume | The old campaign finished with the old code. New batches use version 3 receipts and recovery; Phase 9 recovery intents are never imported. |
| `templates/run-configurations.sh` | `run-experiments.sh`, the tracked example and this reference. |
| Private `inputs/custom/**/run-*.sh` | Immutable historical records, not supported launchers. Converted batches live beside them as `inputs/custom/<campaign>/batch-v2.json` (or `batch-a-v2.json`); an existing file is refused, never overwritten. |
| Standalone `online`, `train`, `evaluate`, `compare`, `scenario_check`, `preflight_campaign`, `inspect_model`, `validate_config`, `ops.*` | Supported as before; one simulation never requires the batch runner. |

Cross-scenario reward summaries formerly written by `campaign.py` remain a
reporting output with source identities; they are not a ranking across
unrelated rewards.

## 18\. Source and tests

| Owner | Test (behavior map) |
|---|---|
| `experiments/config.py`, `experiments/plan.py`, `experiments/selection.py` | `test_matrix_v2.py` (\ref src_rl_policy_comparison_tests "Policy comparison tests") |
| `experiment.py`, `run-experiments.sh` | `test_experiment_launcher.py` covers CLI dispatch, v1 compatibility, and invoking the Bash launcher from another directory. |
| `policy/operation.py`, `policy/schedules.py`, `policy/replay_gate.py`, `policy/reward_audit.py` | `test_operation.py`, `test_schedules.py`, `test_replay_and_audit.py`, `test_online_protocols.py` (\ref scripts_rl_tests "scripts/rl/tests") |
| `policy/online_adaptation.py`, `online.py` | `test_online_protocols.py` |
| `policy/bundle.py` bindings and digests, `policy/training.py`, `agents/post_update.py`, `train.py` | `test_checkpoint_recovery_support.py` (\ref src_rl_policy_lifecycle_tests "Lifecycle tests") |
| Reward and observation registries | `test_registry_identity.py` (\ref src_rl_policy_input_tests "Policy-input tests") |
| `env/geometry.py`, `env/curriculum.py`, `env/seeded_env.py`, `policy/scripted.py` | `test_geometry.py`, `test_curriculum.py`, `test_seeded_env.py` and `test_scripted_mission_policy.py` |
| `operate.py` | `test_operate_cli.py` covers help, argument dispatch and capability probes. `test_operate_integration.py` runs model and baseline commands against the fake simulator. |
| `ops/local.py` | `test_ops_local.py` (\ref scripts_rl_ops_tests "Operations test map"); inert child, worker and supervisor entry points. |
| `ops/recovery.py` | `test_ops_recovery.py` (\ref scripts_rl_ops_tests "Operations test map"). |
| `experiments/reporting.py` | `test_gui_index.py` (index v4 and online v5 fixtures), `test_report_comparison.py` and `test_report_selection.py`. |
| Historical conversions | `test_conversion_parity.py` (private datasets; a named skip where absent). |

Native authority: no agent builds or runs the simulator. The human builds the
binary, runs the native smoke and any real-binary test, and passes the binary
with `--sim-binary`.

Previous: \ref mesh_sim_rl_experiments "Experiments and operations" · Next: \ref mesh_sim_rl_code_map "Where the RL code lives"
