"""Use the existing placement engine with the scenario check's outdoor domain."""

from dataclasses import asdict
import json
import math
from pathlib import Path

from scripts.artifact_io import write_json, sha256_file
from scripts.baselines.runtime_identity import (
    channel_runtime_identity,
    planner_code_identity,
)
from scripts.baselines.solver import PlannerNode, PlanRequest, solve
from scripts.baselines.planners.objective import (
    GridSettings,
    ProbeSettings,
    MovementCost,
    ObjectiveSettings,
)
from scripts.rl.env.geometry import safe_segment
from scripts.rl.scenario_check.archive import read_ini, write_ini
from scripts.rl.scenario_check.defaults import (
    BAND,
    BUILDING_CLEARANCE_M,
    CANDIDATE_GRID_CELLS,
    CHANNEL_PLANNING_SEED,
    COVERAGE_GRID_CELLS,
    COVERAGE_SINR_DB,
    EVALUATION_SEEDS,
    GRID_MIN_RESOLUTION_M,
    MAP_SIZE_M,
    OPTIMIZER_MAX_ITERATIONS,
    OPTIMIZER_SEED,
    PEER_SEPARATION_M,
    PROBE_HEIGHT_M,
    PROBE_RX_GAIN_DBI,
)


def prepare(method, case_folder, output, binary):
    """Plan once on seed 311; apply legal endpoints before both evaluation episodes.

    This is an initial-placement benchmark, not a route from the compact start.
    """
    output = Path(output)
    output.mkdir(parents=True)
    ini_path = case_folder / f"seed-{EVALUATION_SEEDS[0]}/run.ini"
    nodes = json.loads((case_folder / "nodes.json").read_text())
    boxes = [
        b["bounds"] for b in json.loads((case_folder / "buildings.json").read_text())
    ]
    expanded = tuple(
        {
            key: value
            + (-BUILDING_CLEARANCE_M if key.endswith("_min") else BUILDING_CLEARANCE_M)
            for key, value in b.items()
        }
        for b in boxes
    )
    records = tuple(
        PlannerNode(
            node["id"],
            i,
            node["mobility"],
            "aerial" if node["node_type"] == "drone" else "ground",
            **node["position"],
            role="movable",
        )
        for i, node in enumerate(nodes)
    )
    request = PlanRequest(
        method=method,
        objective="coverage",
        nodes=records,
        rectangle=dict(x_min=0, x_max=MAP_SIZE_M, y_min=0, y_max=MAP_SIZE_M),
        rl_bounds=dict(
            x_min=0, x_max=MAP_SIZE_M, y_min=0, y_max=MAP_SIZE_M, z_min=0, z_max=60
        ),
        mode="evaluation",
        penalties={p: MovementCost(0, 0) for p in ("aerial", "ground")},
        grid=GridSettings(
            CANDIDATE_GRID_CELLS, COVERAGE_GRID_CELLS, GRID_MIN_RESOLUTION_M
        ),
        probe=ProbeSettings(PROBE_HEIGHT_M, PROBE_RX_GAIN_DBI, COVERAGE_SINR_DB),
        planner_seed=OPTIMIZER_SEED,
        max_iterations=OPTIMIZER_MAX_ITERATIONS,
        balanced_core_fraction=0.5,
        waypoint_policy="reject",
        planning_seed=CHANNEL_PLANNING_SEED,
        run_id=1,
        band=BAND,
        query_run_config=ini_path,
        sim_binary=Path(binary),
        objective_settings=ObjectiveSettings(
            coverage_weight=1,
            separation_frac=0,
            disconnected_aoi_factor=0,
            vulnerability_aoi_factor=0,
        ),
        forbidden_buildings=expanded,
        minimum_separation_m=PEER_SEPARATION_M,
        probe_exclusion_buildings=tuple(boxes),
    )
    with (output / "planner.log").open("w") as log:
        result = solve(request, log)
    displaced = 0
    for node in nodes:
        old = tuple(node["position"][k] for k in "xyz")
        new = result.positions[node["id"]]
        if (
            new[2] != old[2]
            or not all(0 <= v <= MAP_SIZE_M for v in new[:2])
            or not safe_segment(new, new, boxes, BUILDING_CLEARANCE_M)
        ):
            raise ValueError(f'invalid planned endpoint: {node["id"]}')
        displaced += math.dist(old, new)
        node["position"] = dict(zip("xyz", new))
    points = [tuple(n["position"][k] for k in "xyz") for n in nodes]
    if any(
        math.dist(a, b) < PEER_SEPARATION_M - 1e-6
        for i, a in enumerate(points)
        for b in points[i + 1 :]
    ):
        raise ValueError("planned endpoints violate peer separation")
    write_json(output / "nodes.json", nodes)
    configs = {}
    for seed in EVALUATION_SEEDS:
        ini = read_ini(case_folder / f"seed-{seed}/run.ini")
        ini["scenario"]["nodes_file"] = str((output / "nodes.json").resolve())
        configs[str(seed)] = output / f"seed-{seed}.ini"
        write_ini(configs[str(seed)], ini)
    metadata = dict(
        method=method,
        benchmark_kind="initial_placement_not_navigation",
        initial_displacement_m_total=displaced,
        planning_seed=CHANNEL_PLANNING_SEED,
        optimizer_seed=OPTIMIZER_SEED,
        seed_roles=dict(
            planning=[CHANNEL_PLANNING_SEED],
            optimizer=[OPTIMIZER_SEED],
            diagnostic_evaluation=list(EVALUATION_SEEDS),
        ),
        source_ini_sha256=sha256_file(ini_path),
        result=asdict(result),
        planner_code=planner_code_identity(),
        channel_runtime=channel_runtime_identity(binary),
        claim="Feasible bounded search; no global optimality or navigation claim.",
    )
    write_json(output / "placement.json", metadata)
    return configs, metadata
