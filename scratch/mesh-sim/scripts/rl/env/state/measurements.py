"""Current-position and current-radio measurements for coordinated mission rewards."""

import math


def mean(values):
    return sum(values) / len(values) if values else 0.0


def lower_tail(values):
    """Average the worst ceil(N/3) contributions; never dilute with healthy peers."""
    count = max(1, math.ceil(len(values) / 3))
    return mean(sorted(values)[:count])


def isolation(points, span=150.0):
    """Largest edge of the XY minimum spanning tree / 150 m, clipped at one."""
    if len(points) < 2:
        return 0.0
    used = {0}
    largest = 0.0
    while len(used) < len(points):
        distance, node = min(
            (math.dist(points[a][:2], points[b][:2]), b)
            for a in used
            for b in range(len(points))
            if b not in used
        )
        largest = max(largest, distance)
        used.add(node)
    return min(1.0, largest / span)


def link_support(facts, contract, active):
    """Bottom-third demanded-pair widest-path SINR; capacity is measured by D/F."""
    ids = contract["node_ids"]
    n = len(ids)
    margins = [[-1000.0] * n for _ in ids]
    k = 0
    for i in range(n):
        margins[i][i] = float("inf")
        for j in range(i + 1, n):
            if i in active and j in active:
                margins[i][j] = margins[j][i] = facts["links"][k][0]
            k += 1
    if contract["mission"]["kind"] == "recovery":
        pairs = [
            (i, ids.index("vehicle-" + node.split("-", 1)[1]))
            for i, node in enumerate(ids)
            if node.startswith("ground-") and "vehicle-" + node.split("-", 1)[1] in ids
        ]
        pairs = [(i, j) for i, j in pairs if i in active and j in active]
    else:
        pairs = [(i, j) for i in active for j in active if i < j]
    for relay in active:
        for i in active:
            for j in active:
                margins[i][j] = max(margins[i][j], min(margins[i][relay], margins[relay][j]))
    return lower_tail(
        [1 / (1 + math.exp(max(-60.0, min(60.0, -(margins[i][j] + 6.7) / 4.0)))) for i, j in pairs]
    )


def measurements(facts, contract, mission=None):
    m = contract["mission"]
    mission = mission or m["kind"]
    active = [i for i, v in enumerate(facts["node_available"]) if v]
    raw = facts["mission"] if mission == "recovery" else facts["window"]
    prefix = "survivor_" if mission == "recovery" else ""
    demand = raw[prefix + "demand_mbps_sum"]
    delivered = raw[prefix + "delivered_mbps_sum"]
    service = (
        facts["mission"]["survivor_node_service"]
        if mission == "recovery"
        else facts["node_service"]
    )
    ratios = [
        min(1.0, max(0.0, v / d)) for i, (d, v) in enumerate(service) if i in active and d > 1e-9
    ]
    distances = [math.dist(facts["nodes"][i][:2], [m["goal_x"], m["goal_y"]]) for i in active]
    radius = m.get("team_radius_m", 50.0)
    proximities = [math.exp(-max(0.0, distance - radius) / 100.0) for distance in distances]
    k = 0
    los = []
    for i in range(len(facts["nodes"])):
        for j in range(i + 1, len(facts["nodes"])):
            if i in active and j in active:
                los.append(facts["links"][k][2])
            k += 1
    return dict(
        D=min(1.0, max(0.0, delivered / demand)) if demand > 1e-9 else 0.0,
        F=lower_tail(ratios),
        W=min(ratios) if ratios else 0.0,
        L=link_support(facts, contract, active)
        if mission in ("recovery", "jamming") and demand > 1e-9
        else 0.0,
        Q=0.5 * (mean(proximities) + min(proximities)) if proximities else 0.0,
        A=mean([d <= radius for d in distances]),
        K=float(facts["mission_state"].get("team_connected", False)),
        area=facts["coverage"]["fraction"],
        I=isolation([facts["nodes"][i] for i in active]),
        los_deficit=1 - mean(los),
        max_target_distance=max(distances) if distances else 0.0,
        active_count=len(active),
        demand=demand,
    )


def global_bridge_support(facts, contract):
    """Sigmoid of the weakest active pair's widest-path bottleneck SINR in dB."""
    active = [i for i, available in enumerate(facts["node_available"]) if available]
    if len(active) < 2:
        return 0.0
    n = len(contract["node_ids"])
    margins = [[-math.inf] * n for _ in range(n)]
    k = 0
    for i in range(n):
        margins[i][i] = math.inf
        for j in range(i + 1, n):
            if i in active and j in active:
                value = float(facts["links"][k][0])
                if not math.isfinite(value):
                    raise ValueError("whole-team support requires finite current SINR")
                margins[i][j] = margins[j][i] = value
            k += 1
    for relay in active:
        for i in active:
            for j in active:
                margins[i][j] = max(margins[i][j], min(margins[i][relay], margins[relay][j]))
    weakest = min(margins[i][j] for i in active for j in active if i < j)
    return 1 / (1 + math.exp(max(-60.0, min(60.0, -(weakest + 6.7) / 4.0))))
