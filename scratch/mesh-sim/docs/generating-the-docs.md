# Generating the docs {#generating_the_docs}

[TOC]

This site is built by Doxygen from the sources under `scratch/mesh-sim` and
styled with the doxygen-awesome-css theme.

## 1\. Quick start

**Step 1. Install Doxygen and Graphviz** (versions in section 2):

```bash
brew install doxygen graphviz        # macOS
sudo apt install doxygen graphviz    # Debian / Ubuntu
```

`build.sh` also uses `python3` and `rsync`, which macOS and most Linux
systems already have. On Windows, run it from WSL or Git Bash.

**Step 2. Build.** From the ns3-mmwave repository root:

```bash
cd scratch/mesh-sim/docs
./build.sh                  # builds html/, warnings go to doxygen-warnings.log
```

**Checkpoint:** the script ends without an error and `html/index.html` exists.

**Step 3. Open the site:**

```bash
open html/index.html        # macOS; xdg-open on Linux
```

The site is a set of local files, so no server is needed. Re-run `./build.sh`
after changing a Markdown page or a source comment. It copies the `.py` files
into the ignored `.api-src/` folder (so Doxygen names Python modules
`scripts.<package>...` rather than after the `scratch/` and `mesh-sim/`
folders), regenerates `api-groups.dox` with `diagrams/api-groups.py`, then runs
`doxygen Doxyfile` from `docs/`, where the input paths are relative.

## 2\. Tool versions

On other platforms, download [Doxygen](https://www.doxygen.nl/download.html) and
[Graphviz](https://graphviz.org/download/). Check the install with
`doxygen --version` and `dot -V`.

Tested versions (macOS, October 2026):

| Tool | Version | Notes |
|---|---|---|
| Doxygen | 1.18.0 | The theme supports Doxygen 1.9.1–1.9.4 and 1.9.6–1.18.0. |
| Graphviz (`dot`) | 13.1.2 | Draws the class inheritance graphs. |
| doxygen-awesome-css | v2.5.0 (commit `46483f1e5a70ffb9ecd3b82d0a1cd1b24edf13da`) | Vendored; see section 5. |

A different Doxygen version may print configuration warnings or render pages
differently.

## 3\. What gets generated

| Path | What | In Git? |
|---|---|---|
| `html/` | The site. Open `html/index.html`. | No (ignored by `docs/.gitignore`) |
| `doxygen-warnings.log` | Doxygen's warnings and errors from the last build. | No |

## 4\. Warnings

Check `doxygen-warnings.log` after each build and fix any new warnings your
change introduced. The log already contains some older ones (unresolved `\ref`
targets and "documented return type" notes); fix those in their own pages when
you next edit them.

A "does not exist" error naming a stylesheet or extra file means the theme
folder is missing or incomplete; see section 7.

## 5\. Theme and site files

| File | What it does |
|---|---|
| `theme/doxygen-awesome-css/` | The vendored theme: eight files copied unchanged from the upstream release, with its MIT license. |
| `theme/provenance.md` | The theme's tag, commit, archive hash and per-file hashes, plus the commands to re-download or verify it. |
| `theme/mesh-sim.css` | Site styling (colors, light and dark mode, sidebar, headings, tables, code, diagrams, landing page). Loaded last, so it overrides the theme without editing it. |
| `header.html` | Doxygen 1.18.0's stock header plus the theme's four scripts (dark-mode toggle, copy button, paragraph links, interactive table of contents), the Lato and Roboto Slab fonts, a home link on the project name, and a script for the sidebar and diagrams. |
| `DoxygenLayout.xml` | Doxygen's default layout, with the API section limited to Classes, Class hierarchy, Namespaces and Files. |
| `Doxyfile` | Doxygen settings, including the page-scoped `FILTER_PATTERNS` (see below). |

Keep these in sync when you change them:

- `--side-nav-fixed-width` in `theme/mesh-sim.css` must equal `TREEVIEW_WIDTH`
  in `Doxyfile` (both 340 px).
- The sidebar pages follow the order of the `\subpage` links on `index.md`. The
  sidebar group captions in `header.html` name the first page of each group, so
  update both together.
- `FILTER_PATTERNS` rewrites some source-file links in
  `documentation-standard.md` to rendered pages during the build, using `sed`.
  Update its mappings if those link targets change.

**Upgrading Doxygen:** generate a stock header in a scratch folder with
`doxygen -w html header.html footer.html stylesheet.css`, then re-apply the
additions listed above for `header.html`.

## 6\. Diagrams

- **Class inheritance graphs** are drawn by Graphviz. Other Doxygen graphs
  (collaboration, include, directory) are turned off in `Doxyfile`.
- **The system overview diagram** is `diagrams/system-overview.svg`, generated
  by a script. After editing the script, run this from `docs/`:

  ```bash
  python3 diagrams/system-overview.py
  ```

  The visualizer repository keeps an identical copy of the script and SVG;
  keep the two the same.
- **The first-result figure** on \ref mesh_sim_first_result "Understand the
  result" is `diagrams/first-result.svg`, plotted from a run of
  `01-static-los-baseline` (seed 1). Rerun it after a change that alters that
  scenario's output:

  ```bash
  ../.venv/bin/python diagrams/first-result.py ../outputs/getting-started/01-static-los-baseline
  ```

  `screenshots/plotting-capacity-timeseries.png` on the same page is the
  `scripts/plotting` output for that run.
- **The repository map** (\ref mesh_sim_repo_map "Repository map") is
  `repo-map.md`, generated by `diagrams/repo-map.py` and drawn in the browser
  by `theme/repo-map.js`. Its links come from the Doxygen tag file
  `html/mesh-sim.tag`, so regenerate it between two builds after adding,
  moving or removing files:

  ```bash
  ./build.sh
  python3 diagrams/repo-map.py
  ./build.sh
  ```
