"""Generate the three figures on the "How the two searches work" placement page.

placement-setup.svg      the example scenario as the planner sees it: area,
                         coverage probes, each drone's candidate points and cap
placement-geometric.svg  the two greedy steps, every candidate colored by how
                         much it would change the score
placement-annealing.svg  the annealing schedule and the score of every proposal

The data comes from the real planner on inputs/baselines/channel-scored-example
(planning seed 701). The script runs scripts.baselines.preparation.prepare with
the score and proposal functions wrapped, so every layout the planner scores is
recorded; nothing in the planner changes. Run it with the project venv from
docs/, passing an already built binary to capture, or nothing to re-render the
last capture:

    ../.venv/bin/python diagrams/placement-search.py --sim-binary <BIN>
    ../.venv/bin/python diagrams/placement-search.py

Captures go to ../outputs/docs-figures/placement-search/ (ignored by Git).
"""
import argparse
import json
import math
import os
import shutil
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402
from matplotlib.colors import TwoSlopeNorm  # noqa: E402
from matplotlib.patches import Circle, Rectangle  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))  # scratch/mesh-sim
EXAMPLE = os.path.join(ROOT, "inputs", "baselines", "channel-scored-example")
CAPTURE = os.path.join(ROOT, "outputs", "docs-figures", "placement-search")
DATA = os.path.join(CAPTURE, "data.json")

INK, MUTED, GRID, EDGE = "#1f2d3a", "#5b6b7b", "#e6e9ec", "#c9cfd5"
BLUE, AMBER, GREEN, RED = "#2980b9", "#c99a1e", "#27ae60", "#c0392b"
NEUTRAL = "#eef0f2"
# The three runs: (name, settings file, method).
RUNS = (("penalized", "run.ini", "geometric"),
        ("zero_cost", "run-zero-cost.ini", "geometric"),
        ("anneal", "run-zero-cost.ini", "optimization"))


# ---------------------------------------------------------------- capture

def capture(sim_binary):
    """Run the planner three times with recording wrappers; write data.json."""
    sys.path.insert(0, ROOT)
    from scripts.baselines import preparation
    from scripts.baselines.planners import geometric, objective, optimization

    data = {}
    for name, ini, method in RUNS:
        record = {"scores": [], "proposals": [], "accepts": []}
        phase = {"now": "start"}
        real_build = objective.ScoringContext.build.__func__
        real_score = objective.score
        real_propose = optimization.propose
        real_covered = optimization._covered
        real_geometric = geometric.solve

        def build(cls, request, scorer, _real=real_build, _rec=record):
            ctx = _real(cls, request, scorer)
            _rec.setdefault("ctx", {
                "ids": list(ctx.ids), "selected": list(ctx.selected),
                "rectangle": ctx.rectangle, "starts": ctx.starts.tolist(),
                "probes": ctx.coverage_points.tolist(), "cell_m": ctx.cell_m,
                "candidates": {ctx.ids[i]: objective.candidate_positions(ctx, i).tolist()
                               for i in ctx.selected},
                "caps": {ctx.ids[i]: ctx.costs[i].max_displacement_m for i in ctx.selected},
                "aoi_m2": ctx.aoi_m2, "diag_m": ctx.diag_m,
            })
            return ctx

        def score(ctx, result, layout, _real=real_score, _rec=record, _phase=phase):
            out = _real(ctx, result, layout)
            _rec["scores"].append({
                "phase": _phase["now"], "layout": [list(map(float, row)) for row in layout],
                "total": out.total, "components": out.components,
                "coverage": result.coverage,
            })
            return out

        def propose(ctx, rng, layout, covered, move, sigma, config=None,
                    _real=real_propose, _rec=record):
            new = _real(ctx, rng, layout, covered, move, sigma, config)
            _rec["proposals"].append({"move": move, "sigma": sigma, "valid": new is not None})
            return new

        def covered(ctx, result, _real=real_covered, _rec=record):
            _rec["accepts"].append(len(_rec["proposals"]))
            return _real(ctx, result)

        def warm(request, scorer, log, _real=real_geometric, _phase=phase):
            _phase["now"] = "greedy"
            try:
                return _real(request, scorer, log)
            finally:
                _phase["now"] = "anneal"

        objective.ScoringContext.build = classmethod(build)
        geometric.score = optimization.score = score
        optimization.propose, optimization._covered = propose, covered
        optimization.geometric.solve = warm
        if method == "geometric":
            phase["now"] = "greedy"
        target = os.path.join(CAPTURE, name)
        shutil.rmtree(target, ignore_errors=True)
        try:
            preparation.prepare(os.path.join(EXAMPLE, ini), method, target,
                                mode="standalone", sim_binary=sim_binary,
                                simulation_seeds=[801])
        finally:
            objective.ScoringContext.build = classmethod(real_build)
            geometric.score = optimization.score = real_score
            optimization.propose, optimization._covered = real_propose, real_covered
            optimization.geometric.solve = real_geometric
        data[name] = record
    os.makedirs(CAPTURE, exist_ok=True)
    with open(DATA, "w") as fh:
        json.dump(data, fh)


# ---------------------------------------------------------------- drawing helpers

def style_map(ax, rect, title):
    ax.set_title(title, loc="left", fontsize=12.5, fontweight="bold", color=INK, pad=10)
    ax.set_xlim(rect["x_min"] - 10, rect["x_max"] + 10)
    ax.set_ylim(rect["y_min"] - 10, rect["y_max"] + 10)
    ax.set_aspect("equal")
    ax.add_patch(Rectangle((rect["x_min"], rect["y_min"]), rect["x_max"] - rect["x_min"],
                           rect["y_max"] - rect["y_min"], fill=False, ec=EDGE, lw=1.2))
    ax.set_xlabel("x (m)", fontsize=10, color=MUTED)
    ax.set_ylabel("y (m)", fontsize=10, color=MUTED)
    ax.tick_params(colors=MUTED, labelsize=9)
    for side in ax.spines.values():
        side.set_visible(False)


def style_line(ax, title, ylabel):
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", color=INK, pad=8)
    ax.set_ylabel(ylabel, fontsize=10, color=MUTED)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(EDGE)
    ax.tick_params(colors=MUTED, labelsize=9)


def draw_nodes(ax, ctx, layout, moved=()):
    for k, node_id in enumerate(ctx["ids"]):
        x, y = layout[k][0], layout[k][1]
        drone = k in ctx["selected"]
        ax.scatter([x], [y], s=110, marker="^" if drone else "s", color=BLUE if drone else AMBER,
                   edgecolor="white", linewidth=1.5, zorder=6)
        label = node_id + (" (moved)" if node_id in moved else "")
        ax.annotate(label, (x, y), xytext=(0, 12), textcoords="offset points", ha="center",
                    fontsize=9.5, color=INK, fontweight="bold", zorder=7,
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.9))


def save(fig, name):
    path = os.path.join(HERE, name)
    fig.savefig(path, format="svg", bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {os.path.relpath(path, ROOT)}")


# ---------------------------------------------------------------- figures

def figure_setup(run):
    ctx, start = run["ctx"], run["scores"][0]
    rect, cell = ctx["rectangle"], ctx["cell_m"]
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.6))

    ax = axes[0]
    style_map(ax, rect, "What the planner sees")
    for px, py in ctx["probes"]:
        ax.add_patch(Rectangle((px - cell / 2, py - cell / 2), cell, cell, fill=False,
                               ec=GRID, lw=0.8, zorder=1))
    probes = list(zip(*ctx["probes"]))
    ax.scatter(*probes, s=6, color=MUTED, zorder=2, label="coverage probe (cell center)")
    for k in ctx["selected"]:
        node_id = ctx["ids"][k]
        sx, sy = ctx["starts"][k][:2]
        ax.add_patch(Circle((sx, sy), ctx["caps"][node_id], fill=False, ls=(0, (4, 3)),
                            ec=BLUE, lw=1.1, zorder=3))
        pts = list(zip(*[row[:2] for row in ctx["candidates"][node_id][1:]]))
        ax.scatter(*pts, s=34, facecolor="white", edgecolor=BLUE, linewidth=1.3, zorder=4,
                   label="candidate position" if k == ctx["selected"][0] else None)
    draw_nodes(ax, ctx, ctx["starts"])
    ax.plot([], [], ls=(0, (4, 3)), color=BLUE, lw=1.1, label="100 m movement cap")
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.11), ncol=2, frameon=False,
              fontsize=9, labelcolor=INK)

    ax = axes[1]
    style_map(ax, rect, "Coverage at the start")
    counts = [0] * len(ctx["probes"])
    for row in start["coverage"]:
        for p in row:
            counts[p] += 1
    shades = {0: NEUTRAL, 1: "#d4e6f1", 2: "#8fbcdb", 3: "#2f6f9f"}
    for (px, py), n in zip(ctx["probes"], counts):
        ax.add_patch(Rectangle((px - cell / 2, py - cell / 2), cell, cell, fc=shades[n],
                               ec="white", lw=1.0, zorder=1))
    draw_nodes(ax, ctx, ctx["starts"])
    for n in sorted(set(counts)):
        ax.scatter([], [], marker="s", s=80, color=shades[n],
                   label="not covered" if n == 0 else f"seen by {n} node{'s' if n > 1 else ''}")
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.11), ncol=3, frameon=False,
              fontsize=9, labelcolor=INK)
    fig.tight_layout()
    save(fig, "placement-setup.svg")


def greedy_steps(run):
    """[(node index, layout before, [(position, delta)], chosen position or None)]."""
    ctx = run["ctx"]
    scores = [s for s in run["scores"] if s["phase"] == "greedy"]
    current = scores[0]
    steps = []
    for k in ctx["selected"]:
        trials = []
        for s in scores[1:]:
            diff = [i for i in range(len(ctx["ids"]))
                    if s["layout"][i][:2] != current["layout"][i][:2]]
            if diff == [k]:
                trials.append((s["layout"][k][:2], s["total"] - current["total"], s))
        best = max(trials, key=lambda t: t[1]) if trials else None
        chosen = best[0] if best and best[1] > 1e-6 else None
        steps.append((k, current["layout"], [(t[0], t[1]) for t in trials], chosen))
        if chosen:
            current = best[2]
    return steps


def figure_geometric(run):
    ctx = run["ctx"]
    steps = greedy_steps(run)
    deltas = [d for _, _, trials, _ in steps for _, d in trials]
    span = max(abs(min(deltas)), abs(max(deltas)), 1.0)
    norm = TwoSlopeNorm(vmin=-span, vcenter=0.0, vmax=span)
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("pm", [RED, NEUTRAL, BLUE])
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.4))
    for ax, (k, before, trials, chosen), n in zip(axes, steps, (1, 2)):
        node_id = ctx["ids"][k]
        style_map(ax, ctx["rectangle"], f"Step {n}: place {node_id}")
        sx, sy = before[k][:2]
        ax.add_patch(Circle((sx, sy), ctx["caps"][node_id], fill=False, ls=(0, (4, 3)),
                            ec=MUTED, lw=1.0, zorder=2))
        xs, ys = zip(*[p for p, _ in trials])
        sc = ax.scatter(xs, ys, c=[d for _, d in trials], cmap=cmap, norm=norm, s=70,
                        edgecolor="white", linewidth=1.2, zorder=4)
        if chosen:
            ax.scatter([chosen[0]], [chosen[1]], s=260, facecolor="none", edgecolor=INK,
                       linewidth=1.8, zorder=5)
            best = max(d for _, d in trials)
            ax.annotate(f"best: +{best:.1f} m²", (chosen[0], chosen[1]), xytext=(14, -18),
                        textcoords="offset points", fontsize=9.5, color=INK, zorder=7)
            ax.annotate("", xy=chosen, xytext=(sx, sy), zorder=3,
                        arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.2))
        draw_nodes(ax, ctx, before)
    bar = fig.colorbar(sc, ax=axes, orientation="horizontal", fraction=0.05, pad=0.13,
                       aspect=50)
    bar.set_label("change in total score if the node moves here (m²)", fontsize=10, color=MUTED)
    bar.ax.tick_params(colors=MUTED, labelsize=9)
    bar.outline.set_edgecolor(EDGE)
    save(fig, "placement-geometric.svg")


def figure_annealing(run):
    ctx = run["ctx"]
    scores = [s for s in run["scores"] if s["phase"] == "anneal"]
    proposals = run["proposals"]
    accepts = set(run["accepts"][1:])  # the first _covered call is the warm start
    aoi = ctx["aoi_m2"]
    n_iter = len(proposals)
    iters = list(range(n_iter))
    t0, tf = 0.02 * aoi, 0.0002 * aoi
    temps = [t0 * (tf / t0) ** (i / n_iter) for i in iters]
    sigmas = [p["sigma"] for p in proposals]
    base = scores[:2]  # warm (greedy) layout, then the start layout
    current = max(base, key=lambda s: s["total"])["total"]
    queue = iter(scores[2:])
    # x = 0 is the starting layout; proposal i is plotted at x = i + 1.
    cur_line, best_line, acc, rej, invalid = [current], [current], [], [], []
    best = current
    for i, p in enumerate(proposals):
        if not p["valid"]:
            invalid.append(i + 1)
        else:
            total = next(queue)["total"]
            if (i + 1) in accepts:
                current = total
                acc.append((i + 1, total))
            else:
                rej.append((i + 1, total))
            best = max(best, current)
        cur_line.append(current)
        best_line.append(best)

    fig, axes = plt.subplots(3, 1, figsize=(10, 9.2), sharex=True,
                             gridspec_kw={"height_ratios": [1, 1, 1.6]})
    ax = axes[0]
    style_line(ax, "Temperature: how bad a move may be and still be accepted", "T (m²)")
    ax.plot(iters, temps, color=BLUE, lw=2)
    ax.set_yscale("log")
    ax.annotate(rf"$T_0$ = 0.02 × area = {t0:,.0f} m²", (0, t0), xytext=(8, -4),
                textcoords="offset points", fontsize=9.5, color=INK, va="top")
    ax.annotate(rf"$T_f$ = 0.0002 × area = {tf:,.0f} m²", (n_iter - 1, temps[-1]),
                xytext=(-8, 10), textcoords="offset points", fontsize=9.5, color=INK, ha="right")

    ax = axes[1]
    style_line(ax, "Step size: how far a nudge moves a node", "σ (m)")
    ax.plot(iters, sigmas, color=BLUE, lw=2)
    ax.annotate(rf"$\sigma_0$ = 0.08 × diagonal + 2 m = {sigmas[0]:.1f} m", (0, sigmas[0]),
                xytext=(8, -4), textcoords="offset points", fontsize=9.5, color=INK, va="top")

    ax = axes[2]
    style_line(ax, "Score of every proposal", "total score (m²)")
    if rej:
        ax.scatter(*zip(*rej), s=30, facecolor="white", edgecolor=MUTED, linewidth=1.1,
                   zorder=3, label=f"rejected ({len(rej)})")
    if acc:
        ax.scatter(*zip(*acc), s=34, color=GREEN, edgecolor="white", linewidth=0.8, zorder=4,
                   label=f"accepted ({len(acc)})")
    steps = list(range(n_iter + 1))
    ax.step(steps, cur_line, where="post", color=INK, lw=1.4, label="current layout", zorder=2)
    ax.step(steps, best_line, where="post", color=BLUE, lw=2, label="best so far (returned)",
            zorder=2)
    ax.annotate("start: the geometric plan, never beaten", (0, best_line[0]), xytext=(8, 6),
                textcoords="offset points", fontsize=9.5, color=INK)
    scored = [s for _, s in rej + acc]
    lo, hi = min(scored + [best]), max(scored + [best])
    rug = lo - 0.12 * (hi - lo)
    if invalid:
        ax.scatter(invalid, [rug] * len(invalid), marker="x", s=24, color=RED, linewidth=1.2,
                   zorder=3, label=f"invalid, not scored ({len(invalid)})")
    ax.set_ylim(rug - 0.06 * (hi - lo), hi + 0.22 * (hi - lo))
    ax.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
    ax.set_xlabel("iteration", fontsize=10, color=MUTED)
    ax.legend(loc="upper right", bbox_to_anchor=(1, 0.9), frameon=False, fontsize=9,
              labelcolor=INK, ncol=3)
    fig.tight_layout()
    save(fig, "placement-annealing.svg")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sim-binary", help="capture fresh data with this built binary")
    args = parser.parse_args()
    if args.sim_binary:
        capture(os.path.abspath(args.sim_binary))
    with open(DATA) as fh:
        data = json.load(fh)
    figure_setup(data["zero_cost"])
    figure_geometric(data["zero_cost"])
    figure_annealing(data["anneal"])


if __name__ == "__main__":
    main()
