"""Draw the before-and-after figures for the field-data "Transforms and assumptions" pages.

Every figure is drawn from the practice-bundle run that field-example.py leaves
under ../outputs/docs-figures/field-example/ (raw/ is the invented bundle,
work/ the real pipeline's workspace). Nothing here reruns a tool or changes a
value: each figure reads the files a pipeline step wrote and shows what that
step did to the data.

field-rcpi-antennas.svg  unit-d's four raw antenna RSSI values and the RCPI the
                         loader keeps (mean of antennas above -110 dBm)
field-window-cut.svg     unit-b's SNR samples over the whole logged day, the
                         window split-scenario keeps, and the elapsed-time reset
field-waypoints.svg      unit-b's GPS track in the window against the 20
                         waypoints build_waypoints wrote, and the distance between them
field-seed-average.svg   one simulator seed against the 5-seed row-wise average
                         compare makes, for one link and for unit-b's whole pile
field-ks-cdf.svg         the empirical CDFs compare measures K-S D on, for
                         unit-b's SNR, with the largest gap marked
field-pathloss.svg       path loss against distance: the simulator's 3GPP RMa
                         line-of-sight formula at 1.5 m, its seed-1 samples,
                         free space, and the practice bundle's invented formula

From docs/, after field-example.py has run:

    ../.venv/bin/python diagrams/field-example.py --sim-binary <BIN>   # once, ~40 s
    ../.venv/bin/python diagrams/field-transforms.py                   # these figures, a few seconds
"""
import json
import math
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))  # scratch/mesh-sim
OUT = os.path.join(ROOT, "outputs", "docs-figures", "field-example")
RAW, WORK = os.path.join(OUT, "raw"), os.path.join(OUT, "work")
DAY, TAG = "2026-03-14", "1500-1520"
BATCH = os.path.join(WORK, "batch", TAG)
SEEDS = (1, 2, 3, 4, 5)

INK, MUTED, GRID, EDGE = "#1f2d3a", "#5b6b7b", "#e6e9ec", "#c9cfd5"
BLUE, AMBER, GREEN, RED = "#2980b9", "#c99a1e", "#27ae60", "#c0392b"
LIGHT = "#b8c2cc"


# ---------------------------------------------------------------- helpers

def style(ax, title, xlabel, ylabel):
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", color=INK, pad=8)
    ax.set_xlabel(xlabel, fontsize=10, color=MUTED)
    ax.set_ylabel(ylabel, fontsize=10, color=MUTED)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(EDGE)
    ax.tick_params(colors=MUTED, labelsize=9)


def label(ax, x, y, text, color=INK, **kw):
    kw.setdefault("fontsize", 9.5)
    ax.annotate(text, (x, y), color=color, zorder=8,
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.9), **kw)


def save(fig, name):
    path = os.path.join(HERE, name)
    fig.savefig(path, format="svg", bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {os.path.relpath(path, ROOT)}")


def clock_min(t_utc):
    """Minutes after 14:50 UTC, the start of the practice bundle's logs."""
    t = pd.to_datetime(t_utc, utc=True)
    return (t - pd.Timestamp(f"{DAY} 14:50:00", tz="UTC")).dt.total_seconds() / 60.0


def ecdf(values):
    v = np.sort(values)
    return v, np.arange(1, v.size + 1) / v.size


# ---------------------------------------------------------------- figures

def figure_rcpi():
    """unit-d -> unit-a: raw antennas, the -110 dBm drop, and the RCPI mean."""
    ns = pd.read_csv(os.path.join(RAW, "unit-d", "silvus", "network_status.csv"))
    t0 = int(pd.Timestamp(f"{DAY} 15:00:00", tz="UTC").value)
    ns = ns[(ns["neighbor"] == 3101) & (ns["time"] >= t0) & (ns["time"] < t0 + 180 * 10**9)]
    t = (ns["time"].to_numpy() - t0) / 1e9
    ants = ns[[f"rssi_ant{i}" for i in range(1, 5)]].to_numpy(dtype=float)
    kept = np.where(ants > -110, ants, np.nan)
    rcpi = np.nanmean(kept, axis=1)
    naive = ants.mean(axis=1)

    fig, ax = plt.subplots(figsize=(10.5, 4.6))
    style(ax, "unit-d hearing unit-a: four antennas in, one RCPI value out",
          "seconds after 15:00:00 UTC", "power (dBm)")
    for k in range(3):
        ax.scatter(t, ants[:, k], s=9, color=LIGHT, zorder=3)
    good4 = ants[:, 3] > -110
    ax.scatter(t[good4], ants[good4, 3], s=9, color=LIGHT, zorder=3)
    ax.scatter(t[~good4], ants[~good4, 3], s=26, marker="x", color=RED, zorder=4, linewidth=1.2)
    ax.axhline(-110, color=RED, linewidth=1, linestyle=(0, (4, 3)), zorder=2)
    ax.plot(t, naive, color=AMBER, linewidth=1.2, linestyle=(0, (5, 3)), zorder=5)
    ax.plot(t, rcpi, color=BLUE, linewidth=2.0, zorder=6)
    ax.set_xlim(0, 236)
    ax.set_ylim(-125, -70)
    label(ax, 182, rcpi[-1], "RCPI kept\n(mean of antennas > −110)", BLUE,
          xytext=(0, 4), textcoords="offset points", fontweight="bold", va="bottom")
    label(ax, 182, -97, "dashed: the mean if\n−120 were kept", AMBER, va="center")
    label(ax, 2, -110, "−110 dBm: at or below is dropped", RED,
          xytext=(0, 4), textcoords="offset points", va="bottom")
    label(ax, t[~good4][0], -120, "antenna 4 logs −120 (blocked)", RED,
          xytext=(8, -4), textcoords="offset points", va="top")
    label(ax, 182, -90, "grey dots: antennas 1–4\n(raw rssi_ant1…4)", MUTED, va="center")
    save(fig, "field-rcpi-antennas.svg")
    drop = ~good4
    return {"rows": int(t.size), "dropped": int(drop.sum()),
            "naive_gap_db": float((rcpi[drop] - naive[drop]).mean())}


def figure_window():
    """unit-b SNR over the day, the window kept, and its sec column reset to 0."""
    day = pd.read_csv(os.path.join(WORK, "daily", DAY, "unit-b", "csvs", "unit-b",
                                   "IH_snr__unit-b_to_neighbors_trace.csv"))
    win = pd.read_csv(os.path.join(WORK, "windows", TAG, "unit-b", "csvs", "unit-b",
                                   "IH_snr__unit-b_to_neighbors_trace.csv"))
    dm, wm = clock_min(day["t_utc"]), clock_min(win["t_utc"])
    inside = (dm >= 10) & (dm < 30)

    fig, (ax, bx) = plt.subplots(2, 1, figsize=(10.5, 6.4), sharex=True,
                                 gridspec_kw={"height_ratios": [2.2, 1], "hspace": 0.32})
    style(ax, "split-scenario keeps one clock window of every trace",
          "", "SNR reported (dB)")
    ax.axvspan(10, 30, color=GRID, alpha=0.7, zorder=0, lw=0)
    ax.scatter(dm[~inside], day["snr_db"][~inside], s=6, color=LIGHT, zorder=3)
    ax.scatter(wm, win["snr_db"], s=6, color=BLUE, zorder=4)
    top = float(day["snr_db"].max()) + 4
    ax.set_ylim(None, top + 4)
    label(ax, 20, top, f"kept: [15:00, 15:20)  ·  {len(win):,} of {len(day):,} samples",
          INK, ha="center", va="center", fontweight="bold")
    label(ax, 0.5, top, "dropped", MUTED, va="center")
    label(ax, 39.5, top, "dropped", MUTED, va="center", ha="right")

    style(bx, "and restarts each file's elapsed time at 0", "UTC clock time",
          "sec column (s)")
    bx.axvspan(10, 30, color=GRID, alpha=0.7, zorder=0, lw=0)
    bx.plot(dm, day["sec"], color=LIGHT, linewidth=2, zorder=3)
    bx.plot(wm, win["sec"], color=BLUE, linewidth=2, zorder=4)
    label(bx, 34, float(day["sec"].iloc[-1]) * 0.80, "daily file: 0 at 14:50", MUTED, ha="center")
    label(bx, 21.5, float(win["sec"].max()) * 0.12, "window file: 0 at 15:00", BLUE,
          va="center")
    ticks = [0, 5, 10, 15, 20, 25, 30, 35, 40]
    bx.set_xticks(ticks)
    bx.set_xticklabels([f"{14 + (50 + m) // 60}:{(50 + m) % 60:02d}" for m in ticks])
    bx.set_xlim(-0.5, 40.5)
    save(fig, "field-window-cut.svg")
    return {"day_rows": int(len(day)), "win_rows": int(len(win)),
            "win_sec_max": float(win["sec"].max())}


def figure_waypoints():
    """unit-b: the window's GPS fixes against the 20 waypoints, and the gap."""
    gps = pd.read_csv(os.path.join(WORK, "windows", TAG, "gps_all_nodes_trace.csv"))
    nodes = json.load(open(os.path.join(WORK, "scenarios", TAG, "nodes.json")))
    wp = next(n for n in nodes if n["id"] == "unit-b")["waypoints"]
    wt = np.array([w["t"] for w in wp])
    wx, wy = np.array([w["x"] for w in wp]), np.array([w["y"] for w in wp])
    g = gps[gps["node"] == "unit-b"].sort_values("sec_since_origin")
    t = g["sec_since_origin"].to_numpy() - g["sec_since_origin"].iloc[0]
    x, y = g["east_m"].to_numpy(), g["north_m"].to_numpy()
    err = np.hypot(np.interp(t, wt, wx) - x, np.interp(t, wt, wy) - y)

    fig, (ax, bx) = plt.subplots(1, 2, figsize=(11.5, 5.0),
                                 gridspec_kw={"width_ratios": [1, 1.25], "wspace": 0.28})
    lap = 6
    style(ax, "First lap: track and waypoint path", "east of the day's mean fix (m)",
          "north of the day's mean fix (m)")
    ax.plot(x[t <= wt[lap]], y[t <= wt[lap]], color=BLUE, linewidth=1.8, zorder=3)
    ax.plot(wx[:lap + 1], wy[:lap + 1], color=AMBER, linewidth=1.5, zorder=4)
    ax.scatter(wx[:lap + 1], wy[:lap + 1], s=34, marker="s", color=AMBER, edgecolor="white",
               linewidth=0.8, zorder=5)
    cx, cy = float(np.mean(x)), float(np.mean(y))
    for k in range(lap + 1):
        a = math.atan2(wy[k] - cy, wx[k] - cx)
        if math.cos(a) < -0.9:      # left edge: label inside the loop, clear of the y axis
            ax.annotate(f"{wt[k]:.0f} s", (wx[k], wy[k]), xytext=(9, 4), textcoords="offset points",
                        fontsize=8.5, color=AMBER, zorder=7, va="bottom")
            continue
        ax.annotate(f"{wt[k]:.0f} s", (wx[k], wy[k]), xytext=(16 * math.cos(a), 14 * math.sin(a)),
                    textcoords="offset points", fontsize=8.5, color=AMBER, zorder=7,
                    ha="left" if math.cos(a) > 0.3 else "right" if math.cos(a) < -0.3 else "center",
                    va="bottom" if math.sin(a) > 0.3 else "top" if math.sin(a) < -0.3 else "center")
    ax.set_aspect("equal", adjustable="datalim")
    ax.margins(0.16)
    label(ax, cx, cy + 30, "GPS track,\n1 fix per s", BLUE, ha="center", va="bottom",
          fontweight="bold")
    label(ax, cx, cy - 30, "20 waypoints,\nstraight lines between", AMBER, ha="center",
          va="top", fontweight="bold")

    style(bx, "Distance from the real position", "seconds into the scenario",
          "waypoint path − GPS (m)")
    bx.plot(t, err, color=BLUE, linewidth=1.4, zorder=3)
    bx.scatter(wt, np.zeros_like(wt), s=22, marker="s", color=AMBER, zorder=4, clip_on=False)
    bx.axhline(err.mean(), color=MUTED, linewidth=1, linestyle=(0, (4, 3)))
    bx.set_ylim(-2, err.max() * 1.25)
    bx.set_xlim(0, t[-1])
    label(bx, t[-1] * 0.5, err.mean(), f"mean {err.mean():.0f} m", MUTED, ha="center",
          xytext=(0, -6), textcoords="offset points", va="top")
    label(bx, t[int(np.argmax(err))], err.max(), f"max {err.max():.0f} m", INK,
          xytext=(6, 6), textcoords="offset points", ha="left", va="bottom")
    label(bx, wt[1], 0, "0 at each waypoint", AMBER, xytext=(4, 8),
          textcoords="offset points", va="bottom")
    save(fig, "field-waypoints.svg")
    real = float(np.sum(np.hypot(np.diff(x), np.diff(y))))
    path = float(np.sum(np.hypot(np.diff(wx), np.diff(wy))))
    return {"spacing_s": float(np.diff(wt).mean()), "err_mean": float(err.mean()),
            "err_max": float(err.max()), "real_path_m": real, "wp_path_m": path}


def figure_seed_average():
    """One seed against the 5-seed row-wise mean, for one link and one node's pile."""
    links = [pd.read_csv(os.path.join(BATCH, f"seed-{s}", "links.csv")) for s in SEEDS]
    ab = np.stack([L[(L["node_a"] == 0) & (L["node_b"] == 1)]["sinr_db"].to_numpy() for L in links])
    tt = links[0][(links[0]["node_a"] == 0) & (links[0]["node_b"] == 1)]["time_s"].to_numpy()
    mean_ab = ab.mean(axis=0)
    piles = np.stack([pd.read_csv(os.path.join(
        BATCH, "sim_traces", f"seed-{s}", "csvs", "unit-b",
        "IH_snr__unit-b_to_neighbors_trace.csv"))["snr_db"].to_numpy() for s in SEEDS])
    avg = piles.mean(axis=0)

    fig, (ax, bx) = plt.subplots(1, 2, figsize=(11.5, 4.8),
                                 gridspec_kw={"width_ratios": [1.45, 1], "wspace": 0.25})
    span = tt <= 360
    style(ax, "One link, unit-a to unit-b, first 6 minutes", "simulated time (s)", "SINR (dB)")
    for k in range(1, len(SEEDS)):
        ax.plot(tt[span], ab[k, span], color=LIGHT, linewidth=0.8, zorder=2)
    ax.plot(tt[span], ab[0, span], color=AMBER, linewidth=1.3, zorder=3)
    ax.plot(tt[span], mean_ab[span], color=BLUE, linewidth=2.0, zorder=4)
    spread = float((ab - mean_ab).std())
    i = int(np.argmin(np.abs(tt - 300)))
    label(ax, 300, ab[0, i], "seed 1", AMBER, xytext=(0, 14), textcoords="offset points",
          ha="center", fontweight="bold")
    label(ax, 300, mean_ab[i], "mean of 5 seeds", BLUE, xytext=(0, -16),
          textcoords="offset points", ha="center", va="top", fontweight="bold")
    label(ax, 6, ab[:, span].min(), "seeds 2–5", MUTED, va="bottom")

    style(bx, "unit-b's whole pile, as compare sees it", "SINR (dB)", "density")
    bins = np.linspace(min(piles.min(), avg.min()), max(piles.max(), avg.max()), 45)
    d1, _ = np.histogram(piles[0], bins=bins, density=True)
    d2, _ = np.histogram(avg, bins=bins, density=True)
    bx.stairs(d1, bins, color=AMBER, linewidth=1.5, zorder=3)
    bx.stairs(d2, bins, color=BLUE, linewidth=2.0, zorder=4)
    iqr1 = float(np.subtract(*np.percentile(piles[0], [75, 25])))
    iqr2 = float(np.subtract(*np.percentile(avg, [75, 25])))
    ymax = max(d1.max(), d2.max())
    bx.set_ylim(0, ymax * 1.35)
    label(bx, bins[-1], ymax * 1.28, f"seed 1: IQR {iqr1:.1f} dB", AMBER, ha="right", va="top",
          fontweight="bold")
    label(bx, bins[-1], ymax * 1.12, f"5-seed mean: IQR {iqr2:.1f} dB", BLUE, ha="right",
          va="top", fontweight="bold")
    save(fig, "field-seed-average.svg")
    return {"link_spread_db": spread, "iqr_seed1": iqr1, "iqr_avg": iqr2,
            "std_seed1": float(piles[0].std()), "std_avg": float(avg.std()),
            "iqr_concat": float(np.subtract(*np.percentile(piles.ravel(), [75, 25])))}


def figure_ks():
    """unit-b SNR: the two empirical CDFs and the K-S D gap."""
    piles = np.stack([pd.read_csv(os.path.join(
        BATCH, "sim_traces", f"seed-{s}", "csvs", "unit-b",
        "IH_snr__unit-b_to_neighbors_trace.csv"))["snr_db"].to_numpy() for s in SEEDS])
    sim = piles.mean(axis=0)
    field = pd.read_csv(os.path.join(WORK, "windows", TAG, "unit-b", "csvs", "unit-b",
                                     "IH_snr__unit-b_to_neighbors_trace.csv"))["snr_db"].dropna().to_numpy()
    # The same arithmetic as compare._ks_2samp: both CDFs at every pooled value.
    joint = np.sort(np.concatenate([sim, field]))
    fs = np.searchsorted(np.sort(sim), joint, side="right") / sim.size
    ff = np.searchsorted(np.sort(field), joint, side="right") / field.size
    k = int(np.argmax(np.abs(fs - ff)))
    D, xD = float(abs(fs[k] - ff[k])), float(joint[k])

    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    style(ax, "K-S D is the widest vertical gap between the two cumulative curves",
          "SNR (dB)", "share of samples ≤ x")
    for vals, color in ((field, BLUE), (sim, AMBER)):
        v, F = ecdf(vals)
        ax.step(v, F, where="post", color=color, linewidth=2.0, zorder=3)
    ax.plot([xD, xD], [fs[k], ff[k]], color=RED, linewidth=2.4, zorder=5)
    ax.scatter([xD, xD], [fs[k], ff[k]], color=RED, s=18, zorder=6)
    label(ax, xD, 0.68, f"D = {D:.2f}\nat {xD:.1f} dB", RED,
          xytext=(10, 0), textcoords="offset points", va="center", fontweight="bold")
    ms, mf = float(np.median(sim)), float(np.median(field))
    ax.axhline(0.5, color=EDGE, linewidth=0.8, zorder=1)
    ax.scatter([mf, ms], [0.5, 0.5], color=[BLUE, AMBER], s=34, zorder=6, edgecolor="white")
    ax.annotate("", xy=(ms, 0.5), xytext=(mf, 0.5), zorder=5,
                arrowprops=dict(arrowstyle="<->", color=INK, lw=1.1, shrinkA=5, shrinkB=5))
    label(ax, ms, 0.5, f"|Δmedian|\n= {abs(ms - mf):.1f} dB", INK,
          xytext=(-10, -7), textcoords="offset points", ha="right", va="top")
    lo = min(field.min(), sim.min())
    label(ax, np.percentile(field, 88), 0.88, "field (practice bundle)", BLUE,
          xytext=(10, -2), textcoords="offset points", va="top", fontweight="bold")
    label(ax, np.percentile(sim, 18), 0.18, "simulator (5-seed mean)", AMBER,
          xytext=(10, -2), textcoords="offset points", va="top", fontweight="bold")
    ax.set_ylim(0, 1.02)
    ax.set_xlim(lo - 1, max(field.max(), sim.max()) + 1)
    save(fig, "field-ks-cdf.svg")
    return {"D": D, "xD": xD, "median_sim": ms, "median_field": mf}


def rma_los_db(d, f_hz=2.45e9, h_a=1.5, h_b=1.5, h=5.0):
    """ns-3 ThreeGppRmaPropagationLossModel LOS loss, without shadowing."""
    def pl1(dd):
        return (20 * math.log10(40 * math.pi * dd * f_hz / 1e9 / 3)
                + min(0.03 * h ** 1.72, 10) * math.log10(dd)
                - min(0.044 * h ** 1.72, 14.77) + 0.002 * math.log10(h) * dd)
    d_bp = 2 * math.pi * h_a * h_b * f_hz / 299792458.0
    return pl1(d) if d <= d_bp else pl1(d_bp) + 40 * math.log10(d / d_bp)


def figure_pathloss():
    """Loss against distance: simulator RMa LOS, its samples, free space, the bundle's formula."""
    ini = open(os.path.join(BATCH, "inputs", "run.ini")).read()
    tx = float(ini.split("tx_power_dbm = ")[1].split()[0])
    gains = (float(ini.split("tx_array_gain_dbi = ")[1].split()[0])
             + float(ini.split("rx_array_gain_dbi = ")[1].split()[0]))
    L = pd.read_csv(os.path.join(BATCH, "seed-1", "links.csv"))
    R = pd.read_csv(os.path.join(BATCH, "seed-1", "rx-power.csv"))
    d_s = L["dist_m"].to_numpy()
    pl_s = tx + gains - R["rx_power_dbm"].to_numpy()   # rx = tx - PL + gains
    d = np.logspace(1, math.log10(1500), 300)
    rma = np.array([rma_los_db(x) for x in d])
    fspl = 20 * np.log10(d) + 20 * math.log10(2.45e9) - 147.55221677811664
    bundle = 40.2 + 29.0 * np.log10(d)          # field-example.py's invented model, no shadowing
    d_bp = 2 * math.pi * 1.5 * 1.5 * 2.45e9 / 299792458.0

    fig, ax = plt.subplots(figsize=(10.5, 5.0))
    style(ax, "Path loss the simulator uses, against the practice bundle's formula",
          "distance between the two nodes (m, log scale)", "path loss (dB)")
    ax.set_xscale("log")
    ax.scatter(d_s, pl_s, s=3, color=BLUE, alpha=0.18, zorder=2, lw=0)
    ax.plot(d, fspl, color=MUTED, linewidth=1.2, linestyle=(0, (4, 3)), zorder=3)
    ax.plot(d, rma, color=BLUE, linewidth=2.2, zorder=4)
    ax.plot(d, bundle, color=AMBER, linewidth=2.2, zorder=4)
    ax.axvline(d_bp, color=EDGE, linewidth=1, zorder=1)
    label(ax, d_bp, 64, f"RMa breakpoint {d_bp:.0f} m\n(both nodes at 1.5 m)", MUTED,
          xytext=(6, 0), textcoords="offset points", va="bottom")
    x5 = 500.0
    r5, b5 = rma_los_db(x5), 40.2 + 29.0 * math.log10(x5)
    ax.annotate("", xy=(x5, b5), xytext=(x5, r5), zorder=6,
                arrowprops=dict(arrowstyle="<->", color=INK, lw=1.1))
    label(ax, x5, (r5 + b5) / 2, f"{b5 - r5:.1f} dB at 500 m", INK, xytext=(8, 0),
          textcoords="offset points", va="center")
    label(ax, 1500, float(bundle[-1]), "practice bundle: 40.2 + 29 log₁₀ d\n(invented, plus 5 dB shadowing)",
          AMBER, xytext=(-6, 8), textcoords="offset points", ha="right", va="bottom",
          fontweight="bold")
    label(ax, 11, rma_los_db(11.0), "simulator: 3GPP RMa LOS (blue line);\nbelow the breakpoint it sits on free space",
          BLUE, xytext=(0, -10), textcoords="offset points", va="top", fontweight="bold")
    label(ax, 1500, float(fspl[-1]), "free space (the floor)", MUTED, xytext=(-6, -8),
          textcoords="offset points", ha="right", va="top")
    label(ax, 22, 104, "dots: seed 1, every pair and tick\n(the formula plus shadowing)", BLUE,
          va="center")
    ax.set_xlim(10, 1500)
    ax.set_ylim(50, 150)
    save(fig, "field-pathloss.svg")
    resid = pl_s - np.array([rma_los_db(x) for x in d_s])
    return {"d_bp": d_bp, "gap_500": b5 - r5, "resid_mean": float(resid.mean()),
            "resid_std": float(resid.std())}


def main():
    if not os.path.isdir(BATCH):
        sys.exit(f"no practice run under {OUT}; run field-example.py --sim-binary <BIN> first")
    plt.rcParams["font.family"] = ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]
    plt.rcParams["svg.hashsalt"] = "field-transforms"
    for name, fn in (("rcpi", figure_rcpi), ("window", figure_window),
                     ("waypoints", figure_waypoints), ("seeds", figure_seed_average),
                     ("ks", figure_ks), ("pathloss", figure_pathloss)):
        stats = fn()
        print(f"  {name}: " + ", ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}"
                                        for k, v in stats.items()))


if __name__ == "__main__":
    main()
