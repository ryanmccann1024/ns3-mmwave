# Add an RL algorithm {#mesh_sim_rl_add_algorithm}

[TOC]

How any learning algorithm talks to the simulator, what the training and
evaluation tools expect from one, how to plug in another Stable-Baselines3
algorithm, and how to write your own, with a hand-written Q-learning agent
trained and evaluated beside the tutorial's model.

## 1\. Before you start

- You did the tutorial through \ref mesh_sim_rl_evaluate "Evaluate and compare",
  and know the module map from \ref mesh_sim_rl_code_map "Where the RL code lives".
- Working directory: `scratch/mesh-sim/`, with `SIM_BIN` and `OUT` set.
- Read the "update together" table in \ref Contributing "Contributing" before
  changing a manifest or the CLI.

## 2\. Pick a route

| You want | Route | Source edits | Section |
|---|---|---|---|
| A quick experiment with your own learner or a hand-written policy | Drive `MeshRlEnv` yourself and call `evaluate()` from a script | None | 6 |
| A hand-written policy selectable as `evaluate --policies <name>` | Add a policy class | `policy/evaluate.py`, `evaluate.py` | \ref mesh_sim_rl_extend "Change or extend RL", section 5 |
| Another SB3 or sb3-contrib algorithm with the full train, bundle, evaluate and compare tooling | A trainer, a CLI subcommand, manifest fields and a loader | About ten files | 5 |

## 3\. How any algorithm talks to the simulator

Whatever the algorithm, it only ever sees a Gymnasium environment,
`MeshRlEnv` (`scripts/rl/env/mesh_env.py`). The environment owns the
simulator process.

\image html rl-sequence.svg "One episode as messages between your algorithm, MeshRlEnv and the simulator process. Drawn by docs/diagrams/rl-tutorial.py from scripts/rl/env/mesh_env.py, scripts/rl/env/episode.py and src/rl/rl-bridge.cc, not from a run."

What your algorithm can rely on:

1. **`reset()` starts a new simulator process** with `--rl-mode --seed=<S>
   --output-dir=<output_dir>/episode-NNNN` and stops the previous one. Each
   episode is a separate process and a separate folder.
2. **The first line is `init`.** The environment checks it against the first
   episode's `init` and fails on any change, then builds
   `observation_space` (from the preset) and `action_space`
   (`MultiDiscrete([5] * slots)`). **Both are `None` until the first
   `reset()`**, so call `reset()` before you build a network from them; the
   tutorial's trainer does exactly that (`policy/training.py:47`).
3. **The second line is the tick-0 `step`.** `reset()` returns its observation
   and `info`. Its reward is not a learning step.
4. **`action_masks()`** returns a bool array of `5 * slots` entries for the
   current decision: west, east, south, north, hold for slot 0, then slot 1.
   Hold is always true.
5. **`step(action)`** takes one integer 0–4 per slot (a NumPy array or list),
   checks the shape and range in Python, writes `{"action":[...]}` to the
   simulator's stdin, and blocks until the next `step` line. The simulator
   checks the mask again: a masked move becomes hold.
6. **`step()` returns** `obs` (the preset rebuilt from the new facts),
   `reward` (the window's mean C++ reward, or the weighted components),
   `terminated` (true on the last step), `truncated` (always `False`) and
   `info`.
7. **`info`** holds `tick`, `time_s`, `decision`, `ticks_in_step`,
   `scored_ticks` and `revalidated_slots`, plus a `reward` breakdown when
   components are selected. It does **not** hold the facts. If your algorithm
   needs more than the observation, choose a richer preset
   (`full_facts_v1`) or add one (\ref mesh_sim_rl_extend "Change or extend RL",
   section 4).
8. **After `terminated`, call `reset()`** for the next episode, and `close()`
   at the end to stop the last process.

The constructor is
`MeshRlEnv(sim_binary, run_config, seed=None, output_dir=..., band=None, selection=None)`.
`output_dir` is required. `seed=None` uses `[scenario] seed`, and every reset
reuses that seed unless you pass `reset(seed=...)`. `selection=None` resolves
the observation and reward from `run.ini`.

## 4\. What the tools expect from an algorithm

The `train`, `inspect_model`, `evaluate` and `compare` tools are built around
MaskablePPO. Each one assumes the following:

| Tool and file | What it assumes | Algorithm-specific? |
|---|---|---|
| `train.py` | One subcommand per algorithm. Only `m-ppo` works; `qr-dqn` prints `qr-dqn is disabled in this version` and exits 1 (`train.py:68-79`). | Yes |
| `policy/training.py` (`train_mppo`) | Builds `MaskablePpoTrainer(cfg, env, mask_fn)`, wires the callbacks, calls `trainer.train(callback=..., continuing=...)`, then `artifacts.complete(trainer)`. | Yes |
| `agents/mask_ppo.py` | The trainer surface: `.model` (an SB3 model with `num_timesteps`), `train()`, `save(path)`, a static `load(path, env, mask_fn)` and a `resume()` class method. | Yes |
| `agents/callbacks.py` | Model selection uses `MaskableEvalCallback` with `use_masking=True`, which calls `model.predict(..., action_masks=...)`; checkpoints use SB3's `CheckpointCallback`. | Yes |
| `policy/training_artifacts.py` | Writes `"algorithm": "MaskablePPO"` as a constant (line 58), the `hyperparameters` from `PPO_FIELDS`, and the SHA-256 of each saved zip. | Partly |
| `policy/bundle.py` | `read_bundle` checks manifest version, `status`, `control_mode` and digests; it does not look at `algorithm`. `load_model` always calls `MaskablePPO.load(..., device="cpu")` (lines 249-253). | Yes, in `load_model` |
| `policy/evaluate.py` (`ModelPolicy`) | Calls `model.predict(obs, action_masks=mask, deterministic=...)` (lines 82-85). | Yes |
| `inspect_model.py` | Reads the manifest and checks digests; never loads the network. | No |
| `compare.py` | Reads only `eval_manifest.json`; pairs a policy named `model` with every other policy. | No |
| Every manifest | `package_versions` records the installed version of each entry in `requirements.txt` (`cli_common.py:21-29`). | A new dependency must be added there |

## 5\. Route A: another Stable-Baselines3 algorithm

### Which algorithms fit the action space

The action space is `MultiDiscrete([5] * slots)` and only the env, not the
algorithm, knows the mask. This table was produced by constructing each
algorithm on a stand-in env with `MultiDiscrete([5])` actions and an 8-value
`Box` observation, with `stable_baselines3` and `sb3_contrib` 2.9.0:

| Algorithm | Package | Accepts `MultiDiscrete`? | `predict(action_masks=...)`? |
|---|---|---|---|
| `MaskablePPO` | sb3-contrib | Yes | Yes: the only one that uses masks |
| `PPO`, `A2C` | stable-baselines3 | Yes | No |
| `TRPO`, `RecurrentPPO` | sb3-contrib | Yes | No |
| `DQN`, `QRDQN` | both | No: `Discrete` only | No |
| `ARS` | sb3-contrib | No: `Box` or `Discrete` only | No |
| `SAC`, `TD3`, `DDPG`, `TQC`, `CrossQ` | both | No: `Box` only | No |

**What happens to an algorithm without masks.** It trains and runs, but it
will sometimes choose a masked move. The simulator turns that slot's move into
hold, lists the slot in `revalidated_slots`, and prints one warning to the
episode's `sim_stderr.log`. In evaluation every such decision counts in
`revalidated` and `mask_violations`, and `evaluate` exits 2. The policy also
never learns why the move did nothing. To see it, this script sends south on
every decision of seed 11, wall or not:

```python
import os, sys
import numpy as np
from scripts.rl.env.mesh_env import MeshRlEnv

HERE = os.path.dirname(os.path.abspath(__file__))
env = MeshRlEnv(sys.argv[1], "inputs/baselines/building-bypass-smoke/run.ini", seed=11,
                output_dir=os.path.join(HERE, "unmasked"))
obs, info = env.reset()
done = False
while not done:
    masked = not env.action_masks()[2]
    obs, reward, terminated, truncated, info = env.step(np.array([2]))   # always south
    if masked or info["revalidated_slots"]:
        print(f"decision {info['decision']}: south was masked={masked}, "
              f"revalidated_slots={info['revalidated_slots']}, reward {reward:+.1f}")
    done = terminated or truncated
env.close()
```

```bash
PYTHONPATH=. .venv/bin/python outputs/rl-tutorial/custom-algorithm/unmasked.py "$SIM_BIN"
```

**Checkpoint:** 15 lines, one per decision after node-b reached y = −100,
starting

```
decision 6: south was masked=True, revalidated_slots=[0], reward +1.0
decision 7: south was masked=True, revalidated_slots=[0], reward +1.0
```

and the episode's `sim_stderr.log` contains
`Warning: RL joint action revalidated; invalid slot actions replaced by hold.`

**`Discrete`-only algorithms** (DQN, QR-DQN) need the joint action flattened
to `Discrete(5 ** slots)` with a Gymnasium `ActionWrapper`, and still ignore
masks. That was not tried for this page (unverified).

**The predict call.** Calling a non-maskable model the way `ModelPolicy` does
fails. On `PPO` it raised

```
TypeError: BaseAlgorithm.predict() got an unexpected keyword argument 'action_masks'
```

so `ModelPolicy` and the model-selection callback both need a branch.

### Step by step

This procedure comes from reading the code; it was not carried out for this
page (unverified). The example is `RecurrentPPO` from sb3-contrib, which is
already pinned in `requirements.txt` through `sb3-contrib==2.9.0`.

1. **Trainer.** Add `scripts/rl/agents/recurrent_ppo.py` with a class that has
   the same surface as `MaskablePpoTrainer`: `__init__(cfg, env, mask_fn)`
   building `RecurrentPPO("MlpLstmPolicy", env, seed=cfg.seed, ...)`,
   `.model`, `train(callback=None, continuing=False)`, `save(path)`, a static
   `load(path, env, mask_fn)` that loads on the CPU, and `resume(...)` if you
   want `--resume-run-dir`. Do not wrap the env in `ActionMasker`.
2. **Settings.** In `scripts/rl/agents/config.py`, add a config dataclass and
   its field tuple next to `MaskablePPOConfig` and `PPO_FIELDS`, and validate
   every value in `validate_training_settings` so bad values fail before a
   simulator starts.
3. **CLI.** In `scripts/rl/train.py`, add a subparser (for example `r-ppo`)
   with its options and replace `if args.modeltype != "m-ppo": return 1` with a
   dispatch. Selection and scenario options stay before the subcommand.
4. **Training loop.** `scripts/rl/policy/training.py` hard-codes
   `MaskablePpoTrainer`; take the trainer class as a parameter or add a sibling
   function. Keep the first `env.reset()` before building the model.
5. **Model selection.** In `scripts/rl/agents/callbacks.py`, `SeededEvalCallback`
   extends `MaskableEvalCallback(use_masking=True)`. Add an SB3 `EvalCallback`
   variant for unmasked algorithms; recurrent policies also need the LSTM state
   and episode-start flags passed to `predict`.
6. **Manifest.** In `scripts/rl/policy/training_artifacts.py`, record the real
   algorithm instead of the constant `"MaskablePPO"` and the new settings
   instead of `PPO_FIELDS`. If the meaning of a field changes, bump
   `MANIFEST_VERSION` and add it to the versions `policy/bundle.py` accepts
   (line 91); \ref Contributing "Contributing" lists the versions.
7. **Loader.** In `scripts/rl/policy/bundle.py`, make `load_model` dispatch on
   `manifest["algorithm"]`.
8. **Policy.** In `scripts/rl/policy/evaluate.py`, give `ModelPolicy` a path
   that calls `predict` without `action_masks` (and keeps the LSTM state across
   one episode for a recurrent policy). Decide whether it should replace masked
   choices with hold itself, so `mask_violations` stays 0.
9. **Grouping.** In `scripts/rl/policy/compare.py`, add the new settings to
   `_TRAINING_SETTINGS`, so runs with different values never group together.
10. **Dependencies.** A new package goes in `requirements.txt` (and
    `bootstrap_venv.py` installs it). Every manifest records the installed
    versions of that file's entries, so evaluation can show drift.
11. **Tests.** Extend `scripts/rl/tests/policy/test_policy_lifecycle.py` (train,
    inspect, evaluate on the fake simulator) and
    `scripts/rl/tests/experiments/test_experiment_matrix.py` if matrices should accept the
    algorithm.
12. **Docs.** Update \ref scripts_rl_agents "scripts/rl/agents",
    \ref scripts_rl "scripts/rl" and the rows named in
    \ref Contributing "Contributing".

## 6\. Route B: your own algorithm, no SB3

You need nothing but the environment from section 3. The worked example below
is a masked, tabular Q-learning agent. It imports `scripts.rl` unchanged,
trains for 600 decisions on seed 1, and then uses the same `evaluate()`
function as the `evaluate` tool, with a hand-made policy list, to play it
beside `hold` and `random_valid` on held-out seeds 11–15.

### The state

The Q-table needs a small discrete state. The agent rounds `local_links_v1`'s
`x_n` and `y_n` (features 1 and 2) to steps of 0.1: 12.5 m in x and 10 m in y.
In this scenario LOS depends only on position, so position alone is enough.

### The code

`outputs/rl-tutorial/custom-algorithm/qtable.py` (under `outputs/`, which Git
ignores):

```python
import argparse, json, os
from collections import defaultdict

import numpy as np

from scripts.rl.env.mesh_env import MeshRlEnv
from scripts.rl.env.protocol import SLOT_ACTIONS
from scripts.rl.env.selection import resolve_selection
from scripts.rl.policy.bundle import eval_selection
from scripts.rl.policy.evaluate import (HoldPolicy, PolicySpec, Prepared,
                                        RandomValidPolicy, evaluate)

RUN_CONFIG = "inputs/baselines/building-bypass-smoke/run.ini"
HERE = os.path.dirname(os.path.abspath(__file__))


def state(obs):
    """local_links_v1 slot 0: x_n and y_n, rounded to steps of 0.1 (12.5 m by 10 m)."""
    return (int(round(float(obs[1]) * 10)), int(round(float(obs[2]) * 10)))


class QTablePolicy:
    """Greedy over the valid actions of one slot; the Policy protocol evaluate() calls."""

    name = "qtable"

    def __init__(self, q):
        self.q = q

    def act(self, obs, mask, contract):
        values = np.where(mask, self.q[state(obs)], -np.inf)
        return np.array([int(np.argmax(values))], dtype=np.int64)


def train(sim_binary, steps, seed=1, gamma=0.95, alpha=0.5):
    env = MeshRlEnv(sim_binary, RUN_CONFIG, seed=seed, output_dir=os.path.join(HERE, "train"))
    q = defaultdict(lambda: np.zeros(SLOT_ACTIONS))
    rng = np.random.default_rng(seed)
    done_steps, returns = 0, []
    try:
        while done_steps < steps:
            obs, info = env.reset()                      # starts a fresh simulator process
            epsilon = max(0.05, 1.0 - done_steps / (0.6 * steps))
            total, done = 0.0, False
            while not done:
                mask = env.action_masks()                # bool, 5 per slot
                valid = np.flatnonzero(mask)
                if rng.random() < epsilon:
                    a = int(rng.choice(valid))
                else:
                    a = int(valid[np.argmax(q[state(obs)][valid])])
                nxt, reward, terminated, truncated, info = env.step(np.array([a]))
                done = terminated or truncated
                target = reward
                if not done:
                    target += gamma * np.max(q[state(nxt)][np.flatnonzero(env.action_masks())])
                q[state(obs)][a] += alpha * (target - q[state(obs)][a])
                obs, total, done_steps = nxt, total + reward, done_steps + 1
            returns.append(total)
            print(f"episode {len(returns):3d}  steps {done_steps:4d}  epsilon {epsilon:.2f}  return {total:+.1f}")
    finally:
        env.close()
    with open(os.path.join(HERE, "qtable.json"), "w") as fh:
        json.dump({"returns": returns, "q": {f"{k[0]},{k[1]}": v.tolist() for k, v in q.items()}},
                  fh, indent=1)
    return q
```

and its `main()`, which trains (or reloads `qtable.json` with `--load`) and
evaluates:

```python
    seeds = [int(s) for s in args.seeds.split(",")]                 # 11,12,13,14,15
    selection = eval_selection(resolve_selection(RUN_CONFIG))     # forces steps.jsonl
    out = os.path.join(HERE, "eval" if args.name == "qtable" else f"eval-as-{args.name}")
    specs = [PolicySpec(args.name, lambda env, first: Prepared(QTablePolicy(q))),
             PolicySpec("hold", lambda env, first: Prepared(HoldPolicy())),
             PolicySpec("random_valid", lambda env, first: Prepared(RandomValidPolicy()))]

    def make_env(name):
        return MeshRlEnv(args.sim_binary, RUN_CONFIG, seed=seeds[0],
                         output_dir=os.path.join(out, name), selection=selection)

    manifest = evaluate(make_env, specs, seeds, out, {"label": "qtable-demo"})
```

The parts that matter for any algorithm:

- **Masks in the policy, not after.** Exploration samples only from
  `np.flatnonzero(mask)`, and greedy choice is an `argmax` over valid actions
  only. The bootstrap target also maxes over the next decision's valid
  actions. The agent never sends a masked move.
- **One action per slot.** `env.step(np.array([a]))`, even with one slot.
- **`eval_selection`** forces per-decision telemetry, because evaluation
  metrics are computed from `steps.jsonl`.
- **`PolicySpec(name, build)`**: `build(env, first_seed)` returns
  `Prepared(policy)`; the policy needs a `name` and
  `act(obs, mask, contract)` returning one integer per slot, and may have
  `start_episode(seed)`.

### Run it

```bash
PYTHONPATH=. .venv/bin/python outputs/rl-tutorial/custom-algorithm/qtable.py \
  --sim-binary "$SIM_BIN" --steps 600
```

`PYTHONPATH=.` lets a script outside the package import `scripts.rl`.

**Checkpoint:** after about 35 seconds, 30 episode lines, the first and last
reading

```
episode   1  steps   20  epsilon 1.00  return -12.6
...
episode  30  steps  600  epsilon 0.05  return +13.8
```

then

```
qtable: mean_return=14.00 episodes=5/5 mask_violations=0 los_fraction=0.850
hold: mean_return=-20.00 episodes=5/5 mask_violations=0 los_fraction=0.000
random_valid: mean_return=-10.28 episodes=5/5 mask_violations=0 los_fraction=0.243
```

\image html rl-custom.svg "The Q-learning example. Left: return of each of its 30 training episodes on seed 1 (outputs/rl-tutorial/custom-algorithm/qtable.json). Right: held-out seeds 11-15 for the Q-table, random_valid and hold, with means and 95% t intervals (outputs/rl-tutorial/custom-algorithm/eval)."

### What it learned, next to MaskablePPO

| On held-out seeds 11–15 | MaskablePPO (8,192 decisions) | Q-table (600 decisions) |
|---|---|---|
| Return, every seed | 15.6 | 14.0 |
| `first_all_los_decision` | 4 | 4 |
| `los_fraction` | 0.89 | 0.85 |
| `travel_m_total` | 390 m | 80 m |
| Path | South 100 m, east to the corner, then back and forth | North 40 m, west 40 m to (160, 40), then holds |

The Q-table leaves the shadow one decision later: its third move, west from
(200, 40) to (180, 40), ends exactly on the shadow's edge
(\f$40 \times 90/180 = 20\f$, not more than 20), so that window is still all
NLOS. It then holds: in its table's state for (160, 40), hold is worth 10.1
and no other move more than 4.3. It never learned that more LOS ticks were
available sooner. Lower return, a fifth of the travel: the reward cannot see
the travel, but the domain metrics can.

### Pair it with compare

`compare` pairs the policy named `model` with every other policy. Run the
evaluation again under that name, reusing the saved table, then compare:

```bash
PYTHONPATH=. .venv/bin/python outputs/rl-tutorial/custom-algorithm/qtable.py \
  --sim-binary "$SIM_BIN" --load outputs/rl-tutorial/custom-algorithm/qtable.json --name model
.venv/bin/python -m scripts.rl.compare \
  --eval-dirs outputs/rl-tutorial/custom-algorithm/eval-as-model \
  --output-dir outputs/rl-tutorial/custom-algorithm/compare
```

**Checkpoint:** `compare` exits 0 and prints

```
qtable-demo eval-as-model vs hold  delivery_ratio  -0.0010 [-0.0038, +0.0018]  paired t, 5/5 evaluation seeds, fixed model
qtable-demo eval-as-model vs random_valid  delivery_ratio  -0.0010 [-0.0038, +0.0018]  paired t, 5/5 evaluation seeds, fixed model
qtable-demo (group)       vs hold  delivery_ratio  n/a  0/1 training runs; no interval
qtable-demo (group)       vs random_valid  delivery_ratio  n/a  0/1 training runs; no interval
```

and `comparison.json` gives `return` +34.0 against `hold` (zero variance) and
+24.28 [+13.11, +35.45] against `random_valid`. The group lines have no
interval because there is no training manifest, so no training run to count.

### What you give up outside the tools

Calling `evaluate()` from your own script skips everything the `evaluate`
tool does around it:

- **No bundle.** There is no `train_manifest.json`, so no digest check, no
  record of the training settings and nothing for `inspect_model`.
- **No seed-role enforcement.** The manifest's `seed_roles` and `training`
  are `null`, and nothing stops you evaluating on your training seed. Keep
  the roles apart yourself (here: training 1, held out 11–15).
- **No compatibility checks.** Nothing compares the evaluation scenario,
  preset or reward with what you trained on.

To get those, wrap your algorithm as in section 5, writing the same manifest
fields.

## 7\. Going further

- \ref src_rl "src/rl": the wire contract, if you want to drive the simulator
  without `MeshRlEnv` (not recommended: you would re-implement its checks).
- \ref scripts_rl_env "scripts/rl/env": the environment's own reference.
- \ref mesh_sim_rl_assumptions "Every assumption", section 10: what the
  current PPO setup assumes.

<!-- Provenance: executed 2026-10-28 with build/scratch/mesh-sim/ns3.42-sim-debug
     (sha256 d7a2f4d1...6c9fe2), mesh-sim commit b54bfbe7 plus the working tree,
     stable_baselines3/sb3_contrib 2.9.0. Scripts and outputs under
     outputs/rl-tutorial/custom-algorithm/; logs custom.log, custom-as-model.log,
     custom-compare.log and unmasked.log in outputs/rl-tutorial/logs/. The
     algorithm table came from constructing each class on a stand-in env. Route A
     steps and the Discrete wrapper: source inspection only, unverified. -->

Previous: \ref mesh_sim_rl_extend "Change or extend RL"
