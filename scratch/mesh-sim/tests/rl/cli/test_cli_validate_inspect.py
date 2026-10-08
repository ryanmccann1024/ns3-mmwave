"""Gap tests for scripts/rl/validate_config.py and scripts/rl/inspect_model.py.

Sources: scripts/rl/README.md "Model lifecycle" (validate: static unless --launch;
--launch starts the simulator under <output-dir>/validate/ and resets once;
inspect exit table: 0 readable + every recorded model present with matching
digest, 2 a model file missing or digest differs, 1 manifest missing or
unreadable; "Summarize a finished or failed run"), src/rl/policy-lifecycle-tests.md.
"""

import json
from pathlib import Path

import pytest

from scripts.rl import inspect_model, validate_config
from scripts.rl.cli_common import sha256_file
from scripts.rl.tests.conftest import MULTI_RUN_INI, NODES_JSON


def _scenario(tmp_path: Path, ini: str = MULTI_RUN_INI, nodes: bool = True) -> str:
    scenario = tmp_path / "scn"
    scenario.mkdir(exist_ok=True)
    (scenario / "run.ini").write_text(ini)
    if nodes:
        (scenario / "nodes.json").write_text(NODES_JSON)
    return str(scenario / "run.ini")


def _validate(capsys, sim_binary, run_config, *extra) -> tuple[int, dict, str]:
    code = validate_config.main(["--sim-binary", sim_binary, "--run-config", run_config,
                                 "--json", *extra])
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def _checks(payload: dict) -> dict:
    return {check["check"]: check for check in payload["checks"]}


# 1. validate_config static checks ---------------------------------------------------

def test_missing_run_config_skips_dependent_checks(sim_binary, tmp_path, capsys):
    code, payload, err = _validate(capsys, sim_binary, str(tmp_path / "nope.ini"))
    assert code == 1 and payload["status"] == "failed"
    checks = _checks(payload)
    assert checks["run_config"]["status"] == "error"
    assert "run config not found" in checks["run_config"]["detail"]
    for skipped in ("selection", "seed", "scenario_identity", "rl_bounds",
                    "control_mode"):
        assert skipped not in checks
    assert "sim_binary" in checks and "package_versions" in checks
    assert "run_config: run config not found" in err


def test_keys_before_any_section_are_ignored_like_cpp(sim_binary, tmp_path, capsys):
    # src/util/ini-parser.cc files keys before any header under section "" and skips
    # lines without '=', so the run config itself parses; other checks still fail.
    run_config = _scenario(tmp_path, "seed = 1\nno section header\n")
    code, payload, _ = _validate(capsys, sim_binary, run_config)
    assert code == 1
    assert _checks(payload)["run_config"]["status"] == "ok"


@pytest.mark.parametrize("axis,low,high", [("x", "10.0", "10.0"), ("y", "5", "-5"),
                                           ("z", "50", "0")])
def test_unordered_bounds_are_errors(sim_binary, tmp_path, capsys, axis, low, high):
    ini = MULTI_RUN_INI
    defaults = {"x": ("0.0", "100.0"), "y": ("-50.0", "100.0"), "z": ("0.0", "50.0")}
    ini = ini.replace(f"{axis}_min = {defaults[axis][0]}", f"{axis}_min = {low}")
    ini = ini.replace(f"{axis}_max = {defaults[axis][1]}", f"{axis}_max = {high}")
    code, payload, _ = _validate(capsys, sim_binary, _scenario(tmp_path, ini))
    bounds = _checks(payload)["rl_bounds"]
    assert code == 1 and bounds["status"] == "error"
    assert f"['{axis}']" in bounds["detail"]


def test_non_numeric_bound_is_an_error(sim_binary, tmp_path, capsys):
    ini = MULTI_RUN_INI.replace("x_max = 100.0", "x_max = east")
    code, payload, _ = _validate(capsys, sim_binary, _scenario(tmp_path, ini))
    bounds = _checks(payload)["rl_bounds"]
    assert code == 1 and bounds["status"] == "error"
    assert bounds["detail"].startswith("ValueError")


def test_bounds_with_inline_comments_and_defaults_are_ok(sim_binary, tmp_path, capsys):
    ini = MULTI_RUN_INI.replace("x_min = 0.0", "x_min = 0.0 ; west edge")
    ini = ini.replace("z_min = 0.0\n", "").replace("z_max = 50.0\n", "")
    code, payload, _ = _validate(capsys, sim_binary, _scenario(tmp_path, ini))
    bounds = _checks(payload)["rl_bounds"]
    assert code == 0 and bounds["status"] == "ok"
    assert "x=[0.0, 100.0]" in bounds["detail"]
    assert "z=[0.0, 100.0]" in bounds["detail"]           # RlConfig fallbacks


def test_missing_nodes_file_is_an_identity_error(sim_binary, tmp_path, capsys):
    code, payload, err = _validate(capsys, sim_binary, _scenario(tmp_path, nodes=False))
    identity = _checks(payload)["scenario_identity"]
    assert code == 1 and identity["status"] == "error"
    assert "nodes file not found" in identity["detail"]
    assert "scenario_identity:" in err


def test_missing_binary_is_an_error(tmp_path, capsys):
    code, payload, _ = _validate(capsys, str(tmp_path / "no-binary"), _scenario(tmp_path))
    assert code == 1
    assert "simulator binary not found" in _checks(payload)["sim_binary"]["detail"]


def test_directory_as_binary_is_an_error(tmp_path, capsys):
    code, payload, _ = _validate(capsys, str(tmp_path), _scenario(tmp_path))
    assert code == 1 and _checks(payload)["sim_binary"]["status"] == "error"


@pytest.mark.parametrize("existing", ["train_manifest.json", "maskable_ppo_mesh.zip"])
def test_output_dir_with_a_previous_run_is_an_error(sim_binary, tmp_path, capsys,
                                                    existing):
    out_dir = tmp_path / "prev"
    out_dir.mkdir()
    (out_dir / existing).write_text("x")
    code, payload, _ = _validate(capsys, sim_binary, _scenario(tmp_path),
                                 "--output-dir", str(out_dir))
    check = _checks(payload)["output_dir"]
    assert code == 1 and check["status"] == "error" and existing in check["detail"]


def test_new_output_dir_is_free_and_not_created(sim_binary, tmp_path, capsys):
    out_dir = tmp_path / "fresh"
    code, payload, _ = _validate(capsys, sim_binary, _scenario(tmp_path),
                                 "--output-dir", str(out_dir))
    assert code == 0
    assert "is free" in _checks(payload)["output_dir"]["detail"]
    assert not out_dir.exists()                         # static checks write nothing


def test_cli_seed_overrides_the_ini_seed(sim_binary, tmp_path, capsys):
    code, payload, _ = _validate(capsys, sim_binary, _scenario(tmp_path), "--seed", "42")
    assert code == 0
    assert _checks(payload)["seed"]["detail"] == "42 (source: cli)"


def test_package_drift_is_a_warning_not_an_error(sim_binary, tmp_path, capsys,
                                                 monkeypatch):
    monkeypatch.setattr(validate_config, "package_versions",
                        lambda: {module: None for module in validate_config.DIRECT_DEPS})
    code, payload, _ = _validate(capsys, sim_binary, _scenario(tmp_path))
    check = _checks(payload)["package_versions"]
    assert code == 0 and payload["status"] == "ok"
    assert check["status"] == "warning" and "not installed" in check["detail"]


def test_unreadable_requirements_is_a_warning(sim_binary, tmp_path, capsys, monkeypatch):
    def broken(_path):
        raise ValueError("Expected an exact dependency pin, got: numpy>=1")

    monkeypatch.setattr(validate_config, "read_pins", broken)
    code, payload, _ = _validate(capsys, sim_binary, _scenario(tmp_path))
    check = _checks(payload)["package_versions"]
    assert code == 0 and check["status"] == "warning"
    assert "cannot read requirements.txt" in check["detail"]


def test_text_report_lists_every_check(sim_binary, tmp_path, capsys):
    code = validate_config.main(["--sim-binary", sim_binary,
                                 "--run-config", _scenario(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "launch checks: not run (static checks only)" in out
    for name in ("run_config", "control_mode", "selection", "seed", "scenario_identity",
                 "rl_bounds", "sim_binary", "output_dir", "package_versions"):
        assert f" {name} " in out
    assert "[OK     ] static" in out


# 2. validate_config --launch --------------------------------------------------------

def test_launch_is_skipped_after_a_static_failure(tmp_path, capsys):
    out_dir = tmp_path / "out"
    code, payload, _ = _validate(capsys, str(tmp_path / "no-binary"), _scenario(tmp_path),
                                 "--output-dir", str(out_dir), "--launch")
    launch = _checks(payload)["launch"]
    assert code == 1 and payload["launch"] is None
    assert launch["status"] == "error" and launch["kind"] == "launch"
    assert "skipped" in launch["detail"]
    assert not (out_dir / "validate").exists()


def test_launch_failure_is_reported(sim_binary, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("FAKE_SIM_MODE", "bad_contract")   # protocol error on reset
    out_dir = tmp_path / "out"
    code, payload, err = _validate(capsys, sim_binary, _scenario(tmp_path),
                                   "--output-dir", str(out_dir), "--launch")
    launch = _checks(payload)["launch"]
    assert code == 1 and payload["launch"] is None and payload["status"] == "failed"
    assert launch["status"] == "error" and launch["kind"] == "launch"
    assert "launch:" in err


def test_launch_uses_the_cli_seed(sim_binary, tmp_path, capsys):
    out_dir = tmp_path / "out"
    code, payload, _ = _validate(capsys, sim_binary, _scenario(tmp_path),
                                 "--output-dir", str(out_dir), "--launch",
                                 "--seed", "9")
    assert code == 0
    assert payload["launch"]["output_dir"] == str((out_dir / "validate").resolve())
    episode = json.loads((out_dir / "validate" / "episode-0000"
                          / "rl_episode.json").read_text())
    assert episode["seed"] == 9


# 3. inspect_model ---------------------------------------------------------------------

def _manifest(tmp_path: Path, **overrides) -> dict:
    model = tmp_path / "maskable_ppo_mesh.zip"
    model.write_bytes(b"final-model")
    manifest = {
        "manifest_version": 4, "status": "completed", "algorithm": "MaskablePPO",
        "seed": 1, "seed_source": "cli", "control_mode": "centralized", "band": None,
        "model_path": str(model), "model_sha256": sha256_file(model),
        "best_model_path": None, "best_model_sha256": None, "checkpoints": [],
        "package_versions": {}, "python_version": "3.13.0",
        "platform": {"system": "Linux", "machine": "x86_64"},
    }
    manifest.update(overrides)
    (tmp_path / "train_manifest.json").write_text(json.dumps(manifest))
    return manifest


def _inspect(capsys, run_dir: Path, *extra) -> tuple[int, str, str]:
    code = inspect_model.main(["--run-dir", str(run_dir), *extra])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.mark.parametrize("content", ["{broken", "[1, 2]", '"text"', ""])
def test_unreadable_manifest_exits_one(tmp_path, capsys, content):
    (tmp_path / "train_manifest.json").write_text(content)
    code, _, err = _inspect(capsys, tmp_path)
    assert code == 1
    assert "Cannot read" in err


def test_consistent_run_exits_zero(tmp_path, capsys):
    _manifest(tmp_path)
    code, out, err = _inspect(capsys, tmp_path)
    assert code == 0 and not err
    assert "digest=ok" in out
    assert "evaluation      off" in out


def test_failed_run_without_a_model_is_summarized(tmp_path, capsys):
    _manifest(tmp_path, status="failed", error="RuntimeError: sim died",
              model_path=None, model_sha256=None)
    code, out, _ = _inspect(capsys, tmp_path, "--json")
    report = json.loads(out)
    assert code == 0
    assert report["status"] == "failed" and report["error"] == "RuntimeError: sim died"
    final, = [entry for entry in report["models"] if entry["role"] == "final"]
    assert final["exists"] is False and final["path"] is None

    code, text, _ = _inspect(capsys, tmp_path)
    assert code == 0 and "error           RuntimeError: sim died" in text


def test_relative_model_paths_resolve_inside_the_run_dir(tmp_path, capsys):
    (tmp_path / "checkpoints").mkdir()
    ckpt = tmp_path / "checkpoints" / "checkpoint_8_steps.zip"
    ckpt.write_bytes(b"ckpt")
    _manifest(tmp_path, model_path="maskable_ppo_mesh.zip",
              checkpoints=[{"path": "checkpoints/checkpoint_8_steps.zip",
                            "sha256": sha256_file(ckpt), "num_timesteps": 8}])
    code, out, _ = _inspect(capsys, tmp_path, "--json")
    assert code == 0
    models = json.loads(out)["models"]
    assert models[0]["path"] == str(tmp_path.resolve() / "maskable_ppo_mesh.zip")
    assert models[0]["digest_ok"] is True
    assert models[1]["role"] == "checkpoint" and models[1]["num_timesteps"] == 8
    assert models[1]["digest_ok"] is True


def test_checkpoint_digest_mismatch_exits_two(tmp_path, capsys):
    ckpt = tmp_path / "ckpt.zip"
    ckpt.write_bytes(b"ckpt")
    _manifest(tmp_path, checkpoints=[{"path": str(ckpt), "sha256": "0" * 64,
                                      "num_timesteps": 8}])
    code, out, err = _inspect(capsys, tmp_path)
    assert code == 2
    assert "digest=MISMATCH" in out
    assert "Model problem: checkpoint" in err


def test_missing_best_model_exits_two(tmp_path, capsys):
    _manifest(tmp_path, best_model_path=str(tmp_path / "best_model.zip"),
              best_model_sha256="1" * 64)
    code, _, err = _inspect(capsys, tmp_path)
    assert code == 2
    assert "Model problem: best" in err and "exists=False" in err


def test_package_drift_is_flagged_in_text(tmp_path, capsys):
    _manifest(tmp_path, package_versions={"numpy": "0.0.1"})
    code, out, _ = _inspect(capsys, tmp_path)
    assert code == 0
    numpy_line, = [line for line in out.splitlines() if line.strip().startswith("numpy")]
    assert "0.0.1" in numpy_line and "<- differs" in numpy_line


def test_json_report_round_trips(tmp_path, capsys):
    _manifest(tmp_path, observation_schema={"schema_id": "local_links_v1"})
    code, out, _ = _inspect(capsys, tmp_path, "--json")
    report = json.loads(out)
    assert code == 0
    assert report["manifest_path"] == str(tmp_path.resolve() / "train_manifest.json")
    assert report["observation_schema"]["note"] is None
    assert report["manifest_version"] == 4


# QUESTION: inspect_model.py:40, :51, :78 (_models/_versions/build_report) assume every manifest
# field has the documented type. A JSON-object manifest with a malformed field
# (e.g. a null checkpoint entry, a string contract, a list package_versions) raises AttributeError out of main() instead of
# the documented exit 1 "Manifest missing or unreadable".
@pytest.mark.parametrize("overrides", [{"checkpoints": [None]},
                                       {"contract": "mesh_move_2d_v1"},
                                       {"package_versions": ["numpy"]}])
def test_malformed_manifest_fields_exit_one_not_a_traceback(tmp_path, capsys, overrides):
    _manifest(tmp_path, **overrides)
    code, _, err = _inspect(capsys, tmp_path)
    assert code == 1
    assert err.strip()
