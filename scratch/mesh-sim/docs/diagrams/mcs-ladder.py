"""Generate mcs-ladder.svg, the SINR-to-MCS figure on the mcs.csv page.

It plots the mcs_index the simulator writes for each SINR under the two index
ladders in src/eval/sinr-capacity.h: the 3GPP CQI table (amc_model shannon or
table, indices 0-15) and the Silvus single-stream table (amc_model silvus,
indices 0-6). The thresholds below are copied from MCS_TABLE and
SILVUS_MCS_TABLE in that header. Run it with the project venv from docs/:

    ../.venv/bin/python diagrams/mcs-ladder.py
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "mcs-ladder.svg")

INK, MUTED, GRID = "#1f2d3a", "#5b6b7b", "#e6e9ec"
BLUE, AMBER, GREEN, RED = "#2980b9", "#c99a1e", "#27ae60", "#c0392b"

SINR_MIN_DB = -6.7
CQI = [-6.7, -4.7, -2.3, 0.2, 2.4, 4.3, 5.9, 8.1, 10.3, 11.7, 14.1, 16.3, 18.7, 21.0, 22.7, 25.0]
SILVUS = [-6.7, 2.4, 5.9, 8.1, 11.7, 16.3, 18.7]
X0, X1 = -17.0, 30.0


def ladder(thresholds):
    xs, ys = [X0, SINR_MIN_DB], [0, 0]
    for k, th in enumerate(thresholds):
        xs += [th, th]
        ys += [ys[-1], k]
    xs.append(X1)
    ys.append(len(thresholds) - 1)
    return xs, ys


def main():
    plt.rcParams["font.family"] = ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    fig.patch.set_facecolor("white")

    ax.axvspan(X0, SINR_MIN_DB, color=RED, alpha=0.07, linewidth=0)
    ax.axvline(SINR_MIN_DB, color=RED, linewidth=1, linestyle="--")
    ax.text(X0 + 0.4, 13.6, "SINR < −6.7 dB:\ncapacity_mbps = 0,\nmcs_index still 0",
            fontsize=9, color=RED, va="top")

    xs, ys = ladder(CQI)
    ax.plot(xs, ys, color=BLUE, linewidth=2.2, label="amc_model = shannon or table (3GPP CQI, 0–15)")
    xs, ys = ladder(SILVUS)
    ax.plot(xs, ys, color=AMBER, linewidth=2.2, label="amc_model = silvus (Silvus MCS, 0–6)")

    ax.set_xlim(X0, X1)
    ax.set_ylim(-0.6, 15.8)
    ax.set_yticks(range(0, 16))
    ax.set_xlabel("sinr_db in links.csv (dB)", fontsize=10.5, color=MUTED)
    ax.set_ylabel("mcs_index in mcs.csv", fontsize=10.5, color=MUTED)
    ax.set_title("mcs_index is the highest level whose SINR threshold is met", loc="left",
                 fontsize=12.5, fontweight="bold", color=INK, pad=10)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c9cfd5")
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.legend(loc="lower right", frameon=False, fontsize=9.5)
    fig.tight_layout()
    fig.savefig(TARGET, format="svg")
    print("wrote", TARGET)


if __name__ == "__main__":
    main()
