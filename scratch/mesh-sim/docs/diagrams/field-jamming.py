"""Generate the three figures on the "Jammed windows" field-data page.

field-jam-map.svg       the window from above: node tracks, the jammer, the
                        simulator's hard 60-degree cone and the practice
                        bundle's smooth beam
field-jam-timeline.svg  one link's SNR over the window: the field reports, and
                        the simulator without and with the jammer
field-jam-gaps.svg      each node's SNR median gap, without and with the jammer

It reads the practice-run outputs written by docs/diagrams/field-example.py
(run that first). From docs/:

    ../.venv/bin/python diagrams/field-jamming.py
"""
import csv
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Wedge  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WORK = os.path.join(ROOT, "outputs", "docs-figures", "field-example", "work")
TAG = "1000-1020"

INK, MUTED, GRID, EDGE = "#1f2d3a", "#5b6b7b", "#e6e9ec", "#c9cfd5"
BLUE, AMBER, GREEN, RED = "#2980b9", "#c99a1e", "#27ae60", "#c0392b"
NODE_STYLE = {"unit-a": "o", "unit-b": "s", "unit-c": "^", "unit-d": "D"}


def style(ax, title, xlabel, ylabel):
    ax.set_title(title, loc="left", fontsize=12.5, fontweight="bold", color=INK, pad=10)
    ax.set_xlabel(xlabel, fontsize=10, color=MUTED)
    ax.set_ylabel(ylabel, fontsize=10, color=MUTED)
    ax.grid(True, color=GRID)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(EDGE)
    ax.tick_params(colors=MUTED, labelsize=9.5)


def read(path):
    with open(path) as fh:
        return list(csv.DictReader(fh))


def jammer():
    with open(os.path.join(WORK, "jam", "batch", TAG, "inputs", "jammers.json")) as fh:
        return json.load(fh)[0]


def map_figure():
    jam = jammer()
    gps = read(os.path.join(WORK, "windows", TAG, "gps_all_nodes_trace.csv"))
    fig, ax = plt.subplots(figsize=(8.8, 6.6))
    jx, jy = jam["position"]["x"], jam["position"]["y"]
    az, bw = jam["azimuth_deg"], jam["beamwidth_deg"]
    reach = 1500
    # matplotlib angles: counterclockwise from east; compass: clockwise from north
    center = 90 - az
    # the practice bundle's smooth beam: shade by off-axis loss bands
    for off, alpha in ((60, 0.07), (45, 0.08), (30, 0.10)):
        ax.add_patch(Wedge((jx, jy), reach, center - off, center + off, fc=AMBER, ec="none", alpha=alpha,
                           zorder=0))
    ax.add_patch(Wedge((jx, jy), reach, center - bw / 2, center + bw / 2, fill=False, ec=RED, lw=1.8,
                       ls=(0, (5, 3)), zorder=1))
    nodes = {}
    for row in gps:
        nodes.setdefault(row["node"], ([], []))
        nodes[row["node"]][0].append(float(row["east_m"]))
        nodes[row["node"]][1].append(float(row["north_m"]))
    for node, (xs, ys) in sorted(nodes.items()):
        ax.plot(xs, ys, color=BLUE, lw=1.4, zorder=2)
        ax.scatter([xs[0]], [ys[0]], marker=NODE_STYLE[node], s=70, color=BLUE, ec="white", lw=1.2, zorder=3)
        ax.annotate(node, (xs[0], ys[0]), xytext=(8, 8), textcoords="offset points", fontsize=10,
                    fontweight="bold", color=INK, zorder=4,
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))
    ax.scatter([jx], [jy], marker="*", s=320, color=RED, ec="white", lw=1, zorder=4)
    ax.annotate("jammer ew-1\n33 dBm + 10 dBi", (jx, jy), xytext=(12, -6), textcoords="offset points",
                fontsize=9.5, color=INK, va="top", zorder=4)
    ax.text(0.02, 0.03, "Red dashed: the simulator's beam, full power inside the 60° cone, none outside.\n"
                        "Amber shading: the practice bundle's beam, fading smoothly off axis (3 dB at 30°, 12 dB at 60°).",
            transform=ax.transAxes, fontsize=9, color=INK, va="bottom",
            bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=EDGE))
    allx = [x for xs, _ in nodes.values() for x in xs] + [jx]
    ally = [y for _, ys in nodes.values() for y in ys] + [jy]
    pad = 120
    ax.set_xlim(min(allx) - pad, max(allx) + pad)
    ax.set_ylim(min(ally) - 3 * pad, max(ally) + pad)
    ax.set_aspect("equal")
    style(ax, "Window 10:00-10:20 from above", "east (m)", "north (m)")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "field-jam-map.svg"), format="svg", bbox_inches="tight")
    plt.close(fig)
    print("wrote docs/diagrams/field-jam-map.svg")


def sim_link(variant, a=0, b=1):
    rows = read(os.path.join(WORK, variant, "batch", TAG, "seed-1", "links.csv"))
    pts = [(float(r["time_s"]), float(r["sinr_db"])) for r in rows
           if int(r["node_a"]) == a and int(r["node_b"]) == b]
    return zip(*pts)


def timeline_figure():
    jam = jammer()
    iv = jam["intervals"][0]
    field = read(os.path.join(WORK, "windows", TAG, "unit-a", "csvs", "unit-a",
                              "IH_snr__unit-a_to_neighbors_trace.csv"))
    fx = [float(r["sec"]) for r in field if r["tag_sta_mac"] == "unit-b"]
    fy = [float(r["snr_db"]) for r in field if r["tag_sta_mac"] == "unit-b"]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.axvspan(iv["start"], iv["end"], color=RED, alpha=0.07, lw=0)
    ax.text((iv["start"] + iv["end"]) / 2, 0.97, "jamming trial", transform=ax.get_xaxis_transform(),
            ha="center", va="top", fontsize=10, color=RED, fontweight="bold")
    t, s = sim_link("nojam")
    ax.plot(list(t), list(s), color=MUTED, lw=1.3, label="simulator, no jammer")
    t, s = sim_link("jam")
    ax.plot(list(t), list(s), color=RED, lw=1.6, label="simulator, with jammers.json")
    ax.scatter(fx, fy, s=12, color=BLUE, zorder=3, label="field reports (practice bundle)")
    ax.axhline(-6.7, color=INK, lw=0.8, ls=(0, (3, 3)))
    ax.text(1195, -6.7, "−6.7 dB: link carries nothing", fontsize=8.8, color=INK, ha="right", va="bottom")
    ax.set_xlim(0, 1200)
    style(ax, "unit-a and unit-b: SNR through the window", "seconds into the window", "SNR (dB)")
    ax.legend(loc="upper center", frameon=False, fontsize=9, labelcolor=INK, ncol=3, bbox_to_anchor=(0.5, -0.16))
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "field-jam-timeline.svg"), format="svg", bbox_inches="tight")
    plt.close(fig)
    print("wrote docs/diagrams/field-jam-timeline.svg")


def gaps_figure():
    gap = {}
    for variant in ("nojam", "jam"):
        for r in read(os.path.join(WORK, variant, "batch", TAG, "validation", "metrics.csv")):
            if r["metric"] == "snr":
                gap.setdefault(r["src_rab"], {})[variant] = float(r["abs_diff_medians"])
    nodes = sorted(gap)
    fig, ax = plt.subplots(figsize=(8.4, 3.8))
    for i, node in enumerate(nodes):
        a, b = gap[node]["nojam"], gap[node]["jam"]
        ax.plot([a, b], [i, i], color=EDGE, lw=3, zorder=1, solid_capstyle="round")
        ax.scatter([a], [i], s=80, color=MUTED, zorder=2, label="no jammer" if i == 0 else None)
        ax.scatter([b], [i], s=80, color=RED, zorder=2, label="with jammers.json" if i == 0 else None)
        ax.text(max(a, b) + 0.6, i, f"{a:.1f} → {b:.1f} dB", va="center", fontsize=9.5, color=INK)
    ax.set_yticks(range(len(nodes)), nodes)
    ax.set_xlim(0, 27)
    ax.invert_yaxis()
    style(ax, "SNR median gap, simulator − field", "dB", "")
    ax.legend(loc="lower left", frameon=False, fontsize=9, labelcolor=INK)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "field-jam-gaps.svg"), format="svg", bbox_inches="tight")
    plt.close(fig)
    print("wrote docs/diagrams/field-jam-gaps.svg")


if __name__ == "__main__":
    map_figure()
    timeline_figure()
    gaps_figure()
