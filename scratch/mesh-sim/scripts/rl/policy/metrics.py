"""Episode metric reductions, units, comparison rules, and export order."""

import math

from dataclasses import dataclass, field
from typing import Callable

METRIC_SOURCE = {"kind": "telemetry_window", "warmup_excluded": True,
                 "movement": {"nodes": "controlled", "measurement": "xy_endpoint_distance",
                              "origin": "last_unscored_endpoint_or_reset",
                              "incomplete_or_partial_warmup": "null"}}
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

    def add(self, record, num_links, contract):
        if int(record.get("decision", 0)) == 0:
            return
        window = record["facts"]["window"]
        ticks = int(window["scored_ticks"])
        self.pairs += ticks * num_links
        self.demand += float(window["demand_mbps_sum"])
        self.delivered += float(window["delivered_mbps_sum"])
        self.connected += int(window["connected_pairs_sum"])
        self.los += int(window["los_pairs_sum"])
        self.flow_ticks += int(window["flow_ticks_with_demand"])
        self.unroutable += int(window["unroutable_flow_ticks"])
        if (self.first_all_los_decision is None and ticks > 0 and num_links > 0
                and int(window["los_pairs_sum"]) == ticks * num_links):
            self.first_all_los_decision = int(record["decision"])


@dataclass
class MovementTotals:
    previous: list | None = None
    origin: list | None = None
    last_decision: int = -1
    travel: dict = field(default_factory=dict)
    displacement: dict = field(default_factory=dict)
    complete: bool = True
    scored: bool = False

    def add(self, record, num_links, contract):
        current = record["facts"].get("nodes")
        decision = int(record["decision"])
        if contract is None or current is None:
            self.complete = False
            return
        if decision != self.last_decision + 1:
            self.complete = False
        self.last_decision = decision
        if decision == 0:
            self.previous = self.origin = current
            self.travel = {node: 0.0 for node in contract["slot_node_ids"] if node is not None}
            return
        window = record["facts"]["window"]
        scored = int(window["scored_ticks"])
        if scored and scored != int(record["ticks_in_step"]):
            self.complete = False
        if scored and self.previous is not None:
            self.scored = True
            for node in self.travel:
                index = contract["node_ids"].index(node)
                self.travel[node] += math.hypot(current[index][0] - self.previous[index][0],
                                               current[index][1] - self.previous[index][1])
                self.displacement[node] = math.hypot(current[index][0] - self.origin[index][0],
                                                     current[index][1] - self.origin[index][1])
        elif not self.scored:
            self.origin = current
        self.previous = current

    def total(self, field):
        return sum(getattr(self, field).values()) if self.complete and self.scored else None

    def per_node(self, field):
        return dict(getattr(self, field)) if self.complete and self.scored else None


def _ratio(numerator, denominator, minimum=0):
    return numerator / denominator if denominator > minimum else None


@dataclass(frozen=True)
class Metric:
    units: str
    higher_is_better: bool | None
    comparable_across_reward_definitions: bool
    reduce: Callable | None = None
    accumulator: Callable = WindowTotals
    export: bool = True

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
    "travel_m_total": Metric("m", False, True, lambda t: t.total("travel"), MovementTotals),
    "displacement_m_final": Metric("m", None, True, lambda t: t.total("displacement"), MovementTotals),
    "per_node_travel_m": Metric("m", None, True, lambda t: t.per_node("travel"), MovementTotals, False),
    "per_node_displacement_m": Metric("m", None, True, lambda t: t.per_node("displacement"), MovementTotals, False),
}
METRICS = {name: (metric.higher_is_better, metric.comparable_across_reward_definitions)
           for name, metric in sorted(REGISTRY.items()) if metric.higher_is_better is not None}
GROUP_METRICS = tuple(name for name, (_, shared) in METRICS.items() if shared)
CSV_METRICS = tuple(name for name, metric in REGISTRY.items() if metric.reduce is not None and metric.export)
CSV_METRIC_COLUMNS = tuple(name for name, metric in REGISTRY.items() if metric.export)


def metric_value(record, name):
    return REGISTRY[name].value(record, name)


def episode_metrics(records, num_links: int, contract=None) -> dict:
    """Stream records through the accumulator declared by each metric."""
    factories = dict.fromkeys(metric.accumulator for metric in REGISTRY.values()
                              if metric.reduce is not None)
    accumulators = {factory: factory() for factory in factories}
    for record in records:
        for accumulator in accumulators.values():
            accumulator.add(record, num_links, contract)
    return {name: metric.reduce(accumulators[metric.accumulator])
            for name, metric in REGISTRY.items() if metric.reduce is not None}


def check_metric_source(source):
    """Refuse missing or obsolete scoring metadata rather than relabeling results."""
    if (not isinstance(source, dict) or source.get("kind") != METRIC_SOURCE["kind"]
            or source.get("warmup_excluded") is not True):
        raise ValueError(f"metric_source must describe scored telemetry with warmup excluded; "
                         f"got {source!r}; re-evaluate with current tooling")
