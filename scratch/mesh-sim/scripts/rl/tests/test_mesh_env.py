"""Contract tests for MeshRlEnv and the training CLI, driven by fake_sim.py."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import gymnasium
import pytest

from scripts.rl.env.mesh_env import MeshRlEnv

MESH_SIM_ROOT = Path(__file__).resolve().parents[3]
FAKE_SIM = Path(__file__).resolve().parent / "fake_sim.py"

RUN_INI = """[scenario]
name = fake
seed = 1
duration_s = 0.4
tick_s = 0.1

[rl]
enabled = true
controlled_node_id = relay
action_type = discrete
reward_type = all_links_los
step_size_m = 5.0
"""


@pytest.fixture
def run_config(tmp_path: Path) -> str:
    path = tmp_path / "run.ini"
    path.write_text(RUN_INI)
    return str(path)


@pytest.fixture
def sim_binary(tmp_path: Path) -> str:
    """Executable shim so MeshRlEnv can spawn the fake sim like a real binary."""
    shim = tmp_path / "fake-sim"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_SIM}" "$@"\n')
    shim.chmod(0o755)
    return str(shim)


def _episode_manifest(out_dir: Path, index: int) -> dict:
    return json.loads((out_dir / f"episode-{index:04d}" / "rl_episode.json").read_text())


# 1. Episode directory allocation ------------------------------------------------

def test_two_resets_allocate_distinct_episodes(sim_binary, run_config, tmp_path):
    out_dir = tmp_path / "train"
    env = MeshRlEnv(sim_binary, run_config, output_dir=str(out_dir))
    env.reset()
    first = _episode_manifest(out_dir, 0)
    env.reset()
    env.close()

    second = _episode_manifest(out_dir, 1)
    assert (out_dir / "episode-0000").is_dir() and (out_dir / "episode-0001").is_dir()
    assert first["episode"] == 0 and second["episode"] == 1
    assert _episode_manifest(out_dir, 0)["command"] == first["command"]
    for manifest in (first, second):
        assert manifest["seed"] == 1
        assert manifest["seed_source"] == "run.ini"
        assert manifest["manifest_version"] == 1
    for index in (0, 1):
        manifest = _episode_manifest(out_dir, index)
        assert manifest["status"] == "interrupted"
        assert manifest["exit_code"] == 0


def test_done_episode_is_completed(sim_binary, run_config, tmp_path):
    out_dir = tmp_path / "train"
    env = MeshRlEnv(sim_binary, run_config, output_dir=str(out_dir))
    env.reset()
    for _ in range(4):
        _, _, done, _, _ = env.step(6)
    assert done
    env.close()
    manifest = _episode_manifest(out_dir, 0)
    assert manifest["status"] == "completed" and manifest["steps"] == 4


# 2. Seed resolution -------------------------------------------------------------

def test_reset_seed_override_persists(sim_binary, run_config, tmp_path):
    out_dir = tmp_path / "train"
    env = MeshRlEnv(sim_binary, run_config, output_dir=str(out_dir))
    env.reset(seed=7)
    env.reset()
    env.close()

    assert _episode_manifest(out_dir, 0)["seed"] == 7
    assert _episode_manifest(out_dir, 1)["seed"] == 7
    assert _episode_manifest(out_dir, 1)["seed_source"] == "gym"


def test_reset_with_resolved_seed_keeps_source(sim_binary, run_config, tmp_path):
    out_dir = tmp_path / "train"
    env = MeshRlEnv(sim_binary, run_config, output_dir=str(out_dir))
    env.reset(seed=1)     # same value the run.ini already resolved
    env.close()

    manifest = _episode_manifest(out_dir, 0)
    assert manifest["seed"] == 1
    assert manifest["seed_source"] == "run.ini"


def test_missing_seed_is_rejected(sim_binary, tmp_path):
    ini = tmp_path / "noseed.ini"
    ini.write_text("[scenario]\nduration_s = 0.4\ntick_s = 0.1\n")
    with pytest.raises(ValueError, match="seed"):
        MeshRlEnv(sim_binary, str(ini), output_dir=str(tmp_path / "train"))


@pytest.mark.parametrize("marker", ["#", ";"])
def test_seed_and_bounds_strip_inline_comments(sim_binary, run_config, tmp_path, marker):
    path = Path(run_config)
    path.write_text(RUN_INI.replace("seed = 1", f"seed = 1{marker}seed note") +
                    f"x_min = -10{marker}low\nx_max = 10 {marker}high\n"
                    f"y_min = -20{marker}low\ny_max = 20 {marker}high\n"
                    f"z_min = 0{marker}low\nz_max = 30 {marker}high\n")
    env = MeshRlEnv(sim_binary, run_config, output_dir=str(tmp_path / "train"))
    env.reset()
    assert env.seed_value == 1
    assert env._x_range == (-10.0, 10.0)
    assert env._y_range == (-20.0, 20.0)
    assert env._z_range == (0.0, 30.0)
    env.close()


# 3. Protocol failures -----------------------------------------------------------

def test_premature_exit_reports_code_and_stderr(sim_binary, run_config, tmp_path,
                                                monkeypatch):
    monkeypatch.setenv("FAKE_SIM_MODE", "exit3")
    env = MeshRlEnv(sim_binary, run_config, output_dir=str(tmp_path / "train"))
    env.reset()
    with pytest.raises(RuntimeError) as err:
        env.step(6)
    message = str(err.value)
    assert "exit code 3" in message
    assert "fake-sim: simulated fatal error" in message


def test_malformed_output_reports_line_and_text(sim_binary, run_config, tmp_path,
                                                monkeypatch):
    monkeypatch.setenv("FAKE_SIM_MODE", "malformed")
    env = MeshRlEnv(sim_binary, run_config, output_dir=str(tmp_path / "train"))
    env.reset()
    with pytest.raises(RuntimeError) as err:
        env.step(6)
    message = str(err.value)
    assert "message line 2" in message
    assert "this is not json {" in message


# 4. Band forwarding and action masks --------------------------------------------

@pytest.mark.parametrize("band", ["sub-6", None])
def test_band_flag_forwarding(sim_binary, run_config, tmp_path, band):
    env = MeshRlEnv(sim_binary, run_config, output_dir=str(tmp_path / "train"),
                    band=band)
    env.reset()
    env.close()
    flags = [a for a in env._cmd if a.startswith("--band")]
    assert flags == ([f"--band={band}"] if band else [])


def test_bound_defaults_match_cpp_and_mask_z(sim_binary, run_config, tmp_path):
    env = MeshRlEnv(sim_binary, run_config, output_dir=str(tmp_path / "train"))
    env.reset()
    assert env._x_range == (-1000.0, 2000.0)
    assert env._y_range == (-1000.0, 1000.0)
    assert env._z_range == (0.0, 100.0)

    mask = env.action_masks()
    assert not mask[4]      # at z_min -> -Z illegal
    assert mask[5] and mask[6]
    env.close()


# 5. Registration, CLI shape, and a tiny training run -----------------------------

def test_gym_registration_resolves(sim_binary, run_config, tmp_path):
    import scripts.rl  # noqa: F401  (performs the registration)

    env = gymnasium.make(
        "mesh_sim/MeshEnv-v0",
        disable_env_checker=True,
        sim_binary=sim_binary,
        run_config=run_config,
        output_dir=str(tmp_path / "train"),
    )
    assert isinstance(env.unwrapped, MeshRlEnv)
    env.close()


@pytest.mark.parametrize("argv,expected", [
    (["--help"], "--sim-binary"),
    (["--sim-binary", "x", "--run-config", "y", "m-ppo", "--help"], "--total-timesteps"),
])
def test_cli_help(argv, expected):
    result = subprocess.run(
        [sys.executable, "-m", "scripts.rl.train", *argv],
        cwd=MESH_SIM_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout
    if argv == ["--help"]:
        assert "--total-timesteps" not in result.stdout


@pytest.mark.skipif(importlib.util.find_spec("sb3_contrib") is None,
                    reason="sb3_contrib not installed")
def test_tiny_training_run(sim_binary, run_config, tmp_path, monkeypatch):
    from scripts.rl import train

    out_dir = tmp_path / "train"
    argv = ["train", "--sim-binary", sim_binary, "--run-config", run_config,
            "--output-dir", str(out_dir), "--verbose", "0",
            "m-ppo", "--total-timesteps", "16", "--n-steps", "16"]
    monkeypatch.setattr(sys, "argv", argv)
    assert train.main() == 0

    manifest = json.loads((out_dir / "train_manifest.json").read_text())
    assert manifest["status"] == "completed"
    assert manifest["seed"] == 1 and manifest["seed_source"] == "run.ini"
    assert manifest["package_versions"]["sb3_contrib"]
    assert set(manifest["package_versions"]) == set(train.DIRECT_DEPS)
    assert len(manifest["package_versions"]) == 8
    assert all(manifest["package_versions"].values())
    assert (out_dir / "maskable_ppo_mesh.zip").is_file()

    # Every simulator episode, including the ones SB3 opens, must agree with the manifest.
    episodes = sorted(out_dir.glob("episode-*/rl_episode.json"))
    assert episodes
    for path in episodes:
        episode = json.loads(path.read_text())
        assert episode["seed"] == manifest["seed"], path
        assert episode["seed_source"] == manifest["seed_source"], path
        if episode["steps"] == 0:
            assert episode["status"] == "interrupted", path

    monkeypatch.setattr(sys, "argv", argv)
    assert train.main() == 1      # refuses to reuse a populated output directory
