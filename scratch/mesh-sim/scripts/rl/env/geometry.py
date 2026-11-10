"""Pure route, swept-segment and recorded-path geometry for legal mission motion.

Building boxes use the simulator's `{x,y,z}_{min,max}` keys. Nothing here loads
a model, a bundle or a simulator.
"""

import heapq
import math

import numpy as np


def segment_hits(a, b, box, clearance=0):
    """True when segment a->b touches `box` expanded by `clearance` on every axis."""
    entry, exit = 0.0, 1.0
    for axis, key in enumerate("xyz"):
        lo, hi = box[key + "_min"] - clearance, box[key + "_max"] + clearance
        delta = b[axis] - a[axis]
        if abs(delta) < 1e-12:
            if not lo <= a[axis] <= hi:
                return False
        else:
            t0, t1 = sorted(((lo - a[axis]) / delta, (hi - a[axis]) / delta))
            entry = max(entry, t0)
            exit = min(exit, t1)
            if entry > exit:
                return False
    return True


def safe_segment(a, b, buildings, clearance=3.0):
    return not any(segment_hits(a, b, box, clearance) for box in buildings)


def route(start, target, buildings, spacing=5):
    """A* on the closed 0..400 m map; preserve height and check every swept segment."""
    z = start[2]
    first = tuple(round(v / spacing) for v in start[:2])
    last = tuple(round(v / spacing) for v in target[:2])

    def point(cell):
        return (cell[0] * spacing, cell[1] * spacing, z)

    if not safe_segment(start, point(first), buildings):
        raise ValueError("start cannot reach route grid")
    if not safe_segment(point(last), (*target[:2], z), buildings):
        raise ValueError("target cannot reach route grid")
    queue = [(0, first)]
    cost, previous = {first: 0}, {}
    while queue:
        _, current = heapq.heappop(queue)
        if current == last:
            cells = [last]
            while cells[-1] != first:
                cells.append(previous[cells[-1]])
            points = [point(c) for c in reversed(cells)]
            points.append((*target[:2], z))
            # Collapse collinear segments, retaining corners and exact endpoints.
            compact = [tuple(start)]
            for p in points:
                if p == compact[-1]:
                    continue
                if len(compact) > 1:
                    a, b = compact[-2], compact[-1]
                    if (b[0] - a[0]) * (p[1] - b[1]) == (b[1] - a[1]) * (p[0] - b[0]):
                        compact[-1] = p
                        continue
                compact.append(p)
            return [list(p) for p in compact[1:]] or [list(start)]
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nxt = current[0] + dx, current[1] + dy
            if not all(0 <= v * spacing <= 400 for v in nxt):
                continue
            distance = cost[current] + spacing
            if distance >= cost.get(nxt, math.inf):
                continue
            if not safe_segment(point(current), point(nxt), buildings):
                continue
            cost[nxt], previous[nxt] = distance, current
            heuristic = spacing * sum(abs(a - b) for a, b in zip(nxt, last))
            heapq.heappush(queue, (distance + heuristic, nxt))
    raise ValueError(f"no physical route: {start} -> {target}")


def swept_distance(a, b, c, d):
    """Closest approach of two points moving linearly a->b and c->d (XYZ only)."""
    relative = np.asarray(a[:3], dtype=float) - c[:3]
    delta = np.asarray(b[:3], dtype=float) - d[:3] - relative
    denom = float(delta @ delta)
    t = float(np.clip(-relative @ delta / denom, 0, 1)) if denom else 0
    return float(np.linalg.norm(relative + t * delta))


def physical_audit(records, contract):
    """Check dense paths and actual resolved geometry, including closest swept peer approach."""
    nav = contract["navigation"]
    clearance = nav["building_clearance_m"]
    minimum = math.inf
    for record in records:
        for p in record["facts"]["nodes"]:
            if any(segment_hits(p, p, b, clearance) for b in nav["buildings"]):
                raise ValueError("recorded position penetrates building clearance")
    for previous, current in zip(records, records[1:]):
        a, b = previous["facts"]["nodes"], current["facts"]["nodes"]
        available = previous["facts"]["node_available"]
        for i in range(len(a)):
            if any(segment_hits(a[i], b[i], box, clearance) for box in nav["buildings"]):
                raise ValueError("recorded movement crosses a building")
            for j in range(i + 1, len(a)):
                if not available[i] or not available[j]:
                    continue
                relative = [a[i][k] - a[j][k] for k in range(3)]
                delta = [(b[i][k] - b[j][k]) - relative[k] for k in range(3)]
                denominator = sum(v * v for v in delta)
                u = (
                    max(0, min(1, -sum(x * y for x, y in zip(relative, delta)) / denominator))
                    if denominator
                    else 0
                )
                distance = math.sqrt(sum((x + u * y) ** 2 for x, y in zip(relative, delta)))
                minimum = min(minimum, distance)
                if distance + 1e-6 < contract["unsafe_separation_m"]:
                    raise ValueError("recorded peer collision")
    return {"building_penetrations": 0, "peer_collisions": 0, "min_swept_peer_distance_m": minimum}
