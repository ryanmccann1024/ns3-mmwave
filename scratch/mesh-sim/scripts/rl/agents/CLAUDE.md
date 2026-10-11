# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# scripts/rl/agents

Thin SB3 wrappers used by `train.py` and `policy/bundle.py`.

- `mask_ppo.py` -- config and constructor for masked PPO. CLI and matrices expose
  rollout, discount, entropy and its optional decay endpoint, learning rate,
  minibatch, GAE, clipping, epochs, target KL, and actor/critic layer widths.
  Entropy decay is applied by `callbacks.py` at rollout boundaries. Keep CLI,
  manifest, comparison grouping and scalar Optuna search knobs aligned; network
  widths are explicit matrix profiles rather than scalar Optuna suggestions.
- `MaskablePpoTrainer.load` forces `device="cpu"` so evaluation replay is
  deterministic; keep it that way.
- `callbacks.py` -- `BoundedCheckpointCallback` (keeps the newest `keep_last`
  `checkpoints/checkpoint_<N>_steps.zip`) and `MaskableEvalCallback` wiring.
  All cadences are SB3 timesteps, i.e. one RL decision each. `policy/bundle.py`
  depends on the checkpoint naming via `list_checkpoints`.
- `q_learning.py` -- exploratory tabular agent for the legacy single-node mode;
  not on the training, evaluation, or experiment path.

`agents/__init__.py` imports `sb3_contrib` eagerly, so importing this package
needs the full `requirements.txt`. Code that must work without it (e.g.
`policy/bundle.py::load_model`) imports `mask_ppo` lazily.
