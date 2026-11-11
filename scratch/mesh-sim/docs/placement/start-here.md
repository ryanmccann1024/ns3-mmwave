# Placement baselines {#mesh_sim_placement_start}

[TOC]

What a placement baseline is, why Mesh-Sim has one, the terms this sequence
uses, and the five pages that take you from running one to writing your own.

## 1\. What a placement baseline does

A placement baseline picks better **starting positions** for some nodes, once,
before a simulation. Then it steps aside. The simulator runs the scenario with
those nodes moved and nothing else changed.

It does this by trying many candidate layouts and scoring each one with the
simulator's own radio model. The best-scoring layout becomes the **plan**.

## 2\. Why it exists

Mesh-Sim trains RL policies that move nodes during an episode. A trained
policy's numbers mean little on their own, so evaluation runs it beside
**baselines**: policies that do not learn, run on the same scenario and the
same seeds.

<!-- Policy comparison. Sources: scripts/rl/policy/evaluate.py (DEFAULT_POLICIES,
     PLACEMENT_POLICIES, placement_spec runs HoldPolicy), scripts/baselines/README.md.
     Styles: .ms-stack in theme/mesh-sim.css. -->
<div class="ms-stack">
<div class="ms-stack-row ms-stack-head"><div>Policy</div><div>What it does</div><div>What beating it shows</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer"><code>hold</code></div><div>Never moves anything.</div><div class="ms-stack-none"><span class="ms-stack-tag">Floor</span>Moving at all helps.</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer"><code>random_valid</code></div><div>Makes a random allowed move each decision.</div><div class="ms-stack-none"><span class="ms-stack-tag">Floor</span>The policy moves with purpose.</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer"><code>geometric</code></div><div>Plans starting positions once with a greedy search, then holds.</div><div class="ms-stack-replaced"><span class="ms-stack-tag">Placement baseline</span>Moving during the episode beats a careful one-time plan.</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer"><code>optimization</code></div><div>Same, with a longer annealing search.</div><div class="ms-stack-replaced"><span class="ms-stack-tag">Placement baseline</span>The same, against a stronger plan.</div></div>
<div class="ms-stack-row"><div class="ms-stack-layer"><code>model</code></div><div>The trained RL policy. Moves nodes every decision.</div><div class="ms-stack-same"><span class="ms-stack-tag">Under test</span>What every row above is measured against.</div></div>
</div>

`hold` and `random_valid` are easy to beat. The placement baselines are the
hard bar. If a trained policy cannot beat a plan made once at the start,
moving during the episode has not paid for itself.

You can also run a placement baseline on its own, with no RL at all, to get a
better-placed scenario.

**What it cannot do.** It plans x/y only; every node keeps its height. It
plans once, at t = 0, and never reacts to anything later, such as a jammer
switching on. It scores area coverage, not delivered traffic, so the
simulation decides whether the plan was actually better.

Background: \ref research_rl_placement_evolution "RL and placement evolution"
records how the design changed. Earlier versions had two movable UAVs, a
Friis range model and a gateway; today every movable peer is placed with the
simulator's own channel and no gateway.

## 3\. Terms used in this sequence

| Term | Meaning |
|---|---|
| **Movable node** | A node the planner may move, listed in `[baseline] movable_nodes`. Every other node stays exactly where the scenario puts it. |
| **Method** | The search: `geometric` or `optimization` today, set by `[baseline] algorithm`. `none` turns placement off. |
| **Objective** | What counts as a good layout: `coverage`, `balanced` or `resilience`. |
| **Score** | One number per layout, in m²: covered area, minus penalties for moving, for cut-off nodes and for fragile links. Higher is better. |
| **Channel query** | The simulator binary run with `--channel-query`. Python sends it candidate layouts and it returns SINR, links and coverage for each, using the same radio models as a real run. |
| **Planning seed** | `[baseline] planning_seed`: the random channel realization the planner scores against. Kept separate from the seeds the simulation runs, so a plan is never tuned to the run that judges it. |
| **Plan** | `baseline-plan.json`: original and planned position of every node, and the planner's score breakdown. |
| **Effective inputs** | The copy of the scenario that actually runs: the original files, with the movable nodes' start positions rewritten to the plan. |
| **Runner** | `scripts.baselines.runner`: plans, then runs the simulator on the effective inputs. |

## 4\. What you will do

1. \subpage mesh_sim_placement_run "Run a baseline": check a scenario's
   settings, plan it with both methods, and make the nodes move.
2. \subpage mesh_sim_placement_read "Understand the plan": read what the
   runner wrote, from the planner's log to the simulation's own results.
3. \subpage mesh_sim_placement_searches "How the two searches work": the
   score, and both searches worked through on the example, with figures.
4. \subpage mesh_sim_placement_code "How a plan is made": follow one plan
   through the code, module by module.
5. \subpage mesh_sim_placement_add "Add a baseline": write a new method,
   test it and run it.

Pages 1 and 2 need a built binary and the Python environment. Page 3 needs
nothing. Pages 4 and 5 are for changing the code.

## 5\. Going further

- \ref scripts_baselines "scripts/baselines": every `[baseline]` key, the
  mapping file, output files and manifest fields.
- \ref scripts_baselines_planners "scripts/baselines/planners": the exact
  score, both searches and every tuning setting.
- \ref src_query "Channel query": the contract between the planner and the
  binary.

Next: \ref mesh_sim_placement_run "Run a baseline"
