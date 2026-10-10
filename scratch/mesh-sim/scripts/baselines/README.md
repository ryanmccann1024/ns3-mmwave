@page scripts_baselines Placement baselines
# Placement baselines

`scripts/baselines/` runs the supplied geometric and optimization placement
planners once, before a simulation, and hands the simulator an ordinary
scenario whose selected nodes start at the planned positions. The simulator
binary never plans; it only reads the prepared inputs.

| File | Owns |
| --- | --- |
| `config.py` / `mapping.py` | Strict INI/options parsing / versioned mapping and geofence validation. |
| `adapter.py` | Node roles/platforms/radios, gateway authority, datum and result validation. |
| `preparation.py` | `prepare()`: coordinate input loading, planning, snapshots and preparation metadata. |
| `arpo_solver.py` | Planner source resolution, hashing, the import shim, projection, solving. The only module that imports the planner. |
| `effective_inputs.py` | Source snapshots, line-preserving INI edits, the `nodes.json` rewrite. |
| `artifacts.py` | `baseline_manifest.json` and `baseline-plan.json` schemas and status transitions. |
| `execution.py` | Standalone settings, simulator child lifecycle, seed results and failure recording. |
| `runner.py` | Parse CLI arguments and delegate to `execution.py`. |
| `../artifact_io.py` | Shared atomic JSON I/O, hashes and timestamps. |

RL placement setup lives in `scripts/rl/policy/evaluate.py`; experiment matrix
validation and execution live in `scripts/rl/policy/experiment.py`. CLI modules
delegate to those owners. The adapter's existing preparation imports remain
available for downstream callers.

No module here imports `scripts.rl.*`, Gymnasium, Torch, or Stable-Baselines3.
With `algorithm = none`, no planner module or planner dependency is imported.

## Setup

The planner needs four packages that are not in `requirements.txt`. Install
them once into the project environment:

```bash
.venv/bin/python -m pip install -r requirements-baselines.txt
```

Nothing installs them automatically. A missing package fails preparation with
one error naming every missing package and `requirements-baselines.txt`.

The planner source is the nine-file copy in `third_party/arpo_placement/`
(see its `PROVENANCE.md`). A different directory can be selected, in this
order: `--planner-source DIR` (standalone only), then `$MESH_SIM_ARPO_PATH`,
then the committed copy. All nine allowlisted files must be present. Loading
fails if a module named `models`, `core`, or `planners` is already imported
from somewhere else.

## Commands

Standalone: plan once, then run the ordinary (non-RL) simulator on the plan.

```bash
.venv/bin/python -m scripts.baselines.runner \
  --sim-binary <BIN> --run-config <INI> \
  [--seeds 1,2,3] [--algorithm none|geometric|optimization] [--output-dir DIR] \
  [--band mmwave|sub-6] [--planner-source DIR]
```

| Option | Default |
| --- | --- |
| `--algorithm` | `[baseline] algorithm`, else `none` |
| `--seeds` | `[scenario] seed` (the simulator's default, 42, when the key is absent). Accepts `A-B` ranges; the simulator receives the expanded comma list. |
| `--output-dir` | `outputs/YYYY-MM/DD/HH-MM-SS-baseline[-N]` under the mesh-sim root |
| `--band` | the scenario's band |

The output directory must be absent or empty; otherwise the runner exits 1
and writes nothing. Exit codes: `0` only when the run is `complete`; `1` for
an argument or preparation error, or when a seed has no `summary.json`; the
simulator's own exit code when it exits non-zero; `128 + signal` (130 for
SIGINT, 143 for SIGTERM) when interrupted.

Evaluation: the placement methods are two more policy names in
`scripts.rl.evaluate`, next to `model`, `hold`, and `random_valid`:

```bash
.venv/bin/python -m scripts.rl.evaluate \
  --sim-binary <BIN> --run-config <INI> \
  --output-dir <FRESH-EVAL-DIR> \
  --seeds 1,2 --policies hold,random_valid,geometric,optimization
```

The `--policies` default is still `model,hold,random_valid`. Every requested
placement method is prepared before any episode runs; a preparation failure
exits 1, runs no episode, and writes no `eval_manifest.json`. In evaluation the
policy name is the method; `[baseline] algorithm` is only recorded as
`requested_algorithm`.

## The `[baseline]` section

The C++ binary reads only `algorithm`. Everything else is read by
`config.py`, which rejects unknown keys, unknown values, duplicate sections or
keys, `:` assignments, and indented continuation lines. See also
[`src/config/run-ini-reference.md`](../../src/config/run-ini-reference.md).

| Key | Values | Default | Required when active |
| --- | --- | --- | --- |
| `algorithm` | `none`, `geometric`, `optimization` | `none` (also for an absent section or blank value) | — |
| `objective` | `coverage`, `balanced`, `resilience` | none | yes |
| `application` | `initial_positions` | `initial_positions` | no |
| `gateway_node_id` | one node id, not in `movable_nodes` | none | yes |
| `movable_nodes` | distinct comma list of node ids; `all` is rejected | none | yes |
| `seed` | integer ≥ 0; the planner seed, never a simulation seed | none | `optimization` |
| `max_iterations` | integer ≥ 1 | none | `optimization` |
| `waypoint_policy` | `reject`, `translate` | `reject` | no |
| `mapping_file` | path, relative to the INI | none | yes |
| `rf_config` | planner RF YAML, relative to the INI | none | yes |

`geometric` accepts `seed` and `max_iterations` so one INI can serve both
methods; the manifest records them as `null` with status `unused` /
`not_applicable`. Gateway and movable nodes are never inferred from
`[traffic]` or `[rl]`.

## Mapping file

JSON with exactly these top-level keys (`platforms` is optional):

```json
{
  "baseline_mapping_version": 1,
  "origin": {"lat": 0.0, "lon": 0.0, "synthetic": true},
  "ground_datum": "z_is_agl_m",
  "geofence": {"source": "rl_bounds"},
  "radios": {"default": ["<radio-type>"], "nodes": {"<node-id>": ["<radio-type>"]}},
  "platforms": {"nodes": {"<node-id>": "aerial"}}
}
```

| Field | Rule |
| --- | --- |
| `origin` | `lat` in [-80, 80], `lon` in [-180, 180]; `synthetic` (true/false) is required and recorded. Projection is azimuthal-equidistant about this point, x east, y north. |
| `ground_datum` | Only `z_is_agl_m`: z is metres above flat ground at z = 0. A node with z < 0 fails preparation. |
| `geofence` | `{"source": "rl_bounds"}` uses `[rl] x_min, x_max, y_min, y_max`, all four written in the INI (loader defaults are not used). `{"source": "rectangle_xy_m", "x_min": …, "x_max": …, "y_min": …, "y_max": …}` gives the rectangle directly. |
| `radios` | Every node needs a radio type from `nodes[id]` or `default`. Each type must exist in the RF file; a type marked `blos: true` is rejected. |
| `platforms` | Optional per-node `ground` or `aerial`. Otherwise `drone` is `aerial`, `vehicle` and `pedestrian` are `ground`. |

Planner roles: the gateway is a fixed `c2` node, each movable node is
`controlled`, and every other node is a fixed `relay` for planning only; its
simulator mobility is unchanged. Each node's altitude band is `[z, z]`.

## TODO: polygon geofences

The adapter supports **only an axis-aligned rectangle** in scenario metres. The
supplied planner can accept polygon geofences, but this adapter does not expose
that capability: it accepts no polygon vertices and does not derive a polygon
from buildings.

A polygon-shaped mapping request is rejected, not approximated. `config.py`
fails when `geofence` is a JSON list, when it has any of the keys `vertices`,
`polygon`, `polygons`, `points`, `coordinates`, `rings`, `holes`, `geojson`,
`exterior`, or `interiors`, or when an unknown `source` mentions `poly`,
`geojson`, `vert`, or `point`. The error ends with:

> only axis-aligned rectangle geofences are supported (geofence.source
> 'rl_bounds' or 'rectangle_xy_m'); polygon geofences are a documented TODO,
> and a bounding rectangle is never substituted

Do not work around this by writing the bounding rectangle of an irregular
permitted area. The planner would then be free to place nodes in the excluded
parts of that rectangle (a no-fly zone, a building footprint, water), and every
recorded check would still pass, so the run would appear to enforce a geofence
that it does not. Polygon support needs its own mapping schema, coordinate
conversion, containment checks on the result, boundary and hole semantics, and
tests.

## Direct-binary guard

A direct simulator run whose INI has `algorithm = geometric` or
`optimization` exits 1 with a message pointing at this runner or at
`scripts.rl.evaluate --policies`. `[rl] enabled = true` alone does not bypass
the guard; only the explicit `--rl-mode` flag does, and then the binary prints
one stderr notice and runs the **original** layout. `algorithm = none` or an
absent section behaves exactly as before. Prepared effective INIs always carry
`algorithm = none`, so they pass the guard. The binary does not see misspelled
`[baseline]` keys; the Python launchers reject them.

## Hold executor contract (evaluation)

Placement policies act as `hold` on a layout whose selected nodes start at the
plan. That only preserves the plan for nodes whose mobility the RL bridge
installs, so preparation requires:

1. `[rl] controlled_nodes` is present (legacy single-node control is rejected);
2. every id in `movable_nodes` is RL-controlled;
3. every planned position lies inside the `[rl]` x/y bounds.

An RL-controlled node that was not selected holds at its original start. A node
that is not RL-controlled follows its scenario mobility under every policy.
When `[traffic] flow_topology = gateway`, its `gateway_node_id` must be outside
both baseline selection and RL control. `controlled_nodes = all` is refused
for that topology. The version 1 planner's `[baseline] gateway_node_id` is a
separate, fixed planning anchor; it does not select the traffic gateway.
Standalone runs do not require RL control slots: a moved node starts at the
plan and then follows its configured mobility. The active traffic gateway
still cannot be selected.

The plan's `slot` records a controlled node's index in the centralized
control order for evaluation; it is `null` in standalone mode. Planner roles
and radio names describe planner inputs, not simulator traffic roles or radio
calibration. A random-walk node's initial placement must also fit its own
mobility bounds, because those bounds govern its movement after startup.

## What preparation does

1. Parse and validate `[baseline]`, the mapping file, and `nodes.json`.
2. Copy the INI and every file it references into `source-inputs/`.
3. For an active method, solve once and validate the result. Validation fails,
   and never clamps, on: missing or extra ids; non-finite values; a selected
   node outside the rectangle (the boundary counts as inside); a planned z that
   differs from the source z by more than 1e-6; displacement beyond the RF
   file's `max_displacement_m`; a gateway or unselected node moved by more than
   0.01 m; in evaluation, a position outside the `[rl]` bounds; for a
   `random_walk` node, a position outside its own `random_walk.bounds`.
4. Write `effective-inputs/`: the INI with `[baseline] algorithm = none`,
   `[scenario] nodes_file = nodes.json`, referenced files rebased to copied
   basenames, and, standalone only, `[rl] enabled = false`; every other byte is
   kept. Selected nodes' start x/y are rewritten; z and all other nodes are
   written from the source. A selected `waypoint` node fails under
   `waypoint_policy = reject`; under `translate` its whole path shifts by the
   planned offset.

One plan is reused for every simulation seed of a run.

## Outputs

Standalone (`<run>` is `--output-dir`):

```
<run>/
  baseline_manifest.json
  planner.log               planner output, or "method none: no planner was run"
  sim.log                   simulator stdout and stderr
  source-inputs/            byte copies of the requested INI and its files
  effective-inputs/         run.ini nodes.json [assets] baseline-plan.json
  run.log  inputs/  seed-N/ written by the simulator, unchanged
```

No `rl_episode.json` or `steps.jsonl` is written. The simulator archives every
file beside the effective INI, so `inputs/` also holds `baseline-plan.json`.

Evaluation adds `<eval-out>/<method>/baseline/` with the same preparation files
(no `sim.log`, no `seed-N/`), beside that policy's usual `episode-NNNN/`
directories. `eval_manifest.json` gains `policies[<method>].baseline` for
placement policies only: method, requested algorithm, objective, executor,
planner seed, `max_iterations`, fingerprint, `initial_displacement_m_total`,
effective input hashes, planner-source/RF/mapping hashes, and paths to the
baseline manifest and plan.

`baseline_manifest.json` (`baseline_manifest_version: 1`):

| Field | Meaning |
| --- | --- |
| `status` | `preparing` → `prepared` → `running` → `complete`, or `failed` / `interrupted` at any step. Evaluation stops at `prepared`; episode results live in `eval_manifest.json`. |
| `error` | Failure reason; for a simulator failure, its exit code and the tail of `sim.log`. |
| `seeds` | Standalone, one `{seed, status, summary}` per simulation seed: `complete` (with `seed-N/summary.json`), `missing`, or `failed` (no summary after a non-zero exit). |
| `method`, `requested_algorithm` | Effective method and the INI's `algorithm`. |
| `planner_seed`, `max_iterations` (+ `_status`) | Optimizer settings, separate from `simulation_seeds`. |
| `planner_source` | Origin, per-file SHA-256, and one aggregate hash. |
| `rf` | RF file hash, `planner` (radio specs and settings actually used), and `simulator_channel` (the INI's `[channel]` values and effective band). |
| `fingerprint` | Hash of method, objective, planner seed, `max_iterations`, waypoint policy, mapping/RF/source hashes, and the four effective-input hashes. `scripts.rl.compare` rejects a `--label` group whose placement fingerprints differ. |
| `initial_displacement_m_total` | Sum of planned x/y displacement before the first decision. This is a placement cost, separate from motion during the episode; this PR does not export an episode travel total. |

All paths are relative to the run directory, so a moved run stays readable;
`source_run_config_abs` is the one informational absolute path.
`baseline-plan.json` lists, per node, id, roster index, RL slot (evaluation),
role, platform, radios, `selected`, `original` and `planned` x/y/z, and
`displacement_m`, plus the planner's own diagnostics as `planner_predictions`.

Evaluation manifest version 3 uses scored facts at `time_s >= warmup_s`.
Decisions still run during warmup. Empty scored windows have zero reward and
null measured metrics. Use the same scoring window when comparing policies;
planning predictions cannot substitute for measured delivered demand.

## Planner limits

- Rectangle geofences only (see the TODO above); flat ground at z = 0 only.
- Placement is 2D. The altitude band is pinned to each node's z and a changed z
  fails validation.
- The supplied optimizer's `swap` move exchanges two nodes' positions **and
  altitudes**. When the selected nodes have different z, a swap can return a
  z that fails the unchanged-z check, and preparation fails; nothing is
  clamped. Selected nodes that share one z avoid it. The active planner ports
  in [PR #26](https://github.com/ryanmccann1024/ns3-mmwave/pull/26) replace this
  with x/y-only swaps; that downstream fix is not duplicated here.
- The planner seed does not follow the simulation seed. Same-machine
  determinism is tested; determinism across platforms or numpy versions is not
  claimed.
- Optimization can legitimately return the input layout; that is reported as
  zero displacement, not as a failure.
- No periodic replanning, no 3D placement, no target following.
- The planner's RF model (flat-earth free-space Friis ranges from the RF file)
  is not the simulator's channel model. The manifest records both side by side under
  `rf.planner` and `rf.simulator_channel`; no equivalence is claimed, and
  `planner_predictions` are predictions, not measurements.
  [PR #25](https://github.com/ryanmccann1024/ns3-mmwave/pull/25) adds simulator
  channel queries and PR #26 uses them instead of this RF/Friis runtime path.

## What may not be committed

Only the nine allowlisted planner source files and `PROVENANCE.md` under
`third_party/arpo_placement/` are authorized. Never commit the supplied
`rf_config.yaml` or any other supplied RF configuration, datasets, examples,
payloads, weights, archives, generated plans, or run outputs, and nothing from
`data/` or `outputs/`. Users pass their own `rf_config`. Tests use only the
hand-written synthetic scenario, mapping, and RF strings in
`tests/conftest.py`; no scenario is added under `inputs/`.

## Tests

```bash
.venv/bin/python -m pytest scripts/baselines/tests -q -rs
MESH_SIM_BIN=<BIN> .venv/bin/python -m pytest scripts/baselines/tests/test_real_binary.py -q
```

`test_runner.py` drives the runner against `tests/fake_child.py`, a stand-in
that checks argv and writes `seed-N/summary.json`, with failure and hang modes
selected by `FAKE_CHILD_MODE`. `test_real_binary.py` covers the guard, the
standalone runner, and the evaluation suite on a real binary; without
`MESH_SIM_BIN` each test is skipped with a reason starting `BLOCKED:`, which is
missing evidence, not a pass.

See [the worked input guide](input-guide.md) for a small configuration, coordinate
explanations, and active-planner extension steps.
