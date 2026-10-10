"""Optional per-decision telemetry: steps.jsonl writing and replay."""

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .observations import get_preset, observation_schema
from .protocol import CentralizedProtocol
from .rewards import RewardBreakdown, RewardComposer, reward_schema

TELEMETRY_VERSION = 3
TELEMETRY_FILE = "steps.jsonl"
_FLUSH_EVERY = 32
_TOTAL_TOL = 1e-9
_DTYPES = {"float32": "<f4", "float64": "<f8"}


def obs_sha256(obs, dtype=None) -> str:
    """Hash the observation as contiguous little-endian bytes of the schema dtype."""
    array = np.asarray(obs)
    named = array.dtype if dtype is None else _DTYPES.get(str(dtype), dtype)
    target = np.dtype(named).newbyteorder("<")
    return hashlib.sha256(
        np.ascontiguousarray(array, dtype=target).tobytes()
    ).hexdigest()


class StepRecorder:
    """Buffered JSONL writer for saved decisions; no wall-clock fields."""

    def __init__(self, path, every: int = 1):
        if int(every) < 1:
            raise ValueError(f"telemetry_every must be >= 1, got {every!r}")
        self.path = Path(path)
        self.every = int(every)
        self._handle = open(self.path, "w")
        self._pending = 0
        self._records = 0

    @property
    def records(self) -> int:
        return self._records

    def should_save(self, decision: int, done: bool) -> bool:
        """Always save reset; then every kth decision plus the terminal one."""
        if decision == 0:
            return True
        return decision % self.every == 0 or bool(done)

    def write_header(self, header: dict) -> None:
        self._write(header)
        self._flush()

    def append(self, record: dict) -> None:
        self._write(record)
        self._records += 1
        self._pending += 1
        if self._pending >= _FLUSH_EVERY:
            self._flush()

    def close(self) -> None:
        if self._handle is None:
            return
        handle, self._handle = self._handle, None
        try:
            handle.flush()
        finally:
            handle.close()

    def _write(self, payload: dict) -> None:
        if self._handle is None:
            raise ValueError(f"telemetry recorder for {self.path} is closed")
        self._handle.write(json.dumps(payload, allow_nan=False, sort_keys=True) + "\n")

    def _flush(self) -> None:
        if self._handle is not None:
            self._handle.flush()
            self._pending = 0


def make_header(contract: dict, selection_describe: dict, observation_schema: dict,
                reward_schema: dict) -> dict:
    """Line 1 of steps.jsonl: everything replay needs besides the records."""
    return {
        "type": "header",
        "telemetry_version": TELEMETRY_VERSION,
        "contract": dict(contract),
        "selection": selection_describe,
        "observation_schema": observation_schema,
        "reward_schema": reward_schema,
    }


def reward_field(reward) -> dict | None:
    if reward is None:
        return None
    if isinstance(reward, RewardBreakdown):
        return {"total": reward.total, "components": dict(reward.components),
                "valid": dict(reward.valid)}
    if isinstance(reward, dict):
        return dict(reward)
    return {"total": float(reward), "source": "cpp"}


def make_record(decision: int, tick: int, time_s: float, ticks_in_step: int,
                action_sent, mask, revalidated_slots, facts: dict,
                legacy_reward: float, reward, obs,
                reward_context: dict | None = None) -> dict:
    """One saved decision; `reward` is None (reset), a RewardBreakdown, or msg.reward."""
    return {
        "type": "step",
        "decision": int(decision),
        "tick": int(tick),
        "time_s": float(time_s),
        "ticks_in_step": int(ticks_in_step),
        "scored_ticks": int(facts["window"]["scored_ticks"]),
        "action_sent": None if action_sent is None else [int(a) for a in action_sent],
        "mask": [int(m) for m in mask],
        "revalidated_slots": [int(s) for s in revalidated_slots],
        "facts": facts,
        "legacy_reward": float(legacy_reward),
        "reward": reward_field(reward),
        "reward_context": reward_context,
        "obs_sha256": obs_sha256(obs),
    }


@dataclass(frozen=True)
class ReplaySummary:
    """Replay outcome for one steps.jsonl file."""

    records: int
    obs_mismatches: int
    reward_mismatches: int


def replay_record(header: dict, record: dict):
    """Rebuild the saved observation and, for composed policy steps, the reward."""
    contract = header["contract"]
    preset = get_preset(header["observation_schema"]["schema_id"],
                        header["selection"]["observation_parameters"])
    obs = preset.build(record["facts"], contract)

    reward_schema = header.get("reward_schema") or {}
    saved = record.get("reward")
    if (saved is None or reward_schema.get("authority") != "python"
            or record["decision"] == 0):
        return obs, None
    composer = RewardComposer(reward_schema["components"], reward_schema["weights"],
                              header["selection"]["reward_parameters"])
    return obs, composer.compose(record["facts"]["window"], record["legacy_reward"],
                                 contract, composer.context(record["facts"], contract, record.get("reward_context")))


def _load_line(line: str) -> dict:
    payload = json.loads(line)
    def check(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Telemetry values must be finite")
        if isinstance(value, dict):
            for entry in value.values():
                check(entry)
        elif isinstance(value, list):
            for entry in value:
                check(entry)
    check(payload)
    if not isinstance(payload, dict):
        raise ValueError("Telemetry lines must be JSON objects")
    return payload


def _validate_header(header: dict) -> CentralizedProtocol:
    if header.get("type") != "header":
        raise ValueError("Telemetry must start with a header")
    if header.get("telemetry_version") != TELEMETRY_VERSION:
        raise ValueError(f"Unsupported telemetry_version {header.get('telemetry_version')!r}")
    contract = header["contract"]
    protocol = CentralizedProtocol(contract)
    selection = header["selection"]
    expected_observation = observation_schema(selection["observation_preset"], contract, selection["observation_parameters"])
    expected_reward = reward_schema(selection["reward_components"], selection["reward_weights"], contract=contract, parameters=selection["reward_parameters"])
    if header["observation_schema"] != expected_observation:
        raise ValueError("Telemetry observation schema does not match its selection and contract")
    if header["reward_schema"] != expected_reward:
        raise ValueError("Telemetry reward schema does not match its selection and contract")
    return protocol


def replay_file(path) -> ReplaySummary:
    """Compare saved records using the declared schemas and validated raw facts."""
    records = obs_bad = reward_bad = 0
    with Path(path).open() as handle:
        lines = (line for line in handle if line.strip())
        try:
            header = _load_line(next(lines))
        except StopIteration:
            raise ValueError(f"telemetry file {path} is empty") from None
        protocol = _validate_header(header)
        dtype = header["observation_schema"]["dtype"]
        for line in lines:
            record = _load_line(line)
            if record.get("type") != "step":
                raise ValueError("Telemetry record must be a step")
            protocol.validate_facts({"facts": record["facts"],
                                     "scored_ticks": record["scored_ticks"],
                                     "reward": record["legacy_reward"]})
            records += 1
            obs, breakdown = replay_record(header, record)
            if obs_sha256(obs, dtype) != record["obs_sha256"]:
                obs_bad += 1
            if breakdown is not None:
                if abs(breakdown.total - record["reward"]["total"]) > _TOTAL_TOL:
                    reward_bad += 1
    return ReplaySummary(records, obs_bad, reward_bad)
