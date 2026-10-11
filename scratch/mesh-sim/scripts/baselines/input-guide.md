@page scripts_baseline_inputs Placement input walkthrough
# Placement baselines

This guide connects the version 2 inputs to the baseline adapter and CLI.
See [the execution guide](README.md) for commands, ownership, and output formats.
The nine supplied algorithm files are preserved as reference source, with hashes
in [PROVENANCE.md](../../third_party/arpo_placement/PROVENANCE.md).

## Setup and a small configuration example

Run commands from `scratch/mesh-sim/`. For the existing RL environment, use
`python3 scripts/rl/bootstrap_venv.py`. Active placement uses the simulator's
channel query and the existing NumPy dependency; configuration and artifact
modules use only the Python standard library.

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
movable_nodes = relay-a, relay-b
mapping_file = mapping.json
planning_seed = 701
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

Create `mapping.json` for this review's **version 2** format:

```json
{
  "baseline_mapping_version": 2,
  "geofence": {"source": "rl_bounds"},
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
400 metres on both axes. Parsing does not start the channel worker or establish
simulator readiness. The optional mapping classifies the gateway as ground;
without a mapping the adapter uses explicit RL bounds and classifies platforms from `node_type`.

## Prepare, run, evaluate, and compare

Use an already built binary. Planning launches its channel-query worker, then
writes source/effective snapshots and a plan before any episode starts. It is
initial 2D placement, not an episode movement controller. The active traffic
gateway stays out of both placement and RL control. `movable_nodes = all` is
accepted only when the entire roster is valid for both owners.

The [complete walkthrough](walkthrough.md) supplies committed inputs and exact
commands for training, zero-cost versus penalized evaluation, comparison,
standalone execution, artifact inspection and fetching matrix results. Keep
channel-planning, optimizer, training, model-selection and evaluation seeds
separate. Initial relocation and scored episode travel have separate fields;
do not silently add them together.

`optimization` requires an optimizer `seed` and `max_iterations`; `geometric`
uses neither. Both require an objective, movable IDs and a dedicated
`planning_seed`. Mapping is optional; there is no RF file or planner gateway.
`algorithm = none` leaves placement unchanged. Relative file paths resolve
against the INI directory. Keys and sections are case-sensitive; use
`[scenario]`, not `[ scenario ]`. Duplicates, continuation lines and `:`
assignments are rejected.

## Coordinates and geofences

Scenario `x`, `y`, and `z` are metres. Placement updates x/y and preserves each
node's z. For waypoint nodes, the start is `waypoints[0]`; `reject` refuses a
moved waypoint node, while `translate` shifts its complete path by the start's
x/y displacement. Other node data stays intact.

The read-only reference source uses WGS84 latitude/longitude and a local
projection. The active channel-scored port operates directly in scenario
meters, so mapping v2 has no origin, datum or radio fields.
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

The active port queries the simulator channel instead of the reference
RF/Friis path, has no mandatory planner gateway, and accepts mapping v2.
Keep explanations and adaptations outside the nine pinned reference files so
their source hashes remain meaningful.
## Adding an active baseline

For the active channel-based implementation:

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
