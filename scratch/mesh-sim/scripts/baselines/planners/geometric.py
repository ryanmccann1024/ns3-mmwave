"""Sequential greedy placement over a rootless peer-anchor schedule, scored by the channel."""

import math

import numpy as np

from scripts.baselines.planners import objective
from scripts.baselines.planners.objective import (
    LayoutCache,
    ScoringContext,
    candidate_positions,
    check_layout,
    components,
    core,
    diagnose,
    score,
)


def needs(objective_name: str, count: int, balanced_core_fraction: float) -> list[int]:
    """Anchor links each selected node should have, in roster order."""
    return objective.objective_preset(objective_name).anchor_needs(count, balanced_core_fraction)


def settings(request) -> dict:
    count = sum(1 for node in request.nodes if node.role == "movable")
    return {
        "strategy": "sequential_greedy",
        "minimum_separation_m": getattr(request, "minimum_separation_m", 0.0),
        "order": "roster",
        "needs": needs(request.objective, count, request.balanced_core_fraction),
        "balanced_core_fraction": float(request.balanced_core_fraction),
        "acceptance": "strictly_positive_total_gain",
        "score_tie_tol_m2": objective.SCORE_TIE_TOL_M2,
        "objective_settings": getattr(
            request, "objective_settings", objective.ObjectiveSettings()
        ).resolved(request.objective),
    }


def _pool(ctx: ScoringContext, connected: np.ndarray, processed: list[int], node: int) -> list[int]:
    members = core(components(connected))
    chosen = set(processed)
    return sorted(k for k in members if k != node and (k not in ctx.selected or k in chosen))


def _place(ctx, cache, layout, current, current_score, node, need, processed, log):
    pool = _pool(ctx, current.connected, processed, node)
    eff_need = min(need, len(pool))
    step = {
        "node": ctx.ids[node],
        "need": need,
        "eff_need": eff_need,
        "pool": [ctx.ids[k] for k in pool],
        "bootstrap": eff_need == 0,
        "degraded": False,
        "candidates": 0,
        "feasible": 0,
        "accepted": False,
        "marginal_m2": None,
        "anchor_links": None,
    }
    moves = candidate_positions(ctx, node)[1:]
    moves = [position for position in moves if objective.layout_separated(
        ctx, np.array([position if i == node else layout[i] for i in range(len(layout))]))]
    step["candidates"] = len(moves)
    if not len(moves):
        return layout, current, current_score, step

    def trials():
        for position in moves:
            trial = layout.copy()
            trial[node] = position
            yield trial

    best = fallback = None
    feasible_count = fallback_count = 0
    for k, result in enumerate(cache.iter_evaluate(trials())):
        links = int(result.connected[node, pool].sum())
        if links < min(eff_need, 1):
            continue
        trial = layout.copy()
        trial[node] = moves[k]
        trial_score = score(ctx, result, trial)
        candidate = (trial, result, trial_score, links)
        fallback_count += 1
        if fallback is None or trial_score.total > fallback[2].total:
            fallback = candidate
        if links >= eff_need:
            feasible_count += 1
            if best is None or trial_score.total > best[2].total:
                best = candidate
    if best is None and eff_need >= 2:
        best = fallback
        feasible_count = fallback_count
        step["degraded"] = True
    step["feasible"] = feasible_count
    if best is None:
        log.write(f"geometric: {ctx.ids[node]} stays put (no anchor-feasible candidate)\n")
        return layout, current, current_score, step
    best_layout, best_result, best_score, best_links = best
    step["marginal_m2"] = best_score.total - current_score.total
    if step["marginal_m2"] <= objective.SCORE_TIE_TOL_M2:
        log.write(
            f"geometric: {ctx.ids[node]} stays put (best marginal {step['marginal_m2']:.6g} m2)\n"
        )
        return layout, current, current_score, step
    step["accepted"] = True
    step["anchor_links"] = best_links
    log.write(
        f"geometric: {ctx.ids[node]} -> ({best_layout[node, 0]:.3f}, {best_layout[node, 1]:.3f}) marginal {step['marginal_m2']:.6g} m2\n"
    )
    return best_layout, best_result, best_score, step


def solve(request, scorer, log):
    """Place selected nodes one at a time in roster order; returns (N x 3, diagnostics, notes)."""
    ctx = ScoringContext.build(request, scorer)
    cache = LayoutCache(scorer, getattr(request, "cache_bytes", 32 * 1024 * 1024))
    layout = ctx.starts.copy()
    check_layout(ctx, layout)
    current = cache.evaluate([layout])[0]
    current_score = score(ctx, current, layout)
    start_total = current_score.total
    schedule = needs(ctx.objective, len(ctx.selected), ctx.balanced_core_fraction)
    processed, steps, notes = [], [], []
    for node, need in zip(ctx.selected, schedule):
        layout, current, current_score, step = _place(
            ctx, cache, layout, current, current_score, node, need, processed, log
        )
        processed.append(node)
        steps.append(step)
        if not step["accepted"]:
            notes.append(f"{step['node']}: stay put")
        elif step["degraded"]:
            notes.append(f"{step['node']}: anchor need degraded 2 -> 1")
    log.flush()
    check_layout(ctx, layout)
    diagnostics = diagnose(ctx, current, layout, current_score, log=log)
    diagnostics["geometric"] = {"steps": steps, "start_total": start_total}
    notes.append(
        f"geometric: {sum(s['accepted'] for s in steps)}/{len(steps)} moved, "
        f"score {current_score.total:,.0f} m2-equivalent"
    )
    return layout, diagnostics, notes
