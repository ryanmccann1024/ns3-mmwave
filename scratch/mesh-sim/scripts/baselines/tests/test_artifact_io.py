"""Atomic artifact failures and dependency-free imports."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import artifact_io
from scripts.baselines import artifacts


@pytest.mark.parametrize("existing", (False, True))
def test_replace_failure_preserves_destination_and_removes_temp(tmp_path, monkeypatch, existing):
    path = tmp_path / "manifest.json"
    original = b'{"original": true}\n'
    if existing:
        path.write_bytes(original)

    def fail_replace(source, destination):
        assert Path(source).read_text() == '{\n  "updated": true\n}\n'
        raise OSError("replacement failed")

    monkeypatch.setattr(artifact_io.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replacement failed"):
        artifacts.write_json(path, {"updated": True})
    if existing:
        assert path.read_bytes() == original
    else:
        assert not path.exists()
    assert not path.with_name(path.name + ".tmp").exists()


@pytest.mark.parametrize("invalid", (float("nan"), float("inf"), object()))
def test_serialization_failure_preserves_existing_bytes(tmp_path, invalid):
    path = tmp_path / "manifest.json"
    original = b'{"original": true}\n'
    path.write_bytes(original)
    with pytest.raises((ValueError, TypeError)):
        artifact_io.write_json(path, {"value": invalid})
    assert path.read_bytes() == original
    assert not path.with_name(path.name + ".tmp").exists()


def test_baseline_and_rl_share_the_atomic_writer(tmp_path):
    from scripts.rl import cli_common

    assert artifacts.write_json is cli_common.write_json is artifact_io.write_json
    assert artifacts.sha256_file is cli_common.sha256_file is artifact_io.sha256_file
    assert artifacts.now_iso is cli_common.now_iso is artifact_io.now_iso
    path = tmp_path / "manifest.json"
    cli_common.write_json(path, {"name": "café", "value": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"name": "café", "value": 2}
    assert not path.with_name(path.name + ".tmp").exists()


def test_baseline_imports_need_no_rl_or_planner_dependencies():
    root = Path(__file__).resolve().parents[3]
    code = '''
import builtins
original_import = builtins.__import__
blocked = {"torch", "gymnasium", "sb3_contrib", "numpy", "pydantic", "shapely", "pyproj", "yaml"}
def guarded(name, *args, **kwargs):
    if name.split(".")[0] in blocked:
        raise AssertionError("unexpected dependency: " + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded
from scripts.baselines import artifacts, config, effective_inputs, mapping
from scripts import artifact_io
assert artifacts.write_json is artifact_io.write_json
assert config.Mapping is mapping.Mapping
'''
    subprocess.run([sys.executable, "-c", code], cwd=root, check=True,
                   capture_output=True, text=True)
