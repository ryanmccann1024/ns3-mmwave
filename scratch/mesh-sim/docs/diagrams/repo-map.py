"""Generate the repository map page, docs/repo-map.md, from the files in the repo.

The page is an interactive, searchable tree of scratch/mesh-sim (rendered by
docs/theme/repo-map.js, styled by the "Repository map" section of
docs/theme/mesh-sim.css). Edit this script, not repo-map.md. From docs/:

    doxygen Doxyfile                    # writes html/mesh-sim.tag (used for links)
    python3 diagrams/repo-map.py        # rewrites repo-map.md
    doxygen Doxyfile                    # renders the updated page

What goes in the map: every file Git tracks plus untracked files that are not
ignored, minus LOCAL_ONLY folders and dotfiles. Descriptions come from the files
themselves, in this order: OVERRIDES, a folder's README (its @brief or first
paragraph), a C++ @brief, a Python module docstring or "## @file" block, a
Markdown page title, or the first comment line of an .ini/.sh file. Links come
from the Doxygen tag file, so a file only links when Doxygen documents it.
"""
import ast
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

DOCS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(DOCS)  # scratch/mesh-sim
TAGFILE = os.path.join(DOCS, "html", "mesh-sim.tag")
TARGET = os.path.join(DOCS, "repo-map.md")

# Local working folders that other checkouts will not have.
LOCAL_ONLY = {"archived-runs", "work", "feature-research", "outputs", "data"}
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".venv", "node_modules"}

# Paths whose files carry no usable description, or that need a better one.
OVERRIDES = {
    "": "Mesh-Sim: a time-stepped mmWave / sub-6 mesh simulator built on ns3-mmwave.",
    "sim.cc": "Simulator entry point: parses the CLI, loads the scenario and runs the per-tick loop.",
    "CMakeLists.txt": "Source list for the ns-3 build. Add new C++ files here.",
    "README.md": "The User guide.",
    "CONTRIBUTING.md": "The \"update together\" checklist for user-visible changes.",
    "CLAUDE.md": "Project guidance for AI coding assistants.",
    "AGENTS.md": "Project guidance for AI coding agents.",
    "TODO.md": "Open work items.",
    "__init__.py": "Makes scratch/mesh-sim importable as a Python package.",
    "requirements.txt": "Pinned Python dependencies for the tools in scripts/.",
    "requirements-tuning.txt": "Optuna pin, used only for hyperparameter tuning.",
    "docs": "Sources for this documentation site (Doxygen).",
    "src": "Simulator C++ modules, one folder per concern (namespace mesh_sim).",
    "scripts": "Python tools: field data, validation, sweeps, RL, placement baselines, plotting.",
    "tests": "C++ unit tests, CLI integration tests and regression fixtures.",
    "docs/Doxyfile": "Doxygen settings for this site.",
    "docs/DoxygenLayout.xml": "Doxygen navigation layout.",
    "docs/header.html": "Page header template: theme scripts, fonts and sidebar helpers.",
    "docs/topics.dox": "Defines the Simulator modules and Python tools index pages.",
    "docs/theme": "Site theme: vendored doxygen-awesome-css plus mesh-sim.css.",
    "docs/theme/mesh-sim.css": "Site styling layered over the vendored theme.",
    "docs/theme/repo-map.js": "Renders this repository map.",
    "docs/diagrams": "Scripts that generate the site's figures and this map.",
    "docs/diagrams/system-overview.py": "Generates the system overview diagram.",
    "docs/diagrams/system-overview.svg": "The system overview diagram (generated).",
    "docs/diagrams/repo-map.py": "Generates this repository map.",
    "docs/getting-started": "The step-by-step getting-started sequence.",
    "docs/rl": "RL how-to guides: training and evaluating a policy.",
    "docs/research": "Research records: the reasoning behind design choices.",
    "docs/research/evidence": "Slide text and source manifest behind the research records.",
    "docs/schemas": "JSON schemas for saved artifacts.",
    "docs/screenshots": "Screenshots used in the docs.",
    "docs/repo-map.md": "This page (generated).",
    "inputs": "Scenario definitions: run.ini plus JSON files, sweeps and experiment matrices.",
    "inputs/experiments": "Experiment matrices (v1) and batch files (v2) for scripts.rl.experiment.",
    "inputs/sweeps": "Sweep definitions for scripts.sweep.",
    "tests/unit": "Standalone C++ unit test suites (no ns-3 needed).",
    "tests/common": "Shared stubs and helpers for the C++ unit tests.",
    "tests/integration": "CLI integration tests against a built simulator binary.",
    "tests/fixtures": "Reference data for the regression suite.",
    "third_party": "Vendored third-party code.",
}

BASENAME_DESC = {
    "run.ini": "Scenario settings.",
    "nodes.json": "Node list: ids, positions and mobility.",
    "buildings.json": "Building footprints and heights.",
    "jammers.json": "Jammer definitions (sub-6 only).",
    "Makefile": "Builds and runs this test suite.",
    "CLAUDE.md": "Scope notes for AI coding assistants.",
    "AGENTS.md": "Scope notes for AI coding agents.",
    "README.md": "This folder's guide page.",
    "README.txt": "This folder's notes.",
    "__init__.py": "Package marker.",
    "conftest.py": "Shared pytest fixtures.",
}

# The landing view: how the main folders connect, as lanes of numbered steps.
# Each step is [path, short label]; a path not in the repo (outputs/, the
# visualizer) is drawn as a plain box. "rows" splits a lane's steps into
# labeled rows ([label, count]); "fan" draws the first step feeding the rest;
# "ordered": False drops the numbers and arrows. Keep in step with the system
# overview.
FLOW = [
    {"title": "Prepare a scenario",
     "text": "Write a scenario by hand, or build one from field data.",
     "steps": [["scripts/arpo_data", "Field logs to per-node traces"],
               ["scripts/validation", "Traces to run.ini + nodes.json"],
               ["inputs", "Scenario folders the simulator reads"]]},
    {"title": "Run the simulator",
     "text": "sim.cc runs steps 1 to 3 once, then steps 4 to 7 on every tick.",
     "rows": [["Once per run", 3], ["Every tick, after advancing the ns-3 clock", 4]],
     "steps": [["src/cli", "Read the command-line flags"],
               ["src/config", "Load and validate the scenario"],
               ["src/setup", "Build ns-3 nodes, mobility, channel"],
               ["src/eval", "SINR, capacity and MCS for every link"],
               ["src/traffic", "Traffic demand for each flow"],
               ["src/routing", "Route flows over the links"],
               ["src/io", "Write CSVs, summary.json, run.log"]],
     "side": [["src/jammer", "Adds jammer power in step 4 (sub-6)"],
              ["src/rl", "RL step after each tick, in RL mode"],
              ["src/query", "--channel-query mode for baselines"],
              ["src/domain", "Shared data types used by every step"],
              ["src/util", "Shared string, path and INI helpers"]]},
    {"title": "Use the results",
     "text": "Each run writes a folder of CSV and JSON files, read by these tools.",
     "fan": True,
     "steps": [["outputs", "Run folders (not in Git)"],
               ["scripts/validation", "Compare with field data"],
               ["scripts/plotting", "Plots from finished runs"],
               ["ns3-mmwave-viz", "3D visualizer (separate repo)"]]},
    {"title": "Drive the simulator from Python",
     "text": "These tools launch an already-built simulator binary.",
     "ordered": False,
     "steps": [["scripts/sweep", "Many runs over a parameter grid"],
               ["scripts/rl", "Train and evaluate RL policies"],
               ["scripts/baselines", "Plan node placements"]]},
    {"title": "Check and document",
     "text": "",
     "ordered": False,
     "steps": [["tests", "C++ unit and CLI integration tests"],
               ["docs", "This documentation site"],
               ["third_party", "Vendored code (json.hpp)"]]},
]

# What each folder uses, as [path, why]. "Used by" is derived in the browser.
# C++ entries follow the dependency layers in CLAUDE.md; Python entries follow
# imports and the files each tool reads or writes.
USES = {
    "src/cli": [["src/domain", "SimConfig"], ["src/util", "seed list parsing"]],
    "src/config": [["inputs", "reads run.ini and its JSON files"], ["src/domain", "fills SimConfig"],
                   ["src/util", "INI and path helpers"], ["third_party", "json.hpp"]],
    "src/setup": [["src/config", "the loaded scenario"], ["src/domain", "SimConfig"]],
    "src/eval": [["src/jammer", "jammer power in the SINR"], ["src/domain", "LinkResult"]],
    "src/jammer": [["src/domain", "jammer specs"]],
    "src/traffic": [["src/domain", "flow types"]],
    "src/routing": [["src/eval", "the link table"], ["src/traffic", "active flows"], ["src/domain", "flow results"]],
    "src/io": [["src/eval", "the link table"], ["src/routing", "flow results"], ["src/cli", "parsed flags"],
               ["src/util", "path helpers"], ["src/domain", "result types"]],
    "src/rl": [["src/eval", "link quality for observations"], ["src/routing", "delivered traffic for rewards"],
               ["src/domain", "SimConfig"]],
    "src/query": [["src/config", "the scenario"], ["src/setup", "a private ns-3 world"],
                  ["src/eval", "the same link calculation"], ["src/cli", "seed resolution"], ["src/domain", "types"]],
    "src/domain": [["src/jammer", "jammer spec type"]],
    "scripts/validation": [["scripts/arpo_data", "per-node field traces"], ["inputs", "writes generated scenarios"],
                           ["src", "runs the built simulator"]],
    "scripts/sweep": [["inputs", "base scenario and sweep.ini"], ["src", "runs the built simulator"]],
    "scripts/rl": [["src/rl", "JSON bridge over stdin/stdout"], ["scripts/baselines", "placement policies"],
                   ["inputs", "scenarios and experiment matrices"]],
    "scripts/baselines": [["src/query", "scores layouts with --channel-query"], ["inputs", "the [baseline] section"]],
    "scripts/plotting": [["outputs", "reads finished runs"]],
    "tests": [["src", "unit and CLI tests"]],
}

# Folders whose guide page is not a README in the folder (Doxygen page names).
DIR_PAGES = {"src": "src", "scripts": "scripts", "docs": "index"}

CATEGORY_BY_TOP = {
    "src": "sim", "scripts": "tool", "inputs": "data", "tests": "test",
    "docs": "docs", "third_party": "vendor",
}
CATEGORY_BY_FILE = {
    "sim.cc": "sim", "CMakeLists.txt": "sim",
    "requirements.txt": "tool", "requirements-tuning.txt": "tool", "__init__.py": "tool",
}

ID_RE = re.compile(r"\{#([A-Za-z0-9_]+)\}")


def git_files():
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, check=True, capture_output=True, text=True).stdout.splitlines()
    files = []
    for p in sorted(set(out)):
        parts = p.split("/")
        if parts[0] in LOCAL_ONLY or any(x in SKIP_PARTS for x in parts) or p.startswith(("docs/rl-program/", "docs/baseline-program/", "docs/claude/")):
            continue
        if any(x.startswith(".") for x in parts):
            continue
        if os.path.isfile(os.path.join(ROOT, p)):
            files.append(p)
    return files


def read_head(path, n=80):
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8", errors="replace") as f:
            return [next(f) for _ in range(n)]
    except StopIteration:
        with open(os.path.join(ROOT, path), encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except OSError:
        return []


def clean(text):
    """Strip Doxygen/Markdown markup and keep the first sentence."""
    text = re.sub(r"[@\\](ref|c|p|a|b|e)\s+", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = text.replace("`", "").replace("**", "").strip().strip("#").strip()
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    if m and len(m.group(1)) >= 20:
        text = m.group(1)
    if len(text) > 160:
        text = text[:157].rsplit(" ", 1)[0] + "…"
    if text and text[-1] not in ".!?…)":
        text += "."
    return text[0].upper() + text[1:] if text else text


def md_info(path):
    """(page id, title, description) for a Markdown page."""
    lines = read_head(path, 60)
    pid = title = brief = None
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("@page") or s.startswith("\\page"):
            bits = s.split(None, 2)
            pid = bits[1] if len(bits) > 1 else None
            title = bits[2] if len(bits) > 2 else None
        elif s.startswith("# ") and title is None:
            m = ID_RE.search(s)
            pid = pid or (m.group(1) if m else None)
            title = ID_RE.sub("", s[2:]).strip()
        elif s.startswith("@brief") or s.startswith("\\brief"):
            brief = s.split(None, 1)[1] if " " in s else None
        if title and brief:
            break
    if not brief:
        # first plain paragraph line after the title
        started = False
        for line in lines:
            s = line.strip()
            if not started:
                started = s.startswith("# ") or s.startswith("@page") or s.startswith("@brief")
                continue
            if not s or s.startswith(("#", "@", "\\", "[TOC]", "<", "|", "-", "```", ">")):
                continue
            brief = s
            break
    return pid, title, brief


def cpp_brief(path):
    for line in read_head(path):
        m = re.search(r"@brief\s+(.*)", line)
        if m:
            return m.group(1)
    for line in read_head(path, 10):
        s = line.strip()
        if s.startswith("//") and len(s) > 6:
            return s.lstrip("/ ")
    return None


def py_brief(path):
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            src = f.read()
        doc = ast.get_docstring(ast.parse(src))
        if doc:
            return doc.strip().splitlines()[0]
    except (SyntaxError, ValueError, OSError):
        pass
    for line in read_head(path, 40):
        m = re.match(r"\s*#+\s*@brief\s+(.*)", line)
        if m:
            return m.group(1)
    return None


def comment_brief(path):
    for line in read_head(path, 20):
        s = line.strip()
        if not s.startswith(("#", ";")) or s.startswith("#!"):
            continue
        s = s.lstrip("#; ").strip()
        if not s or set(s) <= set("=-*"):
            continue
        if " — " in s:
            s = s.split(" — ", 1)[1]
        return s
    return None


def file_desc(path):
    if path in OVERRIDES:
        return OVERRIDES[path]
    base = os.path.basename(path)
    ext = os.path.splitext(base)[1]
    if base in ("CLAUDE.md", "AGENTS.md", "README.md", "README.txt"):
        return BASENAME_DESC[base]
    desc = None
    if ext in (".h", ".hpp", ".cc", ".cpp"):
        desc = cpp_brief(path)
    elif ext == ".py":
        desc = py_brief(path)
    elif ext == ".md":
        _, title, _ = md_info(path)
        desc = title
    elif ext in (".ini", ".sh", ".txt", ".cfg"):
        desc = comment_brief(path)
    if not desc:
        desc = BASENAME_DESC.get(base)
    return clean(desc) if desc else ""


def load_tag():
    files, pages, titles = {}, {}, {}
    if not os.path.exists(TAGFILE):
        print(f"warning: {TAGFILE} not found; run `doxygen Doxyfile` first. "
              "File links will be missing.", file=sys.stderr)
        return files, pages, titles
    root = ET.parse(TAGFILE).getroot()
    for comp in root.findall("compound"):
        kind = comp.get("kind")
        fn = comp.findtext("filename")
        if not fn:
            continue
        if not fn.endswith(".html"):
            fn += ".html"
        if kind == "file":
            # Paths are relative to scratch/mesh-sim (STRIP_FROM_PATH = ..).
            rel = os.path.join(comp.findtext("path") or "", comp.findtext("name") or "")
            if os.path.isabs(rel):
                rel = os.path.relpath(rel, ROOT)
            files[os.path.normpath(rel)] = fn
        elif kind == "page":
            pages[comp.findtext("name")] = fn
            title = comp.findtext("title")
            if title:
                titles.setdefault(title.strip(), fn)
    return files, pages, titles


def main():
    tag_files, tag_pages, tag_titles = load_tag()
    files = git_files()

    def page_link(md_path):
        pid, title, _ = md_info(md_path)
        if pid and pid in tag_pages:
            return tag_pages[pid]
        if title and title in tag_titles:
            return tag_titles[title]
        return None

    tree = {"n": "scratch/mesh-sim", "p": "", "k": {}}
    for f in files:
        node = tree
        parts = f.split("/")
        for i, part in enumerate(parts[:-1]):
            path = "/".join(parts[:i + 1])
            node = node["k"].setdefault(part, {"n": part, "p": path, "k": {}})
        node["k"][parts[-1]] = {"n": parts[-1], "p": f, "f": True}

    def category(path):
        top = path.split("/")[0]
        return CATEGORY_BY_TOP.get(top) or CATEGORY_BY_FILE.get(path, "docs")

    def badges(path, is_file):
        b = []
        base = os.path.basename(path)
        if path == "sim.cc":
            b.append("entry point")
        if is_file and (base.startswith("test_") or base.endswith("-test.cc")):
            b.append("test")
        if path.endswith(".svg") or path == "docs/repo-map.md":
            b.append("generated")
        return b

    def finish(node):
        path = node["p"]
        out = {"n": node["n"], "c": category(path) if path else "root"}
        if node.get("f"):
            out["f"] = 1
            out["d"] = file_desc(path)
            link = page_link(path) if path.endswith(".md") else tag_files.get(path)
            if link:
                out["l"] = link
        else:
            readme = next((os.path.join(path, r) for r in ("README.md", "README.txt")
                           if os.path.join(path, r).lstrip("/") in node_files(node)), None)
            readme = readme.lstrip("/") if readme else None
            desc = OVERRIDES.get(path)
            if desc is None and readme:
                _, title, brief = md_info(readme)
                desc = brief or title
                desc = clean(desc) if desc else None
            if desc is None and "__init__.py" in node["k"]:
                desc = py_brief(os.path.join(path, "__init__.py").lstrip("/"))
                desc = clean(desc) if desc else None
            out["d"] = desc or ""
            link = tag_pages.get(DIR_PAGES.get(path, ""))
            if not link and readme and readme.endswith(".md"):
                link = page_link(readme)
            if link:
                out["l"] = link
            kids = sorted(node["k"].values(), key=lambda k: (bool(k.get("f")), k["n"].lower()))
            out["k"] = [finish(k) for k in kids]
            out["t"] = sum(1 if k.get("f") else k["t"] for k in out["k"])
        bs = badges(path, bool(node.get("f")))
        if bs:
            out["b"] = bs
        return out

    def node_files(node):
        return {k["p"] for k in node["k"].values() if k.get("f")}

    data = {"tree": finish(tree), "flow": FLOW, "uses": USES}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    n_links = payload.count('"l":')
    page = f"""# Repository map {{#mesh_sim_repo_map}}

<!-- Generated by docs/diagrams/repo-map.py. Edit the script, not this file;
     regeneration steps are at the bottom of this page. -->

Every folder and file in `scratch/mesh-sim/`, and how they connect. Start with
**How it fits together**: each lane is one job, with its steps in order. Click
any box to open that folder, where you'll see what is inside it, what it uses
and what uses it. Search finds any file by name or description.

\\htmlonly
<div class="ms-map" id="ms-map"><noscript>The repository map needs JavaScript.</noscript></div>
<script type="application/json" id="ms-map-data">{payload}</script>
<script src="repo-map.js"></script>
\\endhtmlonly

## Regenerating this page

The map is generated from the files in the repository. After adding, moving or
removing files, run this from `scratch/mesh-sim/docs/`:

```bash
doxygen Doxyfile                    # writes html/mesh-sim.tag, used for the links
python3 diagrams/repo-map.py        # rewrites repo-map.md
doxygen Doxyfile                    # renders the updated map
```

Descriptions come from the files themselves: each folder's README, a C++
`@brief`, a Python module docstring, or a Markdown page title. To change one,
edit that file's own description, or add an entry to `OVERRIDES` in
`docs/diagrams/repo-map.py`. Local working folders
({", ".join(f"`{d}/`" for d in sorted(LOCAL_ONLY))}) are left out.
"""
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"wrote {TARGET}: {len(files)} files, {n_links} links")


if __name__ == "__main__":
    main()
