"""Behavior checks preserved from the experiment pilots; no native simulation."""

import copy, json, subprocess
from pathlib import Path
import numpy as np
import pytest
from scripts.rl.env.rewards import RewardComposer
from scripts.rl.env.observations import get_preset
from scripts.rl.env.observations import observation_schema

ROOT = Path(__file__).resolve().parents[4]
INPUT = ROOT / "inputs/custom/10-23-3"


@pytest.fixture(autouse=True)
def no_processes(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("No simulator, fake process, build or optimizer may run")

    monkeypatch.setattr(subprocess, "Popen", deny)


def saved_episode(mission="investigation", policy="frozen_deterministic"):
    root = ROOT / "outputs/custom/10-23-2"
    source = root / "main" / f"urban-{mission}-3-peers" / "phase_three_report.json"
    if not source.is_file():
        pytest.skip("private recorded trajectory unavailable")
    report = json.loads(source.read_text())
    episode = next(
        e
        for e in report["variants"][0]["diagnostics"]
        if e["policy"] == policy and e["seed"] == 201
    )
    with (Path(episode["episode_dir"]) / "steps.jsonl").open() as f:
        h = json.loads(next(f))
        rows = [json.loads(x) for x in f]
    return h, rows


def value(name, facts, c, previous=None):
    q = RewardComposer([name], [1])
    inputs = (
        None
        if previous is None
        else dict(previous_nodes=previous, initial_nodes=previous, elapsed_ticks=2)
    )
    return q.compose(facts["window"], 0, c, q.context(facts, c, inputs))


def test_closeness_excludes_failed_and_forced_prefix():
    h, rows = saved_episode("recovery")
    r = next(r for r in rows if r["time_s"] == 11)
    f = copy.deepcopy(r["facts"])
    c = h["contract"]
    f["nodes"][0][:2] = [100.0, 100.0]
    f["nodes"][2][:2] = [200.0, 100.0]
    a = value("available_team_closeness_v1", f, c).total
    f["nodes"][1][:2] = [9999.0, 9999.0]
    assert value("available_team_closeness_v1", f, c).total == a
    f["nodes"][2][:2] = [110.0, 100.0]
    assert value("available_team_closeness_v1", f, c).total > a
    f["deployment"]["active"] = False
    assert value("available_team_closeness_v1", f, c).total == 0


def test_demanded_margin_uses_relays_not_unrelated_pairs():
    h, rows = saved_episode("jamming")
    f = copy.deepcopy(next(r for r in rows if r["time_s"] == 200)["facts"])
    c = h["contract"]
    f["links"] = [[0, 1, 1], [0, 1, 1], [0, 1, 1]]
    f["window"]["delivered_mbps_sum"] = 0
    low = value("demanded_path_sinr_margin_v1", f, c).total
    f["links"][0][0] = 8
    f["links"][2][0] = 8
    high = value("demanded_path_sinr_margin_v1", f, c).total
    assert high > low  # relay 0--1--2 improves the 0--2 bottleneck too
    f["node_available"][1] = False
    assert value("demanded_path_sinr_margin_v1", f, c).total < high
    f["window"]["delivered_mbps_sum"] = f["window"]["demand_mbps_sum"]
    assert value("demanded_path_sinr_margin_v1", f, c).total == 1
    f["node_service"] = [[0, 0]] * 3
    v = value("demanded_path_sinr_margin_v1", f, c)
    assert v.total == 0 and not v.valid["demanded_path_sinr_margin_v1"]


def test_target_potential_telescopes_and_uses_terminal_zero():
    h, rows = saved_episode()
    c = h["contract"]
    previous = rows[0]["facts"]["nodes"]
    delta = 0
    for r in rows[1:]:
        f = r["facts"]
        a = value("target_proximity_potential_v1", f, c, previous).total
        b = value("team_target_distance_score_v1", f, c).total
        delta += 0.99 ** (r["decision"] - 1) * (a - b)
        previous = f["nodes"]
    initial = value("team_target_distance_score_v1", rows[0]["facts"], c).total
    assert delta == pytest.approx(-50 * initial, abs=1e-9)
    assert rows[-1]["facts"]["mission_state"]["done"]
    with pytest.raises(ValueError, match="previous positions"):
        value("target_proximity_potential_v1", rows[1]["facts"], c)


def test_compact_layout_bounds_and_target_sensitivity():
    h, rows = saved_episode()
    c = h["contract"]
    f = rows[0]["facts"]
    p = get_preset("mission_compact_v1")
    obs = p.build(f, c)
    assert len(obs) == len(p.feature_names(c)) == 57
    assert p.space(c).contains(obs)
    assert (
        observation_schema("mission_compact_v1", c)["sha256"] != h["observation_schema"]["sha256"]
    )
    altered = copy.deepcopy(c)
    altered["mission"]["goal_x"] -= 30
    changed = p.build(f, altered)
    assert not np.array_equal(changed, obs)
    names = p.feature_names(c)
    assert all(
        changed[names.index("node." + node + ".goal_dx")]
        < obs[names.index("node." + node + ".goal_dx")]
        for node in c["node_ids"]
    )
    assert not any("jammer" in name or "future" in name for name in names)
    assert len(set(names)) == len(names)


def test_historical_observation_hashes_unchanged():
    import hashlib

    for mission in ["investigation", "recovery", "jamming"]:
        h, rows = saved_episode(mission)
        p = get_preset(
            h["selection"]["observation_preset"], h["selection"]["observation_parameters"]
        )
        for r in rows[::100]:
            assert (
                hashlib.sha256(p.build(r["facts"], h["contract"]).tobytes()).hexdigest()
                == r["obs_sha256"]
            )
