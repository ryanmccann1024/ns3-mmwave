"""Generate first-result.svg, the 4-panel figure on the "Understand the result" page.

It plots seed 1 of the 01-static-los-baseline run made on "Your first run":
link SINR, capacity against delivered traffic, MCS index and flow latency.
Run it with the project venv from docs/, passing the run's output folder:

    ../.venv/bin/python diagrams/first-result.py \\
        ../outputs/getting-started/01-static-los-baseline

The figure in the docs was made from a run of the simulator binary built from
this repository, with the scenario's tracked run.ini and --seeds=1.
"""
import csv
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "first-result.svg")

INK, MUTED, GRID = "#1f2d3a", "#5b6b7b", "#e6e9ec"
BLUE, AMBER, GREEN, RED = "#2980b9", "#c99a1e", "#27ae60", "#c0392b"
SINR_MIN_DB = -6.7  # below this a link carries nothing (src/eval/sinr-capacity.h)


def read(path):
    with open(path, newline="") as f:
        rows = [r for r in csv.reader(line for line in f if not line.startswith("#"))]
    head, body = rows[0], rows[1:]
    return [dict(zip(head, r)) for r in body]


def col(rows, key):
    return [float(r[key]) for r in rows]


def style(ax, title, ylabel):
    ax.set_title(title, loc="left", fontsize=12.5, fontweight="bold", color=INK, pad=10)
    ax.set_ylabel(ylabel, fontsize=10.5, color=MUTED)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c9cfd5")
    ax.tick_params(colors=MUTED, labelsize=9.5)
    ax.set_xlim(0, 5)


def main():
    run = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        HERE, "..", "..", "outputs", "getting-started", "01-static-los-baseline")
    seed = os.path.join(run, "seed-1")
    links = read(os.path.join(seed, "links.csv"))
    mcs = read(os.path.join(seed, "mcs.csv"))
    flows = read(os.path.join(seed, "flows.csv"))

    t = col(links, "time_s")
    plt.rcParams["font.family"] = ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]
    fig, axes = plt.subplots(2, 2, figsize=(10, 6.2), sharex=True)
    fig.patch.set_facecolor("white")

    ax = axes[0][0]
    ax.plot(t, col(links, "sinr_db"), color=BLUE, linewidth=2)
    ax.axhline(SINR_MIN_DB, color=RED, linewidth=1, linestyle="--")
    ax.text(4.95, SINR_MIN_DB + 1.5, "no capacity below −6.7 dB", ha="right", fontsize=9, color=RED)
    ax.set_ylim(-10, 45)
    style(ax, "Link SINR", "SINR (dB)")

    ax = axes[0][1]
    ax.plot(t, col(links, "capacity_mbps"), color=BLUE, linewidth=2, label="link capacity")
    ax.plot(col(flows, "time_s"), col(flows, "delivered_mbps"), color=GREEN, linewidth=2,
            label="delivered traffic")
    ax.plot(col(flows, "time_s"), col(flows, "demand_mbps"), color=AMBER, linewidth=1.5,
            linestyle="--", label="demand")
    ax.set_yscale("log")
    ax.set_ylim(1, 20000)
    cap = sorted(col(links, "capacity_mbps"))[len(links) // 2]
    dem = col(flows, "demand_mbps")[0]
    ax.annotate("", xy=(1.2, dem * 1.15), xytext=(1.2, cap / 1.15),
                arrowprops=dict(arrowstyle="<->", color=MUTED, linewidth=1))
    ax.text(1.35, (cap * dem) ** 0.5, f"headroom: about {cap / dem:,.0f}×", fontsize=9.5,
            color=MUTED, va="center")
    ax.legend(loc="center right", fontsize=9, frameon=False)
    style(ax, "Capacity vs. traffic", "Mbps (log scale)")

    ax = axes[1][0]
    ax.step(col(mcs, "time_s"), col(mcs, "mcs_index"), where="post", color=BLUE, linewidth=2)
    ax.set_ylim(0, 16)
    ax.set_yticks([0, 5, 10, 15])
    style(ax, "MCS index", "index (0–15)")
    ax.set_xlabel("simulation time (s)", fontsize=10.5, color=MUTED)

    ax = axes[1][1]
    ax.plot(col(flows, "time_s"), col(flows, "latency_ms"), color=BLUE, linewidth=2)
    ax.set_ylim(0, 1.0)
    style(ax, "Flow latency", "latency (ms)")
    ax.set_xlabel("simulation time (s)", fontsize=10.5, color=MUTED)

    fig.tight_layout(h_pad=2.2, w_pad=2.5)
    fig.savefig(TARGET, format="svg", facecolor="white")
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
