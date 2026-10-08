"""Import isolation of scripts/baselines.

Contract: scripts/baselines/README.md -- "No module here imports scripts.rl.*, Gymnasium,
Torch, or Stable-Baselines3. With algorithm = none, neither solver.py nor any planners/
module is imported." Checked statically (AST) and in fresh interpreters.
"""

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from scripts.baselines.tests.conftest import FAKE_CHILD, FAKE_QUERY, write_scenario

MESH_ROOT = Path(__file__).resolve().parents[3]
BASELINES = MESH_ROOT / "scripts" / "baselines"
BANNED_ROOTS = ("gymnasium", "gym", "torch", "stable_baselines3", "sb3_contrib")
PLANNER_PREFIXES = ("scripts.baselines.solver", "scripts.baselines.planners")


def _production_modules() -> list[Path]:
    return sorted(p for p in BASELINES.rglob("*.py")
                  if "tests" not in p.relative_to(BASELINES).parts)


def _banned(name: str) -> bool:
    return name.split(".")[0] in BANNED_ROOTS or name == "scripts.rl" or name.startswith(
        "scripts.rl.")


def test_no_production_module_imports_rl_or_ml_stacks_statically():
    offenders = []
    for path in _production_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    package = path.relative_to(MESH_ROOT).parent.parts
                    base = package[:len(package) - node.level + 1]
                    names = [".".join((*base, node.module or ""))]
                else:
                    names = [node.module or ""]
                    names += [f"{node.module}.{a.name}" for a in node.names]
            elif (isinstance(node, ast.Call) and getattr(node.func, "attr", "") ==
                  "import_module" and node.args and isinstance(node.args[0], ast.Constant)):
                names = [str(node.args[0].value)]
            offenders += [(path.name, name) for name in names if _banned(name)]
    assert offenders == []


def _fresh(script: str) -> list[str]:
    result = subprocess.run([sys.executable, "-c", textwrap.dedent(script)], cwd=MESH_ROOT,
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()


REPORT = f"""
banned = {BANNED_ROOTS!r}
print(sorted(m for m in sys.modules if m.split('.')[0] in banned
             or m == 'scripts.rl' or m.startswith('scripts.rl.')))
print(sorted(m for m in sys.modules if m.startswith({PLANNER_PREFIXES!r})))
"""


def test_importing_every_baselines_module_loads_no_rl_or_ml_stack():
    modules = [".".join(p.relative_to(MESH_ROOT).with_suffix("").parts)
               for p in _production_modules()]
    modules = [m[:-len(".__init__")] if m.endswith(".__init__") else m for m in modules]
    lines = _fresh("import importlib, sys\n"
                   f"for name in {modules!r}:\n    importlib.import_module(name)\n" + REPORT)
    assert lines[0] == "[]"
    assert "scripts.baselines.planners.optimization" in lines[1]


def test_importing_the_runner_defers_the_planner():
    lines = _fresh("import sys\nimport scripts.baselines.runner\n" + REPORT)
    assert lines == ["[]", "[]"]


def _composite(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "mesh-sim-composite"
    path.write_text(
        f"#!{sys.executable}\nimport runpy, sys\n"
        f"target = {str(FAKE_QUERY)!r} if '--channel-query' in sys.argv[1:] "
        f"else {str(FAKE_CHILD)!r}\nsys.argv[0] = target\n"
        "runpy.run_path(target, run_name='__main__')\n")
    path.chmod(0o755)
    return path


@pytest.mark.parametrize("algorithm,flag,planner_loaded", [
    ("geometric", None, True),
    ("optimization", None, True),
    ("geometric", "none", False),
    ("optimization", "none", False),
])
def test_runner_end_to_end_import_footprint(tmp_path, algorithm, flag, planner_loaded):
    ini = write_scenario(tmp_path / "s", overrides={
        "algorithm": algorithm, "candidate_grid_cells": "9", "coverage_grid_cells": "9",
        "max_iterations": "5"})
    argv = ["--sim-binary", str(_composite(tmp_path / "bin")), "--run-config", str(ini),
            "--output-dir", str(tmp_path / "run")]
    if flag:
        argv += ["--algorithm", flag]
    lines = _fresh("import sys\nfrom scripts.baselines import runner\n"
                   f"code = runner.main({argv!r})\n" + REPORT + "print(code)\n")
    assert lines[-1] == "0"
    assert lines[-3] == "[]"
    loaded = lines[-2] != "[]"
    assert loaded is planner_loaded, lines[-2]
    if not planner_loaded:
        assert (tmp_path / "run/planner.log").read_text() == (
            "method none: no planner was run\n")
