"""Composable rewards with component-owned parameters, dependencies, and schemas."""

import math
from dataclasses import dataclass, field
from typing import Callable, Sequence

from scripts.artifact_io import canonical_sha256
from .normalization import Normalization, SINR_FIELDS

DEMAND_EPS = 1e-9
MOVEMENT_SPAN_M = {"drone": 500.0, "pedestrian": 300.0, "vehicle": 300.0}
COHESION_FLOOR_M = 20.0


def _distance_3d(a: list, b: list) -> float:
    return math.sqrt(sum((float(a[axis]) - float(b[axis])) ** 2 for axis in range(3)))


def _delivery_ratio(window: dict, msg_reward: float, contract: dict, parameters: dict, context: dict) -> tuple[float, bool]:
    demand = float(window["demand_mbps_sum"])
    if demand <= DEMAND_EPS:
        return 0.0, False
    return float(window["delivered_mbps_sum"]) / demand, True


def _delivery_binary(window: dict, msg_reward: float, contract: dict, parameters: dict, context: dict) -> tuple[float, bool]:
    """Reward any measured delivery and penalize a complete service failure."""
    demand = float(window["demand_mbps_sum"])
    if demand <= DEMAND_EPS:
        return 0.0, False
    delivered = float(window["delivered_mbps_sum"])
    return (1.0 if delivered > DEMAND_EPS else -1.0), True


def _signed_delivery_ratio(window: dict, msg_reward: float,
                           contract: dict, parameters: dict, context: dict) -> tuple[float, bool]:
    """Map delivered/offered demand from [0, 1] to a symmetric [-1, 1]."""
    ratio, valid = _delivery_ratio(window, msg_reward, contract, parameters, context)
    if not valid:
        return 0.0, False
    return 2.0 * max(0.0, min(1.0, ratio)) - 1.0, True


def _connectivity(window: dict, msg_reward: float, contract: dict, parameters: dict, context: dict) -> tuple[float, bool]:
    pairs = int(window["scored_ticks"]) * int(contract["num_links"])
    if pairs <= 0:
        return 0.0, True
    return float(window["connected_pairs_sum"]) / pairs, True


def _throughput_mbps(window: dict, msg_reward: float, contract: dict, parameters: dict, context: dict) -> tuple[float, bool]:
    return float(window["delivered_mbps_sum"]) / int(window["scored_ticks"]), True


def _legacy(window: dict, msg_reward: float, contract: dict, parameters: dict, context: dict) -> tuple[float, bool]:
    return float(window["legacy_reward_sum"]) / int(window["scored_ticks"]), True


def _service_success(window: dict, msg_reward: float, contract: dict, parameters: dict, context: dict) -> tuple[float, bool]:
    demand = float(window["demand_mbps_sum"])
    flows = int(window["flow_ticks_with_demand"])
    if demand <= DEMAND_EPS or flows == 0:
        return -1.0, True
    delivered = float(window["delivered_mbps_sum"]) / demand
    routable = 1.0 - int(window["unroutable_flow_ticks"]) / flows
    return (1.0 if delivered >= parameters["delivery_threshold"] and routable >= parameters["routable_threshold"]
            else -1.0), True


def _service_failure(window: dict, msg_reward: float, contract: dict, parameters: dict, context: dict) -> tuple[float, bool]:
    success, _ = _service_success(window, msg_reward, contract, parameters, context)
    return (1.0 if success < 0 else 0.0), True


def position_context(facts, previous_nodes, initial_nodes, contract, elapsed_ticks=None):
    """Endpoint movement measurements; mixed warmup windows have no travel cost."""
    window = facts["window"]
    ticks = int(window.get("ticks", contract["decision_interval_ticks"]) if elapsed_ticks is None else elapsed_ticks)
    interval = ticks * float(contract["tick_s"])
    if interval <= 0:
        return {}
    bounds = contract["bounds"]
    diagonal = math.hypot(bounds["x_max"] - bounds["x_min"],
                          bounds["y_max"] - bounds["y_min"])
    travel, displacement = [], []
    slots = [node for node in contract["slot_node_ids"] if node is not None]
    node_ids = contract["node_ids"]
    travel_by_type = {kind: 0.0 for kind in MOVEMENT_SPAN_M}
    span_travel = 0.0
    node_types = contract.get("node_types")
    for slot, node_id in enumerate(contract["slot_node_ids"]):
        if node_id is None:
            continue
        index = node_ids.index(node_id)
        current, previous, initial = (facts["nodes"][index], previous_nodes[index],
                                      initial_nodes[index])
        speed = float(contract["slot_speed_mps"][slot])
        moved_m = math.hypot(current[0] - previous[0], current[1] - previous[1])
        fraction = min(1.0, moved_m / (speed * interval))
        travel.append(fraction)
        if node_types is not None and node_types[index] in travel_by_type:
            travel_by_type[node_types[index]] += fraction
            span_travel += moved_m / MOVEMENT_SPAN_M[node_types[index]]
        displacement.append(min(1.0, math.hypot(current[0] - initial[0],
                                                 current[1] - initial[1]) / diagonal))
    scales = Normalization()
    qualities = [scales.sinr_quality(float(link[0])) for link in facts["links"]]
    context = {"travel_fraction": sum(travel) / len(travel),
               "origin_fraction": sum(displacement) / len(displacement),
               "sinr_quality": sum(qualities) / len(qualities) if qualities else 0.0}
    if node_types is not None:
        context.update({f"{kind}_travel_fraction": value / len(travel)
                        for kind, value in travel_by_type.items()})
        context["span_travel_fraction"] = span_travel / len(travel)
        if all(node_types[node_ids.index(node_id)] in MOVEMENT_SPAN_M for node_id in slots):
            cohesion = []
            for node_id in slots:
                index = node_ids.index(node_id)
                if len(node_ids) < 2:
                    cohesion.append(0.0)
                    continue
                peer = min((j for j in range(len(node_ids)) if j != index),
                           key=lambda j: (_distance_3d(initial_nodes[index], initial_nodes[j]), j))
                reference = max(COHESION_FLOOR_M,
                                _distance_3d(initial_nodes[index], initial_nodes[peer]))
                distance = max(COHESION_FLOOR_M,
                               _distance_3d(facts["nodes"][index], facts["nodes"][peer]))
                span = MOVEMENT_SPAN_M[node_types[index]]
                cohesion.append(max(-1.0, min(1.0, (reference - distance) / span)))
            context["peer_cohesion"] = sum(cohesion) / len(cohesion)
    safety = facts.get("safety")
    if safety is not None:
        context["unsafe_proximity_fraction"] = (
            int(safety["unsafe_ticks"]) / max(1, int(facts["window"]["scored_ticks"])))
    if "coverage" in facts:
        context["coverage_fraction"] = float(facts["coverage"]["fraction"])
    service = facts.get("node_service")
    if service is not None:
        ratios = [min(1.0, max(0.0, float(delivered) / float(demand)))
                  for demand, delivered in service if float(demand) > DEMAND_EPS]
        context["worst_node_delivery_fraction"] = min(ratios) if ratios else None
        context["fair_node_service"] = sum(math.sqrt(r) for r in ratios)/len(ratios) if ratios else None
    if int(window["scored_ticks"]) != ticks:
        for key in ("travel_fraction", "span_travel_fraction", "drone_travel_fraction",
                    "pedestrian_travel_fraction", "vehicle_travel_fraction"):
            if key in context:
                context[key] = None
    return context


def _movement_context(facts, contract, inputs):
    if inputs is None:
        raise ValueError("movement rewards require previous and reset positions")
    return position_context(facts, inputs["previous_nodes"], inputs["initial_nodes"],
                            contract, inputs["elapsed_ticks"])


def _context_fraction(key):
    def calculate(window, msg_reward, contract, parameters, context):
        value = context[key]
        return (0.0, False) if value is None else (float(value), True)
    return calculate


def _sinr_quality(window, msg_reward, contract, parameters, context):
    scales = Normalization(**parameters)
    links = context["links"]
    return (sum(scales.sinr_quality(float(link[0])) for link in links) / len(links)
            if links else 0.0), True


def _unmet_sinr_quality(window, msg_reward, contract, parameters, context):
    demand = float(window["demand_mbps_sum"])
    ratio = float(window["delivered_mbps_sum"]) / demand if demand > DEMAND_EPS else 0.0
    threshold = parameters["delivery_threshold"]
    unmet = max(0.0, min(1.0, (threshold - ratio) / threshold))
    quality, _ = _sinr_quality(window, msg_reward, contract,
                              {key: parameters[key] for key in SINR_FIELDS}, context)
    return quality * unmet, True



def _adaptive_movement_cost(window, msg_reward, contract, parameters, context):
    travel = context["travel_fraction"]
    return ((0.0, False) if travel is None else
            ((0.02 + 0.08 * context["previous_network_health"]) * travel, True))


def _throughput_log_mbps(window, msg_reward, contract, parameters, context):
    return math.log1p(max(0.0, float(window["delivered_mbps_sum"]) / int(window["scored_ticks"]))), True


@dataclass(frozen=True)
class RewardComponent:
    name: str
    _value: Callable
    range: tuple[float | None, float | None]
    required_facts: tuple[str, ...]
    parameters: dict = field(default_factory=dict)
    contract_fields: tuple[str, ...] = ()
    tunable: dict = field(default_factory=dict)
    context_fields: tuple[str, ...] = ()
    formula: str = ""
    zero_demand_rule: str = "not_applicable"
    context_builder: Callable | None = None

    def resolve(self, overrides):
        if not isinstance(overrides, dict):
            raise ValueError(f"{self.name} parameters must be an object")
        unknown = set(overrides) - set(self.tunable)
        if unknown:
            raise ValueError(f"{self.name} has unknown parameters: {sorted(unknown)}")
        resolved = dict(self.parameters)
        for key, (default, low, high) in self.tunable.items():
            value = overrides.get(key, default)
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                    not math.isfinite(value) or (low is not None and value <= low) or
                    (high is not None and value > high)):
                raise ValueError(f"{self.name}.{key} must be finite in ({low}, {high}]")
            resolved[key] = float(value)
        if set(SINR_FIELDS) <= set(resolved):
            Normalization(**{key: resolved[key] for key in SINR_FIELDS})
        return resolved

    def value(self, window, msg_reward, contract, context=None, parameters=None):
        if not window["scored_ticks"]:
            return 0.0, False
        context = {} if context is None else context
        missing = set(self.context_fields) - set(context)
        if missing:
            raise ValueError(f"{self.name} requires context: {sorted(missing)}")
        return self._value(window, msg_reward, contract,
                           self.resolve({}) if parameters is None else parameters, context)

    def schema(self, contract, parameters=None):
        resolved = self.resolve({}) if parameters is None else parameters
        return {"range": list(self.range), "required_facts": list(self.required_facts),
                "context_fields": list(self.context_fields), "parameters": dict(resolved),
                "formula": self.formula.format(**resolved),
                "zero_demand_rule": self.zero_demand_rule,
                "contract": {key: contract[key] for key in self.contract_fields}}


_SERVICE_PARAMETERS = {"delivery_threshold": (0.95, 0.0, 1.0),
                       "routable_threshold": (0.95, 0.0, 1.0)}
_SINR_PARAMETERS = {key: (getattr(Normalization(), key), None, None) for key in SINR_FIELDS}
_SERVICE_FACTS = ("demand_mbps_sum", "delivered_mbps_sum",
                  "flow_ticks_with_demand", "unroutable_flow_ticks")

COMPONENTS = {
    "delivery_ratio": RewardComponent(
        "delivery_ratio", _delivery_ratio, (0.0, 1.0),
        ("demand_mbps_sum", "delivered_mbps_sum"),
        {"demand_epsilon_mbps_sum": DEMAND_EPS},
        formula="delivered/demand", zero_demand_rule="masked"),
    "delivery_binary": RewardComponent(
        "delivery_binary", _delivery_binary, (-1.0, 1.0),
        ("demand_mbps_sum", "delivered_mbps_sum"),
        {"demand_epsilon_mbps_sum": DEMAND_EPS},
        formula="+1 for any delivery, else -1", zero_demand_rule="masked"),
    "signed_delivery_ratio": RewardComponent(
        "signed_delivery_ratio", _signed_delivery_ratio, (-1.0, 1.0),
        ("demand_mbps_sum", "delivered_mbps_sum"),
        {"demand_epsilon_mbps_sum": DEMAND_EPS},
        formula="2*clip(delivered/demand,0,1)-1", zero_demand_rule="masked"),
    "connectivity": RewardComponent(
        "connectivity", _connectivity, (0.0, 1.0), ("connected_pairs_sum",),
        contract_fields=("num_links",), formula="connected_pairs_sum/(scored_ticks*num_links)"),
    "throughput_mbps": RewardComponent(
        "throughput_mbps", _throughput_mbps, (0.0, None), ("delivered_mbps_sum",),
        formula="delivered_mbps_sum/scored_ticks"),
    "legacy": RewardComponent(
        "legacy", _legacy, (None, None), ("legacy_reward_sum",),
        contract_fields=("reward_type", "reward_window"), formula="legacy_reward_sum/scored_ticks"),
    "service_success": RewardComponent(
        "service_success", _service_success, (-1.0, 1.0), _SERVICE_FACTS,
        tunable=_SERVICE_PARAMETERS,
        formula="+1 if delivery >= {delivery_threshold:g} and routable >= {routable_threshold:g}, else -1",
        zero_demand_rule="failure"),
    "service_failure": RewardComponent(
        "service_failure", _service_failure, (0.0, 1.0), _SERVICE_FACTS,
        tunable=_SERVICE_PARAMETERS,
        formula="1 if delivery < {delivery_threshold:g} or routable < {routable_threshold:g}, else 0",
        zero_demand_rule="failure"),
    "travel_fraction": RewardComponent(
        "travel_fraction", _context_fraction("travel_fraction"), (0.0, 1.0), ("nodes",),
        parameters={"partial_warmup_rule": "masked", "measurement": "xy_endpoint_distance"},
        context_fields=("travel_fraction",), context_builder=_movement_context,
        contract_fields=("slot_speed_mps", "tick_s", "slot_node_ids"),
        formula="mean controlled-slot endpoint distance/(speed*elapsed_ticks*tick_s), clipped [0,1]"),
    "origin_fraction": RewardComponent(
        "origin_fraction", _context_fraction("origin_fraction"), (0.0, 1.0), ("nodes",),
        context_fields=("origin_fraction",), context_builder=_movement_context, contract_fields=("bounds", "slot_node_ids"),
        formula="mean controlled-slot xy distance from reset/bounds diagonal, clipped [0,1]"),
    "sinr_quality": RewardComponent(
        "sinr_quality", _sinr_quality, (0.0, 1.0), ("links",),
        tunable=_SINR_PARAMETERS, context_fields=("links",),
        formula="mean SINR clipped [{sinr_min_db:g},{sinr_max_db:g}] and mapped to [0,1]; <= {sinr_invalid_db:g} scores 0"),
    "unmet_sinr_quality": RewardComponent(
        "unmet_sinr_quality", _unmet_sinr_quality, (0.0, 1.0),
        ("links", "demand_mbps_sum", "delivered_mbps_sum"),
        tunable={**_SINR_PARAMETERS, "delivery_threshold": _SERVICE_PARAMETERS["delivery_threshold"]},
        context_fields=("links",), zero_demand_rule="delivery_ratio_zero",
        formula="SINR quality [{sinr_min_db:g},{sinr_max_db:g}] above {sinr_invalid_db:g} * clip(({delivery_threshold:g}-delivery_ratio)/{delivery_threshold:g},0,1)"),
}

COMPONENTS["throughput_log_mbps"] = RewardComponent(
    "throughput_log_mbps", _throughput_log_mbps, (0.0, None), ("delivered_mbps_sum",),
    formula="ln(1 + delivered_mbps_sum/scored_ticks)")
for _name, _range, _facts, _fields, _parameters in (
    ("fair_node_service", (0.0, 1.0), ("node_service",), (), {"formula": "mean sqrt(clipped node delivered/offered)", "zero_demand_rule": "masked"}),
    ("worst_node_delivery_fraction", (0.0, 1.0), ("node_service",), (), {"formula": "min node delivered/offered; exclude zero-demand nodes", "zero_demand_rule": "masked"}),
    ("coverage_fraction", (0.0, 1.0), ("coverage",), ("coverage",), {"measurement": "decision_endpoint_connected_core"}),
    ("unsafe_proximity_fraction", (0.0, 1.0), ("safety",), ("unsafe_separation_m",), {"denominator": "scored_ticks"}),
    ("span_travel_fraction", (0.0, None), ("nodes",), ("node_types",), {"reference_span_m": dict(MOVEMENT_SPAN_M), "hard_limit": False, "partial_warmup_rule": "masked"}),
    ("peer_cohesion", (-1.0, 1.0), ("nodes",), ("node_types",), {"reference_span_m": dict(MOVEMENT_SPAN_M), "floor_m": COHESION_FLOOR_M, "peer": "nearest peer at reset"}),
    *((f"{kind}_travel_fraction", (0.0, 1.0), ("nodes",), ("node_types",), {"partial_warmup_rule": "masked"}) for kind in MOVEMENT_SPAN_M),
):
    COMPONENTS[_name] = RewardComponent(
        _name, _context_fraction(_name), _range, _facts, parameters=_parameters,
        contract_fields=_fields, context_fields=(_name,), context_builder=_movement_context,
        formula=_parameters.get("formula", _name), zero_demand_rule=_parameters.get("zero_demand_rule", "not_applicable"))
COMPONENTS["adaptive_movement_cost"] = RewardComponent(
    "adaptive_movement_cost", _adaptive_movement_cost, (0.0, 0.1), ("nodes", "node_service", "coverage"),
    parameters={"reset_health": 0.0, "lag_decisions": 1, "partial_warmup_rule": "masked"},
    context_fields=("travel_fraction", "fair_node_service", "coverage_fraction"),
    context_builder=_movement_context, contract_fields=("coverage",),
    formula="(0.02 + 0.08 * previous_network_health) * travel_fraction")


def get_component(name: str) -> RewardComponent:
    """Look up a registered reward component by name."""
    component = COMPONENTS.get(name)
    if component is None:
        raise ValueError(
            f"Unknown reward_components entry {name!r}; "
            f"valid choices: {sorted(COMPONENTS)}"
        )
    return component


@dataclass(frozen=True)
class RewardBreakdown:
    """Per-component values, validity, and the weighted total returned to the policy."""

    total: float
    components: dict
    valid: dict
    weights: dict
    legacy: float


class RewardComposer:
    """Weighted sum of registered components over one decision window."""

    def __init__(self, components: Sequence[str], weights: Sequence[float], parameters=None):
        names = list(components)
        values = [float(w) for w in weights]
        if len(names) != len(values):
            raise ValueError(
                f"reward_weights has {len(values)} entries but reward_components has "
                f"{len(names)}"
            )
        if len(set(names)) != len(names):
            raise ValueError(f"reward_components has duplicate entries: {names}")
        bad = next((w for w in values if not math.isfinite(w)), None)
        if bad is not None:
            raise ValueError(f"reward_weights must all be finite, got {bad!r}")
        self.components = [get_component(name) for name in names]
        self.weights = values
        overrides = {} if parameters is None else parameters
        if not isinstance(overrides, dict):
            raise ValueError("reward_parameters must be an object keyed by selected component")
        unknown = set(overrides) - set(names)
        if unknown:
            raise ValueError(f"parameters for unselected reward components: {sorted(unknown)}")
        self.parameters = {c.name: c.resolve(overrides.get(c.name, {})) for c in self.components}
        self.context_fields = {key for c in self.components for key in c.context_fields}
        self.reset()

    def reset(self):
        self.previous_health = 0.0

    def context(self, facts, contract, inputs=None):
        context = {key: facts[key] for key in self.context_fields if key in facts}
        for component in self.components:
            if set(component.context_fields) - set(context) and component.context_builder is not None:
                context.update(component.context_builder(facts, contract, inputs))
        if inputs is not None and "previous_network_health" in inputs:
            context["previous_network_health"] = inputs["previous_network_health"]
        return context

    def compose(self, window: dict, msg_reward: float, contract: dict, context=None) -> RewardBreakdown:
        values, valid, weights = {}, {}, {}
        adaptive = bool(window["scored_ticks"]) and any(c.name == "adaptive_movement_cost" for c in self.components)
        if adaptive:
            if context is None or "coverage_fraction" not in context or "fair_node_service" not in context:
                raise ValueError("adaptive_movement_cost requires coverage and node_service facts")
            context.setdefault("previous_network_health", self.previous_health)
        total = 0.0
        for component, weight in zip(self.components, self.weights):
            value, ok = component.value(window, msg_reward, contract, context, self.parameters[component.name])
            values[component.name] = float(value)
            valid[component.name] = int(bool(ok))
            weights[component.name] = float(weight)
            if ok:
                total += weight * float(value)
        if not math.isfinite(total):
            raise ValueError(f"composed reward is not finite: {total!r} from {values}")
        if adaptive:
            delivery, ok = _delivery_ratio(window, msg_reward, contract, {}, context)
            fairness = context["fair_node_service"]
            self.previous_health = min(max(0.0, min(1.0, delivery)), fairness, context["coverage_fraction"]) if ok and fairness is not None else 0.0
        return RewardBreakdown(float(total), values, valid, weights, float(msg_reward))


def reward_schema(components: Sequence[str], weights: Sequence[float], *, contract: dict, parameters=None) -> dict:
    """Reward identity includes scoring rules and each component's dependencies."""
    composer = RewardComposer(components, weights, parameters)
    scoring = {"warmup_s": float(contract["warmup_s"]),
               "reward_warmup": contract["reward_warmup"],
               "window": "sums_over_scored_ticks"}
    if not list(components):
        schema = {
            "authority": "cpp",
            "reward_type": contract["reward_type"],
            "reward_window": contract["reward_window"],
            **scoring,
        }
        schema["sha256"] = canonical_sha256(schema)
        return schema
    names = list(components)
    schema = {
        "authority": "python",
        "components": names,
        "weights": [float(w) for w in weights],
        "zero_scored_rule": "masked",
        **scoring,
        "component_details": {name: get_component(name).schema(contract, composer.parameters[name]) for name in names},
        "ranges": {name: list(get_component(name).range) for name in names},
    }
    schema["sha256"] = canonical_sha256(schema)
    return schema
