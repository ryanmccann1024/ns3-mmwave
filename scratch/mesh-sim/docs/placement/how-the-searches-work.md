# How the two searches work {#mesh_sim_placement_searches}

[TOC]

How `geometric` and `optimization` choose a layout, worked through on the
example scenario from \ref mesh_sim_placement_run "Run a baseline": the score
each layout gets, every candidate the greedy search tries, and every proposal
the annealing search makes.

<!-- Every figure and number on this page comes from the real planner on
     inputs/baselines/channel-scored-example (planning seed 701) on 2026-10-28,
     mesh-sim commit b54bfbe7 plus the working tree, binary SHA-256
     d7a2f4d1eb52c30abb0c6cecc8480aa29232afd12730fcc402caa0fc446c9fe2.
     Figures: docs/diagrams/placement-search.py, which records every score and
     proposal the unmodified planner makes. -->

## 1\. What both searches see

\image html placement-setup.svg "The example scenario as the planner sees it. Left: the 400 × 400 m area split into 100 coverage cells, and the 16 positions each drone may move to inside its 100 m cap. Right: how many nodes reach each cell at the start."

Before searching, the planner lays two grids over the allowed area \f$A\f$
(here 160,000 m²):

- **Coverage probes.** The area is cut into square cells, and a receiver probe
  sits at each cell's center, 1.5 m above the ground. A probe stands for its
  cell's area.
- **Candidate positions.** The same kind of grid gives the positions a node may
  move to. A node's candidates are the grid points inside the area, inside any
  `[rl]` and random-walk bounds, outside buildings when `[rl] avoid_buildings`
  is on, and within its movement cap.

Both grids use the same cell size rule:

\f[ c = \max\!\left(r_{\min},\ \sqrt{A / N}\right) \f]

where \f$N\f$ is `coverage_grid_cells` (or `candidate_grid_cells`) and
\f$r_{\min}\f$ is `grid_min_resolution_m`. The example sets \f$N = 100\f$ and
\f$r_{\min} = 10\f$ m, so \f$c = \max(10, \sqrt{1600}) = 40\f$ m: a 10 × 10
grid. Each drone has 16 candidate points within 100 m.

The right panel shows why this example is hard to improve. Every cell is
already reached by all three nodes, so coverage is at its maximum before any
node moves.

## 2\. The score

Both searches maximize the same number for a layout \f$L\f$, in m²:

\f[ \text{score}(L) = C(L) + S(L) - M(L) - B\,D(L) - w\,V(L) \f]

The **core** is the largest group of nodes that can all reach each other. A
link counts when the channel reports SINR ≥ −6.7 dB. \f$\mathcal{M}\f$ is the
set of movable nodes.

| Term | Formula | Meaning |
|---|---|---|
| Coverage | \f$ C = \sum_{p} a_p \cdot [\exists\, n \in \text{core}: \text{SINR}_{n,p} \ge \theta] \f$ | Area of every probe \f$p\f$ (cell area \f$a_p\f$) that some core node reaches at SINR ≥ \f$\theta\f$ = `coverage_sinr_db`. |
| Separation | \f$ S = 0.4\,c^2 \cdot \frac{1}{\lvert\mathcal{M}\rvert} \sum_{i \in \mathcal{M}} \min\!\left(\frac{r_i}{D}, 1\right) \f$ | A tie-break for spreading out. \f$r_i\f$ is node \f$i\f$'s horizontal distance to its nearest neighbor; \f$D\f$ is the area's diagonal. Always below one cell's area. |
| Movement | \f$ M = \sum_{i \in \mathcal{M},\, d_i > 0} \left(F_i + k_i d_i\right) \f$ | \f$d_i\f$ is how far node \f$i\f$ moved from its start. \f$F\f$ is `*_fixed_cost_m2`, \f$k\f$ is `*_cost_m2_per_m`. |
| Connectivity | \f$ B = 2A \f$ per node in \f$D(L)\f$ | \f$D(L)\f$ counts movable nodes outside the core. Large enough that cutting a node off never pays. |
| Resilience | \f$ w \cdot V(L) \f$ | \f$V\f$ counts pairs of core nodes that losing one movable node would split. \f$w\f$ is 0, \f$0.02A\f$ or \f$A\f$ for `coverage`, `balanced`, `resilience`. |

**The start layout, by hand.** The diagonal is \f$D = \sqrt{400^2 + 400^2} =
565.7\f$ m. Each drone's nearest neighbor is the other drone, 160 m away, so:

\f[ S = 0.4 \times 40^2 \times \frac{160}{565.7} = 640 \times 0.283 = 181.0 \f]

Coverage is the whole area and nothing moved, so the score is
\f$160{,}000 + 181.0 = 160{,}181.0\f$ m², which is what the planner computed.

## 3\. geometric: one pass, one node at a time

`geometric` visits each movable node once, in `nodes.json` order. For each
node it:

1. **Builds the anchor pool:** the core's fixed nodes, plus the movable nodes
   it has already placed.
2. **Sets how many anchors the node should reach.** `coverage` asks for 1 per
   node and `resilience` for 2. `balanced` asks 2 of the first
   \f$\lceil n \times\f$ `balanced_core_fraction` \f$\rceil\f$ nodes, then 1.
   The need is capped at the pool size.
3. **Tries every candidate.** Each one is the current layout with only this
   node moved. Candidates that do not reach enough anchors are dropped, and
   every remaining layout gets a full channel query and a full score.
4. **Keeps the best**, but only if it raises the score by more than
   \f$10^{-6}\f$ m². Otherwise the node stays put.

\image html placement-geometric.svg "The two greedy steps on run-zero-cost.ini. Each dot is a candidate, colored by how much the whole score would change if the node moved there; the ring marks the one kept."

**Step 1, `air-a`.** With 2 movable nodes and the default fraction of 0.5,
`balanced` asks `air-a` for 2 anchors and `air-b` for 1. The pool holds only
`ground-peer`, so `air-a` needs 1. All 16 candidates reach it.

The best candidate is (60, 60), and only separation changes:

- `air-a`'s nearest neighbor is now `air-b` at 228.0 m.
- `air-b`'s nearest neighbor is now `ground-peer` at 178.9 m.

\f[ S = 640 \times \frac{1}{2}\left(\frac{228.0}{565.7} + \frac{178.9}{565.7}\right) = 230.2 \qquad \Delta = 230.2 - 181.0 = +49.2 \text{ m}^2 \f]

Candidates toward `air-b` bring the drones closer, so they score lower (red).
The worst is −65.6 m².

**Step 2, `air-b`.** `air-a` is now in the pool, at its new position. The best
candidate is (340, 60), where both drones' nearest neighbor is `ground-peer`
at 260.8 m. Separation rises to 295.0, a gain of +64.8 m². The final score is
160,295.0 m².

**The same steps with movement costs.** On `run.ini` every candidate also pays
for the move. `air-a`'s best is (100, 100), 28.3 m away:

\f[ \Delta = \underbrace{22.6}_{\text{separation}} - \underbrace{(150{,}000 + 500 \times 28.3)}_{\text{movement}} = -164{,}119.5 \text{ m}^2 \f]

That is the `best marginal -164120 m2` in `planner.log`. Every candidate
lowers the score, so both drones stay put.

**What it cannot do.** It visits each node once and never revisits an earlier
choice. It has no randomness: the same inputs always give the same plan.

## 4\. optimization: random proposals, cooled over time

`optimization` starts from the better of the `geometric` plan and the start
layout. Then, for each of `max_iterations` iterations \f$k\f$:

1. **Pick a move.** The weights are 0.55, 0.20 and 0.10, normalized to sum to 1:

   | Move | Chance | What it does |
   |---|---|---|
   | nudge | 0.647 | Move one random movable node by a random step of size \f$\sigma(k)\f$ in x and y. |
   | teleport | 0.235 | Move one node to a random **uncovered** probe, plus a little jitter. |
   | swap | 0.118 | Exchange two movable nodes' x/y. |

2. **Check it.** A node pushed past its cap is pulled back to 99.9% of the
   cap. A proposal that leaves the allowed area is **invalid**: it is dropped
   without a query.
3. **Score it** with a full channel query: \f$\Delta =
   \text{score}(\text{proposal}) - \text{score}(\text{current})\f$.
4. **Accept or reject:**

   \f[ P(\text{accept}) = \begin{cases} 1 & \Delta \ge 0 \\ e^{\Delta / T(k)} & \Delta < 0 \end{cases} \f]

5. **Remember the best layout seen.** That is what it returns, not the last
   one.

The temperature and step size both shrink as the search goes on. With
\f$K\f$ = `max_iterations` and \f$D\f$ the diagonal:

\f[ T(k) = T_0 \left(\frac{T_f}{T_0}\right)^{k/K}, \qquad T_0 = 0.02A,\ T_f = 0.0002A \f]

\f[ \sigma(k) = 0.08\,D \cdot 0.05^{\,k/K} + 2 \text{ m} \f]

Early on, a high \f$T\f$ accepts bad moves so the search can wander. Late, a
low \f$T\f$ accepts almost only improvements, and \f$\sigma\f$ makes the steps
small. The randomness comes only from `[baseline] seed`.

\image html placement-annealing.svg "optimization on run-zero-cost.ini, seed 201, 100 iterations. Top: the temperature. Middle: the nudge step size. Bottom: the score of every proposal, the current layout and the best layout seen."

**Iteration 1, by hand.** The first proposal is a swap. Each drone is pulled
back to 99.9 m from its own start, and the layout scores 160,037.1 m²:

\f[ \Delta = 160{,}037.1 - 160{,}295.0 = -258.0, \qquad P = e^{-258.0 / 3200} = 0.92 \f]

It is accepted, even though it is worse.

**What the figure shows.**

- 80 of the 83 scored proposals were accepted. In this example, layouts differ
  only by separation, a few hundred m² at most. That is small next to \f$T\f$,
  which starts at 3,200 m² and only falls to 32. The search therefore wanders
  like a random walk.
- No proposal beat the starting `geometric` plan, so that is what it returns.
  Keeping the best is what stops a wandering search from returning something
  worse.
- All 17 teleports were invalid: every probe is already covered, so there is
  nowhere to teleport to.

**The same search with movement costs.** On `run.ini` every move costs at
least 150,000 m². Then \f$P = e^{-164{,}000/3200} \approx e^{-51}\f$, which is
effectively zero. That is why the penalized run on
\ref mesh_sim_placement_run "Run a baseline" logged `accepts=0`.

## 5\. Which one to use

| | `geometric` | `optimization` |
|---|---|---|
| Search | One greedy pass over a fixed grid | Starts from `geometric`, then random proposals anywhere in the area |
| Randomness | None | `[baseline] seed` |
| Can revisit a node | No | Yes |
| Can do worse than `geometric` | — | No: it starts from `geometric` and keeps the best |
| Layouts scored here | 33 | 118 (33 from `geometric`, 2 to compare, 83 proposals) |
| Result here | 160,295 m² | 160,295 m², the same plan |

Use `geometric` for a fast, repeatable plan. Use `optimization` when the
grid is coarse or nodes interact strongly, so that moving off the grid points
or revisiting an earlier node could help. Always judge the result by the
simulation, as on \ref mesh_sim_placement_read "Understand the plan".

## 6\. Change the search yourself

The searches read optional sections in `run.ini`; you do not need to change
any code:

| To | Set |
|---|---|
| Use a finer candidate grid | `[baseline] candidate_grid_cells` |
| Start colder, so fewer bad moves are accepted | `[placement_optimizer] t0_area_frac` |
| Change how likely each move is | `[placement_optimizer] move_weights = {"nudge": 0.7, "teleport": 0.1, "swap": 0.2}` |
| Anneal from the start layout instead of `geometric` | `[placement_optimizer] warm_start = current` |
| Make resilience count more or less | `[placement_objective] vulnerability_aoi_factor` |

Every key and its limits are in \ref scripts_baselines_planners "the planners
page". To redraw the figures on this page after a change, from `docs/`:

```bash
../.venv/bin/python diagrams/placement-search.py --sim-binary "$SIM_BIN"
```

**Checkpoint:** it prints `wrote docs/diagrams/placement-setup.svg` and the
other two figures. The recorded data goes to
`outputs/docs-figures/placement-search/`.

## 7\. Going further

- \ref scripts_baselines_planners "scripts/baselines/planners": the exact
  rules, including tie-breaks, the anchor fallback and how this differs from
  the original planners.
- \ref mesh_sim_placement_code "How a plan is made": where each step lives in
  the code.
- \ref mesh_sim_placement_add "Add a baseline": write a third search.

Previous: \ref mesh_sim_placement_read "Understand the plan" · Next: \ref mesh_sim_placement_code "How a plan is made"
