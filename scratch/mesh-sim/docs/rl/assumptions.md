# Every assumption {#mesh_sim_rl_assumptions}

[TOC]

Every assumption that RL in Mesh-Sim makes, from the radio model to the
statistics, with where it lives in the code, what it does to your results,
and whether you can change it.

## 1\. Before you start

- You did the tutorial through \ref mesh_sim_rl_evaluate "Evaluate and compare".
  The examples below point at its outputs in `$OUT`.
- Working directory: `scratch/mesh-sim/`. File paths are relative to it;
  line numbers are for mesh-sim commit `b54bfbe7` plus the working tree on
  2026-10-28.

## 2\. How to read this page

Each row is one assumption. **Where** is the file and line that implements it.
**Implies** is what it does to a result you report. **Configurable** says
whether a setting changes it (and which), or whether it takes a code change.
Every row was checked against the code; rows that came from a run say so.

Sections 3 to 11 follow the path of one decision. Section 12 lists places
where the code and its documentation disagree. Section 13 sums up what the
model cannot tell you.

## 3\. Physics and the link model

| Assumption | Where | Implies | Configurable |
|---|---|---|---|
| Nodes do not interfere with each other. SINR is signal over noise plus jammer power only. | `src/eval/link-evaluator.h:96`, `src/eval/link-evaluator.cc:202` | Moving nodes closer together never hurts another link. A policy can never learn to avoid self-interference. | No |
| Jammer interference is added only when `band = sub-6` and `jammers.json` defines jammers. | `src/eval/link-evaluator.cc:66`, `src/rl/rl-bridge.cc:76` | On mmWave scenarios such as the example, nothing but distance, buildings and fading changes SINR. | `[channel] band`, `jammers_file` |
| A link carries nothing below SINR −6.7 dB; a pair is "connected" at SINR ≥ −6.7 dB. | `src/eval/sinr-capacity.h:46`, `src/eval/link-table.h:98` | One faded tick can cut a flow: seed 14's model episode lost one tick at −7.2 dB. | No (a literal in two places) |
| Traffic is flow-level: a demand in Mbps per flow per tick, no packets, queues or retransmissions. | `src/routing/mesh-router.h:242` | Delivered rate is capped by the bottleneck link; latency does not grow with load. RL can only improve rates and connectivity, never queueing. | `[traffic]`, `[routing]` |
| When flows on a link ask for more than its capacity, every flow on it is scaled by capacity ÷ total demand. | `src/routing/mesh-router.h:242` | Fair proportional sharing; no priorities. | No |
| With a `buildings.json`, LOS is decided by building geometry only (`BuildingsChannelConditionModel`). Without one, the 3GPP model's random LOS probability decides. | `src/setup/topology-builder.cc:440` | In the example, LOS is a deterministic function of position: the shadow wedge on \ref mesh_sim_rl_example "The example scenario" is exact. | `buildings_file`, `[channel] condition_model` |
| Antenna gains are fixed numbers per node (ideal beamforming). | `src/eval/link-evaluator.cc:78` | Pointing and beam training are not modeled; orientation never matters. | `[channel]` and per-node gains |
| Channel randomness is driven by the episode seed. The same seed gives the same draws to every policy until positions differ. | `scripts/rl/env/episode.py:66` (`--seed`) | Observed: on seed 11, `model`, `hold` and `random_valid` all start at SINR 6.611 dB. Paired comparisons rely on this. | The seeds you pass |
| SINR fluctuates tick to tick even at a fixed position on some seeds. | ns-3 channel model | Observed: `hold` on seed 11 ranged 6.6–12.4 dB without moving. Single-tick metrics are noisy. | Channel settings |

## 4\. Control and movement

| Assumption | Where | Implies | Configurable |
|---|---|---|---|
| Movement is 2D. Height never changes; z velocity is set to 0. | `src/rl/rl-bridge.cc:729`; `move_3d` refused at `src/config/rl-control.cc:107` | A policy cannot climb over a building or out of a shadow. | No (a new contract) |
| Five moves per slot: west, east, south, north at full speed, or hold. No diagonals, no partial speed. | `src/rl/rl-bridge.cc:245`, `:709-716` | A diagonal path takes alternating moves, so it is √2 slower than a straight line. | No (a new contract) |
| Speed is constant: `min(step_size_m / tick_s, top speed)`; top speed is 20 m/s for drones, 15 for vehicles, 1.5 for pedestrians, 20 for any other type. | `src/rl/rl-bridge.cc:52-53`, `src/domain/node-spec.h:122-127` | `step_size_m` above the cap changes nothing. The example moves exactly 20 m per decision. | `step_size_m`, `node_type` |
| A controlled node's own mobility is replaced by constant velocity from its start position (first waypoint for a waypoint node). | `src/setup/topology-builder.h:21`, `src/config/rl-control.cc:82-96` | Mobility in `nodes.json` for a controlled node is ignored. | `controlled_nodes` |
| Walls clip: a move that would cross a bound stops exactly on it, checked every tick. No bounce, no penalty. | `src/rl/rl-bridge.cc:630-648` (`wall_policy: clip`) | Pushing into a wall is free. Observed: east from x = 240 ended at 250. | Bounds only |
| A direction is masked only when the node is within \f$10^{-6}\f$ m of that bound. Buildings are **not** masked unless `avoid_buildings` is on. | `src/rl/rl-bridge.cc:337-348` | By default nodes fly through buildings. In the example, west through the building is a legal path. | `avoid_buildings`, `mask_building_moves`, `building_clearance_m` |
| Nodes may overlap or collide unless `avoid_node_collisions` is on. | `src/rl/rl-bridge.cc:601-627` | `min_pair_distance_m` can be 0 without any penalty. | `avoid_node_collisions`, `unsafe_separation_m` |
| Hold sets velocity to 0 for the whole next window. It does not repeat the last move. | `src/rl/rl-bridge.cc:715` | | No |
| The simulator re-checks every action. A masked move, or a non-hold on a padded slot, becomes hold and is reported in `revalidated_slots`. Python never re-derives masks. | `src/rl/rl-bridge.cc:549-558` | An algorithm that ignores masks still runs, but its masked choices silently become holds (counted as health errors in evaluation). | No |
| A malformed line, a wrong-length action or a closed stdin makes every slot hold, with one warning per process. | `src/rl/rl-bridge.cc:497-546` | A broken agent looks like `hold`, not like a crash, until Python's own checks catch it. | No |
| Padded slots (beyond the controlled nodes, up to `max_controlled_nodes`) always hold and observe zeros. At most 64 slots. | `src/rl/rl-bridge.cc:331-334`, `:363-369`; `src/config/rl-control.cc:23` | One network shape can serve scenarios with fewer controlled nodes. | `max_controlled_nodes` |
| Jammers and the active traffic gateway cannot be controlled; every controlled node must start inside the bounds. | `src/config/rl-control.cc:191-194`, `:375`, `:316-321` | | No |
| Before `control_start_s`, every controlled node holds and its mask is hold-only. | `src/rl/rl-bridge.cc:331`, `:709` | | `control_start_s` |

## 5\. Timing

| Assumption | Where | Implies | Configurable |
|---|---|---|---|
| The loop runs ticks 0 to `num_ticks` inclusive, with `num_ticks` = `duration_s / tick_s` rounded when within \f$10^{-6}\f$ of a whole number. | `sim.cc:275`, `src/config/rl-control.cc:62-80` | 20 s at 0.1 s is 201 evaluated ticks. | `duration_s`, `tick_s` |
| A decision tick is every tick whose index is a multiple of \f$k\f$ = `decision_interval_s / tick_s`, which must be a whole number. The last tick always sends a step with `done`. | `src/rl/rl-bridge.cc:202-205`, `sim.cc:349-351`, `src/config/rl-control.cc:263` | 20 learning steps in the example. | `decision_interval_s` |
| An action takes effect from the next tick and lasts exactly one window; the policy cannot react inside a window. | `sim.cc:286`, `:367` | Reaction time is one decision interval. Shorter intervals give finer control and more, shorter learning steps. | `decision_interval_s` |
| Tick 0 is evaluated and sent with the reset; its reward is not a learning step and metrics skip decision 0. | `src/rl/rl-bridge.cc:574-594`, `scripts/rl/policy/metrics.py:39-40` | The start position is never scored. | No |
| The last window is shorter when the duration is not a whole number of intervals; it still counts as one full step. | `src/rl/rl-bridge.cc:234` | A short last window weighs as much as a full one in the return. | `duration_s`, `decision_interval_s` |
| Warmup: ticks with `time_s < warmup_s` are simulated and moves happen, but they earn no reward and are left out of every metric. The tick at exactly `warmup_s` is scored. | `src/rl/reward-window.h:15-25` | Moves made during warmup pay off later. See section 8 for the partly scored window this can create. | `[scenario] warmup_s` |
| A window with no scored ticks has reward 0. | `src/rl/reward-window.h:30` | Early warmup steps teach the policy nothing directly. | `warmup_s` |

Check the warmup rule on the placement run from
\ref mesh_sim_rl_evaluate "Evaluate and compare" (`warmup_s = 2.0`, 5-tick
windows):

```bash
.venv/bin/python - "$OUT/placement/zero-cost/eval/model/episode-0000/steps.jsonl" <<'PY'
import json, sys
for line in list(open(sys.argv[1]))[1:8]:
    r = json.loads(line)
    print(r["decision"], r["tick"], r["time_s"], r["ticks_in_step"], r["scored_ticks"])
PY
```

**Checkpoint:** decision, tick, time, ticks in the window, scored ticks:

```
0 0 0.0 1 0
1 5 0.5 5 0
2 10 1.0 5 0
3 15 1.5 5 0
4 20 2.0 5 1
5 25 2.5 5 5
6 30 3.0 5 5
```

## 6\. Observation

| Assumption | Where | Implies | Configurable |
|---|---|---|---|
| The policy's observation is rebuilt in Python from `facts` by the selected preset; the simulator's own `obs` vector is used only by `raw_links_v1`, whose layout is the same. | `scripts/rl/env/mesh_env.py:147`, `scripts/rl/env/observations/__init__.py` | Changing what the policy sees needs no rebuild. | `observation_preset` |
| The default preset is `raw_links_v1`: unscaled meters, dB and Mbps. | `scripts/rl/env/observations/__init__.py` | Inputs of very different magnitudes (capacity in thousands, flags of 1). Prefer a scaled preset. | `observation_preset` |
| `local_links_v1` scales position by the `[rl]` bounds to ±1, SINR as (SINR + 20)/60 and capacity as log10(1 + C)/4, all clipped. | `scripts/rl/env/observations/__init__.py`, `scripts/rl/env/normalization.py:9-35` | SINR above 40 dB or capacity above 9,999 Mbps saturates at 1. Changing the bounds changes the inputs, so the bounds are part of the model's identity. | `observation_parameters` |
| The observation is a snapshot at the decision tick, not an average over the window (window sums appear only in `service_v1` and `full_facts_v1`). | `src/rl/rl-bridge.cc:354-479` | A fade on the decision tick looks permanent to the policy. | Preset choice |
| Not observed by `local_links_v1`: buildings, the LOS flag, time or decision number, traffic, other nodes' positions and velocities. | `scripts/rl/env/observations/__init__.py` | The policy infers shadows from low SINR at its position. Without time it cannot plan for the episode's end. | Preset choice |
| The observation length depends only on `init` (slots and node count), never on the state; padded slots are zeros. | `scripts/rl/env/observations/__init__.py` | One trained network fits only scenarios with the same node count and slot count. | `max_controlled_nodes` |
| The contract may not change between resets. | `scripts/rl/env/mesh_env.py:290-301` | All training episodes share one layout. | No |
| A preset's schema (features, bounds, scales) is hashed; a saved model is refused when the live hash differs. | `scripts/rl/policy/compat.py:113-133` | Never edit a preset in place; add a `_vN`. | No |

## 7\. Reward

| Assumption | Where | Implies | Configurable |
|---|---|---|---|
| One reward for the whole network, shared by every slot. There is no per-node credit. | `src/rl/rl-bridge.cc:81-122` | With several controlled nodes, the policy must learn which node earned the reward. | No |
| The C++ step reward is the **mean** over the window's scored ticks, not the sum. | `src/rl/reward-window.h:30`, `init.reward_window = "mean"` | Returns are comparable across decision intervals; a shorter last window counts the same. | No |
| `all_links_los` is +1 only when every controlled node has every one of its links LOS; otherwise −1. | `src/rl/rl-bridge.cc:85-112` | With several peers, one blocked link anywhere costs the full −1. | `reward_type` |
| `throughput` (the C++ default) is the sum of delivered Mbps over flows. | `src/rl/rl-bridge.cc:115-121` | Its scale grows with demand and node count; hard to compare across scenarios. | `reward_type` |
| Naming `reward_components` replaces the C++ reward with a weighted sum of the valid components; the C++ reward is still computed and available as `legacy`. | `scripts/rl/env/mesh_env.py:150-167`, `scripts/rl/env/rewards/__init__.py` | A component invalid in a window (for example `delivery_ratio` with no demand) adds 0, not a penalty. | `reward_components`, `reward_weights` |
| Every component is invalid in a window with no scored ticks. | `scripts/rl/env/rewards/__init__.py` | Warmup windows contribute 0. | No |
| Travel-based components are invalid in a partly scored window. | `scripts/rl/env/rewards/__init__.py` | No travel cost for the warmup boundary window. | No |
| No reward or penalty for movement, energy or time unless you add one. | `src/rl/rl-bridge.cc:81-122` | Observed: the trained model traveled 390 m for no gain (\ref mesh_sim_rl_how_it_works "How a decision works", section 6). | `travel_fraction` and similar components |

## 8\. Episodes and scoring windows

| Assumption | Where | Implies | Configurable |
|---|---|---|---|
| One simulator process per episode; `reset()` stops the old one and starts a new one. | `scripts/rl/env/mesh_env.py:119-120`, `scripts/rl/env/episode.py:58-95` | Each episode pays the simulator's start-up cost; an episode cannot be resumed mid-way. | No |
| Episodes have a fixed length and end only when the simulator says `done`; `truncated` is always `False`. | `scripts/rl/env/mesh_env.py:173-179` | Bootstrapping at the end is treated as terminal. | `duration_s` |
| Training resets once before wrapping the env, which leaves an `interrupted` episode with zero steps. | `scripts/rl/policy/training.py:47` | Filter by `status` before averaging episode files. | No |
| Evaluation recomputes each episode's return and refuses one that differs from `rl_episode.json`. | `scripts/rl/policy/evaluate.py:203-208` | | No |
| Evaluation metrics come only from `steps.jsonl`, over scored ticks, skipping decision 0. | `scripts/rl/policy/metrics.py:8-23`, `:38-52` | They differ from `summary.json`, which also counts tick 0. | No |
| `travel_m_total`, `displacement_m_final` and the per-node movement metrics are **null for the whole episode** if any window was only partly scored, or a decision is missing. | `scripts/rl/policy/metrics.py:71-81`, `:94-98` | See below. | `warmup_s` |

**The partly scored window.** When `warmup_s` is a multiple of
`decision_interval_s`, the first scored tick (the one at exactly `warmup_s`)
is the **last** tick of a window, so that window has 1 of \f$k\f$ ticks scored
and every movement metric becomes null. That is what happened on
`channel-scored-example` (`warmup_s = 2.0`, 0.5 s windows): `travel_m_total`
is null for every policy and seed, every travel pair is excluded, and
`compare` exits 1 with `"status": "incomplete"`. Movement metrics are complete
when the first scored tick **starts** a window, that is when

\f[ m k \cdot \mathtt{tick\_s} < \mathtt{warmup\_s} \le (m k + 1) \cdot \mathtt{tick\_s} \quad \text{for some whole } m \f]

for example `warmup_s = 2.1` there, or no warmup. This rule is derived from
the code above; a run with `warmup_s = 2.1` was not made for this page.

## 9\. Seeds

| Assumption | Where | Implies | Configurable |
|---|---|---|---|
| Every training episode uses the same seed. | `scripts/rl/policy/training.py:35`, `scripts/rl/env/mesh_env.py:106-113` | Training sees one channel realization; generalization to other seeds is only tested by evaluation. | `--seed` |
| The training seed seeds both the network and PPO's sampling (`MaskablePPO(seed=...)`) and the training scenario (`--seed` to the simulator). | `scripts/rl/train.py:129-130`, `scripts/rl/agents/mask_ppo.py:25` | Training-run variability mixes network luck and scenario luck; they cannot be separated. | No |
| The model-selection seed defaults to training seed + 1 and must differ from it. | `scripts/rl/train.py:121-127` | | `--eval-seed`, `--eval-seeds` |
| Evaluation refuses held-out seeds that equal the training, model-selection or placement-planning seeds, unless `--allow-seed-overlap`, which marks the result not held out. | `scripts/rl/evaluate.py:216-230`, `scripts/rl/policy/bundle.py:141-173` | Observed: seed 1 refused. | `--allow-seed-overlap` |
| `best_model.zip` is chosen on `--eval-episodes` episodes (1 by default) and only replaced by a strictly better score. | `scripts/rl/agents/callbacks.py:126-137` | With one episode, model selection is noisy; ties keep the earliest model (here the one at 512 decisions). | `--eval-episodes`, `--eval-seeds` |
| `random_valid` reseeds from each episode's seed; `--stochastic-model` calls SB3's `set_random_seed(seed)` per episode. | `scripts/rl/policy/evaluate.py:56-57`, `:78-80` | Baselines and stochastic evaluation are repeatable. | No |

## 10\. PPO and masking

| Assumption | Where | Implies | Configurable |
|---|---|---|---|
| The algorithm is MaskablePPO from `sb3_contrib`; `train` has no other working algorithm (`qr-dqn` exits 1). | `scripts/rl/train.py:33`, `:68-76` | Another algorithm needs code (\ref mesh_sim_rl_add_algorithm "Add an RL algorithm"). | No |
| Settings passed: `seed`, `n_steps`, `gamma`, `ent_coef`, `learning_rate`, `batch_size`, `gae_lambda`, `clip_range`, `n_epochs`, `target_kl`, `net_arch` (both actor and critic), `verbose`, `tensorboard_log`. Everything else is the SB3 default. | `scripts/rl/agents/mask_ppo.py:22-38`, defaults at `scripts/rl/agents/config.py:55-70` | See \ref mesh_sim_rl_train "Train a policy", section 5. | The `m-ppo` flags |
| Masked moves get logit \f$-10^{8}\f$, so probability 0 in sampling, in the probability ratio and in the entropy. | `sb3_contrib/common/maskable/distributions.py` (installed package) | The policy never wastes probability on illegal moves. | No |
| The action space is `MultiDiscrete([5] * slots)`: an independent 5-way choice per slot from one shared network. | `scripts/rl/env/mesh_env.py:261` | Slots coordinate only through the shared observation. | No |
| One environment, no vectorization, no observation or reward normalization wrapper. | `scripts/rl/policy/training.py:43` | Throughput is one simulator at a time; scaling relies on the preset. | No |
| Model selection plays masked, deterministic episodes. | `scripts/rl/agents/callbacks.py:126-137` | Its curve can sit far above the training curve, which samples. | No |
| Saved models are reloaded on the CPU. | `scripts/rl/agents/mask_ppo.py:70-73` | | No |

## 11\. Evaluation and statistics

| Assumption | Where | Implies | Configurable |
|---|---|---|---|
| Every comparison is `model` minus one baseline, paired by seed. Baselines are never compared with each other. | `scripts/rl/policy/compare.py:63-80` | To compare two baselines, compare each with the same model. | No |
| The interval is a paired t interval, \f$\bar d \pm t_{0.975,n-1}\,s/\sqrt n\f$, with t from a table at the largest tabulated df not above \f$n-1\f$. | `scripts/rl/policy/compare.py:39-49`, `scripts/stats.py:19-25` | It assumes roughly normal differences; with 3–5 seeds it is wide and approximate. | Number of seeds |
| A pair is used only when both episodes completed and the metric is not null; otherwise it is listed in `excluded` and the comparison is `incomplete`. | `scripts/rl/policy/compare.py:52-82` | One null metric makes `compare` exit 1 (section 8). | No |
| All seeds giving the same difference produce a zero-width interval flagged `zero_variance`. | `scripts/rl/policy/compare.py:92` | A deterministic pair, not certainty. | No |
| The primary metric printed is `delivery_ratio`. | `scripts/rl/policy/compare.py:23` | On scenarios where delivery is saturated it cannot separate policies; read the other metrics in `comparison.json`. Observed on the example: −0.001 [−0.0038, +0.0018]. | No |
| `return` is marked not comparable across reward definitions. | `scripts/rl/policy/metrics.py:220` | Compare different rewards on the domain metrics only. | No |
| Seed-to-seed intervals hold the trained model fixed; variability across training runs needs a `--label` group of several training seeds. | `scripts/rl/policy/compare.py:25` (`ACROSS_RUNS_KIND`) | One trained model says nothing about training luck. | `--label`, matrices |
| A passed compatibility check means the inputs match, not that the policy transfers. | `eval_manifest.json` compatibility `note` | | No |

## 12\. Code and documentation that disagree

These were found while writing this guide. The code is what runs; the pages
named in the left column were not changed.

| Document | What it says | What the code does |
|---|---|---|
| `src/config/run-ini-reference.md:128-136` | Lists `controlled_node_id` ("blank selects the last mesh node"), `action_type` and `arrival_threshold_m` as live `[rl]` keys, and presents `controlled_nodes` as one of two alternative selectors. | Those keys are rejected (`src/config/config-loader.cc:360-366`, `src/config/rl-control.cc:340-344`), and `controlled_nodes` is required when RL is enabled. |
| `scripts/rl/README.md:401`, `scripts/rl/CLAUDE.md:56-62`, `scripts/rl/env/README.md:39` and `:71-74`, `scripts/rl/agents/CLAUDE.md:21`, `scripts/rl/tests/CLAUDE.md:19` | Describe a legacy single-node mode (`Discrete(7)`, no `init` message, a Python-built mask). | `MeshRlEnv.reset` refuses any first message that is not `init` ("legacy control is unsupported", `scripts/rl/env/mesh_env.py:126-127`); only `MultiDiscrete([5]*M)` exists. |
| `scripts/rl/tests/README.md:59`, `:126`, `:133`, `:139-141`, `:153` | Lists legacy-mode tests such as `test_rl_legacy_selection` and `test_reset_mode_drift_is_rejected`. | No test with those names exists under `scripts/rl/tests/` or `tests/`. |
| `scripts/rl/agents/README.md`, "Hyperparameters that reach MaskablePPO" | Only `seed`, `n_steps`, `gamma`, `ent_coef` (plus logging) reach `MaskablePPO`; "All other MaskablePPO settings use SB3 defaults". | `scripts/rl/agents/mask_ppo.py:22-38` also passes `learning_rate`, `batch_size`, `gae_lambda`, `clip_range`, `n_epochs`, `target_kl` and `net_arch`. |
| `scripts/rl/agents/README.md`, module table | `mask_ppo.py` holds `MaskablePPOConfig`; `callbacks.py` holds `list_checkpoints`; tunable settings are in `ops/tune.py`'s `_SEARCHABLE`. | `MaskablePPOConfig` is in `agents/config.py` (re-exported); `list_checkpoints` is in `policy/training_artifacts.py:21`; the search list is `agents.config.PPO_SEARCH_PARAMETERS` and `_SEARCHABLE` does not exist. |
| `scripts/rl/agents/q_learning.py:44-49` | `TabularQLearning` reads the observation as `[x, y, sinr, cap, ...]` and returns one scalar action. | With `raw_links_v1` the first value is the active flag, and the env needs one action per slot. The class cannot drive the current env unchanged. |
| `inputs/baselines/channel-scored-example` with `scripts/rl/policy/metrics.py:80-81` | The placement example is the documented way to put planners beside a model. | Its `warmup_s = 2.0` ends on a decision boundary, so `MovementTotals` nulls `travel_m_total` for every episode and `compare` reports `incomplete` and exits 1 (section 8). This is the metric's documented rule (`metric_source.movement.incomplete_or_partial_warmup = "null"`), but it means the shipped example never yields a complete comparison. |
| `scripts/rl/policy/compare.py:23` with `inputs/baselines/building-bypass-smoke` | `delivery_ratio` is the primary metric `compare` prints. | On the tutorial scenario every policy delivers ≥ 99.5%, so the printed line cannot separate a learned policy from `hold`. |

## 13\. Known limitations

- **No interference, no packets.** RL here optimizes positions against a
  noise-limited, flow-level model. It cannot learn spacing for interference,
  scheduling or queueing.
- **One scenario per network.** The observation length, the bounds scaling and
  the contract tie a trained model to one node count, slot count and bounds.
- **One seed per training run.** Generalization across channel realizations
  is measured only at evaluation.
- **Coarse control.** Four directions at one speed, decided once per window.
- **No cost of motion by default.** Learned paths can be long and aimless when
  the reward is flat, as in the tutorial.
- **Small-sample statistics.** Paired t intervals over a handful of seeds;
  across-training-run intervals need a matrix.
- **Shared reward.** With several controlled nodes, credit assignment is left
  to the network.

## 14\. Going further

- \ref research_link_model "Link model assumptions" and
  \ref research_flow_abstraction "Flow abstraction": the reasons behind
  section 3.
- \ref src_rl "src/rl": the wire contract these rows come from.
- \ref Contributing "Contributing": what to update together when you change
  any of these.

Previous: \ref mesh_sim_rl_evaluate "Evaluate and compare" · Next: \ref mesh_sim_rl_experiments "Experiments and operations"
