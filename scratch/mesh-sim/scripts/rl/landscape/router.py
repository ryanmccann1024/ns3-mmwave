"""Python port of the simulator's flow-level router (`src/routing/mesh-router.cc`).

Takes one link-capacity matrix and a list of flows and returns one result per
flow with the same path choice, hop limit and congestion scaling as
`MeshRouter::Route`. Used to score candidate layouts offline (reward landscape).
"""
# Recovered from bytecode — approximate reconstruction
import heapq
import math
from dataclasses import dataclass, field

ALGORITHMS = ('shortest_path', 'max_throughput', 'min_hop')
PROCESSING_DELAY_MS = 0.5
SPEED_OF_LIGHT_M_S = 300_000_000.0


@dataclass(frozen=True)
class Flow:
    """One directed flow, as `mesh_sim::Flow` hands it to the router."""

    src: int
    dst: int
    demand_mbps: float
    active: bool = True
    in_on_phase: bool = True


@dataclass
class FlowResult:
    """Routing result for one flow at one tick (mirror of `mesh_sim::FlowResult`)."""

    src: int
    dst: int
    demand_mbps: float = 0.0
    delivered_mbps: float = 0.0
    latency_ms: float = 0.0
    hop_count: int = 0
    path: list = field(default_factory=list)
    routable: bool = False


def _matrix(values) -> list:
    return [[float(v) for v in row] for row in values]


def _reconstruct(prev: list, src: int, dst: int) -> list:
    """Walk `prev` back from `dst`; empty when `dst` was not reached."""
    if prev[dst] is None and src != dst:
        return []
    path = []
    cur = dst
    while cur is not None:
        path.append(cur)
        if cur == src:
            break
        cur = prev[cur]
    path.reverse()
    if not path or path[0] != src:
        return []
    return path


def _shortest_path(cap: list, src: int, dst: int, n: int) -> list:
    """Dijkstra with weight 1/capacity; heap ties pop the lower node index first."""
    dist = [math.inf] * n
    prev = [None] * n
    visited = [False] * n
    dist[src] = 0.0
    heap = [(0.0, src)]
    while heap:
        _, u = heapq.heappop(heap)
        if visited[u]:
            continue
        visited[u] = True
        if u == dst:
            break
        row = cap[u]
        for v in range(n):
            if visited[v] or v == u:
                continue
            c = row[v]
            if c <= 0.0:
                continue
            new_dist = dist[u] + 1.0 / c
            if new_dist < dist[v]:
                dist[v] = new_dist
                prev[v] = u
                heapq.heappush(heap, (new_dist, v))
    return _reconstruct(prev, src, dst)


def _max_throughput(cap: list, src: int, dst: int, n: int) -> list:
    """Widest path; std::priority_queue<pair> ties pop the higher node index first."""
    bw = [0.0] * n
    prev = [None] * n
    visited = [False] * n
    bw[src] = math.inf
    heap = [(-math.inf, -src)]
    while heap:
        _, neg_u = heapq.heappop(heap)
        u = -neg_u
        if visited[u]:
            continue
        visited[u] = True
        if u == dst:
            break
        row = cap[u]
        for v in range(n):
            if visited[v] or v == u:
                continue
            c = row[v]
            if c <= 0.0:
                continue
            new_bw = min(bw[u], c)
            if new_bw > bw[v]:
                bw[v] = new_bw
                prev[v] = u
                heapq.heappush(heap, (-new_bw, -v))
    return _reconstruct(prev, src, dst)


def _min_hop(cap: list, src: int, dst: int, n: int) -> list:
    """BFS over capacity > 0 edges, expanding lower node indices first."""
    prev = [None] * n
    visited = [False] * n
    queue = [src]
    visited[src] = True
    head = 0
    while head < len(queue):
        u = queue[head]
        head += 1
        if u == dst:
            break
        row = cap[u]
        for v in range(n):
            if visited[v] or v == u:
                continue
            if row[v] <= 0.0:
                continue
            visited[v] = True
            prev[v] = u
            queue.append(v)
    return _reconstruct(prev, src, dst)


_FINDERS = {
    'shortest_path': _shortest_path,
    'max_throughput': _max_throughput,
    'min_hop': _min_hop,
}


def find_path(capacity: list, src: int, dst: int, algorithm: str = 'shortest_path', max_hops: int = 5) -> list:
    cap = _matrix(capacity)
    return _find(cap, src, dst, len(cap), algorithm, max_hops)


def _find(cap: list, src: int, dst: int, n: int, algorithm: str, max_hops: int) -> list:
    path = _FINDERS.get(algorithm, _shortest_path)(cap, src, dst, n)
    if max_hops > 0 and len(path) > max_hops + 1:
        return []
    return path


def _latency_ms(path: list, distance: list | None) -> float:
    total = 0.0
    for i in range(len(path) - 1):
        d = distance[path[i]][path[i + 1]] if distance is not None else 0.0
        total += d / SPEED_OF_LIGHT_M_S * 1000.0 + PROCESSING_DELAY_MS
    return total


def _apply_congestion(results: list, cap: list) -> None:
    """Single-pass proportional scaling on every edge whose demand exceeds capacity."""
    demand = {}
    users = {}
    for index, fr in enumerate(results):
        if not fr.routable or fr.demand_mbps <= 0.0:
            continue
        for a, b in zip(fr.path, fr.path[1:]):
            key = (min(a, b), max(a, b))
            demand[key] = demand.get(key, 0.0) + fr.demand_mbps
            users.setdefault(key, []).append(index)
    for key in sorted(demand):
        total = demand[key]
        capacity = cap[key[0]][key[1]]
        if total <= capacity or capacity <= 0.0:
            continue
        scale = capacity / total
        for index in users[key]:
            fr = results[index]
            fr.delivered_mbps = min(fr.delivered_mbps, fr.demand_mbps * scale)


def route(capacity: list, flows, algorithm: str = 'shortest_path', max_hops: int = 5, distance=None) -> list:
    cap = _matrix(capacity)
    dist = _matrix(distance) if distance is not None else None
    n = len(cap)
    results = []
    for flow in flows:
        fr = FlowResult(src=int(flow.src), dst=int(flow.dst))
        demand = float(flow.demand_mbps) if flow.active and flow.in_on_phase else 0.0
        fr.demand_mbps = demand
        if demand <= 0.0 or fr.src == fr.dst:
            fr.routable = fr.src == fr.dst
            results.append(fr)
            continue
        path = _find(cap, fr.src, fr.dst, n, algorithm, int(max_hops))
        if path:
            fr.routable = True
            fr.path = path
            fr.hop_count = len(path) - 1
            fr.delivered_mbps = demand
            fr.latency_ms = _latency_ms(path, dist)
        results.append(fr)
    _apply_congestion(results, cap)
    return results
