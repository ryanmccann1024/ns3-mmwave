"""Greedy planner edges: acceptance threshold, anchor filter precedence, need fallback,
empty candidate sets, one batched query per node, roster order and determinism.
"""

import json
import math
import sys
from contextlib import contextmanager

import numpy as np
import pytest

from scripts.baselines.planners import geometric
from scripts.baselines.planners.channel import ChannelScorer
from scripts.baselines.planners.objective import (LayoutScore, MovementCost, prepare_scorer,
                                                  SCORE_TIE_TOL_M2)
from scripts.baselines.tests.conftest import fake_query_binary
from scripts.baselines.tests.test_objective import (ZERO, assert_plan_invariants, entry,
                                                    make_request)

from ._planner_support import DistanceScorer, TableScorer, full_table


class _Log:
    def __init__(self):
        self.text = ""

    def write(self, text):
        self.text += text

    def flush(self):
        pass


def _run(entries, movable, scorer, **kwargs):
    request = make_request(entries, movable, **kwargs)
    prepare_scorer(request, scorer)
    log = _Log()
    positions, diagnostics, notes = geometric.solve(request, scorer, log)
    json.dumps(diagnostics)
    assert_plan_invariants(request, positions)
    return request, positions, diagnostics, notes, log


def _fake_score(totals: dict, default: float):
    """score() replacement: total by the moved node's (x, y); the start scores 0."""

    def fake(ctx, result, layout):
        layout = np.asarray(layout)
        if np.array_equal(layout, ctx.starts):
            total = 0.0
        else:
            total = totals.get(tuple(layout[1, :2].tolist()), default)
        return LayoutScore(0.0, 0.0, 0.0, 0, 0, float(total))
    return fake


PAIR = [entry("F", 200.0, 200.0, 2.0, "vehicle"), entry("M", 210.0, 200.0, 10.0)]


# ---------------------------------------------------------------------------------------
# needs()

def test_needs_edges():
    assert geometric.needs("balanced", 1, 0.01) == [2]
    assert geometric.needs("balanced", 3, 1.0) == [2, 2, 2]
    assert geometric.needs("balanced", 3, 0.34) == [2, 2, 1]
    assert geometric.needs("coverage", 0, 0.5) == []
    with pytest.raises(ValueError):
        geometric.needs("gateway", 2, 0.5)


# ---------------------------------------------------------------------------------------
# Acceptance threshold (marginal must exceed SCORE_TIE_TOL_M2 = 1e-6 m^2).

@pytest.mark.parametrize("delta,accepted", [
    (SCORE_TIE_TOL_M2, False),
    (math.nextafter(SCORE_TIE_TOL_M2, 1.0), True),
    (2e-6, True),
    (0.0, False),
    (-5.0, False),
])
def test_marginal_must_strictly_exceed_the_tie_tolerance(monkeypatch, delta, accepted):
    monkeypatch.setattr(geometric, "score", _fake_score({(50.0, 50.0): delta}, -1.0))
    scorer = TableScorer(lambda layout: full_table(2))
    request, positions, diagnostics, notes, _ = _run(PAIR, {"M"}, scorer)
    step = diagnostics["geometric"]["steps"][0]
    assert step["accepted"] is accepted
    assert step["marginal_m2"] == max(delta, -1.0)  # best of the 16 candidates
    if accepted:
        assert positions[1].tolist() == [50.0, 50.0, 10.0]
    else:
        assert positions.tolist() == [[n.x, n.y, n.z] for n in request.nodes]
        assert "M: stay put" in notes


def test_anchor_filter_takes_precedence_over_score(monkeypatch):
    totals = {(50.0, 50.0): 1e6, (350.0, 350.0): 10.0}
    monkeypatch.setattr(geometric, "score", _fake_score(totals, 1.0))

    def table(layout):
        cut = tuple(layout[1, :2].tolist()) == (50.0, 50.0)
        return full_table(2, missing=[(0, 1)] if cut else ())
    _, positions, diagnostics, _, _ = _run(PAIR, {"M"}, TableScorer(table))
    step = diagnostics["geometric"]["steps"][0]
    assert step["pool"] == ["F"] and step["eff_need"] == 1
    assert step["candidates"] == 16 and step["feasible"] == 15
    assert positions[1].tolist() == [350.0, 350.0, 10.0]
    assert step["marginal_m2"] == 10.0 and step["anchor_links"] == 1


# ---------------------------------------------------------------------------------------
# No feasible / no candidate cases: stay-put is always allowed.

def test_no_candidate_feasible_even_after_need_drops_to_one():
    entries = [entry("F1", 0.0, 0.0, 10.0), entry("F2", 5.0, 0.0, 10.0),
               entry("M", 2.0, 5.0, 10.0)]
    scorer = DistanceScorer(range_m=10.0)
    request, positions, diagnostics, notes, log = _run(entries, {"M"}, scorer,
                                                       objective="resilience")
    step = diagnostics["geometric"]["steps"][0]
    assert step["need"] == 2 and step["eff_need"] == 2 and step["degraded"]
    assert step["candidates"] == 16 and step["feasible"] == 0
    assert step["accepted"] is False and step["marginal_m2"] is None
    assert positions.tolist() == [[n.x, n.y, n.z] for n in request.nodes]
    assert "M: stay put" in notes and "no anchor-feasible candidate" in log.text
    assert [len(call) for call in scorer.calls] == [1, 16]


def test_no_candidate_inside_the_cap_queries_only_the_start():
    penalties = {"aerial": MovementCost(0.0, 0.0, 1.0), "ground": MovementCost(0.0, 0.0)}
    entries = [entry("F", 200.0, 200.0, 2.0, "vehicle"), entry("M", 210.0, 200.0, 10.0)]
    scorer = DistanceScorer()
    request, positions, diagnostics, notes, _ = _run(entries, {"M"}, scorer,
                                                     penalties=penalties)
    step = diagnostics["geometric"]["steps"][0]
    assert step["candidates"] == 0 and step["feasible"] == 0 and not step["accepted"]
    assert [len(call) for call in scorer.calls] == [1]
    assert positions.tolist() == [[n.x, n.y, n.z] for n in request.nodes]
    assert "M: stay put" in notes


def test_candidate_exactly_at_the_cap_can_be_chosen():
    # M starts 100 m below the (50, 150) centre with a 100 m cap; only the cap-edge
    # candidates reconnect it to F, so the plan must land exactly on the cap.
    penalties = {"aerial": MovementCost(0.0, 0.0, 100.0), "ground": MovementCost(0.0, 0.0)}
    entries = [entry("F", 50.0, 230.0, 10.0), entry("M", 50.0, 50.0, 10.0)]
    scorer = DistanceScorer(range_m=90.0)
    _, positions, diagnostics, _, _ = _run(entries, {"M"}, scorer, penalties=penalties)
    assert diagnostics["geometric"]["steps"][0]["accepted"]
    assert positions[1].tolist() == [50.0, 150.0, 10.0]
    assert diagnostics["nodes"]["M"]["displacement_m"] == 100.0
    assert diagnostics["disconnected_selected"] == []


# ---------------------------------------------------------------------------------------
# Query batching, order and bookkeeping.

THREE = [entry("F", 205.0, 205.0, 2.0, "vehicle"), entry("A", 120.0, 120.0, 10.0),
         entry("B", 280.0, 130.0, 10.0), entry("C", 210.0, 300.0, 1.5, "pedestrian")]


def test_one_evaluate_call_per_node_and_roster_order():
    scorer = DistanceScorer()
    _, _, diagnostics, _, _ = _run(THREE, {"C", "A", "B"}, scorer)
    steps = diagnostics["geometric"]["steps"]
    assert [s["node"] for s in steps] == ["A", "B", "C"]
    assert [len(call) for call in scorer.calls] == [1] + [s["candidates"] for s in steps]
    for call, node in zip(scorer.calls[1:], (1, 2, 3)):
        others = [k for k in range(4) if k != node]
        base = call[0][0]
        # Every layout of a node's batch differs from the others only in that node's x/y.
        assert all(np.array_equal(layout[others], base[others]) for layout, _ in call)
        assert len({tuple(layout[node]) for layout, _ in call}) == len(call)
        assert all(layout[node, 2] == THREE[node]["position"]["z"] for layout, _ in call)


def test_total_gain_is_the_sum_of_accepted_marginals():
    scorer = DistanceScorer()
    _, _, diagnostics, _, _ = _run(THREE, {"A", "B", "C"}, scorer, objective="balanced")
    steps = diagnostics["geometric"]["steps"]
    gained = sum(s["marginal_m2"] for s in steps if s["accepted"])
    assert all(s["marginal_m2"] > SCORE_TIE_TOL_M2 for s in steps if s["accepted"])
    assert diagnostics["score"]["total"] - diagnostics["geometric"]["start_total"] == \
        pytest.approx(gained)


def test_geometric_is_deterministic():
    first = _run(THREE, {"A", "B", "C"}, DistanceScorer(), objective="resilience")
    second = _run(THREE, {"A", "B", "C"}, DistanceScorer(), objective="resilience")
    assert np.array_equal(first[1], second[1])
    assert first[2] == second[2] and first[3] == second[3]


@contextmanager
def _fake_query_scorer(tmp_path, monkeypatch, entries, request, max_layouts):
    for name in ("FAKE_QUERY_FAULT", "FAKE_QUERY_FAULT_AT", "FAKE_QUERY_INIT_PATCH",
                 "FAKE_QUERY_PAD_BYTES", "FAKE_QUERY_PID_FILE", "FAKE_QUERY_RANGE_M"):
        monkeypatch.delenv(name, raising=False)
    record = tmp_path / "record.jsonl"
    monkeypatch.setenv("FAKE_QUERY_RECORD", str(record))
    scenario = tmp_path / "scenario"
    scenario.mkdir()
    (scenario / "run.ini").write_text("[scenario]\nname = t\nseed = 3\nrun_id = 1\n"
                                      "nodes_file = nodes.json\n")
    (scenario / "nodes.json").write_text(json.dumps(entries))
    binary = fake_query_binary(tmp_path / "bin")
    starts = [[n.x, n.y, n.z] for n in request.nodes]
    with open(tmp_path / "planner.log", "w", encoding="utf-8") as log:
        with ChannelScorer(binary, scenario / "run.ini", 3, 1, None, "standalone",
                           [n.id for n in request.nodes], starts, 3, log,
                           max_layouts=max_layouts) as scorer:
            prepare_scorer(request, scorer)
            yield scorer, log, record


def test_node_candidates_split_into_worker_requests_by_max_layouts(tmp_path, monkeypatch):
    request = make_request(THREE, {"A", "B", "C"})
    with _fake_query_scorer(tmp_path, monkeypatch, THREE, request, 7) as (scorer, log, rec):
        positions, diagnostics, _ = geometric.solve(request, scorer, log)
        stats = scorer.stats
    steps = diagnostics["geometric"]["steps"]
    sizes = [json.loads(line)["layouts"] for line in rec.read_text().splitlines()
             if json.loads(line).get("type") == "evaluate"]
    expected = [1]
    for s in steps:
        expected += [7] * (s["candidates"] // 7) + ([s["candidates"] % 7]
                                                    if s["candidates"] % 7 else [])
    assert sizes == expected
    assert stats["layouts"] == 1 + sum(s["candidates"] for s in steps)
    assert_plan_invariants(request, positions)
    # Same plan as the in-process distance channel with fake_query's default 100 m range.
    _, same, _, _, _ = _run(THREE, {"A", "B", "C"}, DistanceScorer())
    assert np.allclose(positions, same)
