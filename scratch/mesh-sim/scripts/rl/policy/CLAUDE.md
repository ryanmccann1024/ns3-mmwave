# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# scripts/rl/policy

Library behind the `evaluate` and `compare` CLIs (`../evaluate.py`,
`../compare.py`): load a saved training run, prove it fits the live env, run
policies, and compute paired statistics. The CLIs own argument parsing and exit
codes; this package owns the logic.

## Files and flow

- `bundle.py` -- `read_bundle` accepts only a `completed`, centralized
  `train_manifest.json` at `MANIFEST_VERSION` (must equal
  `train.MANIFEST_VERSION`) and verifies the model file's SHA-256. `final`,
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

## Rules

- Bump the relevant version constant and its reader together when a manifest
  field changes; the `CONTRIBUTING.md` "update together" table applies.
- Comparisons group by scenario digests and training settings, not paths;
  mixing groups is an error, not a warning.
- Tests: `tests/test_policy_lifecycle.py`, `test_lifecycle_cli.py`,
  `test_evaluation_pipeline.py`, `test_policy_comparison.py`; their maps are
  `src/rl/policy-lifecycle-tests.md` and `src/rl/policy-comparison-tests.md`.

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
  it to post-reset episode movement. Evaluation v5 and comparison v2 readers
  must stay aligned with baseline manifest/plan v3.
