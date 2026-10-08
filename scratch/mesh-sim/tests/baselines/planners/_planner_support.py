"""In-process scorers and custom query workers shared by the test_planners_* modules.

Not a test module. Imported relatively (``from ._planner_support import ...``).
"""

import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

from scripts.baselines.planners.channel import LayoutResult


class DistanceScorer:
    """In-process stand-in for ChannelScorer with fake_query.py's distance channel.

    connected iff 3-D distance <= range_m; a probe is covered iff the node-to-probe
    distance (probe at height_m) <= range_m. Records every evaluate() call.
    """

    def __init__(self, range_m: float = 100.0):
        self.range_m = range_m
        self.probes = None
        self.calls: list[list[tuple[np.ndarray, LayoutResult]]] = []

    def set_probes(self, points, *, height_m, rx_gain_dbi, sinr_db):
        self.probes = {"points": [list(p) for p in np.asarray(points, dtype=float).tolist()],
                       "height_m": float(height_m),
                       "rx_gain_dbi": 0.0 if rx_gain_dbi is None else rx_gain_dbi,
                       "sinr_db": sinr_db}

    def result(self, layout) -> LayoutResult:
        layout = np.asarray(layout, dtype=float)
        n = len(layout)
        distance = np.linalg.norm(layout[:, None, :] - layout[None, :, :], axis=2)
        connected = distance <= self.range_m
        np.fill_diagonal(connected, False)
        sinr = -6.7 + 20.0 * np.log10(self.range_m / np.maximum(distance, 1.0))
        np.fill_diagonal(sinr, -np.inf)
        coverage = None
        if self.probes is not None:
            h = self.probes["height_m"]
            coverage = [[k for k, (px, py) in enumerate(self.probes["points"])
                         if math.dist(point, (px, py, h)) <= self.range_m]
                        for point in layout.tolist()]
        return LayoutResult(connected=connected, sinr_db=sinr, capacity_mbps=np.zeros((n, n)),
                            is_los=connected.copy(), coverage=coverage, wall_s=0.0)

    def evaluate(self, layouts):
        arrays = [np.array(layout, dtype=float) for layout in layouts]
        results = [self.result(array) for array in arrays]
        self.calls.append(list(zip(arrays, results)))
        return results

    @property
    def layouts(self) -> list[np.ndarray]:
        return [array for call in self.calls for array, _ in call]


class TableScorer:
    """Stand-in scorer whose results come from a function of the layout."""

    def __init__(self, fn):
        self.fn = fn
        self.probes = None
        self.calls = []

    def set_probes(self, points, *, height_m, rx_gain_dbi, sinr_db):
        self.probes = {"points": [list(p) for p in np.asarray(points, dtype=float).tolist()],
                       "height_m": height_m, "rx_gain_dbi": rx_gain_dbi or 0.0,
                       "sinr_db": sinr_db}

    def evaluate(self, layouts):
        arrays = [np.array(layout, dtype=float) for layout in layouts]
        self.calls.append(arrays)
        return [self.fn(array) for array in arrays]


def full_table(n: int, coverage=None, missing=()) -> LayoutResult:
    """All pairs connected except `missing` (i, j) pairs."""
    connected = ~np.eye(n, dtype=bool)
    for i, j in missing:
        connected[i, j] = connected[j, i] = False
    sinr = np.where(connected, 10.0, -30.0)
    np.fill_diagonal(sinr, -np.inf)
    return LayoutResult(connected=connected, sinr_db=sinr, capacity_mbps=np.zeros((n, n)),
                        is_los=connected.copy(),
                        coverage=[[] for _ in range(n)] if coverage is None else coverage,
                        wall_s=0.0)


# ---------------------------------------------------------------------------------------
# Custom mesh_channel_query_v1 workers written into tmp_path for precise protocol cases.

CUSTOM_ROSTER = ["n0", "n1", "n2"]
CUSTOM_STARTS = [[0.0, 0.0, 10.0], [50.0, 0.0, 10.0], [300.0, 0.0, 10.0]]

WORKER_PRELUDE = '''
import json, math, os, signal, sys, time
ROSTER = %(roster)r
STARTS = %(starts)r
RANGE_M = 100.0
MIB = 1024 * 1024
LIMITS = {"max_layouts": 1024, "max_probes": 10000, "max_request_line_bytes": 16 * MIB,
          "max_child_response_bytes": 16 * MIB, "child_deadline_s": 60.0}
if os.environ.get("CUSTOM_PID"):
    with open(os.environ["CUSTOM_PID"], "w") as handle:
        handle.write(str(os.getpid()))

def init_obj(**patch):
    obj = {"type": "init", "contract": "mesh_channel_query_v1",
           "isolation": "fork_per_layout", "node_ids": ROSTER,
           "node_types": ["drone"] * len(ROSTER), "mobility": ["fixed"] * len(ROSTER),
           "start_positions": STARTS, "controlled_indices": [], "rl_enabled": False,
           "band": "mmwave", "band_source": "default", "seed": 7, "run_id": 1,
           "jammer_seed": 7, "sinr_threshold_db": -6.7, "jammer_path_enabled": False,
           "num_buildings": 0,
           "channel": {"frequency_ghz": 28.0, "tx_power_dbm": 30.0, "bandwidth_mhz": 400.0,
                       "noise_figure_db": 5.0, "amc_model": "shannon",
                       "channel_model": "3gpp", "scenario": "UMi",
                       "condition_model": "auto", "tx_array_gain_dbi": 12.0,
                       "rx_array_gain_dbi": 12.0},
           "limits": dict(LIMITS), "time_s": 0.0}
    obj.update(patch)
    return obj

def emit(item):
    text = item if isinstance(item, str) else json.dumps(item)
    sys.stdout.write(text + "\\n")
    sys.stdout.flush()

def record(entry):
    path = os.environ.get("CUSTOM_RECORD")
    if path:
        with open(path, "a") as handle:
            handle.write(json.dumps(entry) + "\\n")

def layout_entry(layout, probes):
    links = []
    for i in range(len(layout)):
        for j in range(i + 1, len(layout)):
            d = math.dist(layout[i], layout[j])
            sinr = -6.7 + 20.0 * math.log10(RANGE_M / max(d, 1.0))
            links.append([i, j, sinr, 100.0, True, d <= RANGE_M])
    coverage = None
    if probes is not None:
        coverage = [[k for k, (px, py) in enumerate(probes["points"])
                     if math.dist(p, (px, py, probes["height_m"])) <= RANGE_M]
                    for p in layout]
    return {"links": links, "coverage": coverage, "wall_s": 0.001}

def result(req, **patch):
    obj = {"type": "result", "request_id": req["request_id"],
           "layouts": [layout_entry(l, req.get("probes")) for l in req["layouts"]],
           "wall_s": 0.01}
    obj.update(patch)
    return obj

def requests():
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            record({"type": "eof"})
            return
        req = json.loads(line)
        record({"type": req.get("type"), "request_id": req.get("request_id"),
                "layouts": len(req.get("layouts") or [])})
        if req.get("type") == "shutdown":
            return
        yield req
'''


def make_worker(directory: Path, body: str) -> Path:
    """Executable custom worker: the prelude, then `body` (module-level Python)."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "custom-worker"
    prelude = WORKER_PRELUDE % {"roster": CUSTOM_ROSTER, "starts": CUSTOM_STARTS}
    path.write_text(f"#!{sys.executable}\n{prelude}\n{body}\n")
    path.chmod(0o755)
    return path


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # a zombie still answers kill(0); treat it as gone only once reaped elsewhere
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            return handle.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


def assert_gone(*pids: int, wait_s: float = 10.0) -> None:
    deadline = time.monotonic() + wait_s
    while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not [pid for pid in pids if alive(pid)], "worker processes still alive"


def read_records(path: Path, kind: str | None = None) -> list[dict]:
    if not Path(path).exists():
        return []
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    return rows if kind is None else [r for r in rows if r.get("type") == kind]
