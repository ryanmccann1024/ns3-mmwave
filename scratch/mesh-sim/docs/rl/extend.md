# Change or extend RL {#mesh_sim_rl_extend}

[TOC]

Where each kind of RL change goes, the exact files to touch, and the checks to
run, with examples tested on real simulator output.

## 1\. Before you start

- You know which module owns what:
  \ref mesh_sim_rl_code_map "Where the RL code lives".
- Read the "update together" table in \ref Contributing "Contributing" before
  changing anything users see. It lists the docs and checks that must change
  with the code.
- Working directory: `scratch/mesh-sim/`.

## 2\. Pick the right place

| You want to change | Where | Python only? | Old models still load? |
|---|---|---|---|
| What the policy learns from | A reward component (section 3) | Yes | Only models trained with that reward |
| What the policy sees | An observation preset (section 4) | Yes | Only models trained with that preset |
| What it is compared against | An evaluation policy (section 5) | Yes | Yes |
| What evaluation measures | A metric (section 6) | Yes | Yes |
| A PPO setting | `agents/` and `train.py` (section 7) | Yes | Yes |
| The C++ per-tick reward | `rl-bridge.cc` (section 8) | No: you rebuild | Only models trained with it |
| The moves themselves | A new contract (section 9) | No: you rebuild | No |
| The learning algorithm | A new trainer and loader (\ref mesh_sim_rl_add_algorithm "Add an RL algorithm") | Yes | Yes, if the loader still reads MaskablePPO bundles |

**Why "only models trained with it".** Every reward and preset definition is
hashed into the training manifest. Evaluation refuses a model whose saved hash
differs from the live one. So never change an existing component or preset in
place. Add a new one with a new name, such as `_v2`, and old models stay
loadable.

## 3\. Add a reward component

A component turns one decision window's facts into a number, plus a flag saying
whether the window was valid. The example rewards the share of node-pair ticks
that were line of sight.

In `scripts/rl/env/rewards/__init__.py`, add the function next to the others and an
entry to `COMPONENTS`:

```python
def _los_pair_fraction(window, msg_reward, contract, parameters, context):
    """Share of node-pair ticks that were line of sight in this window."""
    pairs = int(window["scored_ticks"]) * int(contract["num_links"])
    if pairs <= 0:
        return 0.0, False
    return float(window["los_pairs_sum"]) / pairs, True

COMPONENTS["los_pair_fraction"] = RewardComponent(
    "los_pair_fraction", _los_pair_fraction, (0.0, 1.0), ("los_pairs_sum",),
    contract_fields=("num_links",), formula="los_pairs_sum/(scored_ticks*num_links)")
```

| `RewardComponent` field | Meaning |
|---|---|
| name, function, range | The function gets `(window, msg_reward, contract, parameters, context)` and returns `(value, valid)`. An invalid window adds nothing. |
| `required_facts` | The `facts.window` keys or fact tables it reads. |
| `contract_fields` | `init` fields it reads. They become part of its identity. |
| `tunable` | `{name: (default, low, high)}` parameters users can set through `reward_parameters`. |
| `context_fields`, `context_builder` | For components that need positions from earlier decisions, such as travel. |
| `formula` | Human-readable formula, saved in the reward schema. |

A family of related components can live in its own `*_components.py` module
with a `register(RewardComponent, COMPONENTS, …)` function, called at the
bottom of `rewards/__init__.py`, as the mission families do.

**Use it.** No other code changes: selection, the composer, telemetry replay
and the schema all read `COMPONENTS`.

```ini
reward_components = los_pair_fraction, delivery_ratio
reward_weights    = 1.0, 0.5
```

**Checkpoint.** Registered at run time (no source edited) by
`outputs/rl-tutorial/extend-examples/check.py` and composed on the first
decisions of the real episode from \ref mesh_sim_rl_how_it_works "How a decision works":

```
decision 1 total 0.5 {'los_pair_fraction': 0.0, 'delivery_ratio': 1.0}
decision 2 total 0.5 {'los_pair_fraction': 0.0, 'delivery_ratio': 1.0}
decision 3 total 1.3 {'los_pair_fraction': 0.8, 'delivery_ratio': 1.0}
```

Decision 3 is the window where the link turned LOS for 8 of its 10 ticks. The
reward schema's `authority` changes from `cpp` to `python`.

**Tests:** add formula and masking cases next to `test_other_components` in
`scripts/rl/tests/env/test_observations_rewards/__init__.py`, then run

```bash
.venv/bin/python -m pytest scripts/rl/tests/env/test_observations_rewards/__init__.py \
  scripts/rl/tests/env/test_reward_boundaries.py scripts/rl/tests/env/test_policy_input_parameters.py -q
```

**Checkpoint** (before adding your component): `214 passed`.

`test_policy_input_parameters.py` already loops over every registered
component, including the zero-scored-window mask. `test_reward_boundaries.py`
lists its window components by name; add yours to `WINDOW_COMPONENTS` there.
Then
document the formula in \ref src_rl_policy_inputs "Policy inputs", section 5.

## 4\. Add an observation preset

A preset turns the facts at a decision into the policy's input vector. The
example gives each slot its raw x and y.

In `scripts/rl/env/observations/__init__.py`, add a builder, a space, the feature names
and an entry to `PRESETS`:

```python
def _build_slot_xy_v1(facts, contract):
    """Each slot's raw x and y; padded slots are zero."""
    out = np.zeros(2 * contract["max_controlled_nodes"], dtype=np.float32)
    for row in facts["nodes"]:
        slot = int(row[6])
        if slot >= 0:
            out[2 * slot:2 * slot + 2] = row[0], row[1]
    return out

def _slot_xy_space(contract):
    return spaces.Box(-np.inf, np.inf, (2 * contract["max_controlled_nodes"],), np.float32)

def _slot_xy_features(contract):
    return [f"slot{s}_{axis}" for s in range(contract["max_controlled_nodes"]) for axis in ("x", "y")]

PRESETS["slot_xy_v1"] = ObservationPreset(
    "slot_xy_v1", "float32", _build_slot_xy_v1, _slot_xy_space, _slot_xy_features,
    {"position": "raw"}, required_facts=("nodes",))
```

**Rules:**

- **Same length every decision.** The length depends only on `init`, never on
  the state. Padded slots are zeros.
- **Space matches the build.** The `Box` bounds and dtype must match what the
  builder returns.
- **Declare your dependencies.** List the fact tables you read in
  `required_facts`. When the preset depends on the movement bounds, list
  `"bounds"` in `compatibility_fields`, so a model trained with other bounds
  is refused.
- **Scales go in the normalization.** Put tunable scales in
  `normalization_fields` and read them from the `Normalization` argument, as
  `local_links_v1` does.

**Checkpoint.** Built from the real reset facts:
`[200. 0.] Box(-inf, inf, (2,), float32) ['slot0_x', 'slot0_y']`. Select it with
`observation_preset = slot_xy_v1`.

**Tests:** `scripts/rl/tests/env/test_observation_boundaries.py` loops over every
entry in `PRESETS`. It checks determinism, that the dtype, length and space
agree, and that schema hashes are unique, so a new preset is checked
automatically. Add exact-value cases next to
`test_local_links_v1_exact_slot_vector` in `test_observations_rewards/__init__.py`, then
run

```bash
.venv/bin/python -m pytest scripts/rl/tests/env/test_observations_rewards/__init__.py \
  scripts/rl/tests/env/test_observation_boundaries.py -q
```

**Checkpoint** (before adding your preset, on the working tree used for this
guide): `21 failed, 147 passed`. The 21 failures are the mission presets'
fixture errors listed on \ref mesh_sim_rl_code_map "Where the RL code lives",
section 5; they are there before any change. Your new preset must add no new
failure.

Document the features in \ref src_rl_policy_inputs_observation "What the observation contains".

## 5\. Add an evaluation policy

A policy has a `name` and `act(obs, mask, contract)` returning one action per
slot. It may also have `start_episode(seed)` to reseed itself. The example
moves east whenever east is allowed.

1. In `scripts/rl/policy/evaluate.py`, next to `HoldPolicy`:

   ```python
   class EastPolicy:
       """Move east whenever east is allowed, otherwise hold."""

       name = "east"

       def act(self, obs, mask, contract) -> np.ndarray:
           flat = np.asarray(mask, dtype=bool).reshape(-1, SLOT_ACTIONS)
           return np.where(flat[:, 1], 1, HOLD_ACTION).astype(np.int64)
   ```

2. In the same file, add the name to the accepted list without changing the
   default list:

   ```python
   POLICY_NAMES = DEFAULT_POLICIES + PLACEMENT_POLICIES + ("east",)
   ```

3. In `scripts/rl/evaluate.py`, `_baseline_spec` currently maps every
   non-`hold` name to `RandomValidPolicy`. Give the new name its own branch.

`--policies model,hold,east` then works, and so do matrices, because
`policy/experiment.py` validates against the same `POLICY_NAMES`. `compare`
pairs `model` with every other policy it finds.

**Checkpoint.** On the real mask of decision 6, `[1, 1, 0, 1, 1]` (south
masked, east allowed), `EastPolicy().act(...)` returns `[1]`; on decision 8's
`[1, 0, 0, 1, 1]` it returns `[4]` (hold).

**Tests:** add a case next to the `HoldPolicy` and `RandomValidPolicy` checks
in `scripts/rl/tests/policy/test_policy_lifecycle.py`, then run

```bash
.venv/bin/python -m pytest scripts/rl/tests/policy/test_policy_lifecycle.py \
  scripts/rl/tests/policy/test_evaluation_pipeline.py -q
```

**Checkpoint** (before adding your policy): `115 passed` in about 30 s.

## 6\. Add an evaluation metric

Metrics live in the `REGISTRY` dictionary in `scripts/rl/policy/metrics.py`.
Each entry gives units, whether higher is better, whether it compares across
reward definitions, and a reduction over an accumulator. Add a new entry
inside the `REGISTRY = {...}` literal, because derived lists such as
`CSV_METRICS` are built from it once at import:

```python
    "nlos_fraction": Metric("fraction", False, True, lambda t: _ratio(t.pairs - t.los, t.pairs)),
```

**Checkpoint.** On the real model episode: `los_fraction` 0.89,
`nlos_fraction` 0.11.

Then follow the "Comparison metrics" row of \ref Contributing "Contributing":
the evaluation writer, `comparison.json` and `episodes.csv`, the schema
version, tests (`test_metrics.py`) and the fetch include rules.

## 7\. Add a PPO setting

Settings reach MaskablePPO through one path. Change all of it:

| File | Change |
|---|---|
| `scripts/rl/agents/config.py` | Add the field to `MaskablePPOConfig` and `PPO_FIELDS`, and its range to `validate_training_settings`. Add it to `PPO_SEARCH_PARAMETERS` if `ops.tune` may search it. |
| `scripts/rl/agents/mask_ppo.py` | Pass it to `MaskablePPO(...)`. |
| `scripts/rl/train.py` | Add the `m-ppo` option. |
| `scripts/rl/policy/compare.py` | Add it to `_TRAINING_SETTINGS`, so runs with different values never group together. |
| `scripts/rl/policy/training_artifacts.py` | Nothing to add: it copies every `PPO_FIELDS` entry into the manifest's `hyperparameters`. Bump `manifest_version` if the field set's meaning changes (\ref Contributing "Contributing"). |

Run `scripts/rl/tests/policy/test_policy_lifecycle.py`,
`scripts/rl/tests/experiments/test_experiment_matrix.py` and `test_ops_tune.py`.

## 8\. Change the C++ per-tick reward

`reward_type` values are computed in `src/rl/rl-bridge.cc` (the function after
the comment at line 79), validated in `src/config/config-validator.cc`
(`reward_type` must be `throughput` or `all_links_los`) and documented in
`src/domain/sim-config.h`. A new value needs all three, a C++ test in
`tests/unit/rl-bridge`, and a rebuild, which you do yourself. Before you do
this, check whether a Python component (section 3) can express it from the
facts. That needs no rebuild.

## 9\. Change the moves

There is one action profile, `move_2d`, and its meaning is the contract
`mesh_move_2d_v2`. A different action set changes the wire format, so it is a
new contract, not a setting. This was not tried for this page. From the
source, it touches:

| Side | Files |
|---|---|
| C++ | `src/config/rl-control.cc` (accepted profiles), `src/domain/sim-config.h`, `src/rl/rl-bridge.cc` (action meanings, masks, applying actions, the contract name at line 243), `src/io/run-logger.h` (contract name in `run.log`) |
| Python | `scripts/rl/env/protocol.py` (`_CONTRACTS`, `SLOT_ACTIONS`, `HOLD_ACTION`), `scripts/rl/env/config.py` (default profile), `scripts/rl/policy/evaluate.py` (hold value), `scripts/rl/policy/experiment.py` (row `action_profile` check) |
| Tests | `tests/unit/rl`, `tests/unit/rl-bridge`, `scripts/rl/tests/env/test_mesh_env.py`, `test_real_binary.py` |
| Docs | \ref src_rl "src/rl" contract section, \ref Contributing "Contributing" |

Change the contract name only for an incompatible change. Every model trained
under the old contract is then refused, by design.

## 10\. Run everything

```bash
.venv/bin/python -m pytest scripts/rl/tests -q
MESH_SIM_BIN="$SIM_BIN" .venv/bin/python -m pytest scripts/rl/tests/integration/test_real_binary.py -q
make -C tests/unit/rl test
make -C tests/unit/rl-bridge test
```

For a protocol or simulator change, also run `make -C tests/unit/config test`
and `make -C tests integration` against a fresh build. Without `MESH_SIM_BIN`,
the real-binary tests are skipped, which means they did not run.

**Checkpoint:** the two C++ suites end with

```
Reward warmup, boundary, mean, and reset checks passed.
joint motion: crossing, altitude, wall clipping, cascade and safe motion passed
178 passed, 0 failed
```

The Python suite's result on the working tree used for this guide, with its
30 unrelated failures, is on \ref mesh_sim_rl_code_map "Where the RL code lives",
section 5. Compare your run against the same command on an unmodified checkout
before blaming your change. The real-binary tests were not run for this page.

## 11\. Going further

- \ref mesh_sim_rl_add_algorithm "Add an RL algorithm": replace MaskablePPO,
  or bring your own learner.
- \ref mesh_sim_rl_assumptions "Every assumption": what each of these
  extension points currently assumes.

Previous: \ref mesh_sim_rl_code_map "Where the RL code lives" · Next: \ref mesh_sim_rl_add_algorithm "Add an RL algorithm"
