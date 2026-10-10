@page scripts_baseline_inputs Placement input walkthrough
# Placement baselines

This guide connects the version 1 inputs to the baseline adapter and CLI.
See [the execution guide](README.md) for commands, ownership, and output formats.
The nine supplied algorithm files are preserved as reference source, with hashes
in [PROVENANCE.md](../../third_party/arpo_placement/PROVENANCE.md).

## Setup and a small configuration example

Run commands from `scratch/mesh-sim/`. For the existing RL environment, use
`python3 scripts/rl/bootstrap_venv.py`; install the separate planner dependencies
with `.venv/bin/python -m pip install -r requirements-baselines.txt` when working
with the supplied planners. Configuration and artifact modules use only the
Python standard library and can be exercised without those dependencies.

In a new local scenario directory, create `run.ini`:

```ini
[scenario]
seed = 1
duration_s = 10
warmup_s = 2
nodes_file = nodes.json

[traffic]
flow_topology = gateway
gateway_node_id = gw

[rl]
enabled = true
controlled_nodes = relay-a, relay-b
max_controlled_nodes = 2
action_profile = move_2d
x_min = 0
x_max = 400
y_min = 0
y_max = 400

[baseline]
algorithm = geometric
objective = coverage
application = initial_positions
gateway_node_id = gw
movable_nodes = relay-a, relay-b
mapping_file = mapping.json
rf_config = rf.yaml
seed = 7
max_iterations = 60
waypoint_policy = reject
```

Create `nodes.json`:

```json
[
  {"id": "gw", "node_type": "vehicle", "mobility": "fixed", "position": {"x": 200, "y": 200, "z": 2}},
  {"id": "relay-a", "node_type": "drone", "mobility": "fixed", "position": {"x": 150, "y": 180, "z": 30}},
  {"id": "relay-b", "node_type": "drone", "mobility": "fixed", "position": {"x": 170, "y": 140, "z": 30}}
]
```

Create `mapping.json` for this review's **version 1** format:

```json
{
  "baseline_mapping_version": 1,
  "origin": {"lat": 10, "lon": 20, "synthetic": true},
  "ground_datum": "z_is_agl_m",
  "geofence": {"source": "rl_bounds"},
  "radios": {"default": ["meshradio"]},
  "platforms": {"nodes": {"relay-a": "aerial", "relay-b": "aerial", "gw": "ground"}}
}
```

Check the baseline configuration and mapping, replacing `my-scenario` with that
directory's path:

```bash
python3 - <<'PY'
from scripts.baselines.config import load_baseline, read_ini, require_method
from scripts.baselines.mapping import load_mapping
cfg = load_baseline("my-scenario/run.ini")
require_method(cfg, cfg.algorithm)
mapping = load_mapping(cfg.mapping_file, read_ini(cfg.run_config))
print(cfg.algorithm, cfg.objective, cfg.movable_nodes)
print(mapping.rectangle)
PY
```

Expected: `geometric coverage ('relay-a', 'relay-b')` and a rectangle from 0 to
400 metres on both axes. This checks parsing, not simulator readiness or RF
availability. The adapter also needs a locally supplied `rf.yaml`
whose radio names match `radios`, plus the rest of the simulator's scenario
configuration. Private supplied RF files are not included in the repository.
The public, hand-written synthetic RF fixture in `tests/conftest.py` is used for
local tests; it is not a field calibration.

## Prepare, run, evaluate, and compare

After supplying that RF file and checking the scenario, inspect preparation
without starting the simulator. Use a fresh directory for each command:

```bash
.venv/bin/python - <<'PY'
from scripts.baselines.preparation import prepare
plan = prepare("my-scenario/run.ini", "geometric", "outputs/placement-preview",
               mode="standalone")
print(plan.manifest_path)
print(plan.plan_path)
print(plan.effective_run_config)
PY
```

Read `outputs/placement-preview/effective-inputs/baseline-plan.json`: compare
`original`, `planned`, `selected`, and `displacement_m` for each node. `gw`
stays fixed and both relays preserve z = 30. The source INI and nodes are
unchanged. Planning happens once; it is not an episode movement controller.

For a standalone run, replace `<BIN>` with an already-built mesh-sim binary.
The runner prepares again in its own fresh output directory, then starts it:

```bash
.venv/bin/python -m scripts.baselines.runner \
  --sim-binary <BIN> --run-config my-scenario/run.ini \
  --seeds 11,12 --output-dir outputs/placement-standalone
```

Inspect `baseline_manifest.json`, `sim.log`, and each `seed-N/summary.json`.
A failed/interrupted run keeps its evidence; correct the cause and choose a
fresh output directory to retry. The runner stops and reaps a launched child
even if writing its running status or waiting for it fails. If storage also
prevents recording the failure, stderr names that second error.

To evaluate without a saved model:

```bash
.venv/bin/python -m scripts.rl.evaluate \
  --sim-binary <BIN> --run-config my-scenario/run.ini \
  --seeds 11,12 --policies hold,random_valid,geometric,optimization \
  --output-dir outputs/placement-eval
```

Inspect `eval_manifest.json`, `<method>/baseline/baseline_manifest.json`, and
each policy's episode artifacts. Both placement methods use the same scored
window and hold their prepared positions. Their initial relocation cost is in
the `baseline` block; it is not a measured travel total during the episode.

The comparison command pairs a model with baselines. With an existing compatible
training run, replace `<TRAIN-RUN>` with its directory and choose evaluation
seeds outside its training and model-selection seeds:

```bash
.venv/bin/python -m scripts.rl.evaluate \
  --sim-binary <BIN> --run-dir <TRAIN-RUN> \
  --seeds 11,12 --policies model,hold,random_valid,geometric,optimization \
  --output-dir outputs/model-placement-eval
.venv/bin/python -m scripts.rl.compare \
  --eval-dirs outputs/model-placement-eval \
  --baselines hold,random_valid,geometric,optimization \
  --output-dir outputs/model-placement-comparison
```

The saved training scenario must have the baseline inputs above; its saved
observation/reward selection determines evaluation. Read `comparison.json`
and `episodes.csv` for measured, paired results and exclusions. A baseline-only
evaluation remains useful, but has no model for this comparison. One trained
run does not establish variability across independent training runs.

Choose `optimization` to use the optimizer; it requires `seed` and
`max_iterations`. `geometric` requires neither. Both require an objective,
gateway, explicit movable IDs, mapping, and RF path at this review point.
`algorithm = none` leaves placement unchanged and needs none of those extra
settings. Baseline seed controls planning; `[scenario] seed` controls simulation.
The active gateway stays out of both the movable list and RL control slots.
`movable_nodes = all` is rejected. Relative file paths resolve against the INI's
directory. Keys and sections are case-sensitive; use `[scenario]`, not
`[ scenario ]`. Duplicates, continuation lines, and `:` assignments are rejected.

## Coordinates and geofences

Scenario `x`, `y`, and `z` are metres. Placement updates x/y and preserves each
node's z. For waypoint nodes, the start is `waypoints[0]`; `reject` refuses a
moved waypoint node, while `translate` shifts its complete path by the start's
x/y displacement. Other node data stays intact.

The supplied source uses WGS84 latitude/longitude in degrees. Its
`core/geometry.py::LocalFrame` converts between those angles and a local
azimuthal-equidistant frame in metres. `to_xy(lat, lon)` returns `(x, y)`;
`to_latlon(x, y)` returns `(lat, lon)`. A synthetic origin provides a local
projection anchor, not a claim that the scenario is at that real location.
The version 1 mapping declares z as height above ground in metres.

The integration accepts only axis-aligned rectangles. `rl_bounds` requires all
four x/y bounds explicitly in `[rl]`; it does not use loader fallbacks.
Alternatively, `rectangle_xy_m` takes `x_min`, `x_max`, `y_min`, and `y_max` in the
mapping. Polygon fields are rejected, even though the supplied geometry code
can represent polygons. A polygon is never replaced with its bounding box.

## Reading the supplied algorithms

| Source | What it does |
| --- | --- |
| `models.py` | Defines the supplied planner's input/output records; these are separate from the simulator's nodes and traffic model. |
| `core/context.py` | Builds projected planning nodes, movement costs, link/connectivity checks, and coverage calculations. |
| `core/geometry.py` | Projects coordinates, repairs source polygons, samples grids, and computes bearings. Polygon repair is reference behavior, not supported mapping input here. |
| `core/rf.py` | Computes RF-based range estimates, including Friis calculations, for the supplied planners. |
| `planners/base.py` | Defines the supplied placement-model interface. |
| `planners/geometric.py` | Places movable nodes greedily using sampled candidates and connectivity requirements. |
| `planners/optimization.py` | Searches layouts with simulated annealing, starting from geometric/current candidates. |

The optimizer's `_Evaluator.score` measures connected coverage area, adds a
separation bonus, and subtracts movement, disconnection, and vulnerability
penalties. It does **not** optimize total delivered traffic demand. Coverage,
balanced, and resilience select different planner tradeoffs; accepting each
configuration does not prove that each algorithm improves a simulated network.
Delivered demand and delivery ratio must be measured by the simulator after
placement, with consistent warmup/scoring rules across compared runs.

[PR #25](https://github.com/ryanmccann1024/ns3-mmwave/pull/25) introduces simulator
channel queries, and [PR #26](https://github.com/ryanmccann1024/ns3-mmwave/pull/26)
uses them in the active planner ports. #26 replaces the RF/Friis runtime path,
removes the mandatory planner gateway, and migrates mapping to version 2.
Use that PR's migration guide for its configuration; the version 1 example
above belongs to this review. Keep explanations and adaptations outside the
nine pinned reference files so their source hashes remain meaningful.

## Adding an active baseline

For the active channel-based implementation in #26:

1. Add a method to `config.PLACEMENT_METHODS` and its applicable configuration
   validation. Keep method settings with their method owner.
2. Add `scripts/baselines/planners/<method>.py` implementing
   `solve(request, scorer, log)` and `settings(request)`. The method returns
   `(positions, diagnostics, notes)`, with an N-by-3 position array in roster
   order, a diagnostics object, and a list of notes. `solver.py` packages this
   into its `PlanResult`. Preserve node z and roster order, and respect selected
   nodes, movement bounds, and the channel scorer.
3. Update the adapter/evaluation accepted method names and required settings.
   The solver dispatch imports the method module; there is no single registry
   that automatically updates every caller.
4. Add focused valid/invalid configuration, plan-authority, and deterministic
   stub/channel tests. Exercise every supported objective, saved settings,
   failure status, and CLI selection; document the method and outputs.

Keep CLI work to argument parsing and delegation. Configuration checks belong
with config/mapping, plan checks with the adapter, search with the planner,
and schemas with the artifact owner. Reuse shared I/O rather than copying it.
Do not modify pinned supplied algorithms to add an active method. If changing
saved fields or their meanings, update readers, examples, and the appropriate
schema version together. Real-binary performance checks remain separate from
local parsing and fake-channel tests.

Run the local suite with `.venv/bin/python -m pytest scripts/baselines/tests -q -rs`.
See the [test map](tests/README.md) for what those checks establish.
