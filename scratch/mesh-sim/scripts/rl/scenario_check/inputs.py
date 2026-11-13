"""Materialize the approved scenario-check scenarios without launching any processes."""

import json
import math
from pathlib import Path
import random

from scripts.artifact_io import write_json
from scripts.rl.env.geometry import route, safe_segment
from scripts.rl.scenario_check.archive import input_hashes, read_ini, write_ini
from scripts.rl.scenario_check.defaults import (
    BUILDING_CLEARANCE_M,
    CANDIDATE_GRID_CELLS,
    CHANNEL_PLANNING_SEED,
    COVERAGE_GRID_CELLS,
    COVERAGE_SINR_DB,
    DEFAULT_WORKERS,
    EVALUATION_SEEDS,
    GRID_MIN_RESOLUTION_M,
    OPTIMIZER_SEED,
    PEER_SEPARATION_M,
    PROBE_HEIGHT_M,
    PROBE_RX_GAIN_DBI,
)

TYPES = ("ground", "drone", "vehicle")
TARGETS = {
    "coverage": {
        "ground": [(195, 200), (195, 300), (300, 300)],
        "drone": [(100, 200), (280, 300), (195, 100)],
        "vehicle": [(300, 200), (100, 300), (100, 100)],
    },
    "investigation": {
        "ground": [(315, 300), (315, 290), (315, 310)],
        "drone": [(345, 300), (345, 280), (345, 320)],
        "vehicle": [(345, 330), (355, 300), (335, 300)],
    },
    "recovery": {
        "ground": [(170, 200), (170, 190), (170, 220)],
        "drone": [(200, 200), (200, 140), (200, 260)],
        "vehicle": [(230, 200), (230, 190), (230, 220)],
    },
    "jamming": {
        "ground": [(195, 355), (195, 375), (245, 355)],
        "drone": [(195, 395), (245, 395), (295, 395)],
        "vehicle": [(245, 375), (295, 375), (295, 355)],
    },
}


def traffic(nodes, mission, q=3.0):
    if mission != "recovery":
        return [
            dict(src=a["id"], dst=b["id"], demand_mbps=q / (len(nodes) - 1))
            for a in nodes
            for b in nodes
            if a != b
        ]
    pairs = []
    for i in range(1, len(nodes) // 3 + 1):
        g, d, v = (f"{kind}-{i}" for kind in TYPES)
        pairs += [
            dict(src=g, dst=v, demand_mbps=q),
            dict(src=v, dst=g, demand_mbps=q),
            dict(src=d, dst=g, demand_mbps=q / 2),
            dict(src=d, dst=v, demand_mbps=q / 2),
        ]
    return pairs


def jammer(seed):
    """Seeded route chosen before rollout; silent approach, then stationary emission."""
    rng = random.Random(seed)
    onset = rng.choice((160, 180, 200))
    # Counterbalance stop and approach side rather than drawing duplicate
    # routes in this small two-seed diagnostic set. Onset is pseudorandom.
    end = ((195, 200), (220, 200), (245, 200))[(seed - EVALUATION_SEEDS[0]) % 3]
    vertical = end[0] == 245
    side = 20 if seed % 2 else 380
    start = (245, side) if vertical else (side, 200)
    points = [(0, *start), (onset - 60, *start), (onset, *end), (600, *end)]
    spec = dict(
        id="seeded-arrive-and-stay",
        enabled=True,
        type="constant",
        target_freq=[5800],
        tx_power_dbm=18,
        tx_array_gain_dbi=3,
        duty_cycle=1,
        max_range_m=140,
        beamwidth_deg=360,
        azimuth_deg=0,
        zenith_deg=90,
        position=dict(x=start[0], y=start[1], z=1.5),
        intervals=[dict(start=onset, end=600.5)],
        waypoints=[dict(t=t, x=x, y=y, z=1.5) for t, x, y in points],
    )
    return spec, onset


def reference_routes(nodes, buildings, targets):
    """Route around buildings and other peers' start/settled positions."""
    routes = {}
    for i, node in enumerate(nodes):
        if "failure_at_s" in node:
            routes[node["id"]] = []
            continue
        reservations = []
        for j, other in enumerate(nodes):
            if i == j:
                continue
            end = (*targets[other["id"]], other["position"]["z"])
            for pos in (tuple(other["position"][k] for k in "xyz"), end):
                reservations.append(
                    {
                        f"{axis}_{bound}": v + (-2.3 if bound == "min" else 2.3)
                        for axis, v in zip("xyz", pos)
                        for bound in ("min", "max")
                    }
                )
        start = tuple(node["position"][k] for k in "xyz")
        routes[node["id"]] = route(start, targets[node["id"]], buildings + reservations)
    return routes


def _case_nodes(mission, n, positions):
    nodes = []
    for group in range(n // 3):
        for kind in TYPES:
            x, y = positions[mission][kind][group]
            z = 20 if kind == "drone" else 1.5
            node = dict(
                id=f"{kind}-{group+1}",
                role="peer",
                node_type="pedestrian" if kind == "ground" else kind,
                mobility="constant_velocity",
                position=dict(x=x, y=y, z=z),
                velocity=dict(vx=0, vy=0, vz=0),
            )
            if mission == "recovery":
                gain = 12 if kind == "drone" else 3
                node.update(tx_array_gain_dbi=gain, rx_array_gain_dbi=gain)
                if kind == "drone":
                    node["failure_at_s"] = 10.0
            nodes.append(node)
    return nodes


def _write_seed_configs(template, folder, name, mission, n, pairs, boxes):
    ini = read_ini(template)
    ini["scenario"].update(
        name=f"10-23-check-{name}",
        nodes_file=str((folder / "nodes.json").resolve()),
        buildings_file=str((folder / "buildings.json").resolve()),
        jammers_file="",
    )
    ini["traffic"].update(
        flow_topology="explicit_pairs",
        model="constant",
        demand_mbps="3",
        pairs=json.dumps(pairs, separators=(",", ":")),
    )
    # A diagnostic return only: these references never learn from it.
    ini["rl"].update(
        controlled_nodes="all",
        max_controlled_nodes=str(n),
        telemetry="steps",
        compact_training="false",
        reward_components="delivery_ratio",
        reward_weights="1",
        avoid_buildings="true",
        avoid_node_collisions="true",
        building_clearance_m=str(BUILDING_CLEARANCE_M),
        unsafe_separation_m=str(PEER_SEPARATION_M),
        mask_building_moves="true",
    )
    for key in list(ini["rl"]):
        if key.startswith("jammer_") or key in (
            "training_jammer_onsets_s",
            "evaluation_jammer_onsets_s",
        ):
            del ini["rl"][key]
    ini["baseline"].update(
        candidate_grid_cells=str(CANDIDATE_GRID_CELLS),
        coverage_grid_cells=str(COVERAGE_GRID_CELLS),
        grid_min_resolution_m=str(GRID_MIN_RESOLUTION_M),
        coverage_probe_height_m=str(PROBE_HEIGHT_M),
        coverage_probe_rx_gain_dbi=str(PROBE_RX_GAIN_DBI),
        coverage_sinr_db=str(COVERAGE_SINR_DB),
        aerial_cost_m2_per_m="0",
        ground_cost_m2_per_m="0",
    )
    if mission == "investigation":
        ini["mission"].update(
            arrival_radius_m="50",
            team_radius_m="50",
            goal_coverage_target="0",
            team_delivery_target="0",
        )
    seeds = {}
    for seed in EVALUATION_SEEDS:
        seed_folder = folder / f"seed-{seed}"
        seed_folder.mkdir()
        gate = 10 if mission == "recovery" else 0
        if mission == "jamming":
            spec, gate = jammer(seed)
            points = [(p["x"], p["y"], p["z"]) for p in spec["waypoints"]]
            if not all(
                safe_segment(a, b, boxes, BUILDING_CLEARANCE_M)
                for a, b in zip(points, points[1:])
            ):
                raise ValueError(f"jammer path crosses buildings: {name}/{seed}")
            write_json(seed_folder / "jammers.json", [spec])
            ini["scenario"]["jammers_file"] = str(
                (seed_folder / "jammers.json").resolve()
            )
        ini["scenario"]["seed"] = str(seed)
        write_ini(seed_folder / "run.ini", ini)
        seeds[str(seed)] = dict(run_config=f"seed-{seed}/run.ini", gate_s=gate)
    # run.ini is the first diagnostic seed, useful for inspection only.
    write_ini(
        folder / "run.ini", read_ini(folder / f"seed-{EVALUATION_SEEDS[0]}/run.ini")
    )
    return seeds


def _materialize_case(root, out, environment, mission, n, positions, buildings, boxes):
    name = f"{environment}-{mission}-{n}-peers"
    folder = out / name
    folder.mkdir()
    write_json(folder / "buildings.json", buildings)
    nodes = _case_nodes(mission, n, positions)
    targets = {
        node["id"]: TARGETS[mission][node["id"].rsplit("-", 1)[0]][
            int(node["id"].rsplit("-", 1)[1]) - 1
        ]
        for node in nodes
    }
    routes = reference_routes(nodes, boxes, targets)
    write_json(folder / "nodes.json", nodes)
    write_json(
        folder / "reference.json",
        dict(
            reference_version=1,
            routes=routes,
            description="Obstacle-safe diagnostic routes; RF feasibility and joint completion are checked at runtime.",
        ),
    )
    pairs = traffic(nodes, mission)
    template = root / f"{environment}-{mission}-small/run.ini"
    seeds = _write_seed_configs(template, folder, name, mission, n, pairs, boxes)
    offered = {
        node["id"]: sum(p["demand_mbps"] for p in pairs if p["src"] == node["id"])
        for node in nodes
    }
    assert all(math.isclose(v, 3) for v in offered.values())
    starts = [list(node["position"].values()) for node in nodes]
    assert all(safe_segment(p, p, boxes, BUILDING_CLEARANCE_M) for p in starts)
    separation = min(
        math.dist(a, b) for i, a in enumerate(starts) for b in starts[i + 1 :]
    )
    assert separation >= PEER_SEPARATION_M
    case = dict(
        name=name,
        mission=mission,
        environment=environment,
        peers=n,
        seeds=seeds,
    )
    write_json(folder / "case.json", case)
    lengths = {
        node: sum(math.dist(a, b) for a, b in zip([starts[i]] + points, points))
        for i, (node, points) in enumerate(routes.items())
    }
    check = dict(
        case=name,
        per_source_mbps=offered,
        total_mbps=sum(offered.values()),
        min_start_3d_separation_m=separation,
        reference_route_length_m=lengths,
    )
    return case, check


def materialize(root, positions):
    """Create a distinct subtree, retaining all earlier experimental inputs."""
    root = Path(root)
    out = root / "scenario-check"
    if out.exists():
        raise FileExistsError(f"will not overwrite scenario-check inputs: {out}")
    out.mkdir()
    cases, checks = [], []
    for environment in ("urban", "rural"):
        buildings = json.loads(
            (root / f"{environment}-coverage-small/buildings.json").read_text()
        )
        boxes = [b["bounds"] for b in buildings]
        for mission in TARGETS:
            for n in (3, 6, 9):
                case, check = _materialize_case(
                    root, out, environment, mission, n, positions, buildings, boxes
                )
                cases.append(case)
                checks.append(check)
    campaign = dict(
        scenario_check_version=1,
        stage="scenario_checks_only",
        training_enabled=False,
        evaluation_seeds=list(EVALUATION_SEEDS),
        planning_seed=CHANNEL_PLANNING_SEED,
        optimizer_seed=OPTIMIZER_SEED,
        workers=DEFAULT_WORKERS,
        episodes_expected=168,
        cases=cases,
        source_specification="Approved planning record 001",
        static_validation=checks,
    )
    campaign["input_hashes"] = input_hashes(out)
    write_json(out / "scenario-check.json", campaign)
    return campaign
