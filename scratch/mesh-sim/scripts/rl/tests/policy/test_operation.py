"""Frozen policy operation, native gate inputs, and input compatibility."""

import json
from pathlib import Path
import pytest
from scripts.rl.policy import bundle as bundles
from scripts.rl.policy import operation
from scripts.rl.policy.operation import DiagnosticEnv, resolve_gates, run_operation
from scripts.rl.policy.schedules import (
    COVERAGE_SCHEDULE_VERSION,
)
from scripts.rl.tests.policy.test_online_protocols import (
    three_decision_config,
    train_run,
)
from scripts.rl.tests.support.operation import CASE, trained_policy as trained_policy

pytest.importorskip("sb3_contrib")


def absolute_paths(value, root):
    if isinstance(value, dict):
        return [p for v in value.values() for p in absolute_paths(v, root)]
    if isinstance(value, list):
        return [p for v in value for p in absolute_paths(v, root)]
    return [value] if isinstance(value, str) and value.startswith(str(root)) else []


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
