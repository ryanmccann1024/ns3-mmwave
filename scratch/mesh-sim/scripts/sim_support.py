"""Shared paths, loader environment, and diagnostics for simulator launchers."""

from collections import deque
import os
from pathlib import Path


def find_mesh_root(start: str | Path = __file__) -> Path:
    """Find the ancestor containing mesh-sim's sim.cc."""
    path = Path(start).resolve()
    directory = path.parent if path.is_file() else path
    for candidate in (directory, *directory.parents):
        if (candidate / "sim.cc").is_file():
            return candidate
    raise RuntimeError(f"Could not locate mesh-sim root from {path}")


def find_sim_binary(mesh_root: str | Path) -> str | None:
    """Return the first matching binary in the containing ns-3 build tree."""
    build = Path(mesh_root).resolve().parent.parent / "build" / "scratch" / "mesh-sim"
    matches = sorted(build.glob("ns3*-sim-*"))
    return str(matches[0]) if matches else None


def simulator_env(mesh_root: str | Path) -> dict[str, str]:
    """Copy the process environment and prepend ns-3's shared-library directory."""
    env = dict(os.environ)
    lib = str(Path(mesh_root).resolve().parent.parent / "build" / "lib")
    for variable in ("DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH"):
        parts = [part for part in env.get(variable, "").split(os.pathsep) if part]
        env[variable] = os.pathsep.join([lib, *parts])
    return env


def strip_inline_comment(value: str) -> str:
    """Mirror the C++ INI parser's # and ; inline-comment handling."""
    for marker in ("#", ";"):
        value = value.split(marker, 1)[0]
    return value.strip()


def tail_lines(path: str | Path, count: int = 40) -> str:
    """Read only the trailing lines into memory for failure diagnostics."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        return "\n".join(line.rstrip("\r\n") for line in deque(handle, maxlen=count))
