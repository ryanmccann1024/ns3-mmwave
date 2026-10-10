"""Regression-suite manifest, reference integrity, and output ownership."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .regression_snapshot import SNAPSHOT_VERSION, compare_source_digests, sha256_of

MANIFEST_VERSION = 1


def path_under_root(value: str, root: Path) -> Path:
    """Resolve a manifest path while rejecting absolute or escaping paths."""
    path = Path(value)
    if path.is_absolute():
        raise ValueError("Manifest path must be relative: %s" % value)
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Manifest path escapes mesh-sim root: %s" % value) from exc
    return resolved


def _validate_case_name(name: str) -> None:
    """Require a nonempty case name that denotes one child directory."""
    if (
        not isinstance(name, str)
        or not name
        or Path(name).name != name
        or name in (".", "..")
    ):
        raise ValueError("Manifest case name must be one safe path segment")


def suite_output_dir(value: str, root: Path) -> Path:
    """Require suite output beneath outputs/ without allowing outputs/ itself."""
    path = Path(value).resolve()
    outputs = (root / "outputs").resolve()
    try:
        path.relative_to(outputs)
    except ValueError as exc:
        raise ValueError("Suite --out must be beneath %s" % outputs) from exc
    if path == outputs:
        raise ValueError("Suite --out must be a directory beneath %s" % outputs)
    return path


def prepare_suite_output(out_root: Path, case_names: list[str]) -> bool:
    """Remove only files owned by a previous run of this suite."""
    for name in case_names:
        _validate_case_name(name)
    targets = [out_root / "suite-report.json"]
    targets.extend(out_root / name for name in case_names)
    replaced = any(path.exists() or path.is_symlink() for path in targets)
    for path in targets:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
    out_root.mkdir(parents=True, exist_ok=True)
    return replaced


def load_suite_manifest(path: Path, root: Path) -> dict:
    """Load and validate the tracked regression-suite manifest."""
    with open(path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise ValueError(
            "Unsupported manifest_version %r" % manifest.get("manifest_version")
        )
    baseline = manifest.get("baseline")
    if not isinstance(baseline, dict):
        raise ValueError("Manifest baseline must be an object")
    for key in ("git_commit", "simulator_binary_sha256"):
        if not isinstance(baseline.get(key), str) or not baseline[key]:
            raise ValueError("Manifest baseline.%s is required" % key)

    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Manifest cases must be a non-empty array")
    names = set()
    required = (
        "name", "label", "required", "family", "case", "seed", "band", "run_config",
        "snapshot", "snapshot_sha256",
    )
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError("Manifest cases[%d] must be an object" % index)
        missing = [key for key in required if key not in case]
        if missing:
            raise ValueError(
                "Manifest cases[%d] missing: %s" % (index, ", ".join(missing))
            )
        _validate_case_name(case["name"])
        if case["name"] in names:
            raise ValueError("Duplicate manifest case name: %s" % case["name"])
        names.add(case["name"])
        if not isinstance(case["label"], str) or not case["label"]:
            raise ValueError("Manifest label is required for %s" % case["name"])
        if not isinstance(case["required"], bool):
            raise ValueError("Manifest required must be boolean for %s" % case["name"])
        if case["band"] not in ("mmwave", "sub-6"):
            raise ValueError("Invalid band for %s: %s" % (case["name"], case["band"]))
        int(case["seed"])
        path_under_root(case["run_config"], root)
        path_under_root(case["snapshot"], root)
    return manifest


def verify_manifest_snapshots(manifest: dict, root: Path) -> list[dict]:
    """Verify snapshot bytes and duplicated case metadata before running."""
    verified = []
    for case in manifest["cases"]:
        snapshot_path = path_under_root(case["snapshot"], root)
        if not snapshot_path.is_file():
            raise ValueError(
                "Reference snapshot not installed: %s. Ask the project team for "
                "the approved cloud baseline bundle and unpack it under "
                "tests/fixtures/regression/p0/. Reference snapshots are local-only; "
                "do not recapture them from the changed simulator."
                % case["snapshot"]
            )
        actual_sha = sha256_of(snapshot_path)
        if actual_sha != case["snapshot_sha256"]:
            raise ValueError(
                "Snapshot digest mismatch for %s: expected %s, got %s"
                % (case["name"], case["snapshot_sha256"], actual_sha)
            )
        with open(snapshot_path, encoding="utf-8") as handle:
            snapshot = json.load(handle)
        expected = {
            "snapshot_version": SNAPSHOT_VERSION,
            "family": case["family"],
            "case": case["case"],
            "seed": int(case["seed"]),
            "band": case["band"],
        }
        for key, value in expected.items():
            if snapshot.get(key) != value:
                raise ValueError(
                    "Snapshot metadata mismatch for %s.%s: expected %r, got %r"
                    % (case["name"], key, value, snapshot.get(key))
                )
        source_paths = {entry.get("path") for entry in snapshot.get("sources", [])}
        if case["run_config"] not in source_paths:
            raise ValueError(
                "Snapshot %s does not record run_config %s"
                % (case["name"], case["run_config"])
            )
        verified.append(
            {"case": case, "snapshot": snapshot, "snapshot_path": snapshot_path}
        )
    return verified


def source_issues(snapshot: dict, root: Path) -> tuple[list[str], list[str]]:
    """Return missing and digest-mismatched scenario source paths."""
    missing = []
    changed = []
    for result in compare_source_digests(snapshot, root):
        if result["candidate"] is None:
            missing.append(result["path"])
        elif not result["match"]:
            changed.append(result["path"])
    return missing, changed
