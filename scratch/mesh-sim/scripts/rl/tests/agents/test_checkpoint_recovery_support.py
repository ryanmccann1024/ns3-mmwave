"""Post-update checkpoints, continuation options and model digests/bindings.

Real-PPO cases either drive ``train`` against ``fake_sim.py`` (protocol peer,
no radio model; labelled "fake simulator") or optimize a tiny in-process
masked stub env (labelled "stub env"). ZIPs are generated under tmp_path.
"""

import importlib.util
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import gymnasium as gym
import numpy as np
import pytest

from scripts.rl.agents.config import Cadence, MaskablePPOConfig
from scripts.rl.agents.post_update import (AFTER_UPDATE_TIMING, POST_UPDATE_CHECKPOINTS_NAME,
                                           PostUpdateCheckpoints,
                                           validate_after_update_schedule)
from scripts.rl.policy.bundle import (MODEL_BINDING_VERSION, bind_model, checkpoint_counters,
                                      checkpoint_optimizer_digest, read_bound_checkpoint)
from scripts.rl.policy.compat import BundleError

needs_sb3 = pytest.mark.skipif(importlib.util.find_spec("sb3_contrib") is None,
                               reason="sb3_contrib not installed")


def _train_argv(sim_binary, run_config, out_dir, *extra, total=8):
    return ["--sim-binary", sim_binary, "--run-config", run_config,
            "--output-dir", str(out_dir), "--verbose", "0", "m-ppo",
            "--total-timesteps", str(total), "--n-steps", "4", "--batch-size", "4",
            "--n-epochs", "1", "--seed", "1", *extra]


def _after_update(every=4, keep=1, dpe="2"):
    return ["--checkpoint-timing", "after-update", "--checkpoint-every-steps", str(every),
            "--keep-checkpoints", str(keep), "--decisions-per-episode", dpe]


def test_post_update_callback_milestones_counters_and_file_fields(tmp_path):
    """Stub model: no parent save, no pre-update save, cumulative milestones only."""
    saved = []
    artifacts = SimpleNamespace(out_dir=tmp_path,
                                record_checkpoint=lambda path, steps, keep: saved.append(
                                    (steps, path.name, keep)))
    callback = PostUpdateCheckpoints(artifacts, every=3000, keep=5, decisions_per_episode=600)
    callback.model = SimpleNamespace(num_timesteps=15000, _n_updates=250,
                                     save=lambda path: Path(path).write_bytes(b"stub"))
    callback._on_training_start()
    callback._on_rollout_start()
    callback.model.num_timesteps = 18000
    callback._on_rollout_start()
    assert not saved  # steps advanced without an optimizer update
    callback.model._n_updates = 300
    callback._on_rollout_start()
    callback._on_rollout_start()
    callback.model.num_timesteps, callback.model._n_updates = 19200, 310
    callback._on_rollout_start()  # updated, but not on the cadence
    callback.model.num_timesteps, callback.model._n_updates = 21000, 320
    callback._on_training_end()
    assert saved == [(18000, "checkpoint_18000_steps.zip", 5),
                     (21000, "checkpoint_21000_steps.zip", 5)]
    record = json.loads((tmp_path / POST_UPDATE_CHECKPOINTS_NAME).read_text())
    assert record == {"post_update_checkpoints_version": 1, "restored_steps": 15000,
                      "validation_during_training": False, "events": [
                          {"steps": 18000, "total_episodes": 30, "optimizer_epoch_counter": 300,
                           "timing": AFTER_UPDATE_TIMING},
                          {"steps": 21000, "total_episodes": 35, "optimizer_epoch_counter": 320,
                           "timing": AFTER_UPDATE_TIMING}]}
    assert not list((tmp_path / "checkpoints").glob("*.tmp.zip"))


@pytest.mark.parametrize("settings, restored, dpe, pattern", [
    (dict(eval_every=4), 0, None, "without in-training validation"),
    (dict(checkpoint_every=0), 0, None, "positive checkpoint cadence"),
    (dict(checkpoint_every=6), 0, None, "multiples of n_steps"),
    (dict(), 2, None, "multiples of n_steps"),
    (dict(total=12), 0, None, "multiple of the checkpoint cadence"),
    (dict(total=8), 8, None, "beyond the restored"),
    (dict(), 0, 3, "whole episodes"),
])
def test_after_update_schedule_rejects_misaligned_budgets(settings, restored, dpe, pattern):
    cfg = MaskablePPOConfig(total_timesteps=settings.get("total", 16), n_steps=4, batch_size=4)
    cadence = Cadence(checkpoint_every=settings.get("checkpoint_every", 8),
                      eval_every=settings.get("eval_every", 0))
    with pytest.raises(ValueError, match=pattern):
        validate_after_update_schedule(cfg, cadence, restored, dpe)
    validate_after_update_schedule(MaskablePPOConfig(total_timesteps=16, n_steps=4, batch_size=4),
                                   Cadence(checkpoint_every=8), 8, 4)


def test_existing_argv_parses_with_unchanged_defaults():
    from scripts.rl.train import build_parser
    args = build_parser().parse_args(
        ["--sim-binary", "b", "--run-config", "r", "m-ppo", "--total-timesteps", "16",
         "--checkpoint-every-steps", "8", "--resume-run-dir", "parent"])
    assert (args.total_timesteps, args.checkpoint_every_steps, args.keep_checkpoints,
            args.eval_every_steps, args.resume_run_dir, args.resume_checkpoint, args.seed) == (
        16, 8, 3, 0, "parent", None, None)
    assert (args.continue_from_run_dir, args.continue_model, args.checkpoint_timing,
            args.decisions_per_episode, args.curriculum_schedule) == (
        None, None, "standard", None, None)
    new = build_parser().parse_args(
        ["--sim-binary", "b", "--run-config", "r", "m-ppo", "--continue-from-run-dir", "p",
         "--continue-model", "checkpoints/checkpoint_8_steps.zip", "--checkpoint-timing",
         "after-update", "--decisions-per-episode", "600", "--curriculum-schedule", "c.json"])
    assert (new.continue_from_run_dir, new.continue_model, new.checkpoint_timing,
            new.decisions_per_episode, new.curriculum_schedule) == (
        "p", "checkpoints/checkpoint_8_steps.zip", "after-update", 600, "c.json")
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--sim-binary", "b", "--run-config", "r", "m-ppo",
                                   "--checkpoint-timing", "sometimes"])


@pytest.mark.parametrize("extra, pattern", [
    (["--continue-from-run-dir", "a", "--resume-run-dir", "b"], "mutually exclusive"),
    (["--continue-model", "best"], "requires --continue-from-run-dir"),
    (["--continue-from-run-dir", "a", "--resume-checkpoint", "checkpoints/x.zip"],
     "requires --resume-run-dir"),
    (["--checkpoint-timing", "after-update", "--checkpoint-every-steps", "4",
      "--eval-every-steps", "4"], "without in-training validation"),
    (["--checkpoint-timing", "after-update", "--checkpoint-every-steps", "6"],
     "multiples of n_steps"),
    (["--checkpoint-timing", "after-update", "--checkpoint-every-steps", "8"],
     "multiple of the checkpoint cadence"),
    (["--decisions-per-episode", "0"], "decisions per episode"),
])
def test_cli_refuses_invalid_options_before_any_output(tmp_path, capsys, extra, pattern):
    from scripts.rl import train
    out = tmp_path / "out"
    assert train.main(_train_argv("missing-bin", str(tmp_path / "run.ini"), out, *extra,
                                  total=12)) == 1
    assert pattern in capsys.readouterr().err
    assert not out.exists()


@needs_sb3
def test_decisions_per_episode_mismatch_fails_before_training(sim_binary, multi_run_config,
                                                             tmp_path, capsys):
    """Fake simulator: the native contract has 2 decisions; asserting 4 is refused."""
    from scripts.rl import train
    out = tmp_path / "out"
    assert train.main(_train_argv(sim_binary, multi_run_config, out,
                                  *_after_update(dpe="4"))) == 1
    assert "the simulator contract has 2" in capsys.readouterr().err
    manifest = json.loads((out / "train_manifest.json").read_text())
    assert manifest["status"] == "failed" and manifest["num_timesteps"] == 0
    assert not (out / "checkpoints").exists() and not (out / POST_UPDATE_CHECKPOINTS_NAME).exists()


@needs_sb3
def test_after_update_training_and_continuation(sim_binary, multi_run_config, tmp_path):
    """Fake simulator, real MaskablePPO: fresh after-update run then a final-model continuation."""
    from scripts.rl import train
    parent = tmp_path / "parent"
    assert train.main(_train_argv(sim_binary, multi_run_config, parent, *_after_update())) == 0
    record = json.loads((parent / POST_UPDATE_CHECKPOINTS_NAME).read_text())
    assert record["restored_steps"] == 0 and record["validation_during_training"] is False
    assert [(e["steps"], e["total_episodes"], e["optimizer_epoch_counter"], e["timing"])
            for e in record["events"]] == [(4, 2, 1, AFTER_UPDATE_TIMING),
                                           (8, 4, 2, AFTER_UPDATE_TIMING)]
    manifest = json.loads((parent / "train_manifest.json").read_text())
    assert manifest["manifest_version"] == 7 and manifest["checkpoint_timing"] == "after-update"
    assert manifest["decisions_per_episode"] == {"asserted": 2, "native": 2}
    assert manifest["evaluation"] is None and "continuation" not in manifest
    # keep=1 retention: only the newest checkpoint survives on disk and in the manifest.
    assert [Path(c["path"]).name for c in manifest["checkpoints"]] == ["checkpoint_8_steps.zip"]
    assert sorted(p.name for p in (parent / "checkpoints").iterdir()) == ["checkpoint_8_steps.zip"]
    counters = checkpoint_counters(parent / "checkpoints/checkpoint_8_steps.zip")
    assert counters == {"num_timesteps": 8, "n_updates": 2, "policy_state_present": True,
                        "optimizer_state_present": True}

    refused = tmp_path / "refused"
    assert train.main(_train_argv(sim_binary, multi_run_config, refused, "--continue-from-run-dir",
                                  str(parent), *_after_update(), total=8)) == 1
    assert not refused.exists()

    child = tmp_path / "child"
    assert train.main(_train_argv(sim_binary, multi_run_config, child, "--continue-from-run-dir",
                                  str(parent), *_after_update(), total=16)) == 0
    record = json.loads((child / POST_UPDATE_CHECKPOINTS_NAME).read_text())
    assert record["restored_steps"] == 8
    assert [(e["steps"], e["total_episodes"], e["optimizer_epoch_counter"])
            for e in record["events"]] == [(12, 6, 3), (16, 8, 4)]
    manifest = json.loads((child / "train_manifest.json").read_text())
    assert manifest["status"] == "completed" and manifest["num_timesteps"] == 16
    assert manifest["resume"]["restored_timesteps"] == 8
    continuation = manifest["continuation"]
    assert continuation["selector"] == "final"
    assert continuation["parent"]["model_selection"] == "final"
    assert (continuation["parent"]["num_timesteps"], continuation["parent"]["n_updates"]) == (8, 2)
    assert checkpoint_counters(child / "maskable_ppo_mesh.zip")["n_updates"] == 4
    assert json.loads((parent / "train_manifest.json").read_text())["status"] == "completed"


class _MaskedStub(gym.Env):
    """Tiny masked env with no simulator, for optimizer-digest and binding fixtures."""

    observation_space = gym.spaces.Box(-1.0, 1.0, (3,), np.float32)
    action_space = gym.spaces.Discrete(3)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.t = 0
        return np.zeros(3, np.float32), {}

    def step(self, action):
        self.t += 1
        return np.full(3, self.t / 4, np.float32), float(action == 1), self.t >= 4, False, {}

    def action_masks(self):
        return np.array([True, True, False])


def _stub_model(steps=8):
    from sb3_contrib import MaskablePPO
    model = MaskablePPO("MlpPolicy", _MaskedStub(), n_steps=4, batch_size=4, n_epochs=1,
                        seed=3, device="cpu", verbose=0)
    model.learn(steps)
    return model


@needs_sb3
def test_optimizer_digest_survives_save_load_and_changes_after_a_step(tmp_path):
    """Stub env: real Adam state; parameter digest matches the online.py algorithm."""
    from sb3_contrib import MaskablePPO
    from scripts.rl import online
    from scripts.rl.policy.bundle import optimizer_digest, parameter_digest
    model = _stub_model()
    before, params = optimizer_digest(model), parameter_digest(model)
    assert params == online.parameter_digest(model)
    path = tmp_path / "model.zip"
    model.save(str(path))
    assert checkpoint_optimizer_digest(path) == before
    loaded = MaskablePPO.load(str(path), device="cpu")
    assert optimizer_digest(loaded) == before and parameter_digest(loaded) == params
    assert optimizer_digest(model) == before  # digesting does not mutate state
    model.learn(4, reset_num_timesteps=False)
    assert optimizer_digest(model) != before and parameter_digest(model) != params


def test_checkpoint_counters_reads_without_loading(tmp_path):
    path = tmp_path / "plain.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data", json.dumps({"num_timesteps": 128, "_n_updates": 40}))
        archive.writestr("policy.pth", b"weights")
    before = path.read_bytes()
    assert checkpoint_counters(path) == {"num_timesteps": 128, "n_updates": 40,
                                         "policy_state_present": True,
                                         "optimizer_state_present": False}
    assert path.read_bytes() == before
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data", json.dumps({"num_timesteps": None, "_n_updates": 40}))
    with pytest.raises(BundleError, match="num_timesteps"):
        checkpoint_counters(path)


def _interrupted_run(tmp_path, model):
    from scripts.rl.cli_common import sha256_file
    run = tmp_path / "attempt-1"
    checkpoint = run / "checkpoints" / "checkpoint_8_steps.zip"
    checkpoint.parent.mkdir(parents=True)
    model.save(str(checkpoint))
    (run / "train_manifest.json").write_text(json.dumps({
        "manifest_version": 7, "status": "interrupted", "control_mode": "centralized",
        "num_timesteps": 8, "model_path": None, "model_sha256": None,
        "checkpoints": [{"path": str(checkpoint), "sha256": sha256_file(checkpoint),
                         "num_timesteps": 8}]}))
    return run, checkpoint


@needs_sb3
def test_bound_checkpoint_accepts_original_bytes_and_refuses_changes(tmp_path):
    """Stub env: a checkpoint of an interrupted attempt read through its binding."""
    model = _stub_model()
    run, checkpoint = _interrupted_run(tmp_path, model)
    manifest_bytes = (run / "train_manifest.json").read_bytes()
    binding = bind_model(run, checkpoint)
    assert binding["model_binding_version"] == MODEL_BINDING_VERSION
    assert (binding["model_selection"], binding["num_timesteps"]) == ("checkpoint", 8)
    bundle = read_bound_checkpoint(json.loads(json.dumps(binding)))
    assert bundle.model_path == checkpoint.resolve() and bundle.num_timesteps == 8
    assert bundle.manifest["status"] == "interrupted"
    assert (run / "train_manifest.json").read_bytes() == manifest_bytes

    for key, value, pattern in (("n_updates", binding["n_updates"] + 1, "counters differ"),
                                ("num_timesteps", 16, "counters differ"),
                                ("optimizer_sha256", "0" * 64, "optimizer state differs"),
                                ("model_selection", "final", "manifest records"),
                                ("model_binding_version", 2, "version")):
        with pytest.raises(BundleError, match=pattern):
            read_bound_checkpoint({**binding, key: value})
    with pytest.raises(BundleError, match="lacks"):
        read_bound_checkpoint({k: v for k, v in binding.items() if k != "optimizer_sha256"})

    model.learn(4, reset_num_timesteps=False)
    model.save(str(checkpoint))
    with pytest.raises(BundleError, match="digest mismatch"):
        read_bound_checkpoint(binding)
    (run / "train_manifest.json").write_bytes(manifest_bytes.replace(b"interrupted", b"completed"))
    with pytest.raises(BundleError, match="digest mismatch"):
        read_bound_checkpoint(binding)


@needs_sb3
def test_curriculum_schedule_trains_and_records_hashes(sim_binary, multi_run_config, tmp_path):
    """Fake simulator: curriculum env trains; the manifest pins the schedule and stage INIs."""
    import shutil
    from scripts.rl import train
    from scripts.rl.cli_common import sha256_file
    scenario = Path(multi_run_config).parent
    for stage in ("near", "intermediate"):
        (scenario / stage).mkdir()
        shutil.copy(scenario / "run.ini", scenario / stage / "run.ini")
        shutil.copy(scenario / "nodes.json", scenario / stage / "nodes.json")
    schedule = scenario / "schedule.json"
    schedule.write_text(json.dumps({"near": "near/run.ini", "intermediate": "intermediate/run.ini",
                                    "original": "run.ini"}))
    out = tmp_path / "out"
    assert train.main(_train_argv(sim_binary, multi_run_config, out,
                                  "--curriculum-schedule", str(schedule))) == 0
    manifest = json.loads((out / "train_manifest.json").read_text())
    assert manifest["status"] == "completed" and manifest["manifest_version"] == 7
    assert manifest["curriculum"] == {
        "schedule_path": str(schedule.resolve()), "schedule_sha256": sha256_file(schedule),
        "config_sha256": {stage: sha256_file(scenario / path) for stage, path in (
            ("near", "near/run.ini"), ("intermediate", "intermediate/run.ini"),
            ("original", "run.ini"))}}
    assert manifest["run_config"] == str(Path(multi_run_config).resolve())
    resets = json.loads((out / "curriculum.json").read_text())["resets"]
    assert resets and {r["stage"] for r in resets} == {"near"}
