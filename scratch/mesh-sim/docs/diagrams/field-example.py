"""Make the synthetic field bundle and run the field comparison on it, for the field-data pages.

The real ARPO field bundle is private, so the field-data pages are illustrated
with a synthetic one. This script writes a small bundle in exactly the raw
layout the pipeline reads (one folder per node, with gps/ and silvus/), then
runs the seven pipeline commands on it with the real tools and copies the
tools' own figures into docs/diagrams/ as field-*.png.

The bundle is made up: four nodes named unit-a .. unit-d at an invented site,
moving on simple paths, with radio statistics from a log-distance path-loss
model (exponent 2.9, 5 dB shadowing, 2450 MHz, 10 MHz, 27 dBm). It is
deliberately not the simulator's own model, so the comparison has something to
show. Nothing in it is measured.

From docs/, with the project venv:

    ../.venv/bin/python diagrams/field-example.py --bundle-only DIR   # just the raw bundle, for practice
    ../.venv/bin/python diagrams/field-example.py --sim-binary <BIN>  # bundle + full pipeline + figures

The full run writes everything under ../outputs/docs-figures/field-example/
(ignored by Git): raw/ (the bundle), work/ (the pipeline workspace) and
logs/ (each command's console output, quoted on the pages).
"""
import argparse
import math
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))  # scratch/mesh-sim
OUT = os.path.join(ROOT, "outputs", "docs-figures", "field-example")
PYTHON = os.path.join(ROOT, ".venv", "bin", "python")

DAY = "2026-03-14"
START = datetime(2026, 3, 14, 14, 50, tzinfo=timezone.utc)  # logs run 14:50-15:30 UTC
SPAN_S = 40 * 60
WINDOW = ("15.00", "15.20", "1500-1520")                     # the test event the pages cut out
EXTRA_WINDOWS = (("14.50", "15.00", "1450-1500"),            # "Add a window" on Extend the comparison
                 ("15.20", "15.30", "1520-1530"))
ORIGIN = (39.5000, -104.5000)                                # an invented site
NODES = {  # folder name -> Silvus node_id
    "unit-a": "3101", "unit-b": "3102", "unit-c": "3103", "unit-d": "3104"}
RADIO = {"freq": 2450, "bw": 10, "power_dBm": 27}
SEED = 20260314

# A second, separate day with a jamming trial ("Jammed windows" page). Its rows are
# appended after day 1's and use their own random generator, so day 1 is unchanged.
JAM_DAY = "2026-03-15"
JAM_START = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)  # logs run 10:00-10:20 UTC
JAM_SPAN_S = 20 * 60
JAM_WINDOW = ("10.00", "10.20", "1000-1020")
JAM_TRIAL = {"trial": "ew-1", "start_s": 300, "end_s": 900,      # 10:05-10:15
             "east": 700.0, "north": 150.0, "heading": 258.0,    # pointing west-southwest
             "watts": 2.0, "gain_dbi": 10.0, "band": "2440-2460", "type": "directional"}


def track(name, t):
    """(east, north) in meters at t seconds after START."""
    if name == "unit-a":                       # fixed base
        return 0.0, 0.0
    if name == "unit-b":                       # vehicle on a 300 m loop, 6 min a lap
        a = 2 * math.pi * t / 360.0
        return 400 + 300 * math.cos(a), 200 + 300 * math.sin(a)
    if name == "unit-c":                       # vehicle driving out and back, 10 min each way
        f = (t % 1200) / 600.0
        f = f if f <= 1 else 2 - f
        return 100 + 1000 * f, -100 - 200 * f
    # unit-d: a person walking slowly around a point
    return 250 + 80 * math.sin(t / 150.0), 450 + 60 * math.sin(t / 97.0)


def latlon(east, north):
    lat = ORIGIN[0] + north / 111_320.0
    lon = ORIGIN[1] + east / (111_320.0 * math.cos(math.radians(ORIGIN[0])))
    return lat, lon


def write_bundle(raw):
    """Write the synthetic per-node bundle under raw/."""
    rng = np.random.default_rng(SEED)
    if os.path.isdir(raw) and os.listdir(raw):
        sys.exit(f"{raw} is not empty; pick a new folder")
    t0_ns = int(START.timestamp() * 1e9)
    noise_dbm = -174 + 10 * math.log10(RADIO["bw"] * 1e6) + 7          # 7 dB noise figure
    body_loss = {"unit-d": 6.0}                                         # a handheld radio
    shadow = {}
    for name, nid in NODES.items():
        os.makedirs(os.path.join(raw, name, "gps"))
        os.makedirs(os.path.join(raw, name, "silvus"))
        with open(os.path.join(raw, name, "gps", "gps_position.csv"), "w") as fh:
            fh.write("time,latitude,longitude,callsign\n")
            for t in range(SPAN_S):
                lat, lon = latlon(*track(name, t))
                fh.write(f"{t0_ns + t * 1_000_000_000},{lat:.7f},{lon:.7f},{name.upper()}\n")
        with open(os.path.join(raw, name, "silvus", "config.csv"), "w") as fh:
            fh.write("time,node_id,virtual_ip,freq,bw,power_dBm\n")
            fh.write(f"{t0_ns},{nid},10.0.0.{nid[-1]},{RADIO['freq']},{RADIO['bw']},{RADIO['power_dBm']}\n")
    for name, nid in NODES.items():
        rows = []
        for t in range(0, SPAN_S, 2):                                   # one report every 2 s
            for peer, pid in NODES.items():
                if peer == name:
                    continue
                (x1, y1), (x2, y2) = track(name, t), track(peer, t)
                d = max(math.hypot(x1 - x2, y1 - y2), 1.0)
                key = (name, peer)                                      # AR(1) shadowing per direction
                shadow[key] = 0.9 * shadow.get(key, 0.0) + rng.normal(0, 5.0 * math.sqrt(1 - 0.81))
                pl = 40.2 + 29.0 * math.log10(d) + shadow[key]          # 2.45 GHz, exponent 2.9
                prx = RADIO["power_dBm"] + 4 + 4 - pl - body_loss.get(name, 0) - body_loss.get(peer, 0)
                snr = prx - noise_dbm
                if snr < -2:                                            # too weak to be heard
                    continue
                ants = [prx + rng.normal(0, 1.5) for _ in range(4)]
                if name == "unit-d" and rng.random() < 0.3:             # a blocked antenna logs -120
                    ants[3] = -120.0
                mcs = int(np.clip(math.floor((snr - 2) / 2.3 + rng.normal(0, 0.5)), 0, 15))
                rows.append(f"{t0_ns + t * 1_000_000_000},{nid},10.0.0.{nid[-1]},{pid},"
                            f"{snr:.1f},{mcs},{mcs},{ants[0]:.1f},{ants[1]:.1f},{ants[2]:.1f},{ants[3]:.1f}")
        with open(os.path.join(raw, name, "silvus", "network_status.csv"), "w") as fh:
            fh.write("time,node_id,virtual_ip,neighbor,snr,mcs,mcs_rx,"
                     "rssi_ant1,rssi_ant2,rssi_ant3,rssi_ant4\n")
            fh.write("\n".join(rows) + "\n")
    append_jam_day(raw, noise_dbm, body_loss)
    print(f"wrote the synthetic bundle: {raw}")


def jammer_loss_db(east, north):
    """Off-axis loss of the practice bundle's jammer: a smooth beam, not a hard cone.

    The 3GPP-style pattern 12 (off / 60)^2 dB, capped at 20 dB, so a node 30 deg off
    axis loses 3 dB and one behind the jammer still gets 20 dB below the peak.
    """
    bearing = math.degrees(math.atan2(east - JAM_TRIAL["east"], north - JAM_TRIAL["north"])) % 360
    off = abs((bearing - JAM_TRIAL["heading"] + 180) % 360 - 180)
    return min(12.0 * (off / 60.0) ** 2, 20.0)


def append_jam_day(raw, noise_dbm, body_loss):
    """Append day 2 (a 20-minute event with a 10-minute jamming trial) to every node's logs."""
    rng = np.random.default_rng(SEED + 1)
    t0_ns = int(JAM_START.timestamp() * 1e9)
    shadow = {}
    for name in NODES:
        with open(os.path.join(raw, name, "gps", "gps_position.csv"), "a") as fh:
            for t in range(JAM_SPAN_S):
                lat, lon = latlon(*track(name, t))
                fh.write(f"{t0_ns + t * 1_000_000_000},{lat:.7f},{lon:.7f},{name.upper()}\n")
    eirp = 10 * math.log10(JAM_TRIAL["watts"]) + 30 + JAM_TRIAL["gain_dbi"]
    for name, nid in NODES.items():
        rows = []
        for t in range(0, JAM_SPAN_S, 2):
            x1, y1 = track(name, t)
            jam_mw = 0.0
            if JAM_TRIAL["start_s"] <= t < JAM_TRIAL["end_s"]:
                dj = max(math.hypot(x1 - JAM_TRIAL["east"], y1 - JAM_TRIAL["north"]), 1.0)
                pj = (eirp - (40.2 + 29.0 * math.log10(dj) + rng.normal(0, 4.0))
                      - jammer_loss_db(x1, y1) - body_loss.get(name, 0))
                jam_mw = 10 ** (pj / 10)
            for peer, pid in NODES.items():
                if peer == name:
                    continue
                x2, y2 = track(peer, t)
                d = max(math.hypot(x1 - x2, y1 - y2), 1.0)
                key = (name, peer)
                shadow[key] = 0.9 * shadow.get(key, 0.0) + rng.normal(0, 5.0 * math.sqrt(1 - 0.81))
                pl = 40.2 + 29.0 * math.log10(d) + shadow[key]
                prx = RADIO["power_dBm"] + 4 + 4 - pl - body_loss.get(name, 0) - body_loss.get(peer, 0)
                s_mw, n_mw = 10 ** (prx / 10), 10 ** (noise_dbm / 10)
                snr = 10 * math.log10(s_mw / (n_mw + jam_mw))                # the radio reports SINR
                if snr < -2:
                    continue
                total = 10 * math.log10(s_mw + jam_mw)                       # RSSI counts jammer energy too
                ants = [total + rng.normal(0, 1.5) for _ in range(4)]
                mcs = int(np.clip(math.floor((snr - 2) / 2.3 + rng.normal(0, 0.5)), 0, 15))
                rows.append(f"{t0_ns + t * 1_000_000_000},{nid},10.0.0.{nid[-1]},{pid},"
                            f"{snr:.1f},{mcs},{mcs},{ants[0]:.1f},{ants[1]:.1f},{ants[2]:.1f},{ants[3]:.1f}")
        with open(os.path.join(raw, name, "silvus", "network_status.csv"), "a") as fh:
            fh.write("\n".join(rows) + "\n")
    lat, lon = latlon(JAM_TRIAL["east"], JAM_TRIAL["north"])
    start = JAM_START.timestamp()
    with open(os.path.join(os.path.dirname(raw), "ew_trials.csv"), "w") as fh:
        fh.write("trial,start,end,ew_type,ew_approx_lat,ew_approx_lon,ew_approx_heading (deg from N),"
                 "ew_strength (W),ew_gain (dBi),ew_band_range\n")
        fh.write(f"{JAM_TRIAL['trial']},{start + JAM_TRIAL['start_s']:.0f},{start + JAM_TRIAL['end_s']:.0f},"
                 f"{JAM_TRIAL['type']},{lat:.7f},{lon:.7f},{JAM_TRIAL['heading']},{JAM_TRIAL['watts']},"
                 f"{JAM_TRIAL['gain_dbi']},{JAM_TRIAL['band']}\n")


def run(logs, name, args):
    """Run one pipeline command from scratch/mesh-sim/, keeping its console output."""
    proc = subprocess.run([PYTHON, "-m", *args], cwd=ROOT, capture_output=True, text=True)
    text = proc.stdout + proc.stderr
    with open(os.path.join(logs, f"{name}.log"), "w") as fh:
        fh.write(text)
    print(f"[{name}] exit {proc.returncode}")
    if proc.returncode:
        sys.exit(text)


def pipeline(sim_binary):
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    raw, work, logs = (os.path.join(OUT, d) for d in ("raw", "work", "logs"))
    os.makedirs(logs)
    write_bundle(raw)
    rel = lambda p: os.path.relpath(p, ROOT)  # noqa: E731
    start, end, tag = WINDOW
    run(logs, "1-plot", ["scripts.arpo_data.cli", "plot", "--nodes", "-i", raw,
                         "-o", rel(f"{work}/daily"), "--day", DAY])
    run(logs, "2-split", ["scripts.arpo_data.cli", "split-scenario", "-i", rel(f"{work}/daily/{DAY}"),
                          "-o", rel(f"{work}/windows"), "--start", start, "--end", end])
    run(logs, "3-config", ["scripts.validation.build_config_files", "-i", rel(f"{work}/windows"),
                           "--day", tag, "--csv-dir", raw, "--band", "sub-6", "--mode", "node",
                           "--name", "field-example", "-o", rel(f"{work}/scenarios")])
    run(logs, "4-waypoints", ["scripts.validation.build_waypoints", "node",
                              "-i", rel(f"{work}/scenarios/{tag}"),
                              "-f", rel(f"{work}/windows/{tag}/gps_all_nodes_trace.csv"),
                              "--all-nodes", "--time-mode", "raw"])
    run(logs, "5-batch", ["scripts.validation.run_batch", "--scenarios-dir", rel(f"{work}/scenarios"),
                          "--only", tag, "--out", rel(f"{work}/batch"), "--seeds", "1,2,3,4,5",
                          "--sim-binary", sim_binary])
    run(logs, "6-traces", ["scripts.validation.sim_to_traces", "-m", "node", rel(f"{work}/batch/{tag}")])
    run(logs, "7-compare", ["scripts.validation.compare", "-m", "node",
                            "--batch_root", rel(f"{work}/batch/{tag}"),
                            "--field-root", rel(f"{work}/windows/{tag}")])
    # The "controlled change" on Read the comparison: the same window with the
    # bundle's own antenna gains and noise figure instead of the generator defaults.
    run(logs, "8-matched-config", ["scripts.validation.build_config_files", "-i", rel(f"{work}/windows"),
                                   "--day", tag, "--csv-dir", raw, "--band", "sub-6", "--mode", "node",
                                   "--name", "field-example-matched", "--tx-gain", "4", "--rx-gain", "4",
                                   "--noise-figure", "7", "-o", rel(f"{work}/matched/scenarios")])
    run(logs, "8-matched-waypoints", ["scripts.validation.build_waypoints", "node",
                                      "-i", rel(f"{work}/matched/scenarios/{tag}"),
                                      "-f", rel(f"{work}/windows/{tag}/gps_all_nodes_trace.csv"),
                                      "--all-nodes", "--time-mode", "raw"])
    run(logs, "8-matched-batch", ["scripts.validation.run_batch",
                                  "--scenarios-dir", rel(f"{work}/matched/scenarios"), "--only", tag,
                                  "--out", rel(f"{work}/matched/batch"), "--seeds", "1,2,3,4,5",
                                  "--sim-binary", sim_binary])
    run(logs, "8-matched-traces", ["scripts.validation.sim_to_traces", "-m", "node",
                                   rel(f"{work}/matched/batch/{tag}")])
    run(logs, "8-matched-compare", ["scripts.validation.compare", "-m", "node",
                                    "--batch_root", rel(f"{work}/matched/batch/{tag}"),
                                    "--field-root", rel(f"{work}/windows/{tag}")])
    # "Add a window" on Extend the comparison: two more windows from the same day,
    # each with its own scenario and batch folder.
    for start_w, end_w, tag_w in EXTRA_WINDOWS:
        step = f"9-{tag_w}"
        run(logs, f"{step}-split", ["scripts.arpo_data.cli", "split-scenario",
                                    "-i", rel(f"{work}/daily/{DAY}"), "-o", rel(f"{work}/windows"),
                                    "--start", start_w, "--end", end_w])
        run(logs, f"{step}-config", ["scripts.validation.build_config_files", "-i", rel(f"{work}/windows"),
                                     "--day", tag_w, "--csv-dir", raw, "--band", "sub-6", "--mode", "node",
                                     "--name", f"field-example-{tag_w}", "-o", rel(f"{work}/scenarios")])
        run(logs, f"{step}-waypoints", ["scripts.validation.build_waypoints", "node",
                                        "-i", rel(f"{work}/scenarios/{tag_w}"),
                                        "-f", rel(f"{work}/windows/{tag_w}/gps_all_nodes_trace.csv"),
                                        "--all-nodes", "--time-mode", "raw"])
        run(logs, f"{step}-batch", ["scripts.validation.run_batch",
                                    "--scenarios-dir", rel(f"{work}/scenarios"), "--only", tag_w,
                                    "--out", rel(f"{work}/batch-{tag_w}"), "--seeds", "1,2,3,4,5",
                                    "--sim-binary", sim_binary])
        run(logs, f"{step}-traces", ["scripts.validation.sim_to_traces", "-m", "node",
                                     rel(f"{work}/batch-{tag_w}/{tag_w}")])
        run(logs, f"{step}-compare", ["scripts.validation.compare", "-m", "node",
                                      "--batch_root", rel(f"{work}/batch-{tag_w}/{tag_w}"),
                                      "--field-root", rel(f"{work}/windows/{tag_w}")])
    jam_pipeline(logs, raw, work, sim_binary, rel)
    copy_figures(work, tag)


def jam_pipeline(logs, raw, work, sim_binary, rel):
    """The "Jammed windows" example: day 2's window run without and with its jammer."""
    start, end, tag = JAM_WINDOW
    run(logs, "10-jam-plot", ["scripts.arpo_data.cli", "plot", "--nodes", "-i", raw,
                              "-o", rel(f"{work}/daily"), "--day", JAM_DAY])
    run(logs, "10-jam-split", ["scripts.arpo_data.cli", "split-scenario", "-i", rel(f"{work}/daily/{JAM_DAY}"),
                               "-o", rel(f"{work}/windows"), "--start", start, "--end", end])
    for variant in ("nojam", "jam"):
        base = f"{work}/{variant}"
        run(logs, f"10-{variant}-config", ["scripts.validation.build_config_files", "-i", rel(f"{work}/windows"),
                                           "--day", tag, "--csv-dir", raw, "--band", "sub-6", "--mode", "node",
                                           "--name", f"field-example-{variant}", "-o", rel(f"{base}/scenarios")])
        run(logs, f"10-{variant}-waypoints", ["scripts.validation.build_waypoints", "node",
                                              "-i", rel(f"{base}/scenarios/{tag}"),
                                              "-f", rel(f"{work}/windows/{tag}/gps_all_nodes_trace.csv"),
                                              "--all-nodes", "--time-mode", "raw"])
        if variant == "jam":
            run(logs, "10-jam-make-jammers", ["scripts.validation.make_jammers",
                                              "--trials", os.path.join(os.path.dirname(raw), "ew_trials.csv"),
                                              "--trace", rel(f"{work}/windows/{tag}/gps_all_nodes_trace.csv"),
                                              "-o", rel(f"{base}/scenarios/{tag}/jammers.json"),
                                              "--run-ini", rel(f"{base}/scenarios/{tag}/run.ini")])
        run(logs, f"10-{variant}-batch", ["scripts.validation.run_batch", "--scenarios-dir", rel(f"{base}/scenarios"),
                                          "--only", tag, "--out", rel(f"{base}/batch"), "--seeds", "1,2,3,4,5",
                                          "--sim-binary", sim_binary])
        run(logs, f"10-{variant}-traces", ["scripts.validation.sim_to_traces", "-m", "node",
                                           rel(f"{base}/batch/{tag}")])
        run(logs, f"10-{variant}-compare", ["scripts.validation.compare", "-m", "node",
                                            "--batch_root", rel(f"{base}/batch/{tag}"),
                                            "--field-root", rel(f"{work}/windows/{tag}")])


def copy_figures(work, tag):
    """Copy the tools' own figures that the pages show into docs/diagrams/."""
    picks = {
        f"daily/{DAY}/gps_all_nodes.png": "field-gps.png",
        f"daily/{DAY}/unit-b/pngs/unit-b/IH_snr__unit-b_to_neighbors.png": "field-trace-snr.png",
        f"batch/{tag}/validation/pngs/unit-b/hist_snr__unit-b_to_neighbors.png": "field-hist-snr.png",
        f"batch/{tag}/validation/pngs/unit-b/hist_rcpi__unit-b_to_neighbors.png": "field-hist-rcpi.png",
        f"batch/{tag}/validation/pngs/unit-b/hist_mcs__unit-b_to_neighbors.png": "field-hist-mcs.png",
        f"batch/{tag}/summary/heatmap_snr_dmedian.png": "field-heatmap-snr.png",
        f"matched/batch/{tag}/validation/pngs/unit-b/hist_snr__unit-b_to_neighbors.png":
            "field-hist-snr-matched.png",
    }
    for src, dst in picks.items():
        path = os.path.join(work, src)
        if not os.path.exists(path):
            print(f"missing: {src}")
            continue
        shutil.copyfile(path, os.path.join(HERE, dst))
        print(f"wrote docs/diagrams/{dst}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--bundle-only", metavar="DIR", help="only write the synthetic raw bundle to DIR")
    group.add_argument("--sim-binary", help="write the bundle, run the whole pipeline and copy figures")
    args = parser.parse_args()
    if args.bundle_only:
        write_bundle(os.path.abspath(args.bundle_only))
    else:
        pipeline(os.path.abspath(args.sim_binary))


if __name__ == "__main__":
    main()
