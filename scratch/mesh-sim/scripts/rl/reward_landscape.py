"""Precompute a reward landscape for one RL episode: reward vs. one node's xy position.

For each chosen (decision k, controlled node) the node is placed on a grid over the
`[rl]` bounds while every other node stays where steps.jsonl record k put it. Each
layout is scored by the simulator's `--channel-query` worker (a fresh t = 0 channel
draw), routed with the Python router port and composed with the episode's own reward
schema as a one-tick snapshot. Writes `reward_landscape.json` next to steps.jsonl.

Usage, from scratch/mesh-sim:
    .venv/bin/python -m scripts.rl.reward_landscape --episode-dir <episode-NNNN> \
        --sim-binary <BIN> [--grid 41] [--every 50 | --decisions 0,100] [--workers 4]
"""
# Recovered from bytecode — approximate reconstruction
import argparse
import json
import math
import os
import queue
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from scripts.baselines.planners.channel import ChannelScorer, PlannerError
from scripts.rl.env.rewards import RewardComposer
from scripts.rl.landscape.episode import (
    EpisodeError,
    contract_grid,
    load_episode,
    plan_slice,
    resolve_slots,
    reward_schema_lists,
    select_decisions,
)
from scripts.rl.landscape.snapshot import SnapshotReward, snapshot_reward  # noqa: F401
from scripts.rl.landscape.traffic import (
    TrafficError,
    read_settings,
    resolve_flows,
)

LANDSCAPE_VERSION = 1
OUTPUT_NAME = 'reward_landscape.json'
LOG_NAME = 'reward_landscape.log'
GENERATOR = 'scripts.rl.reward_landscape'
BATCH_LAYOUTS = 32
MAX_FAILED_FRACTION = 0.05


class LandscapeError(RuntimeError):
    """Landscape generation failed; the output file was not written."""


class Progress:
    """Thread-safe progress meter written to a stream."""

    def __init__(self, total: int, label: str, stream=None):
        self._total = max(1, total)
        self._label = label
        self._done = 0
        self._next = 0
        self._lock = threading.Lock()
        self._start = time.monotonic()
        self._stream = stream or sys.stderr

    def add(self, count: int = 1) -> None:
        with self._lock:
            self._done += count
            if self._done >= self._next:
                fraction = self._done / self._total
                elapsed = time.monotonic() - self._start
                self._next = self._done + max(1, math.floor(self._total / 20))
                self._stream.write(
                    f'[{self._label}] {self._done}/{self._total} layouts '
                    f'({fraction * 100:.0f}%), {elapsed:.1f} s\n'
                )
                self._stream.flush()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mean(values):
    nums = [v for v in values if v is not None]
    return sum(nums) / len(nums) if nums else None


def _std(values):
    nums = [v for v in values if v is not None]
    if len(nums) < 2:
        return None
    mean = sum(nums) / len(nums)
    return math.sqrt(sum((v - mean) ** 2 for v in nums) / len(nums))


def _summary(rewards, components):
    """Mean total, mean per component and total std across seeds."""
    totals = [r.total if r is not None else None for r in rewards]
    values = {
        name: _mean([r.component(name) if r is not None else None for r in rewards])
        for name in components
    }
    return _mean(totals), values, _std(totals)


def _recorded(record):
    reward = record.get('reward') or {}
    total = reward.get('total')
    components = reward.get('components')
    if isinstance(components, dict):
        return {'total': total, 'components': {name: value for name, value in components.items()}}
    return {'total': total, 'components': {'legacy': total}}


def _rewards(spec, results_by_seed, index, flows, routing, composer, contract, previous, interval_ticks):
    """SnapshotReward per seed for one layout (`None` where the layout failed)."""
    out = []
    for results in results_by_seed.values():
        result = results[index]
        if result is None:
            out.append(None)
            continue
        snapshot = {
            'nodes': spec.layouts[index],
            'capacity_mbps': result.capacity_mbps,
            'is_los': result.is_los,
            'sinr_db': result.sinr_db,
            'connected': result.connected,
        }
        out.append(snapshot_reward(
            snapshot, flows, routing, composer, contract,
            spec.layouts[index], previous, spec.initial_nodes, interval_ticks,
        ))
    return out


def assemble_slice(spec, results_by_seed, flows, routing, composer, components, contract):
    record = spec.record
    k_ticks = int(contract['decision_interval_ticks'])

    if spec.decision > 0:
        grid_ticks = int(record.get('ticks_in_step') or k_ticks)
    else:
        grid_ticks = k_ticks

    totals = []
    spreads = []
    values = {name: [] for name in components}

    for index in range(spec.grid_count):
        rewards = _rewards(
            spec, results_by_seed, index, flows, routing, composer, contract,
            spec.previous_nodes, grid_ticks,
        )
        total, per, spread = _summary(rewards, components)
        totals.append(total)
        spreads.append(spread)
        for name in components:
            values[name].append(per[name])

    record_nodes = record['facts']['nodes']
    moves = []
    for move in spec.moves:
        entry = dict(move)
        index = spec.move_layouts.get(move['action'])
        if index is None:
            entry.update(total=None, components={name: None for name in components})
        else:
            rewards = _rewards(
                spec, results_by_seed, index, flows, routing, composer, contract,
                record_nodes, k_ticks,
            )
            total, per, _ = _summary(rewards, components)
            entry.update(total=total, components=per)
        moves.append(entry)

    here = record_nodes[spec.node_index]
    out = {
        'decision': spec.decision,
        'time_s': float(record['time_s']),
        'node_id': spec.node_id,
        'slot': spec.slot,
        'position': [float(here[0]), float(here[1]), float(here[2])],
        'values': {'total': totals, **values},
    }

    if len(results_by_seed) > 1:
        out['spread'] = {'total': spreads}

    out['moves'] = moves
    out['recorded'] = _recorded(record)
    return out


def write_landscape(path, payload) -> None:
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    try:
        with open(temp, 'w') as fh:
            json.dump(payload, fh, separators=(',', ':'), allow_nan=False)
            fh.write('\n')
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    os.replace(temp, path)


def score_layouts(layouts, factory, workers: int, progress) -> list:
    results = [None] * len(layouts)
    jobs = queue.Queue()
    for start in range(0, len(layouts), BATCH_LAYOUTS):
        jobs.put(start)
    errors = []
    failed = [0]
    lock = threading.Lock()
    limit = max(10, int(MAX_FAILED_FRACTION * len(layouts)))

    def open_scorer():
        try:
            return factory()
        except (PlannerError, OSError, ValueError) as exc:
            raise LandscapeError(f'cannot start the channel query worker: {exc}') from exc

    def run():
        scorer = None
        try:
            while not errors:
                try:
                    start = jobs.get_nowait()
                except queue.Empty:
                    return
                batch = layouts[start:start + BATCH_LAYOUTS]
                if scorer is None:
                    scorer = open_scorer()
                try:
                    out = scorer.evaluate(batch)
                    results[start:start + len(batch)] = out
                    progress.add(len(batch))
                except PlannerError:
                    scorer.close()
                    scorer = None
                    out = []
                    for layout in batch:
                        single = open_scorer()
                        try:
                            out.extend(single.evaluate([layout]))
                        except PlannerError as exc:
                            out.append(None)
                            with lock:
                                failed[0] += 1
                                if failed[0] > limit:
                                    raise LandscapeError(
                                        f'{failed[0]} layouts failed in the channel query worker '
                                        f'(last: {exc})'
                                    ) from exc
                        finally:
                            single.close()
                    results[start:start + len(batch)] = out
                    progress.add(len(batch))
        except BaseException as exc:
            errors.append(exc)
        finally:
            if scorer is not None:
                scorer.close()

    threads = [threading.Thread(target=run, daemon=True) for _ in range(max(1, workers))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    if errors:
        error = errors[0]
        if isinstance(error, LandscapeError):
            raise error
        raise LandscapeError(f'scoring failed: {type(error).__name__}: {error}') from error

    if failed[0]:
        sys.stderr.write(
            f'warning: {failed[0]} layouts failed in the channel query worker; their cells are null\n'
        )

    return results


def _default_factory(args, episode, seed, log):
    def factory():
        return ChannelScorer(
            args.sim_binary,
            episode.run_ini,
            seed,
            episode.run_id,
            episode.band,
            'evaluation',
            episode.node_ids,
            episode.start_positions,
            seed,
            log=log,
        )
    return factory


def generate(args, scorer_factory=None, log=None):
    episode = load_episode(args.episode_dir)
    contract = episode.contract
    components, weights = reward_schema_lists(episode.header)
    composer = RewardComposer(components, weights)
    traffic, routing = read_settings(episode.run_ini)
    decisions = select_decisions(episode.records, args.decisions, args.every)
    slots = resolve_slots(contract, args.nodes)
    seeds = args.seeds or [episode.seed]
    grid = contract_grid(contract, args.grid)

    times = sorted({float(episode.records[d]['time_s']) for d in decisions})
    flow_source = resolve_flows(traffic, episode.node_ids, times, episode.flows_csv)

    for warning in flow_source.warnings:
        sys.stderr.write(f'warning: {warning}\n')

    specs = [
        plan_slice(episode, d, slot, node_id, grid)
        for d in decisions
        for slot, node_id in slots
    ]

    for spec in specs:
        for warning in dict.fromkeys(spec.warnings):
            sys.stderr.write(f'warning: decision {spec.decision}: {warning}\n')
        if spec.previous_nodes is None and 'travel_fraction' in components:
            sys.stderr.write(
                f'warning: decision {spec.decision - 1} is not saved; '
                f'travel_fraction and the total are null for decision {spec.decision}\n'
            )

    layouts = [layout for spec in specs for layout in spec.layouts]

    sys.stderr.write(
        f'{len(specs)} slices ({len(decisions)} decisions x {len(slots)} nodes), '
        f'{len(layouts)} layouts per seed, seeds {seeds}, {args.workers} workers\n'
    )

    results_by_seed = {}
    for seed in seeds:
        if scorer_factory is None:
            factory = _default_factory(args, episode, seed, log)
        else:
            factory = lambda s=seed: scorer_factory(s)

        progress = Progress(len(layouts), f'seed {seed}')
        results_by_seed[seed] = score_layouts(layouts, factory, args.workers, progress)

    slices = []
    offset = 0
    for spec in specs:
        count = len(spec.layouts)
        per_seed = {
            seed: results[offset:offset + count]
            for seed, results in results_by_seed.items()
        }
        offset += count

        flows_for_time = flow_source.flows[float(spec.record['time_s'])]
        slices.append(assemble_slice(
            spec, per_seed, flows_for_time, routing, composer, components, contract,
        ))

    band = contract.get('band') or episode.band

    return {
        'landscape_version': LANDSCAPE_VERSION,
        'contract': contract['contract'],
        'source': {
            'method': 'channel_query',
            'approximation': 'snapshot',
            'run_config': 'inputs/run.ini',
            'band': band,
            'seeds': list(seeds),
            'run_id': episode.run_id,
            'sim_binary': str(args.sim_binary),
            'generated_at': _now_iso(),
            'generator': GENERATOR,
        },
        'grid': grid.describe(),
        'reward_schema': {'components': components, 'weights': weights},
        'slices': slices,
    }


def parse_seed_spec(raw: str) -> list:
    """Expand a comma list of integers and inclusive `A-B` ranges, order preserved."""
    distinct = str(raw)
    tokens = distinct.split(',')
    if not tokens or all(not t.strip() for t in tokens):
        raise ValueError('seed specification is empty')
    seeds = []
    seen = set()
    for token in tokens:
        token = token.strip()
        low, separator, high = token.partition('-')
        try:
            if separator:
                start, end = int(low), int(high)
                if start > end:
                    raise ValueError(f'seed range {token!r} must have A <= B')
                for seed in range(start, end + 1):
                    if seed in seen:
                        raise ValueError(f'seed {seed} is listed more than once')
                    seen.add(seed)
                    seeds.append(seed)
            else:
                seed = int(token)
                if seed in seen:
                    raise ValueError(f'seed {seed} is listed more than once')
                seen.add(seed)
                seeds.append(seed)
        except ValueError as exc:
            if 'seed' in str(exc):
                raise
            raise ValueError(f'seed {token!r} is not an integer or an A-B range: {exc}') from exc
    return seeds


def _int_list(raw):
    try:
        return parse_seed_spec(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='python -m scripts.rl.reward_landscape',
        description=(
            "Precompute reward vs. one node's xy position for saved decisions of an RL "
            "episode, scored by the simulator's --channel-query."
        ),
    )
    parser.add_argument(
        '--episode-dir', required=True,
        help='episode-NNNN/ with steps.jsonl, rl_episode.json, inputs/',
    )
    parser.add_argument(
        '--sim-binary', required=True,
        help='Built mesh-sim binary with --channel-query support',
    )
    parser.add_argument(
        '--grid', type=int, default=41,
        help='Grid points per axis over the [rl] xy bounds (default 41)',
    )
    pick = parser.add_mutually_exclusive_group()
    pick.add_argument(
        '--decisions', type=_int_list,
        help='Saved decisions to map, e.g. 0,100,200 or 10-12',
    )
    pick.add_argument(
        '--every', type=int,
        help='Map saved decisions divisible by N (default: 8 evenly spaced saved decisions)',
    )
    parser.add_argument(
        '--nodes',
        help='Comma list of controlled node ids or slot indices (default: every controlled slot)',
    )
    parser.add_argument(
        '--seeds', type=_int_list,
        help='Channel seeds to average (default: the episode seed)',
    )
    parser.add_argument(
        '--workers', type=int, default=1,
        help='Parallel channel-query worker processes (default 1)',
    )
    parser.add_argument(
        '--output',
        help=f'Output file (default <episode-dir>/{OUTPUT_NAME})',
    )
    return parser


def main(argv=None, scorer_factory=None) -> int:
    args = build_parser().parse_args(argv)

    if args.workers < 1:
        sys.stderr.write('error: --workers must be >= 1\n')
        return 1

    if args.every is not None and args.every < 1:
        sys.stderr.write('error: --every must be >= 1\n')
        return 1

    if args.nodes:
        args.nodes = [token.strip() for token in args.nodes.split(',') if token.strip()]

    output = Path(args.output) if args.output else Path(args.episode_dir) / OUTPUT_NAME

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output.with_name(LOG_NAME), 'w') as log:
            payload = generate(args, scorer_factory, log)
        write_landscape(output, payload)
        sys.stderr.write(f'wrote {output} ({len(payload["slices"])} slices)\n')
        return 0
    except (EpisodeError, TrafficError, LandscapeError, PlannerError, OSError, ValueError, KeyError) as exc:
        sys.stderr.write(f'error: {exc}\n')
        return 1


if __name__ == '__main__':
    sys.exit(main())
