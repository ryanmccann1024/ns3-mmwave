"""Episode directory allocation and versioned manifest persistence."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

_EPISODE_RE = re.compile(r"^episode-(\d+)$")
_MANIFEST_VERSION = 3


class EpisodeArtifacts:
    def __init__(self, output_dir: Path):
        self._output_dir = output_dir
        self._next_index: int | None = None
        self.directory: Path | None = None
        self.manifest: dict | None = None

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
        temporary.write_text(json.dumps(self.manifest, indent=2) + "\n")
        temporary.replace(path)
