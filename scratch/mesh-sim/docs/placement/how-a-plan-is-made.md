# How a plan is made {#mesh_sim_placement_code}

[TOC]

Follow one runner command through the code, stage by stage, so you know which
file to open for any placement change. Every file named here is under
`scratch/mesh-sim/scripts/baselines/` unless the path says otherwise.

<!-- Source-inspected 2026-10-28 at mesh-sim commit b54bfbe7 plus the working
     tree: runner.py, execution.py, preparation.py, config.py, mapping.py,
     adapter.py, effective_inputs.py, solver.py, planner_config.py, planners/*,
     artifacts.py, runtime_identity.py, scripts/rl/policy/evaluate.py. -->

## 1\. The five stages

\htmlonly
<div class="ms-gates">
<div class="ms-gate"><strong>1. Settings</strong><span>read and check</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>2. Copy</strong><span>stage the inputs</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>3. Search</strong><span>score layouts</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>4. Check</strong><span>validate and save</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate ms-gate-end"><strong>5. Run</strong><span>the simulator</span></div>
</div>
\endhtmlonly

`runner.py` only parses arguments. `execution.py` owns the run folder, the
seed list and the simulator child process. Between them,
`preparation.prepare` drives stages 1–4 and updates `baseline_manifest.json`
after each one. If any stage fails, the manifest says `failed` with the
reason, and the staging folder is removed.

## 2\. Settings

| File | What it does |
|---|---|
| `config.py` | Reads `[baseline]` strictly: unknown keys, bad values, duplicate keys and `:` assignments all fail. `require_method` checks the keys each method needs. Holds `PLACEMENT_METHODS`, the list of method names. |
| `mapping.py` | Works out where nodes may go: the `[rl]` x/y bounds, or a mapping file's rectangle. Refuses polygons rather than approximating them. |
| `adapter.py` | Turns `nodes.json` into node records with a platform (aerial or ground). Checks that the traffic gateway is not movable, and in evaluation that the movable nodes equal the RL-controlled nodes. |

Nothing has launched yet, so mistakes here cost nothing. This is the stage
the settings check on \ref mesh_sim_placement_run "Run a baseline" runs on
its own.

## 3\. Copy

`effective_inputs.py` copies your `run.ini` and every file it names into
`source-inputs/`, then stages `effective-inputs.partial/`. The staged
`run.ini` gets `algorithm = none`, and in a standalone run
`[rl] enabled = false`. Every other byte stays the same.

The channel query in the next stage loads this staged file. It therefore
builds exactly the nodes, buildings and jammers the real run will.

## 4\. Search

This stage runs only for an active method; with `none`, none of these modules
is even imported.

```
solver.solve(request, log)
   ├─ planner_config.py         read the optional [placement_*] tuning sections
   ├─ planners/channel.py       start "<BIN> --channel-query --seed=<planning seed>"
   ├─ planners/objective.py     prepare_scorer: send the coverage probe grid
   └─ planners/<method>.py      solve(): THE SEARCH
          │  builds candidate layouts, sends them to the channel query,
          │  scores each with objective.score(), keeps the best
          └─ returns positions, diagnostics, notes
   <- PlanResult: positions, predictions, settings + hash, query stats
```

| File | What it owns |
|---|---|
| `solver.py` | `PlanRequest` (everything a search needs), `PlanResult`, and `STRATEGIES`, which maps each method name to `planners/<name>.py`. |
| `planners/channel.py` | `ChannelScorer`, the only code that talks to the binary: start-up check, batching, timeouts, cleanup. |
| `planners/objective.py` | The score, the candidate and coverage grids, and the helpers every search uses. |
| `planners/components.py` | The individual score terms, each with its own parameters and version. |
| `planners/graph.py` | Connected groups and which single node loss would split them. |
| `planners/cache.py` | Remembers scored layouts so a search never pays twice for the same one. |
| `planners/geometric.py`, `planners/optimization.py` | The two searches. |

The two searches:

- **`geometric`** visits each movable node once, in `nodes.json` order. For
  each one it scores every candidate-grid point within reach and keeps the
  best, but only if the whole layout's score rises. Otherwise the node stays
  put. It has no randomness.
- **`optimization`** starts from the `geometric` plan, or from the start
  layout if that scores higher. It then makes `max_iterations` random
  proposals: nudge one node, teleport one to an uncovered spot, or swap two.
  It accepts by simulated annealing and returns the best layout it saw. Its
  randomness comes only from `[baseline] seed`.

\ref mesh_sim_placement_searches "How the two searches work" walks through both on
the example, and \ref scripts_baselines_planners "the planners page" has the
full rules.

## 5\. Check

`adapter.validate_result` checks the returned plan and **refuses** it rather
than fixing it. A plan fails if it:

- misses or adds a node, or has a non-finite number;
- puts a movable node outside the allowed area (or, in evaluation, outside the
  `[rl]` bounds or the node's own random-walk bounds);
- changes any node's z;
- moves a node farther than its platform's cap;
- moves a fixed node by more than 0.01 m.

Then `effective_inputs.py` rewrites the movable nodes' start x/y in the staged
`nodes.json` and renames the folder to `effective-inputs/`. `artifacts.py`
writes `baseline-plan.json` and marks the manifest `prepared`.
`runtime_identity.py` records hashes of the planner code and the binary, so
two plans can be told apart.

## 6\. Run

`execution.py` runs the binary on `effective-inputs/run.ini` with the
simulation seeds, captures `sim.log`, and marks the manifest `complete`.
The binary sees an ordinary scenario. It has no idea a planner was involved.

A direct binary run on a file that says `algorithm = geometric` stops with an
error. The binary checks the value but never plans, so it points you to the
runner instead.

## 7\. The same plan in evaluation

`scripts.rl.evaluate --policies geometric,optimization` takes another way in.
`prepare_placements` in `scripts/rl/policy/evaluate.py` calls the same
`preparation.prepare` in `evaluation` mode, once per method, before any
episode runs. Each placement policy is then the `hold` policy, run on its
effective inputs. Stages 1–4 are identical; stage 6 is replaced by RL
episodes. See \ref mesh_sim_rl_start "Reinforcement learning".

## 8\. Rules that hold everywhere

- Every candidate layout is scored by a full channel query on the planning
  seed. There are no shortcuts that re-score only the links that changed: the
  channel's random draws depend on the order links are evaluated in.
- The planning seed is never one of the simulation seeds, unless you pass
  `--allow-seed-overlap`, and then the run is marked as not held out.
- Nothing in `scripts/baselines/` imports `scripts.rl`. The RL side calls in;
  placement never calls out.
- Initial relocation, the distance moved to reach the plan, is kept separate
  from any travel measured during a run.

## 9\. Where the algorithms came from

Both searches are adapted from the geometric and optimization planners of the
ARPO network optimization model. Its nine source files are kept, byte for
byte and never imported, in `third_party/arpo_placement/`.
`tests/test_provenance.py` checks their hashes, and `PROVENANCE.md` there
records the authorization and every deviation.

The main differences from the original:

| Original | Here |
|---|---|
| Friis range model | The simulator's own channel |
| A gateway every node must reach | No gateway; the largest connected group |
| Altitude moves | x/y only |
| A time budget | `max_iterations` |

Change behavior in `scripts/baselines/`, never in `third_party/`.

## 10\. Going further

- \ref scripts_baselines "scripts/baselines", section 12: the module table,
  and section 11: the tests.
- \ref scripts_baselines_planners "scripts/baselines/planners": the engine,
  its settings and the full comparison with the original.
- \ref src_query "Channel query": the binary's side of stage 3.

Previous: \ref mesh_sim_placement_searches "How the two searches work" · Next: \ref mesh_sim_placement_add "Add a baseline"
