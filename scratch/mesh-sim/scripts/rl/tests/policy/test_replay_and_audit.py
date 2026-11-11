"""Saved-action replay, reward audit, and check results."""

import copy
import json
from pathlib import Path
import pytest
from scripts.rl.policy import operation
from scripts.rl.policy.operation import run_operation
from scripts.rl.policy.replay_gate import (
    ReplayPolicy,
    compare_rows,
    compare_rows_pre_contact_source,
    gate_passed,
    run_replay_gate,
)
from scripts.rl.policy.reward_audit import AUDIT_METHODS, audit_episode, reconstruct
from scripts.rl.tests.support.operation import CASE, trained_policy as trained_policy

pytest.importorskip("sb3_contrib")


def rows(n=3):
    return [
        dict(
            decision=i,
            facts={
                "window": {"scored_ticks": 2},
                "nodes": [[1.0 * i, 0.0, 0.0]],
                "safety": {"boundary_contacted_slots": []},
            },
            mask=[True] * 5,
            obs_sha256=f"obs-{i}",
            action_sent=[4],
        )
        for i in range(n)
    ]


@pytest.mark.parametrize("field", ["fact", "mask", "obs"])
def test_replay_comparison_stops_on_changed_fact_mask_or_observation(field):
    before = rows()
    compare_rows(before, copy.deepcopy(before), "case")
    after = copy.deepcopy(before)
    if field == "fact":
        after[2]["facts"]["nodes"][0][0] += 1e-6
    elif field == "mask":
        after[2]["mask"][1] = False
    else:
        after[2]["obs_sha256"] = "changed"
    with pytest.raises(ValueError, match="decision 2"):
        compare_rows(before, after, "case")
    with pytest.raises(ValueError, match="decision count"):
        compare_rows(before, before[:2], "case")


def test_replay_pre_contact_variant_ignores_only_the_new_contact_field():
    before = rows()
    for row in before:
        del row["facts"]["safety"]["boundary_contacted_slots"]
    after = rows()
    compare_rows_pre_contact_source(before, after, "case")
    with pytest.raises(ValueError):
        compare_rows(before, after, "case")
    after[1]["facts"]["window"]["scored_ticks"] = 1
    with pytest.raises(ValueError, match="decision 1"):
        compare_rows_pre_contact_source(before, after, "case")


def test_replay_policy_refuses_newly_masked_action():
    policy = ReplayPolicy(rows())
    assert list(policy.act(None, [True] * 5, {})) == [4]
    with pytest.raises(ValueError, match="mask changed"):
        policy.act(None, [True] * 4 + [False], {})


def test_reward_audit_methods_are_separately_named():
    assert set(AUDIT_METHODS) == {
        "position_replay_v1",
        "coordinated_v1",
        "team_radio_v1",
    }
    with pytest.raises(ValueError, match="unknown reward audit"):
        reconstruct("phase6", {}, [])


def test_position_replay_reconstructs_and_detects_tampering():
    c = {
        "node_ids": ["a"],
        "slot_node_ids": ["a"],
        "slot_speed_mps": [2.0],
        "tick_s": 0.5,
        "warmup_s": 0,
        "reward_warmup": "exclude",
        "coverage": {},
    }
    selection = {
        "reward_components": [
            "connected_outdoor_area_fraction_v1",
            "available_peer_travel_fraction_v1",
        ],
        "reward_weights": [1, -0.05],
    }
    saved = [
        dict(
            decision=i,
            time_s=i,
            ticks_in_step=2,
            legacy_reward=0,
            reward={"total": 0.75 - 0.05},
            facts={
                "nodes": [[2 * i, 0]],
                "node_available": [True],
                "coverage": {"fraction": 0.75},
                "window": {"scored_ticks": 2},
            },
        )
        for i in range(601)
    ]
    header = {"selection": selection, "contract": c}
    assert reconstruct("position_replay_v1", header, saved, verify=True)[
        "return_"
    ] == pytest.approx(420.0)
    saved[-1]["reward"]["total"] = 0.75
    with pytest.raises(ValueError, match="replay"):
        reconstruct("position_replay_v1", header, saved, verify=True)


def test_replay_gate_passes_identical_physics_and_stops_on_change(
    trained, sim_binary, tmp_path
):
    bundle, config = trained
    source = run_operation(
        bundle,
        {"11": config},
        CASE,
        "frozen_deterministic",
        11,
        "diagnostic",
        tmp_path / "source",
        sim_binary,
    )
    episode = tmp_path / "source" / source["evaluation"]["episode_dir"]
    record = run_replay_gate(
        episode, {"11": config}, CASE, 11, tmp_path / "gate", sim_binary, bundle=bundle
    )
    assert record["status"] == "passed" and gate_passed(tmp_path / "gate")
    assert not Path(record["episode_dir"]).is_absolute()
    lines = (episode / "steps.jsonl").read_text().splitlines()
    tampered = json.loads(lines[-1])
    tampered["obs_sha256"] = "0" * 64
    copy_dir = tmp_path / "tampered"
    copy_dir.mkdir()
    (copy_dir / "steps.jsonl").write_text(
        "\n".join(lines[:-1] + [json.dumps(tampered)]) + "\n"
    )
    with pytest.raises(ValueError, match="changed"):
        run_replay_gate(
            copy_dir,
            {"11": config},
            CASE,
            11,
            tmp_path / "gate2",
            sim_binary,
            bundle=bundle,
        )
    assert not gate_passed(tmp_path / "gate2")
    assert (
        json.loads((tmp_path / "gate2/replay_gate.json").read_text())["status"]
        == "failed"
    )


def test_reward_audit_recomputes_only_for_matching_identities(
    trained, sim_binary, tmp_path
):
    bundle, config = trained
    source = run_operation(
        bundle,
        {"11": config},
        CASE,
        "frozen_deterministic",
        11,
        "diagnostic",
        tmp_path / "source",
        sim_binary,
    )
    episode = tmp_path / "source" / source["evaluation"]["episode_dir"]
    header = json.loads((episode / "steps.jsonl").read_text().splitlines()[0])
    reward = header["reward_schema"]["sha256"]
    with pytest.raises(ValueError, match="reward schema"):
        audit_episode(
            episode, "position_replay_v1", reward_schema_sha256="other", seed=11
        )
    with pytest.raises(ValueError, match="seed"):
        audit_episode(
            episode, "position_replay_v1", reward_schema_sha256=reward, seed=12
        )
    with pytest.raises(ValueError, match="observation schema"):
        audit_episode(
            episode,
            "position_replay_v1",
            reward_schema_sha256=reward,
            seed=11,
            observation_schema_sha256="other",
        )
    with pytest.raises(
        ValueError, match="replay|600"
    ):  # identities match, so replay is attempted
        audit_episode(
            episode, "position_replay_v1", reward_schema_sha256=reward, seed=11
        )


def test_check_result_passed_truth_table(tmp_path):
    def result(name, **changes):
        directory = tmp_path / name
        operation.write_check_result(
            directory,
            check_id="c",
            kind="reward_audit",
            passed=True,
            evidence={},
            warnings=[],
        )
        record = json.loads((directory / "check_result.json").read_text())
        record.update(changes)
        (directory / "check_result.json").write_text(json.dumps(record))
        return directory

    assert operation.check_result_passed(result("ok"))
    assert not operation.check_result_passed(tmp_path / "missing")
    assert not operation.check_result_passed(
        result("failed", passed=False, status="failed")
    )
    assert not operation.check_result_passed(result("mixed", status="failed"))
    assert not operation.check_result_passed(result("version", check_result_version=2))
    assert not operation.check_result_passed(result("kind", kind="other"))
    assert not operation.check_result_passed(result("evidence", evidence=None))
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "check_result.json").write_text("{not json")
    assert not operation.check_result_passed(broken)
    gate = result("gate", kind="replay_gate")
    assert not operation.check_result_passed(
        gate
    )  # passed result without a passed replay_gate.json
    (gate / "replay_gate.json").write_text(
        json.dumps({"replay_gate_version": 1, "status": "passed", "matched": True})
    )
    assert operation.check_result_passed(gate)
    with pytest.raises(ValueError):
        operation.write_check_result(
            tmp_path / "x",
            check_id="c",
            kind="audit",
            passed=True,
            evidence={},
            warnings=[],
        )


def test_replay_parent_contact_and_jammer_checks(
    trained, sim_binary, tmp_path, monkeypatch
):
    bundle, config = trained
    source = run_operation(
        bundle,
        {"11": config},
        CASE,
        "frozen_deterministic",
        11,
        "diagnostic",
        tmp_path / "replay-source",
        sim_binary,
    )
    episode = tmp_path / "replay-source" / source["evaluation"]["episode_dir"]
    legacy = tmp_path / "pre-contact"
    legacy.mkdir()
    saved = [
        json.loads(line) for line in (episode / "steps.jsonl").read_text().splitlines()
    ]
    for row in saved:
        if "facts" in row:
            row["facts"]["safety"].pop("boundary_contacted_slots", None)
    (legacy / "steps.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in saved)
    )
    from scripts.rl.policy import mission_metrics

    original_read = mission_metrics.read_episode

    def current_native_telemetry(directory):
        header, rows = original_read(directory)
        for row in rows:
            row["facts"].setdefault(
                "node_available", [True] * len(header["contract"]["node_ids"])
            )
        if Path(directory) != legacy:
            for row in rows:
                row["facts"]["safety"]["boundary_contacted_slots"] = []
        return header, rows

    monkeypatch.setattr(mission_metrics, "read_episode", current_native_telemetry)
    with pytest.raises(ValueError, match="changed"):
        run_replay_gate(
            legacy,
            {"11": config},
            CASE,
            11,
            tmp_path / "strict",
            sim_binary,
            bundle=bundle,
        )
    record = run_replay_gate(
        legacy,
        {"11": config},
        CASE,
        11,
        tmp_path / "pre-contact-gate",
        sim_binary,
        bundle=bundle,
        comparison="pre_contact_source_v1",
        contact_audit=True,
    )
    assert record["boundary"]["available"] and record["compatibility"]
    assert record["parent"]["model_sha256"] == bundle.model_sha256
    from scripts.rl.scenario_check import validation

    calls = []

    def timing(config, case, seed, command):
        calls.append(
            (case["mission"], seed, case["seeds"][str(seed)]["gate_s"], command)
        )
        return {"event_timing_version": 1, "command_checked": True}

    monkeypatch.setattr(validation, "jammer_timing", timing)
    case = {"mission": "jamming", "seeds": {"11": {"gate_s": 160}}}
    record = run_replay_gate(
        episode,
        {"11": config},
        case,
        11,
        tmp_path / "jam-gate",
        sim_binary,
        bundle=bundle,
    )
    assert (
        calls[0][:3] == ("jamming", 11, 160)
        and record["event_timing"]["command_checked"]
    )

    def bad_timing(*args):
        raise ValueError("jammer timing mismatch")

    monkeypatch.setattr(validation, "jammer_timing", bad_timing)
    with pytest.raises(
        (ValueError, RuntimeError), match="jammer timing mismatch|did not complete"
    ):
        run_replay_gate(
            episode,
            {"11": config},
            case,
            11,
            tmp_path / "bad-jam",
            sim_binary,
            bundle=bundle,
        )
    assert not gate_passed(tmp_path / "bad-jam")
    from scripts.rl.policy import compat

    def bad_parent(*args, **kwargs):
        raise ValueError("parent compatibility mismatch")

    monkeypatch.setattr(compat, "check_compatibility", bad_parent)
    with pytest.raises(
        (ValueError, RuntimeError),
        match="parent compatibility mismatch|did not complete",
    ):
        run_replay_gate(
            episode,
            {"11": config},
            CASE,
            11,
            tmp_path / "bad-parent",
            sim_binary,
            bundle=bundle,
        )
    assert not gate_passed(tmp_path / "bad-parent")
