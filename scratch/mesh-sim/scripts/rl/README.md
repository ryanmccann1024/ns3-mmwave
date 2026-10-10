# RL code map

Start with [Python setup](../../README.md#python-environment) and the
[training command](../../README.md#maskableppo-smoke-run) in the main README.
One policy controls selected mesh nodes in 2D, including one-node runs.
Jammers and the active traffic gateway cannot be controlled.

One training episode follows this path:

1. [`train.py`](train.py) reads CLI options and starts
   [`policy/training.py`](policy/training.py). That module runs training and
   closes environments; [`policy/training_artifacts.py`](policy/training_artifacts.py)
   owns the training manifest, checkpoint records, and model provenance.
2. [`agents/mask_ppo.py`](agents/mask_ppo.py) connects MaskablePPO to the
   environment's valid-action mask.
3. [`env/mesh_env.py`](env/mesh_env.py) is the Gymnasium environment. Each
   reset starts a simulator process; each step exchanges one JSON message with
   the C++ bridge. [`env/episode.py`](env/episode.py) handles process cleanup and
   step counters; [`env/episode_artifacts.py`](env/episode_artifacts.py) owns
   episode directories and manifests. [`env/config.py`](env/config.py) reads
   the scenario seed and fingerprints.
4. [`src/rl/rl-bridge.cc`](../../src/rl/rl-bridge.cc) computes observations and
   rewards in the simulator, then applies the action it receives from Python.

[`bootstrap_venv.py`](bootstrap_venv.py) sets up Python dependencies; it does
not build the simulator. [`tests/fake_sim.py`](tests/fake_sim.py) exercises the
Python exchange without ns-3, while the simulator and regression checks cover
real runs. For saved files, see [Where output lands](../../README.md#where-output-lands).

[`agents/q_learning.py`](agents/q_learning.py) is a standalone exploratory
agent using an obsolete observation layout; it does not implement the current
joint-action contract. The training command uses MaskablePPO.

[`agents/callbacks.py`](agents/callbacks.py) adapts SB3 checkpoint and masked
evaluation callbacks. [`policy/bundle.py`](policy/bundle.py) verifies model
digests for evaluation or explicit checkpoint recovery. Resume restores policy
and optimizer state into a fresh episode; the manifest records what restarts.
See [Model lifecycle](../../README.md#model-lifecycle) for commands and budget
semantics.


[`experiment.py`](experiment.py) parses the matrix CLI; [`policy/experiment.py`](policy/experiment.py)
owns matrix validation, planning, and execution. [`agents/config.py`](agents/config.py)
owns PPO and cadence settings so planning and training validate them alike,
without requiring SB3 for matrix planning.

[`policy/metrics.py`](policy/metrics.py) owns episode reductions, units, comparison
direction, reward comparability, and metric export order. Evaluation and
comparison derive their metric lists from that registry. Add metrics there,
rather than duplicating lists in the command scripts. Evaluation schema 3
records warmup exclusion; comparison JSON remains schema 1, with the same
paired and across-run structure. Its reader validates each input's schema and
scoring metadata before writing output. The CSV also records `warmup_excluded`.
