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


def parse_seed_spec(raw: str, distinct: bool = True) -> list[int]:
    """Expand a comma list of integers and inclusive `A-B` ranges, order preserved."""
    tokens = [token.strip() for token in str(raw).split(",") if token.strip()]
    if not tokens:
        raise ValueError("seed specification is empty")
    seeds: list[int] = []
    for token in tokens:
        low, separator, high = token.partition("-")
        try:
            start = int(low.strip())
            end = int(high.strip()) if separator else start
        except ValueError as exc:
            raise ValueError(
                f"seed {token!r} is not an integer or an A-B range: {exc}") from exc
        if start > end:
            raise ValueError(f"seed range {token!r} must have A <= B")
        seeds.extend(range(start, end + 1))
    if distinct:
        seen: set[int] = set()
        for seed in seeds:
            if seed in seen:
                raise ValueError(f"seed {seed} is listed more than once")
            seen.add(seed)
    return seeds


def strip_inline_comment(value: str) -> str:
    """Mirror the C++ INI parser's # and ; inline-comment handling."""
    for marker in ("#", ";"):
        value = value.split(marker, 1)[0]
    return value.strip()


def tail_lines(path: str | Path, count: int = 40) -> str:
    """Read only the trailing lines into memory for failure diagnostics."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        return "\n".join(line.rstrip("\r\n") for line in deque(handle, maxlen=count))
