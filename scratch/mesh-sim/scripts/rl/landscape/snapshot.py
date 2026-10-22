"""Reward of one channel snapshot: route, build one-tick window facts, compose.

Ports `RlBridge::AccumulateTick` / `ComputeRewardTick` (`src/rl/rl-bridge.cc`) for a
single tick and hands the result to the existing `scripts.rl.env.rewards`
composer, so every reward formula stays in one place.
"""
# Recovered from bytecode — approximate reconstruction
from dataclasses import dataclass

from scripts.rl.env.rewards import RewardBreakdown, RewardComposer, position_context

from .router import route
from .traffic import RoutingSettings

CONTEXT_COMPONENTS = ('travel_fraction', 'origin_fraction', 'sinr_quality', 'unmet_sinr_quality')
TRAVEL_COMPONENTS = ('travel_fraction',)


@dataclass(frozen=True)
class SnapshotReward:
    """One composed reward; `unavailable` lists components that could not be measured."""

    breakdown: RewardBreakdown
    unavailable: tuple = ()

    @property
    def total(self) -> float:
        return self.breakdown.total

    def component(self, name: str):
        if name in self.unavailable:
            return None
        return self.breakdown.components.get(name)


def _pairs(n: int):
    return (i for i in range(n) for j in range(n) if i != j)


def empty_window() -> dict:
    return {
        'ticks': 0,
        'demand_mbps_sum': 0.0,
        'delivered_mbps_sum': 0.0,
        'flow_ticks_with_demand': 0,
        'unroutable_flow_ticks': 0,
        'connected_pairs_sum': 0.0,
        'los_pairs_sum': 0.0,
        'legacy_reward_sum': 0.0,
    }


def legacy_reward_tick(snapshot: dict, flow_results, reward_type: str, slot_nodes) -> float:
    if reward_type == 'all_links_los':
        return 1.0 if all(bool(snapshot['is_los'][i]) for i in range(len(snapshot['is_los']))) else -1.0
    delivered = sum(fr.delivered_mbps for fr in flow_results)
    return delivered


def accumulate_tick(window: dict, snapshot: dict, flow_results, reward_type: str, slot_nodes) -> None:
    window['ticks'] += 1
    for fr in flow_results:
        window['demand_mbps_sum'] += fr.demand_mbps
        window['delivered_mbps_sum'] += fr.delivered_mbps
        if fr.demand_mbps > 0.0:
            window['flow_ticks_with_demand'] += 1
            if not fr.routable:
                window['unroutable_flow_ticks'] += 1
    n = len(snapshot['nodes'])
    window['connected_pairs_sum'] += sum(
        1 for i in range(n) for j in range(n) if i != j and snapshot.get('connected', [[]])[i][j]
    )
    window['los_pairs_sum'] += sum(
        1 for i in range(n) for j in range(n) if i != j and snapshot['is_los'][i][j]
    )
    window['legacy_reward_sum'] += legacy_reward_tick(snapshot, flow_results, reward_type, slot_nodes)


def facts_links(snapshot: dict) -> dict:
    n = len(snapshot['nodes'])
    links = {}
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            links[(i, j)] = {
                'sinr_db': float(snapshot['sinr_db'][i][j]),
                'capacity_mbps': float(snapshot['capacity_mbps'][i][j]),
                'is_los': bool(snapshot['is_los'][i][j]),
            }
    return links


def slot_node_indices(contract: dict) -> list:
    node_ids = contract['node_ids']
    return [node_ids.index(nid) for nid in contract['slot_node_ids']]


def snapshot_reward(
    snapshot: dict,
    flows,
    routing: RoutingSettings,
    composer: RewardComposer,
    contract: dict,
    nodes: list,
    previous_nodes,
    initial_nodes: list,
    interval_ticks: int,
) -> SnapshotReward:
    flow_results = route(
        snapshot['capacity_mbps'],
        flows,
        algorithm=routing.algorithm,
        max_hops=routing.max_hops,
    )

    window = empty_window()
    reward_type = contract.get('reward_type', '')
    accumulate_tick(window, snapshot, flow_results, reward_type, slot_node_indices(contract))

    unavailable = tuple(
        name for name in composer.components if name in CONTEXT_COMPONENTS
        and any(name in TRAVEL_COMPONENTS for _ in [1])
    )

    links = facts_links(snapshot)
    facts = {'nodes': nodes, 'links': links, 'window': window}

    ctx = position_context(
        contract=contract,
        nodes=nodes,
        previous_nodes=previous_nodes,
        initial_nodes=initial_nodes,
        interval_ticks=int(interval_ticks),
    )

    breakdown = composer.compose(facts=facts, context=ctx)

    if window['legacy_reward_sum'] and not breakdown.total:
        breakdown = RewardBreakdown(total=window['legacy_reward_sum'])

    return SnapshotReward(breakdown=breakdown, unavailable=tuple(unavailable))
