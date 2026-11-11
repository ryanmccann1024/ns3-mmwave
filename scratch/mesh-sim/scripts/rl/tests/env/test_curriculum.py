"""Investigation curriculum, start placement, and reset accounting."""

import copy
import hashlib
import json
from types import SimpleNamespace
import pytest
from scripts.rl.env import curriculum as curriculum_module
from scripts.rl.env.curriculum import (
    CurriculumEnv,
    load_curriculum_schedule,
    starts_from_reference,
    validate_positions,
)
from scripts.sim_support import find_mesh_root


MESH_ROOT = find_mesh_root()


def _nodes(points, types=("drone", "vehicle", "pedestrian")):
    return [
        dict(id=f"n{i}", role="peer", node_type=t, position=dict(zip("xyz", p)))
        for i, (t, p) in enumerate(zip(types, points))
    ]


def test_validate_positions_rejects_violations():
    buildings = [
        {
            "bounds": {
                "x_min": 100,
                "x_max": 120,
                "y_min": 100,
                "y_max": 120,
                "z_min": 0,
                "z_max": 30,
            }
        }
    ]
    nodes = _nodes([(300, 280, 20.0), (310, 290, 1.5), (330, 300, 1.5)])
    assert validate_positions(nodes, buildings)["minimum_separation_m"] >= 5
    for change, message in (
        (lambda n: n[0]["position"].update(z=1.5), "altitude"),
        (lambda n: n[1]["position"].update(x=401), "bounds"),
        (lambda n: n[1]["position"].update(x=99, y=110), "building clearance"),
        (lambda n: n[2]["position"].update(x=311, y=291), "peer separation"),
        (lambda n: n[0].update(role="relay"), "peer types"),
    ):
        bad = copy.deepcopy(nodes)
        change(bad)
        with pytest.raises(ValueError, match=message):
            validate_positions(bad, buildings)


def test_starts_from_reference_expected_values():
    nodes = _nodes([(0, 0, 20.0), (10, 0, 1.5), (20, 0, 1.5)])
    header = {"contract": {"node_ids": [n["id"] for n in nodes]}}
    rows = []
    for t, distance in enumerate((400, 250, 200, 150, 110, 80)):
        x = 345 - distance
        rows.append(
            {
                "time_s": float(t),
                "facts": {
                    "node_available": [True, True, t != 1],
                    "nodes": [[x, 300, 20.0], [x + 6, 300, 1.5], [x + 12, 300, 1.5]],
                },
            }
        )
    result = starts_from_reference(header, rows, nodes, [])
    assert result["near"]["evidence"]["reference_time_s"] == 4.0
    assert result["intermediate"]["evidence"]["reference_time_s"] == 2.0
    with pytest.raises(ValueError, match="node order"):
        starts_from_reference({"contract": {"node_ids": ["x"]}}, rows, nodes, [])


def test_pinned_curriculum_frames_validate_pinned_frames():
    cases = sorted(
        (MESH_ROOT / "inputs/custom/10-23-6").glob("*/curriculum/evidence.json")
    )
    if not cases:
        pytest.skip("local 10-23-6 curriculum inputs unavailable")
    for evidence in cases:
        case = evidence.parent.parent
        buildings = json.loads((case / "buildings.json").read_text())
        for stage, limit in (("near", 120), ("intermediate", 210)):
            nodes = json.loads((evidence.parent / stage / "nodes.json").read_text())
            check = validate_positions(nodes, buildings)
            assert validate_positions(nodes, buildings)["minimum_separation_m"] >= 5
            assert (
                check["minimum_separation_m"] >= 5
                and check["furthest_target_distance_m"] <= limit
            )


def _stub_curriculum(tmp_path, monkeypatch):
    from scripts.rl.env.mesh_env import MeshRlEnv

    env = object.__new__(CurriculumEnv)
    env.schedule = {s: tmp_path / s for s in ("near", "intermediate", "original")}
    env.completed_episodes = 0
    env.reset_records = []
    env._session = SimpleNamespace(_episode_dir=tmp_path)
    env._protocol = SimpleNamespace(facts={"nodes": [[0, 0, 1.5]]})
    env._output_dir = tmp_path
    monkeypatch.setattr(MeshRlEnv, "reset", lambda *a, **k: ("observation", {}))
    monkeypatch.setattr(
        MeshRlEnv, "step", lambda *a, **k: ("observation", 0, True, False, {})
    )
    monkeypatch.setattr(
        curriculum_module, "read_scenario_identity", lambda p: {"config": p}
    )
    return env


def test_curriculum_counts_completed_episodes_not_probe_resets(tmp_path, monkeypatch):
    env = _stub_curriculum(tmp_path, monkeypatch)
    monkeypatch.setattr(env, "_write_schedule", lambda: None)
    env.reset()
    env.reset()  # initial space probe and learner reset both stay near
    assert env.completed_episodes == 0
    for _ in range(25):
        env.step([4])
        env.reset()
    assert [r["stage"] for r in env.reset_records if r["completed"]] == ["near"] * 5 + [
        "intermediate"
    ] * 5 + ["original"] * 15
    assert env.stage() == "original"
    assert env._run_config == str(tmp_path / "original") == env._session._run_config


def test_curriculum_schedule_file_records_stage_hashes(tmp_path, monkeypatch):
    for stage in ("near", "intermediate", "original"):
        (tmp_path / stage).write_text(stage)
    env = _stub_curriculum(tmp_path, monkeypatch)
    env.reset()
    env.step([4])
    written = json.loads((tmp_path / "curriculum.json").read_text())
    assert written["curriculum_version"] == 1
    assert [(s["stage"], s["completed_episodes"]) for s in written["schedule"]] == [
        ("near", 5),
        ("intermediate", 5),
        ("original", 15),
    ]
    assert (
        written["schedule"][0]["config_sha256"] == hashlib.sha256(b"near").hexdigest()
    )
    assert (
        written["resets"][0]["completed"] is True
        and written["resets"][0]["stage"] == "near"
    )


def test_load_curriculum_schedule_hashes_and_validates(tmp_path):
    for stage in ("near", "intermediate"):
        (tmp_path / stage).mkdir()
        (tmp_path / stage / "run.ini").write_text(f"[scenario]\nname = {stage}\n")
    (tmp_path / "run.ini").write_text("[scenario]\nname = original\n")
    mapping = {
        "near": "near/run.ini",
        "intermediate": "intermediate/run.ini",
        "original": str(tmp_path / "run.ini"),
    }
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps(mapping))
    loaded = load_curriculum_schedule(path)
    assert loaded["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert loaded["schedule"] == {
        "near": tmp_path / "near/run.ini",
        "intermediate": tmp_path / "intermediate/run.ini",
        "original": tmp_path / "run.ini",
    }
    assert (
        loaded["config_sha256"]["near"]
        == hashlib.sha256(b"[scenario]\nname = near\n").hexdigest()
    )
    wrapped = tmp_path / "variant.json"
    wrapped.write_text(json.dumps({"curriculum_configs": mapping, "key": "x"}))
    assert load_curriculum_schedule(wrapped)["schedule"] == loaded["schedule"]
    for bad, message in (
        ({k: v for k, v in mapping.items() if k != "near"}, "exactly"),
        ({**mapping, "far": "run.ini"}, "exactly"),
        ({**mapping, "near": "missing.ini"}, "not found"),
        ({**mapping, "near": 3}, "must name"),
    ):
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError, match=message):
            load_curriculum_schedule(path)
