"""Argument parsing and dispatch for the operation CLI."""

import json
from pathlib import Path
import pytest
from scripts.rl.policy import bundle as bundles
from scripts.rl.policy import operation
from scripts.rl.tests.support.operation import operate, trained_policy as trained_policy

pytest.importorskip("sb3_contrib")


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
