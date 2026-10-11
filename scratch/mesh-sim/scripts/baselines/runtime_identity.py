"""Fingerprint planner sources and the simulator's linked runtime."""

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from scripts.artifact_io import sha256_file
from scripts.sim_support import find_mesh_root, simulator_env

CHANNEL_MODULES = ("core", "network", "mobility", "propagation", "buildings")
_NS3_LIBRARY = re.compile(
    r"^libns3(\.[0-9]+|-dev)?-(?P<module>[a-z0-9-]+?)"
    r"(-(debug|default|release|optimized))?\.(dylib|so)(\.[0-9.]+)?$"
)
_MACHO_MAGICS = {
    bytes.fromhex(m)
    for m in ("feedface", "feedfacf", "cefaedfe", "cffaedfe", "cafebabe", "bebafeca")
}
_ELF_MAGIC = b"\x7fELF"


class RuntimeIdentityError(RuntimeError):
    """The simulator binary's channel libraries cannot be resolved and hashed."""


def _aggregate(entries: list[tuple[str, str]]) -> str:
    listing = "".join(f"{digest}  {name}\n" for name, digest in entries)
    return hashlib.sha256(listing.encode("utf-8")).hexdigest()


def planner_code_identity(package_dir: str | Path | None = None) -> dict:
    """Per-file and aggregate SHA-256 of the adapted planner modules."""
    package_dir = Path(package_dir) if package_dir else Path(__file__).resolve().parent
    source_files = sorted(
        p.relative_to(package_dir).as_posix()
        for p in package_dir.rglob("*.py")
        if "tests" not in p.relative_to(package_dir).parts
    )
    source_files += ["../artifact_io.py", "../sim_support.py"]
    missing = [name for name in source_files if not (package_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"adapted planner modules missing under {package_dir}: " f"{', '.join(missing)}"
        )
    files = {name: sha256_file(package_dir / name) for name in source_files}
    return {"files": files, "aggregate_sha256": _aggregate(list(files.items()))}


def _object_format(path: Path) -> str | None:
    with open(path, "rb") as handle:
        head = handle.read(4)
    if head == _ELF_MAGIC:
        return "elf"
    return "macho" if head in _MACHO_MAGICS else None


def _run_tool(command: list[str], env: dict | None = None) -> str:
    if shutil.which(command[0]) is None:
        raise RuntimeIdentityError(
            f"'{command[0]}' is needed to resolve the simulator's "
            "shared libraries but is not on PATH"
        )
    result = subprocess.run(
        command, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeIdentityError(f"{' '.join(command)} failed: {result.stderr.strip()}")
    return result.stdout


def _macho_rpaths(image: Path) -> list[str]:
    rpaths, in_rpath = [], False
    for line in _run_tool(["otool", "-l", str(image)]).splitlines():
        text = line.strip()
        if text.startswith("cmd "):
            in_rpath = text == "cmd LC_RPATH"
        elif in_rpath and text.startswith("path "):
            rpaths.append(text[5:].rsplit(" (offset", 1)[0])
    return rpaths


def _macho_libraries(binary: Path, env: dict) -> list[Path]:
    """Resolve ns-3 install names with the declaring image's run-path stack."""
    env_dirs = [Path(d) for d in env.get("DYLD_LIBRARY_PATH", "").split(os.pathsep) if d]
    found: dict[str, Path] = {}
    pending, seen = [(binary, ())], set()

    def expand(name: str, declaring_image: Path) -> Path:
        name = name.replace("@loader_path", str(declaring_image.parent)).replace(
            "@executable_path", str(binary.parent)
        )
        return Path(name)

    while pending:
        image, inherited = pending.pop()
        if image in seen:
            continue
        seen.add(image)
        rpaths = tuple(expand(p, image) for p in _macho_rpaths(image)) + inherited
        for line in _run_tool(["otool", "-L", str(image)]).splitlines()[1:]:
            name = line.strip().split(" (compatibility", 1)[0]
            leaf = name.rsplit("/", 1)[-1]
            if not leaf.startswith("libns3"):
                continue
            candidates = [directory / leaf for directory in env_dirs]
            if name.startswith("@rpath/"):
                relative = name.removeprefix("@rpath/")
                candidates.extend(directory / relative for directory in rpaths)
            else:
                candidates.append(expand(name, image))
            resolved = next((c.resolve() for c in candidates if c.is_file()), None)
            if resolved is None:
                raise RuntimeIdentityError(f"cannot resolve {name} needed by {image}")
            previous = found.setdefault(leaf, resolved)
            if previous != resolved:
                raise RuntimeIdentityError(f"linked ns-3 libraries have ambiguous basename {leaf}")
            pending.append((resolved, rpaths))
    return list(found.values())


def _elf_libraries(binary: Path, env: dict) -> list[Path]:
    found = []
    for line in _run_tool(["ldd", str(binary)], env).splitlines():
        name, arrow, rest = line.strip().partition(" => ")
        if not arrow or not name.startswith("libns3"):
            continue
        target = rest.split(" (", 1)[0].strip()
        if target == "not found" or not target:
            raise RuntimeIdentityError(f"ldd cannot resolve {name} for {binary}")
        found.append(Path(target).resolve())
    return found


def linked_libraries(binary: str | Path) -> list[Path]:
    """Dynamically linked ns-3 libraries of the simulator binary; empty when none."""
    binary = Path(binary).resolve()
    kind = _object_format(binary)
    if kind is None:
        return []
    env = simulator_env(find_mesh_root())
    return _macho_libraries(binary, env) if kind == "macho" else _elf_libraries(binary, env)


def channel_runtime_identity(binary: str | Path) -> dict:
    """Aggregate SHA-256 of the binary and the ns-3 channel-path libraries it loads."""
    binary = Path(binary).resolve()
    libraries = linked_libraries(binary)
    channel = {}
    for path in libraries:
        match = _NS3_LIBRARY.search(path.name)
        if match and match.group("module") in CHANNEL_MODULES:
            channel[match.group("module")] = path
    if libraries and set(channel) != set(CHANNEL_MODULES):
        missing = sorted(set(CHANNEL_MODULES) - set(channel))
        raise RuntimeIdentityError(
            f"{binary} links ns-3 dynamically but its "
            f"{', '.join(missing)} libraries were not found; the "
            "channel identity would omit them"
        )
    entries = [("binary", sha256_file(binary))]
    resolved = sorted(set(libraries), key=lambda p: p.name)
    if len({p.name for p in resolved}) != len(resolved):
        raise RuntimeIdentityError("linked ns-3 libraries have ambiguous basenames")
    entries += [(path.name, sha256_file(path)) for path in resolved]
    return {"sha256": _aggregate(entries), "files": [str(binary)] + [str(p) for p in resolved]}
