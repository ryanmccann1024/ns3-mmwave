from scripts.rl.ops import fetch as fetch_cli
"""Fetch: rsync argv construction, source/destination rules, and the manifest.

rsync is always a recording shim under tmp_path (never the system rsync).
Expectations come from scripts/rl/ops/README.md "Fetch".
"""

import itertools
import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

from scripts.rl.cli_common import write_json
from scripts.rl.ops import retrieval as fetch

from scripts.rl.tests.ops_test_support import make_plan

REMOTE_ROOT = Path("/remote/run")
SAFE_OPTIONS = {"-a", "--prune-empty-dirs", "--ignore-existing", "--include=*/",
                "--exclude=*"}


def _payload(tmp_path: Path, plan=True, comparison: str | None = None) -> Path:
    payload = tmp_path / "payload"
    (payload / "cluster" / "receipts").mkdir(parents=True)
    if plan:
        write_json(payload / "experiment_plan.json", make_plan(REMOTE_ROOT, 2))
    write_json(payload / "cluster" / "tasks.json", {"tasks_version": 1})
    write_json(payload / "cluster" / "receipts" / "0001.json", {"submission": "0001"})
    if comparison is not None:
        (payload / "comparison").mkdir()
        (payload / "comparison" / "comparison.json").write_text(comparison)
    return payload


def _rsync(tmp_path: Path, monkeypatch, payload: Path | None, code: int = 0) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "rsync-calls.json"
    script = bin_dir / "rsync"
    script.write_text(textwrap.dedent(f"""\
        #!{sys.executable}
        import json, shutil, sys
        from pathlib import Path
        log = Path({str(log)!r})
        calls = json.loads(log.read_text()) if log.exists() else []
        calls.append(sys.argv[1:])
        log.write_text(json.dumps(calls))
        payload = {str(payload) if payload else None!r}
        if payload and {code} == 0:
            shutil.copytree(payload, sys.argv[-1], dirs_exist_ok=True)
        sys.exit({code})
        """))
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


# --- argv --------------------------------------------------------------------


@pytest.mark.parametrize("size", [1, 2, len(fetch.CATEGORY_INCLUDES)])
def test_no_selection_ever_adds_a_deleting_or_overwriting_option(tmp_path, size):
    for combo in itertools.combinations(sorted(fetch.CATEGORY_INCLUDES), size):
        argv = fetch.build_argv("/r", tmp_path / "d", list(combo))
        options = [token for token in argv[1:-2] if not token.startswith("--include=")
                   or token == "--include=*/"]
        assert set(options) <= SAFE_OPTIONS, combo
        assert argv[-4:-2] == ["--include=*/", "--exclude=*"]
        assert argv.count("--ignore-existing") == 1


# --- destination rules -------------------------------------------------------


def test_a_failed_rsync_leaves_no_manifest_even_after_partial_files(tmp_path,
                                                                       monkeypatch,
                                                                       capsys):
    _rsync(tmp_path, monkeypatch, None, code=23)
    dest = tmp_path / "dest"
    assert fetch_cli.main(["--remote", "u@h:/r", "--dest", str(dest)]) == 1
    assert "rsync exited 23" in capsys.readouterr().err
    assert not (dest / fetch.FETCH_MANIFEST_NAME).exists()


# --- the manifest ------------------------------------------------------------


def _fetch(tmp_path, monkeypatch, payload, *extra, dest=None):
    log = _rsync(tmp_path, monkeypatch, payload)
    dest = dest or tmp_path / "dest"
    code = fetch_cli.main(["--remote", "u@h:/remote/run/", "--dest", str(dest), *extra])
    return code, dest, log


def test_repeated_updates_keep_every_earlier_manifest(tmp_path, monkeypatch):
    payload = _payload(tmp_path)
    code, dest, _ = _fetch(tmp_path, monkeypatch, payload)
    assert code == 0
    for expected in (1, 2):
        assert _fetch(tmp_path, monkeypatch, payload, "--update", dest=dest)[0] == 0
        assert (dest / f"fetch_manifest.{expected}.json").is_file()
    names = sorted(path.name for path in dest.glob("fetch_manifest*.json"))
    assert names == ["fetch_manifest.1.json", "fetch_manifest.2.json",
                     "fetch_manifest.json"]
    current = json.loads((dest / fetch.FETCH_MANIFEST_NAME).read_text())
    assert not any(entry["path"].startswith("fetch_manifest")
                   for entry in current["files"])
