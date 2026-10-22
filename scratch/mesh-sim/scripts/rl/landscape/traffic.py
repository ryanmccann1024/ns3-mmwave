"""Flow lists for the router port: `[traffic]` / `[routing]` settings, topologies, flows.csv.

Mirrors the deterministic parts of `src/traffic/traffic-matrix.cc` (`all_pairs` and
`gateway` topologies under the `constant` model). Random parts (`random_pairs`,
`on_off` phases, `poisson` arrivals) come from a run's `seed-N/flows.csv` instead.
"""
# Recovered from bytecode — approximate reconstruction
import csv
import math
from dataclasses import dataclass
from pathlib import Path

from scripts.sim_support import parse_ini

from .router import ALGORITHMS, Flow

TOPOLOGIES = ('all_pairs', 'random_pairs', 'gateway')
MODELS = ('constant', 'poisson', 'on_off')
_TIME_SCALE = 1_000_000


class TrafficError(ValueError):
    """The flows for a tick cannot be reproduced from the given inputs."""


@dataclass
class TrafficSettings:
    """`[traffic]` keys the router port needs, with the C++ loader defaults."""

    model: str = 'constant'
    demand_mbps: float = 10.0
    flow_topology: str = 'all_pairs'
    gateway_node_id: str = ''
    random_pair_count: int = 3
    holding_time_s: float = 0.0


@dataclass
class RoutingSettings:
    """`[routing]` keys with the C++ loader defaults."""

    algorithm: str = 'shortest_path'
    max_hops: int = 5


def _get(ini, section, key, default):
    return ini.get(section, {}).get(key, default)


def read_settings(run_ini) -> tuple[TrafficSettings, RoutingSettings]:
    ini = parse_ini(run_ini)
    try:
        t = TrafficSettings(
            model=_get(ini, 'traffic', 'model', 'constant'),
            demand_mbps=float(_get(ini, 'traffic', 'demand_mbps', '10.0')),
            flow_topology=_get(ini, 'traffic', 'flow_topology', 'all_pairs'),
            gateway_node_id=_get(ini, 'traffic', 'gateway_node_id', ''),
            random_pair_count=int(_get(ini, 'traffic', 'random_pair_count', '3')),
            holding_time_s=float(_get(ini, 'traffic', 'holding_time_s', '0.0')),
        )
        r = RoutingSettings(
            algorithm=_get(ini, 'routing', 'algorithm', 'shortest_path'),
            max_hops=int(_get(ini, 'routing', 'max_hops', '5')),
        )
    except ValueError as e:
        raise TrafficError(f': bad [traffic]/[routing] value: {e}') from e
    if t.model not in MODELS:
        raise TrafficError(f'unknown [traffic] model {t.model}')
    if t.flow_topology not in TOPOLOGIES:
        raise TrafficError(f'unknown [traffic] flow_topology {t.flow_topology}')
    if r.algorithm not in ALGORITHMS:
        raise TrafficError(f'unknown [routing] algorithm {r.algorithm}')
    return t, r


def gateway_index(gateway_node_id: str, node_ids: list) -> int:
    if gateway_node_id.isdigit():
        idx = int(gateway_node_id)
        if idx < len(node_ids):
            return idx
    if gateway_node_id in node_ids:
        return list(node_ids).index(gateway_node_id)
    raise TrafficError(f'gateway_node_id {gateway_node_id!r} not found in node list')


def topology_pairs(settings: TrafficSettings, node_ids: list) -> list:
    n = len(node_ids)
    if settings.flow_topology == 'all_pairs':
        return [(i, j) for i in range(n) for j in range(n) if i != j]
    if settings.flow_topology == 'gateway':
        gw = gateway_index(settings.gateway_node_id, node_ids)
        return [(i, gw) for i in range(n) if i != gw] + [(gw, i) for i in range(n) if i != gw]
    raise TrafficError(
        "random_pairs flows are drawn from the simulator's RNG; "
        "they can only be read from seed-N/flows.csv"
    )


def _time_key(time_s) -> int:
    return int(round(float(time_s) * _TIME_SCALE))


def read_flow_snapshots(path, times_s, demand_mbps: float) -> dict:
    snapshots = {}
    time_keys = {_time_key(t) for t in times_s}
    with open(path, newline='') as f:
        reader = csv.reader(f)
        header = next(r for r in reader if not r[0].startswith('#'))
        expected = ('time_s', 'src', 'dst', 'demand_mbps')
        if any(c not in header for c in expected):
            raise TrafficError(f': expected columns {", ".join(expected)}')
        ti = header.index('time_s')
        di = header.index('demand_mbps')
        si = header.index('src')
        di2 = header.index('dst')

        current_key = None
        group = []

        def close_group():
            if current_key is not None and current_key in time_keys:
                snapshots[current_key] = list(group)

        for row in reader:
            if not row:
                continue
            key = _time_key(row[ti])
            if key != current_key:
                close_group()
                current_key = key
                group = []
            group.append(Flow(
                src=int(row[si]),
                dst=int(di2),
                demand_mbps=float(row[di]),
                active=True,
            ))
        close_group()
    return snapshots


@dataclass
class FlowSource:
    """Flows per decision time plus how they were obtained."""

    flows: dict
    method: str
    warnings: tuple = ()


def resolve_flows(settings: TrafficSettings, node_ids: list, times_s, flows_csv) -> FlowSource:
    if settings.model == 'constant' and settings.flow_topology in ('all_pairs', 'gateway'):
        pairs = topology_pairs(settings, node_ids)
        flows_by_time = {}
        for t in times_s:
            flows_by_time[float(t)] = [
                Flow(src=src, dst=dst, demand_mbps=float(settings.demand_mbps))
                for src, dst in pairs
            ]
        return FlowSource(flows=flows_by_time, method='config')

    if flows_csv and Path(flows_csv).exists():
        snapshots = read_flow_snapshots(flows_csv, times_s, settings.demand_mbps)
        warnings = []
        result = {}
        for t in times_s:
            key = _time_key(t)
            if key in snapshots:
                result[float(t)] = snapshots[key]
            else:
                # find last tick at or before t
                candidates = [k for k in snapshots if k <= key]
                if not math.isclose(key, max(candidates, default=key), abs_tol=1e-6):
                    warnings.append(
                        f'flows.csv has no row at t = {t:.6f} s; '
                        f'using the last written tick t = {max(candidates) / _TIME_SCALE:.6f} s'
                    )
                best = max(candidates) if candidates else key
                result[float(t)] = snapshots.get(best, [])
        return FlowSource(flows=result, method='flows_csv', warnings=tuple(warnings))

    if settings.flow_topology == 'random_pairs':
        raise TrafficError(
            "random_pairs traffic needs the run's seed-N/flows.csv, which is missing"
        )

    pairs = topology_pairs(settings, node_ids)
    warnings = (
        f'{settings.flow_topology} traffic without seed-N/flows.csv: using the '
        f'{len(pairs)} flows all ON at {settings.demand_mbps} Mbps '
        f'(approximation; real ON/OFF phases and arrivals are not reproduced)',
    )
    flows_by_time = {
        float(t): [
            Flow(src=src, dst=dst, demand_mbps=float(settings.demand_mbps))
            for src, dst in pairs
        ]
        for t in times_s
    }
    return FlowSource(flows=flows_by_time, method='config_fallback', warnings=warnings)
