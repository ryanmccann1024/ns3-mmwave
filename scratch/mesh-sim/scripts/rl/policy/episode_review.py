"""Endpoint service and recovery measurements from saved decision traces."""

import json
from pathlib import Path


def delivery(rows):
    demand = sum(r["facts"]["window"]["demand_mbps_sum"] for r in rows)
    received = sum(r["facts"]["window"]["delivered_mbps_sum"] for r in rows)
    return received/demand if demand > 1e-9 else None


def endpoint_metrics(episode_dir, seconds=60):
    path = Path(episode_dir)
    records = [json.loads(line) for line in (path/"steps.jsonl").open()]
    rows = [r for r in records if r.get("decision", 0) > 0]
    if not rows:
        raise ValueError("endpoint metrics require recorded decisions")
    tail = [r for r in rows if r["time_s"] > rows[-1]["time_s"]-seconds]
    count = len(tail[0]["facts"]["node_service"])
    service = []
    for i in range(count):
        demand = sum(r["facts"]["node_service"][i][0] for r in tail)
        received = sum(r["facts"]["node_service"][i][1] for r in tail)
        if demand > 1e-9:
            service.append(received/demand)
    coverage = [r["facts"]["coverage"]["fraction"] for r in tail]
    episode = json.loads((path/"rl_episode.json").read_text())
    start = episode.get("jammer_motion", {}).get("motion_start_s")
    degraded = recovered = None
    streak = 0
    for row in rows:
        if start is None or row["time_s"] <= start:
            continue
        share = delivery([row])
        if share is not None and share < .9:
            if degraded is None:
                degraded = row["time_s"]
            streak = 0
        elif degraded is not None and recovered is None:
            streak += 1
            if streak == 30:
                recovered = row["time_s"]-29*records[0]["contract"]["decision_interval_s"]
    return {"endpoint_window_s": seconds, "endpoint_delivery_ratio": delivery(tail),
            "endpoint_worst_node_delivery": min(service) if service else None,
            "endpoint_coverage_fraction": sum(coverage)/len(coverage),
            "motion_start_s": start, "first_degradation_s": degraded,
            "first_recovery_s": recovered,
            "recovery_after_degradation_s": recovered-degraded if recovered is not None else None}
