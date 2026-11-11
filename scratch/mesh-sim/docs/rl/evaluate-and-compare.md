# Evaluate and compare {#mesh_sim_rl_evaluate}

[TOC]

Run the trained policy and the baselines on held-out seeds, turn the results
into paired statistics, and read them without fooling yourself. Then put the
model next to the placement planners.

## 1\. Before you start

- `$OUT/train` exists from \ref mesh_sim_rl_train "Train a policy", and
  `SIM_BIN` and `OUT` are still set.
- Working directory: `scratch/mesh-sim/`.

## 2\. The policies

| Policy | What it does each decision |
|---|---|
| `model` | The trained policy's deterministic choice (the most likely move) under the live mask. `--stochastic-model` samples instead, seeded per episode. |
| `hold` | Every slot holds. The "never move" baseline. |
| `random_valid` | A uniformly random allowed move per slot. Its generator restarts from each episode's seed, so it is repeatable. |
| `geometric`, `optimization` | Placement baselines: plan better start positions once, before the run, then hold (section 9). |

Each policy gets its own environment and plays every seed in order. Episodes
of different policies on the **same seed** see the same scenario randomness:
on seed 11, `model`, `hold` and `random_valid` all start at SINR 6.611 dB, and
the channel draws agree until their positions differ. That is what makes a
**paired** comparison fair: the difference on a seed measures the policy, not
luck.

## 3\. Evaluate

```bash
.venv/bin/python -m scripts.rl.evaluate \
  --sim-binary "$SIM_BIN" --run-dir "$OUT/train" \
  --output-dir "$OUT/eval" \
  --seeds 11-15 --policies model,hold,random_valid
```

Before the first model action, `evaluate` checks the saved run, in this order:

1. the manifest's status is `completed`, and the model file's digest matches
   the manifest (`--model final` by default);
2. the seeds do not overlap training or model selection (section 4);
3. the saved contract against the live `init` (slots, nodes, dimensions,
   speeds, timing);
4. the saved observation schema against the live one;
5. the saved reward definition against the live one;
6. the scenario fingerprints (`run.ini`, `nodes.json`, `buildings.json`,
   `jammers.json`) against the live files.

Any mismatch stops it. Only the last can be relaxed, with
`--allow-different-scenario`.

**Checkpoint:** after about 14 seconds,

```
model: mean_return=15.6 episodes=5/5 revalidated=0 mask_violations=0
hold: mean_return=-20.0 episodes=5/5 revalidated=0 mask_violations=0
random_valid: mean_return=-10.28 episodes=5/5 revalidated=0 mask_violations=0
```

and `echo $?` prints `0`. SB3 also prints two lines about wrapping the env;
they are harmless.

- **`revalidated` and `mask_violations`** count actions the simulator had to
  turn into hold, and actions the policy chose against the mask. A masked
  policy should never trigger them; any non-zero value makes the exit code 2.
- **`model` and `hold` score the same on every seed.** Their moves do not
  depend on anything that differs between seeds here. `random_valid` does:
  −4.6, −20.0, −5.4, −1.4 and −20.0 on seeds 11–15.

| Option | What it does |
|---|---|
| `--run-dir` | The training run. Supplies the scenario, band and selection, so the model sees exactly the inputs it was trained on. |
| `--model` | `final` (default), `best`, or `checkpoints/<file>.zip`. |
| `--seeds` | Seeds and ranges: `301-303,310`. |
| `--policies` | Default `model,hold,random_valid`. |
| `--label` | Names the experiment row this evaluation belongs to. Comparison groups by it (section 8). |
| `--run-config` | Evaluate on a different `run.ini`. Needs `--allow-different-scenario` when the fingerprints differ (section 9). |
| `--allow-different-scenario` | Relaxes only the scenario-fingerprint check. The manifest records `scenario: overridden`. |
| `--allow-seed-overlap` | Lets a training or model-selection seed through, for diagnostics. The result is marked not held out. |
| `--stochastic-model` | Sample from the policy instead of taking its most likely move. |
| `--baseline-cache-dir` | Reuses baseline episodes across runs with the same binary, scenario and seeds. |
| `--decision-records`, `--decision-record-seeds` | Write decision records for all or some seeds. |

| Exit | Meaning |
|---|---|
| 0 | Every episode completed, with clean health counters. |
| 1 | An error, or an episode did not complete. |
| 2 | Every episode completed, but a health counter is non-zero. |

## 4\. Held-out seeds are enforced

Ask for the training seed and `evaluate` stops before it starts a simulator:

```bash
.venv/bin/python -m scripts.rl.evaluate \
  --sim-binary "$SIM_BIN" --run-dir "$OUT/train" \
  --output-dir "$OUT/eval-overlap" --seeds 1,11 --policies model,hold
```

**Checkpoint:** exit code 1 and

```
held-out seed 1 is the training seed; choose other seeds or pass --allow-seed-overlap
```

The manifest's `seed_roles` block records the roles for the real run:
`training_seed` 1, `model_selection_seed` 2, `held_out_seeds` 11–15,
`overlap` empty, `"held_out": true`.

## 5\. What evaluation wrote

<!-- Output-folder figure. Listing from outputs/rl-tutorial/eval (2026-10-28), 2.1 MB. -->
<div class="ms-outtree">
<div class="ms-ot-head"><span>File</span><span>What it holds</span><span>Read by</span></div>
<div class="ms-ot-row ms-ot-dir"><code>eval/</code><span>One evaluation, 2.1 MB here.</span><span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>eval_manifest.json</code><span>Status, seed roles, the bundle and its digest, compatibility results, and per policy and seed: status, return, health counters and every metric. <b>Read this first.</b></span><span><span class="ms-ot-tag ms-ot-you">you</span><span class="ms-ot-tag ms-ot-plot">compare</span></span></div>
<div class="ms-ot-row ms-ot-l1 ms-ot-dir"><code>&lt;policy&gt;/</code><span>One folder per policy: <code>model/</code>, <code>hold/</code>, <code>random_valid/</code>.</span><span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>reward_matrix.json</code>, <code>.csv</code><span>Reward per decision per seed, with the mean curve.</span><span><span class="ms-ot-tag ms-ot-you">you</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>episode-NNNN/</code><span>One per seed, in seed order: <code>rl_episode.json</code>, <code>steps.jsonl</code> (always), <code>run.log</code>, <code>inputs/</code>, <code>seed-&lt;N&gt;/</code>.</span><span><span class="ms-ot-tag ms-ot-you">you</span><span class="ms-ot-tag ms-ot-viz">visualizer</span></span></div>
</div>

Metrics are computed from `steps.jsonl`, never from `summary.json`, so they
use exactly the RL scoring window: decision 0 (tick 0) and warmup ticks are
left out. Each episode's return is also checked against its
`rl_episode.json` before it is recorded. The manifest is rewritten after every
episode, so a crash leaves `partial` or `failed` with the finished seeds
intact.

## 6\. The metrics

\image html rl-eval-metrics.svg "Per-policy results on held-out seeds 11-15 of building-bypass-smoke (outputs/rl-tutorial/eval). Hollow markers are seeds; the filled marker and bar are the mean and its 95% t interval across the five seeds for the one trained model."

| Metric | Definition (over scored ticks of decisions 1 to the end) | `model` | `hold` | `random_valid` (mean) |
|---|---|---|---|---|
| `return` | Sum of step rewards | 15.6 | −20.0 | −10.28 |
| `delivery_ratio` | Delivered ÷ demanded Mbps-ticks | 0.999 | 1.0 | 1.0 |
| `connectivity` | Connected pair-ticks ÷ all pair-ticks | 0.999 | 1.0 | 1.0 |
| `los_fraction` | LOS pair-ticks ÷ all pair-ticks | 0.89 | 0.0 | 0.243 |
| `first_all_los_decision` | First decision whose window was all LOS | 4 | none | 11–14 on 3 seeds, none on 2 |
| `travel_m_total` | Controlled nodes' xy distance between consecutive decisions, summed (m) | 390 | 0 | 294 |
| `displacement_m_final` | Distance from the start at the end (m) | 111.8 | 0 | 82.4 |
| `min_pair_distance_m` | Closest any two nodes came (m) | 200.0 | 200.0 | 147.5 |

`model` scored 0.995 for `delivery_ratio` and `connectivity` on seed 14 and
1.0 on the other four. On that seed its link faded to −7.2 dB for one tick
(t = 2.2 s, still in the shadow), below the −6.7 dB a link needs to carry
anything. `hold`, parked elsewhere in the shadow, never dipped that low.

## 7\. Compare

```bash
.venv/bin/python -m scripts.rl.compare \
  --eval-dirs "$OUT/eval" --output-dir "$OUT/compare"
```

**Checkpoint:** exit code 0 and

```
(unlabeled) train-seed-1 vs hold  delivery_ratio  -0.0010 [-0.0038, +0.0018]  paired t, 5/5 evaluation seeds, fixed model
(unlabeled) train-seed-1 vs random_valid  delivery_ratio  -0.0010 [-0.0038, +0.0018]  paired t, 5/5 evaluation seeds, fixed model
```

`$OUT/compare/` now holds `comparison.json` and `episodes.csv` (one row per
policy and seed). Every difference is **model minus baseline**, paired by
seed. The printed line shows only the primary metric, `delivery_ratio`;
`comparison.json` has every metric:

\image html rl-paired.svg "The paired comparison from outputs/rl-tutorial/compare/comparison.json. Left: each held-out seed's baseline value joined to the model's value on the same seed. Right: the mean difference and its paired 95% t interval. hold's five pairs are identical, so its interval has zero width."

<!-- Source: outputs/rl-tutorial/compare/comparison.json, evaluations[0].comparisons. -->

| Metric | Model − hold | Model − random_valid, 95% interval |
|---|---|---|
| `return` | +35.6 (zero variance) | +25.88 [+14.71, +37.05] |
| `los_fraction` | +0.89 (zero variance) | +0.647 [+0.368, +0.926] |
| `delivery_ratio` | −0.001 [−0.0038, +0.0018] | −0.001 [−0.0038, +0.0018] |
| `travel_m_total` | +390 m (zero variance) | +96 m [+24.9, +167.1] |

### How the interval is computed

For each metric and baseline, with \f$n\f$ seeds where both episodes completed
and the metric is not null:

\f[ d_i = m_i - b_i, \qquad \bar d = \frac{1}{n}\sum_i d_i, \qquad s = \sqrt{\frac{1}{n-1}\sum_i (d_i - \bar d)^2}, \qquad \bar d \pm t_{0.975,\,n-1}\,\frac{s}{\sqrt n} \f]

**Worked, `return` against `random_valid`.** The five differences are
15.6 − (−4.6) = 20.2, 35.6, 21.0, 17.0 and 35.6. Their mean is 25.88 and
\f$s\f$ = 9.00. With \f$n = 5\f$, \f$t_{0.975,4} = 2.776\f$:

\f[ 25.88 \pm 2.776 \times \frac{9.00}{\sqrt 5} = 25.88 \pm 11.17 = [14.71,\ 37.05] \f]

which is the `interval` in `comparison.json`. The t value comes from
`scripts/stats.py`, which uses the largest tabulated degrees of freedom not
above \f$n-1\f$ so intervals are never too narrow.

### Read it like this

- **The primary metric says "no difference", and that is correct.**
  `delivery_ratio` is the share of demanded traffic delivered. On this
  scenario the 10 Mbps flow gets through even NLOS: the shadowed link still
  carries about 1,000 Mbps. The one lost tick on seed 14 is a fade, not
  something the model chose, and its interval straddles 0. The model learned
  what its reward asked for, LOS (`los_fraction` +0.89), and LOS did not
  change delivery.
- **`return` is only comparable inside one evaluation.** It depends on the
  reward definition. `comparison.json` marks it
  `comparable_across_reward_definitions: false`. Use the domain metrics
  (`delivery_ratio`, `los_fraction`, `connectivity`, `travel_m_total`) to
  compare across reward definitions.
- **A zero-width interval is not certainty.** Against `hold`, all five seeds
  gave the same difference, so the interval is `[x, x]` and the entry carries
  `zero_variance: true`. The scenario is deterministic for these two policies,
  not the result certain.
- **Moving costs distance.** The model traveled 390 m, 96 m more than random
  moves, for no reward after decision 3. Whether that matters depends on the
  mission; the comparison only reports it. A reward with a travel penalty
  would change it (\ref mesh_sim_rl_configure "Configure an RL scenario", section 5).
- **Five seeds and one model.** This interval says how much the result depends
  on the scenario seed, for this one trained network. It says nothing about
  how a second training run would do.

### The two kinds of interval

| Interval | Varies over | Printed as |
|---|---|---|
| Across evaluation seeds | Held-out seeds, one fixed model | `paired t, 5/5 evaluation seeds, fixed model` |
| Across training runs | Independently trained models sharing a `--label` | `t across 2/2 training runs, 3 common held-out seeds` |

The first says how much the result depends on the scenario seed. The second
says how much it depends on training luck. You need several training seeds,
and therefore an experiment matrix, for the second
(\ref mesh_sim_rl_experiments "Experiments and operations"). The training seed
sets both the network initialization and the training scenario, so the two
sources cannot be separated.

| Exit | Meaning |
|---|---|
| 0 | Complete and clean. |
| 1 | Incomplete (a metric is missing for some seed), or inputs refused. |
| 2 | An evaluation was not held out, or a policy had non-zero health counters. |

`compare` reads only `eval_manifest.json` at the current version, and refuses
an output folder that holds a training or evaluation manifest.

## 8\. Several trained models

`--label` groups evaluations of independently trained models of the same
setup, so `compare` adds a group line with an interval across training runs.
Runs whose settings or scenario fingerprints differ are refused rather than
mixed. An experiment matrix sets labels for you; see
\ref mesh_sim_rl_experiments "Experiments and operations".

## 9\. Placement baselines beside a trained model

`geometric` and `optimization` plan starting positions for the controlled nodes
once, then hold. They show whether a policy that moves during the run beats a
careful plan made before the run. How they plan:
\ref mesh_sim_placement_start "Placement baselines".

They are not in the default policy list, and they need a scenario with a
`[baseline]` section. The committed example is
`inputs/baselines/channel-scored-example/`: two drones and a ground peer,
10 s episodes with 2 s warmup and 0.5 s decisions. `run-zero-cost.ini`
differs from `run.ini` only in setting the four movement-cost keys to zero.

```bash
EX=inputs/baselines/channel-scored-example
P=$OUT/placement
.venv/bin/python -m scripts.rl.train --sim-binary "$SIM_BIN" \
  --run-config "$EX/run.ini" --output-dir "$P/train" --verbose 0 \
  m-ppo --seed 101 --total-timesteps 256 --n-steps 64 --eval-every-steps 128 --eval-seed 301
.venv/bin/python -m scripts.rl.evaluate --run-dir "$P/train" --model best \
  --sim-binary "$SIM_BIN" --run-config "$EX/run-zero-cost.ini" --allow-different-scenario \
  --output-dir "$P/zero-cost/eval" --seeds 801,802,803 \
  --policies model,hold,geometric,optimization
.venv/bin/python -m scripts.rl.compare \
  --eval-dirs "$P/zero-cost/eval" --output-dir "$P/zero-cost/compare"
```

**Checkpoint:** the three commands took 37 seconds together. `evaluate`
exits 0 and prints

```
model: mean_return=17.0 episodes=3/3 revalidated=0 mask_violations=0
hold: mean_return=17.0 episodes=3/3 revalidated=0 mask_violations=0
geometric: mean_return=17.0 episodes=3/3 revalidated=0 mask_violations=0
optimization: mean_return=17.0 episodes=3/3 revalidated=0 mask_violations=0
```

and its manifest's compatibility block reads `"scenario": "overridden"` with
a warning naming the `run_ini_sha256` that differs. `compare` prints three
`delivery_ratio  +0.0000 [+0.0000, +0.0000]` lines and **exits 1**, with
`"status": "incomplete"` in `comparison.json`.

What the placement policies add:

- **Seeds with four roles.** The plan comes from `[baseline] planning_seed`
  (701), never from the evaluation seeds. The optimizer has its own RNG seed
  (`[baseline] seed`, 201). Training (101), model selection (301) and held-out
  evaluation (801–803) stay separate. `seed_roles` records
  `"planning_seeds": [701]`, and evaluation refuses a planning seed that
  overlaps the held-out seeds.
- **Movement settings.** `[baseline] movable_nodes` must name exactly
  `[rl] controlled_nodes`, or preparation fails before any episode.
- **A `baseline/` folder per placement policy.** It holds
  `baseline_manifest.json`, `planner.log`, `source-inputs/` and
  `effective-inputs/` with `baseline-plan.json`. Each plan has a fingerprint;
  changing the costs changes it, so penalized and zero-cost runs never group
  together.
- **Two separate movement measures.** `initial_displacement_m_total` is the
  move to the planned start, before reset: 169.7 m for both planners here and
  0 for `model` and `hold`. `travel_m_total` is movement during the scored
  window. They measure different things and are never added together.

On this example every policy delivers everything and keeps LOS throughout, so
no policy beats another: every paired difference is 0.

**Why `compare` exits 1 here.** With `warmup_s = 2.0` and 0.5 s decisions,
decision 4 ends at t = 2.0 s with 1 scored tick of 5 (the timing figure on
\ref mesh_sim_rl_how_it_works "How a decision works" shows it). The movement
metric is defined as null for a partly scored window, so `travel_m_total` is
null for every policy and every seed, and every `travel_m_total` pair is
excluded as `metric_null`. The other metrics are complete. To get travel on
this scenario, choose a `warmup_s` whose first scored tick starts a window,
for example 2.1 s here, or read `initial_displacement_m_total` and the
trajectories directly. \ref mesh_sim_rl_assumptions "Every assumption",
section 8, has the rule.

Do not tune costs or settings on the held-out results and then report those
seeds as untouched.

## 10\. Going further

- \ref scripts_rl_policy "scripts/rl/policy": the bundle checks, compatibility
  order and statistics in full.
- \ref scripts_rl_comparing_policies "Comparing policies": every `compare`
  flag.
- \ref mesh_sim_rl_assumptions "Every assumption": what these numbers do and
  do not measure.

<!-- Provenance: run 2026-10-28, binary build/scratch/mesh-sim/ns3.42-sim-debug
     (sha256 d7a2f4d1...6c9fe2), mesh-sim commit b54bfbe7 plus the working tree.
     Outputs in outputs/rl-tutorial/{eval,eval-overlap,compare,placement}; logs
     in outputs/rl-tutorial/logs/. The placement comparison's exit 1 was
     observed, not inferred. Figures: docs/diagrams/rl-tutorial.py. -->

Previous: \ref mesh_sim_rl_read_training "Read a training run" · Next: \ref mesh_sim_rl_assumptions "Every assumption"
