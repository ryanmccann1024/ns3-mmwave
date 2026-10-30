# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# scripts/rl/policy

Library behind the `evaluate` and `compare` CLIs (`../evaluate.py`,
`../compare.py`): load a saved training run, prove it fits the live env, run
policies, and compute paired statistics. The CLIs own argument parsing and exit
codes; this package owns the logic.

## Files and flow

- `bundle.py` -- `read_bundle` accepts only a `completed`, centralized
  `train_manifest.json` at the current writer version or one of the earlier
  versions explicitly accepted by `bundle.py`, and verifies the model file's SHA-256. `final`,
  `best`, or a checkpoint step can be selected. No flag bypasses a digest.
  `eval_selection` forces `telemetry=steps` so metrics come from `steps.jsonl`.
- `compat.py` -- `check_compatibility` runs in a fixed order: structural
  contract -> observation schema -> reward schema -> scenario identity
  (SHA-256s + band). Only the scenario step can be overridden
  (`--allow-different-scenario`); the others always raise. Call it before
  `load_model`.
- `evaluate.py` -- policies `hold`, `random_valid`, `model` (deterministic,
  masked). One env per policy, every policy over every seed; `eval_manifest.json`
  (`EVAL_MANIFEST_VERSION`) is rewritten after each episode so a crash leaves a
  `partial` / `failed` manifest, never none.
- `compare_inputs.py` -- loads eval manifests; `REQUIRED_MANIFEST_VERSION` must
  track `evaluate.EVAL_MANIFEST_VERSION`.
- `compare.py` -- paired model-minus-baseline stats per evaluation seed, and
  across training runs when a group has several; `PRIMARY_METRIC =
  "delivery_ratio"`, `COMPARISON_VERSION`. `exit_code` returns 2 for health
  counters or seed overlap. CI math comes from `scripts/stats.py`.

- Batch operation owners (one model, one seed; no batch scheduling here):
  `operation.py` (`run_operation`, `DiagnosticEnv`/`OperationEnv`, frozen and
  online modes, `online_manifest.json` v5 with explicit `protocol`;
  `run_online` keeps the standalone v3/v4 envelope), `online_adaptation.py`
  (`online_gated_v1`: eligible windows, buffered-gap refusal, final partial
  flush, singleton skip, `target_kl` null), `schedules.py` (frozen sampling,
  stall and coverage schedules; no defaults; never an optimizer update),
  `replay_gate.py` (`strict_v1`, `pre_contact_source_v1`; `gate_passed` is the
  success test), `reward_audit.py` (named methods `position_replay_v1`,
  `coordinated_v1`, `team_radio_v1`), `scripted.py` (both route formats and
  their controllers), `mission_metrics.py` / `episode_review.py` (formulas,
  windows and null rules unchanged; `mission_review.json` has no status field).
- `bundle.py` also owns `parameter_digest`, `optimizer_digest`,
  `checkpoint_counters` and model bindings (`bind_model`,
  `read_bound_checkpoint`, `MODEL_BINDING_VERSION`). Policy code never imports
  these from the CLI `online.py`.
- `experiment.py` is the version 1 compatibility facade; keep every public name
  and signature. Version 2 logic lives in `../experiments/`.

## Rules

- Bump the relevant version constant and its reader together when a manifest
  field changes; the `CONTRIBUTING.md` "update together" table applies.
- Comparisons group by scenario digests and training settings, not paths;
  mixing groups is an error, not a warning.
- Online protocols never merge: SB3 defaults (`learning_rate =
  min(parent, 1e-4)`, `ent_coef .001`, `target_kl .02`, untrained tail
  `budget % n_steps`) and gated accounting are pinned by tests. Every online
  operation reloads its parent per seed. Frozen modes verify unchanged
  parameter and optimizer digests.
- Tests: `tests/policy/test_policy_lifecycle.py`, `test_lifecycle_cli.py`,
  `test_evaluation_pipeline.py`, `test_policy_comparison.py`; their maps are
  `src/rl/policy-lifecycle-tests.md` and `src/rl/policy-comparison-tests.md`.
  Batch owners: `test_operation.py`, `test_online_protocols.py`,
  `test_checkpoint_recovery_support.py` (map in `tests/README.md`).

- `metrics.py` owns each metric's units, direction, export behavior, and accumulator.
  Register a metric and its accumulator; do not add parallel metric-name lists to
  evaluation, comparison, or CSV export. Per-node maps remain JSON diagnostics.
  Movement measures controlled nodes only, excludes warmup, and is null for
  missing/partial boundary data rather than inferred from sparse endpoints.

- Placement preflight resolves a dedicated channel-planning seed before any worker
  or episode starts. Keep it separate from training, selection, evaluation and
  optimizer RNG. Explicit seed overlap remains diagnostic and excluded from
  held-out groups.
- Initial source-to-plan relocation is an exported metric with no paired/group
  reduction. Show it beside scored travel in comparison JSON/CSV; never add
  it to post-reset episode movement. Keep evaluation/comparison readers aligned
  with their writers and the baseline manifest/plan contract; see the schema
  ownership in [CONTRIBUTING.md](../../../CONTRIBUTING.md).
