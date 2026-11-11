"""Behavior checks preserved from the experiment pilots; no native simulation."""

import copy
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from scripts.rl.env.state.coordination import CoordinationState
from scripts.rl.env.state.measurements import lower_tail
from scripts.rl.env.state.measurements import isolation
from scripts.rl.env.state.extensions import make_extensions
from scripts.rl.env.observations import get_preset
from scripts.rl.env.observations import observation_schema
from scripts.rl.env.rewards import RewardComposer
from scripts.rl.env.rewards.coordination import decomposition
from scripts.rl.env.selection import resolve_selection
from scripts.rl.policy.mission_metrics import read_episode
from scripts.rl.policy.reward_audit import reconstruct_coordinated as reconstruct

ROOT = Path(__file__).resolve().parents[4]
INPUT = ROOT / "inputs/custom/10-23-5"


@pytest.fixture(autouse=True)
def no_process(monkeypatch):
    def deny(*a, **kw):
        raise AssertionError("No simulator, fake process, build or optimizer allowed")

    monkeypatch.setattr(subprocess, "Popen", deny)


@pytest.fixture(scope="module")
def plan():
    path = INPUT / "phase-six.json"
    if not path.exists():
        pytest.skip("private saved-data fixture unavailable")
    return json.loads(path.read_text())


def saved(mission="investigation", peers=3):
    p = (
        ROOT
        / "outputs/custom/10-23-4/main"
        / f"urban-{mission}-{peers}-peers/phase_five_report.json"
    )
    if not p.is_file():
        pytest.skip("private recorded trajectory unavailable")
    c = json.loads(p.read_text())
    return read_episode(c["variants"][0]["diagnostics"][0]["episode_dir"])


def configured(plan, mission="investigation", peers=3, key="adaptive-aware"):
    c = next(c for c in plan["cases"] if c["name"] == f"urban-{mission}-{peers}-peers")
    a = next(a for a in c["variants"] if a["key"] == key)
    s = resolve_selection(str(INPUT / a["configs"]["101"]))
    q = RewardComposer(s.reward_components, s.reward_weights, s.reward_parameters)
    return c, a, s, q


@pytest.mark.parametrize("peers,width", [(3, 102), (6, 216), (9, 357)])
def test_explicit_observation_layout_goal_and_feedback(plan, peers, width):
    h, rows = saved(peers=peers)
    c, a, s, q = configured(plan, peers=peers)
    f = copy.deepcopy(rows[0]["facts"])
    preset = get_preset(s.observation_preset, s.observation_parameters)
    state = make_extensions(preset, q)[0]
    state.advance(f, h["contract"], 0)
    obs = preset.build(f, h["contract"])
    names = preset.feature_names(h["contract"])
    assert (
        len(obs) == len(names) == width
        and len(set(names)) == width
        and preset.space(h["contract"]).contains(obs)
    )
    assert not any("future" in name or "jammer_position" in name for name in names)
    i = names.index("node.ground-1.target_closeness")
    old = obs[i]
    f["nodes"][0][:2] = [345.0, 300.0]
    f["safety"]["peer_rejected_slots"] = [0]
    state.advance(f, h["contract"], 1, [1] * peers)
    changed = preset.build(f, h["contract"])
    assert changed[i] > old and changed[names.index("node.ground-1.inside_target")] == 1
    assert (
        changed[names.index("node.ground-1.peer_blocked")] == 1
        and changed[names.index("node.ground-1.last_east")] == 1
    )
    assert (
        observation_schema(s.observation_preset, h["contract"])["sha256"]
        != h["observation_schema"]["sha256"]
    )


def test_stage_dwell_hysteresis_relapse_reset_and_forced_prefix():
    h, rows = saved("recovery")
    c = h["contract"]
    f = copy.deepcopy(rows[11]["facts"])
    f["window"]["delivered_mbps_sum"] = f["window"]["demand_mbps_sum"]
    f["mission"]["survivor_delivered_mbps_sum"] = f["mission"][
        "survivor_demand_mbps_sum"
    ]
    f["mission"]["survivor_node_service"] = [
        [d, d] for d, v in f["mission"]["survivor_node_service"]
    ]
    state = CoordinationState({"mission_code": 2})
    for time in range(31):
        state.advance(f, c, float(time), [4] * 3)
    assert f["coordination_v1"]["stage"] == 2
    f["mission"]["survivor_delivered_mbps_sum"] *= 0.84
    f["mission"]["survivor_node_service"] = [
        [d, 0.75 * d] for d, v in f["mission"]["survivor_node_service"]
    ]
    for time in range(31, 35):
        state.advance(f, c, float(time), [4] * 3)
        assert f["coordination_v1"]["stage"] == 2
    state.advance(f, c, 35.0, [4] * 3)
    assert f["coordination_v1"]["stage"] == 0
    reset = CoordinationState({"mission_code": 2})
    reset.advance(f, c, 0)
    assert f["coordination_v1"]["good_s"] == 0
    f["deployment"]["active"] = False
    reset.advance(f, c, 1)
    assert not f["coordination_v1"]["eligible"]
    with pytest.raises(ValueError, match="increasing"):
        reset.advance(f, c, 1)


def test_investigation_arrival_connectivity_and_departure():
    h, rows = saved()
    c = h["contract"]
    f = copy.deepcopy(rows[0]["facts"])
    state = CoordinationState({"mission_code": 1})
    for n in f["nodes"]:
        n[:2] = [345.0, 300.0]
    f["mission_state"]["team_connected"] = True
    state.advance(f, c, 0)
    assert f["coordination_v1"]["stage"] == 1
    for time in range(1, 31):
        state.advance(f, c, float(time), [4] * 3)
    assert f["coordination_v1"]["stage"] == 2
    f["nodes"][0][0] += 61
    state.advance(f, c, 31, [1] * 3)
    assert f["coordination_v1"]["stage"] == 0


def test_lower_tail_and_isolation_do_not_average_away_abandoned_peer():
    assert lower_tail([0, 1, 1]) == 0 and lower_tail([0, 0, 0, 1, 1, 1, 1, 1, 1]) == 0
    assert isolation([[0, 0], [100, 0], [200, 0]]) == pytest.approx(2 / 3)
    assert isolation([[0, 0], [5, 0], [400, 0]]) == 1


@pytest.mark.parametrize(
    "mission", ["recovery", "jamming", "coverage", "investigation"]
)
def test_saved_path_reconstruction_decomposition_and_terminal_potential(plan, mission):
    h, rows = saved(mission)
    c, a, s, q = configured(plan, mission=mission)
    selection = s.describe()
    preset = get_preset(s.observation_preset, s.observation_parameters)
    ext = make_extensions(preset, q)[0]
    total = 0.0
    initial = None
    for r in rows:
        f = copy.deepcopy(r["facts"])
        ext.advance(f, h["contract"], r["time_s"], r["action_sent"])
        if initial is None:
            initial = f["coordination_v1"]["terms"]["Q"]
        assert f["coordination_v1"]["mission"] == mission
        if r["decision"]:
            t, w = decomposition(
                f, h["contract"], q.parameters[a["components"][0]], True
            )
            score = q.compose(
                f["window"], 0, h["contract"], q.context(f, h["contract"])
            )
            if score.valid[a["components"][0]]:
                assert score.total == pytest.approx(sum(t[k] * v for k, v in w.items()))
            if mission == "investigation":
                total += 0.99 ** (r["decision"] - 1) * t["progress"]
        assert preset.space(h["contract"]).contains(preset.build(f, h["contract"]))
    if mission == "investigation":
        assert total == pytest.approx(-10 * initial, abs=1e-8)
    result = reconstruct(h, rows, selection)
    assert sum(result["stage_decisions"].values()) > 0


def test_old_observation_hashes_and_fact_extensions_are_opt_in():
    from scripts.rl.env.recording.telemetry import obs_sha256

    h, rows = saved()
    p = get_preset(
        h["selection"]["observation_preset"], h["selection"]["observation_parameters"]
    )
    q = RewardComposer(
        h["selection"]["reward_components"],
        h["selection"]["reward_weights"],
        h["selection"]["reward_parameters"],
    )
    assert make_extensions(p, q) == []
    for r in rows[::100]:
        assert obs_sha256(p.build(r["facts"], h["contract"])) == r["obs_sha256"]


def test_live_env_mission_hook_uses_current_action_without_native_changes(plan):
    from scripts.rl.env.mesh_env import MeshRlEnv
    from scripts.rl.env.state.mission import MissionState

    h, rows = saved()
    c, a, s, q = configured(plan)
    env = object.__new__(MeshRlEnv)
    env._contract = h["contract"]
    env._mission_state = MissionState()
    env._fact_extensions = make_extensions(
        get_preset(s.observation_preset, s.observation_parameters), q
    )
    for r in rows[:3]:
        raw = copy.deepcopy(r["facts"])
        raw.pop("mission_state")
        before = copy.deepcopy(raw)
        env._protocol = SimpleNamespace(
            facts=raw, mask=np.asarray(r["mask"], dtype=bool)
        )
        env._advance_mission(
            dict(time_s=r["time_s"], done=r["facts"]["mission_state"]["done"]),
            r["action_sent"],
        )
        assert all(raw[k] == value for k, value in before.items())
        assert (
            raw["coordination_v1"]["previous_action"] == r["action_sent"]
            if r["action_sent"] is not None
            else raw["coordination_v1"]["previous_action"] == [None] * 3
        )


def test_new_telemetry_replays_and_independent_state_audit_rejects_tampering(
    plan, tmp_path
):
    from scripts.rl.env.recording.telemetry import replay_file
    from scripts.rl.env.recording.telemetry import make_record
    from scripts.rl.env.rewards import reward_schema

    h, rows = saved()
    c, a, s, q = configured(plan)
    preset = get_preset(s.observation_preset, s.observation_parameters)
    ext = make_extensions(preset, q)[0]
    records = []
    header = copy.deepcopy(h)
    header["selection"] = s.describe()
    header["observation_schema"] = observation_schema(
        s.observation_preset, h["contract"], s.observation_parameters
    )
    header["reward_schema"] = reward_schema(
        s.reward_components,
        s.reward_weights,
        contract=h["contract"],
        parameters=s.reward_parameters,
    )
    for r in rows:
        f = copy.deepcopy(r["facts"])
        ext.advance(f, h["contract"], r["time_s"], r["action_sent"])
        obs = preset.build(f, h["contract"])
        reward = (
            q.compose(
                f["window"],
                r["legacy_reward"],
                h["contract"],
                q.context(f, h["contract"]),
            )
            if r["decision"]
            else None
        )
        records.append(
            make_record(
                r["decision"],
                r["tick"],
                r["time_s"],
                r["ticks_in_step"],
                r["action_sent"],
                r["mask"],
                r["revalidated_slots"],
                f,
                r["legacy_reward"],
                reward,
                obs,
            )
        )
    path = tmp_path / "steps.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in [header, *records]))
    result = replay_file(path)
    assert (
        result.records == 601 and result.obs_mismatches == result.reward_mismatches == 0
    )
    reconstruct(header, records, verify=True)
    records[100]["facts"]["coordination_v1"]["good_s"] += 1
    with pytest.raises(ValueError, match="history mismatch"):
        reconstruct(header, records, verify=True)
