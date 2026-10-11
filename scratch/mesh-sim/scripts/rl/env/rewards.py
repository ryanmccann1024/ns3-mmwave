"""Composable reward components computed from the facts window sums."""

import math
from dataclasses import dataclass
from typing import Callable, Sequence

from .observations import SINR_CLIP_DB, SINR_INVALID_DB, schema_sha256

DEMAND_EPS = 1e-9
SUCCESS_DELIVERY = 0.95
SUCCESS_ROUTABLE = 0.95
# Explicit travel reference spans from the synthetic placement fixture. These are
# soft reward normalizers, not the planner's hard displacement constraints.
MOVEMENT_SPAN_M = {"drone": 500.0, "pedestrian": 300.0, "vehicle": 300.0}
COHESION_FLOOR_M = 20.0


def _distance_3d(a: list, b: list) -> float:
    return math.sqrt(sum((float(a[axis]) - float(b[axis])) ** 2 for axis in range(3)))


def _delivery_ratio(window: dict, msg_reward: float, contract: dict) -> tuple[float, bool]:
    demand = float(window["demand_mbps_sum"])
    if demand <= DEMAND_EPS:
        return 0.0, False
    return float(window["delivered_mbps_sum"]) / demand, True


def _worst_node_delivery_fraction(window, msg_reward, contract, context):
    if context is None or "worst_node_delivery_fraction" not in context:
        raise ValueError("worst_node_delivery_fraction requires a rebuilt simulator emitting node_service")
    value = context["worst_node_delivery_fraction"]
    return (float(value), True) if value is not None else (0.0, False)



def _fair_node_service(window, msg_reward, contract, context):
    if "fair_node_service" not in context:
        raise ValueError("fair_node_service requires simulator node_service")
    value = context["fair_node_service"]
    return (float(value), True) if value is not None else (0.0, False)


def _adaptive_movement_cost(window, msg_reward, contract, context):
    return (0.02 + 0.08*context["previous_network_health"])*context["travel_fraction"], True


def _delivery_binary(window: dict, msg_reward: float, contract: dict) -> tuple[float, bool]:
    """Reward any measured delivery and penalize a complete service failure."""
    demand = float(window["demand_mbps_sum"])
    if demand <= DEMAND_EPS:
        return 0.0, False
    delivered = float(window["delivered_mbps_sum"])
    return (1.0 if delivered > DEMAND_EPS else -1.0), True


def _signed_delivery_ratio(window: dict, msg_reward: float,
                           contract: dict) -> tuple[float, bool]:
    """Map delivered/offered demand from [0, 1] to a symmetric [-1, 1]."""
    ratio, valid = _delivery_ratio(window, msg_reward, contract)
    if not valid:
        return 0.0, False
    return 2.0 * max(0.0, min(1.0, ratio)) - 1.0, True


def _connectivity(window: dict, msg_reward: float, contract: dict) -> tuple[float, bool]:
    pairs = int(window["ticks"]) * int(contract["num_links"])
    if pairs <= 0:
        return 0.0, True
    return float(window["connected_pairs_sum"]) / pairs, True


def _throughput_mbps(window: dict, msg_reward: float, contract: dict) -> tuple[float, bool]:
    return float(window["delivered_mbps_sum"]) / int(window["ticks"]), True


def _throughput_log_mbps(window: dict, msg_reward: float,
                         contract: dict) -> tuple[float, bool]:
    return math.log1p(max(0.0, float(window["delivered_mbps_sum"]) /
                          int(window["ticks"]))), True


def _legacy(window: dict, msg_reward: float, contract: dict) -> tuple[float, bool]:
    return float(window["legacy_reward_sum"]) / int(window["ticks"]), True


def _service_success(window: dict, msg_reward: float, contract: dict) -> tuple[float, bool]:
    demand = float(window["demand_mbps_sum"])
    flows = int(window["flow_ticks_with_demand"])
    if demand <= DEMAND_EPS or flows == 0:
        return -1.0, True
    delivered = float(window["delivered_mbps_sum"]) / demand
    routable = 1.0 - int(window["unroutable_flow_ticks"]) / flows
    return (1.0 if delivered >= SUCCESS_DELIVERY and routable >= SUCCESS_ROUTABLE
            else -1.0), True


def _service_failure(window: dict, msg_reward: float, contract: dict) -> tuple[float, bool]:
    success, _ = _service_success(window, msg_reward, contract)
    return (1.0 if success < 0 else 0.0), True


def position_context(facts: dict, previous_nodes: list, initial_nodes: list,
                     contract: dict) -> dict:
    """Measured position costs for the action just completed, from existing facts."""
    slots = [node_id for node_id in contract["slot_node_ids"] if node_id is not None]
    node_ids = contract["node_ids"]
    interval = int(facts["window"]["ticks"]) * float(contract["tick_s"])
    bounds = contract["bounds"]
    diagonal = math.hypot(float(bounds["x_max"]) - float(bounds["x_min"]),
                          float(bounds["y_max"]) - float(bounds["y_min"]))
    if interval <= 0 or diagonal <= 0:
        raise ValueError("movement reward needs a positive completed window and xy bounds")
    travel, displacement = [], []
    travel_by_type = {kind: 0.0 for kind in MOVEMENT_SPAN_M}
    span_travel = 0.0
    node_types = contract.get("node_types")
    for slot, node_id in enumerate(slots):
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
    qualities = [max(0.0, min(1.0, (float(link[0]) - SINR_CLIP_DB[0]) /
                                  (SINR_CLIP_DB[1] - SINR_CLIP_DB[0])))
                 if float(link[0]) > SINR_INVALID_DB else 0.0
                 for link in facts["links"]]
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
            int(safety["unsafe_ticks"]) / int(facts["window"]["ticks"]))
    if "coverage" in facts:
        context["coverage_fraction"] = float(facts["coverage"]["fraction"])
    service = facts.get("node_service")
    if service is not None:
        ratios = [min(1.0, max(0.0, float(delivered) / float(demand)))
                  for demand, delivered in service if float(demand) > DEMAND_EPS]
        context["worst_node_delivery_fraction"] = min(ratios) if ratios else None
        context["fair_node_service"] = sum(math.sqrt(r) for r in ratios)/len(ratios) if ratios else None
    return context


def _travel_fraction(window: dict, msg_reward: float, contract: dict,
                     context: dict) -> tuple[float, bool]:
    return float(context["travel_fraction"]), True


def _measured_context(name: str) -> Callable[..., tuple[float, bool]]:
    """Read a simulator-backed context value, requiring a current binary."""

    def value(window: dict, msg_reward: float, contract: dict,
              context: dict) -> tuple[float, bool]:
        if name not in context:
            raise ValueError(
                f"{name} requires a rebuilt simulator emitting node_types/safety")
        return float(context[name]), True

    return value


def _origin_fraction(window: dict, msg_reward: float, contract: dict,
                     context: dict) -> tuple[float, bool]:
    return float(context["origin_fraction"]), True


def _sinr_quality(window: dict, msg_reward: float, contract: dict,
                  context: dict) -> tuple[float, bool]:
    return float(context["sinr_quality"]), True


def _unmet_sinr_quality(window: dict, msg_reward: float, contract: dict,
                        context: dict) -> tuple[float, bool]:
    """Shaping disappears once measured service meets the success threshold."""
    demand = float(window["demand_mbps_sum"])
    ratio = (float(window["delivered_mbps_sum"]) / demand
             if demand > DEMAND_EPS else 0.0)
    unmet = max(0.0, min(1.0, (SUCCESS_DELIVERY - ratio) / SUCCESS_DELIVERY))
    return float(context["sinr_quality"]) * unmet, True


@dataclass(frozen=True)
class RewardComponent:
    """One named scalar term with its validity rule and declared range."""

    name: str
    _value: Callable[..., tuple[float, bool]]
    range: tuple[float, float | None]

    def value(self, window: dict, msg_reward: float, contract: dict,
              context: dict | None = None) -> tuple[float, bool]:
        if self.name in ("travel_fraction", "origin_fraction", "sinr_quality",
                         "unmet_sinr_quality", "drone_travel_fraction",
                         "pedestrian_travel_fraction", "vehicle_travel_fraction",
                         "unsafe_proximity_fraction", "span_travel_fraction",
                         "peer_cohesion", "coverage_fraction", "worst_node_delivery_fraction",
                         "fair_node_service", "adaptive_movement_cost"):
            if context is None:
                raise ValueError(f"{self.name} requires measured position context")
            return self._value(window, msg_reward, contract, context)
        return self._value(window, msg_reward, contract)


COMPONENTS = {
    "fair_node_service": RewardComponent("fair_node_service", _fair_node_service, (0.0, 1.0)),
    "adaptive_movement_cost": RewardComponent("adaptive_movement_cost", _adaptive_movement_cost, (0.0, 0.1)),
    "worst_node_delivery_fraction": RewardComponent("worst_node_delivery_fraction",
        _worst_node_delivery_fraction, (0.0, 1.0)),
    "coverage_fraction": RewardComponent("coverage_fraction",
        _measured_context("coverage_fraction"), (0.0, 1.0)),
    "delivery_ratio": RewardComponent("delivery_ratio", _delivery_ratio, (0.0, 1.0)),
    "delivery_binary": RewardComponent("delivery_binary", _delivery_binary,
                                        (-1.0, 1.0)),
    "signed_delivery_ratio": RewardComponent("signed_delivery_ratio",
                                               _signed_delivery_ratio,
                                               (-1.0, 1.0)),
    "connectivity": RewardComponent("connectivity", _connectivity, (0.0, 1.0)),
    "throughput_mbps": RewardComponent("throughput_mbps", _throughput_mbps, (0.0, None)),
    "throughput_log_mbps": RewardComponent(
        "throughput_log_mbps", _throughput_log_mbps, (0.0, None)),
    "legacy": RewardComponent("legacy", _legacy, (None, None)),
    "service_success": RewardComponent("service_success", _service_success, (-1.0, 1.0)),
    "service_failure": RewardComponent("service_failure", _service_failure, (0.0, 1.0)),
    "travel_fraction": RewardComponent("travel_fraction", _travel_fraction, (0.0, 1.0)),
    "drone_travel_fraction": RewardComponent(
        "drone_travel_fraction", _measured_context("drone_travel_fraction"), (0.0, 1.0)),
    "pedestrian_travel_fraction": RewardComponent(
        "pedestrian_travel_fraction", _measured_context("pedestrian_travel_fraction"),
        (0.0, 1.0)),
    "vehicle_travel_fraction": RewardComponent(
        "vehicle_travel_fraction", _measured_context("vehicle_travel_fraction"),
        (0.0, 1.0)),
    "unsafe_proximity_fraction": RewardComponent(
        "unsafe_proximity_fraction", _measured_context("unsafe_proximity_fraction"),
        (0.0, 1.0)),
    "span_travel_fraction": RewardComponent(
        "span_travel_fraction", _measured_context("span_travel_fraction"),
        (0.0, None)),
    "peer_cohesion": RewardComponent(
        "peer_cohesion", _measured_context("peer_cohesion"), (-1.0, 1.0)),
    "origin_fraction": RewardComponent("origin_fraction", _origin_fraction, (0.0, 1.0)),
    "sinr_quality": RewardComponent("sinr_quality", _sinr_quality, (0.0, 1.0)),
    "unmet_sinr_quality": RewardComponent("unmet_sinr_quality",
                                            _unmet_sinr_quality, (0.0, 1.0)),
}


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

    def __init__(self, components: Sequence[str], weights: Sequence[float]):
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
        self.reset()

    def reset(self):
        self.previous_health = 0.0

    def compose(self, window: dict, msg_reward: float, contract: dict,
                context: dict | None = None) -> RewardBreakdown:
        values, valid, weights = {}, {}, {}
        adaptive = any(c.name == "adaptive_movement_cost" for c in self.components)
        if adaptive:
            if context is None or "coverage_fraction" not in context or "fair_node_service" not in context:
                raise ValueError("adaptive_movement_cost requires coverage and node_service facts")
            context["previous_network_health"] = self.previous_health
        total = 0.0
        for component, weight in zip(self.components, self.weights):
            value, ok = component.value(window, msg_reward, contract, context)
            values[component.name] = float(value)
            valid[component.name] = int(bool(ok))
            weights[component.name] = float(weight)
            if ok:
                total += weight * float(value)
        if not math.isfinite(total):
            raise ValueError(f"composed reward is not finite: {total!r} from {values}")
        if adaptive:
            delivery, ok = _delivery_ratio(window, msg_reward, contract)
            fairness = context["fair_node_service"]
            self.previous_health = min(max(0.0, min(1.0, delivery)), fairness, context["coverage_fraction"]) if ok and fairness is not None else 0.0
        return RewardBreakdown(float(total), values, valid, weights, float(msg_reward))


def reward_schema(components: Sequence[str], weights: Sequence[float], *,
                  reward_type: str, reward_window: str,
                  unsafe_separation_m: float = 1.0, coverage: dict | None = None) -> dict:
    """Reward identity; C++ authority (reward_type/reward_window from init) when empty."""
    if not list(components):
        schema = {
            "authority": "cpp",
            "reward_type": reward_type,
            "reward_window": reward_window,
        }
        schema["sha256"] = schema_sha256(schema)
        return schema
    names = list(components)
    schema = {
        "authority": "python",
        "components": names,
        "weights": [float(w) for w in weights],
        "zero_demand_rule": "masked",
        "window": "sums_over_window_ticks",
        "ranges": {name: list(get_component(name).range) for name in names},
    }
    if "fair_node_service" in names or "adaptive_movement_cost" in names:
        schema["fair_node_service_rule"] = "mean sqrt(clip(node incident delivered/offered,0,1)); exclude zero-demand nodes; masked when no demand"
    if "adaptive_movement_cost" in names:
        schema["adaptive_movement_rule"] = {
            "formula": "(0.02 + 0.08 * H_previous) * mean per-slot actual xy movement / (slot_speed_mps * decision duration)",
            "health": "min(clipped delivery ratio, fair_node_service, coverage_fraction)",
            "reset_health": 0.0, "range": [0.0, 0.1], "lag_decisions": 1}
    if "worst_node_delivery_fraction" in names:
        schema["worst_node_delivery_rule"] = {
            "formula": "min of node incident delivered/offered sums over decision ticks; routed flows count at both endpoints",
            "zero_demand_nodes": "excluded; entire term masked when no node has demand",
            "range": [0.0, 1.0]}
    if "service_success" in names or "service_failure" in names:
        schema["success_rule"] = {"delivery_ratio_at_least": SUCCESS_DELIVERY,
                                  "routable_flow_fraction_at_least": SUCCESS_ROUTABLE,
                                  "zero_demand": "failure"}
    if "delivery_binary" in names:
        schema["delivery_binary_rule"] = (
            "+1 when offered demand is positive and any demand is delivered; "
            "-1 when offered demand is positive and none is delivered; "
            "zero demand is masked")
    if "signed_delivery_ratio" in names:
        schema["signed_delivery_ratio_rule"] = (
            "2 * clip(delivered_mbps_sum / demand_mbps_sum, 0, 1) - 1; "
            "zero demand is masked")
    if "travel_fraction" in names or "origin_fraction" in names:
        schema["movement_rule"] = {
            "travel_fraction": "mean per controlled slot of actual xy travel / (slot_speed_mps * window_ticks * tick_s), clipped [0,1]",
            "origin_fraction": "mean per controlled slot of xy distance from reset / bounds xy diagonal, clipped [0,1]",
        }
    if any(f"{kind}_travel_fraction" in names
           for kind in ("drone", "pedestrian", "vehicle")):
        schema["type_travel_rule"] = (
            "sum of normalized actual xy travel for controlled slots of matching "
            "node_type, divided by all active controlled slots")
    if "unsafe_proximity_fraction" in names:
        schema["unsafe_proximity_rule"] = (
            "fraction of completed simulator ticks with any mesh-node pair closer "
            f"than {unsafe_separation_m:g} metres in 3D")
    if "coverage_fraction" in names or "adaptive_movement_cost" in names:
        if coverage is None:
            raise ValueError("coverage_fraction requires [rl] coverage_enabled=true and a rebuilt simulator")
        schema["coverage_rule"] = {
            "formula": "covered clipped-cell area / bounds xy area; union over largest connected component; ties use smallest roster index",
            "cadence": "decision endpoint", "grid": dict(coverage)}
    if "span_travel_fraction" in names:
        schema["span_travel_rule"] = {
            "formula": "mean over controlled slots of actual xy distance moved this decision divided by the node type's reference span; cumulative reward charges the full path even if a node returns to its start",
            "reference_span_m": dict(MOVEMENT_SPAN_M),
            "hard_limit": False,
        }
    if "peer_cohesion" in names:
        schema["peer_cohesion_rule"] = {
            "peer": "nearest other mesh node at reset, fixed for the episode",
            "formula": "mean over controlled nodes of clip((max(initial_distance, floor) - max(current_distance, floor)) / node_type_reference_span, -1, 1)",
            "distance": "3d_m",
            "floor_m": COHESION_FLOOR_M,
            "reference_span_m": dict(MOVEMENT_SPAN_M),
        }
    if "throughput_log_mbps" in names:
        schema["throughput_log_rule"] = "ln(1 + delivered_mbps_sum / window.ticks)"
    if "sinr_quality" in names:
        schema["sinr_quality_rule"] = "mean per-link SINR clipped [-20,40] dB then mapped to [0,1]; invalid links score zero"
    if "unmet_sinr_quality" in names:
        schema["unmet_sinr_quality_rule"] = (
            "sinr_quality * clip((0.95 - delivered/demand)/0.95, 0, 1); "
            "zero demand uses delivery ratio zero")
    schema["sha256"] = schema_sha256(schema)
    return schema
