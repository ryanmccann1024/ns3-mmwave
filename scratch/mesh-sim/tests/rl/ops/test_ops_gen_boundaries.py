"""Static module boundaries of scripts/rl/ops, checked on the AST without importing.

Expectations come from scripts/rl/ops/CLAUDE.md "Boundaries" and README.md
"Module map".
"""

import ast
import json
import re
from pathlib import Path

import pytest

from scripts.sim_support import find_mesh_root

OPS = find_mesh_root() / "scripts" / "rl" / "ops"
MODULES = ("tasks", "reconcile", "slurm", "receipts", "cluster", "run_task",
           "benchmark", "fetch", "tune")
PUBLIC_EXPERIMENT = {"load_matrix", "build_plan", "load_plan", "step_state",
                     "PLAN_NAME"}
SCHEDULER = {"slurm", "receipts", "reconcile", "cluster"}


def _tree(name: str) -> ast.Module:
    return ast.parse((OPS / f"{name}.py").read_text(), filename=f"{name}.py")


def _imports(name: str) -> list[tuple[str, tuple[str, ...], bool]]:
    """(module, imported names, at module level) for every import statement."""
    tree = _tree(name)
    top = {id(node) for node in tree.body}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, (), id(node) in top))
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{name}.py uses a relative import"
            found.append((node.module, tuple(alias.name for alias in node.names),
                          id(node) in top))
    return found


def _ops_deps(name: str) -> set[str]:
    deps = set()
    for module, names, _ in _imports(name):
        if module == "scripts.rl.ops":
            deps.update(names)
        elif module.startswith("scripts.rl.ops."):
            deps.add(module.rsplit(".", 1)[1])
    return deps - {name}


def test_gen_every_listed_module_exists():
    assert {path.stem for path in OPS.glob("*.py")} - {"__init__"} == set(MODULES)


EXPECTED_DEPS = {
    "tasks": set(),
    "reconcile": {"tasks"},
    "run_task": {"tasks"},
    "benchmark": {"tasks"},
    "fetch": {"tasks"},
    "cluster": {"tasks", "slurm", "receipts", "reconcile", "run_task"},
}


@pytest.mark.parametrize("name", sorted(EXPECTED_DEPS))
def test_gen_ops_dependencies_match_the_module_map(name):
    assert _ops_deps(name) == EXPECTED_DEPS[name]


@pytest.mark.parametrize("name,forbidden", [
    ("slurm", {"receipts", "reconcile", "cluster"}),
    ("receipts", {"slurm", "reconcile", "cluster"}),
    ("tune", SCHEDULER),
    ("fetch", SCHEDULER),
    ("run_task", SCHEDULER | {"tune"}),
    ("benchmark", SCHEDULER),
])
def test_gen_forbidden_ops_imports(name, forbidden):
    assert not _ops_deps(name) & forbidden


def test_gen_the_ops_import_graph_has_no_cycle():
    graph = {name: _ops_deps(name) for name in MODULES}
    state: dict[str, int] = {}

    def visit(node, path):
        if state.get(node) == 1:
            raise AssertionError(f"import cycle: {' -> '.join(path + [node])}")
        if state.get(node) == 2:
            return
        state[node] = 1
        for dep in graph.get(node, ()):
            visit(dep, path + [node])
        state[node] = 2

    for name in MODULES:
        visit(name, [])


def test_gen_only_three_modules_import_experiment_and_only_public_names():
    importers = {}
    for name in MODULES:
        for module, names, _ in _imports(name):
            if module == "scripts.rl.experiment":
                importers.setdefault(name, set()).update(names)
            assert module != "scripts.rl" or "experiment" not in names, name
    assert set(importers) <= {"tasks", "tune", "benchmark"}
    for name, names in importers.items():
        assert names <= PUBLIC_EXPERIMENT, (name, names - PUBLIC_EXPERIMENT)


@pytest.mark.parametrize("name", ["tasks", "reconcile"])
def test_gen_pure_modules_import_no_process_or_scheduler_machinery(name):
    modules = {module.split(".")[0] for module, _, _ in _imports(name)}
    assert not modules & {"subprocess", "os", "shutil", "socket", "multiprocessing",
                          "signal"}
    source = (OPS / f"{name}.py").read_text()
    assert "subprocess" not in source and "os.system" not in source


def test_gen_reconcile_imports_nothing_but_tasks():
    assert [(module, names) for module, names, _ in _imports("reconcile")] \
        == [("scripts.rl.ops", ("tasks",))]


def test_gen_optuna_is_imported_lazily_and_only_by_tune():
    for name in MODULES:
        for module, _, top_level in _imports(name):
            if module.split(".")[0] != "optuna":
                continue
            assert name == "tune" and not top_level, name


TIME_LIKE = re.compile(r"^(\d+-)?\d{1,3}:\d\d(:\d\d)?$")
MEM_LIKE = re.compile(r"^\d+[KMGT]B?$")


@pytest.mark.parametrize("name", MODULES)
def test_gen_no_cluster_constants_are_hard_coded(name):
    source = (OPS / f"{name}.py").read_text()
    assert "#SBATCH" not in source
    for node in ast.walk(_tree(name)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            assert not TIME_LIKE.match(value), f"{name}.py: time literal {value!r}"
            assert not MEM_LIKE.match(value), f"{name}.py: memory literal {value!r}"
            for flag in ("--partition=", "--account=", "--qos=", "--constraint=",
                         "--time=", "--mem=", "--cpus-per-task="):
                assert not value.startswith(flag) or value == flag, \
                    f"{name}.py: literal sbatch option {value!r}"


def test_gen_the_example_config_names_every_schema_key():
    body = json.loads((OPS / "cluster-config.example.json").read_text())
    assert set(body) == {"cluster_config_version", "name", "venv", "setup_lines",
                         "task", "compare", "max_array_size", "max_concurrent_tasks"}
    assert set(body["task"]) == {"partition", "account", "qos", "constraint", "time",
                                 "mem", "cpus_per_task"}
    assert set(body["compare"]) == {"time", "mem", "cpus_per_task"}
