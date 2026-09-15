#!/usr/bin/env python3
"""Capture and compare compact normalized simulator snapshots for P0 regression.

Standard library only: it must run before the RL/analysis Python environment
exists, and it never imports simulator or project code.

  python3 -m scripts.validation.regression_check capture ...
  python3 -m scripts.validation.regression_check compare ...
  python3 -m scripts.validation.regression_check verify-suite ...
"""

from __future__ import annotations

import argparse
import configparser
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

SNAPSHOT_VERSION = 1
MANIFEST_VERSION = 1

# Stable per-seed tables covered by the snapshot. links.csv is required.
TABLE_FILES = [
    "positions.csv",
    "links.csv",
    "rx-power.csv",
    "mcs.csv",
    "flows.csv",
    "routes.csv",
]
REQUIRED_TABLES = ["links.csv"]

# summary.json keys dropped because they are wall-clock, not simulation values.
_VOLATILE_SUMMARY_PREFIX = "wall_"

EXIT_MISMATCH = 1
EXIT_USAGE = 2


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def mesh_sim_root() -> Path:
    """Walk up from this file to the directory containing sim.cc."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "sim.cc").is_file():
            return parent
    raise RuntimeError("Could not locate mesh-sim root (no sim.cc above %s)" % here)


def ns3_lib_dir(root: Path) -> Path:
    """ns-3 shared libraries live two parents above the mesh-sim root."""
    return root.parent.parent / "build" / "lib"


def rel_to_root(path: Path, root: Path) -> str:
    """Path relative to the mesh-sim root with posix separators, if possible."""
    path = Path(path).resolve()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


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


# ---------------------------------------------------------------------------
# Value normalization
# ---------------------------------------------------------------------------


def normalize_value(raw: str):
    """Parse a CSV cell as a float when possible, otherwise keep the string."""
    text = raw.strip()
    try:
        num = float(text)
    except ValueError:
        return raw
    if math.isnan(num):
        return "nan"
    if math.isinf(num):
        return "inf" if num > 0 else "-inf"
    return num


def load_table(path: Path) -> dict:
    """Read one CSV into {"columns": [...], "rows": [{col: value}, ...]}."""
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        try:
            columns = next(reader)
            while columns and columns[0].startswith("#"):
                columns = next(reader)
        except StopIteration:
            return {"columns": [], "rows": []}
        columns = [c.strip() for c in columns]
        rows = []
        for fields in reader:
            if not fields:
                continue
            row = {}
            for idx, col in enumerate(columns):
                row[col] = normalize_value(fields[idx]) if idx < len(fields) else None
            rows.append(row)
    return {"columns": columns, "rows": rows}


def normalize_summary(summary: dict) -> dict:
    """Drop wall-clock fields from summary.json; keep every other key."""
    return {
        key: value
        for key, value in summary.items()
        if not key.startswith(_VOLATILE_SUMMARY_PREFIX)
    }


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Scenario sources
# ---------------------------------------------------------------------------


def _strip_inline_comment(value: str) -> str:
    """Mirror src/util/ini-parser.cc: text after the first '#' or ';' is dropped."""
    for marker in ("#", ";"):
        pos = value.find(marker)
        if pos != -1:
            value = value[:pos]
    return value.strip()


def scenario_source_files(run_config: Path) -> list[Path]:
    """run.ini plus the node/buildings/jammer files it references."""
    run_config = Path(run_config).resolve()
    parser = configparser.ConfigParser(
        allow_no_value=True, interpolation=None, strict=False
    )
    parser.optionxform = str
    with open(run_config, encoding="utf-8") as handle:
        parser.read_file(handle)

    sources = [run_config]
    base = run_config.parent
    for key in ("nodes_file", "buildings_file", "jammers_file"):
        raw = parser.get("scenario", key, fallback="") or ""
        name = _strip_inline_comment(raw)
        if not name:
            continue
        candidate = Path(name)
        if not candidate.is_absolute():
            candidate = base / candidate
        if candidate.is_file():
            sources.append(candidate.resolve())
    return sources


def source_digests(paths, root: Path) -> list[dict]:
    entries = [
        {"path": rel_to_root(p, root), "sha256": sha256_of(p)}
        for p in paths
        if Path(p).is_file()
    ]
    entries.sort(key=lambda e: e["path"])
    return entries


# ---------------------------------------------------------------------------
# Snapshot construction
# ---------------------------------------------------------------------------


def build_snapshot(
    run_dir,
    sources,
    root: Path,
    family: str,
    case: str,
    seed: int,
    band: str,
) -> dict:
    """Build the normalized snapshot for one completed run directory."""
    run_dir = Path(run_dir).resolve()
    seed_dir_name = "seed-%d" % seed
    seed_dir = run_dir / seed_dir_name

    summary_path = seed_dir / "summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError("Missing required %s" % summary_path)

    tables = {}
    tables_missing = []
    for name in TABLE_FILES:
        path = seed_dir / name
        if path.is_file():
            tables[name] = load_table(path)
        elif name in REQUIRED_TABLES:
            raise FileNotFoundError("Missing required %s" % path)
        else:
            tables_missing.append(name)

    with open(summary_path, encoding="utf-8") as handle:
        summary = json.load(handle)

    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "family": family,
        "case": case,
        "seed": int(seed),
        "band": band,
        "sources": source_digests(sources, root),
        "seed_dir": seed_dir_name,
        "tables": tables,
        "tables_missing": tables_missing,
        "summary": normalize_summary(summary),
    }


def serialize_snapshot(snapshot: dict) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True)


def check_snapshot_clean(text: str, root: Path) -> None:
    """Refuse snapshots leaking absolute paths, wall-clock fields, or raw logs."""
    problems = []
    if str(root) in text:
        problems.append("absolute mesh-sim root path")
    if _VOLATILE_SUMMARY_PREFIX in text:
        problems.append("wall_ field")
    for name in ("run.log", "console.log"):
        if name in text:
            problems.append(name)
    if problems:
        raise ValueError("Snapshot rejected, contains: " + ", ".join(problems))


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def _values_equal(a, b, atol: float) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b or a == b
    a_num = isinstance(a, (int, float))
    b_num = isinstance(b, (int, float))
    if a_num != b_num:
        return False
    if a_num:
        if math.isnan(a) and math.isnan(b):
            return True
        return abs(a - b) <= atol
    return a == b


def _compare_any(where, base, cand, atol, diffs, max_diffs) -> int:
    """Recursively compare two JSON-ish values; returns the difference count."""
    if isinstance(base, dict) and isinstance(cand, dict):
        count = 0
        for key in sorted(set(base) | set(cand)):
            if key not in base:
                count += _record(diffs, max_diffs, "%s.%s" % (where, key), "<absent>", cand[key])
            elif key not in cand:
                count += _record(diffs, max_diffs, "%s.%s" % (where, key), base[key], "<absent>")
            else:
                count += _compare_any(
                    "%s.%s" % (where, key), base[key], cand[key], atol, diffs, max_diffs
                )
        return count
    if isinstance(base, list) and isinstance(cand, list):
        if len(base) != len(cand):
            return _record(diffs, max_diffs, "%s.length" % where, len(base), len(cand))
        count = 0
        for idx, (b, c) in enumerate(zip(base, cand)):
            count += _compare_any("%s[%d]" % (where, idx), b, c, atol, diffs, max_diffs)
        return count
    if _values_equal(base, cand, atol):
        return 0
    return _record(diffs, max_diffs, where, base, cand)


def _record(diffs, max_diffs, where, baseline, candidate) -> int:
    if len(diffs) < max_diffs:
        diffs.append({"where": where, "baseline": baseline, "candidate": candidate})
    return 1


def _compare_table(name, base, cand, atol, diffs, max_diffs) -> int:
    count = 0
    if base.get("columns") != cand.get("columns"):
        count += _record(
            diffs, max_diffs, "%s.columns" % name, base.get("columns"), cand.get("columns")
        )
    base_rows = base.get("rows", [])
    cand_rows = cand.get("rows", [])
    if len(base_rows) != len(cand_rows):
        count += _record(
            diffs, max_diffs, "%s.row_count" % name, len(base_rows), len(cand_rows)
        )
    local = []
    for idx, (b_row, c_row) in enumerate(zip(base_rows, cand_rows)):
        for col in base.get("columns", []):
            where = "%s[row %d].%s" % (name, idx, col)
            count += _compare_any(where, b_row.get(col), c_row.get(col), atol, local, max_diffs)
    diffs.extend(local[: max(0, max_diffs - len(diffs))])
    return count


def compare_snapshots(baseline: dict, candidate: dict, atol: float = 1e-9,
                      max_diffs: int = 20) -> dict:
    """Compare two normalized snapshots; returns a report dict."""
    diffs = []
    counts = {}

    base_tables = baseline.get("tables", {})
    cand_tables = candidate.get("tables", {})
    for name in sorted(set(base_tables) | set(cand_tables)):
        if name not in cand_tables:
            counts[name] = _record(diffs, max_diffs, "%s" % name, "<present>", "<absent>")
            continue
        if name not in base_tables:
            counts[name] = _record(diffs, max_diffs, "%s" % name, "<absent>", "<present>")
            continue
        table_diffs = []
        counts[name] = _compare_table(
            name, base_tables[name], cand_tables[name], atol, table_diffs, max_diffs
        )
        diffs.extend(table_diffs[: max(0, max_diffs - len(diffs))])

    summary_diffs = []
    counts["summary.json"] = _compare_any(
        "summary", baseline.get("summary", {}), candidate.get("summary", {}),
        atol, summary_diffs, max_diffs
    )
    diffs.extend(summary_diffs[: max(0, max_diffs - len(diffs))])

    total = sum(counts.values())
    counts["total"] = total
    return {"match": total == 0, "differences": diffs, "counts": counts}


def compare_source_digests(baseline: dict, root: Path) -> list[dict]:
    """Recompute each recorded source digest against the current checkout."""
    results = []
    for entry in baseline.get("sources", []):
        path = root / entry["path"]
        current = sha256_of(path) if path.is_file() else None
        results.append(
            {
                "path": entry["path"],
                "baseline": entry["sha256"],
                "candidate": current,
                "match": current == entry["sha256"],
            }
        )
    return results


# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------


def cmd_capture(args) -> int:
    root = mesh_sim_root()
    quiet = getattr(args, "quiet", False)
    run_config = Path(args.run_config).resolve()
    if not run_config.is_file():
        print("Error: run-config not found: %s" % run_config, file=sys.stderr)
        return EXIT_USAGE

    sim_binary = Path(args.sim_binary).resolve()
    if not sim_binary.is_file():
        print("Error: sim-binary not found: %s" % sim_binary, file=sys.stderr)
        return EXIT_USAGE

    out_dir = Path(args.out).resolve()
    seed_dir = out_dir / ("seed-%d" % args.seed)
    if (seed_dir / "summary.json").is_file() and not args.force:
        print(
            "Error: %s already exists. Use --force to overwrite."
            % (seed_dir / "summary.json"),
            file=sys.stderr,
        )
        return EXIT_USAGE

    snapshot_path = Path(args.snapshot).resolve() if args.snapshot else None
    if snapshot_path and snapshot_path.exists() and not args.force:
        print(
            "Error: snapshot %s already exists. Use --force to overwrite."
            % snapshot_path,
            file=sys.stderr,
        )
        return EXIT_USAGE

    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(sim_binary),
        "--run-config=%s" % run_config,
        "--band=%s" % args.band,
        "--seed=%d" % args.seed,
        "--output-dir=%s" % out_dir,
    ]
    if not quiet:
        print("Command: %s" % " ".join(cmd))

    env = os.environ.copy()
    lib_dir = str(ns3_lib_dir(root))
    for var in ("DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH"):
        env[var] = os.pathsep.join(
            [lib_dir] + [part for part in env.get(var, "").split(os.pathsep) if part]
        )

    console_path = out_dir / "console.log"
    with open(console_path, "w", encoding="utf-8") as console:
        console.write("Command: %s\n\n" % " ".join(cmd))
        console.flush()
        result = subprocess.run(
            cmd, stdin=subprocess.DEVNULL, stdout=console,
            stderr=subprocess.STDOUT, env=env
        )

    if result.returncode != 0:
        print("Simulator exited %d. Last 40 lines of %s:"
              % (result.returncode, console_path), file=sys.stderr)
        with open(console_path, encoding="utf-8", errors="replace") as console:
            for line in console.read().splitlines()[-40:]:
                print("  " + line, file=sys.stderr)
        return result.returncode

    if not quiet:
        print("Captured run: %s" % out_dir)

    if snapshot_path:
        snapshot = build_snapshot(
            out_dir,
            scenario_source_files(run_config),
            root,
            args.family,
            args.case,
            args.seed,
            args.band,
        )
        text = serialize_snapshot(snapshot)
        check_snapshot_clean(text, root)
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(text + "\n", encoding="utf-8")
        if not quiet:
            print("Wrote snapshot: %s" % snapshot_path)

    return 0


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


def cmd_compare(args) -> int:
    root = mesh_sim_root()
    quiet = getattr(args, "quiet", False)
    baseline_path = Path(args.baseline).resolve()
    if not baseline_path.is_file():
        print("Error: baseline snapshot not found: %s" % baseline_path, file=sys.stderr)
        return EXIT_USAGE

    with open(baseline_path, encoding="utf-8") as handle:
        baseline = json.load(handle)

    candidate_dir = Path(args.candidate).resolve()
    seed = int(baseline.get("seed", 0))
    try:
        candidate = build_snapshot(
            candidate_dir,
            [],
            root,
            baseline.get("family", ""),
            baseline.get("case", ""),
            seed,
            baseline.get("band", ""),
        )
    except FileNotFoundError as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return EXIT_USAGE

    report = compare_snapshots(baseline, candidate, args.atol, args.max_diffs)
    digests = compare_source_digests(baseline, root)
    digest_diffs = [d for d in digests if not d["match"]]
    if digest_diffs:
        report["match"] = False
        report["counts"]["source_digests"] = len(digest_diffs)
        report["counts"]["total"] += len(digest_diffs)
        for entry in digest_diffs:
            report["differences"].append(
                {
                    "where": "sources[%s].sha256" % entry["path"],
                    "baseline": entry["baseline"],
                    "candidate": entry["candidate"],
                }
            )

    report_body = {
        "baseline": rel_to_root(baseline_path, root),
        "candidate": args.candidate,
        "atol": args.atol,
        "match": report["match"],
        "differences": report["differences"],
        "counts": report["counts"],
        "source_digests": digests,
    }

    if args.report:
        report_file = Path(args.report).resolve()
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(
            json.dumps(report_body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if not quiet:
            print("Wrote report: %s" % report_file)

    if report_body["match"]:
        if not quiet:
            print("MATCH: %s == %s (atol=%g)"
                  % (report_body["baseline"], args.candidate, args.atol))
        return 0

    if not quiet:
        print("MISMATCH: %d difference(s) (atol=%g)"
              % (report["counts"]["total"], args.atol))
        for diff in report_body["differences"][:5]:
            print("  %s: baseline=%r candidate=%r"
                  % (diff["where"], diff["baseline"], diff["candidate"]))
    return EXIT_MISMATCH


# ---------------------------------------------------------------------------
# suite verification
# ---------------------------------------------------------------------------


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
        if (
            not isinstance(case["name"], str)
            or Path(case["name"]).name != case["name"]
            or case["name"] in (".", "..")
        ):
            raise ValueError("Manifest case name must be one safe path segment")
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
            raise ValueError("Snapshot not found: %s" % case["snapshot"])
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


def cmd_verify_suite(args) -> int:
    root = mesh_sim_root()
    manifest_path = Path(args.manifest).resolve()
    if not manifest_path.is_file():
        print("Error: suite manifest not found: %s" % manifest_path, file=sys.stderr)
        return EXIT_USAGE

    sim_binary = Path(args.sim_binary).resolve()
    if not sim_binary.is_file():
        print("Error: sim-binary not found: %s" % sim_binary, file=sys.stderr)
        return EXIT_USAGE

    manifest = load_suite_manifest(manifest_path, root)
    verified = verify_manifest_snapshots(manifest, root)
    out_root = suite_output_dir(args.out, root)
    suite_report_path = out_root / "suite-report.json"
    replaced = prepare_suite_output(
        out_root, [item["case"]["name"] for item in verified]
    )

    baseline = manifest["baseline"]
    baseline_sha = baseline["simulator_binary_sha256"]
    current_sha = sha256_of(sim_binary)
    build = baseline.get("build", {})
    required_total = sum(1 for item in verified if item["case"]["required"])
    optional_total = len(verified) - required_total

    print("P0 simulator regression suite")
    print("Purpose: detect unintended changes against fixed pre-change results.")
    print(
        "Reference: commit %s | %s | %s"
        % (
            baseline["git_commit"][:7],
            build.get("profile", "unknown build"),
            build.get("architecture", "unknown architecture"),
        )
    )
    print("Cases: %d required, %d optional" % (required_total, optional_total))
    relation = (
        "matches reference"
        if current_sha == baseline_sha
        else "different binary; results decide compatibility"
    )
    print("Binary: %s... (%s)\n" % (current_sha[:12], relation))
    if replaced:
        print("Previous suite output: replaced\n")

    results = []
    required_passed = 0
    optional_passed = 0
    skipped = 0
    failed = 0
    label_width = max(len(item["case"]["label"]) for item in verified)
    for index, item in enumerate(verified, start=1):
        case = item["case"]
        name = case["name"]
        case_out = out_root / name
        missing, changed = source_issues(item["snapshot"], root)
        status = None
        reason = None
        capture_exit = None
        compare_exit = None

        if missing:
            if case["required"] or args.require_all:
                status = "FAIL"
                failed += 1
                reason = "required source data is missing"
            else:
                status = "SKIP"
                skipped += 1
                reason = "optional source data is not installed"
        elif changed:
            status = "FAIL"
            failed += 1
            reason = "source data differs from the recorded baseline"

        if status is None:
            capture_args = argparse.Namespace(
                sim_binary=str(sim_binary),
                run_config=str(path_under_root(case["run_config"], root)),
                band=case["band"],
                seed=int(case["seed"]),
                family=case["family"],
                case=case["case"],
                out=str(case_out),
                snapshot=None,
                force=False,
                quiet=True,
            )
            capture_exit = cmd_capture(capture_args)
            if capture_exit == 0:
                compare_args = argparse.Namespace(
                    baseline=str(item["snapshot_path"]),
                    candidate=str(case_out),
                    atol=args.atol,
                    max_diffs=args.max_diffs,
                    report=str(case_out / "comparison.json"),
                    quiet=True,
                )
                compare_exit = cmd_compare(compare_args)

            if capture_exit == 0 and compare_exit == 0:
                status = "PASS"
                if case["required"]:
                    required_passed += 1
                else:
                    optional_passed += 1
            else:
                status = "FAIL"
                failed += 1
                reason = "simulation or comparison failed; inspect the case logs"

        display_band = "mmWave" if case["band"] == "mmwave" else "sub-6"
        details = "%s | %s | seed %s" % (
            case["family"], display_band, case["seed"]
        )
        print(
            "[%d/%d] %-*s  %-28s  %s"
            % (index, len(verified), label_width, case["label"], details, status)
        )
        if missing:
            print("      Missing data: %s" % ", ".join(missing))
            print(
                "      Action: %s"
                % case.get(
                    "missing_help",
                    "Ask the project team or data owner for the missing scenario data.",
                )
            )
        elif changed:
            print("      Changed input: %s" % ", ".join(changed))
            print("      Action: restore the recorded input or approve a new baseline.")
        elif status == "FAIL":
            print("      Details: %s" % rel_to_root(case_out, root))

        results.append(
            {
                "name": name,
                "label": case["label"],
                "required": case["required"],
                "status": status,
                "reason": reason,
                "missing_sources": missing,
                "changed_sources": changed,
                "capture_exit": capture_exit,
                "compare_exit": compare_exit,
                "output": rel_to_root(case_out, root) if status != "SKIP" else None,
                "comparison_report": (
                    rel_to_root(case_out / "comparison.json", root)
                    if compare_exit is not None else None
                ),
            }
        )
    passed = required_passed + optional_passed
    suite_status = "PASS" if failed == 0 else "FAIL"
    report = {
        "manifest_version": manifest["manifest_version"],
        "manifest": rel_to_root(manifest_path, root),
        "baseline_git_commit": baseline["git_commit"],
        "baseline_simulator_sha256": baseline_sha,
        "current_simulator_sha256": current_sha,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "total": len(results),
        "required_passed": required_passed,
        "required_total": required_total,
        "optional_passed": optional_passed,
        "optional_total": optional_total,
        "require_all": args.require_all,
        "status": suite_status,
        "cases": results,
    }
    suite_report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "\nRESULT: %s — required %d/%d, optional %d/%d, skipped %d"
        % (
            suite_status,
            required_passed,
            required_total,
            optional_passed,
            optional_total,
            skipped,
        )
    )
    print("Detailed report: %s" % rel_to_root(suite_report_path, root))
    return 0 if suite_status == "PASS" else EXIT_MISMATCH


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="regression_check",
        description="Capture and compare normalized simulator regression snapshots.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    cap = sub.add_parser("capture", help="run one scenario and optionally snapshot it")
    cap.add_argument("--sim-binary", required=True)
    cap.add_argument("--run-config", required=True)
    cap.add_argument("--band", required=True, choices=["mmwave", "sub-6"])
    cap.add_argument("--seed", required=True, type=int)
    cap.add_argument("--family", required=True)
    cap.add_argument("--case", required=True)
    cap.add_argument("--out", required=True, help="disposable run output directory")
    cap.add_argument("--snapshot", help="write the normalized snapshot here")
    cap.add_argument("--atol", type=float, default=1e-9, help="unused by capture")
    cap.add_argument("--force", action="store_true",
                     help="overwrite an existing run or snapshot")
    cap.set_defaults(func=cmd_capture)

    cmp_ = sub.add_parser("compare", help="compare a snapshot with a candidate run")
    cmp_.add_argument("--baseline", required=True, help="committed snapshot JSON")
    cmp_.add_argument("--candidate", required=True, help="candidate run directory")
    cmp_.add_argument("--atol", type=float, default=1e-9)
    cmp_.add_argument("--max-diffs", type=int, default=20,
                      help="max recorded differences per table")
    cmp_.add_argument("--report", help="write a JSON report here")
    cmp_.set_defaults(func=cmd_compare)

    suite = sub.add_parser(
        "verify-suite", help="run and compare every case in a suite manifest"
    )
    suite.add_argument("--sim-binary", required=True)
    suite.add_argument("--manifest", required=True, help="tracked suite manifest JSON")
    suite.add_argument("--out", required=True, help="disposable suite output directory")
    suite.add_argument("--atol", type=float, default=1e-9)
    suite.add_argument("--max-diffs", type=int, default=20,
                       help="max recorded differences per table")
    suite.add_argument(
        "--require-all", action="store_true",
        help="fail when an optional local-data case is unavailable",
    )
    suite.add_argument("--force", action="store_true",
                       help=argparse.SUPPRESS)
    suite.set_defaults(func=cmd_verify_suite)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
