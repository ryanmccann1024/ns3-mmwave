"""Episode metric reductions, units, comparison rules, and export order."""

from dataclasses import dataclass
from typing import Callable

METRIC_SOURCE = {"kind": "telemetry_window", "warmup_excluded": True}
_DEMAND_EPS = 1e-9


@dataclass
class WindowTotals:
    demand: float = 0.0
    delivered: float = 0.0
    connected: int = 0
    los: int = 0
    pairs: int = 0
    flow_ticks: int = 0
    unroutable: int = 0
    first_all_los_decision: int | None = None


def _ratio(numerator, denominator, minimum=0):
    return numerator / denominator if denominator > minimum else None


@dataclass(frozen=True)
class Metric:
    units: str
    higher_is_better: bool | None
    comparable_across_reward_definitions: bool
    reduce: Callable | None = None

    def value(self, record, name):
        return (record.get(name) if self.reduce is None else
                (record.get("metrics") or {}).get(name))


# In CSV order. A missing direction means the diagnostic is not paired or grouped.
REGISTRY = {
    "return": Metric("reward", True, False),
    "delivery_ratio": Metric("ratio", True, True,
                             lambda t: _ratio(t.delivered, t.demand, _DEMAND_EPS)),
    "connectivity": Metric("fraction", True, True,
                           lambda t: _ratio(t.connected, t.pairs)),
    "los_fraction": Metric("fraction", True, True, lambda t: _ratio(t.los, t.pairs)),
    "unroutable_fraction": Metric("fraction", False, True,
                                  lambda t: _ratio(t.unroutable, t.flow_ticks)),
    "first_all_los_decision": Metric("decision", None, True,
                                     lambda t: t.first_all_los_decision),
}
METRICS = {name: (metric.higher_is_better, metric.comparable_across_reward_definitions)
           for name, metric in sorted(REGISTRY.items()) if metric.higher_is_better is not None}
GROUP_METRICS = tuple(name for name, (_, shared) in METRICS.items() if shared)
CSV_METRICS = tuple(name for name, metric in REGISTRY.items() if metric.reduce is not None)
CSV_METRIC_COLUMNS = tuple(REGISTRY)


def metric_value(record, name):
    return REGISTRY[name].value(record, name)


def episode_metrics(records, num_links: int) -> dict:
    """Reduce scored telemetry windows; empty scored windows have null metrics."""
    totals = WindowTotals()
    for record in records:
        window = record["facts"]["window"]
        ticks = int(window["scored_ticks"])
        totals.pairs += ticks * num_links
        totals.demand += float(window["demand_mbps_sum"])
        totals.delivered += float(window["delivered_mbps_sum"])
        totals.connected += int(window["connected_pairs_sum"])
        totals.los += int(window["los_pairs_sum"])
        totals.flow_ticks += int(window["flow_ticks_with_demand"])
        totals.unroutable += int(window["unroutable_flow_ticks"])
        if (totals.first_all_los_decision is None and ticks > 0 and num_links > 0
                and int(window["los_pairs_sum"]) == ticks * num_links):
            totals.first_all_los_decision = int(record["decision"])
    return {name: metric.reduce(totals) for name, metric in REGISTRY.items()
            if metric.reduce is not None}


def check_metric_source(source):
    """Refuse missing or obsolete scoring metadata rather than relabeling results."""
    if (not isinstance(source, dict) or source.get("kind") != METRIC_SOURCE["kind"]
            or source.get("warmup_excluded") is not True):
        raise ValueError(f"metric_source must describe scored telemetry with warmup excluded; "
                         f"got {source!r}; re-evaluate with current tooling")
