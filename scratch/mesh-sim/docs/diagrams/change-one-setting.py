"""Generate change-one-setting.svg, the comparison figure on "Change one setting".

It compares two seed-1 runs of the first scenario: the original (10 Mbps
demand) and the copy with demand_mbps = 6000. For each run it draws the
demand, the delivered rate and the link capacity, averaged over the run.
Run it with the project venv from docs/:

    ../.venv/bin/python diagrams/change-one-setting.py \\
        ../outputs/getting-started/01-static-los-baseline \\
        ../outputs/getting-started/01-demand-6000
"""
import csv
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "change-one-setting.svg")
INK, MUTED, GRID = "#1f2d3a", "#5b6b7b", "#e6e9ec"
BLUE, AMBER, GREEN = "#2980b9", "#c99a1e", "#27ae60"


def mean_col(path, key):
    with open(path, newline="") as f:
        vals = [float(r[key]) for r in csv.DictReader(f)]
    return sum(vals) / len(vals)


def main():
    root = os.path.join(HERE, "..", "..", "outputs", "getting-started")
    runs = sys.argv[1:3] or [os.path.join(root, "01-static-los-baseline"),
                             os.path.join(root, "01-demand-6000")]
    labels = ["First run\ndemand_mbps = 10", "This page\ndemand_mbps = 6000"]
    series = {"demand": [], "delivered": [], "capacity": []}
    for run in runs:
        seed = os.path.join(run, "seed-1")
        series["demand"].append(mean_col(os.path.join(seed, "flows.csv"), "demand_mbps"))
        series["delivered"].append(mean_col(os.path.join(seed, "flows.csv"), "delivered_mbps"))
        series["capacity"].append(mean_col(os.path.join(seed, "links.csv"), "capacity_mbps"))

    plt.rcParams["font.family"] = ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    fig.patch.set_facecolor("white")
    width = 0.25
    bars = [("demand", "demand (asked for)", AMBER), ("delivered", "delivered", GREEN),
            ("capacity", "link capacity", BLUE)]
    for i, (key, name, color) in enumerate(bars):
        xs = [x + (i - 1) * width for x in range(len(runs))]
        rects = ax.bar(xs, series[key], width * 0.92, color=color, label=name)
        for r, v in zip(rects, series[key]):
            ax.text(r.get_x() + r.get_width() / 2, v * 1.12, f"{v:,.0f}", ha="center",
                    va="bottom", fontsize=10, color=INK)
    ax.set_yscale("log")
    ax.set_ylim(1, 60000)
    ax.set_xticks(range(len(runs)))
    ax.set_xticklabels(labels, fontsize=11, color=INK)
    ax.set_ylabel("Mbps (log scale), mean over the run", fontsize=10.5, color=MUTED)
    ax.grid(True, axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c9cfd5")
    ax.tick_params(colors=MUTED, labelsize=9.5)
    ax.legend(loc="upper left", fontsize=10, frameon=False, ncol=3)
    fig.tight_layout()
    fig.savefig(TARGET, format="svg", facecolor="white")
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
