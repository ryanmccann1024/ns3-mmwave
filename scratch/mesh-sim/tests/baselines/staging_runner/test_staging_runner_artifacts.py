"""artifacts.py: status transition table, write-once plan, atomic JSON, ELF runtime identity.

Contract: scripts/baselines/README.md manifest table -- `status` "preparing -> prepared ->
running -> complete, or failed / interrupted at any step"; `channel_runtime_sha256`
"aggregate hash of the binary plus the ns-3 core/network/mobility/propagation/buildings
libraries it loads (the binary alone if none are dynamic)"; baseline-plan.json is
written once ("rename the directory to effective-inputs/ once"). The existing provenance
tests stub `linked_libraries`; here the ELF/ldd parsing itself is exercised with canned
`ldd` output.
"""

import itertools
import shutil
from pathlib import Path

import pytest

from scripts.baselines import artifacts

ORDER = ("preparing", "prepared", "running", "complete")
LEGAL = {("preparing", "prepared"), ("prepared", "running"), ("running", "complete")} | {
    (src, dst) for src in ("preparing", "prepared", "running")
    for dst in ("failed", "interrupted")}


def _manifest_at(path: Path, status: str) -> None:
    manifest = artifacts.new_manifest("standalone", "none", "none", "none")
    manifest["status"] = status
    artifacts.write_json(path, manifest)


@pytest.mark.parametrize("src,dst", list(itertools.product(artifacts.STATUSES,
                                                           artifacts.STATUSES)))
def test_status_transition_table(tmp_path, src, dst):
    path = tmp_path / "baseline_manifest.json"
    _manifest_at(path, src)
    if (src, dst) in LEGAL:
        manifest = artifacts.set_status(path, dst)
        assert manifest["status"] == dst
        assert (manifest["ended_at"] is not None) == (dst in artifacts.TERMINAL_STATUSES)
    else:
        with pytest.raises(ValueError, match="illegal"):
            artifacts.set_status(path, dst)
        assert artifacts.read_json(path)["status"] == src


def test_new_manifest_starts_preparing_with_version_2():
    manifest = artifacts.new_manifest("evaluation", "hold", "geometric", "none")
    assert (manifest["baseline_manifest_version"], manifest["status"]) == (2, "preparing")
    assert (manifest["mode"], manifest["executor"], manifest["method"],
            manifest["requested_algorithm"]) == ("evaluation", "hold", "geometric", "none")
    assert manifest["seeds"] == [] and manifest["ended_at"] is None
    assert manifest["fingerprint"] is None


def test_plan_is_written_once(tmp_path):
    path = tmp_path / artifacts.PLAN_NAME
    artifacts.write_plan(path, {"baseline_plan_version": 2})
    with pytest.raises(FileExistsError):
        artifacts.write_plan(path, {"baseline_plan_version": 3})
    assert artifacts.read_json(path) == {"baseline_plan_version": 2}


def test_build_plan_totals_displacement():
    nodes = [{"id": "a", "displacement_m": 1.5}, {"id": "b", "displacement_m": 0.0},
             {"id": "c", "displacement_m": 2.25}]
    plan = artifacts.build_plan("geometric", "coverage", nodes, {"p": 1})
    assert plan == {"baseline_plan_version": 2, "method": "geometric",
                    "objective": "coverage", "nodes": nodes,
                    "initial_displacement_m_total": 3.75, "planner_predictions": {"p": 1}}


def test_write_json_failure_keeps_the_old_file_and_no_temp(tmp_path):
    path = tmp_path / "m.json"
    artifacts.write_json(path, {"ok": 1})
    with pytest.raises(ValueError):
        artifacts.write_json(path, {"bad": float("nan")})
    assert artifacts.read_json(path) == {"ok": 1}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["m.json"]


def test_run_relative_is_posix_and_relative(tmp_path):
    root = tmp_path / "eval" / "geometric" / "baseline"
    root.mkdir(parents=True)
    assert artifacts.run_relative(root / "a" / "b.json", root) == "a/b.json"
    assert artifacts.run_relative(tmp_path / "eval" / "eval_manifest.json", root) == (
        "../../eval_manifest.json")


# --- channel runtime identity through ldd -------------------------------------------------

MODULE_FILES = {module: f"libns3.42-{module}-default.so"
                for module in (*artifacts.CHANNEL_MODULES, "lte", "mmwave")}


def _fake_elf(tmp_path: Path) -> tuple[Path, dict]:
    binary = tmp_path / "bin" / "ns3.42-sim-default"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"\x7fELF fake simulator")
    libs = {}
    for module, name in MODULE_FILES.items():
        lib = tmp_path / "lib" / name
        lib.parent.mkdir(exist_ok=True)
        lib.write_bytes(f"lib {module}".encode())
        libs[module] = lib
    return binary, libs


def _ldd(libs: dict, override: dict | None = None) -> str:
    lines = ["\tlinux-vdso.so.1 (0x00007ffd)",
             "\tlibc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x00007f00)"]
    for module, path in libs.items():
        target = (override or {}).get(module, f"{path} (0x00007f01)")
        lines.append(f"\t{path.name} => {target}")
    return "\n".join(lines) + "\n"


def test_elf_identity_hashes_exactly_the_channel_libraries(tmp_path, monkeypatch):
    binary, libs = _fake_elf(tmp_path)
    monkeypatch.setattr(artifacts, "_run_tool", lambda command, env=None: _ldd(libs))
    first = artifacts.channel_runtime_identity(binary)
    assert first["files"] == [str(binary.resolve())] + [
        str(libs[m].resolve()) for m in artifacts.CHANNEL_MODULES]
    expected = artifacts._aggregate(
        [("binary", artifacts.sha256_file(binary))]
        + [(f"ns3-{m}", artifacts.sha256_file(libs[m])) for m in artifacts.CHANNEL_MODULES])
    assert first["sha256"] == expected

    libs["mmwave"].write_bytes(b"rebuilt mmwave")
    libs["lte"].write_bytes(b"rebuilt lte")
    assert artifacts.channel_runtime_identity(binary)["sha256"] == first["sha256"]
    for module in artifacts.CHANNEL_MODULES:
        original = libs[module].read_bytes()
        libs[module].write_bytes(original + b" rebuilt")
        assert artifacts.channel_runtime_identity(binary)["sha256"] != first["sha256"], module
        libs[module].write_bytes(original)
    binary.write_bytes(b"\x7fELF rebuilt simulator")
    assert artifacts.channel_runtime_identity(binary)["sha256"] != first["sha256"]


def test_elf_unresolved_library_is_an_error(tmp_path, monkeypatch):
    binary, libs = _fake_elf(tmp_path)
    monkeypatch.setattr(artifacts, "_run_tool", lambda command, env=None: _ldd(
        libs, {"propagation": "not found"}))
    with pytest.raises(artifacts.RuntimeIdentityError, match="propagation"):
        artifacts.channel_runtime_identity(binary)


def test_elf_missing_channel_module_is_an_error(tmp_path, monkeypatch):
    binary, libs = _fake_elf(tmp_path)
    partial = {m: p for m, p in libs.items() if m != "buildings"}
    monkeypatch.setattr(artifacts, "_run_tool", lambda command, env=None: _ldd(partial))
    with pytest.raises(artifacts.RuntimeIdentityError, match="buildings"):
        artifacts.channel_runtime_identity(binary)


@pytest.mark.parametrize("name,module", [
    ("libns3.42-core-default.so", "core"),
    ("libns3.42-buildings.so", "buildings"),
    ("libns3-dev-mobility-debug.so", "mobility"),
    ("libns3.40-propagation-optimized.so.1.2", "propagation"),
    ("libns3.42-network-release.dylib", "network"),
    ("libns3.42-point-to-point-default.so", "point-to-point"),
])
def test_ns3_library_names(name, module):
    match = artifacts._NS3_LIBRARY.search(name)
    assert match is not None and match.group("module") == module


@pytest.mark.skipif(shutil.which("ldd") is None or not Path("/bin/true").is_file(),
                    reason="BLOCKED: needs ldd and /bin/true")
def test_real_elf_without_ns3_libraries_is_the_binary_alone(tmp_path):
    binary = tmp_path / "plain-elf"
    shutil.copyfile("/bin/true", binary)
    binary.chmod(0o755)
    identity = artifacts.channel_runtime_identity(binary)
    assert identity["files"] == [str(binary.resolve())]
    assert identity["sha256"] == artifacts._aggregate(
        [("binary", artifacts.sha256_file(binary))])
