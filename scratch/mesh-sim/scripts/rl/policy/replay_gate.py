"""Native saved-action replay gate: rerun recorded actions and require identical physics.

A replay passes only when the episode completes, every replayed action is still
valid under the native mask, the decision count matches, and every decision's
facts (within 1e-9), mask and observation hash match the source telemetry. Any
change stops the run; a zero exit code alone is never success.

Two comparison variants are preserved by name:

- ``strict_v1`` -- facts compared exactly as recorded (Phase 8/9 gates).
- ``pre_contact_source_v1`` -- the replayed facts drop
  ``safety.boundary_contacted_slots`` first, because the source telemetry
  predates that native field (Phase 3 gate).
"""
import copy
import json
from pathlib import Path

import numpy as np

from scripts.artifact_io import now_iso, sha256_file, write_json

REPLAY_GATE_VERSION = 2
REPLAY_GATE_FILE = "replay_gate.json"
_TOLERANCE = 1e-9


def facts_close(a, b):
    if isinstance(a, dict):
        return isinstance(b, dict) and a.keys() == b.keys() and all(facts_close(v, b[k]) for k, v in a.items())
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(facts_close(x, y) for x, y in zip(a, b))
    if isinstance(a, (float, int)) and not isinstance(a, bool):
        return isinstance(b, (float, int)) and abs(a - b) <= _TOLERANCE
    return a == b


class ReplayPolicy:
    """Replays the source episode's sent actions; a now-masked action stops the replay."""

    name = "model"

    def __init__(self, rows):
        self.actions = [r["action_sent"] for r in rows if r["decision"] > 0]
        self.index = 0

    def act(self, obs, mask, contract):
        action = np.asarray(self.actions[self.index], dtype=np.int64)
        self.index += 1
        if any(not mask[5 * i + a] for i, a in enumerate(action)):
            raise ValueError("native replay mask changed")
        return action


def compare_rows(before, after, label):
    if len(before) != len(after):
        raise ValueError(f"{label}: native replay decision count changed")
    for a, b in zip(before, after):
        if not facts_close(a["facts"], b["facts"]) or a["mask"] != b["mask"] or a["obs_sha256"] != b["obs_sha256"]:
            raise ValueError(f"{label}: native facts/masks/observations changed at decision {b['decision']}")


def compare_rows_pre_contact_source(before, after, label):
    if len(before) != len(after):
        raise ValueError(f"{label}: native replay decision count changed")
    for a, b in zip(before, after):
        aa, bb = copy.deepcopy(a["facts"]), copy.deepcopy(b["facts"])
        bb["safety"].pop("boundary_contacted_slots", None)
        if not facts_close(aa, bb) or a["mask"] != b["mask"] or a["obs_sha256"] != b["obs_sha256"]:
            raise ValueError(f"{label}: native facts/masks/observations changed at decision {b['decision']}")


COMPARISONS = {"strict_v1": compare_rows, "pre_contact_source_v1": compare_rows_pre_contact_source}


def run_replay_gate(source_episode_dir, configs, case, seed, output_dir, sim_binary, *, bundle=None,
                    comparison="strict_v1", contact_audit=False, label="saved-action native replay gate", band=None):
    """Replay one source episode for one seed; write ``replay_gate.json``; raise on any change.

    Paths in the record are relative to ``output_dir`` except the source episode,
    which is an immutable input and is identified by its telemetry SHA-256.
    """
    from scripts.rl.policy.evaluate import PolicySpec, Prepared, evaluate
    from scripts.rl.policy.mission_metrics import read_episode
    from scripts.rl.env.seeded_env import resolve_band
    from scripts.rl.policy.operation import DiagnosticEnv
    if comparison not in COMPARISONS:
        raise ValueError(f"unknown replay comparison {comparison!r}; expected one of {sorted(COMPARISONS)}")
    output, source = Path(output_dir), Path(source_episode_dir)
    output.mkdir(parents=True, exist_ok=True)
    target = output / REPLAY_GATE_FILE
    record = dict(replay_gate_version=REPLAY_GATE_VERSION, status="running", started_at=now_iso(), seed=int(seed),
                  comparison=comparison, telemetry_only=True, case=case,
                  parent=bundle.describe() if bundle else None, contact_audit=bool(contact_audit),
                  source_episode_dir=str(source),
                  source_steps_sha256=sha256_file(source / "steps.jsonl"), binary_sha256=sha256_file(sim_binary))
    write_json(target, record)
    try:
        _, before = read_episode(source)

        def build(env, seed):
            initial = env.reset(seed=seed, options={"seed_source": "eval"})
            return Prepared(ReplayPolicy(before), initial, dict(saved_action_replay=True, weights_frozen=True))
        envs = []

        def environment(policy):
            env = DiagnosticEnv(sim_binary, configs, output / "model", case, bundle=bundle,
                                initial_seed=seed, band=band)
            envs.append(env)
            return env

        manifest = evaluate(environment,
                            [PolicySpec("model", build)], [seed], output,
                            dict(label=label, band=resolve_band(configs[str(seed)], band)[0], held_out=False))
        if manifest["status"] != "completed":
            raise RuntimeError(f"seed {seed}: native replay execution did not complete")
        episode = manifest["policies"]["model"]["episodes"][0]
        header, after = read_episode(episode["episode_dir"])
        if contact_audit:
            from scripts.rl.policy.episode_review import contact_audit as audit_contact
            record["boundary"] = audit_contact(header, after)
        record["compatibility"] = [entry for env in envs for entry in env.compatibility]
        timing = Path(episode["episode_dir"]) / "event_timing.json"
        record["event_timing"] = json.loads(timing.read_text()) if timing.is_file() else None
        COMPARISONS[comparison](before, after, f"seed {seed}")
        record.update(status="passed", matched=True, decisions=len(after),
                      episode_dir=Path(episode["episode_dir"]).relative_to(output).as_posix(),
                      replay_steps_sha256=sha256_file(Path(episode["episode_dir"]) / "steps.jsonl"),
                      eval_manifest="eval_manifest.json", ended_at=now_iso())
        write_json(target, record)
        return record
    except BaseException as exc:
        record.update(status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed", matched=False,
                      ended_at=now_iso(), error=f"{type(exc).__name__}: {exc}")
        write_json(target, record)
        raise


def gate_passed(output_dir):
    """The owner's success criterion for a finished gate directory."""
    path = Path(output_dir) / REPLAY_GATE_FILE
    if not path.is_file():
        return False
    record = json.loads(path.read_text())
    return (record.get("replay_gate_version") in (1, REPLAY_GATE_VERSION) and record.get("status") == "passed"
            and record.get("matched") is True)
