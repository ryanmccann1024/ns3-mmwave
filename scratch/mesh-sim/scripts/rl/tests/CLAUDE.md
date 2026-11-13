# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# scripts/rl/tests

Pytest suite for `scripts/rl`. Run from `scratch/mesh-sim/`; tests write only to
pytest temp dirs, never to `inputs/`.

```bash
.venv/bin/python -m pytest scripts/rl/tests -q
.venv/bin/python -m pytest scripts/rl/tests/env/test_mesh_env.py::<test_name>
MESH_SIM_BIN=/abs/path/to/bin .venv/bin/python -m pytest scripts/rl/tests/integration/test_real_binary.py -q
```

## Fakes

- `support/fake_sim.py` -- stand-in simulator speaking the same flags and the
  centralized RL protocol. `FAKE_SIM_MODE` selects fault
  modes; `FAKE_SIM_FAIL_SEEDS` kills chosen seeds mid-episode. It has no radio
  model, so it proves protocol handling, never movement or reward correctness.
  Protocol changes in `src/rl/rl-bridge.cc` must be mirrored here.
- `support/fake_slurm.py` -- `sbatch`/`squeue`/`sacct`/`scancel` shims sharing one JSON
  state file (`FAKE_SLURM_STATE`), installed via `fake_slurm.install(tmp_path)`.
- `conftest.py` -- shared `sim_binary` (shell shim that execs `support/fake_sim.py`) and
  `multi_run_config` (centralized 3-node scenario) fixtures. Use these fixtures and the shared `support/` helpers in new tests.

## Skips

- `integration/test_real_binary.py` skips entirely without `MESH_SIM_BIN`; it uses
  `inputs/baselines/centralized-multi-smoke/`. Run it against a fresh build after any
  protocol or `mesh_env` change.
- Tests needing `sb3_contrib`, Optuna (`requirements-tuning.txt`), or pandas
  skip when those are missing, so a green run may hide skipped coverage; use
  `-rs` to see skips.

## Test maps

Each test's input and expected output is documented, and new tests should be
added to the matching map:

- `README.md` here -- `env/test_mesh_env.py`, `integration/test_real_binary.py`, the C++
  config/CLI RL tests, `cluster/test_ops_{tasks,benchmark,cluster,fetch}.py`,
  `tuning/test_ops_tune.py`,
  `tooling/test_bootstrap_venv.py`, and the batch operation owners
  `policy/test_online_protocols.py`, `policy/test_operation.py`, `policy/test_operate_cli.py`
  and `env/test_geometry.py`, `env/test_curriculum.py` and `env/test_seeded_env.py`.
- `ops-tests.md` here -- every `cluster/`, `ops/` and `tuning/` test file:
  task execution, measurement, tuning, cluster, fetch, and the batch scheduler
  and recovery tests.
- `src/rl/policy-input-tests.md` -- `env/test_observations_rewards.py`,
  `env/test_registry_identity.py` and the policy-input cases in `env/test_mesh_env.py` /
  `integration/test_real_binary.py`.
- `src/rl/policy-lifecycle-tests.md` -- `policy/test_lifecycle_cli.py`,
  `policy/test_policy_lifecycle.py`, `agents/test_checkpoint_recovery_support.py`.
- `src/rl/policy-comparison-tests.md` -- `policy/test_evaluation_pipeline.py`,
  `experiments/test_experiment_matrix.py`, `policy/test_policy_comparison.py`, `experiments/test_matrix_v2.py`,
  `experiments/test_gui_index.py`, `experiments/test_conversion_parity.py`.
- `src/rl/decision-records.md` -- `env/test_decision_records.py` and
  `env/test_decision_record_contract.py`.
