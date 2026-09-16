"""Centralized-control tests against the real mesh-sim binary (p1-multi-smoke).

Set MESH_SIM_BIN to a built simulator to run them; every run writes only into
pytest's tmp_path, never into inputs/.
"""

import json
import os
import statistics
import subprocess
import threading
from pathlib import Path

import gymnasium
import numpy as np
import pytest

from scripts.rl.env.mesh_env import MeshRlEnv
from scripts.sim_support import find_mesh_root, simulator_env

MESH_SIM_BIN = os.environ.get("MESH_SIM_BIN")
if not MESH_SIM_BIN:
    pytest.skip(
        "MESH_SIM_BIN is not set; these tests need a built mesh-sim binary "
        "(see the build step in docs/README).",
        allow_module_level=True,
    )

MESH_ROOT = find_mesh_root(__file__)
FIXTURE = MESH_ROOT / "inputs" / "baselines" / "p1-multi-smoke"
RUN_CONFIG = FIXTURE / "run.ini"

SLOT_WIDTH = 8          # 4 + 2*(N-1) with N = 3
MALFORMED_WARNING = "Warning: malformed RL joint action; all controlled nodes hold."
REVALIDATED_WARNING = ("Warning: RL joint action revalidated; invalid slot actions "
                       "replaced by hold.")


def _action(values) -> str:
    return json.dumps({"action": list(values)})


def _slot_xy(obs, slot: int) -> tuple[float, float]:
    base = slot * SLOT_WIDTH
    return obs[base + 1], obs[base + 2]


## @brief One scripted simulator run with closed stdin and a hard timeout.
def _run_binary(run_config: Path, out_dir: Path, lines: list[str],
                timeout: float = 300.0) -> tuple[subprocess.CompletedProcess, list[dict]]:
    cmd = [MESH_SIM_BIN, f"--run-config={run_config}", "--rl-mode", "--seed=1",
           f"--output-dir={out_dir}"]
    result = subprocess.run(
        cmd, input="".join(line + "\n" for line in lines), text=True,
        capture_output=True, timeout=timeout, env=simulator_env(MESH_ROOT),
    )
    assert result.returncode == 0, result.stderr[-2000:]
    messages = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    return result, messages


def _steps(messages: list[dict]) -> list[dict]:
    return [m for m in messages if m.get("type") == "step"]


@pytest.fixture
def env(tmp_path):
    instance = MeshRlEnv(MESH_SIM_BIN, str(RUN_CONFIG), output_dir=str(tmp_path / "rl"))
    yield instance
    instance.close()


def _episode_manifest(out_dir: Path, index: int = 0) -> dict:
    return json.loads((out_dir / f"episode-{index:04d}" / "rl_episode.json").read_text())


def _drain_threads() -> list:
    return [t for t in threading.enumerate() if t.name == "mesh-sim-drain"]


# 1. Live contract ---------------------------------------------------------------

def test_live_spaces_and_metadata(env):
    obs, info = env.reset()

    assert env.control_mode == "centralized"
    assert env.action_space == gymnasium.spaces.MultiDiscrete([5, 5, 5])
    assert env.observation_space.shape == (24,)
    assert obs.shape == (24,)

    contract = env.contract
    assert contract["contract"] == "mesh_move_2d_v1"
    assert contract["dimensions"] == 2
    assert contract["action_meanings"] == ["west", "east", "south", "north", "hold"]
    assert contract["slot_node_ids"] == ["node-b", "node-c", None]
    assert contract["slot_speed_mps"] == [10.0, 10.0, None]
    assert (contract["num_mesh_nodes"], contract["max_controlled_nodes"],
            contract["num_controlled"]) == (3, 3, 2)
    assert (contract["obs_dim"], contract["mask_dim"]) == (24, 15)
    assert contract["tick_s"] == 0.1 and contract["decision_interval_s"] == 0.5
    assert (contract["decision_interval_ticks"], contract["num_ticks"],
            contract["num_decisions"]) == (5, 10, 2)
    assert contract["reward_window"] == "mean" and contract["wall_policy"] == "clip"

    assert info == {"tick": 0, "time_s": 0.0, "decision": 0, "ticks_in_step": 1,
                    "revalidated_slots": []}
    assert _slot_xy(obs, 0) == (100.0, 0.0)
    assert _slot_xy(obs, 1) == (97.0, 50.0)
    assert list(obs[16:24]) == [0.0] * 8


# 2. Scripted pathway of plan §8 -------------------------------------------------

def test_scripted_positions_and_masks(env, tmp_path):
    env.reset()

    obs, reward, done, _, info = env.step([2, 1, 4])
    assert info["tick"] == 5 and info["decision"] == 1 and info["ticks_in_step"] == 5
    assert info["time_s"] == pytest.approx(0.5)
    assert info["revalidated_slots"] == []
    assert not done
    assert _slot_xy(obs, 0) == (100.0, -5.0)
    assert _slot_xy(obs, 1) == (100.0, 50.0)     # clipped exactly at x_max

    mask = env.action_masks().astype(int)
    assert mask[1] == 0 and mask[6] == 0          # both controlled nodes at x_max
    assert mask[4] == 1 and mask[9] == 1 and mask[14] == 1
    assert list(mask[10:14]) == [0, 0, 0, 0]

    obs, reward, done, _, info = env.step([4, 0, 4])
    assert done and info["tick"] == 10 and info["ticks_in_step"] == 5
    assert _slot_xy(obs, 0) == (100.0, -5.0)      # hold stops the node
    assert _slot_xy(obs, 1) == (95.0, 50.0)

    manifest = _episode_manifest(Path(env._output_dir))
    assert manifest["manifest_version"] == 2 and manifest["status"] == "completed"
    assert manifest["exit_code"] == 0 and manifest["stop_reason"] == "done"
    assert manifest["decisions"] == 2 and manifest["last_tick"] == 10


def test_masked_random_run_completes(env):
    env.reset()
    env.action_space.seed(5)
    done, steps = False, 0
    while not done:
        flat = np.asarray(env.action_masks(), dtype=np.int8)
        action = env.action_space.sample(
            mask=tuple(flat[i * 5:(i + 1) * 5] for i in range(3)))
        _, _, done, _, info = env.step(action)
        steps += 1
    assert steps == 2 and info["tick"] == 10
    assert _episode_manifest(Path(env._output_dir))["status"] == "completed"


def test_repeated_resets_are_deterministic(env):
    trajectories = []
    for _ in range(2):
        env.reset()
        run = []
        for action in ([2, 1, 4], [4, 0, 4]):
            obs, reward, done, _, info = env.step(action)
            run.append((obs.tolist(), reward, done, info))
        trajectories.append(run)
    assert trajectories[0] == trajectories[1]


# 3. Revalidation, structural errors, and interruption ---------------------------

def test_masked_and_padded_actions_hold_per_slot(env):
    env.reset()
    # slot 0 east is masked (node-b sits at x_max); slot 2 is padding, so only
    # hold is legal there. Slot 1 west is valid and must still be applied.
    obs, _, _, _, info = env.step([1, 0, 2])
    assert info["revalidated_slots"] == [0, 2]
    assert _slot_xy(obs, 0) == (100.0, 0.0)
    assert _slot_xy(obs, 1) == (92.0, 50.0)


@pytest.mark.parametrize("line", [
    '{"action": [2, 1, 4]',                 # invalid JSON
    '{"action": 2}',                        # scalar, not a list
    '{"action": [2, 1]}',                   # wrong length
    '{"action": [true, 1, 4]}',             # boolean entry
    '{"action": [2.5, 1, 4]}',              # non-integer entry
    '{"action": [9, 1, 4]}',                # out of range
])
def test_structural_malformed_actions_hold_everything(tmp_path, line):
    result, messages = _run_binary(RUN_CONFIG, tmp_path / "out", [line])
    steps = _steps(messages)
    assert len(steps) == 3
    assert result.stderr.count(MALFORMED_WARNING) == 1
    for step in steps:
        assert _slot_xy(step["obs"], 0) == (100.0, 0.0)
        assert _slot_xy(step["obs"], 1) == (97.0, 50.0)


def test_malformed_action_stops_a_moving_node(tmp_path):
    result, messages = _run_binary(
        RUN_CONFIG, tmp_path / "out", [_action([2, 1, 4]), '{"action": [2, 1, 4]'])
    steps = _steps(messages)
    assert result.stderr.count(MALFORMED_WARNING) == 1
    assert _slot_xy(steps[1]["obs"], 0) == (100.0, -5.0)
    # Hold stops node-b instead of letting the previous command persist.
    assert _slot_xy(steps[2]["obs"], 0) == (100.0, -5.0)
    assert _slot_xy(steps[2]["obs"], 1) == (100.0, 50.0)


def test_semantic_errors_only_affect_invalid_slots(tmp_path):
    result, messages = _run_binary(RUN_CONFIG, tmp_path / "out", [_action([1, 0, 2])])
    steps = _steps(messages)
    assert result.stderr.count(REVALIDATED_WARNING) == 1
    assert MALFORMED_WARNING not in result.stderr
    assert steps[1]["revalidated_slots"] == [0, 2]
    assert _slot_xy(steps[1]["obs"], 0) == (100.0, 0.0)
    assert _slot_xy(steps[1]["obs"], 1) == (92.0, 50.0)


def test_close_mid_episode_is_interrupted(tmp_path):
    out_dir = tmp_path / "rl"
    before = threading.active_count()
    env = MeshRlEnv(MESH_SIM_BIN, str(RUN_CONFIG), output_dir=str(out_dir))
    env.reset()
    env.step([2, 1, 4])
    proc = env._proc
    env.close()

    assert proc.poll() is not None and env._proc is None
    assert _drain_threads() == []
    assert threading.active_count() == before
    manifest = _episode_manifest(out_dir)
    assert manifest["status"] == "interrupted" and manifest["stop_reason"] == "close"
    assert manifest["escalation"] == "exited"


# 4. Combined window / clipping / reward-mean case -------------------------------

COARSE_ACTIONS = ([2, 1, 4], [2, 0, 4], [4, 4, 4])
COARSE_WINDOWS = (3, 3, 1)
BUILDINGS = [{
    "id": "window-wall",
    "bounds": {"x_min": 75.0, "x_max": 80.0, "y_min": 9.0, "y_max": 9.5,
               "z_min": 0.0, "z_max": 20.0},
    "type": "Office",
    "ext_walls": "ConcreteWithWindows",
    "n_floors": 1,
    "n_rooms_x": 1,
    "n_rooms_y": 1,
}]


## @brief Rewrite whole-key INI lines, failing loudly if the fixture changed.
def _edit_ini(text: str, **values: str) -> str:
    seen, lines = set(), []
    for line in text.splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in values:
            seen.add(key)
            lines.append(f"{key} = {values[key]}")
        else:
            lines.append(line)
    missing = set(values) - seen
    assert not missing, f"keys not present in {RUN_CONFIG}: {sorted(missing)}"
    return "\n".join(lines) + "\n"


def _combined_scenario(tmp_path: Path, decision_interval_s: str) -> Path:
    scenario = tmp_path / f"scenario-{decision_interval_s}"
    scenario.mkdir(parents=True)
    (scenario / "run.ini").write_text(_edit_ini(
        RUN_CONFIG.read_text(),
        duration_s="0.7",
        decision_interval_s=decision_interval_s,
        buildings_file="buildings.json",
    ))
    (scenario / "buildings.json").write_text(json.dumps(BUILDINGS, indent=2) + "\n")

    nodes = json.loads((FIXTURE / "nodes.json").read_text())
    by_id = {node["id"]: node for node in nodes}
    by_id["node-c"]["position"]["x"] = 97.4
    node_a = by_id["node-a"]
    node_a.pop("random_walk", None)
    node_a["mobility"] = "constant_velocity"
    node_a["velocity"] = {"vx": 0.0, "vy": 0.0, "vz": 0.0}
    (scenario / "nodes.json").write_text(json.dumps(nodes, indent=2) + "\n")
    return scenario / "run.ini"


def test_partial_windows_clipping_and_reward_mean(tmp_path):
    coarse_config = _combined_scenario(tmp_path, "0.3")
    fine_config = _combined_scenario(tmp_path, "0.1")

    _, coarse_messages = _run_binary(
        coarse_config, tmp_path / "coarse", [_action(a) for a in COARSE_ACTIONS])
    fine_lines = [_action(action)
                  for action, window in zip(COARSE_ACTIONS, COARSE_WINDOWS)
                  for _ in range(window)]
    _, fine_messages = _run_binary(fine_config, tmp_path / "fine", fine_lines)

    coarse, fine = _steps(coarse_messages), _steps(fine_messages)
    assert [s["tick"] for s in coarse] == [0, 3, 6, 7]
    assert [s["ticks_in_step"] for s in coarse] == [1, 3, 3, 1]
    assert [s["tick"] for s in fine] == list(range(8))
    assert [s["ticks_in_step"] for s in fine] == [1] * 8
    assert coarse[-1]["done"] and fine[-1]["done"]

    # node-c: east until it clips exactly at x_max, then west, then hold.
    fine_x = [_slot_xy(s["obs"], 1)[0] for s in fine]
    assert fine_x == [97.4, 98.4, 99.4, 100.0, 99.0, 98.0, 97.0, 97.0]
    assert max(fine_x) <= 100.0

    # Same scripted commands, same trajectory at the shared ticks.
    for step in coarse:
        assert step["obs"] == fine[step["tick"]]["obs"]

    # Reward over a window is the mean of the per-tick rewards, reset excluded.
    fine_rewards = [s["reward"] for s in fine]
    windows, start = [], 1
    for length in COARSE_WINDOWS:
        windows.append(fine_rewards[start:start + length])
        start += length
    assert any(len(set(window)) > 1 for window in windows), (
        f"fine rewards {fine_rewards} are constant; the setup no longer varies LOS "
        "and cannot demonstrate averaging"
    )
    for step, window in zip(coarse[1:], windows):
        assert step["reward"] == pytest.approx(statistics.fmean(window), abs=1e-9)
