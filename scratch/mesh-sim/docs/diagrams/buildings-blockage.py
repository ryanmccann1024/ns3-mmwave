"""Generate buildings-blockage.svg, the figure on the "buildings.json" page.

Left panel: top-down map of baseline 03-building-blockage (node-a, the "wall"
building, node-b's path, and the sight line at the first NLOS and first LOS
tick). Right panel: link SINR over time from seed 1 of that scenario, with the
same scenario minus the building (condition_model = static_los) for reference.
Run it with the project venv from docs/, passing both output folders:

    ../.venv/bin/python diagrams/buildings-blockage.py \\
        ../outputs/examples/03-building-blockage \\
        ../outputs/examples/03-no-building-static-los

The first folder comes from the tracked scenario run with --seeds=1. The second
is the same run.ini with buildings_file blank and condition_model = static_los.
"""
import csv
import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "buildings-blockage.svg")

INK, MUTED, GRID = "#1f2d3a", "#5b6b7b", "#e6e9ec"
BLUE, AMBER, GREEN, RED = "#2980b9", "#c99a1e", "#27ae60", "#c0392b"


def read(path):
    with open(path, newline="") as f:
        rows = list(csv.reader(line for line in f if not line.startswith("#")))
    head, body = rows[0], rows[1:]
    return [dict(zip(head, r)) for r in body]


def style(ax, title):
    ax.set_title(title, loc="left", fontsize=12.5, fontweight="bold", color=INK, pad=10)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c9cfd5")
    ax.tick_params(colors=MUTED, labelsize=9.5)


def main():
    run = sys.argv[1]
    ref = sys.argv[2]
    with open(os.path.join(run, "inputs", "buildings.json")) as f:
        wall = json.load(f)[0]["bounds"]
    pos = read(os.path.join(run, "seed-1", "positions.csv"))
    links = read(os.path.join(run, "seed-1", "links.csv"))
    ref_links = read(os.path.join(ref, "seed-1", "links.csv"))

    a = next(p for p in pos if p["node_id"] == "0")
    b_path = [p for p in pos if p["node_id"] == "1"]
    first_los = next(r for r in links if r["condition"] == "LOS")
    t_los = float(first_los["time_s"])
    b_at = {round(float(p["time_s"]), 1): p for p in b_path}
    b_first_los = b_at[round(t_los, 1)]

    plt.rcParams["font.family"] = ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(12, 4.3),
                                 gridspec_kw={"width_ratios": [1.45, 1]})
    fig.patch.set_facecolor("white")

    # --- Map ---
    ax.add_patch(Rectangle((wall["x_min"], wall["y_min"]), wall["x_max"] - wall["x_min"],
                           wall["y_max"] - wall["y_min"], facecolor="#d5dbe1",
                           edgecolor=MUTED, linewidth=1.2, zorder=2))
    ax.text((wall["x_min"] + wall["x_max"]) / 2, wall["y_max"] + 3, "wall, z 0–20 m",
            ha="center", va="bottom", fontsize=9, color=INK, zorder=3)
    ax.plot([wall["x_min"]], [wall["y_min"]], "o", color=INK, markersize=3.5, zorder=4)
    ax.text(wall["x_min"] - 3, wall["y_min"] - 2, "near corner\n(90, −20)", ha="right",
            va="top", fontsize=8.5, color=MUTED)
    ax_x, ax_y = float(a["x"]), float(a["y"])
    bx_xy = [(float(p["x"]), float(p["y"])) for p in b_path]
    ax.plot([ax_x, bx_xy[0][0]], [ax_y, bx_xy[0][1]], color=RED,
            linewidth=1.2, linestyle="--", zorder=1)
    ax.plot([ax_x, float(b_first_los["x"])], [ax_y, float(b_first_los["y"])], color=GREEN,
            linewidth=1.4, zorder=1)
    nlos = [xy for xy, r in zip(bx_xy, links) if r["condition"] == "NLOS"]
    los = [xy for xy, r in zip(bx_xy, links) if r["condition"] == "LOS"]
    ax.plot([p[0] for p in nlos], [p[1] for p in nlos], color=AMBER, linewidth=5,
            solid_capstyle="butt", zorder=3)
    ax.plot([p[0] for p in los], [p[1] for p in los], color=GREEN, linewidth=5,
            solid_capstyle="butt", zorder=3)
    ax.annotate("", xy=(bx_xy[-1][0], bx_xy[-1][1] - 3), xytext=bx_xy[-1],
                arrowprops=dict(arrowstyle="-|>", color=INK, linewidth=1.2))
    ax.plot([ax_x], [ax_y], "o", color=BLUE, markersize=9, zorder=4)
    ax.plot([bx_xy[0][0]], [bx_xy[0][1]], "o", color=BLUE, markersize=9, zorder=4)
    ax.text(ax_x, ax_y + 6, "node-a (0)\nfixed", ha="center", va="bottom", fontsize=9, color=INK)
    ax.text(bx_xy[0][0] + 5, bx_xy[0][1] + 6, "node-b (1)\nt = 0 s", ha="center", va="bottom",
            fontsize=9, color=INK)
    ax.text(bx_xy[0][0] + 6, -22, "NLOS\nt 0–%.1f s" % (t_los - 0.1), ha="left", va="center",
            fontsize=9, color=AMBER)
    ax.text(bx_xy[0][0] + 6, -53, "LOS\nt %.1f–30 s" % t_los, ha="left", va="center",
            fontsize=9, color=GREEN)
    ax.text(150, -36.5, "first LOS tick\ny = %.1f m" % float(b_first_los["y"]), ha="center",
            va="top", fontsize=8.5, color=GREEN, rotation=-12)
    ax.text(158, -3, "t = 0 s: line crosses the wall", ha="center", va="top", fontsize=8.5,
            color=RED)
    ax.set_xlim(-15, 235)
    ax.set_ylim(-70, 35)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel("x (m, east)", fontsize=10.5, color=MUTED)
    ax.set_ylabel("y (m, north)", fontsize=10.5, color=MUTED)
    style(ax, "03-building-blockage, top-down")

    # --- SINR ---
    t = [float(r["time_s"]) for r in links]
    s = [float(r["sinr_db"]) for r in links]
    bx.axvspan(0, t_los, color=AMBER, alpha=0.12, linewidth=0)
    bx.axvspan(t_los, 30, color=GREEN, alpha=0.12, linewidth=0)
    bx.plot([float(r["time_s"]) for r in ref_links], [float(r["sinr_db"]) for r in ref_links],
            color=MUTED, linewidth=1.2, linestyle="--", label="no building (static_los)")
    bx.plot(t, s, color=BLUE, linewidth=1.8, label="with buildings.json")
    nl = [v for v, r in zip(s, links) if r["condition"] == "NLOS"]
    lo = [v for v, r in zip(s, links) if r["condition"] == "LOS"]
    bx.text(11, 4, "NLOS, building\nmean %.1f dB" % (sum(nl) / len(nl)), ha="center",
            fontsize=9.5, color=AMBER)
    bx.text(26.2, 18, "LOS\nmean %.1f dB" % (sum(lo) / len(lo)), ha="center",
            fontsize=9.5, color=GREEN)
    bx.set_xlim(0, 30)
    bx.set_ylim(0, 35)
    bx.set_xlabel("simulation time (s)", fontsize=10.5, color=MUTED)
    bx.set_ylabel("SINR (dB)", fontsize=10.5, color=MUTED)
    bx.legend(loc="lower right", fontsize=9, frameon=False)
    style(bx, "Link node-a ↔ node-b, seed 1")

    fig.tight_layout(w_pad=3)
    fig.savefig(TARGET, format="svg", facecolor="white")
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
