#!/usr/bin/env python3
"""Capture and compare compact normalized simulator snapshots for baseline regression.

Standard-library helpers only; no RL/analysis dependencies are needed.

  python3 -m scripts.validation.regression_check capture ...
  python3 -m scripts.validation.regression_check compare ...
  python3 -m scripts.validation.regression_check verify-suite ...
"""
# regression_check.py
# CLI and suite runner for the baseline regression check. `capture` runs the simulator
# on one scenario (optionally saving a snapshot), `compare` diffs a run against a
# saved snapshot, `verify-suite` does both for every case in a manifest.
# Snapshot building and numeric comparison live in regression_snapshot.py.
# Exit codes: 0 pass, 1 mismatch/failure (EXIT_MISMATCH), 2 usage or I/O error (EXIT_USAGE).

from __future__ import annotations

import argparse
import configparser
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.sim_support import find_mesh_root, simulator_env, strip_inline_comment, tail_lines
from .regression_snapshot import (
    build_snapshot, check_snapshot_clean, compare_snapshots,
    compare_source_digests, rel_to_root, serialize_snapshot, sha256_of,
)
from .regression_suite import (
    load_suite_manifest, path_under_root, prepare_suite_output, source_issues,
    suite_output_dir, verify_manifest_snapshots,
)

EXIT_MISMATCH = 1
EXIT_USAGE = 2


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


## @fn mesh_sim_root
# @brief Locate the mesh-sim root directory independent of the working directory.
#
# @return Path of the mesh-sim root (found from this file's location).
def mesh_sim_root() -> Path:
    """Locate mesh-sim without depending on the current working directory."""
    return find_mesh_root(__file__)


# ---------------------------------------------------------------------------
# Scenario sources
# ---------------------------------------------------------------------------


## @fn scenario_source_files
# @brief List the input files a scenario depends on.
#
# @param run_config  Path to the scenario's `run.ini`.
# @return `run.ini` followed by the existing files named by `nodes_file`,
#         `buildings_file` and `jammers_file` in its `[scenario]` section
#         (relative names resolve against the `run.ini` directory; blank or
#         missing files are skipped).
# @throws OSError if `run_config` cannot be read.
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
        name = strip_inline_comment(raw)
        if not name:
            continue
        candidate = Path(name)
        if not candidate.is_absolute():
            candidate = base / candidate
        if candidate.is_file():
            sources.append(candidate.resolve())
    return sources


## @fn cmd_capture
# @brief `capture` subcommand: run the simulator once and optionally write a snapshot.
#
# @param args  Parsed arguments: `sim_binary`, `run_config`, `band`, `seed`,
#              `family`, `case`, `out`, `snapshot`, `force`, and optional `quiet`.
# @return 0 on success; 2 (EXIT_USAGE) for a missing input or an existing output
#         without `--force`; the simulator's own non-zero exit code if it fails.
#
# Runs `<sim> --run-config=... --band=... --seed=... --output-dir=<out>` with
# stdin closed, and writes the combined stdout/stderr to `<out>/console.log`
# (last 40 lines are echoed to stderr on failure). If `--snapshot` is set, builds
# the snapshot, refuses it if `check_snapshot_clean` objects, and writes it there
# (parent directories are created). `--atol` is accepted but unused here.
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

    env = simulator_env(root)

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
        for line in tail_lines(console_path).splitlines():
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


## @fn cmd_compare
# @brief `compare` subcommand: diff a candidate run against a saved snapshot.
#
# @param args  Parsed arguments: `baseline`, `candidate`, `atol`, `max_diffs`,
#              `report`, and optional `quiet`.
# @return 0 on match; 1 (EXIT_MISMATCH) on any difference; 2 (EXIT_USAGE) if the
#         baseline or the candidate's required files are missing.
#
# Takes seed, family, case and band from the baseline, builds a snapshot of the
# candidate run directory, and compares tables and summary. It also re-hashes the
# scenario input files recorded in the baseline against the current checkout; any
# changed or missing file counts as a difference. Optionally writes a JSON report
# to `--report`. Prints `MATCH` or `MISMATCH` plus up to five differences.
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

    print("Baseline simulator regression suite")
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


## @fn build_parser
# @brief Build the argparse parser with the `capture`, `compare` and `verify-suite` subcommands.
#
# @return Configured `argparse.ArgumentParser`. The suite's `--force` flag is hidden and unused.
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
    cmp_.add_argument("--baseline", required=True, help="local reference snapshot JSON")
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


## @fn main
# @brief CLI entry point.
#
# @param argv  Argument list; defaults to `sys.argv[1:]` when None.
# @return The subcommand's exit code; 2 (EXIT_USAGE) if it raised OSError,
#         ValueError or json.JSONDecodeError (message printed to stderr).
def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
