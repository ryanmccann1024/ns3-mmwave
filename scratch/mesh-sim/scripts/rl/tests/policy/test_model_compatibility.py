"""Compatibility of historical models with the current registry."""

import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
import pytest
from scripts.sim_support import find_mesh_root


MESH_ROOT = find_mesh_root()


# Run in a fresh interpreter that refuses any phase-numbered env module, so the
# load proves the ZIP and live registries need only the functional names.
LOAD_SCRIPT = r"""
import hashlib, importlib.abc, json, re, sys
LEGACY = re.compile(r"scripts\.rl\.(env\.phase\d_|phase_|pilot_reference)")
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if LEGACY.match(name):
            raise ImportError("blocked legacy module " + name)
sys.meta_path.insert(0, Block())
mode, target = sys.argv[1], sys.argv[2]
if mode == "bundle":
    from scripts.rl.env.config import read_scenario_identity
    from scripts.rl.env.mesh_env import MeshRlEnv
    from scripts.rl.policy.bundle import load_model, read_bundle, selection_from_manifest
    from scripts.rl.policy.compat import check_compatibility
    from scripts.rl.policy.training import mask_fn
    bundle = read_bundle(target, "final")
    manifest = bundle.manifest
    run_config = sys.argv[4]
    env = MeshRlEnv(sys.argv[3], run_config, seed=1, output_dir=sys.argv[5],
                    selection=selection_from_manifest(manifest))
    try:
        env.reset()
        check_compatibility(manifest, env, live_identity=read_scenario_identity(run_config), live_band=None)
        model = load_model(bundle, env, mask_fn)
    finally:
        env.close()
else:
    from sb3_contrib import MaskablePPO
    import scripts.rl.env.observations, scripts.rl.env.rewards
    model = MaskablePPO.load(target, device="cpu")
state = model.policy.state_dict()
digest = hashlib.sha256()
for key in sorted(state):
    digest.update(key.encode()); digest.update(state[key].detach().cpu().numpy().tobytes())
print(json.dumps({"digest": digest.hexdigest(), "type": type(model).__name__,
                  "legacy_loaded": sorted(m for m in sys.modules if LEGACY.match(m))}))
"""


def _zip_digest(path):
    import torch

    with zipfile.ZipFile(path) as archive:
        state = torch.load(
            io.BytesIO(archive.read("policy.pth")),
            map_location="cpu",
            weights_only=True,
        )
    digest = hashlib.sha256()
    for key in sorted(state):
        digest.update(key.encode())
        digest.update(state[key].detach().cpu().numpy().tobytes())
    return digest.hexdigest()


def _serialized_module_refs(path):
    with zipfile.ZipFile(path) as archive:
        text = b"".join(archive.read(name) for name in archive.namelist())
    return text.count(b"scripts.rl"), text.count(b"env.phase")


def _load_in_subprocess(*args):
    result = subprocess.run(
        [sys.executable, "-c", LOAD_SCRIPT, *map(str, args)],
        cwd=MESH_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_historical_zip_deserializes_without_legacy_modules():
    """Read-only check of one real saved model; set MESH_HISTORICAL_ZIP to run it."""
    target = os.environ.get("MESH_HISTORICAL_ZIP")
    if not target:
        pytest.skip("MESH_HISTORICAL_ZIP not set")
    pytest.importorskip("sb3_contrib")
    path = Path(target)
    assert path.is_file(), path
    _, legacy_references = _serialized_module_refs(path)
    assert legacy_references == 0
    loaded = _load_in_subprocess("zip", path)
    assert loaded["digest"] == _zip_digest(path) and loaded["legacy_loaded"] == []
