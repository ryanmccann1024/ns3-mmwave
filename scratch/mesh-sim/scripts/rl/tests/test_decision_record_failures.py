"""Decision-record helpers, recorder file formats, caps, and failure isolation.

Spec: src/rl/decision-records.md (Files, Masks and hashes, Requested/revalidated/
applied, Sampling/caps/coverage/status, Failure isolation) and scripts/rl/env/
CLAUDE.md ("recorder failures must never raise into the env").
"""

import json
import warnings
from pathlib import Path


from scripts.rl.env.decision_settings import resolve_decision_records
from scripts.rl.env import decisions
from scripts.rl.env.decisions import DECISIONS_FILE, DECISIONS_MANIFEST, DecisionContext, DecisionRecorder, DecisionRecording
from scripts.rl.env.mesh_env import MeshRlEnv
from scripts.rl.env.selection import resolve_selection

HOLD = 4
TRAINING = DecisionContext(mode="training", source="train")
EVALUATION = DecisionContext(mode="evaluation", source="evaluate", policy="hold")
SLOT_NODE_IDS = ["node-b", "node-c", None]
CONTRACT = {
    "contract": "mesh_move_2d_v2",
    "node_ids": ["node-a", "node-b", "node-c"],
    "slot_node_ids": SLOT_NODE_IDS,
    "action_meanings": ["west", "east", "south", "north", "hold"],
    "tick_s": 0.1,
    "decision_interval_ticks": 5,
    "num_decisions": 4,
}
OBS_SCHEMA = {"schema_id": "local_links_v1", "dtype": "float32", "obs_dim": 4,
              "sha256": "0" * 64}
REWARD_SCHEMA = {"sha256": "1" * 64}
EPISODE = {"dir_name": "episode-0000", "index": 0, "seed": 7, "seed_source": "cli"}
MASK = [1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 0, 0, 0, 0, 1]


# --- Settings ---------------------------------------------------------------------


# --- Pure helpers -------------------------------------------------------------------


# --- Recorder: files and formats --------------------------------------------------


# --- Recorder: ordering errors (raised to the caller, which isolates them) ----------


# --- Recorder: byte cap boundaries --------------------------------------------------


# --- Recorder: close / fail lifecycle -----------------------------------------------


# --- Failure isolation through MeshRlEnv (fake simulator) -------------------------

def _env(sim_binary, run_config, out_dir):
    selection = resolve_selection(run_config, telemetry="steps")
    records = DecisionRecording(resolve_decision_records(enabled=True), TRAINING)
    return MeshRlEnv(sim_binary, run_config, output_dir=str(out_dir),
                     selection=selection, decision_records=records)


def _run_to_done(env) -> int:
    env.reset()
    steps, done = 0, False
    while not done:
        _, _, done, _, _ = env.step([HOLD, HOLD, HOLD])
        steps += 1
    return steps


def _isolated_run(sim_binary, run_config, out_dir):
    env = _env(sim_binary, run_config, out_dir)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            steps = _run_to_done(env)
        finally:
            env.close()
    runtime = [w for w in caught if issubclass(w.category, RuntimeWarning)
               and "Decision records" in str(w.message)]
    episode = Path(out_dir) / "episode-0000"
    rl_episode = json.loads((episode / "rl_episode.json").read_text())
    return steps, runtime, episode, rl_episode


def test_recorder_open_failure_does_not_reach_the_env(sim_binary, multi_run_config,
                                                     tmp_path, monkeypatch):
    real_open = open

    def failing_open(path, *args, **kwargs):
        if str(path).endswith(DECISIONS_FILE):
            raise PermissionError("injected open failure")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(decisions, "open", failing_open, raising=False)
    steps, runtime, episode, rl_episode = _isolated_run(sim_binary, multi_run_config,
                                                        tmp_path / "rl")
    assert steps == 2 and rl_episode["status"] == "completed"
    assert len(runtime) == 1
    data = json.loads((episode / DECISIONS_MANIFEST).read_text())
    assert data["status"] == "failed" and "injected open failure" in data["error"]
    assert (episode / "steps.jsonl").is_file()


def test_close_failure_does_not_reach_the_env(sim_binary, multi_run_config, tmp_path,
                                              monkeypatch):
    def broken_close(self, *args, **kwargs):
        raise OSError("injected close failure")

    monkeypatch.setattr(DecisionRecorder, "close", broken_close)
    steps, runtime, episode, rl_episode = _isolated_run(sim_binary, multi_run_config,
                                                        tmp_path / "rl")
    assert steps == 2 and rl_episode["status"] == "completed"
    assert len(runtime) == 1
    data = json.loads((episode / DECISIONS_MANIFEST).read_text())
    assert data["status"] == "failed" and "injected close failure" in data["error"]
