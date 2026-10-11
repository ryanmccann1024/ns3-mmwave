@page scripts_rl scripts/rl
# RL code map

Python side of mesh-sim RL: a Gymnasium environment that drives the simulator
over a stdin/stdout JSON bridge, MaskablePPO training, saved-policy evaluation
and comparison, and experiment matrices. The wire contract lives in
[`src/rl/README.md`](../../src/rl/README.md); this page only says where things are.

Start with [Python setup](../../README.md#python-environment) and the
[smoke run](../../README.md#maskableppo-smoke-run) in the main README.

## Control modes

Chosen in `run.ini`, not on the command line.

- **Legacy single-node**: one `controlled_node_id`, `Discrete(7)` action, no
  `init` message. The jammer is part of the scenario, not an agent.
- **Centralized multi-node**: `controlled_nodes`, `MultiDiscrete([5]*M)` action.
  C++ owns masks and clamping; Python builds observations and rewards from the
  raw facts. See [Centralized multi-node control](../../README.md#centralized-multi-node-control)
  and [Selecting observations, rewards, and telemetry](../../README.md#selecting-observations-rewards-and-telemetry).

## Lifecycle

Each stage writes a manifest that the next one reads. Details are in
[Model lifecycle](../../README.md#model-lifecycle).

1. [`validate_config.py`](validate_config.py): pre-flight check of scenario,
   selection, and binary; `--launch` adds one real reset.
2. [`train.py`](train.py): trains MaskablePPO; writes `train_manifest.json`,
   the model, checkpoints, and per-episode `rl_episode.json`.
3. [`inspect_model.py`](inspect_model.py): prints manifest provenance and
   verifies model file digests (`--run-dir`).
4. [`evaluate.py`](evaluate.py): loads the training run as a verified bundle,
   runs the model and baselines (for example hold) on `--seeds`; writes
   `eval_manifest.json`.
5. [`compare.py`](compare.py): paired model-minus-baseline statistics from
   `--eval-dirs` or `--plan`; writes `comparison.json` and `episodes.csv`.

`evaluate` and `compare` exit `2` for warnings (for example seed overlap); see
[Comparing policies](../../README.md#comparing-policies-and-running-an-experiment-matrix).

## Experiment matrices

[`experiment.py`](experiment.py) expands an explicit matrix
(`inputs/experiments/*.json`) into `experiment_plan.json`, then runs the
train, evaluate, and compare steps. Subcommands: `plan`, `run`, `status`.
Set `evaluation.decision_records` to `true` to write opt-in decision sidecars
for evaluated episodes; the default is off and training is unchanged.
Step state comes only from each step's output directory and manifest, so a
changed matrix, binary, or `--rows` needs a new `--output-root`.

## Module Layout

| File | Role |
| --- | --- |
| [`__init__.py`](__init__.py) | Registers `mesh_sim/MeshEnv-v0` with Gymnasium |
| [`bootstrap_venv.py`](bootstrap_venv.py) | Creates `.venv` from `requirements.txt` and checks pins; does not build the simulator |
| [`cli_common.py`](cli_common.py) | Shared CLI options, atomic JSON writes, hashes, package versions |
| [`validate_config.py`](validate_config.py) | Pre-flight scenario check |
| [`train.py`](train.py) | MaskablePPO training CLI |
| [`inspect_model.py`](inspect_model.py) | Training-run summary |
| [`evaluate.py`](evaluate.py) | Policy and baseline evaluation CLI |
| [`compare.py`](compare.py) | Paired comparison CLI |
| [`experiment.py`](experiment.py) | Experiment matrix planner and runner |

## Subdirectories

| Directory | Contents |
| --- | --- |
| @ref scripts_rl_agents | MaskablePPO glue; exploratory `q_learning.py` (not on the training path) |
| @ref scripts_rl_env | Gymnasium env, simulator subprocess, protocol checks, selection, observations, rewards, telemetry |
| @ref scripts_rl_policy  | Bundle loading, compatibility checks, evaluation, comparison |
| @ref scripts_rl_ops | SLURM, benchmark, and tuning wrappers around an existing plan |
| @ref scripts_rl_tests | Test map; `fake_sim.py` exercises the Python exchange without ns-3 |

The C++ end of the bridge is [`src/rl/rl-bridge.cc`](../../src/rl/rl-bridge.cc).
For saved files, see [Where output lands](../../README.md#where-output-lands).

## Dependencies

Python packages are pinned in `requirements.txt` (installed by
`bootstrap_venv.py`); Optuna for `ops/tune.py` is in `requirements-tuning.txt`.
An already-built simulator binary is passed with `--sim-binary`.

## Multiple-seed checkpoint evaluation

`train ... m-ppo --eval-episodes 10 --eval-seeds 201-210` freezes the policy and
uses the complete seed set at each checkpoint. Without `--eval-seeds`,
validation seeds run consecutively from `--eval-seed` for `--eval-episodes`
episodes. Experiment matrices accept an integer, list, or range in
`seeds.model_selection`; a list means one episode per seed. Validation and
held-out seeds must be disjoint from training. Seed-overlap checks reserve all
validation seeds, including when reading a best-model bundle.

Checkpoint and final evaluation produce episode-by-decision reward matrices,
means, sample standard deviations and cumulative reward curves in
`reward_matrix.{json,csv}`. Checkpoint matrices live under
`train/.../eval/checkpoint-<step>/`; final matrices live under each policy's
evaluation directory. Centralized validation forces full decision telemetry.
Incomplete or sparsely recorded episodes do not become zero-padded rows.
Default PPO logging includes `ppo/progress.csv` with entropy, value loss,
approximate KL, clipping fraction and explained variance; explicit TensorBoard
logging retains its existing behavior.

The synthetic October 9 campaign and phase launcher are documented in
`inputs/custom/10-09/README.md`. `scripts.rl.preflight_campaign` checks the
binary's coverage/obstacle/proximity features and verifies healthy hold
fixtures before a campaign starts. Source setup does not validate radio
scenario difficulty; use a rebuilt binary and inspect the preflight metrics.

## Local concurrency

`python -m scripts.rl.campaign --config <campaign.json> [--plan-only]` prepares
existing experiment plans and dispatches row/seed jobs through
`ops.run_task`, with bounded local concurrency. The configuration owns paths,
worker/thread counts and preflight/pilot/main stages. Training and evaluation
within a job stay ordered; comparison has one writer per matrix. See the
October 9 campaign example for configuration and recovery behavior.

The local quick campaign under `inputs/custom/10-09/local-fast/` uses one
training seed and three explicit reward rows per scenario. `campaign.py`
prints worker progress every 30 seconds and writes `reward_comparison.csv`
using common domain metrics instead of comparing unlike reward returns.
Optional campaign `preflight.seeds` and `challenge_delivery_max` enable
multi-seed difficulty checks; criteria are included in the saved signature.

## Main-only campaign, compact output and baseline reuse

See [iteration-two configuration](../../inputs/custom/10-09-2/README.md). `campaign.py` runs only requested execution stages; main-only skips preflight. Optional `initial_scenarios` gates remaining main jobs on the first group. Saved-model diagnostics compare deterministic/sampled inference and explicit scenario transfer without weight updates.

Matrix evaluation can set `reuse_baselines=true`; the CLI uses `--baseline-cache-dir`, validates a binary/scenario/seed/planner identity, reuses immutable baseline trajectories, and rescales their composed rewards. `eval_manifest_version=3` records `baseline_cache`; comparison readers accept 2 and 3. `--stochastic-model` enables sampled inference, reseeded for each evaluation episode. `--decision-record-seeds` restricts detailed sidecars to selected held-out seeds.

## Bounded profiles and continuing operation

`adaptive_campaign` drives `inputs/custom/10-09-3/campaign.json`: four cases × six profiles, validation-only profile selection, eight extensions, archived-reference evaluation and moving-jammer operation. See that input README for the command and budgets. `online` loads one verified checkpoint per operation seed and runs the PPO learning loop with short rollouts; its matched sampled control never trains. Adaptation results use `online_manifest.json` and explicit seed-role labels. `policy/episode_review.py` adds final-minute service and moving-jammer recovery to campaign reports without changing normal evaluation manifest fields.
