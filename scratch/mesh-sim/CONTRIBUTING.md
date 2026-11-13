@page Contributing Contributing

This page lists what to update together when you change user-visible behavior,
the current saved-file schema versions, and the checks to run. Start with the
[user guide](@ref mesh_sim_overview) for setup and the [RL bridge contract](@ref src_rl)
for centralized control.

## 1\. Update together

Before changing a user-visible behavior, find the change below and update
everything listed under it.

### 1.1 run.ini or CLI option

- The loader, plus resolution and validation
- [run.ini options](@ref src_config_run_ini_reference) and [CLI options](@ref src_cli)
- An example
- A valid/invalid configuration check

### 1.2 RL semantics

Action, observation, mask, cadence or reward semantics.

- The C++ bridge and simulator loop
- The Python protocol and environment
- The [contract](src/rl/README.md)
- Focused fake-simulator and real-binary checks

### 1.3 Placement engine or query contract

- Component and strategy owners, and the settings and settings hash
- C++ query owners
- The client and fake worker
- The [engine workflow](scripts/baselines/planners/README.md)
- Query unit tests and real-binary checks

### 1.4 Placement seeds, penalties or provenance

- The INI/CLI owner
- Preparation and seed-role preflight
- Runtime identity and baseline artifacts
- Examples and a fake-worker check

### 1.5 Comparison metrics

- The `policy/metrics.py` registry and the evaluation writer
- Comparison JSON/CSV and their schema versions
- Tests and fetch include rules
- Keep initial relocation separate from scored travel.

### 1.6 Training or episode output

- The writer and any reader
- The [output layout](@ref readme_where_output_lands)
- A test of the changed fields

### 1.7 Scenario identity

- `read_scenario_identity` in `scripts/rl/env/config.py`
- The saved training manifest and relevant tests
- The [identity description](@ref src_rl_saved_scenario_identity)

### 1.8 Batch matrix (version 2)

A field, kind requirement, path rule, task kind, task-key dimension or output
destination.

- `scripts/rl/experiments/config.py` or `plan.py`
- The plan version, if the plan payload changes
- `test_matrix_v2.py`
- The public example under `inputs/experiments/examples/`
- The [batch reference](@ref mesh_sim_rl_batch_reference)

### 1.9 Experiment and training command flags

A flag, default or exit code of `experiment.py`, `run-experiments.sh`,
`operate.py` or `train.py m-ppo`.

- The parser, and launcher normalization if it is a path flag
- The flag tables in the [batch reference](@ref mesh_sim_rl_batch_commands)
  and [scripts/rl](@ref scripts_rl)
- A CLI test
- Compare the documentation with the actual `--help` output.

### 1.10 Operations, schedules and selection

An operation mode, online protocol default, schedule, replay-gate or
reward-audit method, or selection rule.

- Its owner in `policy/` or `experiments/selection.py`, and the record version
  beside it
- `test_operation.py`, `test_online_protocols.py` and `test_matrix_v2.py`
- The [protocol](@ref mesh_sim_rl_batch_protocols),
  [schedule](@ref mesh_sim_rl_batch_schedules) and
  [selection](@ref mesh_sim_rl_batch_selection) sections
- Never merge the two online protocols.

### 1.11 Batch state and recovery

A batch receipt, task or batch state, binding, runtime identity or recovery
rule.

- `scripts/rl/ops/` and the `policy/bundle.py` bindings, with their versions
- Scheduler and recovery tests
- The [states](@ref mesh_sim_rl_batch_states) and
  [resume](@ref mesh_sim_rl_batch_resume) sections

### 1.12 Batch scenario index or online manifest

The batch scenario index (`mission_scenario.json` version 4) or online
manifest fields.

- The producers (`experiments/reporting.py`, `policy/operation.py`) and the
  producer contract fixtures
- The companion reader in the sibling `ns3-mmwave-viz` repository
  (`src/lib/batchMissionIndex.ts`), with its tests and docs
- Keep every legacy reader branch.

### 1.13 Reward and observation registry

A registry module, its order or a descriptor.

- Registration in `env/rewards/` or `env/observations/`
- `tests/fixtures/registry_identity.json`; never regenerate it to hide a change
- The saved-model loading test
- [Policy inputs](@ref src_rl_policy_inputs)

### 1.14 Anything the getting-started pages quote

The getting-started pages quote build commands, binary names, scenario values,
output file names and field formats. Update them when you change the
`inputs/baselines/01-static-los-baseline/` scenario, the default output
layout, the root `VERSION`, the CI configure line in
`.github/workflows/mesh-sim.yml`, the `run.log` Resolved-config fields, or the
`flows.csv` columns and format:

- [Install and build](@ref mesh_sim_install_build)
- [Your first run](@ref mesh_sim_first_run)
- [Understand the result](@ref mesh_sim_first_result)
- [Change one setting](@ref mesh_sim_change_one_setting)

## 2\. Versioning rules

| Identifier | Describes | Change it when |
|---|---|---|
| `contract` name (`mesh_move_2d_v2`, C++ and Python) | The wire format and action meaning. | Protocol semantics or layout change incompatibly. A refactor that keeps behavior does not change it. |
| A saved JSON `manifest_version` | That file's schema. | Its fields or their meanings change. Increment only the relevant version, then update writers, readers, examples and tests. |
| SHA-256 fields in `scenario_identity` | Fingerprints of input files (not schema versions). | The corresponding input files or the identity definition change. |

- Versions do not increment per run.
- Regenerate existing outputs after a version change; do not relabel them.
- Navigation, team, `coordination_v1` and `deployment_gate` extensions are
  versioned inside the unchanged `mesh_move_2d_v2` wire contract.

## 3\. Current schema versions

### Core outputs

| File or schema | Version | Contents |
|---|---|---|
| `train_manifest.json` | 7 | All PPO settings and the full validation seed set. |
| `rl_episode.json` | 6 | Scored tick counts, a consistent pre-handshake failure schema, optional jammer-motion metadata, and configurable progress persistence. |
| `eval_manifest.json` | 8 | Scored metrics, initial relocation, planning seed roles, coverage, service, safety and delayed-jammer metrics, plus the optional measurements below. |
| Comparison JSON | 2 | Validates the evaluation version and scoring metadata. |
| Telemetry | 3 | Resolved input parameters and movement-context inputs. |
| Experiment plans (`experiment_plan_version`) | 2 (matrix version 1), 3 (matrix version 2 batches) | Version 2: resolved parameter identities; read unchanged and never rewritten with extra fields. Version 3 (`EXPERIMENT_PLAN_VERSION` in `experiments/plan.py`): task graph, SHA-256 task keys over fixed dimensions, destinations, argument lists and hashed inputs. |
| Online operation manifest (`online_experiment_version`) | 3, 4 (standalone, legacy); 5 (batch operations) | Saves the optional measurements below. Version meanings are listed below the table. |
| Episode `event_timing.json` | 1 | The checked fixed jammer interval and whether the actual command was verified. |
| `deployment_gate` extension | 1 | Opt-in; scenarios with the default of zero emit no extension. |

**Optional evaluation measurements** (`eval_manifest.json` and online
manifests): mission outcomes, survivor service, failure accounting,
final-minute service and coverage, survivor outage, post-failure movement, team
arrival and collision attempts. A measurement that is unavailable is `null` and
is left out of paired comparisons.

**Online operation manifest versions:**

- **3:** standalone `scripts.rl.online` with exactly the default mode tuple
  `('fixed_sampled', 'online')`, in default order.
- **4:** any other standalone mode subset or order (with a `modes` list), and
  the gated online protocol written by the Phase 2, Phase 3 and Phase 8
  runners. Version 4 alone therefore does not identify the protocol; old
  version 4 files are never relabeled as a verified protocol without evidence
  from their original writer.
- **5:** written by `policy/operation.py` (`ONLINE_MANIFEST_VERSION`) for batch
  operations. Requires `protocol` (`frozen_deterministic`, `frozen_sampled`,
  `online_gated_v1` or `online_sb3_v1`), settings, parent/model/optimizer
  identities and seed role, plus schedule metadata where applicable,
  update/tail accounting and relative evaluation references.
- The standalone CLI keeps its version 3/4 envelope.
- Readers: the GUI's legacy branch accepts versions 2–4. Version 5 is read only
  through batch scenario-index references, by the companion GUI reader
  (`ns3-mmwave-viz` `src/lib/batchMissionIndex.ts`, `BATCH_ONLINE_VERSION`).

### Batch runner

Written for matrix version 2 batches. Constants live beside their writers (the
constant name is given for each row; every number below was checked against
its constant on 2026-10-29); the contracts are in the
[batch reference](@ref mesh_sim_rl_batch_reference).

| File or schema | Version | Writer / reader |
|---|---|---|
| Matrix (`matrix_version`) | 1, 2 | Input. Version 1 is read by `policy/experiment.py` (unchanged); version 2 (`MATRIX_V2_VERSION`) by `experiments/config.py`. Extensions within version 2 are listed below the table. |
| Runtime identity (`runtime_identity_version`, `runtime_identity.json`) | 1 (`RUNTIME_IDENTITY_VERSION`) | Writer/reader `ops/batch_identity.py`. Written once; pins plan, matrix, inputs, parent models, binary, non-test `scripts/**/*.py`, package versions and registry descriptor digests. |
| Step receipt (`batch_step_version`, `state/steps/<task-key>.json`) | 1 (`BATCH_STEP_VERSION`) | Only the scheduler (`ops/local.py`) writes, through `ops/batch_receipts.py`; recovery and status read. |
| Model binding (`model_binding_version`, `state/bindings/*.json`) | 1 (`MODEL_BINDING_VERSION`) | `policy/bundle.py` `bind_model` (writer, called by the scheduler) and `read_bound_checkpoint` (reader); write-once. |
| Recovery proposal (`batch_recovery_version`, `state/recovery/<proposal-id>.json`) | 1 (`BATCH_RECOVERY_VERSION`) | `ops/recovery.py`. Not the Phase 9 `recovery_plan.json` schema, which it never reads. |
| `campaign_status.json` (`campaign_version`) | 2 for batch roots (`CAMPAIGN_VERSION`) | `ops/local.py`. State, counts, incomplete/blocked lists, execution, invocations and receipt pointers. Legacy campaign statuses (version 1 rows below) remain readable data. |
| Shared resource pool (`resource_pool_version`, `<pool>/pool.json`) | 1 (`RESOURCE_POOL_VERSION`) | `ops/local.py`. Records the pool capacity; a batch declaring another capacity is refused. |
| `mission_scenario.json` (scenario index) | 4 for batch roots (`MISSION_SCENARIO_VERSION`) | `experiments/reporting.py`. Explicit relative references to models, baselines (placement entries add an optional `planning`) and evaluations, with per-entry `config` INI records. GUI reader: companion `batchMissionIndex.ts`; the existing v1–3 branch is unchanged. |
| Selection receipt (`selection_receipt_version`) | 1 (`SELECTION_RECEIPT_VERSION`) | `experiments/selection.py`; evidence from `experiments/reporting.py` `selection_evidence`. |
| `check_result.json` (`check_result_version`) | 1 (`CHECK_RESULT_VERSION`) | `policy/operation.py` (writer and `check_result_passed` reader). |
| `replay_gate.json` | 2 (`REPLAY_GATE_VERSION`; reader accepts 1 and 2) | `policy/replay_gate.py`; case, verified parent, compatibility, boundary audit and jammer-timing evidence. |
| Reward audit | 1 (`REWARD_AUDIT_VERSION`) | `policy/reward_audit.py`. |
| Frozen schedules (`coverage_execution.json`) | 1 (`SAMPLING_SCHEDULE_VERSION`, `COVERAGE_SCHEDULE_VERSION`) | `policy/schedules.py`; the 30 s qualification, 5 s relapse and service thresholds are part of the coverage schedule version. |
| `post_update_checkpoints.json` | 1 (`POST_UPDATE_CHECKPOINTS_VERSION`) | `agents/post_update.py` (also used by the historical Phase 8 package). |
| `training_curve_sources.json` | 1 (`TRAINING_CURVE_SOURCES_VERSION`) | `experiments/reporting.py`; payload key `training_curve_version`. No completion-status field. |
| `phase_comparison.json` | 1 (`PHASE_COMPARISON_VERSION`) | `experiments/reporting.py`. |
| Reward summary (`reward_comparison.{csv,json}`) | 1 (`REWARD_SUMMARY_VERSION`) | `experiments/reporting.py`; keeps the retired campaign summary's metric meanings; not a ranking across unrelated rewards. |

**Extensions within matrix version 2:** placement baselines, `rows[].configs`,
`checks[].applies_to`, operation candidates, `source_checkpoint`,
`configs_scope`, `decision_record_seeds`, and replay
`comparison`/`parent`/`case`/`contact_audit`. Plan version 3 keeps its existing
payload and key dimensions; replay identities use `operation_digest` and
`model_source`.

Train, evaluation, episode, telemetry, review, comparison, history and
checkpoint payloads keep their versions when batch metadata lives in wrappers
and receipts. `train_manifest.json` gains optional `checkpoint_timing`,
`decisions_per_episode`, `curriculum` and `continuation` keys only when the
matching `train.py` option is used; its version is unchanged.

### Placement baselines

| File or schema | Version | Notes |
|---|---|---|
| `baseline_manifest.json`, `baseline-plan.json`, plan fingerprints | 3 | See [scripts/baselines](@ref scripts_baselines). |
| Mapping JSON | 2 | |
| Placement engine settings | 2 with optional outdoor probe domains or physical constraints; 1 for unconstrained rectangular requests | The settings version enters the settings hash. |

### Campaigns and GUI output (historical)

<details>
<summary>Versions of artifacts from the retired research runners</summary>

These rows document saved artifacts from the retired research runners. Their
files remain readable data; new batches use the supported schemas above.
The numbered runner packages were removed; the [batch reference](@ref mesh_sim_rl_batch_retired)
explains the supported replacements.

| Files | Version | Notes |
|---|---|---|
| Checks-only campaign, status and report | 1 | Written beside evaluation version 8 artifacts. |
| Correction campaign | 2 | Supports an explicit subset of cases and optional omission of placement benchmarks. Version 1 campaigns keep their 24-case / 168-episode inventory. |
| Phase 1 input, status and report | 1 | |
| `phase-four.json`, campaign status, `phase_four_report.json` | 1 | Reports keep nested variant/baseline diagnostics; the visualizer accepts the report identity. Historical artifact; the current contract is in the batch reference. |
| `phase-five.json`, status, report | 1 | Historical artifact; the current contract is in the batch reference. |
| `mission_scenario.json` | 3 | Adds source-phase tags. Batch roots write version 4 (see Batch runner). |
| `phase_comparison.json` (optional) | 1 | Source-hashed recorded Phase 1–4 diagnostic summaries for narrow-folder GUI comparisons. Historical metrics are not rerun or pooled. |
| `phase-six.json`, campaign status, `phase_six_report.json` | 1 | Historical artifact; the current contract is in the batch reference. |
| `phase-eight.json`, package campaign status, per-job results, `post_update_checkpoints.json`, `coverage_execution.json` | 1 | Historical artifact; the current contract is in the batch reference. |
| `phase-nine.json`, Phase 9 status, per-track results, report, native gate and curve-source inventory | 1 | Historical artifact; the current contract is in the batch reference. Existing training/evaluation/index schemas are unchanged. |
| Phase 9 `recovery_plan.json` | 1 | Explicit restart ownership, checkpoint/source pins, archived partial tracks and retained completed results. Optional result/curve provenance distinguishes repeated tails from accepted checkpoint history. |
| GUI scenario index | 2 (Phase 1), 3 (Phase 6 and Phase 8) | The scenario index is `main/<case>/mission_scenario.json`; these are the versions the historical writers produced. Batch reporting writes version 4 (Batch runner table); the plan calls it "scenario index v4". |
| Comparison history | 1 | |
| `mission_review.json` | 1 | |

</details>

### Descriptor identities

- `mission_compact_v1` and the new reward descriptors have their own schema
  identities. Historical presets and components, and the native wire, are
  unchanged.
- The Phase 5 arrival fraction has its own descriptor identity.
- `coordination_v1` reward and observation descriptors declare optional
  Python-derived facts: current/history measurements, phase/dwell and
  completed-action feedback. They are appended after native validation, only
  for selections that opt in. Native facts, masks and old schema hashes are
  unchanged. New history sequences and decomposed rewards are replayed
  independently in tests.

### Behavior notes tied to these versions

<details>
<summary>Behavior decisions recorded alongside the versions above</summary>

- Directed explicit traffic validates ordered duplicates.
- Investigation secondary target ranges extend to zero in both the native and
  Python validators, with no change to the wire shape.
- `control_start_s` is loaded, validated, logged, mirrored in the fake and
  Python protocol, and covered by user-run native configuration/deployment
  checks.
- Phase 8 diagnostics reconstruct available-peer radio connectivity from native
  links, not from the investigation-only mission flag.
- The optional campaign checkpoint callback in `policy/training.py` keeps
  default callers working and performs no validation during training.
- Phase 8 leaves model and evaluation manifest versions and reward/observation
  meanings unchanged.
- The functional renames of the former `phase3`–`phase7` environment files leave
  every reward/observation ID, descriptor, registration order and schema hash
  unchanged (`tests/fixtures/registry_identity.json`).

</details>

## 4\. Checks to run

For a protocol or simulator change, run these against a fresh build (listed in
the [test map](@ref scripts_rl_tests)):

1. The small Python contract suite.
2. The C++ configuration tests.
3. The real-binary integration checks.

Record any known platform limitation. Matching results on one platform do not
show bit-for-bit equality on others.

Add a focused test only when it checks behavior the existing tests do not
cover; the [RL test map](@ref scripts_rl_tests) shows current coverage with
inputs and outputs.

## 5\. Code ownership

- Keep CLI modules to parsing and delegation.
- Put configuration beside its domain owner. Preparation, child lifecycle,
  artifacts and runtime provenance each have their own owner.
- Use the shared artifact I/O implementation; do not copy helpers into scripts.
- New planner modules must be included in the automatic code identity.
- Test Python defaults against the actual C++ configuration loader.
- Keep optimizer, channel-planning, training, selection and evaluation seeds
  separate. An explicit overlap override marks results as diagnostics, not
  held-out results.
- Keep generated outputs, trained models, large regression snapshots and local
  virtual environments out of Git.

The [placement guide](@ref mesh_sim_placement_start) runs both cost settings
and shows the limits of planner predictions.

## 6\. Pull requests

Use the repository's [PR template](https://github.com/ryanmccann1024/ns3-mmwave/blob/develop/.github/pull_request_template.md).
Write for someone who has not followed the implementation conversation. A small
change may need only a paragraph and its validation results; a larger change
needs enough context to explain the behavior and the important tradeoffs.

- **Title:** use the Conventional Commit format from `CLAUDE.md`,
  under 72 characters. Name the resulting behavior or responsibility.
- **Branch:** use a purpose-based prefix such as `feat/`, `fix/`, `refactor/`
  or `docs/`, followed by a short description. Name the responsibility rather
  than the author, tool or private experiment phase.
- **Summary:** start with the concrete problem and what changes for the user.
  Use a short before/after example when it helps. Add a few bullets for distinct
  changes; avoid a file inventory, implementation diary or repeated checklist.
- **Validation:** list actual checks and results, including commands or a short
  reproduction where useful. Distinguish checks of this branch from checks of
  the combined dependency stack. State relevant skipped, blocked or unrun
  checks and why. Pending CI is pending, never a local pass.
- **Review notes:** include only material compatibility/migration details,
  limitations, dependencies or a decision needing review. Delete the section
  when it adds nothing. Link related issues and PRs; keep local paths and
  unpublished coordination records out of the description.

Keep one coherent reviewer concern per PR, including its implementation, tests
and user-facing contract. Aim for roughly 4,000 changed lines (additions plus
deletions, accounting for renames), with flexibility to keep necessary pieces
together. Count generated/vendored assets and fixtures separately from authored
code, tests and prose. Explain larger exceptions and give a useful review order.
File count alone is not a reason to split.

The base is the branch that will receive the change; use `develop` for the
current feature work unless the maintainer specifies otherwise. Declare every
unmerged dependency. A PR targeting `develop` includes pending ancestor changes
in its main diff: provide an incremental comparison link, keep it draft while
blocked, and merge prerequisites first. Do not describe those dependent branches
as independently mergeable. Recheck the diff and CI after each prerequisite
lands; squash/rebase merges may require an explicit restack.

Before publishing, verify the intended fork/base, exact changed-file list and
configured human identity. Preserve unrelated work and exclude private planning
records, outputs, trained models and large result bundles. Do not add automated
attribution or sign-off trailers. Publish as draft while required validation or
dependencies remain outstanding; the maintainer decides when to merge.
