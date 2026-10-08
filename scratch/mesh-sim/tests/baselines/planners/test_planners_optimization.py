"""Annealing edges: schedule formulas, keep-best, seed choice, determinism, iteration bounds,
clamping and the move rules, with in-process and fake_query.py scorers.
"""

import json
import math
import types

import numpy as np
import pytest

from scripts.baselines.planners import geometric, optimization
from scripts.baselines.planners.channel import PlannerError
from scripts.baselines.planners.objective import (LayoutScore, MovementCost, ScoringContext,
                                                  prepare_scorer, score)
from scripts.baselines.tests.test_objective import (AOI, REFERENCE, ZERO,
                                                    assert_plan_invariants, entry,
                                                    make_request, planning_scorer,
                                                    pure_context)

from ._planner_support import DistanceScorer

DIAG = math.hypot(400.0, 400.0)
MIXED = [entry("F", 200.0, 200.0, 2.0, "vehicle"), entry("A", 210.0, 200.0, 10.0),
         entry("P", 190.0, 200.0, 1.5, "pedestrian")]
SPREAD = [entry("F", 200.0, 200.0, 2.0, "vehicle"), entry("A", 120.0, 150.0, 10.0),
          entry("B", 280.0, 260.0, 10.0), entry("P", 230.0, 120.0, 1.5, "pedestrian")]


class _Log:
    def write(self, text):
        pass

    def flush(self):
        pass


def _marking_geometric(monkeypatch, marker: dict):
    """Wrap geometric.solve to remember how many evaluate() calls the warm start used."""
    original = geometric.solve

    def wrapped(request, scorer, log):
        out = original(request, scorer, log)
        marker["calls"] = len(scorer.calls)
        marker["layouts"] = len(scorer.layouts)
        return out
    monkeypatch.setattr(geometric, "solve", wrapped)


def _run(entries, movable, scorer=None, **kwargs):
    kwargs.setdefault("max_iterations", 30)
    request = make_request(entries, movable, method="optimization", **kwargs)
    scorer = scorer or DistanceScorer()
    prepare_scorer(request, scorer)
    positions, diagnostics, notes = optimization.solve(request, scorer, _Log())
    json.dumps(diagnostics)
    assert_plan_invariants(request, positions)
    return request, scorer, positions, diagnostics, notes


# ---------------------------------------------------------------------------------------
# Iteration bounds.

@pytest.mark.parametrize("iterations", [0, -3])
def test_non_positive_max_iterations_fail_before_any_query(iterations):
    request = make_request(MIXED, {"A"}, method="optimization", max_iterations=iterations)
    scorer = DistanceScorer()
    prepare_scorer(request, scorer)
    with pytest.raises(PlannerError, match="max_iterations"):
        optimization.solve(request, scorer, _Log())
    assert scorer.calls == []


def test_single_iteration_run_accounts_for_every_query(monkeypatch):
    marker = {}
    _marking_geometric(monkeypatch, marker)
    _, scorer, _, diagnostics, notes = _run(SPREAD, {"A", "B", "P"}, max_iterations=1,
                                            planner_seed=4)
    sa = diagnostics["optimization"]
    assert sa["iterations"] == 1
    assert sa["queried_proposals"] + sa["rejected_proposals"] == 1
    assert len(scorer.layouts) == marker["layouts"] + 2 + sa["queried_proposals"]
    assert [len(call) for call in scorer.calls[marker["calls"]:]] == \
        [2] + [1] * sa["queried_proposals"]
    assert notes[-1].startswith("sa iters=1 ")


def test_layout_accounting_through_the_fake_worker(tmp_path, monkeypatch):
    request = make_request(SPREAD, {"A", "B", "P"}, method="optimization", max_iterations=15,
                           planner_seed=8)
    with planning_scorer(tmp_path, monkeypatch, SPREAD, request) as (scorer, log):
        positions, diagnostics, _ = optimization.solve(request, scorer, log)
        stats = scorer.stats
    steps = diagnostics["geometric"]["steps"]
    sa = diagnostics["optimization"]
    assert stats["layouts"] == (1 + sum(s["candidates"] for s in steps) + 2 +
                                sa["queried_proposals"])
    assert sa["queried_proposals"] + sa["rejected_proposals"] == sa["iterations"] == 15
    assert_plan_invariants(request, positions)


# ---------------------------------------------------------------------------------------
# Seed choice and keep-best.

def test_tie_between_greedy_and_start_goes_to_greedy():
    _, _, positions, diagnostics, _ = _run(MIXED, {"A", "P"}, penalties=REFERENCE,
                                           max_iterations=3)
    sa = diagnostics["optimization"]
    assert sa["geometric_total"] == sa["current_total"]
    assert sa["seed_layout"] == "geometric"


def test_better_start_layout_seeds_the_anneal(monkeypatch):
    def bad_greedy(request, scorer, log):
        layout = np.array([[n.x, n.y, n.z] for n in request.nodes], dtype=float)
        layout[1, :2] = [10.0, 390.0]   # A far from everyone: BIG penalty
        return layout, {"geometric": {"steps": [], "start_total": 0.0}}, ["bad"]
    monkeypatch.setattr(geometric, "solve", bad_greedy)
    _, _, positions, diagnostics, notes = _run(MIXED, {"A"}, max_iterations=5,
                                               planner_seed=2)
    sa = diagnostics["optimization"]
    assert sa["seed_layout"] == "current"
    assert sa["current_total"] > sa["geometric_total"] + AOI
    assert sa["best_total"] >= sa["current_total"]
    assert notes[0] == "bad" and "(seed: current)" in notes[-1]
    assert positions[1].tolist() != [10.0, 390.0, 10.0]


@pytest.mark.parametrize("objective", ["coverage", "resilience"])
def test_returns_the_best_layout_ever_queried(monkeypatch, objective):
    marker = {}
    _marking_geometric(monkeypatch, marker)
    caps = {"aerial": MovementCost(0.0, 0.0, 120.0), "ground": MovementCost(0.0, 0.0, 120.0)}
    request, scorer, positions, diagnostics, _ = _run(
        SPREAD, {"A", "B", "P"}, objective=objective, penalties=caps, max_iterations=40,
        planner_seed=5)
    ctx = ScoringContext.build(request, scorer)
    totals = [score(ctx, result, layout).total
              for call in scorer.calls[marker["calls"]:] for layout, result in call]
    sa = diagnostics["optimization"]
    # A proposal above the best is above the current layout too, so it is always accepted.
    assert sa["best_total"] == pytest.approx(max(totals))
    assert sa["best_total"] >= max(sa["geometric_total"], sa["current_total"])
    again = score(ctx, scorer.result(positions), positions)
    assert again.total == pytest.approx(sa["best_total"])
    assert diagnostics["score"]["total"] == sa["best_total"]
    for k in ctx.selected:
        assert ctx.displacement(k, positions[k]) <= 120.0


# ---------------------------------------------------------------------------------------
# Determinism.

def test_same_seed_replays_every_query_and_other_seed_differs(monkeypatch):
    runs = {}
    for label, seed in (("a", 11), ("b", 11), ("c", 12)):
        marker = {}
        _marking_geometric(monkeypatch, marker)
        _, scorer, positions, diagnostics, _ = _run(SPREAD, {"A", "B", "P"},
                                                    planner_seed=seed, max_iterations=25)
        runs[label] = (scorer.layouts, marker["layouts"], positions, diagnostics)
    (la, ma, pa, da), (lb, _, pb, db), (lc, mc, _, _) = runs["a"], runs["b"], runs["c"]
    assert len(la) == len(lb) and all(np.array_equal(x, y) for x, y in zip(la, lb))
    assert np.array_equal(pa, pb) and da == db
    assert ma == mc  # the greedy warm start does not depend on the planner seed
    sa_a, sa_c = la[ma:], lc[mc:]
    assert len(sa_a) != len(sa_c) or not all(np.array_equal(x, y)
                                             for x, y in zip(sa_a, sa_c))


# ---------------------------------------------------------------------------------------
# Schedule: T = T0 (Tf/T0)^frac, sigma = 0.08 diag 0.05^frac + 2, frac = it / max_iterations.

def test_temperature_and_sigma_schedule(monkeypatch):
    iterations = 5
    sigmas, exp_args = [], []
    start = np.array([[n["position"]["x"], n["position"]["y"], n["position"]["z"]]
                      for n in MIXED])
    moved = start.copy()
    moved[1, 0] += 1.0

    def fake_greedy(request, scorer, log):
        return start.copy(), {"geometric": {"steps": [], "start_total": 0.0}}, []

    def fake_propose(ctx, rng, layout, covered, move, sigma):
        sigmas.append(sigma)
        return moved.copy()

    def fake_score(ctx, result, layout):
        total = 0.0 if np.array_equal(layout, start) else -1000.0
        return LayoutScore(0.0, 0.0, 0.0, 0, 0, total)

    def fake_exp(value):
        exp_args.append(value)
        return 0.0          # never accept the worse proposal

    monkeypatch.setattr(geometric, "solve", fake_greedy)
    monkeypatch.setattr(optimization, "propose", fake_propose)
    monkeypatch.setattr(optimization, "score", fake_score)
    monkeypatch.setattr(optimization, "math", types.SimpleNamespace(exp=fake_exp))
    _, scorer, positions, diagnostics, _ = _run(MIXED, {"A"}, max_iterations=iterations)
    t0, tf = 0.02 * AOI, 0.0002 * AOI
    fracs = [k / iterations for k in range(iterations)]
    assert sigmas == pytest.approx([0.08 * DIAG * 0.05 ** f + 2.0 for f in fracs])
    assert exp_args == pytest.approx([-1000.0 / (t0 * (tf / t0) ** f) for f in fracs])
    sa = diagnostics["optimization"]
    assert (sa["iterations"], sa["accepted"], sa["queried_proposals"]) == (5, 0, 5)
    assert np.array_equal(positions, start) and sa["best_total"] == 0.0


def test_rejected_proposals_are_never_queried(monkeypatch):
    marker = {}
    _marking_geometric(monkeypatch, marker)
    monkeypatch.setattr(optimization, "propose", lambda *args: None)
    _, scorer, _, diagnostics, _ = _run(MIXED, {"A", "P"}, max_iterations=12)
    sa = diagnostics["optimization"]
    assert (sa["rejected_proposals"], sa["queried_proposals"], sa["accepted"]) == (12, 0, 0)
    assert len(scorer.layouts) == marker["layouts"] + 2


# ---------------------------------------------------------------------------------------
# Clamp and move rules.

def _capped(cap=50.0, nodes=None):
    nodes = nodes or [entry("A", 100.0, 100.0, 10.0), entry("F", 300.0, 300.0, 2.0, "vehicle")]
    return pure_context(nodes, {"A"}, penalties={"aerial": MovementCost(0.0, 0.0, cap),
                                                 "ground": MovementCost(0.0, 0.0)})[0]


def test_clamp_pulls_back_to_0999_of_the_cap_from_the_original_start():
    ctx = _capped()
    assert optimization._clamp(ctx, 0, np.array([200.0, 100.0])).tolist() == \
        pytest.approx([100.0 + 50.0 * 0.999, 100.0])
    assert optimization._clamp(ctx, 0, np.array([100.0, 30.0])).tolist() == \
        pytest.approx([100.0, 100.0 - 50.0 * 0.999])
    assert optimization._clamp(ctx, 0, np.array([150.0, 100.0])).tolist() == [150.0, 100.0]
    assert optimization._clamp(ctx, 0, np.array([120.0, 110.0])).tolist() == [120.0, 110.0]


def test_clamp_happens_before_the_bounds_check():
    nodes = [entry("A", 395.0, 200.0, 10.0), entry("F", 300.0, 300.0, 2.0, "vehicle")]
    capped = _capped(3.0, nodes)
    xy = optimization._clamp(capped, 0, np.array([500.0, 200.0]))
    assert xy is not None and xy.tolist() == pytest.approx([395.0 + 3.0 * 0.999, 200.0])
    free = pure_context(nodes, {"A"}, penalties=ZERO)[0]
    assert optimization._clamp(free, 0, np.array([500.0, 200.0])) is None
    assert optimization._clamp(free, 0, np.array([400.0, 200.0])).tolist() == [400.0, 200.0]


def test_swap_with_one_selected_node_is_a_nudge():
    ctx, _ = pure_context(MIXED, {"A"})
    covered = np.zeros(len(ctx.coverage_weights), dtype=bool)
    swap = optimization.propose(ctx, np.random.default_rng(5), ctx.starts, covered, "swap",
                                10.0)
    nudge = optimization.propose(ctx, np.random.default_rng(5), ctx.starts, covered, "nudge",
                                 10.0)
    assert swap is not None and np.array_equal(swap, nudge)
    assert np.array_equal(swap[[0, 2]], ctx.starts[[0, 2]]) and swap[1, 2] == 10.0
    assert not np.array_equal(swap[1], ctx.starts[1])


def test_teleport_targets_only_uncovered_probes():
    ctx, _ = pure_context(MIXED, {"A"})
    covered = np.ones(len(ctx.coverage_weights), dtype=bool)
    uncovered = [3, 9, 14]
    covered[uncovered] = False
    rng = np.random.default_rng(7)
    hits = set()
    for _ in range(60):
        proposal = optimization.propose(ctx, rng, ctx.starts, covered, "teleport", 1e-6)
        assert proposal is not None
        distance = np.hypot(*(ctx.coverage_points - proposal[1, :2]).T)
        nearest = int(np.argmin(distance))
        assert distance[nearest] < 1e-5 and nearest in uncovered
        hits.add(nearest)
        assert proposal[1, 2] == 10.0 and np.array_equal(proposal[[0, 2]], ctx.starts[[0, 2]])
    assert hits == set(uncovered)


def test_nudge_from_a_moved_layout_is_capped_from_the_original_start():
    ctx = _capped(50.0)
    layout = ctx.starts.copy()
    layout[0, :2] = [140.0, 100.0]       # already 40 m from the start
    covered = np.zeros(len(ctx.coverage_weights), dtype=bool)
    rng = np.random.default_rng(1)
    for _ in range(200):
        proposal = optimization.propose(ctx, rng, layout, covered, "nudge", 300.0)
        if proposal is not None:
            assert ctx.displacement(0, proposal[0]) <= 50.0
