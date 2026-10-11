"""Episode metric reductions, units, comparison rules, and export order."""

import math

from dataclasses import dataclass, field
from typing import Callable

METRIC_SOURCE = {
    "kind": "telemetry_window",
    "warmup_excluded": True,
    "movement": {
        "nodes": "controlled",
        "measurement": "xy_endpoint_distance",
        "origin": "last_unscored_endpoint_or_reset",
        "incomplete_or_partial_warmup": "null",
    },
    "initial_relocation": {
        "nodes": "baseline_selected",
        "measurement": "xy_source_to_plan_distance",
        "window": "before_reset",
        "comparison": "separate_from_scored_travel",
    },
}
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


@dataclass
class ServiceTotals:
    coverage_sum: float = 0.0
    coverage_count: int = 0
    coverage_final: float | None = None
    safety_ticks: int = 0
    unsafe_ticks: int = 0
    min_distance: float | None = None
    offered: list | None = None
    received: list | None = None
    isolation: dict | None = None
    ids: list | None = None
    worst_sum: float = 0.0
    worst_count: int = 0
    onset: float | None = None
    before_demand: float = 0.0
    before_delivered: float = 0.0
    after_demand: float = 0.0
    after_delivered: float = 0.0
    streak: int = 0
    recovery_start: float | None = None
    recovery: float | None = None

    def add(self, record, num_links, contract):
        if contract is None or int(record.get("decision", 0)) == 0:
            return
        self.onset = contract.get("jammer_onset_s")
        facts = record["facts"]
        window = facts["window"]
        ticks = int(window["scored_ticks"])
        if not ticks:
            return
        if "coverage" in facts:
            self.coverage_final = float(facts["coverage"]["fraction"])
            self.coverage_sum += self.coverage_final
            self.coverage_count += 1
        if "safety" in facts:
            self.safety_ticks += ticks
            self.unsafe_ticks += int(facts["safety"]["unsafe_ticks"])
            distance = facts["safety"].get("min_pair_distance_m")
            if distance is not None:
                self.min_distance = distance if self.min_distance is None else min(self.min_distance, distance)
        service = facts.get("node_service")
        if service is not None:
            if self.ids is None:
                self.ids = contract["node_ids"]
                self.offered = [0.0] * len(self.ids)
                self.received = [0.0] * len(self.ids)
                self.isolation = dict.fromkeys(self.ids, 0)
            ratios = []
            for i, (demand, delivered) in enumerate(service):
                self.offered[i] += demand
                self.received[i] += delivered
                if demand > _DEMAND_EPS:
                    ratios.append(delivered / demand)
            if ratios:
                self.worst_sum += min(ratios)
                self.worst_count += 1
            linked = [False] * len(self.ids)
            index = 0
            for i in range(len(self.ids)):
                for j in range(i + 1, len(self.ids)):
                    if facts["links"][index][1] > 0:
                        linked[i] = linked[j] = True
                    index += 1
            for i, node in enumerate(self.ids):
                self.isolation[node] += int(not linked[i])
        if self.onset is not None:
            demand = float(window["demand_mbps_sum"])
            delivered = float(window["delivered_mbps_sum"])
            # A window crossing jammer onset cannot be split from aggregate sums.
            start = max(float(record["time_s"]) - record["ticks_in_step"] * contract["tick_s"],
                        float(contract.get("warmup_s", 0)))
            if record["time_s"] < self.onset:
                self.before_demand += demand
                self.before_delivered += delivered
            elif start >= self.onset:
                self.after_demand += demand
                self.after_delivered += delivered
                if demand > _DEMAND_EPS and delivered / demand >= .9:
                    if self.streak == 0:
                        self.recovery_start = start
                    self.streak += 1
                    if self.streak == 30 and self.recovery is None:
                        self.recovery = max(0.0, self.recovery_start - self.onset)
                else:
                    self.streak = 0

    def ratios(self):
        return ({node: _ratio(self.received[i], self.offered[i], _DEMAND_EPS)
                 for i, node in enumerate(self.ids)} if self.ids is not None else None)

    def worst_episode(self):
        ratios = self.ratios()
        valid = [value for value in (ratios or {}).values() if value is not None]
        return min(valid) if valid else None


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
    optional: bool = False

    def value(self, record, name):
        return (record.get(name) if self.reduce is None else
                (record.get("metrics") or {}).get(name))


# In CSV order. A missing direction means the diagnostic is not paired or grouped.
REGISTRY = {
    "return": Metric("reward", True, False),
    "delivery_ratio": Metric(
        "ratio", True, True, lambda t: _ratio(t.delivered, t.demand, _DEMAND_EPS)
    ),
    "connectivity": Metric("fraction", True, True, lambda t: _ratio(t.connected, t.pairs)),
    "los_fraction": Metric("fraction", True, True, lambda t: _ratio(t.los, t.pairs)),
    "unroutable_fraction": Metric(
        "fraction", False, True, lambda t: _ratio(t.unroutable, t.flow_ticks)
    ),
    "first_all_los_decision": Metric("decision", None, True, lambda t: t.first_all_los_decision),
    "initial_displacement_m_total": Metric("m", None, True),
    "travel_m_total": Metric("m", False, True, lambda t: t.total("travel"), MovementTotals),
    "displacement_m_final": Metric(
        "m", None, True, lambda t: t.total("displacement"), MovementTotals
    ),
    "per_node_travel_m": Metric(
        "m", None, True, lambda t: t.per_node("travel"), MovementTotals, False
    ),
    "per_node_displacement_m": Metric(
        "m", None, True, lambda t: t.per_node("displacement"), MovementTotals, False
    ),
}
REGISTRY.update({
    "coverage_fraction_mean": Metric("fraction", True, True, lambda t: _ratio(t.coverage_sum, t.coverage_count), ServiceTotals, optional=True),
    "coverage_fraction_final": Metric("fraction", True, True, lambda t: t.coverage_final, ServiceTotals, optional=True),
    "unsafe_proximity_fraction": Metric("fraction", False, True, lambda t: _ratio(t.unsafe_ticks, t.safety_ticks), ServiceTotals, optional=True),
    "min_pair_distance_m": Metric("m", None, True, lambda t: t.min_distance, ServiceTotals, optional=True),
    "worst_node_delivery_fraction": Metric("fraction", True, True, lambda t: _ratio(t.worst_sum, t.worst_count), ServiceTotals, optional=True),
    "worst_node_delivery_fraction_episode": Metric("fraction", True, True, lambda t: t.worst_episode(), ServiceTotals, optional=True),
    "per_node_delivery_fraction": Metric("fraction", None, True, lambda t: t.ratios(), ServiceTotals, False, True),
    "per_node_isolated_decisions": Metric("decisions", None, True, lambda t: t.isolation, ServiceTotals, False, True),
    "jammer_onset_s": Metric("s", None, True, lambda t: t.onset, ServiceTotals, optional=True),
    "pre_jammer_delivery_ratio": Metric("ratio", True, True, lambda t: _ratio(t.before_delivered, t.before_demand, _DEMAND_EPS), ServiceTotals, optional=True),
    "post_jammer_delivery_ratio": Metric("ratio", True, True, lambda t: _ratio(t.after_delivered, t.after_demand, _DEMAND_EPS), ServiceTotals, optional=True),
    "recovery_time_s": Metric("s", False, True, lambda t: t.recovery, ServiceTotals, optional=True),
})

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
