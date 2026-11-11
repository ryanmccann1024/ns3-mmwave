"""Generate amc-capacity.svg, the SINR-to-capacity figure on "Channel models: 3GPP and NYU".

It draws link capacity against SINR for the three amc_model values at a given
bandwidth (400 MHz, the run.ini default). The CQI and Silvus tables are read
straight from src/eval/sinr-capacity.h, so the figure follows the code; the
three curves apply the same rules as SinrToCapacity() in that header.
Run it with the project venv from scratch/mesh-sim/:

    .venv/bin/python docs/diagrams/amc-capacity.py
"""
import math
import os
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
HEADER = os.path.join(HERE, "..", "..", "src", "eval", "sinr-capacity.h")
TARGET = os.path.join(HERE, "amc-capacity.svg")
INK, MUTED, GRID = "#1f2d3a", "#5b6b7b", "#e6e9ec"
BLUE, AMBER, GREEN, RED = "#2980b9", "#c99a1e", "#27ae60", "#c0392b"
BANDWIDTH_HZ = 400e6


def table(src, name):
    body = re.search(name + r"\[\] = \{(.*?)\n\};", src, re.S).group(1)
    return [[float(x) if re.fullmatch(r"-?[\d.]+", x) else x.strip('"')
             for x in (v.strip() for v in row.split(","))]
            for row in re.findall(r"\{([^{}]*)\}", body)]


def main():
    with open(HEADER) as f:
        src = f.read()
    sinr_min = float(re.search(r"SINR_MIN_DB = (-?[\d.]+)", src).group(1))
    cqi = table(src, "MCS_TABLE")                     # [sinr_min_db, spectral_eff]
    silvus = table(src, "SILVUS_MCS_TABLE")[:7]       # single-stream rows, MCS 0-6

    def step(rows, sinr, value):
        best = None
        for row in rows:
            if sinr >= row[0]:
                best = row
        return 0.0 if sinr < sinr_min or best is None else value(best)

    sinrs = [-10 + 0.05 * k for k in range(1001)]
    shannon = [0.0 if s < sinr_min else BANDWIDTH_HZ * math.log2(1 + 10 ** (s / 10)) / 1e6
               for s in sinrs]
    tab = [step(cqi, s, lambda r: r[1] * BANDWIDTH_HZ / 1e6) for s in sinrs]
    sil = [step(silvus, s, lambda r: r[4] * BANDWIDTH_HZ / 20e6) for s in sinrs]

    plt.rcParams["font.family"] = ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    fig.patch.set_facecolor("white")
    ax.plot(sinrs, shannon, color=BLUE, linewidth=2, label="shannon  B·log₂(1+SINR)")
    ax.plot(sinrs, tab, color=GREEN, linewidth=2, label="table  CQI 0–15 spectral efficiency × B")
    ax.plot(sinrs, sil, color=AMBER, linewidth=2, label="silvus  MCS 0–6 rate × B / 20 MHz")
    ax.axvline(sinr_min, color=RED, linewidth=1, linestyle="--")
    ax.text(sinr_min - 0.6, 3000, f"capacity 0 below {sinr_min} dB", fontsize=9, color=RED,
            rotation=90, ha="right", va="center")
    for value, color in ((tab[-1], GREEN), (sil[-1], AMBER)):
        ax.text(40.5, value, f"{value:,.0f}", fontsize=9, color=color, va="center")
    ax.set_xlim(-10, 44)
    ax.set_ylim(0, 6000)
    ax.set_xlabel("SINR (dB)", fontsize=10.5, color=MUTED)
    ax.set_ylabel("capacity_mbps at 400 MHz", fontsize=10.5, color=MUTED)
    ax.set_title("Link capacity by amc_model", loc="left", fontsize=12.5, fontweight="bold",
                 color=INK, pad=10)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c9cfd5")
    ax.tick_params(colors=MUTED, labelsize=9.5)
    ax.legend(loc="upper left", bbox_to_anchor=(0.12, 1.0), fontsize=9.5, frameon=False)
    fig.tight_layout()
    fig.savefig(TARGET, format="svg", facecolor="white")
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
