"""Frozen operations, schedules, replay gate, reward-audit identity and seeded operation records."""

import copy
import json
from pathlib import Path

import pytest

from scripts.rl.policy import bundle as bundles
from scripts.rl.policy import operation
from scripts.rl.policy.operation import DiagnosticEnv, resolve_gates, run_operation
from scripts.rl.policy.replay_gate import (
    ReplayPolicy,
    compare_rows,
    compare_rows_pre_contact_source,
    gate_passed,
    run_replay_gate,
)
from scripts.rl.policy.reward_audit import AUDIT_METHODS, audit_episode, reconstruct
from scripts.rl.policy.schedules import (
    COVERAGE_RULES,
    COVERAGE_SCHEDULE_VERSION,
    CoverageSchedule,
    CoverageSchedulePolicy,
    SamplingSchedule,
    schedule_metadata,
    validate_schedule,
)
from scripts.rl.tests.policy.test_online_protocols import (
    three_decision_config,
    train_run,
)

pytest.importorskip("sb3_contrib")

# The 10-23-2 escape settings, split by kind.
INITIAL = {"initial_sample_decisions": 60}
STALL = {
    "burst_decisions": 20,
    "cooldown_decisions": 40,
    "max_bursts": 3,
    "rejected_window": 20,
    "rejected_threshold": 10,
    "movement_threshold_m": 1.0,
    "progress_window": 60,
    "progress_threshold": 0.01,
}
CASE = {"mission": "coverage", "coverage_target": 0.5}


@pytest.fixture
def trained(sim_binary, multi_run_config, tmp_path, monkeypatch):
    config = three_decision_config(multi_run_config)
    run = train_run(sim_binary, config, tmp_path / "train", monkeypatch)
    return bundles.read_bundle(run, "final"), config


def absolute_paths(value, root):
    if isinstance(value, dict):
        return [p for v in value.values() for p in absolute_paths(v, root)]
    if isinstance(value, list):
        return [p for v in value for p in absolute_paths(v, root)]
    return [value] if isinstance(value, str) and value.startswith(str(root)) else []


def test_initial_sampling_exactly_n_eligible_decisions():
    schedule, flags = SamplingSchedule("initial-sampling", INITIAL), []
    for _ in range(100):
        flags.append(schedule.sampled())
        schedule.observe(0.1, False, [False], [0.0])
    assert flags == [True] * 60 + [False] * 40


def test_stall_trigger_burst_cooldown_and_limit():
    schedule, flags = SamplingSchedule("stall-burst", STALL), []
    for _ in range(260):
        flags.append(schedule.sampled())
        schedule.observe(0.1, False, [True], [0.0])
    assert (
        flags[:20] == [False] * 20
        and flags[20:40] == [True] * 20
        and flags[40:80] == [False] * 40
    )
    assert len(schedule.events) == 3 and sum(flags) == 60
    assert schedule.events[0]["reason"] == "blocked-slot-0" and all(
        "score_after" in e for e in schedule.events
    )
    good = SamplingSchedule("stall-burst", STALL)
    for _ in range(100):
        assert not good.sampled()
        good.observe(1.0, True, [False], [0.0])
    assert not good.events


def test_stall_progress_trigger_when_slots_move():
    schedule, reasons = SamplingSchedule("stall-burst", STALL), []
    for _ in range(80):
        schedule.sampled()
        schedule.observe(0.1, False, [True], [5.0])
    assert schedule.events[0]["reason"] == "mission-progress-stall"
    assert schedule.events[0]["after_eligible_decision"] == 61


@pytest.mark.parametrize(
    "kind,state",
    [("sample-then-deterministic", "deterministic"), ("sample-then-hold", "hold")],
)
def test_coverage_qualification_relapse_and_severe_loss(kind, state):
    schedule = CoverageSchedule(kind, 0.6)
    for t in range(1, 30):
        schedule.observe(t, 0.65, 0.95, 0.85)
    assert schedule.state == "sampled"
    schedule.observe(30, 0.65, 0.95, 0.85)
    assert (
        schedule.state == state
        and schedule.events[-1]["reason"] == "30 s qualification"
    )
    for t in range(31, 35):
        schedule.observe(t, 0.57, 0.95, 0.85)
    assert schedule.state == state
    schedule.observe(35, 0.57, 0.95, 0.85)
    assert (
        schedule.state == "sampled" and schedule.events[-1]["reason"] == "5 s relapse"
    )
    for t in range(36, 66):
        schedule.observe(t, 0.65, 0.95, 0.85)
    schedule.observe(66, 0.65, 0.95, 0.19)
    assert (
        schedule.state == "sampled"
        and schedule.events[-1]["reason"] == "severe service loss"
    )


def test_coverage_rules_are_the_documented_versioned_constants():
    assert COVERAGE_RULES["qualification_s"] == 30 and COVERAGE_RULES["relapse_s"] == 5
    meta = schedule_metadata(
        {"kind": "sample-then-hold", "settings": {"coverage_target": 0.6}}
    )
    assert (
        meta["schedule_version"] == COVERAGE_SCHEDULE_VERSION
        and meta["rules"] == COVERAGE_RULES
        and meta["optimizer_updates"] == 0
    )


def test_coverage_policy_uses_elapsed_scored_time(tmp_path):
    policy = CoverageSchedulePolicy(
        None, "sample-then-hold", 0.6, tmp_path, tick_s=0.25
    )
    policy.executed_state = "sampled"
    facts = {
        "window": {"scored_ticks": 2, "demand_mbps_sum": 10, "delivered_mbps_sum": 10},
        "node_service": [[10, 10]],
        "node_available": [True],
        "coverage": {"fraction": 0.8},
    }
    for decision in range(1, 60):
        policy.observe(None, 0, False, False, {"time_s": decision * 0.5}, facts)
    assert policy.schedule.state == "sampled"
    policy.observe(None, 0, False, False, {"time_s": 30.0}, facts)
    assert policy.schedule.events[-1]["time_s"] == 30.0
    assert policy.schedule.state == "hold"


@pytest.mark.parametrize(
    "schedule,match",
    [
        ({"kind": "initial-sampling", "settings": {}}, "missing"),
        (
            {"kind": "initial-sampling", "settings": {**INITIAL, "max_bursts": 3}},
            "unexpected",
        ),
        (
            {
                "kind": "stall-burst",
                "settings": {k: v for k, v in STALL.items() if k != "progress_window"},
            },
            "missing",
        ),
        (
            {"kind": "stall-burst", "settings": {**STALL, "rejected_window": 62}},
            "rejected_window",
        ),
        (
            {"kind": "stall-burst", "settings": {**STALL, "rejected_threshold": 21}},
            "rejected_threshold",
        ),
        (
            {"kind": "stall-burst", "settings": {**STALL, "burst_decisions": 0}},
            "burst_decisions",
        ),
        ({"kind": "sample-then-hold", "settings": {}}, "missing"),
        (
            {"kind": "sample-then-hold", "settings": {"coverage_target": 1.5}},
            "coverage_target",
        ),
        ({"kind": "explore", "settings": {}}, "unknown"),
    ],
)
def test_schedule_settings_refused_without_defaults(schedule, match):
    with pytest.raises(ValueError, match=match):
        validate_schedule(schedule)


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


def test_frozen_modes_keep_parameter_and_optimizer_digests(
    trained, sim_binary, tmp_path
):
    bundle, config = trained
    for mode in ("frozen_deterministic", "frozen_sampled"):
        out = tmp_path / mode
        record = run_operation(
            bundle, {"11": config}, CASE, mode, 11, "diagnostic", out, sim_binary
        )
        assert record["status"] == "completed" and record["protocol"] == mode
        model, optimizer = record["model"], record["optimizer"]
        assert model["initial_parameter_sha256"] == model["final_parameter_sha256"]
        assert (
            optimizer["initial_optimizer_sha256"] == optimizer["final_optimizer_sha256"]
        )
        assert (
            record["accounting"]["optimizer_steps"] == 0
            and model["adapted_model"] is None
        )
        audit = json.loads((out / "weight_audit.json").read_text())
        assert audit["final_optimizer_sha256"] == optimizer["initial_optimizer_sha256"]
        assert (
            json.loads((out / "eval_manifest.json").read_text())["status"]
            == "completed"
        )
        assert (out / "online_manifest.json").exists() == (mode == "frozen_sampled")
        assert not absolute_paths(
            {k: v for k, v in record.items() if k not in ("parent", "run_config")}, out
        )
        assert (out / record["evaluation"]["episode_dir"] / "steps.jsonl").is_file()


def test_frozen_operation_refuses_changed_optimizer(
    trained, sim_binary, tmp_path, monkeypatch
):
    bundle, config = trained
    calls = iter(range(100))
    monkeypatch.setattr(
        bundles, "optimizer_digest", lambda model: f"state-{next(calls)}"
    )
    with pytest.raises(RuntimeError, match="optimizer"):
        run_operation(
            bundle,
            {"11": config},
            CASE,
            "frozen_sampled",
            11,
            "diagnostic",
            tmp_path / "op",
            sim_binary,
        )
    saved = json.loads((tmp_path / "op/online_manifest.json").read_text())
    assert saved["status"] == "failed" and "optimizer" in saved["error"]


def test_scheduled_frozen_operation_logs_switches(
    sim_binary, multi_run_config, tmp_path, monkeypatch
):
    config = three_decision_config(multi_run_config)
    Path(config).write_text(Path(config).read_text() + "\n[mission]\nkind = coverage\n")
    bundle = bundles.read_bundle(
        train_run(sim_binary, config, tmp_path / "train", monkeypatch), "final"
    )
    schedule = {"kind": "sample-then-hold", "settings": {"coverage_target": 0.6}}
    out = tmp_path / "scheduled"
    record = run_operation(
        bundle,
        {"11": config},
        CASE,
        "frozen_deterministic",
        11,
        "diagnostic",
        out,
        sim_binary,
        schedule=schedule,
    )
    assert (
        record["schedule"]["kind"] == "sample-then-hold"
        and record["schedule"]["schedule_version"] == COVERAGE_SCHEDULE_VERSION
    )
    assert (
        record["model"]["initial_parameter_sha256"]
        == record["model"]["final_parameter_sha256"]
    )
    assert (
        record["optimizer"]["initial_optimizer_sha256"]
        == record["optimizer"]["final_optimizer_sha256"]
    )
    log = json.loads(
        (
            out / record["evaluation"]["episode_dir"] / "coverage_execution.json"
        ).read_text()
    )
    assert (
        log["coverage_execution_version"] == COVERAGE_SCHEDULE_VERSION
        and log["optimizer_updates"] == 0
    )
    assert [d["executed_state"] for d in log["decisions"]] == ["sampled"] * 3
    assert (out / "online_manifest.json").is_file()


def test_seeded_adapter_uses_first_declared_seed(
    trained, sim_binary, tmp_path, monkeypatch
):
    bundle, config = trained
    built = []

    class Spy(DiagnosticEnv):
        def __init__(self, *args, initial_seed, **kwargs):
            built.append(initial_seed)
            super().__init__(*args, initial_seed=initial_seed, **kwargs)

    monkeypatch.setattr(operation, "DiagnosticEnv", Spy)
    configs = {"7": config, "11": config}
    run_operation(
        bundle,
        configs,
        CASE,
        "frozen_deterministic",
        11,
        "diagnostic",
        tmp_path / "op",
        sim_binary,
        evaluation_seeds=[7, 11],
        allow_different_scenario=True,
    )
    assert built == [7]
    with pytest.raises(ValueError, match="declared evaluation seeds"):
        run_operation(
            bundle,
            configs,
            CASE,
            "frozen_deterministic",
            11,
            "diagnostic",
            tmp_path / "x",
            sim_binary,
            evaluation_seeds=[7],
        )


def test_gates_come_from_native_settings(tmp_path):
    ini = tmp_path / "run.ini"
    ini.write_text("[rl]\ncontrol_start_s = 40 # gate\n")
    plain = tmp_path / "plain.ini"
    plain.write_text("[rl]\nenabled = true\n")
    resolved = resolve_gates({"201": ini, "202": plain}, {"mission": "recovery"})
    assert resolved["seeds"] == {"201": {"gate_s": 40.0}, "202": {"gate_s": 0.0}}
    assert (
        resolve_gates({"201": ini}, {"seeds": {"201": {"gate_s": 40}}})["seeds"]["201"][
            "gate_s"
        ]
        == 40.0
    )
    with pytest.raises(ValueError, match="differs from native"):
        resolve_gates({"201": ini}, {"seeds": {"201": {"gate_s": 30}}})


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


def operate(*argv):
    from scripts.rl import operate as cli

    return cli.main([str(a) for a in argv])


def test_operate_help_and_usage_errors_exit_one(capsys):
    from scripts.rl import operate as cli

    for command in (
        [],
        ["model"],
        ["baseline"],
        ["preflight"],
        ["replay-gate"],
        ["reward-audit"],
    ):
        with pytest.raises(SystemExit) as exit_info:
            cli.main([*command, "--help"])
        assert exit_info.value.code == 0
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["model", "--mode", "frozen_greedy"])
    assert exit_info.value.code == 1


def test_model_command_dispatches_contract_arguments(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        bundles, "read_bundle", lambda run_dir, model: ("bundle", run_dir, model)
    )
    monkeypatch.setattr(
        operation, "prevalidated_scenario_difference", lambda bundle, ini, gate: True
    )

    def fake(
        bundle, configs, case, mode, seed, seed_role, output_dir, sim_binary, **kwargs
    ):
        calls.append(
            dict(
                bundle=bundle,
                configs=configs,
                case=case,
                mode=mode,
                seed=seed,
                role=seed_role,
                **kwargs,
            )
        )
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / "online_manifest.json").write_text("{}")

    monkeypatch.setattr(operation, "run_operation", fake)
    code = operate(
        "model",
        "--sim-binary",
        "B",
        "--run-dir",
        "R",
        "--model",
        "checkpoints/checkpoint_8_steps.zip",
        "--mode",
        "online_gated_v1",
        "--operation-id",
        "op-a",
        "--seed",
        201,
        "--seed-role",
        "diagnostic",
        "--run-config",
        "seed.ini",
        "--band",
        "sub-6",
        "--output-dir",
        tmp_path / "out",
        "--protocol-settings-json",
        '{"batch_size": 60, "n_steps": 120}',
        "--schedule-json",
        '{"kind": "initial-sampling", "settings": {"initial_sample_decisions": 60}}',
        "--gate-s",
        "160.0",
        "--mission",
        "jamming",
        "--coverage-target",
        ".6",
        "--decision-records",
    )
    assert code == 0
    (call,) = calls
    assert call["bundle"] == ("bundle", "R", "checkpoints/checkpoint_8_steps.zip")
    assert call["configs"] == {"201": "seed.ini"}
    assert call["case"] == {
        "mission": "jamming",
        "coverage_target": 0.6,
        "seeds": {"201": {"gate_s": 160.0}},
    }
    assert call["decision_records"].enabled
    assert (
        call["evaluation_seeds"] == [201] and call["allow_different_scenario"] is True
    )
    assert (
        call["protocol_settings"] == {"batch_size": 60, "n_steps": 120}
        and call["band"] == "sub-6"
    )
    assert call["schedule"]["kind"] == "initial-sampling" and call["label"] == "op-a"
    assert (
        operate(
            "model",
            "--sim-binary",
            "B",
            "--run-dir",
            "R",
            "--model",
            "final",
            "--mode",
            "frozen_sampled",
            "--operation-id",
            "o",
            "--seed",
            1,
            "--seed-role",
            "diagnostic",
            "--run-config",
            "x.ini",
            "--band",
            "mmwave",
            "--output-dir",
            tmp_path / "d",
            "--protocol-settings-json",
            "{}",
        )
        == 0
    )
    assert (
        calls[-1]["case"] == {}
        and calls[-1]["band"] == "mmwave"
        and not calls[-1]["decision_records"].enabled
    )


def test_baseline_and_check_commands_dispatch(tmp_path, monkeypatch):
    from scripts.rl.policy import replay_gate, reward_audit

    calls = {}

    def baseline(policy, seed, role, ini, output_dir, binary, **kwargs):
        calls["baseline"] = (policy, seed, role, ini, kwargs)
        return {
            "policies": {
                policy: {
                    "episodes": [
                        dict(
                            status="completed",
                            revalidated_slots_total=0,
                            mask_violations=1,
                        )
                    ]
                }
            }
        }

    monkeypatch.setattr(operation, "run_baseline", baseline)
    assert (
        operate(
            "baseline",
            "--sim-binary",
            "B",
            "--policy",
            "scripted",
            "--seed",
            7,
            "--seed-role",
            "diagnostic",
            "--run-config",
            "s.ini",
            "--band",
            "sub-6",
            "--output-dir",
            tmp_path / "b",
            "--reference-kind",
            "scenario_routes_v1",
            "--reference",
            "ref.json",
            "--gate-s",
            "0.0",
            "--mission",
            "recovery",
            "--decision-records",
        )
        == 2
    )
    assert calls["baseline"][:4] == ("scripted", 7, "diagnostic", "s.ini")
    kwargs = calls["baseline"][4]
    assert (
        kwargs["decision_records"].enabled
        and kwargs["band"] == "sub-6"
        and kwargs["gate_s"] == 0.0
    )
    assert kwargs["case"] == {"mission": "recovery", "seeds": {"7": {"gate_s": 0.0}}}
    assert (kwargs["reference_kind"], kwargs["reference_path"]) == (
        "scenario_routes_v1",
        "ref.json",
    )

    def gate(source, configs, case, seed, output_dir, binary, **kwargs):
        calls["gate"] = (source, configs, seed)
        calls["gate_band"] = kwargs.get("band")
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / "replay_gate.json").write_text(
            json.dumps({"replay_gate_version": 1, "status": "passed", "matched": True})
        )
        return {"seed": seed}

    monkeypatch.setattr(replay_gate, "run_replay_gate", gate)
    out = tmp_path / "gate"
    assert (
        operate(
            "replay-gate",
            "--check-id",
            "g",
            "--sim-binary",
            "B",
            "--seed-configs-json",
            '{"201": "s.ini"}',
            "--band",
            "sub-6",
            "--source",
            "ep",
            "--output-dir",
            out,
        )
        == 0
    )
    assert calls["gate"] == (
        "ep",
        {"201": "s.ini"},
        201,
    ) and operation.check_result_passed(out)
    assert calls["gate_band"] == "sub-6"
    accepted = tmp_path / "accepted"
    accepted.mkdir()
    (accepted / "eval_manifest.json").write_text(
        json.dumps(
            {
                "policies": {
                    "hold": {
                        "episodes": [
                            {
                                "seed": 201,
                                "status": "completed",
                                "episode_dir": "hold/episode-0000",
                            }
                        ]
                    }
                }
            }
        )
    )
    assert (
        operate(
            "replay-gate",
            "--check-id",
            "g",
            "--sim-binary",
            "B",
            "--seed-configs-json",
            '{"201": "s.ini"}',
            "--source",
            accepted,
            "--output-dir",
            tmp_path / "gate-accepted",
        )
        == 0
    )
    assert calls["gate"][0] == "hold/episode-0000"
    assert (
        operate(
            "replay-gate",
            "--check-id",
            "g",
            "--sim-binary",
            "B",
            "--seed-configs-json",
            '{"201": "s.ini", "202": "t.ini"}',
            "--source",
            "ep",
            "--output-dir",
            tmp_path / "two",
        )
        == 1
    )

    def audit(manifest, selection, method):
        calls["audit"] = (selection, method)
        return {"hold": {"episodes": []}}

    monkeypatch.setattr(reward_audit, "baseline_audit", audit)
    source = tmp_path / "source"
    source.mkdir()
    (source / "rl_episode.json").write_text(json.dumps({"seed": 3}))
    ini = tmp_path / "s.ini"
    ini.write_text("[rl]\n")
    out = tmp_path / "audit"
    assert (
        operate(
            "reward-audit",
            "--check-id",
            "a",
            "--source",
            source,
            "--method",
            "team_radio_v1",
            "--run-config",
            ini,
            "--observation-preset",
            "raw_links_v1",
            "--reward-components",
            "x,y",
            "--reward-weights=-1,0.5",
            "--observation-parameters",
            "{}",
            "--reward-parameters",
            '{"x": {}}',
            "--output-dir",
            out,
        )
        == 0
    )
    assert calls["audit"] == (
        dict(
            observation_preset="raw_links_v1",
            reward_components=["x", "y"],
            reward_weights=[-1.0, 0.5],
            observation_parameters={},
            reward_parameters={"x": {}},
        ),
        "team_radio_v1",
    )
    assert operation.check_result_passed(out)
    bad = tmp_path / "bad"
    assert (
        operate(
            "reward-audit",
            "--check-id",
            "a",
            "--source",
            source,
            "--method",
            "phase6",
            "--run-config",
            ini,
            "--observation-preset",
            "p",
            "--reward-components",
            "x",
            "--reward-weights",
            "1",
            "--observation-parameters",
            "{}",
            "--reward-parameters",
            "{}",
            "--output-dir",
            bad,
        )
        == 1
    )
    assert not operation.check_result_passed(bad)


def test_operate_preflight_probes_requested_native_features(
    sim_binary, multi_run_config, tmp_path
):
    config = Path(multi_run_config)
    config.write_text(
        config.read_text().replace("[rl]", "[rl]\ncoverage_enabled = true")
    )
    common = (
        "preflight",
        "--check-id",
        "p",
        "--sim-binary",
        sim_binary,
        "--seed-configs-json",
        json.dumps({"11": str(config)}),
    )
    covered = tmp_path / "covered"
    assert operate(*common, "--requirements", "coverage", "--output-dir", covered) == 0
    assert operation.check_result_passed(covered)
    record = json.loads((covered / "check_result.json").read_text())
    assert record["evidence"]["capabilities"]["coverage"]
    missing = tmp_path / "missing"
    assert (
        operate(*common, "--requirements", "peer_separation", "--output-dir", missing)
        == 1
    )
    assert json.loads((missing / "check_result.json").read_text())["evidence"][
        "missing"
    ] == ["peer_separation"]
    config.write_text(
        config.read_text().replace(
            "[rl]", "[rl]\navoid_buildings = true\nmask_building_moves = false"
        )
    )
    no_masks = tmp_path / "no-masks"
    assert (
        operate(*common, "--requirements", "building_masks", "--output-dir", no_masks)
        == 1
    )
    assert json.loads((no_masks / "check_result.json").read_text())["evidence"][
        "missing"
    ] == ["building_masks"]
    unknown = tmp_path / "unknown"
    assert operate(*common, "--requirements", "unknown", "--output-dir", unknown) == 1
    assert (
        "unknown preflight requirements"
        in json.loads((unknown / "check_result.json").read_text())["evidence"]["error"]
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


def test_operate_end_to_end_frozen_model_and_hold_baseline(
    trained, sim_binary, tmp_path
):
    bundle, config = trained
    model_out = tmp_path / "model"
    assert (
        operate(
            "model",
            "--sim-binary",
            sim_binary,
            "--run-dir",
            bundle.run_dir,
            "--model",
            "final",
            "--mode",
            "frozen_deterministic",
            "--operation-id",
            "frozen",
            "--seed",
            11,
            "--seed-role",
            "diagnostic",
            "--run-config",
            config,
            "--band",
            "sub-6",
            "--output-dir",
            model_out,
            "--protocol-settings-json",
            "{}",
        )
        == 0
    )
    manifest = json.loads((model_out / "eval_manifest.json").read_text())
    assert manifest["status"] == "completed" and manifest["seeds"] == [11]
    assert not (model_out / "online_manifest.json").exists()
    hold_out = tmp_path / "hold"
    assert (
        operate(
            "baseline",
            "--sim-binary",
            sim_binary,
            "--policy",
            "hold",
            "--seed",
            11,
            "--seed-role",
            "diagnostic",
            "--run-config",
            config,
            "--band",
            "sub-6",
            "--output-dir",
            hold_out,
        )
        == 0
    )
    hold = json.loads((hold_out / "eval_manifest.json").read_text())
    assert hold["status"] == "completed" and list(hold["policies"]) == ["hold"]
    episode = Path(hold["policies"]["hold"]["episodes"][0]["episode_dir"])
    (
        episode / "inputs"
    ).mkdir()  # the real simulator archives its run.ini; the fake does not
    (episode / "inputs/run.ini").write_text(Path(config).read_text())
    imported = tmp_path / "imported"
    assert (
        operate(
            "baseline",
            "--sim-binary",
            sim_binary,
            "--policy",
            "hold",
            "--seed",
            11,
            "--seed-role",
            "diagnostic",
            "--run-config",
            config,
            "--band",
            "sub-6",
            "--output-dir",
            imported,
            "--import-from",
            hold_out,
        )
        == 0
    )
    assert (
        operate(
            "baseline",
            "--sim-binary",
            sim_binary,
            "--policy",
            "hold",
            "--seed",
            11,
            "--seed-role",
            "diagnostic",
            "--run-config",
            config,
            "--output-dir",
            tmp_path / "other-band",
            "--import-from",
            hold_out,
        )
        == 1
    )  # run.ini default band is mmwave; the control ran sub-6
    copy_ = json.loads((imported / "eval_manifest.json").read_text())
    assert (
        copy_["imported_from"]["eval_manifest_sha256"]
        and copy_["imported_from"]["new_evaluation"] is False
    )
    assert Path(copy_["policies"]["hold"]["episodes"][0]["episode_dir"]).is_relative_to(
        imported
    )
    assert (
        operate(
            "baseline",
            "--sim-binary",
            sim_binary,
            "--policy",
            "hold",
            "--seed",
            12,
            "--seed-role",
            "diagnostic",
            "--run-config",
            config,
            "--band",
            "sub-6",
            "--output-dir",
            tmp_path / "wrong-seed",
            "--import-from",
            hold_out,
        )
        == 1
    )


def test_per_seed_scenario_difference_is_explicit(trained, tmp_path):
    bundle, config = trained
    assert operation.prevalidated_scenario_difference(bundle, config) is False
    timing = Path(config).with_name("seed.ini")
    timing.write_text(
        Path(config).read_text().replace("[rl]", "[rl]\ncontrol_start_s = 0.5")
    )
    assert operation.prevalidated_scenario_difference(bundle, timing, 0.5) is True
    with pytest.raises(ValueError, match="native"):
        operation.prevalidated_scenario_difference(bundle, timing, 1.0)
    traffic = Path(config).with_name("traffic.ini")
    traffic.write_text(Path(config).read_text() + "\n[traffic]\ndemand_mbps = 30\n")
    with pytest.raises(ValueError, match=r"non-timing settings.*traffic.demand_mbps"):
        operation.prevalidated_scenario_difference(bundle, traffic)
    moved = Path(config).with_name("moved.ini")
    other_nodes = Path(config).with_name("other-nodes.json")
    other_nodes.write_text(
        Path(config).with_name("nodes.json").read_text().replace("50.0", "51.0")
    )
    moved.write_text(
        Path(config)
        .read_text()
        .replace("nodes_file = nodes.json", "nodes_file = other-nodes.json")
    )
    with pytest.raises(ValueError, match="nodes_json_sha256"):
        operation.prevalidated_scenario_difference(bundle, moved)


def test_per_seed_jammer_changes_only_allow_timing(tmp_path):
    from types import SimpleNamespace

    from scripts.rl.env.config import read_scenario_identity

    (tmp_path / "nodes.json").write_text("[]")
    original = tmp_path / "original.ini"
    original.write_text(
        "[scenario]\nnodes_file = nodes.json\njammers_file = original-jammer.json\n"
    )
    jammer = {
        "id": "j",
        "tx_power_dbm": 10,
        "intervals": [{"start": 1, "end": 3}],
        "waypoints": [{"t": 0, "x": 0, "y": 0, "z": 1}],
    }
    (tmp_path / "original-jammer.json").write_text(json.dumps([jammer]))
    bundle = SimpleNamespace(
        manifest={"scenario_identity": read_scenario_identity(str(original))}
    )

    live = tmp_path / "live.ini"
    live.write_text(
        original.read_text().replace("original-jammer.json", "live-jammer.json")
    )
    live_jammer = tmp_path / "live-jammer.json"
    jammer["intervals"][0]["start"] = 2
    live_jammer.write_text(json.dumps([jammer]))
    assert operation.prevalidated_scenario_difference(bundle, live)

    jammer["tx_power_dbm"] = 20
    live_jammer.write_text(json.dumps([jammer]))
    with pytest.raises(ValueError, match="limited to event timing"):
        operation.prevalidated_scenario_difference(bundle, live)


def test_gated_and_sampling_operations_need_the_declared_mission(
    trained, sim_binary, tmp_path
):
    bundle, config = trained
    common = [
        "model",
        "--sim-binary",
        sim_binary,
        "--run-dir",
        bundle.run_dir,
        "--model",
        "final",
        "--operation-id",
        "o",
        "--seed",
        11,
        "--seed-role",
        "diagnostic",
        "--run-config",
        config,
    ]
    assert (
        operate(
            *common,
            "--mode",
            "online_gated_v1",
            "--output-dir",
            tmp_path / "gated",
            "--protocol-settings-json",
            '{"n_steps": 2, "batch_size": 2}',
        )
        == 1
    )
    schedule = (
        '{"kind": "initial-sampling", "settings": {"initial_sample_decisions": 2}}'
    )
    assert (
        operate(
            *common,
            "--mode",
            "frozen_sampled",
            "--output-dir",
            tmp_path / "sampled",
            "--protocol-settings-json",
            "{}",
            "--schedule-json",
            schedule,
        )
        == 1
    )
    assert (
        operate(
            *common,
            "--mode",
            "online_gated_v1",
            "--output-dir",
            tmp_path / "with-mission",
            "--mission",
            "coverage",
            "--protocol-settings-json",
            '{"n_steps": 2, "batch_size": 2}',
        )
        == 0
    )
    record = json.loads((tmp_path / "with-mission/online_manifest.json").read_text())
    assert record["protocol"] == "online_gated_v1" and record["status"] == "completed"


def test_band_and_decision_records_reach_the_seeded_env_and_record(
    trained, sim_binary, tmp_path, monkeypatch
):
    from scripts.rl.env import mesh_env

    bundle, config = trained
    seen = []
    original = mesh_env.MeshRlEnv.__init__

    def spy(self, *args, **kwargs):
        seen.append((kwargs.get("band"), kwargs.get("decision_records")))
        original(self, *args, **kwargs)

    monkeypatch.setattr(mesh_env.MeshRlEnv, "__init__", spy)
    out = tmp_path / "op"
    assert (
        operate(
            "model",
            "--sim-binary",
            sim_binary,
            "--run-dir",
            bundle.run_dir,
            "--model",
            "final",
            "--mode",
            "frozen_sampled",
            "--operation-id",
            "o",
            "--seed",
            11,
            "--seed-role",
            "diagnostic",
            "--run-config",
            config,
            "--band",
            "sub-6",
            "--output-dir",
            out,
            "--protocol-settings-json",
            "{}",
            "--decision-records",
        )
        == 0
    )
    assert seen and all(band == "sub-6" for band, _ in seen)
    assert all(records is not None and records.settings.enabled for _, records in seen)
    record = json.loads((out / "online_manifest.json").read_text())
    assert (
        record["settings"]["band"] == "sub-6"
        and record["settings"]["band_source"] == "cli"
    )
    assert record["settings"]["decision_records"]["enabled"] is True
    episode = out / record["evaluation"]["episode_dir"]
    assert (episode / "policy_decisions.jsonl").is_file()
    seen.clear()
    plain = tmp_path / "plain"
    assert operate(
        "baseline",
        "--sim-binary",
        sim_binary,
        "--policy",
        "hold",
        "--seed",
        11,
        "--seed-role",
        "diagnostic",
        "--run-config",
        config,
        "--band",
        "mmwave",
        "--output-dir",
        plain,
    ) in (0, 1)
    assert seen and seen[0][0] == "mmwave" and seen[0][1] is None


def review_stub(monkeypatch):
    from scripts.rl.policy import episode_review

    monkeypatch.setattr(
        episode_review,
        "review_metrics",
        lambda directory: {"stub_dir": Path(directory).name},
    )
    return episode_review


def fake_episode(directory):
    directory.mkdir(parents=True)
    (directory / "steps.jsonl").write_text("{}\n")
    (directory / "rl_episode.json").write_text("{}")
    return directory


def test_scene_review_without_models_is_a_valid_empty_v1_payload(tmp_path, monkeypatch):
    review = review_stub(monkeypatch).scene_review(
        tmp_path, "urban-coverage-3-peers", []
    )
    assert review == {
        "mission_review_version": 1,
        "objective": "coverage",
        "ranking_basis": "Frozen deterministic validation; separate variants and training seeds; "
        "not held-out confirmation",
        "ranking": [],
        "episodes": {},
    }


def test_scene_review_reads_explicit_baselines_before_the_legacy_path(
    tmp_path, monkeypatch
):
    episode_review = review_stub(monkeypatch)
    legacy = tmp_path / "baselines/s-coverage/eval_manifest.json"
    fake_episode(tmp_path / "baselines/s-coverage/hold/episode-0000")
    legacy.write_text(
        json.dumps(
            {
                "policies": {
                    "hold": {
                        "episodes": [
                            {
                                "episode_dir": str(
                                    tmp_path / "baselines/s-coverage/hold/episode-0000"
                                )
                            }
                        ]
                    }
                }
            }
        )
    )
    leaf = tmp_path / "new/baselines/hold/attempt-1"
    fake_episode(leaf / "hold/episode-0000")
    (leaf / "eval_manifest.json").write_text(
        json.dumps(
            {"policies": {"hold": {"episodes": [{"episode_dir": "hold/episode-0000"}]}}}
        )
    )
    loaded = {
        "policies": {
            "scripted": {
                "episodes": [
                    {"episode_dir": str(fake_episode(tmp_path / "loaded/episode-0000"))}
                ]
            }
        }
    }
    explicit = episode_review.scene_review(
        tmp_path, "s-coverage", [], baselines=[leaf, loaded]
    )
    assert list(explicit["episodes"]) == [
        "new/baselines/hold/attempt-1/hold/episode-0000",
        "loaded/episode-0000",
    ]
    legacy_only = episode_review.scene_review(tmp_path, "s-coverage", [])
    assert list(legacy_only["episodes"]) == ["baselines/s-coverage/hold/episode-0000"]
    assert (
        episode_review.scene_review(tmp_path, "s-coverage", [], baselines=[])[
            "episodes"
        ]
        == {}
    )


def test_scene_review_resolves_v5_episode_dirs_against_their_manifest(
    tmp_path, monkeypatch
):
    episode_review = review_stub(monkeypatch)
    leaf = (
        tmp_path
        / "operations/s-coverage/row/train-seed-1/checkpoint-final/op-k/diagnostic/seed-11/attempt-1"
    )
    fake_episode(leaf / "episode-0000")
    (leaf / "online_manifest.json").write_text(
        json.dumps(
            {
                "online_experiment_version": 5,
                "episodes": [
                    {
                        "mode": "online_gated_v1",
                        "seed": 11,
                        "episode_dir": "episode-0000",
                        "metrics": {"recorded": 1},
                    }
                ],
            }
        )
    )
    fixed = tmp_path / "fixed"
    fixed.mkdir()
    (fixed / "eval_manifest.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "policies": {
                    "model": {"episodes": [{"episode_dir": "../fixed-episode"}]}
                },
            }
        )
    )
    fake_episode(tmp_path / "fixed-episode")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    models = [
        {
            "scene": "s-coverage",
            "reward": "r",
            "profile": "p",
            "fixed": str(fixed),
            "operation": str(leaf),
        }
    ]
    review = episode_review.scene_review(tmp_path, "s-coverage", models, baselines=[])
    assert sorted(review["episodes"]) == [
        "fixed-episode",
        leaf.relative_to(tmp_path).as_posix() + "/episode-0000",
    ]
    assert len(review["ranking"]) == 1 and review["ranking"][0]["metrics"] == {}


@pytest.mark.parametrize("policy", ["geometric", "optimization"])
def test_placement_baselines_delegate_to_the_evaluate_placement_path(
    policy, tmp_path, monkeypatch
):
    from scripts.rl import evaluate as evaluate_cli

    seen = []
    monkeypatch.setattr(evaluate_cli, "main", lambda argv: seen.append(argv) or 0)
    ini = tmp_path / "run.ini"
    ini.write_text("[rl]\ncontrol_start_s = 40\n")
    assert (
        operate(
            "baseline",
            "--sim-binary",
            "B",
            "--policy",
            policy,
            "--seed",
            7,
            "--seed-role",
            "diagnostic",
            "--run-config",
            ini,
            "--band",
            "sub-6",
            "--output-dir",
            tmp_path / "out",
            "--gate-s",
            "40.0",
            "--planning-seed",
            99,
            "--allow-seed-overlap",
            "--decision-records",
            "--decision-records-every",
            2,
        )
        == 0
    )
    assert seen == [
        [
            "--sim-binary",
            "B",
            "--run-config",
            str(ini),
            "--output-dir",
            str(tmp_path / "out"),
            "--seeds",
            "7",
            "--policies",
            policy,
            "--label",
            f"baseline {policy} diagnostic seed 7",
            "--band",
            "sub-6",
            "--planning-seed",
            "99",
            "--allow-seed-overlap",
            "--decision-records",
            "--decision-records-every",
            "2",
        ]
    ]
    common = [
        "baseline",
        "--sim-binary",
        "B",
        "--seed",
        7,
        "--seed-role",
        "diagnostic",
        "--run-config",
        ini,
        "--output-dir",
        tmp_path / "bad",
    ]
    assert (
        operate(*common, "--policy", policy, "--gate-s", "30.0") == 1
    )  # declared gate disagrees with run.ini
    assert operate(*common, "--policy", policy, "--import-from", tmp_path) == 1
    assert operate(*common, "--policy", "hold", "--planning-seed", 99) == 1
    assert len(seen) == 1


def test_placement_baseline_end_to_end_with_the_stub_planner(
    sim_binary, tmp_path, monkeypatch
):
    from scripts.rl.tests.policy.test_evaluation_pipeline import _placement_run_config

    run_config = _placement_run_config(tmp_path, monkeypatch)
    out = tmp_path / "geometric"
    assert (
        operate(
            "baseline",
            "--sim-binary",
            sim_binary,
            "--policy",
            "geometric",
            "--seed",
            2,
            "--seed-role",
            "diagnostic",
            "--run-config",
            run_config,
            "--output-dir",
            out,
            "--planning-seed",
            17,
        )
        == 0
    )
    manifest = json.loads((out / "eval_manifest.json").read_text())
    assert manifest["status"] == "completed" and list(manifest["policies"]) == [
        "geometric"
    ]
    assert manifest["seeds"] == [2] and manifest["seed_roles"]["planning_seeds"] == [17]
    block = manifest["policies"]["geometric"]["baseline"]
    assert (
        block["method"] == "geometric"
        and block["executor"] == "hold"
        and block["fingerprint"]
    )
    assert (
        "initial_displacement_m_total"
        in manifest["policies"]["geometric"]["episodes"][0]
    )
    assert (
        operate(
            "baseline",
            "--sim-binary",
            sim_binary,
            "--policy",
            "geometric",
            "--seed",
            2,
            "--seed-role",
            "diagnostic",
            "--run-config",
            run_config,
            "--output-dir",
            tmp_path / "overlap",
            "--planning-seed",
            2,
        )
        == 1
    )  # planning seed equal to the evaluation seed needs explicit overlap


def test_bound_checkpoint_of_an_interrupted_run_needs_its_binding(
    trained, sim_binary, tmp_path
):
    bundle, config = trained
    run_dir = Path(bundle.run_dir)
    manifest_path = run_dir / "train_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["status"] = "interrupted"
    manifest_path.write_text(json.dumps(manifest))
    binding = tmp_path / "state/bindings/producer-final.json"
    binding.parent.mkdir(parents=True)
    binding.write_text(json.dumps(bundles.bind_model(run_dir, manifest["model_path"])))
    common = [
        "model",
        "--sim-binary",
        sim_binary,
        "--run-dir",
        run_dir,
        "--mode",
        "frozen_sampled",
        "--operation-id",
        "bound",
        "--seed",
        11,
        "--seed-role",
        "diagnostic",
        "--run-config",
        config,
        "--protocol-settings-json",
        "{}",
    ]
    assert (
        operate(*common, "--model", "final", "--output-dir", tmp_path / "unbound") == 1
    )
    out = tmp_path / "bound"
    assert (
        operate(*common, "--model", "final", "--output-dir", out, "--binding", binding)
        == 0
    )
    record = json.loads((out / "online_manifest.json").read_text())
    assert record["status"] == "completed"
    assert record["parent"]["binding"] == {
        "path": str(binding.resolve()),
        "sha256": bundles.sha256_file(binding),
    }
    assert (
        json.loads((out / "eval_manifest.json").read_text())["bundle"]["binding"][
            "sha256"
        ]
        == record["parent"]["binding"]["sha256"]
    )
    assert (
        operate(
            *common,
            "--model",
            "best",
            "--output-dir",
            tmp_path / "other-model",
            "--binding",
            binding,
        )
        == 1
    )
    hand_written = tmp_path / "binding.json"
    hand_written.write_bytes(binding.read_bytes())
    assert (
        operate(
            *common,
            "--model",
            "final",
            "--output-dir",
            tmp_path / "manual-binding",
            "--binding",
            hand_written,
        )
        == 1
    )
    with open(manifest["model_path"], "ab") as handle:
        handle.write(b"tampered")
    assert (
        operate(
            *common,
            "--model",
            "final",
            "--output-dir",
            tmp_path / "tampered",
            "--binding",
            binding,
        )
        == 1
    )
    assert not (tmp_path / "tampered/online_manifest.json").exists()


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
