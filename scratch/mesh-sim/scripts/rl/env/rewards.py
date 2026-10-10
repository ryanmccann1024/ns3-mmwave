"""Composable reward components computed from the facts window sums."""

import math
from dataclasses import dataclass, field
from typing import Callable, Sequence

from .observations import schema_sha256

DEMAND_EPS = 1e-9


def _delivery_ratio(window: dict, msg_reward: float, contract: dict) -> tuple[float, bool]:
    demand = float(window["demand_mbps_sum"])
    if demand <= DEMAND_EPS:
        return 0.0, False
    return float(window["delivered_mbps_sum"]) / demand, True


def _connectivity(window: dict, msg_reward: float, contract: dict) -> tuple[float, bool]:
    pairs = int(window["scored_ticks"]) * int(contract["num_links"])
    if pairs <= 0:
        return 0.0, True
    return float(window["connected_pairs_sum"]) / pairs, True


def _throughput_mbps(window: dict, msg_reward: float, contract: dict) -> tuple[float, bool]:
    return float(window["delivered_mbps_sum"]) / int(window["scored_ticks"]), True


def _legacy(window: dict, msg_reward: float, contract: dict) -> tuple[float, bool]:
    return float(window["legacy_reward_sum"]) / int(window["scored_ticks"]), True


@dataclass(frozen=True)
class RewardComponent:
    """One named scalar term with its validity rule and declared range."""

    name: str
    _value: Callable[[dict, float, dict], tuple[float, bool]]
    range: tuple[float | None, float | None]
    required_facts: tuple[str, ...]
    parameters: dict = field(default_factory=dict)
    contract_fields: tuple[str, ...] = ()

    def value(self, window: dict, msg_reward: float, contract: dict) -> tuple[float, bool]:
        if not window["scored_ticks"]:
            return 0.0, False
        return self._value(window, msg_reward, contract)

    def schema(self, contract: dict) -> dict:
        return {"range": list(self.range), "required_facts": list(self.required_facts),
                "parameters": dict(self.parameters),
                "contract": {key: contract[key] for key in self.contract_fields}}


COMPONENTS = {
    "delivery_ratio": RewardComponent(
        "delivery_ratio", _delivery_ratio, (0.0, 1.0),
        ("demand_mbps_sum", "delivered_mbps_sum"),
        {"demand_epsilon_mbps_sum": DEMAND_EPS, "zero_demand_rule": "masked"}),
    "connectivity": RewardComponent(
        "connectivity", _connectivity, (0.0, 1.0), ("connected_pairs_sum",),
        contract_fields=("num_links",)),
    "throughput_mbps": RewardComponent(
        "throughput_mbps", _throughput_mbps, (0.0, None), ("delivered_mbps_sum",)),
    "legacy": RewardComponent(
        "legacy", _legacy, (None, None), ("legacy_reward_sum",),
        contract_fields=("reward_type", "reward_window")),
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

    def compose(self, window: dict, msg_reward: float, contract: dict) -> RewardBreakdown:
        values, valid, weights = {}, {}, {}
        total = 0.0
        for component, weight in zip(self.components, self.weights):
            value, ok = component.value(window, msg_reward, contract)
            values[component.name] = float(value)
            valid[component.name] = int(bool(ok))
            weights[component.name] = float(weight)
            if ok:
                total += weight * float(value)
        if not math.isfinite(total):
            raise ValueError(f"composed reward is not finite: {total!r} from {values}")
        return RewardBreakdown(float(total), values, valid, weights, float(msg_reward))


def reward_schema(components: Sequence[str], weights: Sequence[float], *, contract: dict) -> dict:
    """Reward identity includes scoring rules and each component's dependencies."""
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
        schema["sha256"] = schema_sha256(schema)
        return schema
    names = list(components)
    schema = {
        "authority": "python",
        "components": names,
        "weights": [float(w) for w in weights],
        "zero_demand_rule": "masked",
        **scoring,
        "component_details": {name: get_component(name).schema(contract) for name in names},
        "ranges": {name: list(get_component(name).range) for name in names},
    }
    schema["sha256"] = schema_sha256(schema)
    return schema
