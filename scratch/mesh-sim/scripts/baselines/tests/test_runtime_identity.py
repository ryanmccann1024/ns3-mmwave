"""Runtime provenance hashes every linked ns-3 library; canned ldd output
exercises the ELF reader without requiring an ns-3 simulator build. A missing
runtime dependency cannot silently disappear from experiment identity.
"""

import shutil
from pathlib import Path

import pytest

from scripts.baselines import artifacts, runtime_identity


def test_plan_is_written_once(tmp_path):
    path = tmp_path / artifacts.PLAN_NAME
    artifacts.write_plan(path, {"baseline_plan_version": 2})
    with pytest.raises(FileExistsError):
        artifacts.write_plan(path, {"baseline_plan_version": 3})
    assert artifacts.read_json(path) == {"baseline_plan_version": 2}


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
                for module in (*runtime_identity.CHANNEL_MODULES, "lte", "mmwave")}


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


def test_elf_identity_hashes_all_linked_ns3_libraries(tmp_path, monkeypatch):
    binary, libs = _fake_elf(tmp_path)
    monkeypatch.setattr(runtime_identity, "_run_tool", lambda command, env=None: _ldd(libs))
    first = runtime_identity.channel_runtime_identity(binary)
    assert set(first["files"]) == {str(binary.resolve()), *(str(p.resolve()) for p in libs.values())}
    # Every dynamically linked ns-3 module contributes, including lte/mmwave.
    for module in libs:
        original = libs[module].read_bytes()
        libs[module].write_bytes(original + b" rebuilt")
        assert runtime_identity.channel_runtime_identity(binary)["sha256"] != first["sha256"], module
        libs[module].write_bytes(original)
    binary.write_bytes(b"\x7fELF rebuilt simulator")
    assert runtime_identity.channel_runtime_identity(binary)["sha256"] != first["sha256"]


@pytest.mark.skipif(shutil.which("ldd") is None or not Path("/bin/true").is_file(),
                    reason="BLOCKED: needs ldd and /bin/true")
def test_real_elf_without_ns3_libraries_is_the_binary_alone(tmp_path):
    binary = tmp_path / "plain-elf"
    shutil.copyfile("/bin/true", binary)
    binary.chmod(0o755)
    identity = runtime_identity.channel_runtime_identity(binary)
    assert identity["files"] == [str(binary.resolve())]
    assert identity["sha256"] == runtime_identity._aggregate(
        [("binary", artifacts.sha256_file(binary))])
