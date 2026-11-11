"""Generate jammer-beam.svg, the beam-geometry figure on the "jammers.json" page.

Top-down view of baseline p0-jammer-smoke: three peers and one jammer, with the
60-degree cone the page's "point the beam east" change produces
(azimuth_deg = 90, zenith_deg = 90, beamwidth_deg = 60). Each link is labelled
with its seed-1 SINR at t = 0.3 s from three runs: no jammer (--band=mmwave),
the tracked omni jammer, and the 60-degree east beam. Run it from docs/:

    ../.venv/bin/python diagrams/jammer-beam.py \\
        ../outputs/examples/p0-jammer-smoke-mmwave \\
        ../outputs/examples/p0-jammer-smoke \\
        ../outputs/examples/jam-beam-east
"""
import csv
import json
import math
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Wedge  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "jammer-beam.svg")

INK, MUTED, GRID = "#1f2d3a", "#5b6b7b", "#e6e9ec"
BLUE, AMBER, GREEN, RED = "#2980b9", "#c99a1e", "#27ae60", "#c0392b"
T_PICK = 0.3


def sinr_at(run):
    with open(os.path.join(run, "seed-1", "links.csv"), newline="") as f:
        rows = list(csv.DictReader(f))
    return {(int(r["node_a"]), int(r["node_b"])): float(r["sinr_db"])
            for r in rows if abs(float(r["time_s"]) - T_PICK) < 1e-6}


def main():
    none_run, omni_run, beam_run = sys.argv[1:4]
    with open(os.path.join(omni_run, "inputs", "nodes.json")) as f:
        nodes = json.load(f)
    with open(os.path.join(omni_run, "inputs", "jammers.json")) as f:
        jam = json.load(f)[0]["position"]
    s_none, s_omni, s_beam = sinr_at(none_run), sinr_at(omni_run), sinr_at(beam_run)
    xy = [(n["position"]["x"], n["position"]["y"]) for n in nodes]

    plt.rcParams["font.family"] = ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]
    fig, ax = plt.subplots(figsize=(8.2, 6.2))
    fig.patch.set_facecolor("white")

    # Cone: azimuth 90 (east) is matplotlib angle 0; half-angle 30 deg.
    az, bw = 90.0, 60.0
    centre = 90.0 - az
    ax.add_patch(Wedge((jam["x"], jam["y"]), 75, centre - bw / 2, centre + bw / 2,
                       facecolor=RED, alpha=0.10, edgecolor=RED, linewidth=1, zorder=1))
    ax.text(jam["x"] + 70, jam["y"] - 14, "60° beam\nazimuth_deg = 90", ha="center",
            fontsize=8.5, color=RED)

    for (i, j), off in {(0, 1): (-22, 5), (0, 2): (-8, 6), (1, 2): (8, 6)}.items():
        (x1, y1), (x2, y2) = xy[i], xy[j]
        ax.plot([x1, x2], [y1, y2], color=MUTED, linewidth=1.2, zorder=2)
        label = "%.1f / %.1f / %.1f dB" % (s_none[(i, j)], s_omni[(i, j)], s_beam[(i, j)])
        ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
        if ang > 90:
            ang -= 180
        if ang < -90:
            ang += 180
        ax.text((x1 + x2) / 2 + off[0], (y1 + y2) / 2 + off[1], label, ha="center",
                va="center", fontsize=8.5, color=INK, rotation=ang,
                bbox=dict(facecolor="white", edgecolor="none", pad=1.2))

    for k, (n, (x, y)) in enumerate(zip(nodes, xy)):
        ax.plot([x], [y], "o", color=BLUE, markersize=9, zorder=4)
        ax.text(x, y + 6, "%s (%d)" % (n["id"], k), ha="center", va="bottom", fontsize=9,
                color=INK)
    ax.plot([jam["x"]], [jam["y"]], "D", color=RED, markersize=8, zorder=5)
    ax.text(jam["x"], jam["y"] - 6, "jammer-0\nzenith_deg = 90", ha="center", va="top",
            fontsize=9, color=RED)

    # Compass
    cx, cy = -28, 50
    for dx, dy, lab in ((0, 1, "0° N"), (1, 0, "90° E")):
        ax.annotate("", xy=(cx + 14 * dx, cy + 14 * dy), xytext=(cx, cy),
                    arrowprops=dict(arrowstyle="-|>", color=MUTED, linewidth=1))
        ax.text(cx + 18 * dx, cy + 18 * dy, lab, ha="left" if dx else "center",
                va="center" if dx else "bottom", fontsize=8.5, color=MUTED)

    fig.text(0.02, 0.015, "Link labels: SINR with no jammer / omni jammer / 60° east beam"
             " (seed 1, t = %.1f s)" % T_PICK, fontsize=8.5, color=MUTED)
    ax.set_xlim(-40, 140)
    ax.set_ylim(-42, 80)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("x (m, east)", fontsize=10.5, color=MUTED)
    ax.set_ylabel("y (m, north)", fontsize=10.5, color=MUTED)
    ax.set_title("p0-jammer-smoke, top-down", loc="left", fontsize=12.5, fontweight="bold",
                 color=INK, pad=10)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c9cfd5")
    ax.tick_params(colors=MUTED, labelsize=9.5)

    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(TARGET, format="svg", facecolor="white")
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
