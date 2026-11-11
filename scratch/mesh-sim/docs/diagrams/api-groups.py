"""Generate docs/api-groups.dox: the "Code by module" tree of the API reference.

Doxygen's own lists (Classes, Namespaces, Files) are flat and alphabetical. This
script builds one ordered tree instead:

    Simulator (C++)  > Inputs and configuration > cli, config, domain, util
                     > Scene and link quality   > setup, eval, jammer
                     > ...
    Python tools     > Field data and validation > arpo_data, validation
                     > Reinforcement learning    > rl > agents, env, ...
                     > ...

Each category and folder is a Doxygen group (@defgroup). Each Python module
(a namespace) and each C++ file and namespace-scope class is put in its
folder's group with an external "@ingroup" block, so no source file changes.
Edit LAYOUT below to move a folder; the script fails if a source folder is not
placed anywhere. Edit this script, not api-groups.dox. docs/build.sh runs it.

A group's one-line brief comes from its folder's README (@brief), else the
first line of its __init__.py docstring, else its local RUN_PLAN.md title;
its guide link (@page or {#id} in the README) goes in the detailed description so the overview table stays short.
"""
import ast
import os
import re

DOCS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(DOCS)  # scratch/mesh-sim
TARGET = os.path.join(DOCS, "api-groups.dox")
SOURCE_EXT = {"src": (".h", ".cc"), "scripts": (".py",)}

# (group id, title, brief, children). A child is a folder path, which brings
# its subfolders with it, or another (id, title, brief, children) category.
LAYOUT = [
    ("api_simulator", "Simulator (C++)",
     "The simulator's C++ modules, in namespace mesh_sim, in the order a run uses them.", [
         ("api_cpp_inputs", "Inputs and configuration",
          "Command-line parsing, run.ini and JSON loading, and the plain data types every layer shares.",
          ["src/cli", "src/config", "src/domain", "src/util"]),
         ("api_cpp_scene", "Scene and link quality",
          "Creating the ns-3 nodes and models, then computing SINR, capacity and jammer interference for every link.",
          ["src/setup", "src/eval", "src/jammer"]),
         ("api_cpp_flows", "Traffic and routing",
          "Flow-level demand, and routing it over the link graph.",
          ["src/traffic", "src/routing"]),
         ("api_cpp_outputs", "Outputs",
          "The per-tick CSVs, summary.json, run.log and progress.",
          ["src/io"]),
         ("api_cpp_interfaces", "External interfaces",
          "The RL bridge to Python and the `--channel-query` worker used by placement planning.",
          ["src/rl", "src/query"]),
     ]),
    ("api_python", "Python tools",
     "The Python packages, run as python -m scripts.PACKAGE.MODULE from scratch/mesh-sim/.", [
         ("api_py_field", "Field data and validation",
          "Turning field logs into traces, building scenarios from them, and comparing the simulator with the field.",
          ["scripts/arpo_data", "scripts/validation"]),
         ("api_py_runs", "Runs and plots",
          "Parameter sweeps and post-run figures.",
          ["scripts/sweep", "scripts/plotting"]),
         ("api_py_placement", "Placement baselines",
          "Planning node start positions before a run, scored by the simulator's channel.",
          ["scripts/baselines"]),
         ("api_py_rl", "Reinforcement learning",
          "The Gymnasium environment, training, evaluation, comparison and experiment operations.",
          ["scripts/rl"]),
         ("api_py_shared", "Shared helpers",
          "Small modules every package uses: simulator launching, JSON artifacts and statistics.",
          ["scripts"]),
     ]),
]

def group_id(folder):
    return "api_" + re.sub(r"[^A-Za-z0-9]+", "_", folder)


def is_source(rel, kind):
    name = os.path.basename(rel)
    if not name.endswith(SOURCE_EXT[kind]):
        return False
    return not (name == "__init__.py" or name.startswith("test_") or name == "conftest.py"
                or "tests" in rel.split("/"))


def collect():
    """{folder: [relative source files]} for every folder holding documented sources."""
    found = {}
    for kind in SOURCE_EXT:
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, kind)):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__" and not d.startswith("."))
            folder = os.path.relpath(dirpath, ROOT)
            files = sorted(os.path.join(folder, f) for f in filenames
                           if is_source(os.path.join(folder, f), kind))
            if files:
                found[folder] = files
    return found


def describe(folder):
    """(brief, guide page id): README @brief, else the __init__.py docstring's first line."""
    brief = page = None
    readme = os.path.join(ROOT, folder, "README.md")
    if os.path.isfile(readme):
        text = open(readme, encoding="utf-8").read()
        m = re.search(r"^@brief\s+(.+)$", text, re.M)
        brief = m.group(1).strip() if m else None
        m = re.search(r"^@page\s+(\S+)", text, re.M) or re.search(r"\{#([A-Za-z0-9_]+)\}", text)
        page = m.group(1) if m else None
    init = os.path.join(ROOT, folder, "__init__.py")
    if not brief and os.path.isfile(init):
        doc = ast.get_docstring(ast.parse(open(init, encoding="utf-8").read()))
        brief = doc.strip().splitlines()[0] if doc else None
    plan = os.path.join(ROOT, folder, "RUN_PLAN.md")
    if not brief and os.path.isfile(plan):
        m = re.search(r"^#\s+(.+?)(?:\s*\{#.*\})?$", open(plan, encoding="utf-8").read(), re.M)
        brief = m.group(1).strip() + "." if m else None
    return brief, page


CPP_TYPE = re.compile(r"^(?:class|struct)\s+([A-Za-z_]\w*)\s*(?:final\s*)?(?::[^;{]*)?\{", re.M)


def cpp_classes(rel):
    """Fully qualified classes and structs a header defines at namespace scope."""
    text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    scope = "mesh_sim::query" if "namespace mesh_sim::query" in text else "mesh_sim"
    return [f"{scope}::{name}" for name in CPP_TYPE.findall(text)]


def members(gid, rel):
    """Python: the module's namespace page. C++: the file and each class it defines."""
    if rel.endswith(".py"):
        return [f"/** @namespace {rel[:-3].replace('/', '::')}\n *  @ingroup {gid}\n */"]
    out = [f"/** @file {rel}\n *  @ingroup {gid}\n */"]
    if rel.endswith(".h"):
        out += [f"/** @class {name}\n *  @ingroup {gid}\n */" for name in cpp_classes(rel)]
    return out


def block(gid, title, brief, parent, page=None, files=()):
    lines = [f"/** @defgroup {gid} {title}"]
    if parent:
        lines.append(f" *  @ingroup {parent}")
    if brief:
        lines.append(f" *  @brief {brief}")
    if page:
        lines += [" *", f" *  Guide: \\ref {page}"]
    lines.append(" */")
    for rel in files:
        lines.extend(members(gid, rel))
    return "\n".join(lines)


def main():
    found = collect()
    placed = set()
    out = ["/* Generated by docs/diagrams/api-groups.py; do not edit. */"]

    def emit_folder(folder, parent_gid, title=None):
        brief, page = describe(folder)
        gid = group_id(folder)
        files = found.get(folder, []) if folder != "scripts" else []
        out.append(block(gid, title or os.path.basename(folder), brief, parent_gid, page, files))
        placed.add(folder)
        children = direct_children(folder)
        for child in children:
            emit_folder(child, gid)

    def emit_category(entry, parent_gid):
        gid, title, brief, children = entry
        files = []
        if children == ["scripts"]:                        # top-level scripts/*.py modules
            files, children = found.get("scripts", []), []
            placed.add("scripts")
        out.append(block(gid, title, brief, parent_gid, None, files))
        for child in children:
            if isinstance(child, tuple):
                emit_category(child, gid)
            else:
                emit_folder(child, gid)

    def direct_children(folder):
        """Nearest descendant folders with sources (skipping source-less levels)."""
        prefix = folder + "/"
        below = sorted(f for f in found if f.startswith(prefix))
        return [f for f in below if not any(f.startswith(g + "/") for g in below if g != f)]

    for entry in LAYOUT:
        emit_category(entry, None)
    missing = sorted(set(found) - placed)
    if missing:
        raise SystemExit(f"source folders not placed in LAYOUT: {missing}")
    with open(TARGET, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(out) + "\n")
    print(f"wrote {os.path.relpath(TARGET, ROOT)}: {len(placed)} folders, "
          f"{sum(len(v) for v in found.values())} files")



if __name__ == "__main__":
    main()
