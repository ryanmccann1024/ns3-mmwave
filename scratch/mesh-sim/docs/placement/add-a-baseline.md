# Add a baseline {#mesh_sim_placement_add}

[TOC]

Add a new placement method, `random_search`, from name to tested plan. Each
step changes one file and ends with a checkpoint. All paths are relative to
`scratch/mesh-sim/`.

<!-- Every step on this page was applied to a scratch copy of scripts/, src/,
     third_party/ and inputs/ on 2026-10-28 (mesh-sim commit b54bfbe7 plus the
     working tree) and run there: baseline suite 603 passed, 28 skipped; runner
     on run-zero-cost.ini with binary SHA-256
     d7a2f4d1eb52c30abb0c6cecc8480aa29232afd12730fcc402caa0fc446c9fe2.
     Step 7 (C++) was not applied or built. The repository does not contain
     random_search. -->

## 1\. Before you start

- You have read \ref mesh_sim_placement_code "How a plan is made". You know
  what `solver.solve`, `planners/objective.py` and `adapter.validate_result`
  do.
- You can run the baseline tests:
  `.venv/bin/python -m pytest scripts/baselines/tests -q` passes.
- `SIM_BIN` and `EX` are set as in \ref mesh_sim_placement_run "Run a baseline",
  and you run commands from `scratch/mesh-sim/`.
- A new method changes **how layouts are searched**. If you want to change
  **what counts as a good layout**, you want a score term instead; see
  section 12.

**The example.** `random_search` draws `max_iterations` random layouts from the
movable nodes' allowed positions, scores them all, and keeps the best one if
it beats the starting layout. It is simple enough to read in a minute and a
useful yardstick: a smarter search should beat it on the same seeds.

## 2\. What a method must provide

A method is one module, `scripts/baselines/planners/<name>.py`, with these
functions:

| Function | Required | Contract |
|---|---|---|
| `solve(request, scorer, log)` | yes | Returns `(positions, diagnostics, notes)`: an N × 3 array in `nodes.json` order, a dict that converts to JSON, and a list of strings. |
| `settings(request)` | yes | Returns a dict describing how the method behaves. It is saved in the manifest and hashed into the plan's fingerprint. |
| `validate_request(request)` | no | Raises `PlannerError` for bad settings. It runs **before** the binary starts, so a mistake fails fast. |

What it can use:

| Name | Use it to |
|---|---|
| `request.nodes` | Read each node's id, x, y, z, platform and role (`movable` or `fixed`). |
| `request.planner_seed`, `request.max_iterations` | Read `[baseline] seed` and `max_iterations`, once step 3 passes them in. |
| `ScoringContext.build(request, scorer)` | Get `ctx`: `ctx.starts` (start layout, N × 3), `ctx.selected` (indices of movable nodes), `ctx.aoi_m2`. |
| `candidate_positions(ctx, i)` | Get node `i`'s allowed positions. Row 0 is where it is now. The rest already respect the area, bounds, cap and buildings. |
| `LayoutCache(scorer, ...)` | Score layouts with `.evaluate([...])`, or `.iter_evaluate(...)` for many. A repeated layout is free. |
| `score(ctx, result, layout)` | Turn one channel result into a score; compare `.total`. |
| `check_layout(ctx, layout)` | Raise if a fixed node moved, a z changed or nodes are too close. |
| `diagnose(ctx, result, layout, layout_score, log=log)` | Build the standard `planner_predictions` for the plan file. |

The rules your plan must follow:

- Write only the rows of movable nodes.
- Never change a z.
- Stay inside what `candidate_positions` allows.
- Score every layout with the scorer. Never estimate a score yourself.
- Take all randomness from `planner_seed`, never from `planning_seed`, which
  belongs to the channel.
- Staying put is always a valid answer.

## 3\. Register the name

In `scripts/baselines/config.py`:

```python
PLACEMENT_METHODS = ("geometric", "optimization", "random_search")
```

This one tuple feeds:

- the accepted `[baseline] algorithm` values;
- the runner's `--algorithm` choices;
- `solver.STRATEGIES`, which imports `planners/random_search.py`.

Never edit `STRATEGIES` directly.

**Checkpoint:**

```bash
.venv/bin/python -m scripts.baselines.runner --help | grep -A1 -- '--algorithm {'
```

```
  --algorithm {none,geometric,optimization,random_search}
                        Override [baseline] algorithm
```

## 4\. Require its settings

`random_search` needs a seed and a sample count, like `optimization`. In
`require_method` in the same file:

```python
    required = ["objective", "movable_nodes"]
    if method in ("optimization", "random_search"):
        required += ["seed", "max_iterations"]
```

**Checkpoint:** a settings file without `seed` now fails while it is read,
before anything launches:

```
.../run.ini: method 'random_search' requires [baseline] seed
```

## 5\. Pass the settings to the search

`scripts/baselines/preparation.py` hands `seed` and `max_iterations` only to
`optimization`, and gives every other method `None`. Widen the three places
that test for it:

| Where | Change |
|---|---|
| `_seed_fields` | `if method in ("optimization", "random_search"):` |
| `_plan`, the `planner_seed=` argument | `cfg.seed if method in ("optimization", "random_search") else None` |
| `_plan`, the `max_iterations=` argument | the same test |

A method that needs neither key, like `geometric`, skips this step and the
previous one.

**Checkpoint:** comes in step 8, where the manifest reports
`planner_seed_status` as `used`.

## 6\. Write the search

Create `scripts/baselines/planners/random_search.py`:

```python
"""Best of N random layouts, scored by the channel; the guide's example strategy."""

import numpy as np

from scripts.baselines.planners import objective
from scripts.baselines.planners.channel import PlannerError
from scripts.baselines.planners.objective import (
    LayoutCache,
    ScoringContext,
    candidate_positions,
    check_layout,
    diagnose,
    score,
)


def validate_request(request):
    """Fail before the channel worker starts when a required setting is missing."""
    if not isinstance(request.max_iterations, int) or request.max_iterations < 1:
        raise PlannerError("random_search needs [baseline] max_iterations >= 1")
    if not isinstance(request.planner_seed, int) or request.planner_seed < 0:
        raise PlannerError("random_search needs a nonnegative integer [baseline] seed")


def settings(request) -> dict:
    """Resolved behavior; saved in the manifest and folded into the settings hash."""
    return {
        "strategy": "random_search",
        "samples": request.max_iterations,
        "acceptance": "strictly_positive_total_gain",
        "score_tie_tol_m2": objective.SCORE_TIE_TOL_M2,
    }


def solve(request, scorer, log):
    """Score max_iterations random layouts; returns (N x 3, diagnostics, notes)."""
    validate_request(request)
    ctx = ScoringContext.build(request, scorer)
    cache = LayoutCache(scorer, getattr(request, "cache_bytes", 32 * 1024 * 1024))
    rng = np.random.default_rng(request.planner_seed)

    start = ctx.starts.copy()
    check_layout(ctx, start)
    best_layout = start
    best_result = cache.evaluate([start])[0]
    best = start_score = score(ctx, best_result, start)

    # Row 0 of each node's options is its start, so staying put is always a draw.
    options = {node: candidate_positions(ctx, node) for node in ctx.selected}
    trials = []
    for _ in range(request.max_iterations):
        layout = start.copy()
        for node, rows in options.items():
            layout[node] = rows[rng.integers(len(rows))]
        if objective.layout_separated(ctx, layout):
            trials.append(layout)

    for layout, result in zip(trials, cache.iter_evaluate(trials)):
        trial = score(ctx, result, layout)
        if trial.total > best.total + objective.SCORE_TIE_TOL_M2:
            best_layout, best_result, best = layout, result, trial

    check_layout(ctx, best_layout)
    log.write(
        f"random_search: {len(trials)} layouts scored, "
        f"gain {best.total - start_score.total:.6g} m2\n"
    )
    diagnostics = diagnose(ctx, best_result, best_layout, best, log=log)
    diagnostics["random_search"] = {"scored": len(trials), "start_total": start_score.total}
    return best_layout, diagnostics, [f"random_search: best of {len(trials)} layouts"]
```

How it keeps the rules:

- It writes only rows in `ctx.selected`, with x, y and z all taken from
  `candidate_positions`.
- The start layout is the one to beat, so staying put is the default.
- `layout_separated` skips layouts that put nodes too close together, which
  matters when `[rl] avoid_node_collisions` is on.

Settings that only this method uses, such as a sample count separate from
`max_iterations`, belong in this module or in `planner_config.py`, not in
`[baseline]`.

## 7\. Test it without the simulator

The test helpers run the real `ChannelScorer` against `tests/fake_query.py`, a
stand-in binary whose channel is simply "connected within 100 m". Create
`scripts/baselines/tests/test_random_search.py`:

```python
"""Random search against fake_query.py's distance channel."""

import json

import numpy as np

from scripts.baselines.planners import random_search
from scripts.baselines.tests.test_objective import (
    ZERO, assert_plan_invariants, entry, make_request, planning_scorer)


def _solve(tmp_path, monkeypatch, entries, movable, **kwargs):
    request = make_request(entries, movable, method="random_search", **kwargs)
    with planning_scorer(tmp_path, monkeypatch, entries, request) as (scorer, log):
        positions, diagnostics, notes = random_search.solve(request, scorer, log)
    json.dumps(diagnostics)
    json.dumps(random_search.settings(request))
    assert_plan_invariants(request, positions)
    return request, positions, diagnostics


def test_same_seed_same_plan(tmp_path, monkeypatch):
    entries = [entry("A", 100.0, 100.0, 10.0), entry("B", 150.0, 100.0, 10.0),
               entry("C", 300.0, 300.0, 10.0)]
    kwargs = dict(penalties=ZERO, planner_seed=3, max_iterations=20)
    _, first, d1 = _solve(tmp_path / "1", monkeypatch, entries, {"A", "C"}, **kwargs)
    _, second, _ = _solve(tmp_path / "2", monkeypatch, entries, {"A", "C"}, **kwargs)
    assert np.array_equal(first, second)
    assert d1["random_search"]["scored"] >= 1
```

`assert_plan_invariants` checks the rules from section 2: fixed nodes
unmoved and no z changed.

**Checkpoint:**

```bash
.venv/bin/python -m pytest scripts/baselines/tests/test_random_search.py -q
.venv/bin/python -m pytest scripts/baselines/tests -q
```

The first prints `1 passed`. The second passes with no failures; tests that
need a real binary are skipped.

Before you call the method done, add tests next to the existing ones for:

- a missing `seed` or `max_iterations` (`test_config.py`);
- staying put when nothing improves the score;
- each objective;
- evaluation mode with `[rl]` bounds;
- the runner picking `--algorithm random_search` (`test_runner.py`).

`test_geometric.py` and `test_optimization.py` have one example of each.

## 8\. Run it on the real channel

```bash
.venv/bin/python -m scripts.baselines.runner \
  --sim-binary "$SIM_BIN" --run-config "$EX/run-zero-cost.ini" \
  --algorithm random_search --output-dir outputs/my-baselines/random-search
```

`--algorithm` overrides the file's `algorithm = geometric`, so the scenario
files need no change.

**Checkpoint:** it prints `Baseline run complete: ...`, and

```bash
grep '^random_search' outputs/my-baselines/random-search/planner.log
```

```
random_search: 100 layouts scored, gain 95.4895 m2
```

In `baseline_manifest.json`:

- `status` is `complete`;
- `method` and `planner_settings.strategy` are `random_search`;
- `planner_seed` is `201` with `planner_seed_status` `used`, which confirms
  step 5.

**Does it beat `geometric`?** On the same file and seeds:

| Method | Planner score | Gain over start |
|---|---|---|
| start layout | 160,181 m² | — |
| `random_search`, 100 samples | 160,276 m² | 95 m² |
| `geometric` | 160,295 m² | 114 m² |

`geometric` wins here, as it should. Run more samples, other seeds and the
penalized `run.ini` before drawing any conclusion. Then check the simulation
results, as on \ref mesh_sim_placement_read "Understand the plan".

## 9\. Make it an evaluation policy

In `scripts/rl/policy/evaluate.py`:

```python
PLACEMENT_POLICIES = ("geometric", "optimization", "random_search")
```

`scripts.rl.evaluate --policies random_search` and experiment matrices then
accept the name, because both check against this list.

Two RL scripts list the methods by hand. Change them only if you want the new
method there too:

- `scripts/rl/scenario_check/execution.py`, the default placement benchmarks;
- `scripts/rl/adaptive_campaign.py`, a default policy list.

## 10\. Let the simulator accept the name

The binary never plans, but it does check that `[baseline] algorithm` is a
known value. Add the name in `src/config/config-validator.cc`:

```cpp
    checkOneOf(r, "baseline.algorithm", cfg.baseline.algorithm,
               {"none", "geometric", "optimization", "random_search"});
```

This is C++, so rebuild the binary
(\ref mesh_sim_install_build "Install and build").

Step 8 worked without this change because `--algorithm` overrode the file.
Without it, a `run.ini` that says `algorithm = random_search` fails to load
in RL training and evaluation, and in the direct-run check.

## 11\. Document it

In the same change, update:

- `scripts/baselines/README.md`, section 2: the `algorithm` values and the
  keys the method requires;
- `src/config/run-ini-reference.md`: the `algorithm` row;
- `scripts/baselines/planners/README.md`: how the search works;
- \ref mesh_sim_placement_start "Placement baselines": the policy table;
- [CONTRIBUTING.md](@ref Contributing): check its "update together" rows for
  the placement engine.

## 12\. Other kinds of change

| You want to | Change | Example |
|---|---|---|
| Score something new, such as capacity | Register a `ScoreComponent` in `planners/components.py` and add its name to an objective's `components` in `planners/objective.py`. `score()` picks it up without other edits. | `test_new_objective_and_component_use_registry_without_composer_edits` in `test_engine_settings.py` |
| Add an objective name | Add an `ObjectivePreset` to `OBJECTIVE_PRESETS` in `planners/objective.py`, then add the name to `OBJECTIVES` in **both** `planners/objective.py` and `config.py`. | The same test |
| Tune an existing method | Set `[placement_objective]` or `[placement_optimizer]` keys in `run.ini`; no code change. | \ref scripts_baselines_planners "Planners page", "Configuration and extension" |

## 13\. Checklist

| Step | File | Change |
|---|---|---|
| 3 | `scripts/baselines/config.py` | Add the name to `PLACEMENT_METHODS` |
| 4 | `scripts/baselines/config.py` | `require_method`: required keys |
| 5 | `scripts/baselines/preparation.py` | `_seed_fields` and `_plan`: pass seed and budget |
| 6 | `scripts/baselines/planners/<name>.py` | `solve`, `settings`, `validate_request` |
| 7 | `scripts/baselines/tests/test_<name>.py` | Fake-channel tests |
| 8 | — | One runner run on the real binary |
| 9 | `scripts/rl/policy/evaluate.py` | `PLACEMENT_POLICIES` |
| 10 | `src/config/config-validator.cc` | Accepted `algorithm` values; rebuild |
| 11 | READMEs, run.ini reference | Document the method |

Never touch `solver.STRATEGIES`, which is derived, or anything in
`third_party/arpo_placement/`, whose hashes are tested.

Previous: \ref mesh_sim_placement_code "How a plan is made"
