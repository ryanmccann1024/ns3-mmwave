"""Regression-suite input validation and output preservation."""

import json
import sys

import pytest

from scripts.validation import regression_check, regression_suite
from scripts.validation.regression_snapshot import SNAPSHOT_VERSION, sha256_of


@pytest.fixture
def suite_manifest(tmp_path):
    snapshot = {
        "snapshot_version": SNAPSHOT_VERSION,
        "family": "baseline",
        "case": "example",
        "seed": 1,
        "band": "mmwave",
        "sources": [{"path": "inputs/example/run.ini", "sha256": "0" * 64}],
    }
    snapshot_path = tmp_path / "reference.json"
    snapshot_path.write_text(json.dumps(snapshot))
    manifest = {
        "manifest_version": regression_suite.MANIFEST_VERSION,
        "baseline": {"git_commit": "baseline", "simulator_binary_sha256": "binary"},
        "cases": [{
            "name": "example",
            "label": "Example",
            "required": True,
            "family": "baseline",
            "case": "example",
            "seed": 1,
            "band": "mmwave",
            "run_config": "inputs/example/run.ini",
            "snapshot": "reference.json",
            "snapshot_sha256": sha256_of(snapshot_path),
        }],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


@pytest.mark.parametrize("name", ["", ".", ".."])
def test_invalid_case_name_preserves_suite_output(tmp_path, monkeypatch, suite_manifest, name):
    manifest = json.loads(suite_manifest.read_text())
    manifest["cases"][0]["name"] = name
    suite_manifest.write_text(json.dumps(manifest))
    out = tmp_path / "outputs" / "suite"
    out.mkdir(parents=True)
    saved = out / "unrelated.txt"
    saved.write_text("keep me")
    report = out / "suite-report.json"
    report.write_text("previous report")
    monkeypatch.setattr(regression_check, "mesh_sim_root", lambda: tmp_path)

    result = regression_check.main([
        "verify-suite", "--sim-binary", sys.executable,
        "--manifest", str(suite_manifest), "--out", str(out),
    ])

    assert saved.read_text() == "keep me"
    assert report.read_text() == "previous report"
    assert result == regression_check.EXIT_USAGE


@pytest.mark.parametrize("name", ["", ".", "..", "../unrelated", "nested/case"])
def test_cleanup_validates_all_names_before_removing_files(tmp_path, name):
    out = tmp_path / "suite"
    owned = out / "owned"
    owned.mkdir(parents=True)
    saved = owned / "result.txt"
    saved.write_text("previous result")
    report = out / "suite-report.json"
    report.write_text("previous report")

    with pytest.raises(ValueError, match="safe path segment"):
        regression_suite.prepare_suite_output(out, ["owned", name])

    assert saved.read_text() == "previous result"
    assert report.read_text() == "previous report"


def test_cleanup_removes_only_owned_products(tmp_path):
    out = tmp_path / "suite"
    owned = out / "owned"
    owned.mkdir(parents=True)
    (owned / "result.txt").write_text("old result")
    report = out / "suite-report.json"
    report.write_text("old report")
    saved = out / "unrelated.txt"
    saved.write_text("keep me")
    external = tmp_path / "external"
    external.mkdir()
    external_saved = external / "result.txt"
    external_saved.write_text("keep external result")
    link = out / "linked-case"
    link.symlink_to(external, target_is_directory=True)

    assert regression_suite.prepare_suite_output(out, ["owned", "linked-case"])
    assert out.is_dir()
    assert not owned.exists()
    assert not report.exists()
    assert not link.is_symlink()
    assert saved.read_text() == "keep me"
    assert external_saved.read_text() == "keep external result"


def test_valid_manifest_verifies_reference_snapshot(tmp_path, suite_manifest):
    manifest = regression_suite.load_suite_manifest(suite_manifest, tmp_path)
    verified = regression_suite.verify_manifest_snapshots(manifest, tmp_path)
    assert len(verified) == 1
    assert verified[0]["case"] == manifest["cases"][0]
    assert verified[0]["snapshot_path"] == tmp_path / "reference.json"


def test_changed_reference_snapshot_is_rejected(tmp_path, suite_manifest):
    manifest = regression_suite.load_suite_manifest(suite_manifest, tmp_path)
    (tmp_path / "reference.json").write_text("{}")
    with pytest.raises(ValueError, match="Snapshot digest mismatch"):
        regression_suite.verify_manifest_snapshots(manifest, tmp_path)
