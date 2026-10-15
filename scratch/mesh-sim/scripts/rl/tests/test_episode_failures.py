"""MeshRlEnv / EpisodeSession lifecycle: exit paths, manifests, leaks, signatures, masks.

Expectations: scripts/rl/env/README.md ("Failure and close", "Control Modes",
"Output"), scripts/rl/env/CLAUDE.md ("Every exit path must leave no child
process or reader thread"; "A later reset whose contract signature differs is a
protocol error, and the original spaces stay"), and src/rl/README.md
("Message fields": signature contents).
"""

import json
from pathlib import Path

import pytest

from scripts.rl.env import episode as episode_mod
from scripts.rl.env.mesh_env import MeshRlEnv

from scripts.rl.tests.protocol_peer import (CENTRAL_INI, ScriptedPeer, centralized_script,
                       drain_threads, episode_manifest, episode_steps,
                       make_init, write_ini)


@pytest.fixture
def peer(tmp_path, monkeypatch) -> ScriptedPeer:
    return ScriptedPeer(tmp_path, monkeypatch)


@pytest.fixture
def out_dir(tmp_path) -> Path:
    return tmp_path / "train"


@pytest.fixture
def central_ini(tmp_path) -> str:
    return write_ini(tmp_path, CENTRAL_INI)


def _env(binary, ini, out_dir, **kwargs) -> MeshRlEnv:
    return MeshRlEnv(str(binary), ini, output_dir=str(out_dir), **kwargs)


def _assert_clean(env: MeshRlEnv, proc=None) -> None:
    assert env._proc is None
    if proc is not None:
        assert proc.poll() is not None, "simulator child was left running"
    assert drain_threads() == [], "stdout drain thread leaked"


# Lifecycle without an episode --------------------------------------------------

def test_close_before_reset_is_a_noop(peer, central_ini, out_dir):
    env = _env(peer.binary, central_ini, out_dir)
    env.close()
    env.close()
    assert not out_dir.exists() or not list(out_dir.glob("episode-*"))
    assert peer.argvs() == []
    assert env.action_space is None and env.observation_space is None


# Launch failures -----------------------------------------------------------------


def test_launch_command_shape(peer, central_ini, out_dir):
    peer.script(centralized_script(make_init()))
    env = _env(peer.binary, central_ini, out_dir, seed=9)
    env.reset()
    env.close()
    (argv,) = peer.argvs()
    assert argv == [f"--run-config={central_ini}", "--rl-mode", "--seed=9",
                    f"--output-dir={out_dir / 'episode-0000'}"]


# Early exit / bad first line -----------------------------------------------------

def test_exit_before_first_message_reports_code_and_stderr(peer, central_ini, out_dir):
    peer.script([{"stderr": "peer: cannot open nodes.json"}, {"exit": 7}])
    env = _env(peer.binary, central_ini, out_dir)
    with pytest.raises(RuntimeError) as err:
        env.reset()
    text = str(err.value)
    assert "ended unexpectedly (exit code 7)" in text
    assert "peer: cannot open nodes.json" in text
    manifest = episode_manifest(out_dir, 0)
    assert manifest["status"] == "failed" and manifest["exit_code"] == 7
    assert manifest["error"] == "sim process ended unexpectedly"
    _assert_clean(env)

    # A corrected simulator works on the next reset, in a fresh episode dir.
    peer.script(centralized_script(make_init()))
    obs, info = env.reset()
    assert obs.shape == (24,) and info["decision"] == 0
    env.close()
    assert episode_manifest(out_dir, 1)["status"] == "interrupted"
    _assert_clean(env)


# Mid-episode failures ------------------------------------------------------------


def test_fail_seed_mid_episode_then_recover(sim_binary, multi_run_config, out_dir,
                                            monkeypatch):
    monkeypatch.setenv("FAKE_SIM_FAIL_SEEDS", "5")
    env = _env(sim_binary, multi_run_config, out_dir)
    env.reset(seed=5)
    proc = env._proc
    _, _, done, _, _ = env.step([4, 4, 4])     # decision 1 arrives, then exit 3
    assert not done
    with pytest.raises(RuntimeError) as err:
        env.step([4, 4, 4])
    assert "exit code 3" in str(err.value)
    assert "fake-sim: simulated fatal error" in str(err.value)
    failed = episode_manifest(out_dir, 0)
    assert failed["status"] == "failed" and failed["exit_code"] == 3
    assert failed["steps"] == 1 and failed["decisions"] == 1
    _assert_clean(env, proc)

    env.reset(seed=1)
    done = False
    while not done:
        _, _, done, _, _ = env.step([4, 4, 4])
    completed = episode_manifest(out_dir, 1)
    assert completed["status"] == "completed" and completed["seed"] == 1
    env.close()
    _assert_clean(env)


def test_done_with_nonzero_exit_is_failed(peer, central_ini, out_dir):
    init = make_init()
    peer.script(centralized_script(init) + [{"exit": 3}])
    env = _env(peer.binary, central_ini, out_dir)
    env.reset()
    env.step([4, 4, 4])
    _, _, done, _, _ = env.step([4, 4, 4])
    assert done
    manifest = episode_manifest(out_dir, 0)
    assert manifest["status"] == "failed" and manifest["exit_code"] == 3
    assert manifest["stop_reason"] == "done"
    _assert_clean(env)


def test_completed_manifest_fields(peer, central_ini, out_dir):
    init = make_init()
    peer.script(centralized_script(init))
    env = _env(peer.binary, central_ini, out_dir)
    env.reset()
    rewards = [env.step([4, 4, 4])[1] for _ in range(2)]
    manifest = episode_manifest(out_dir, 0)
    assert manifest["status"] == "completed" and manifest["exit_code"] == 0
    assert manifest["stop_reason"] == "done" and manifest["escalation"] == "exited"
    assert manifest["steps"] == 2 and manifest["decisions"] == 2
    assert manifest["last_tick"] == 10
    assert manifest["cumulative_reward"] == pytest.approx(sum(rewards))
    assert manifest["contract"] == init
    assert manifest["started_at"] <= manifest["ended_at"]
    assert peer.actions() == [{"action": [4, 4, 4]}, {"action": [4, 4, 4]}]
    _assert_clean(env)


# Close / reset interrupt -----------------------------------------------------------


# Escalation ----------------------------------------------------------------------

def test_close_terminates_simulator_that_ignores_eof(peer, central_ini, out_dir,
                                                     short_waits):
    peer.script([{"emit": make_init()}, {"emit": episode_steps(make_init())[0]}, {"hang": 30}])
    env = _env(peer.binary, central_ini, out_dir)
    env.reset()
    proc = env._proc
    env.close()
    manifest = episode_manifest(out_dir, 0)
    assert manifest["status"] == "interrupted"
    assert manifest["exit_code"] == -15
    _assert_clean(env, proc)


def test_close_kills_simulator_that_ignores_sigterm(peer, central_ini, out_dir,
                                                    short_waits):
    init = make_init()
    peer.script([{"ignore_term": True}, {"emit": init},
                 {"emit": episode_steps(init)[0]}, {"hang": 30}])
    env = _env(peer.binary, central_ini, out_dir)
    env.reset()
    proc = env._proc
    env.close()
    manifest = episode_manifest(out_dir, 0)
    assert manifest["status"] == "interrupted" and manifest["escalation"] == "killed"
    assert manifest["exit_code"] == -9
    _assert_clean(env, proc)


def test_terminated_escalation_is_recorded(peer, central_ini, out_dir, short_waits):
    init = make_init()
    peer.script([{"emit": init}, {"emit": episode_steps(init)[0]}, {"hang": 30}])
    env = _env(peer.binary, central_ini, out_dir)
    env.reset()
    env.close()
    manifest = episode_manifest(out_dir, 0)
    assert manifest["escalation"] == "terminated" and manifest["exit_code"] == -15
    _assert_clean(env)


# Actions and masks (centralized) ---------------------------------------------------


# Contract signature across resets --------------------------------------------------





def test_manifest_json_is_valid_on_every_status(peer, central_ini, out_dir):
    # Every manifest written must be strict JSON (no NaN) with an ISO end time.
    peer.script(centralized_script(make_init()))
    env = _env(peer.binary, central_ini, out_dir)
    env.reset()
    env.reset()
    env.close()
    for index in (0, 1):
        text = (out_dir / f"episode-{index:04d}" / "rl_episode.json").read_text()
        manifest = json.loads(text, parse_constant=lambda c: pytest.fail(c))
        assert manifest["ended_at"] and manifest["status"] == "interrupted"


# Telemetry on failure, and EpisodeSession no-op paths -------------------------------

def test_failed_episode_flushes_telemetry_and_counts(peer, central_ini, out_dir):
    from scripts.rl.env.selection import resolve_selection
    from scripts.rl.env.telemetry import replay_file

    init = make_init()
    steps = episode_steps(init)
    bad = dict(steps[2], decision=5)
    peer.script(centralized_script(init, [steps[0], steps[1], bad]))
    selection = resolve_selection(central_ini, telemetry="steps")
    env = _env(peer.binary, central_ini, out_dir, selection=selection)
    env.reset()
    env.step([4, 4, 4])
    with pytest.raises(RuntimeError, match="decision 5 does not follow 1"):
        env.step([4, 4, 4])
    manifest = episode_manifest(out_dir, 0)
    assert manifest["status"] == "failed"
    assert manifest["telemetry"] == {"file": "steps.jsonl", "records": 2, "every": 1}
    lines = (out_dir / "episode-0000" / "steps.jsonl").read_text().splitlines()
    assert len(lines) == 3                     # header + reset + decision 1
    summary = replay_file(out_dir / "episode-0000" / "steps.jsonl")
    assert (summary.records, summary.obs_mismatches) == (2, 0)
    _assert_clean(env)


@pytest.fixture
def short_waits(monkeypatch):
    monkeypatch.setattr(episode_mod, "_NATURAL_EXIT_S", 0.3)
    monkeypatch.setattr(episode_mod, "_ESCALATION_WAIT_S", 1.0)
