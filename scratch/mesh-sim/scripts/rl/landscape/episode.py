"""Read one RL episode directory and lay out the candidate layouts of a reward landscape.

Inputs are the episode's `steps.jsonl` (header + saved decisions), `rl_episode.json`
(seed and simulator command) and the archived `inputs/run.ini` + nodes file. Output is
plain data: per (decision, slot) the grid of layouts and the five reachable moves.
"""
# Recovered from bytecode — approximate reconstruction
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from scripts.baselines.effective_inputs import start_position
from scripts.rl.env.telemetry import TELEMETRY_FILE
from scripts.sim_support import parse_ini

CONTRACTS = ('mesh_move_2d_v1', 'mesh_move_2d_v2')
MOVE_LABELS = ('W', 'E', 'S', 'N', 'hold')
HOLD_ACTION = 4
WALL_EPS_M = 1e-6
Z_TOL_M = 1e-6


class EpisodeError(ValueError):
    """The episode directory cannot drive a reward landscape."""


@dataclass(frozen=True)
class Episode:
    """Everything the generator reads from one `episode-NNNN/` directory."""

    directory: Path
    header: dict
    records: dict
    manifest: dict
    run_ini: Path
    node_entries: list
    seed: int
    run_id: int
    band: str | None

    @property
    def contract(self) -> dict:
        return self.header['contract']

    @property
    def node_ids(self) -> list:
        return list(self.contract['node_ids'])

    @property
    def start_positions(self) -> list:
        return [list(start_position(entry)) for entry in self.node_entries]

    @property
    def flows_csv(self) -> Path:
        return self.directory / f'seed-{self.seed}' / 'flows.csv'


def _command_value(command, flag: str) -> str | None:
    for arg in (command or []):
        if not isinstance(arg, str):
            continue
        if arg.startswith(flag + '='):
            return arg.split('=', 1)[1]
    return None


def load_episode(episode_dir) -> Episode:
    directory = Path(episode_dir)
    steps = directory / TELEMETRY_FILE
    manifest_path = directory / 'rl_episode.json'
    run_ini = directory / 'inputs' / 'run.ini'

    for path in (steps, manifest_path, run_ini):
        if not path.is_file():
            raise EpisodeError(f'{path} is missing (needs a centralized episode run with --telemetry steps)')

    lines = [line for line in steps.read_text().splitlines() if line.strip()]
    if not lines:
        raise EpisodeError(f'{steps} is empty')

    header = json.loads(lines[0])
    if header.get('type') != 'header':
        raise EpisodeError(f'{steps} does not start with a header line')

    contract = header.get('contract') or {}
    if contract.get('contract') not in CONTRACTS:
        raise EpisodeError(
            f'{steps}: contract {contract.get("contract")!r} is not one of {CONTRACTS!r}'
        )

    records = {}
    for line in lines[1:]:
        record = json.loads(line)
        if record.get('type') == 'step':
            records[int(record['decision'])] = record

    if not records:
        raise EpisodeError(f'{steps} has no saved decisions')

    manifest = json.loads(manifest_path.read_text())
    ini = parse_ini(run_ini)

    nodes_name = ini.get('scenario', {}).get('nodes_file', 'nodes.json') or 'nodes.json'
    nodes_path = run_ini.parent / nodes_name

    if not nodes_path.is_file():
        raise EpisodeError(f'nodes file {nodes_path} is missing')

    node_entries = json.loads(nodes_path.read_text())
    if [entry.get('id') for entry in node_entries] != list(contract['node_ids']):
        raise EpisodeError(f'{nodes_path} node ids differ from the contract\'s node_ids')

    command = manifest.get('command')
    run_id = _command_value(command, '--run-id') or ini.get('scenario', {}).get('run_id')

    return Episode(
        directory=directory,
        header=header,
        records=records,
        manifest=manifest,
        run_ini=run_ini,
        node_entries=node_entries,
        seed=int(manifest['seed']),
        run_id=int(run_id or 1),
        band=_command_value(command, '--band'),
    )


def reward_schema_lists(header: dict) -> tuple[list, list]:
    schema = header.get('reward_schema') or {}
    if schema.get('authority') == 'python' and schema.get('components'):
        return list(schema['components']), [float(w) for w in schema['weights']]
    return ['legacy'], [1.0]


def resolve_slots(contract: dict, tokens) -> list:
    slots = list(contract['slot_node_ids'])
    active = [(i, node_id) for i, node_id in enumerate(slots) if node_id is not None]

    if not tokens:
        return active

    chosen = []
    for token in tokens:
        token = str(token).strip()
        if token in slots:
            pair = (slots.index(token), token)
        elif token.isdigit() and int(token) < len(slots) and slots[int(token)] is not None:
            pair = (int(token), slots[int(token)])
        else:
            node_names = [n for _, n in active]
            raise EpisodeError(
                f'--nodes entry {token!r} is neither a controlled node id '
                f'{node_names} nor an active slot index'
            )
        if pair not in chosen:
            chosen.append(pair)
    return chosen


def select_decisions(records: dict, decisions=None, every=None, default_count: int = 8) -> list:
    saved = sorted(records)

    if decisions:
        missing = [d for d in decisions if d not in records]
        if missing:
            raise EpisodeError(
                f'decisions {missing} are not saved in steps.jsonl '
                f'(saved: {saved[0]}..{saved[-1]}, {len(saved)} records)'
            )
        return sorted(set(int(d) for d in decisions))

    if every:
        chosen = [d for d in saved if int(every) % int(every) == 0]
        # Actually: d % every == 0
        chosen = [d for d in saved if d % int(every) == 0]
    elif len(saved) <= default_count:
        chosen = saved
    else:
        step = (len(saved) - 1) / (default_count - 1)
        chosen = sorted({saved[round(k * step)] for k in range(default_count)})

    if not chosen:
        raise EpisodeError('no saved decision matches the selection')
    return chosen


@dataclass(frozen=True)
class Grid:
    """Cell centres over the xy bounds: x_i = x_min + i (x_max - x_min)/(nx - 1)."""

    x_min: float
    x_max: float
    nx: int
    y_min: float
    y_max: float
    ny: int

    def points(self) -> list:
        """Row-major with y outer: index = iy * nx + ix."""
        xs = [self.x_min + i * (self.x_max - self.x_min) / (self.nx - 1) for i in range(self.nx)]
        ys = [self.y_min + i * (self.y_max - self.y_min) / (self.ny - 1) for i in range(self.ny)]
        return [(x, y) for y in ys for x in xs]

    def describe(self) -> dict:
        return {'x_min': self.x_min, 'x_max': self.x_max, 'nx': self.nx,
                'y_min': self.y_min, 'y_max': self.y_max, 'ny': self.ny}


def contract_grid(contract: dict, size: int) -> Grid:
    if int(size) < 2:
        raise EpisodeError('--grid must be at least 2')
    b = contract['bounds']
    grid = Grid(
        float(b['x_min']), float(b['x_max']), int(size),
        float(b['y_min']), float(b['y_max']), int(size),
    )
    if not (grid.x_max > grid.x_min and grid.y_max > grid.y_min):
        raise EpisodeError(f'contract bounds {b} have no xy area')
    return grid


def reachable_moves(contract: dict, slot: int, x: float, y: float, mask=None) -> list:
    b = contract['bounds']
    step = (float(contract['slot_speed_mps'][slot])
            * int(contract['decision_interval_ticks'])
            * float(contract['tick_s']))

    targets = [
        (max(float(b['x_min']), x - step), y),
        (min(float(b['x_max']), x + step), y),
        (x, max(float(b['y_min']), y - step)),
        (x, min(float(b['y_max']), y + step)),
        (x, y),
    ]
    room = [
        x - float(b['x_min']),
        float(b['x_max']) - x,
        y - float(b['y_min']),
        float(b['y_max']) - y,
        math.inf,
    ]

    moves = []
    for action, (label, target, gap) in enumerate(zip(MOVE_LABELS, targets, room)):
        if mask is not None and len(mask) >= 5 * (slot + 1):
            valid = bool(mask[5 * slot + action])
        else:
            valid = action == HOLD_ACTION or gap > WALL_EPS_M
        moves.append({
            'action': action,
            'label': label,
            'position': [target[0], target[1]],
            'valid': valid,
        })
    return moves


@dataclass
class SliceSpec:
    """One (decision, slot) map: its layouts, and where grid and moves sit in them."""

    decision: int
    slot: int
    node_id: str
    node_index: int
    record: dict
    previous_nodes: list | None
    initial_nodes: list
    layouts: list = field(default_factory=list)
    grid_count: int = 0
    moves: list = field(default_factory=list)
    move_layouts: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


def _base_layout(record: dict, starts: list, warnings: list) -> list:
    """Record positions with each node's z forced to its start z (`ApplyLayout` rule)."""
    layout = []
    for index, (row, start) in enumerate(zip(record['facts']['nodes'], starts)):
        if abs(float(row[2]) - start[2]) > Z_TOL_M:
            warnings.append(
                f'node index {index}: recorded z {row[2]} differs from its start z '
                f'{start[2]}; the channel query needs the start z, so it is used'
            )
        layout.append([float(row[0]), float(row[1]), float(start[2])])
    return layout


def plan_slice(episode: Episode, decision: int, slot: int, node_id: str, grid: Grid) -> SliceSpec:
    record = episode.records[decision]
    node_index = episode.node_ids.index(node_id)
    initial = episode.records.get(0)
    if initial is None:
        raise EpisodeError('steps.jsonl has no decision 0 (reset) record')

    previous = episode.records.get(decision - 1) if decision > 0 else initial
    spec = SliceSpec(
        decision=decision,
        slot=slot,
        node_id=node_id,
        node_index=node_index,
        record=record,
        previous_nodes=previous['facts']['nodes'] if previous is not None else None,
        initial_nodes=initial['facts']['nodes'],
    )

    base = _base_layout(record, episode.start_positions, spec.warnings)

    for x, y in grid.points():
        layout = [list(row) for row in base]
        layout[node_index][0] = x
        layout[node_index][1] = y
        spec.layouts.append(layout)

    spec.grid_count = len(spec.layouts)

    here = base[node_index]
    spec.moves = reachable_moves(episode.contract, slot, here[0], here[1], record.get('mask'))

    for move in spec.moves:
        if not move['valid']:
            continue
        layout = [list(row) for row in base]
        mx, my = move['position']
        layout[node_index][0] = mx
        layout[node_index][1] = my
        spec.move_layouts[move['action']] = len(spec.layouts)
        spec.layouts.append(layout)

    return spec
