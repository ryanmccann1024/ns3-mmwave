# Compare zero-cost and penalized placement

Run these commands from `scratch/mesh-sim/` using an already built simulator
binary and the environment described in the main README. These are example
commands, not measured results. The short training budget is for checking the
workflow; it cannot establish learning performance.

The committed [example](../../inputs/baselines/channel-scored-example/run.ini)
contains two movable aerial nodes and one fixed peer in a 400 × 400 m rectangle.
It uses fixed mobility, the scenario's NYU channel, 2D control, ten-second episodes
and two seconds of warmup. Decisions continue during warmup; scoring starts at
two seconds. No active traffic gateway is present. If adding one, exclude it
from both `controlled_nodes` and `movable_nodes`.

| Role | Example seed(s) |
| --- | --- |
| Training | 101 |
| During-training model selection | 301 |
| Optimizer search RNG | 201 |
| Channel realization used to select the placement | 701 |
| Held-out episode evaluation | 801, 802, 803 |

`planning_seed` is required for placement and supports integers 1–2147483647,
matching the query worker's signed seed option. `--planning-seed` can override
it. Reordering evaluation seeds preserves the plan. Overlap is refused unless
`--allow-seed-overlap` is supplied for an explicitly labeled diagnostic; that
run is marked non-held-out and cannot contribute to held-out groups.

## Train and verify the model

Use a fresh output root for each attempt. Set `SIM_BIN` to your built binary's
absolute path; it must match the binary used for evaluation.

```bash
EX=inputs/baselines/channel-scored-example
OUT=outputs/channel-scored-example
.venv/bin/python -m scripts.rl.train \
  --sim-binary "$SIM_BIN" --run-config "$EX/run.ini" \
  --output-dir "$OUT/train" m-ppo --seed 101 --total-timesteps 4096 \
  --n-steps 64 --eval-every-steps 1024 --eval-seed 301
.venv/bin/python -m scripts.rl.inspect_model --run-dir "$OUT/train"
```

Training uses the source layout; `[baseline]` is prepared only by the baseline
runner or placement evaluation policies. Check that `train_manifest.json` is
completed and records training 101 and selection 301. Model digest and structural,
observation and reward compatibility remain required on evaluation.

## Evaluate both cost choices

[run-zero-cost.ini](../../inputs/baselines/channel-scored-example/run-zero-cost.ini)
differs from `run.ini` only in the four fixed/per-meter relocation costs, all
set to zero. The penalized example uses fixed 150000 m²-equivalent per moved node,
plus 500 per meter for aerial nodes and 100 per meter for ground nodes. Both keep
100 m movement caps, identical seeds, bounds, roster, channel and scored window.
Platforms default from `node_type`: drones are aerial; vehicles and pedestrians
are ground. A v2 mapping can override individual classifications. The penalty changes the planner objective, not the saved
RL reward.

```bash
.venv/bin/python -m scripts.rl.evaluate \
  --run-dir "$OUT/train" --model best --sim-binary "$SIM_BIN" \
  --run-config "$EX/run.ini" --output-dir "$OUT/penalized/eval" \
  --seeds 801,802,803 --policies model,hold,geometric,optimization
.venv/bin/python -m scripts.rl.evaluate \
  --run-dir "$OUT/train" --model best --sim-binary "$SIM_BIN" \
  --run-config "$EX/run-zero-cost.ini" --allow-different-scenario \
  --output-dir "$OUT/zero-cost/eval" \
  --seeds 801,802,803 --policies model,hold,geometric,optimization
```

The zero-cost source INI has a different hash, so the second command records a
scenario override. It still enforces structural, observation and reward
compatibility. Each placement method prepares once, holds its layout for all
evaluation seeds, and records its own fingerprint. The optimizer uses RNG 201;
both methods query channel seed 701. Do not tune costs on the held-out outcomes
and then describe those same seeds as untouched evaluation data.

To run placement without RL evaluation, use the same INI and dedicated seed:

```bash
.venv/bin/python -m scripts.baselines.runner \
  --sim-binary "$SIM_BIN" --run-config "$EX/run.ini" \
  --output-dir "$OUT/standalone" --seeds 801,802,803
```

## Compare and inspect the evidence

```bash
.venv/bin/python -m scripts.rl.compare \
  --eval-dirs "$OUT/penalized/eval" --output-dir "$OUT/penalized/comparison"
.venv/bin/python -m scripts.rl.compare \
  --eval-dirs "$OUT/zero-cost/eval" --output-dir "$OUT/zero-cost/comparison"
```

Keep the two cost conditions separate when grouping repeated training runs:
changing costs changes the placement fingerprint. Within each condition,
comparison pairs model and baseline on the same seed. The primary outcome is
measured delivery; tiny sample sizes and a short training run provide limited
evidence.

Inspect these files before interpreting the result:

| Artifact | What to check |
| --- | --- |
| `eval_manifest.json` | Completed episodes, compatibility overrides, seed roles/held-out status and scoring metadata. |
| Each placement's `baseline/baseline_manifest.json` | Resolved objective/settings, planning seed/run, probe/grid settings, penalties, query counters, source/effective input hashes, binary/linked-library and planner-code hashes. |
| `baseline/effective-inputs/baseline-plan.json` | Source and planned positions, selected nodes, unchanged altitude, initial displacement; correlate it with the manifest fingerprint. |
| `baseline/planner.log` | AOI-to-cost scale warnings, query diagnostics and preparation errors. |
| `comparison/episodes.csv` | `initial_displacement_m_total` beside `travel_m_total`, with per-episode status and delivery metrics. |
| `comparison/comparison.json` | Per-policy `movement` block: initial relocation separately from mean scored travel and usable episode count. |

Initial relocation measures x/y source-to-plan distance before reset. Scored
travel measures movement during the scored episode window. Do not add the two:
this workflow has no common physical relocation/warmup accounting model. A
placement policy holds after reset and ordinarily has zero scored travel while
still showing its initial relocation.

The planner predicts t=0 channel facts and combines normalized score components
with m²-equivalent relocation costs. It does not predict delivered demand or
learning quality. Large fixed-cost/AOI ratios produce a scale warning; other
weighted terms can still favor a move. Zero costs also do not guarantee movement,
particularly with constraints or a local search. Compare the actual scored
telemetry before making a performance claim.

For cluster matrix runs, follow the [matrix workflow](../../README.md#comparing-policies-and-running-an-experiment-matrix)
and [operations guide](../rl/ops/README.md#cluster-runs). Fetch explanations along
with results into a fresh destination:

```bash
.venv/bin/python -m scripts.rl.ops.fetch \
  --remote user@host:/abs/matrix-output-root --dest outputs/fetched/placement-example \
  --select comparison,manifests,inputs,logs
```

This fetch command requires the matrix's `experiment_plan.json`; the local
single-run layout above is not a matrix root. `manifests` includes placement
manifests/plans, `inputs` includes source/effective snapshots and `logs` includes
planner logs. Existing local files are not overwritten.

Mapping v2, baseline manifest/plan/fingerprint v3, evaluation v5 and comparison
v2 are the current schemas. Regenerate older results; relabeling versions does
not recreate missing planning or movement facts.
