"""Generate flow-accounting.svg, the figure on the flows.csv and routes.csv pages.

It draws the first snapshot (t = 0) of 09-congestion-bottleneck: every link with
its capacity and the traffic it carries, and how the router turns three
2000 Mbps demands into delivered rates and latencies. All numbers are read
from the run's links.csv, flows.csv and routes.csv. Run it with the project
venv from docs/, passing the run's output folder:

    ../.venv/bin/python diagrams/flow-accounting.py \\
        ../outputs/examples/09-congestion-bottleneck

The run was made with the simulator binary built from this repository, the
scenario's tracked run.ini and --seeds=1.
"""
import csv
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "flow-accounting.svg")

INK, MUTED, GRID = "#1f2d3a", "#5b6b7b", "#e6e9ec"
BLUE, AMBER, GREEN, RED = "#2980b9", "#c99a1e", "#27ae60", "#c0392b"

NAMES = ["src-a", "src-b", "relay", "dst"]
XY = {0: (0.0, 1.0), 1: (0.0, -1.0), 2: (1.25, 0.0), 3: (2.9, 0.0)}


def read(path):
    with open(path, newline="") as f:
        rows = list(csv.reader(line for line in f if not line.startswith("#")))
    return [dict(zip(rows[0], r)) for r in rows[1:]]


def at_t0(rows):
    return [r for r in rows if float(r["time_s"]) == 0.0]


def main():
    run = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        HERE, "..", "..", "outputs", "examples", "09-congestion-bottleneck")
    seed = os.path.join(run, "seed-1")
    links = at_t0(read(os.path.join(seed, "links.csv")))
    flows = at_t0(read(os.path.join(seed, "flows.csv")))
    routes = at_t0(read(os.path.join(seed, "routes.csv")))

    plt.rcParams["font.family"] = ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]
    fig = plt.figure(figsize=(11, 4.9))
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0.01, 0.04, 0.50, 0.84])
    tx = fig.add_axes([0.53, 0.04, 0.46, 0.84])
    for a in (ax, tx):
        a.set_axis_off()

    # ---- left: the link graph -------------------------------------------
    carried = {}
    for r in links:
        a, b = int(r["node_a"]), int(r["node_b"])
        cap, dlv = float(r["capacity_mbps"]), float(r["delivered_mbps"])
        carried[(a, b)] = dlv
        (x0, y0), (x1, y1) = XY[a], XY[b]
        if cap <= 0.0:
            color, style, width = RED, (0, (4, 3)), 1.2
            label = f"{r['condition']}  {float(r['sinr_db']):.0f} dB\n0 Mbps capacity"
        elif dlv >= cap - 0.05:
            color, style, width = AMBER, "-", 4.0
            label = f"cap {cap:,.0f}\ncarries {dlv:,.0f}  (full)"
        elif dlv > 0:
            color, style, width = BLUE, "-", 2.6
            label = f"cap {cap:,.0f}\ncarries {dlv:,.0f}"
        else:
            color, style, width = MUTED, "-", 1.0
            label = f"cap {cap:,.0f}\ncarries 0"
        ax.plot([x0, x1], [y0, y1], color=color, linestyle=style, linewidth=width, zorder=1)
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        offset = {(0, 1): (-0.33, 0.0), (0, 2): (0.12, 0.30), (1, 2): (0.12, -0.30),
                  (2, 3): (0.0, 0.0), (0, 3): (0.45, 0.42), (1, 3): (0.45, -0.42)}[(a, b)]
        ax.text(mx + offset[0], my + offset[1], label, ha="center", va="center",
                fontsize=8.6, color=color if color != MUTED else MUTED, zorder=3,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none"))
    for i, (x, y) in XY.items():
        ax.scatter([x], [y], s=900, color="white", edgecolor=INK, linewidth=1.6, zorder=4)
        ax.text(x, y, str(i), ha="center", va="center", fontsize=11, fontweight="bold",
                color=INK, zorder=5)
        ax.text(x, y - 0.27 if i != 0 else y + 0.27, NAMES[i], ha="center", va="center",
                fontsize=9.5, color=MUTED, zorder=5)
    ax.set_xlim(-0.6, 3.3)
    ax.set_ylim(-1.45, 1.45)
    ax.set_title("links.csv at t = 0 (capacity and carried traffic, Mbps)", loc="left",
                 fontsize=12, fontweight="bold", color=INK, pad=6)

    # ---- right: how each flow row is built ------------------------------
    tx.set_xlim(0, 1)
    tx.set_ylim(0, 1)
    tx.set_title("How the router fills flows.csv and routes.csv", loc="left",
                 fontsize=12, fontweight="bold", color=INK, pad=6)
    cap23 = next(float(r["capacity_mbps"]) for r in links
                 if (r["node_a"], r["node_b"]) == ("2", "3"))
    demand23 = sum(float(f["demand_mbps"]) for f, rt in zip(flows, routes)
                   if "2;3" in rt["path"])
    scale = cap23 / demand23
    lines = [
        ("1. Path", INK, "bold"),
        ("shortest_path picks the route with the least  Σ 1/capacity.", MUTED, "normal"),
    ]
    for rt in routes:
        lines.append((f"   {rt['src']} → {rt['dst']}:  path {rt['path']},  bottleneck "
                      f"{float(rt['bottleneck_mbps']):,.1f}", BLUE, "normal"))
    lines += [
        ("2. Congestion scaling", INK, "bold"),
        (f"   Edge 2–3 is asked for {demand23:,.0f} Mbps but has {cap23:,.1f}.", MUTED, "normal"),
        (f"   Every flow on it gets demand × {cap23:,.1f} / {demand23:,.0f} = × {scale:.4f}", MUTED,
         "normal"),
        (f"   → delivered_mbps = 2000 × {scale:.4f} = {2000 * scale:,.1f} for all three", AMBER,
         "normal"),
        ("3. Latency (fixed by the path, not by load)", INK, "bold"),
        ("   Σ over hops of  distance / 3×10⁸ m/s  +  0.5 ms", MUTED, "normal"),
    ]
    for f in flows:
        lines.append((f"   {f['src']} → {f['dst']}:  {f['hop_count']} hop(s)  →  "
                      f"latency_ms {f['latency_ms']}", GREEN, "normal"))
    y = 0.97
    for text, color, weight in lines:
        if weight == "bold":
            y -= 0.025
        tx.text(0.0, y, text, fontsize=9.6, color=color, fontweight=weight, va="top")
        y -= 0.068

    fig.savefig(TARGET, format="svg")
    print("wrote", TARGET)


if __name__ == "__main__":
    main()
