"""Behavior checks preserved from the experiment pilots; no native simulation."""

import configparser
import json

import pytest

from scripts.rl.env.state.mission import MissionState
from scripts.rl.env.mesh_env import MeshRlEnv
from scripts.rl.env.rewards import RewardComposer
from scripts.rl.env.selection import resolve_selection
from scripts.rl.env.recording.telemetry import replay_file
from scripts.rl.env.geometry import segment_hits
from scripts.rl.env.geometry import physical_audit
from scripts.rl.policy.mission_metrics import compute_mission_metrics
from scripts.rl.tests.env.test_mission_facts import state_inputs
from scripts.sim_support import find_mesh_root


def test_team_requires_every_member_arrival_connection_and_service():
    facts, c = state_inputs()
    c["mission"].update(
        version=2, team_investigation=True, team_radius_m=50, team_delivery_target=0.8
    )
    facts["nodes"][2][0] = 80
    tracker = MissionState()
    tracker.advance(facts, c, 0)
    assert tracker.advance(facts, c, 1)["team_arrival_fraction"] == pytest.approx(2 / 3)
    assert tracker.advance(facts, c, 2)["investigation_completed_at_s"] is None
    facts["nodes"][2][0] = 40
    assert tracker.advance(facts, c, 3)["arrival_at_s"] == 3
    facts["mission"]["survivor_delivered_mbps_sum"] = 6
    facts["mission"]["survivor_node_service"] = [[8, 4]] * 3
    assert tracker.advance(facts, c, 4)["arrival_streak_s"] == 0
    facts["mission"]["survivor_delivered_mbps_sum"] = 12
    facts["mission"]["survivor_node_service"] = [[8, 8]] * 3
    tracker.advance(facts, c, 5)
    assert tracker.advance(facts, c, 6)["investigation_completed_at_s"] == 6


def test_collision_attempt_penalty_has_no_penetration_requirement():
    reward = RewardComposer(["collision_attempt_fraction"], [-5])
    contract = {
        "num_controlled": 3,
        "unsafe_separation_m": 5,
        "avoid_node_collisions": True,
        "navigation": {},
    }
    context = {
        "safety": {"building_rejected_slots": [0], "peer_rejected_slots": [0, 2]}
    }
    assert reward.compose(
        {"scored_ticks": 2}, 0, contract, context
    ).total == pytest.approx(-10 / 3)
    context = {"safety": {"building_rejected_slots": [], "peer_rejected_slots": []}}
    assert reward.compose({"scored_ticks": 2}, 0, contract, context).total == 0


def test_building_path_checks_include_roofs_clearance_and_diagonal_misses():
    b = {"x_min": 10, "x_max": 30, "y_min": 10, "y_max": 30, "z_min": 0, "z_max": 8}
    assert segment_hits([5, 20, 1.5], [35, 20, 1.5], b, 2)
    assert not segment_hits([5, 20, 20], [35, 20, 20], b, 2)
    assert segment_hits([5, 20, 9], [35, 20, 9], b, 2)
    assert not segment_hits([5, 5, 1.5], [10, 35, 1.5], b)


def test_dense_audit_detects_peer_crossing_between_safe_endpoints():
    contract = {
        "navigation": {"buildings": [], "building_clearance_m": 2},
        "unsafe_separation_m": 5,
    }
    records = [
        {"facts": {"nodes": [[0, 0, 0], [10, 0, 0]], "node_available": [True, True]}},
        {"facts": {"nodes": [[10, 0, 0], [0, 0, 0]], "node_available": [True, True]}},
    ]
    with pytest.raises(ValueError, match="peer collision"):
        physical_audit(records, contract)
    records[0]["facts"]["nodes"][0][2] = records[1]["facts"]["nodes"][0][2] = 20
    assert physical_audit(records, contract)["peer_collisions"] == 0


@pytest.mark.parametrize("mission", ["coverage", "investigation", "recovery"])
def test_pilot_observations_collision_component_and_metrics_replay(
    sim_binary, tmp_path, mission
):
    inputs = find_mesh_root() / "inputs/custom/10-16-2"
    if not inputs.is_dir():
        pytest.skip("local pilot inputs unavailable")
    source = inputs / f"urban-{mission}-small"
    folder = tmp_path / "inputs"
    folder.mkdir()
    ini = configparser.ConfigParser(interpolation=None)
    ini.read(source / "run.ini")
    ini["scenario"]["duration_s"] = "4"
    ini["scenario"]["buildings_file"] = str(source / "buildings.json")
    ini["rl"]["telemetry"] = "steps"
    nodes = json.loads((source / "nodes.json").read_text())
    for n in nodes:
        if "failure_at_s" in n:
            n["failure_at_s"] = 2
    (folder / "nodes.json").write_text(json.dumps(nodes))
    with (folder / "run.ini").open("w") as f:
        ini.write(f)
    path = folder / "run.ini"
    env = MeshRlEnv(
        sim_binary,
        str(path),
        seed=201,
        output_dir=str(tmp_path / "run"),
        selection=resolve_selection(str(path)),
    )
    try:
        obs, _ = env.reset()
        assert env.observation_space.contains(obs)
        for _ in range(4):
            obs, _, _, _, _ = env.step([4] * 3)
            assert env.observation_space.contains(obs)
    finally:
        env.close()
    file = next((tmp_path / "run").glob("episode-*/steps.jsonl"))
    replay = replay_file(file)
    assert not replay.obs_mismatches and not replay.reward_mismatches
    data = [json.loads(line) for line in file.read_text().splitlines()]
    metrics = compute_mission_metrics(data[1:], data[0]["contract"])
    assert (
        metrics["building_collision_attempts"] == 0
        and metrics["peer_collision_attempts"] == 0
    )
    assert metrics["final_minute_coverage"] == 0.75
