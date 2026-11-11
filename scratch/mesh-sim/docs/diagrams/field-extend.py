"""Generate the two figures on the "Extend the comparison" field-data page.

field-pipeline-map.svg  the two packages, every step and the files between
                        them, with the trace file where they meet
field-windows.svg       the SNR median gap per node in three windows of the
                        practice bundle (the "add a window" example)

The second figure reads the practice-run outputs written by
docs/diagrams/field-example.py (run that first). From docs/:

    ../.venv/bin/python diagrams/field-extend.py
"""
import csv
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WORK = os.path.join(ROOT, "outputs", "docs-figures", "field-example", "work")

INK, MUTED, GRID, EDGE = "#1f2d3a", "#5b6b7b", "#e6e9ec", "#c9cfd5"
BLUE, AMBER, GREEN, RED = "#2980b9", "#c99a1e", "#27ae60", "#c0392b"
FIELD_BG, SIM_BG, MEET_BG = "#eaf2f8", "#fbf3df", "#e9f5ee"


def box(ax, x, y, w, h, title, sub, fc, ec=EDGE, bold=False):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.02,rounding_size=0.06",
                                fc=fc, ec=ec, lw=1.6 if bold else 1.0, zorder=2))
    ax.text(x, y + h * 0.17, title, ha="center", va="center", fontsize=10.5, fontweight="bold", color=INK,
            zorder=3)
    ax.text(x, y - h * 0.2, sub, ha="center", va="center", fontsize=8.4, color=MUTED, zorder=3,
            family="monospace", linespacing=1.4)


def arrow(ax, a, b, label=None):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=12, lw=1.2, color=INK, zorder=1))
    if label:
        ax.text((a[0] + b[0]) / 2, a[1] + 0.1, label, ha="center", va="bottom", fontsize=8, color=INK,
                family="monospace", zorder=3)


def pipeline_map():
    fig, ax = plt.subplots(figsize=(13.6, 5.6))
    ax.set_xlim(0, 13.6)
    ax.set_ylim(0, 5.6)
    ax.axis("off")
    for y0, fc in ((3.15, FIELD_BG), (0.2, SIM_BG)):
        ax.add_patch(FancyBboxPatch((0.1, y0), 9.5, 2.2, boxstyle="round,pad=0,rounding_size=0.1",
                                    fc=fc, ec="none", zorder=0))
    ax.text(0.3, 5.18, "Field side: scripts/arpo_data", fontsize=10.5, fontweight="bold", color=BLUE, va="top")
    ax.text(0.3, 0.32, "Simulator side: scripts/validation", fontsize=10.5, fontweight="bold",
            color="#8a6a12", va="bottom")
    w, h = 2.1, 0.8
    xs = (1.35, 4.75, 8.15)
    yf, ys = 4.0, 1.3
    box(ax, xs[0], yf, w, h, "Raw bundle", "gps/  silvus/", "white")
    box(ax, xs[1], yf, w, h, "Daily traces", "daily/<day>/", "white")
    box(ax, xs[2], yf, w, h, "Window traces", "windows/<tag>/", MEET_BG, ec=GREEN, bold=True)
    box(ax, xs[0], ys, w, h, "Scenario", "run.ini  nodes.json", "white")
    box(ax, xs[1], ys, w, h, "Seed outputs", "batch/<tag>/seed-N/", "white")
    box(ax, xs[2], ys, w, h, "Simulator traces", "sim_traces/seed-N/", MEET_BG, ec=GREEN, bold=True)
    for y, labels in ((yf, ("plot --nodes", "split-scenario")), (ys, ("run_batch", "sim_to_traces"))):
        arrow(ax, (xs[0] + w / 2, y), (xs[1] - w / 2, y), labels[0])
        arrow(ax, (xs[1] + w / 2, y), (xs[2] - w / 2, y), labels[1])
    # the window feeds the scenario
    ax.add_patch(FancyArrowPatch((xs[2] - 0.6, yf - h / 2), (xs[0] + 0.3, ys + h / 2),
                                 connectionstyle="arc3,rad=0.08", arrowstyle="-|>", mutation_scale=12, lw=1.1,
                                 color=MUTED, ls=(0, (4, 3)), zorder=1))
    ax.text(4.0, 2.62, "build_config_files + build_waypoints", ha="center", fontsize=8.4, color=INK,
            family="monospace", bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none"), zorder=3)
    # the meeting point: the two trace sets share one format
    ax.plot([xs[2] + 0.55, xs[2] + 0.55], [yf - h / 2, ys + h / 2], color=GREEN, lw=1.6, ls=(0, (2, 2)), zorder=1)
    ax.text(xs[2] + 0.68, 2.62, "same IH_<metric>\ntrace format", fontsize=9, color=GREEN, fontweight="bold",
            va="center", linespacing=1.3)
    # compare
    box(ax, 12.0, 2.62, 2.6, 1.3, "compare", "metrics.csv\nhistograms, heatmaps", "white", ec=INK, bold=True)
    arrow(ax, (xs[2] + w / 2, yf), (10.7, 2.95))
    arrow(ax, (xs[2] + w / 2, ys), (10.7, 2.3))
    fig.savefig(os.path.join(HERE, "field-pipeline-map.svg"), format="svg", bbox_inches="tight")
    plt.close(fig)
    print("wrote docs/diagrams/field-pipeline-map.svg")


def windows_figure():
    windows = (("14:50–15:00", "batch-1450-1500/1450-1500"),
               ("15:00–15:20", "batch/1500-1520"),
               ("15:20–15:30", "batch-1520-1530/1520-1530"))
    gaps = {}
    for label, path in windows:
        with open(os.path.join(WORK, path, "validation", "metrics.csv")) as fh:
            for row in csv.DictReader(fh):
                if row["metric"] == "snr":
                    gaps.setdefault(row["src_rab"], []).append(float(row["abs_diff_medians"]))
    styles = {"unit-a": (BLUE, "o"), "unit-b": (INK, "s"), "unit-c": (GREEN, "^"), "unit-d": (AMBER, "D")}
    fig, ax = plt.subplots(figsize=(8.6, 4.4))
    xs = range(len(windows))
    for node, values in sorted(gaps.items()):
        color, marker = styles[node]
        ax.plot(xs, values, color=color, lw=2, marker=marker, ms=8, mec="white", mew=1.2)
        ax.annotate(node, (xs[-1], values[-1]), xytext=(10, 0), textcoords="offset points", va="center",
                    fontsize=10, color=INK, fontweight="bold")
    ax.set_xticks(list(xs), [w[0] for w in windows])
    ax.set_xlim(-0.3, len(windows) - 0.4)
    ax.set_ylim(0, 24)
    ax.set_ylabel("SNR median gap, simulator − field (dB)", fontsize=10, color=MUTED)
    ax.set_xlabel("window (UTC, 2026-03-14)", fontsize=10, color=MUTED)
    ax.set_title("The same gap in every window", loc="left", fontsize=12.5, fontweight="bold", color=INK, pad=10)
    ax.grid(True, axis="y", color=GRID)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(EDGE)
    ax.tick_params(colors=MUTED, labelsize=9.5)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "field-windows.svg"), format="svg", bbox_inches="tight")
    plt.close(fig)
    print("wrote docs/diagrams/field-windows.svg")


if __name__ == "__main__":
    pipeline_map()
    windows_figure()
