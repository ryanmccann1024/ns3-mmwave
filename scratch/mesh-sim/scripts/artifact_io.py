"""Dependency-free JSON file I/O, content hashes, and UTC timestamps."""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path: str | Path, payload) -> None:
    """Write JSON atomically so a reader never sees a half-written file."""
    path = Path(path)
    temp = path.with_name(path.name + ".tmp")
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def canonical_sha256(payload) -> str:
    """SHA-256 of sorted-key, whitespace-free JSON."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
