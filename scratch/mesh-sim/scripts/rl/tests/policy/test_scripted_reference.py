"""Behavior checks preserved from the experiment pilots; no native simulation."""

import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from scripts.sim_support import find_mesh_root
from scripts.rl.env.jammer_motion import prepare_motion_config
from scripts.rl.policy.scripted import ScriptedMissionPolicy
from scripts.rl.env.geometry import segment_hits


pytestmark = pytest.mark.skipif(
    not (find_mesh_root() / "inputs/custom/10-23/urban-jamming-small").is_dir(),
    reason="private route fixtures unavailable",
)


def test_route_variation_is_reproducible_and_stays_in_open_streets(tmp_path):
    root = find_mesh_root() / "inputs/custom/10-23/urban-jamming-small"
    buildings = json.loads((root / "buildings.json").read_text())
    variants = []
    for i in range(30):
        dest = tmp_path / str(i)
        dest.mkdir()
        path, meta = prepare_motion_config(root / "run.ini", dest, 101, i, False)
        variants.append(meta)
        points = meta["waypoints"]
        assert points[-1]["x"] == points[-2]["x"] and points[-1]["y"] == points[-2]["y"]
        assert meta["arrival_s"] == meta["motion_start_s"] + 60
        assert meta["motion_start_s"] == [160, 180, 200][i % 3]
        for a, b in zip(points, points[1:]):
            assert not any(
                segment_hits(
                    [a[k] for k in "xyz"], [b[k] for k in "xyz"], box["bounds"], 3
                )
                for box in buildings
            )
    assert len({tuple(m["target_xy"]) for m in variants}) == 30 and {
        m["axis"] for m in variants
    } == {"x", "y"}
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _, first = prepare_motion_config(root / "run.ini", a, 201, 0, True)
    _, second = prepare_motion_config(root / "run.ini", b, 201, 9, True)
    assert first == second and first["motion_start_s"] == 200


def test_parallel_reference_moves_each_controlled_peer_while_legacy_is_sequential():
    c = {
        "max_controlled_nodes": 2,
        "node_ids": ["a", "b"],
        "slot_node_ids": ["a", "b"],
        "slot_speed_mps": [2, 2],
        "decision_interval_s": 1,
    }
    env = SimpleNamespace(
        _protocol=SimpleNamespace(
            facts={
                "nodes": [[0, 0, 0], [0, 20, 0]],
                "node_available": [True, True],
                "mission_state": {"time_s": 1},
            }
        )
    )
    ref = {
        "node_order": ["a", "b"],
        "waypoints": {"a": [[10, 0]], "b": [[10, 20]]},
        "start_after_failure": False,
    }
    mask = np.ones(10, dtype=bool)
    policy = ScriptedMissionPolicy(env, ref)
    policy.start_episode(201)
    assert policy.act(None, mask, c).tolist() == [1, 4]
    policy = ScriptedMissionPolicy(env, {**ref, "parallel": True})
    policy.start_episode(201)
    assert policy.act(None, mask, c).tolist() == [1, 1]


def test_new_scenarios_have_fixed_anchor_early_failure_and_far_investigation():
    import configparser
    import math

    root = find_mesh_root() / "inputs/custom/10-23"
    for env in ["rural", "urban"]:
        c = configparser.ConfigParser()
        c.read(root / (env + "-coverage-small") / "run.ini")
        assert (
            c["rl"]["controlled_nodes"] == "drone-1,vehicle-1"
            and c["rl"]["max_controlled_nodes"] == "2"
        )
        for mission in ["coverage", "investigation", "recovery", "jamming"]:
            folder = root / (env + "-" + mission + "-small")
            nodes = json.loads((folder / "nodes.json").read_text())
            assert len(nodes) == 3 and all(n["role"] == "peer" for n in nodes)
            ref = json.loads((folder / "reference.json").read_text())
            assert ref["parallel"]
            if mission == "investigation":
                assert all(
                    math.dist([n["position"]["x"], n["position"]["y"]], [345, 300])
                    > 350
                    for n in nodes
                )
            if mission == "recovery":
                assert (
                    next(n for n in nodes if n["id"] == "drone-1")["failure_at_s"] == 10
                )
                ini = configparser.ConfigParser()
                ini.read(folder / "run.ini")
                assert ini.getfloat("mission", "recovery_coverage_ratio") == 0


def test_jammer_stays_on_through_final_sample_without_cli_truncation(
    tmp_path, monkeypatch
):
    from scripts.rl.env.episode import EpisodeSession
    from scripts.rl.env.jammer_motion import emission_onset
    import configparser

    captured = []

    class NoProcess(Exception):
        pass

    def capture(command, **kwargs):
        captured.append(command)
        raise NoProcess()

    monkeypatch.setattr("scripts.rl.env.episode.subprocess.Popen", capture)
    source = find_mesh_root() / "inputs/custom/10-23/urban-jamming-small/run.ini"
    session = EpisodeSession("not-executed", str(source), tmp_path / "episodes", None)
    try:
        with pytest.raises(NoProcess):
            session.start(201, "eval")
    finally:
        if session._stderr_file:
            session._stderr_file.close()
    command = captured[0]
    assert not any(a.startswith("--jammer-onset-s=") for a in command)
    resolved = Path(
        next(a.split("=", 1)[1] for a in command if a.startswith("--run-config="))
    )
    ini = configparser.ConfigParser()
    ini.read(resolved)
    j = json.loads(Path(ini["scenario"]["jammers_file"]).read_text())[0]
    assert j["intervals"][0]["start"] == 200 and j["intervals"][0]["end"] == 600.5
    assert emission_onset(session.manifest) == 200
    assert emission_onset({"command": ["--jammer-onset-s=180"]}) == 180
    assert (
        emission_onset(
            {"jammer_motion": {"profile": "sweep_v1", "motion_start_s": 100}}
        )
        is None
    )
