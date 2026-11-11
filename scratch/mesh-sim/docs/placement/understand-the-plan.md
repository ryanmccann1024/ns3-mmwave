# Understand the plan {#mesh_sim_placement_read}

[TOC]

What the runs from \ref mesh_sim_placement_run "Run a baseline" wrote, how to
read each file, and how to tell whether a plan helped. The numbers on this
page come from those runs.

<!-- Outputs from runs on 2026-10-28: mesh-sim commit b54bfbe7 plus the working
     tree, binary SHA-256 d7a2f4d1eb52c30abb0c6cecc8480aa29232afd12730fcc402caa0fc446c9fe2,
     folders scratch/mesh-sim/outputs/my-baselines/{geometric,geometric-zero-cost}.
     Planning seed 701, simulation seed 801. -->

## 1\. What the run wrote

Everything is under the `--output-dir` you passed, here
`outputs/my-baselines/geometric-zero-cost/`.

<!-- Output-folder figure. Styles: .ms-outtree in theme/mesh-sim.css.
     File list follows scripts/baselines/README.md section 8. -->
<div class="ms-outtree">
<div class="ms-ot-head"><span>File</span><span>What it holds</span><span>Written by</span></div>
<div class="ms-ot-row ms-ot-dir"><code>geometric-zero-cost/</code><span>The run folder: one per runner command.</span><span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>planner.log</code><span>Every planner decision, in plain text. <b>Check this first.</b></span><span><span class="ms-ot-tag ms-ot-plot">planner</span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>baseline_manifest.json</code><span>Status, settings, seeds, hashes and the plan's fingerprint.</span><span><span class="ms-ot-tag ms-ot-you">runner</span></span></div>
<div class="ms-ot-row ms-ot-l1 ms-ot-dir"><code>source-inputs/</code><span>Byte-for-byte copies of the <code>run.ini</code> you passed and its files.</span><span><span class="ms-ot-tag ms-ot-you">runner</span></span></div>
<div class="ms-ot-row ms-ot-l1 ms-ot-dir"><code>effective-inputs/</code><span>The scenario that actually ran.</span><span><span class="ms-ot-tag ms-ot-you">runner</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>run.ini</code><span>Your file with <code>algorithm = none</code> and <code>[rl] enabled = false</code>. Nothing else changes.</span><span><span class="ms-ot-tag ms-ot-you">runner</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>nodes.json</code><span>Your nodes with the movable ones' start x/y set to the plan.</span><span><span class="ms-ot-tag ms-ot-you">runner</span></span></div>
<div class="ms-ot-row ms-ot-l2"><code>baseline-plan.json</code><span>Original and planned position of every node, and the planner's score breakdown.</span><span><span class="ms-ot-tag ms-ot-plot">planner</span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>sim.log</code><span>The simulator's own output.</span><span><span class="ms-ot-tag ms-ot-viz">simulator</span></span></div>
<div class="ms-ot-row ms-ot-l1"><code>run.log</code>, <code>inputs/</code><span>The usual resolved settings and archived inputs.</span><span><span class="ms-ot-tag ms-ot-viz">simulator</span></span></div>
<div class="ms-ot-row ms-ot-l1 ms-ot-dir"><code>seed-801/</code><span>The usual per-seed results: <code>summary.json</code> and the CSVs.</span><span><span class="ms-ot-tag ms-ot-viz">simulator</span></span></div>
</div>

The runner never edits your scenario. It works on copies: `source-inputs/` is
what you gave it, `effective-inputs/` is what ran. The difference between them
is the plan:

```bash
diff <(python3 -m json.tool inputs/baselines/channel-scored-example/nodes.json) \
     <(python3 -m json.tool outputs/my-baselines/geometric-zero-cost/effective-inputs/nodes.json)
```

```
7,8c7,8
<             "x": 120.0,
<             "y": 120.0,
---
>             "x": 60.0,
>             "y": 60.0,
17,18c17,18
<             "x": 280.0,
<             "y": 120.0,
---
>             "x": 340.0,
>             "y": 60.0,
```

## 2\. Read planner.log first

```
method=geometric objective=balanced planner_seed=None max_iterations=None planning_seed=701 run_id=1 mode=standalone
aoi_m2=160000.0
ground fixed_cost_m2/aoi_m2=0.0000
aerial fixed_cost_m2/aoi_m2=0.0000
channel query: …/ns3.42-sim-debug --run-config=…/effective-inputs.partial/run.ini --channel-query --seed=701
Loading config: …/effective-inputs.partial/run.ini
geometric: air-a -> (60.000, 60.000) marginal 49.1697 m2
geometric: air-b -> (340.000, 60.000) marginal 64.8364 m2
note: geometric: 2/2 moved, score 160,295 m2-equivalent
queries={"layouts": 33, "links": 99, "probe_links": 9900, "requests": 13, "wall_s": 0.8678119610003705}
planner_wall_s=1.540
```

| Line | What it tells you |
|---|---|
| `method=... planning_seed=701 ...` | The settings the planner used. `planner_seed=None` because `geometric` has no randomness. |
| `aoi_m2=160000.0` | The area of interest: the 400 × 400 m rectangle nodes may use. Every score is in the same unit. |
| `fixed_cost_m2/aoi_m2` | What moving at all costs, as a fraction of the area. In the penalized run it is `0.9375`: moving costs 94% of the whole area, so a move almost never pays. At 1.0 or more the log adds a warning. |
| `channel query: ...` | The exact binary command that scored the layouts, with the planning seed. |
| `geometric: air-a -> (60, 60) marginal 49.17 m2` | `air-a` moved because the whole layout's score rose by 49.17 m². A node that does not improve the score `stays put`. |
| `queries={...}` | 33 layouts scored in 13 requests. Each layout costs one full link evaluation plus one link per node per coverage probe (3 × 100 = 300 here, so 9,900 in all). |

## 3\. Read the plan

`effective-inputs/baseline-plan.json` has one entry per node, in roster order:

```json
{"id": "air-a", "roster_index": 0, "slot": null, "role": "movable", "platform": "aerial",
 "selected": true, "original": {"x": 120.0, "y": 120.0, "z": 30.0},
 "planned": {"x": 60.0, "y": 60.0, "z": 30.0}, "displacement_m": 84.85}
{"id": "ground-peer", "roster_index": 2, "slot": null, "role": "fixed", "platform": "ground",
 "selected": false, "original": {"x": 200.0, "y": 280.0, "z": 1.5},
 "planned": {"x": 200.0, "y": 280.0, "z": 1.5}, "displacement_m": 0.0}
```

| Field | Meaning |
|---|---|
| `role`, `selected` | `movable` nodes may be moved; `fixed` ones never are. |
| `platform` | `aerial` or `ground`, from `node_type` (drones are aerial). It picks which movement-cost keys apply. |
| `original`, `planned` | Start position before and after planning, in meters. z never changes. |
| `displacement_m` | How far the node moved. Here √(60² + 60²) ≈ 84.9 m, inside the 100 m cap. |
| `slot` | The node's RL control slot. `null` in a standalone run. |

The same file holds `planner_predictions`, the planner's view of its own plan:

```json
"score": {
  "coverage_m2": 160000.0, "sep_m2": 295.03, "move_cost_m2": 0.0,
  "disconnected": 0, "vuln": 0, "total": 160295.03
},
"coverage_fraction": 1.0, "core": ["air-a", "air-b", "ground-peer"],
"survives_single_node_loss": true
```

## 4\. Read the score

The planner maximizes one number, in m²:

**score = coverage + separation − movement − connectivity − resilience**

| Term | This plan | What it is |
|---|---|---|
| coverage | 160,000 | Ground area where some connected node reaches a receiver at SINR ≥ −6.7 dB. Here: all of it. |
| separation | 295 | A small bonus for spreading nodes out, worth less than one coverage cell. |
| movement | 0 | 150,000 m² to move at all, plus 500 m² per meter, for each drone. Zero in this run. |
| connectivity | 0 | 2 × the area for each movable node cut off from the main group. |
| resilience | 0 | A charge for each pair of nodes that one node's loss would split. `balanced` weights it at 2% of the area. |

This explains both runs from the previous page:

- **Penalized.** The start layout already covered the full 160,000 m². No move
  could add coverage, and any move cost at least 150,000 m², so both drones
  stayed put.
- **Zero cost.** Coverage was still full, so the only term left to improve was
  separation. Spreading the drones raised it from 181 to 295 m². That is
  exactly the 49 + 65 m² in `planner.log`.

The three objectives differ only in how much they charge for fragile links:

| Objective | Resilience charge per fragile pair |
|---|---|
| `coverage` | 0 |
| `balanced` | 2% of the area |
| `resilience` | the whole area |

## 5\. Did the plan help?

The planner's score is a prediction at t = 0 on the planning seed (701). The
simulation runs seed 801 for 10 s. Only the simulation's own results say
whether the plan helped. Compare `seed-801/summary.json` from the two runs:

```bash
grep -A6 '"network"' outputs/my-baselines/geometric/seed-801/summary.json
grep -A6 '"network"' outputs/my-baselines/geometric-zero-cost/seed-801/summary.json
```

| | Penalized (stayed put) | Zero cost (moved apart) |
|---|---|---|
| Planner score | 160,181 m² | 160,295 m² |
| `connectivity` | 1.0 | 1.0 |
| `sum_throughput_mbps` | 30.0 | 30.0 |
| `mean_sinr_db` | 26.95 | 23.17 |

The plan the planner preferred **lowered** mean SINR by almost 4 dB: the
drones are farther from each other and from the ground peer. Traffic was
unaffected, since the three 10 Mbps flows fit either way.

Two lessons hold for every placement run:

- **The planner optimizes area coverage, not SINR or throughput.** A higher
  planner score is not a better network until the simulation says so.
- **Moving the start and moving during the episode are different costs.**
  `initial_displacement_m_total` in the manifest (here about 170 m) is the
  relocation before t = 0. It is never added to any travel measured during a
  run.

## 6\. Is this plan correct?

For any plan, check:

- `baseline_manifest.json` has `"status": "complete"`, and every entry in
  `seeds` is `complete`.
- In `baseline-plan.json`, every `fixed` node has `planned` equal to
  `original`, and no node's z changed.
- No `displacement_m` exceeds the platform's `*_max_displacement_m`.
- `seed_roles.held_out_from_planning` is `true`: the planning seed is not one
  of the simulation seeds.
- `planner.log` has no `planner scale warning` line you cannot explain.

The runner refuses a plan that breaks the second, third or fourth check, so a
`complete` run already passes them.

## 7\. Going further

- \ref scripts_baselines "scripts/baselines", section 8: every manifest and
  plan field, including the fingerprint that identifies a plan.
- \ref scripts_baselines_planners "scripts/baselines/planners": the exact
  definition of every score term.
- \ref mesh_sim_first_result "Understand the result": reading `summary.json`
  and the CSVs in `seed-801/`.

Previous: \ref mesh_sim_placement_run "Run a baseline" · Next: \ref mesh_sim_placement_searches "How the two searches work"
