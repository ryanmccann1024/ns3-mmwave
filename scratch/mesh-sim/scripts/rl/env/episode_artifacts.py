"""Episode directory allocation and versioned manifest persistence."""

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from .telemetry import TELEMETRY_FILE, StepRecorder, make_header, make_record

_EPISODE_RE = re.compile(r"^episode-(\d+)$")
_MANIFEST_VERSION = 4


class EpisodeArtifacts:
    def __init__(self, output_dir: Path):
        self._output_dir = output_dir
        self._next_index: int | None = None
        self.directory: Path | None = None
        self.manifest: dict | None = None
        self._recorder: StepRecorder | None = None
        self.action = None

    def allocate(self) -> tuple[Path, int]:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        if self._next_index is None:
            used = (int(match.group(1)) for path in self._output_dir.iterdir()
                    if (match := _EPISODE_RE.match(path.name)))
            self._next_index = max(used, default=-1) + 1
        while True:
            index = self._next_index
            self._next_index += 1
            path = self._output_dir / f"episode-{index:04d}"
            try:
                path.mkdir(exist_ok=False)
            except FileExistsError:
                continue
            self.directory = path
            return path, index

    def begin(self, index: int, seed: int, seed_source: str, command: list[str]) -> None:
        self.action = None
        self.manifest = {
            "manifest_version": _MANIFEST_VERSION,
            "episode": index,
            "seed": seed,
            "seed_source": seed_source,
            "command": list(command),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "ended_at": None,
            "status": "running",
            "exit_code": None,
            "steps": 0,
            "cumulative_reward": 0.0,
            "control_mode": "centralized",
            "contract": None,
            "decisions": 0,
            "last_tick": None,
            "scored_ticks": 0,
            "stop_reason": None,
            "escalation": None,
        }
        self.write()

    def set_contract(self, init: dict) -> None:
        assert self.manifest is not None
        self.manifest["contract"] = dict(init)
        self.write()

    def set_selection(self, selection, observation_schema: dict, reward_schema: dict) -> None:
        assert self.manifest is not None
        self.manifest.update(
            selection=selection.describe(),
            observation_schema_sha256=observation_schema["sha256"],
            reward_schema_sha256=reward_schema["sha256"],
            reward_components_sum={name: 0.0 for name in selection.reward_components},
            telemetry=None,
        )
        if selection.telemetry == "steps":
            self._recorder = StepRecorder(self.directory / TELEMETRY_FILE,
                                          selection.telemetry_every)
            self._recorder.write_header(make_header(
                self.manifest["contract"], selection.describe(), observation_schema,
                reward_schema))
            self.manifest["telemetry"] = {"file": TELEMETRY_FILE, "records": 0,
                                          "every": selection.telemetry_every}
        self.write()

    def record_reset(self, msg: dict, obs) -> None:
        """Save the reset sample without adding it to learning reward totals."""
        if self._recorder is not None:
            self._append_record(msg, None, obs)
            self.write()

    def record_step(self, msg: dict, reward: float, detail: dict | None = None) -> None:
        if self.manifest is None:
            return
        breakdown = (detail or {}).get("breakdown")
        cumulative = self.manifest["cumulative_reward"] + reward
        sums = dict(self.manifest["reward_components_sum"])
        if breakdown is not None:
            for name, value in breakdown.components.items():
                sums[name] += value
        if not math.isfinite(cumulative) or any(not math.isfinite(v) for v in sums.values()):
            raise ValueError("Episode reward totals must remain finite")
        self.manifest["steps"] += 1
        self.manifest["cumulative_reward"] = cumulative
        self.manifest["reward_components_sum"] = sums
        self.manifest["decisions"] = msg["decision"]
        self.manifest["last_tick"] = msg["tick"]
        self.manifest["scored_ticks"] += msg["scored_ticks"]
        if self._recorder is not None and self._recorder.should_save(
                msg["decision"], msg["done"]):
            self._append_record(msg, breakdown if breakdown is not None else reward,
                                (detail or {}).get("obs"))
        self.write()

    def _append_record(self, msg: dict, reward, obs) -> None:
        self._recorder.append(make_record(
            msg["decision"], msg["tick"], msg["time_s"], msg["ticks_in_step"],
            self.action, msg["mask"], msg["revalidated_slots"], msg["facts"],
            msg["reward"], reward, obs))
        if self.manifest.get("telemetry"):
            self.manifest["telemetry"]["records"] = self._recorder.records

    def close_recorder(self) -> None:
        recorder, self._recorder = self._recorder, None
        if recorder is None:
            return
        try:
            recorder.close()
        finally:
            if self.manifest is not None and self.manifest.get("telemetry"):
                self.manifest["telemetry"]["records"] = recorder.records

    def finish(self, status: str, exit_code: int | None,
               stop_reason: str | None = None, escalation: str | None = None) -> None:
        if self.manifest is None:
            return
        self.manifest.update(status=status, exit_code=exit_code,
                             ended_at=datetime.now(timezone.utc).isoformat(),
                             stop_reason=stop_reason, escalation=escalation)
        self.write()
        self.manifest = None

    def write(self) -> None:
        if self.manifest is None or self.directory is None:
            return
        path = self.directory / "rl_episode.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.manifest, indent=2, allow_nan=False) + "\n")
        temporary.replace(path)
