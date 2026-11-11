"""Compatibility of historical models with the current registry."""

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from functools import partial
from pathlib import Path
import pytest
from scripts.rl.env.curriculum import CurriculumEnv, load_curriculum_schedule
from scripts.rl.tests.conftest import MULTI_RUN_INI, NODES_JSON
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


MISSION_INI = MULTI_RUN_INI.replace(
    "controlled_nodes = node-b, node-c", "controlled_nodes = node-a, node-b, node-c"
).replace(
    "reward_type = all_links_los",
    "reward_type = all_links_los\ncoverage_enabled = true\n"
    "observation_preset = mission_compact_v1\nreward_components = available_target_arrival_fraction_v1\n"
    "reward_weights = 1",
) + (
    "\n[mission]\nkind = investigation\ninvestigator_id = node-b\ngoal_x = 80\ngoal_y = 40\n"
    "team_investigation = true\nteam_radius_m = 50\n"
)


def test_saved_zip_with_renamed_registry_inputs_deserializes(sim_binary, tmp_path):
    pytest.importorskip("sb3_contrib")
    from scripts.rl.agents.config import Cadence, MaskablePPOConfig
    from scripts.rl.env.selection import resolve_selection
    from scripts.rl.policy.training import train_mppo

    scenario = tmp_path / "scenario"
    scenario.mkdir()
    (scenario / "run.ini").write_text(MISSION_INI)
    (scenario / "nodes.json").write_text(NODES_JSON)
    for stage in ("near", "intermediate"):
        (scenario / stage).mkdir()
        shutil.copy(scenario / "run.ini", scenario / stage / "run.ini")
        shutil.copy(scenario / "nodes.json", scenario / stage / "nodes.json")
    (scenario / "schedule.json").write_text(
        json.dumps(
            {
                "near": "near/run.ini",
                "intermediate": "intermediate/run.ini",
                "original": "run.ini",
            }
        )
    )
    schedule = load_curriculum_schedule(scenario / "schedule.json")
    run_config = str(scenario / "run.ini")
    selection = resolve_selection(run_config)
    assert selection.observation_preset == "mission_compact_v1"
    run = tmp_path / "train"
    run.mkdir()
    cfg = MaskablePPOConfig(
        total_timesteps=8,
        n_steps=4,
        batch_size=4,
        n_epochs=1,
        net_arch=(8, 8),
        seed=101,
        verbose=0,
    )
    train_mppo(
        cfg,
        sim_binary,
        run_config,
        str(run),
        None,
        "cli",
        selection,
        Cadence(eval_every=0),
        env_factory=partial(CurriculumEnv, schedule=schedule["schedule"]),
    )
    manifest = json.loads((run / "train_manifest.json").read_text())
    assert manifest["status"] == "completed"
    resets = json.loads((run / "curriculum.json").read_text())["resets"]
    assert resets and {r["stage"] for r in resets} == {"near"}

    model_path = Path(manifest["model_path"])
    references, legacy_references = _serialized_module_refs(model_path)
    assert references == 0 and legacy_references == 0
    expected = _zip_digest(model_path)
    loaded = _load_in_subprocess(
        "bundle", run, sim_binary, run_config, tmp_path / "reload"
    )
    assert loaded == {"digest": expected, "type": "MaskablePPO", "legacy_loaded": []}
    assert _load_in_subprocess("zip", model_path)["digest"] == expected


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
