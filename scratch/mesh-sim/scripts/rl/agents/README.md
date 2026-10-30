@page scripts_rl_agents scripts/rl/agents
@brief Agent code for the RL pipeline: a MaskablePPO wrapper, training callbacks, and an exploratory Q-learning agent.

This directory holds the learning-side code used by [`../train.py`](@ref scripts/rl/train.py).
For the overall RL code map, setup, and training command, see
[scripts/rl README](@ref scripts_rl); this page does not repeat them.

## Module Layout

| File | Role |
|------|------|
| [`mask_ppo.py`](@ref scripts/rl/agents/mask_ppo.py) | `MaskablePPOConfig` and `MaskablePpoTrainer`: wraps the env in `ActionMasker` and builds a `MaskablePPO` model. |
| [`callbacks.py`](@ref scripts/rl/agents/callbacks.py) | `BoundedCheckpointCallback`, `list_checkpoints`, and `build_callbacks` (checkpoint and evaluation wiring). |
| [`post_update.py`](@ref scripts/rl/agents/post_update.py) | `PostUpdateCheckpoints` and `PostUpdateValidation`: checkpoint and validation timing after completed PPO updates, and `validate_after_update_schedule`. |
| [`q_learning.py`](@ref scripts/rl/agents/q_learning.py) | `TabularQLearning`: exploratory agent, not used for training. |
| `__init__.py` | Re-exports `TabularQLearning`, `MaskablePpoTrainer`, `MaskablePPOConfig`. |

## MaskablePPO wrapper

`MaskablePpoTrainer(cfg, env, mask_fn)` wraps `env` in `ActionMasker` so only
valid actions are sampled. `train()` calls `learn(total_timesteps)`; `save(path)`
writes the model. `MaskablePpoTrainer.load` forces `device="cpu"` so evaluation
replay is deterministic.

### Hyperparameters that reach MaskablePPO

| Field | Default | Reaches `MaskablePPO(...)` |
|-------|---------|----------------------------|
| `seed` | 42 | yes |
| `n_steps` | 1024 | yes |
| `gamma` | 0.95 | yes |
| `ent_coef` | 0.01 | yes |
| `verbose` | 1 | yes (logging only) |
| `tensorboard_log` | `None` | yes (logging only) |
| `total_timesteps` | 100000 | no; used by `learn()` as the training budget |

All other MaskablePPO settings use SB3 defaults. Adding a new tunable
hyperparameter means updating the `train.py` CLI, the train manifest,
`policy/compare.py` (`_TRAINING_SETTINGS`), and `ops/tune.py`'s `_SEARCHABLE`.

## Callbacks

`build_callbacks` returns the callback list and the eval callback (or `None`).
All cadences are SB3 timesteps (one env, one decision each).

### Checkpoints

- Enabled when `checkpoint_every > 0` (`train.py --checkpoint-every-steps`, default 0 = off).
- Files are `<out_dir>/checkpoints/checkpoint_<N>_steps.zip`, where `N` is the timestep count.
- `BoundedCheckpointCallback` deletes older files so only the newest `keep_last` remain
  (`--keep-checkpoints`, default 3, must be at least 1).
- `list_checkpoints` returns `(steps, path)` pairs in ascending order and ignores names it cannot parse.
  `policy/bundle.py` and `train.py` rely on this naming.

### Evaluation

- Enabled when `eval_every > 0` and an eval env is given.
- Uses `MaskableEvalCallback` with deterministic, masked actions.
- The best model and eval log are written under `<out_dir>` itself.

### After-update checkpoints

`train.py m-ppo --checkpoint-timing after-update` replaces the per-step
checkpoint callback with `PostUpdateCheckpoints`, which saves only after a
completed optimizer update, so a checkpoint's weights, optimizer state and
`_n_updates` agree.

- Requires `--eval-every-steps 0`, a positive cadence that is a multiple of
  `n_steps` and of the episode length, and a total budget that is a multiple of
  the cadence; restored steps must sit on a rollout boundary. A misaligned
  schedule is refused, never extended.
- Each event is recorded in `post_update_checkpoints.json` with its cumulative
  steps, completed episodes (`steps // decisions_per_episode`), optimizer
  counter and timing.
- Batch checkpoint recovery restarts only from these verified post-update
  checkpoints; see the
  [batch experiment reference](@ref mesh_sim_rl_batch_resume).

Test map: `test_checkpoint_recovery_support.py` in
[scripts/rl/tests](@ref scripts_rl_tests).

## Q-learning (exploratory)

`TabularQLearning` discretizes the observation into `(x_bin, y_bin, sinr_bin)`
and keeps a Q-table with epsilon-greedy `predict()`. It is not on the
training, evaluation, or experiment path; nothing outside `__init__.py`
imports it.

## Conventions

- One-line docstrings; longer detail lives in the READMEs.
- Package imports use the `scripts.rl.agents` path; run tools as `python -m scripts.rl.<module>` from `scratch/mesh-sim/`.

## Dependencies

- `__init__.py` imports `sb3_contrib` eagerly, so importing the package needs the full `requirements.txt`.
  Code that must work without it (for example `load_model` in `policy/bundle.py`) imports `mask_ppo` lazily.
- `mask_ppo.py` and `callbacks.py`: `stable_baselines3`, `sb3_contrib`, `gymnasium`.
- `q_learning.py`: `numpy` only.
