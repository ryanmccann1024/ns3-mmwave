@page scripts_baselines_planners scripts/baselines/planners

@brief The geometric and optimization placement planners and their shared objective and channel scorer.

The two placement baselines, `geometric` (sequential greedy) and
`optimization` (simulated annealing), adapted from the Desktop reference copy
in `third_party/arpo_placement/` (read-only; nothing imports it). Every
candidate layout is scored by the simulator's own channel through the
`--channel-query` worker, so there is no Friis model and no RF YAML here.

| File | Owns |
| --- | --- |
| `channel.py` | `ChannelScorer`: the only client of the `mesh_channel_query_v1` worker (launch, init check, batching, timeouts, cleanup, stats). |
| `objective.py` | Grids, objective presets/settings, scoring context, composition, diagnostics, movement costs and candidate positions. |
| `components.py` | Independent score terms, their parameter validation, units and versions. |
| `graph.py` | Rootless connected components and single-node-loss facts. |
| `cache.py` | Bounded LRU retention and incremental candidate batches. |
| `../planner_config.py` | Strict INI reading; delegates settings to the three owners. |
| `../solver.py` | Engine request/result types, strategy registry and worker coordination. |
| `geometric.py` | Greedy peer-anchor placement. |
| `optimization.py` | Keep-best annealing, warm-started from `geometric`. |

Both strategies take `(request, scorer, log)` with the scorer's probes already
set by `objective.prepare_scorer`, and return `(positions N x 3, diagnostics,
notes)`. Each strategy's `settings(request)` records resolved behavior. `solver.solve`
adds component versions, query settings and advertised worker limits under
`engine_settings_version = 1`, with a canonical SHA-256 over the settings.
Changing a coefficient changes this identity. The engine returns these in
`PlanResult.planner_settings`, including grid, resolved probe gain, movement
costs and bounds; callers must persist them with the plan. This settings hash
is not a complete scenario/source fingerprint: retain staged input hashes,
seeds and simulator revision separately.

## Shared objective

All terms are m² so the Desktop penalty values keep their units. Each layout
is one full query: the t = 0 mesh link table plus every node-to-probe link.
`connected` comes from the worker; Python never re-derives a threshold.

- **Core.** Connected components over all mesh nodes; the core is the largest,
  ties going to the component holding the smallest roster index. No root.
- **Coverage.** Probes sit at the clipped-cell centres of the coverage grid and
  carry their clipped areas (the areas sum to the AOI). A probe counts once if
  any core node covers it. Nodes outside the core contribute nothing.
- **Connectivity.** `BIG = 2 x AOI` per selected node outside the core.
  Unselected nodes are never charged.
- **Vulnerability pairs.** For each victim in core ∩ selected, remove it,
  recompute components and count unordered core pairs (victim excluded) that
  end up apart. Weight per pair: `resilience` AOI, `balanced` 0.02 x AOI,
  `coverage` 0.
- **Separation tie-break.** `0.4 x cell_m² x mean over selected of
  min(nearest-neighbour distance / rectangle diagonal, 1)`; the default is
  below one coverage cell, while an overridden coefficient may exceed it.
- **Movement.** Per selected node, from its ORIGINAL start:
  `0` if displacement ≤ 1e-6 m, else `fixed_cost_m2 + cost_m2_per_m x d`.
  `max_displacement_m` is a hard cap on candidates and proposals.

The defaults give `total = coverage + separation - movement - BIG x disconnected - w x vuln`.
The configurable coverage weight multiplies coverage; component overrides can
replace the resolved coefficients. Diagnostics retain physical coverage and
individual signed score contributions.
`diagnose` adds component sizes, core ids, `survives_single_node_loss`
(victims = every core member), `controlled_mesh_survives_single_loss`
(victims = core ∩ selected), per-node displacement and cost, and
`fixed_cost_m2 / AOI` per platform. A ratio ≥ 1 is logged as a scale warning,
never an error. It does not guarantee staying put: connectivity, resilience
and separation gains can also offset relocation costs.

Grid cell size follows the Desktop rule `max(min_resolution_m,
sqrt(AOI / cells))`, with cells laid from the rectangle's lower-left corner.
Unlike the Desktop grid, every cell that overlaps the rectangle is kept and
the last row/column is clipped, so edge cells are weighted by their real area.
The candidate grid uses the same rule with `candidate_cells`.

## Geometric: sequential greedy

1. Query the start layout and score it.
2. Visit selected nodes once each, in roster order. For node `i`, the anchor
   pool is the current core's unselected members plus already-visited
   selected members (at their chosen position, stay-put included), minus `i`.
   The pool is recomputed from the current core before every node, so it is
   always one component.
3. Needs: `coverage` 1 per node, `resilience` 2, `balanced`
   `ceil(n x balanced_core_fraction)` twos then ones.
   `eff_need = min(need, pool size)`; an empty pool is a zero-anchor
   bootstrap (an all-movable roster starts this way).
4. Candidates are candidate-grid points inside the rectangle, the evaluation
   `[rl]` bounds, the node's random-walk bounds and its cap. All candidate
   layouts are generated and scored incrementally in bounded batches. A candidate is feasible
   when the queried `connected` matrix links `i` to at least `eff_need` pool
   members; with none at 2, the need drops to 1.
5. Each feasible layout is scored in full. The best one is taken only if its
   total beats the current layout's by more than 1e-6 m²; otherwise the node
   stays put. Stay-put is always allowed, even when no candidate is feasible.

Anchor links only filter candidates. Whether the result survives a node loss
is decided by the vulnerability term and `diagnose`, not by link counts.
Results are cached by exact layout bytes within a byte-accounted LRU budget; there are no partial or
changed-pairs-only queries, because sampled draws depend on evaluation order
(see [src/query](@ref src_query)).

## Optimization: keep-best annealing

1. Run `geometric` with the same objective, then query the greedy layout and
   the start layout (two queries) and continue from the better one (ties go
   to the greedy layout). The best layout seen is returned. `warm_start = current` skips greedy planning
   and records that fact explicitly.
2. Each iteration draws a move with weights renormalised after dropping the
   Desktop `altitude` move: nudge 0.55/0.85, teleport 0.20/0.85, swap
   0.10/0.85.
   - `nudge`: Gaussian x/y step on one selected node.
   - `teleport`: one selected node to a random uncovered probe plus a Gaussian
     jitter of 0.15 x sigma.
   - `swap`: two selected nodes exchange x/y only; each keeps its own z.
     With one selected node it acts as a nudge.
3. Every moved node is pulled back inside its cap (to 0.999 x cap, measured
   from its original start), then the proposal is rejected without a query
   if any moved node is outside the rectangle, the evaluation `[rl]` bounds or
   its random-walk bounds.
4. Each remaining proposal is one full query. Metropolis acceptance at
   `T = T0 (Tf / T0)^frac`, with `T0 = 0.02 x AOI`, `Tf = 0.0002 x AOI`,
   `sigma = 0.08 x diagonal x 0.05^frac + 2 m`, and `frac = iteration /
   max_iterations`. The run stops after `max_iterations`; there is no time
   budget. The RNG is `numpy.random.default_rng(planner seed)`.

For a fixed worker and seed, a run is repeatable on one machine. Different
layouts can consume different numbers of channel draws, so the objective is
not a smooth function of position.

## Differences from the Desktop reference

| Desktop | Here |
| --- | --- |
| C2/gateway root; reachability by BFS from it | Rootless largest-component core; no gateway, fixed anchor or BLOS terminal. |
| Order: movable C2 first, then longest radio range | Roster order. |
| Anchors: C2 plus satellite terminals plus placed movables; connected relays as 1-anchors | Pool from the current core only (unselected members plus visited selected members); zero-anchor bootstrap when empty. |
| Disc coverage from Friis ranges on uniform cells | Probe receivers scored by the simulator channel; clipped-cell areas. |
| Greedy gain: new coverage minus move cost plus separation of the node alone | Full-layout score delta, including connectivity, vulnerability and every selected node's movement cost. |
| Pure-relay nodes push the frontier; soft costs only for coverage radios | Every mesh node is a coverage node; soft costs apply to all selected nodes. |
| (victim, orphan) counts from the gateway; sole backhaul terminal skipped | (victim, split core pair) counts over the core. |
| Moves include `altitude`; `swap` exchanges positions and altitudes | No altitude move; `swap` is x/y only; z never changes. |
| Swap over the cap is rejected | Both swap participants are clamped like single-node moves. |
| Time budget `budget_s_per_coa` or `max_iters` | `max_iterations` only. |
| RF/optimizer YAML (`rf_config`) | Engine settings use the owned INI sections below; movement penalties are supplied in `PlanRequest`. |
| Altitude chosen per node from its AGL band | z fixed at each node's start. |


## Configuration and extension

Baseline preparation and placement evaluation policies call this engine API.
These sections are read by `solver.solve(request, log)` from the staged
`query_run_config`:

```ini
[placement_objective]
coverage_weight = 1
separation_frac = 0.4
disconnected_aoi_factor = 2
# Omit vulnerability_aoi_factor to use coverage=0, balanced=0.02, resilience=1.
# Component parameters override the corresponding flat coefficient.
component_parameters = {"coverage": {"coverage_weight": 1.25}}

[placement_optimizer]
t0_area_frac = 0.02
tf_area_frac = 0.0002
nudge_sigma_frac = 0.08
sigma_final_ratio = 0.05
sigma_floor_m = 2
teleport_jitter_frac = 0.15
cap_pullback = 0.999
move_weights = {"nudge": 0.55, "teleport": 0.20, "swap": 0.10}
warm_start = geometric

[channel_query_client]
init_timeout_s = 60
shutdown_grace_s = 5
terminate_wait_s = 5
request_margin_s = 5
max_layouts = 32
response_budget_bytes = 67108864
cache_bytes = 33554432
# request_timeout_s = 190  # Optional explicit per-request deadline, seconds.

[channel_query]
child_deadline_s = 60
terminate_grace_s = 1
max_child_response_bytes = 16777216
max_response_bytes = 67108864
```

An explicit `ObjectiveSettings`, `OptimizerSettings` or `QuerySettings` on
`PlanRequest` replaces that entire INI section; otherwise INI overrides owner
defaults. Empty/unknown keys, non-finite numbers, invalid types and negative
weights fail. All objective coefficients are nonnegative; optimizer scales
are positive, final temperature cannot exceed initial temperature, and
pullback/final sigma ratio are in (0,1]. Move weights are nonnegative with a
finite positive sum, then normalized; zero disables a move. `warm_start` is
`geometric` or `current`. Optimizer RNG `planner_seed` is separate from the
channel realization's `planning_seed`; keep both separate from held-out
performance seeds. `run_id` must match the staged INI's realization.

The default client deadline is `request_margin_s + layout_count *
(child_deadline_s + terminate_grace_s)` using the worker handshake. An explicit
`request_timeout_s` deliberately caps the whole request, including writes and
reads, and may cancel valid slow work. Batch count also respects request bytes
and the smaller of client/worker response budgets, reserving envelope space.
With default 16 MiB child and 64 MiB response bounds, at most three layouts
are sent together. The parent rejects oversized aggregate responses before
retaining more entries. A cache budget of zero disables retention; an entry
larger than the budget is returned without caching. Grid construction rejects
more than 100,000 candidate points before allocating; coverage also respects
the worker's probe limit. Per-layout full facts still cost O(N² + N×probes).

To add a score term, register a `ScoreComponent` in `components.py` with
`value(ctx, facts, parameters)`, owned default parameters, unit and version.
The facts include `result`, `layout`, `core`, coverage, separation, movement,
disconnected nodes and vulnerability. Add it to an `ObjectivePreset` with its
anchor schedule; the composer needs no new name branch. Unused or unknown
component parameters are rejected. To add an optimizer, register a module in
`solver.STRATEGIES` exposing `solve`, `settings`, and optionally
`validate_request`. Keep its settings validation and search mechanics with
that owner. Add public INI/matrix selectors in their configuration owners
when exposing a new strategy through those entry points.

## Engine example and artifacts

Use an already built binary; the following API example creates no training
run. The scenario must contain fixed nodes `A` at (50,50,10) and `B` at
(100,50,10), with no active traffic gateway, and valid ordinary simulator
configuration. Resolve band from the INI or pass an explicit band. Selected
random-walk nodes must supply their resolved walk bounds in `PlannerNode`;
waypoint starts come from their first waypoint.

```python
import json
from pathlib import Path
from scripts.baselines.solver import PlannerNode, PlanRequest, solve
from scripts.baselines.planners.objective import GridSettings, ProbeSettings, MovementCost

nodes = (
    PlannerNode("A", 0, "fixed", "aerial", 50, 50, 10, "movable"),
    PlannerNode("B", 1, "fixed", "aerial", 100, 50, 10),
)
request = PlanRequest(
    method="geometric", objective="balanced", nodes=nodes,
    rectangle={"x_min": 0, "x_max": 400, "y_min": 0, "y_max": 400},
    rl_bounds=None, mode="standalone", penalties={"aerial": MovementCost(0, 0)},
    grid=GridSettings(16, 64, 5), probe=ProbeSettings(1.5, None, -6.7),
    planner_seed=3, max_iterations=25, balanced_core_fraction=0.5,
    waypoint_policy="reject", planning_seed=5, run_id=1, band=None,
    query_run_config=Path("scenario/run.ini").resolve(),
    sim_binary=Path("/absolute/path/to/already-built-binary"),
)
with open("planner.log", "w") as log:
    result = solve(request, log)
Path("engine-result.json").write_text(json.dumps({
    "positions": result.positions, "predictions": result.predictions,
    "planner_settings": result.planner_settings, "query_stats": result.query_stats,
    "channel": result.channel, "notes": result.notes,
}, indent=2) + "\n")
```

The caller writes `planner.log` and `engine-result.json`; the query worker
creates no run directory. Expect resolved coefficients/hash, selected-node
positions, signed score components, channel diagnostics and query counts.
Planning excludes the active traffic gateway through the existing authority
owner. Strategies keep unselected nodes and all z coordinates unchanged.
An init mismatch, bad layout, timeout or response overflow raises
`PlannerError` and closes the worker group; configuration errors fail before
launch. Do not publish a partial plan after an exception.

Capacity is returned as a channel fact but is not a default objective term.
Reduced capacity alone therefore does not change placement scores. These
are initial 2D layouts scored at t=0, not warmup/episode performance or a
periodic controller. Keep initial relocation separate from scored episode
travel. The default thresholds and jammed-SINR clamp may make binary
coverage/connectivity insensitive to jamming; these scores do not establish
jammer avoidance.

The fake engine example is exercised by `test_engine_settings.py`. Pure query
units use a stub evaluator to test protocol limits, pipe draining, deadlines
and reaping. Real t=0 parity, sampled-channel isolation, timing, cancellation
and performance remain checks for a human-built binary; the unit passes and
syntax checks do not establish them.
