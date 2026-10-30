@page scripts_baselines scripts/baselines

@brief Plans gateway-free geometric and optimization node placements before a run, scored by the simulator channel.

`scripts/baselines/` plans the gateway-free `geometric` and `optimization`
placement baselines once, before a simulation. It hands the simulator an
ordinary scenario whose selected nodes start at the planned positions. Every
candidate layout is scored by the simulator's own channel through its
`--channel-query` mode ([contract](@ref src_query)). There is no separate RF
model or RF file, and the only extra Python dependency is `numpy`.

New here? Start with \ref mesh_sim_placement_start "Placement baselines";
this page is the reference it links to.

## 1\. Usage

Run from `scratch/mesh-sim/`. There are two ways to use a placement baseline.

### Standalone run

Plan once, then run the ordinary (non-RL) simulator on the plan:

```bash
.venv/bin/python -m scripts.baselines.runner \
  --sim-binary <BIN> --run-config <INI> \
  [--seeds 1,2,3] [--algorithm none|geometric|optimization] [--output-dir DIR] \
  [--band mmwave|sub-6] [--planning-seed N] [--allow-seed-overlap]
```

| Option | Default | Description |
| --- | --- | --- |
| `--sim-binary` | required | Serves the channel queries while planning, then runs the simulation. |
| `--run-config` | required | The scenario's `run.ini`. |
| `--algorithm` | `[baseline] algorithm`, else `none` | Placement method. |
| `--seeds` | `[scenario] seed` (the simulator's default, 42, when the key is absent) | Simulation seeds. Accepts `A-B` ranges; the simulator receives the expanded comma list. |
| `--output-dir` | `outputs/YYYY-MM/DD/HH-MM-SS-baseline[-N]` under the mesh-sim root | Must be absent or empty; otherwise the runner exits 1 and writes nothing. |
| `--band` | the scenario's band | Radio band. |
| `--planning-seed` | `[baseline] planning_seed` | Channel seed used to choose the plan; required for an active method. |
| `--allow-seed-overlap` | false | Allows the planning seed to overlap the evaluation seeds (adaptation diagnostic; see section 6). |

| Exit code | Meaning |
| --- | --- |
| `0` | The run is `complete`. |
| `1` | Argument or preparation error, or a seed has no `summary.json`. |
| simulator's code | The simulator exited non-zero. |
| `128 + signal` | Interrupted (130 for SIGINT, 143 for SIGTERM). |

### Policy evaluation

`geometric` and `optimization` are also policy names in `scripts.rl.evaluate`,
next to `model`, `hold` and `random_valid`:

```bash
.venv/bin/python -m scripts.rl.evaluate \
  --sim-binary <BIN> --run-config <INI> \
  --seeds 1,2 --policies hold,random_valid,geometric,optimization
```

- The `--policies` default is `model,hold,random_valid`.
- Every requested placement method is prepared before any episode runs. A
  preparation failure exits 1, runs no episode and writes no
  `eval_manifest.json`.
- The policy name is the method; `[baseline] algorithm` is only recorded as
  `requested_algorithm`.
- `[baseline] movable_nodes` must name the same nodes as `[rl] controlled_nodes`
  (see [Evaluation requirements](@ref scripts_baselines_hold_executor)).

\ref mesh_sim_placement_run "Run a baseline" and
\ref mesh_sim_placement_read "Understand the plan" run both methods on a
committed example and read every output.

## 2\. The [baseline] section

The C++ binary reads only `algorithm`. `config.py` reads the other keys and
rejects unknown keys, unknown values, duplicate sections or keys, `:`
assignments, and indented continuation lines. The Python launchers reject
misspelled keys; the binary does not see them. See also
[`src/config/run-ini-reference.md`](@ref src_config_run_ini_reference).

| Key | Values | Default | Required when active |
| --- | --- | --- | --- |
| `algorithm` | `none`, `geometric`, `optimization` | `none` (also for an absent section or blank value) | — |
| `objective` | `coverage`, `balanced`, `resilience` | none | yes |
| `application` | `initial_positions` | `initial_positions` | no |
| `movable_nodes` | distinct comma list of node ids, or `all` | none | yes |
| `seed` | integer ≥ 0; optimizer proposal RNG, separate from the channel seed | none | `optimization` |
| `planning_seed` | integer in [1, 2147483647]; channel realization used to select the plan | none | yes, unless `--planning-seed` supplies it |
| `max_iterations` | integer ≥ 1; the optimizer's only termination rule | none | `optimization` |
| `waypoint_policy` | `reject`, `translate` | `reject` | no |
| `mapping_file` | mapping v2 path, relative to the INI | none (see section 3) | no |
| `aerial_fixed_cost_m2`, `ground_fixed_cost_m2` | number ≥ 0, m² per move | `150000` | no |
| `aerial_cost_m2_per_m`, `ground_cost_m2_per_m` | number ≥ 0, m² per meter | `500` / `100` | no |
| `aerial_max_displacement_m`, `ground_max_displacement_m` | number > 0, meters | none (unlimited) | no |
| `candidate_grid_cells`, `coverage_grid_cells` | integer ≥ 1 | `400` | no |
| `grid_min_resolution_m` | number > 0 | `5.0` | no |
| `coverage_probe_height_m` | number ≥ 0 | `1.5` | no |
| `coverage_probe_rx_gain_dbi` | finite number ≥ 0 | the query's `[channel] rx_array_gain_dbi` | no |
| `coverage_sinr_db` | finite number | `-6.7` | no |
| `balanced_core_fraction` | number in [0, 1] | `0.5` | no |

- `geometric` accepts `seed` and `max_iterations`, so one INI can serve both
  methods. The manifest records them as `null` with status `unused` /
  `not_applicable`.
- Movable nodes are never inferred from `[traffic]` or `[rl]`.
- Zero is not a valid displacement cap; omit the key for no cap.
- The active `[traffic]` gateway cannot be selected or RL-controlled, including
  through `all`. The algorithms need no anchor gateway.

## 3\. Mapping file (optional)

Without `mapping_file`, the geofence is `rl_bounds` and each node's platform
comes from its `node_type`. A mapping file has exactly these top-level keys
(`platforms` is optional):

```json
{
  "baseline_mapping_version": 2,
  "geofence": {"source": "rl_bounds"},
  "platforms": {"nodes": {"<node-id>": "aerial"}}
}
```

| Field | Rule |
| --- | --- |
| `geofence` | `{"source": "rl_bounds"}` uses `[rl] x_min, x_max, y_min, y_max`, all four written in the INI (loader defaults are not used). `{"source": "rectangle_xy_m", "x_min": …, "x_max": …, "y_min": …, "y_max": …}` gives the rectangle directly. |
| `platforms` | Optional per-node `ground` or `aerial`. Otherwise `drone` is `aerial`, and `vehicle` and `pedestrian` are `ground`; any other `node_type` needs an entry here. |

z is meters above flat ground at z = 0; a node with z < 0 fails preparation.

### Rectangle geofences only

The adapter supports **only an axis-aligned rectangle** in scenario meters. The
reference planner in `third_party/` handles polygon geofences; the adapted
planners accept no polygon vertices and do not derive a polygon from buildings.

`mapping.py` rejects a polygon-shaped request instead of approximating it. It
fails when `geofence` is a JSON list, when it has any of the keys `vertices`,
`polygon`, `polygons`, `points`, `coordinates`, `rings`, `holes`, `geojson`,
`exterior` or `interiors`, or when an unknown `source` mentions `poly`,
`geojson`, `vert` or `point`. The error ends with:

> only axis-aligned rectangle geofences are supported (geofence.source
> 'rl_bounds' or 'rectangle_xy_m'); polygon geofences are a documented TODO,
> and a bounding rectangle is never substituted

Do not substitute the bounding rectangle of an irregular permitted area. The
planner can then place nodes in the excluded parts of that rectangle (a no-fly
zone, a building footprint, water) while every recorded check still passes.

**TODO (polygon geofences):** needs its own mapping schema, coordinate
conversion, containment checks on the result, boundary and hole semantics, and
tests.

## 4\. Objective

All terms are in m², so movement penalties and coverage trade off directly.
The mesh link table at t = 0 comes from the query; `connected` means
`sinr_db ≥ -6.7` dB as computed by the simulator. Full definitions and the two
search strategies are in [planners/README.md](@ref scripts_baselines_planners).

| Term | Definition |
| --- | --- |
| Core | The largest connected component of all mesh nodes (ties: the one holding the smallest roster index). There is no gateway or root. |
| Coverage | The clipped-cell area of coverage-grid probes (at `coverage_probe_height_m`, receive gain `coverage_probe_rx_gain_dbi`) whose node-to-probe SINR is at least `coverage_sinr_db` for some core node. The probe areas sum to the geofence area (AOI). |
| Connectivity | `2 x AOI` per selected node outside the core. |
| Resilience | Vulnerability pairs: for each selected core node, the unordered core pairs its removal disconnects. Charged `AOI` per pair for `resilience`, `0.02 x AOI` for `balanced`, nothing for `coverage`. |
| Separation | A tie-break smaller than one coverage cell. |
| Movement | Per selected node, `0` at zero displacement, else `fixed_cost_m2 + cost_m2_per_m x d` from the node's original start, using its platform's keys. `max_displacement_m` is a hard cap. |

**Score = coverage + separation − movement − connectivity − resilience.**
Staying put is always a candidate and a valid result (zero displacement).

### Penalty scale

- Defaults: 150000 m² to move at all for either platform, then 500 m²/m
  (aerial) or 100 m²/m (ground).
- On a 400 m x 400 m AOI (160000 m²) the fixed cost alone is about 94 % of the
  area, so most nodes stay put.
- `planner.log` and the manifest record `aoi_m2` and `fixed_cost_m2 / aoi_m2`
  per platform. A ratio ≥ 1 (no coverage gain can pay for a move) is logged as
  a warning, not an error.
- For a zero-cost comparison, set the four `*_fixed_cost_m2` /
  `*_cost_m2_per_m` keys to `0`. Keep the cap keys absent, or at the same
  positive value, across compared runs.

## 5\. Evaluation requirements {#scripts_baselines_hold_executor}

In evaluation, a placement policy runs `hold` on every RL slot of a layout whose
selected nodes start at the plan. Preparation requires:

1. `[rl] controlled_nodes` is present (legacy single-node control is rejected).
2. The resolved `movable_nodes` set **equals** the resolved `controlled_nodes`
   set. `all` on either side means the whole roster, and order does not matter;
   RL slots keep the `controlled_nodes` order. A mismatch fails before any
   query and names both differences (movable but not controlled, controlled but
   not movable) with the fix: set both keys to the same ids, or `all`.
3. Every candidate and planned position lies in the evaluation region: the
   geofence rectangle intersected with the `[rl]` x/y bounds. An empty
   intersection fails preparation.

Consequences:

- No RL slot outside the plan is frozen by `hold`. Every node that is not
  RL-controlled is unselected and follows its scenario mobility under every
  policy.
- Letting some RL slots follow scenario mobility would need new simulator slot
  semantics and is not supported.
- Saved models are untouched. A model still needs the roster it was trained
  on, so pick `movable_nodes` to match its `controlled_nodes`.
- Standalone runs do not require matching RL slots: a moved node starts at the
  plan and then follows its configured mobility; unselected nodes are
  untouched.
- `ownership` in the manifest records both resolved lists.

## 6\. Channel scoring

**Inputs.** `preparation.prepare` stages the effective INI first and points the
query at it, with the source `nodes.json`. The query therefore builds the same
nodes, mobility models, buildings and jammers as the later run; candidate
positions come from each request. In evaluation the query gets `--rl-mode`,
matching the episode.

**Seeds.**

| Seed | Source |
| --- | --- |
| Planning (channel) seed | `--planning-seed`, then `[baseline] planning_seed`. No fallback to an evaluation seed. The jammer uses it too. |
| Optimizer proposals | `[baseline] seed` |
| `run_id` | `[scenario] run_id` |

- One frozen plan is reused across all evaluation seeds, so reordering them
  cannot select a different plan.
- Preparation and evaluation reject overlap between the planning seed and the
  evaluation seeds unless `--allow-seed-overlap` is given. The manifests record
  both roles and any overlap. Allowed overlap is an adaptation diagnostic and is
  excluded from held-out groups.
- The evaluation gate also checks training and model-selection seeds before
  launching a worker or episode.

**Parity** (see [the query contract](@ref src_query)):

- Every candidate goes through `LinkEvaluator::Evaluate` with the run's
  resolved band, gains, buildings and jammers.
- An ordinary run with the same planning seed and effective inputs has the same
  t = 0 realization; the real-binary parity checks test this. Evaluation seeds
  use other realizations.
- Scores are deterministic per layout. The per-pair random stream is not stable
  across layouts.

**Jammers.** Jammer power is added to the noise side of SINR on sub-6, with no
floor, so a strong enough jammer can push a link or a probe below the −6.7 dB
threshold and change connectivity and coverage. Capacity can also drop but is
not in the objective, and the planners do not steer away from jammers.

**Cost.** Each layout costs one full `EvaluateAll` plus N x G probe links
(G = coverage probes) in a forked child. `channel_scoring.queries` in the
manifest records the totals.

## 7\. What preparation does

1. Parse and validate `[baseline]`, the mapping file (or its defaults), and
   `nodes.json`. In evaluation, check ownership and the evaluation region
   (section 5). Resolve penalties, grids, probe settings, the planning seed and
   `run_id`. Record the binary, channel-runtime and adapted-code hashes.
2. Copy the INI and every file it references into `source-inputs/`.
3. Stage `effective-inputs.partial/`: the INI with `[baseline] algorithm =
   none`, `[scenario] nodes_file = nodes.json`, referenced files rebased to
   copied basenames, and, standalone only, `[rl] enabled = false`. Every other
   byte is kept. The source `nodes.json` is copied unchanged.
4. For an active method, run the strategy against a query worker on the staged
   INI and validate the result. Validation fails (it never clamps) on:
   - missing or extra ids, or non-finite values;
   - a selected node outside the rectangle (the boundary counts as inside);
   - a planned z that differs from the source z by more than 1e-6;
   - displacement beyond the platform's `*_max_displacement_m`;
   - an unselected node moved by more than 0.01 m;
   - in evaluation, a position outside the `[rl]` x/y bounds;
   - for a `random_walk` node, a position outside its own `random_walk.bounds`.
5. Rewrite selected nodes' start x/y in the staged `nodes.json` (z and all
   other nodes are written from the source; unmoved plans keep the source
   bytes), add `baseline-plan.json`, rename the folder to `effective-inputs/`
   once, and hash the result.
   - A selected `waypoint` node fails under `waypoint_policy = reject`; under
     `translate` its whole path shifts by the planned offset.
   - Any failure removes the staging folder.

## 8\. Outputs {#scripts_baselines_outputs}

### Standalone layout

`<run>` is `--output-dir`:

```
<run>/
  baseline_manifest.json
  planner.log               query command, scale check, planner notes and timing,
                            worker stderr, or "method none: no planner was run"
  sim.log                   simulator stdout and stderr
  source-inputs/            byte copies of the requested INI and its files
  effective-inputs/         run.ini nodes.json [assets] baseline-plan.json
  run.log  inputs/  seed-N/ written by the simulator, unchanged
```

- No `rl_episode.json` or `steps.jsonl` is written.
- The simulator archives every file beside the effective INI, so `inputs/` also
  holds `baseline-plan.json`.

### Evaluation layout

Evaluation adds `<eval-out>/<method>/baseline/` with the same preparation files
(no `sim.log`, no `seed-N/`), beside that policy's usual `episode-NNNN/`
folders.

For placement policies only, `eval_manifest.json` gains
`policies[<method>].baseline`: `baseline_manifest_version`, method, requested
algorithm, objective, executor, planner seed, `max_iterations`,
`planning_seed`, `ownership`, fingerprint, `initial_displacement_m_total`,
effective input hashes, the mapping hash, and paths to the baseline manifest
and plan. This block does not change `eval_manifest_version` (current value in
[Contributing](@ref Contributing)).

### Baseline manifest (`baseline_manifest.json`)

`baseline_manifest_version: 3`.

| Field | Meaning |
| --- | --- |
| `status` | `preparing` → `prepared` → `running` → `complete`, or `failed` / `interrupted` at any step. Evaluation stops at `prepared`; episode results live in `eval_manifest.json`. |
| `error` | Failure reason; for a simulator failure, its exit code and the tail of `sim.log`. |
| `seeds` | Standalone, one `{seed, status, summary}` per simulation seed: `complete` (with `seed-N/summary.json`), `missing`, or `failed` (no summary after a non-zero exit). |
| `method`, `requested_algorithm` | Effective method and the INI's `algorithm`. |
| `planner_seed`, `max_iterations` (+ `_status`) | Optimizer settings, separate from `simulation_seeds` and the planning seed. |
| `mapping_sha256`, `geofence` | Mapping file hash (`null` without one) and the resolved rectangle. |
| `sim_binary_sha256` | The binary that scored candidates; required for an active method. |
| `channel_runtime_sha256`, `channel_runtime_files` | Aggregate hash of the binary plus every resolved linked ns-3 library (the binary alone if none are dynamic), and the files hashed. |
| `planner_code_sha256` | Aggregate hash of every baseline Python owner outside tests, plus shared `artifact_io.py` and `sim_support.py`; new owners are discovered automatically. |
| `channel_scoring` | Query contract and isolation, planning seed, `planning_run_id`, `jammer_seed`, `mode_flag` (`--rl-mode` or `null`), band and source, link and coverage thresholds, probe (height, resolved receive gain, cells, cell size, count), candidate grid, and query totals. |
| `penalties` | Per-platform fixed, per-meter and cap values, `aoi_m2`, and `fixed_cost_over_aoi`. |
| `planner_settings` | Versioned resolved objective/component parameters, strategy settings, query budgets, grid/probe/cost settings and a settings hash. See [the engine configuration](planners/README.md#configuration-and-extension). |
| `seed_roles` | Dedicated planning seed/source, evaluation seeds, planning overlap, explicit allowance and held-out status. |
| `ownership` | `mode`, `movable_resolved`, and in evaluation `controlled_resolved` (slot order). |
| `fingerprint` | Hash (`fingerprint_version` 3) of method, objective, planner seed, `max_iterations`, waypoint policy, mapping hash, penalty/grid/probe/threshold settings, planning seed and `run_id`, mode flag, band, the four effective-input hashes, binary, channel-runtime and adapted-code hashes, `planner_settings`, and ownership; never timing or paths. `scripts.rl.compare` rejects a `--label` group whose placement fingerprints differ. |
| `initial_displacement_m_total` | Source-to-plan x/y relocation before reset. Exported beside scored `travel_m_total`; never added to it automatically. |

All paths are relative to the run folder, so a moved run stays readable.
`source_run_config_abs` and `channel_runtime_files` are informational absolute
paths.

### Plan file (`baseline-plan.json`)

`baseline_plan_version: 3`. Per node: id, roster index, RL slot (evaluation),
role (`movable` or `fixed`), platform, `selected`, `original` and `planned`
x/y/z, and `displacement_m`. It also holds the planner's diagnostics and score
breakdown as `planner_predictions`: the planner's t = 0 scores on the planning
seed. The run's own metrics are in its simulator outputs.

## 9\. Guards and limits

### Direct-binary guard

- A direct simulator run whose INI has `algorithm = geometric` or
  `optimization` exits 1 with a message pointing at this runner or at
  `scripts.rl.evaluate --policies`.
- `[rl] enabled = true` alone does not bypass the guard. Only the explicit
  `--rl-mode` flag does; the binary then prints one stderr notice and runs the
  **original** layout.
- `algorithm = none` or an absent section runs the scenario unchanged.
- Prepared effective INIs always carry `algorithm = none`, so they pass the
  guard.

### Planner limits

- Rectangle geofences only (section 3); flat ground at z = 0 only.
- Placement is 2-D: each node keeps its z, and a changed z fails validation.
- No periodic replanning, no 3D placement, no target following.
- Placement baselines set initial positions and then hold; they do not react to
  interference that starts later.
- Optimizer output is deterministic per seed, tested against the fake query
  worker on one machine. Determinism across platforms or numpy versions is not
  tested.

### Buildings as obstacles

With `[rl] avoid_buildings=true`, both planners exclude candidate destinations
inside configured buildings at the node's fixed altitude. Online movement masks
also reject swept paths through buildings. Initial placement is instantaneous:
the planners do not compute a travel route around obstacles.

### Node separation

With centralized `[rl] avoid_node_collisions=true`, planner requests carry
`minimum_separation_m=unsafe_separation_m`. Geometric candidate filtering,
optimization proposals and final layout checks enforce 3D pairwise separation,
and the setting is recorded in the planner settings. The default `0` leaves
planner behavior unchanged.

## 10\. Migrating from earlier versions

| Old | Now |
| --- | --- |
| `[baseline] gateway_node_id`, `rf_config` | Rejected as unknown keys with a hint; delete them. `[traffic] gateway_node_id` is unrelated and still used; its active gateway is excluded from selection. |
| Movement costs and caps in the RF file | The `[baseline]` cost keys (section 2). |
| Mapping files with `origin`, `ground_datum`, `radios` | Set `baseline_mapping_version` to 2 and delete those keys, or drop `mapping_file` to use `rl_bounds` and platforms by node type. |
| `baseline_manifest.json` / `baseline-plan.json` with `rf`, `planner_source`, `origin`, `ground_datum`, per-node `radios` | Version 3 removes these fields. |
| `--planner-source`, `$MESH_SIM_ARPO_PATH`, `requirements-baselines.txt` | Removed. |
| The first evaluation seed chose the plan | Supply a dedicated `planning_seed`, independent of evaluation seeds. |
| Programmatic entry points | Preparation: `scripts.baselines.preparation.prepare`. Mapping parsing: `scripts.baselines.mapping.load_mapping`. |
| Older evaluation results | Evaluation manifests from v5 and comparison output v2 carry planning-overlap and initial-relocation metadata; re-evaluate older results to get them. |
| Evaluation with `movable_nodes` a subset of `[rl] controlled_nodes` (version 1) | The two sets must be equal. Widen `movable_nodes` (or set both to `all`) or narrow `controlled_nodes`. Narrowing `controlled_nodes` changes the RL roster, so a saved model trained on the wider roster no longer applies. Standalone runs are unaffected. |

## 11\. Tests

```bash
.venv/bin/python -m pytest scripts/baselines/tests -q -rs
MESH_SIM_BIN=<BIN> .venv/bin/python -m pytest scripts/baselines/tests/test_real_binary.py -q
```

| Test or helper | Covers |
| --- | --- |
| `test_runner.py` | The runner, driven against `tests/fake_child.py`: a stand-in that checks argv and writes `seed-N/summary.json`, with failure and hang modes selected by `FAKE_CHILD_MODE`. |
| Planner and preparation tests | Score layouts with `tests/fake_query.py`, a stand-in channel-query worker with a distance-threshold channel and fault modes. |
| `test_provenance.py` | The reference hashes and the plan identity. |
| `test_real_binary.py` | On a real binary: the guard, the runner, evaluation (ownership equality, `--rl-mode` query parity, the gateway-free all-movable and partial-selection acceptance rows) and channel-query parity. Without `MESH_SIM_BIN`, each test is skipped with a reason starting `BLOCKED:`, meaning it did not run. |

Tests use only hand-written synthetic scenarios (`tests/conftest.py` and the
inline fixtures of `tests/test_real_binary.py`); no scenario is added under
`inputs/`.

## 12\. Module layout

| File | Owns |
| --- | --- |
| `config.py`, `mapping.py` | Strict baseline settings and simulator INI access; mapping/geofence validation. |
| `adapter.py` | Node records, platform mapping, datum/gateway/control authority and returned-plan validation. |
| `preparation.py` | Resolve planning inputs, call the solver, coordinate snapshots and manifest publication. |
| `solver.py` | `PlanRequest`/`PlanResult`; runs one strategy with a `ChannelScorer` and packages diagnostics, query statistics and timing. |
| `planners/` | The query client, shared objective and the two strategies; see [planners/README.md](@ref scripts_baselines_planners). |
| `effective_inputs.py` | Source snapshots, line-preserving INI edits, two-step staging of `effective-inputs/`, the `nodes.json` rewrite. |
| `artifacts.py` | Manifest/plan v3 schemas, status transitions and fingerprint fields. |
| `runtime_identity.py` | Planner/shared-source hashes and linked simulator-library provenance. |
| `runner.py`, `execution.py` | Argument parsing; standalone preparation and simulator child lifecycle. |

- No module here imports `scripts.rl.*`, Gymnasium, Torch or Stable-Baselines3.
- With `algorithm = none`, neither `solver.py` nor any `planners/` module is
  imported.
- `third_party/arpo_placement/` holds an unused reference copy; its
  `PROVENANCE.md` lists what was adapted and every deviation.

**What may be committed.** Only the nine reference files and `PROVENANCE.md`
under `third_party/arpo_placement/`. Never commit the supplied
`rf_config.yaml`, datasets, examples, payloads, weights, archives, generated
plans or run outputs, and nothing from `data/` or `outputs/`.
