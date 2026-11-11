"""Operation CLI runs against the fake simulator and stub planner."""

import json
from pathlib import Path
import pytest
from scripts.rl.policy import bundle as bundles
from scripts.rl.tests.support.operation import operate, trained_policy as trained_policy

pytest.importorskip("sb3_contrib")


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
