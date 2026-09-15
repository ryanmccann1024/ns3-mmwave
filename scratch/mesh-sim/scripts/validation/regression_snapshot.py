"""Normalized snapshot construction and numeric comparison; standard library only."""

import csv
import hashlib
import json
import math
from pathlib import Path

SNAPSHOT_VERSION = 1

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


def rel_to_root(path: Path, root: Path) -> str:
    """Path relative to the mesh-sim root with posix separators, if possible."""
    path = Path(path).resolve()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


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
