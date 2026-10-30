# Theme provenance: doxygen-awesome-css

The files in `theme/doxygen-awesome-css/` are an unmodified subset of one tagged
upstream release, vendored as plain files (no submodule, no `.gitmodules`).
Keep that directory pristine; record changes here, not there. Project styling
overrides belong in `theme/mesh-sim.css` (not vendored), which `Doxyfile`
loads after the theme's stylesheets.

| Field | Value |
|---|---|
| Theme | doxygen-awesome-css by jothepro |
| Upstream | <https://github.com/jothepro/doxygen-awesome-css> |
| Tag | `v2.5.0` (lightweight tag; release published 2026-09-12) |
| Commit | `46483f1e5a70ffb9ecd3b82d0a1cd1b24edf13da` (resolved with `git ls-remote --tags`) |
| Archive | <https://github.com/jothepro/doxygen-awesome-css/archive/46483f1e5a70ffb9ecd3b82d0a1cd1b24edf13da.tar.gz> |
| Archive SHA-256 | `65abe1d85bc2adf9d1a1b6ef90ae5e63f72425024196f89ec27b7bdc52d94267` (as downloaded 2026-10-20; GitHub does not promise byte-stable archives, so the per-file hashes below are the authoritative check) |
| License | MIT (`LICENSE` is vendored alongside the files) |
| Vendored on | 2026-10-20 |
| Doxygen verified against | 1.18.0 (Graphviz 13.1.2), macOS host |
| Compatibility statement | Upstream `README.md` at `v2.5.0`, line 28: "Works best with **Doxygen 1.9.1** - **1.9.4** and **1.9.6** - **1.18.0**". The same README warns: "This theme is not compatible with the `FULL_SIDEBAR = YES` option" and "`HTML_COLORSTYLE` must be set to `LIGHT` since Doxygen 1.9.5!". |

## Vendored files (SHA-256)

Only these eight files are vendored. Nothing else from the release
(docs, images, examples, build scripts, other extensions) is copied.

| File | SHA-256 |
|---|---|
| `LICENSE` | `e3da754c3f657cc78594fa2e8a3283665f78c743df2485fa9e498a8973051191` |
| `doxygen-awesome.css` | `ea37516ec7a7a7780719b9d9a285fe3268a8d5411523d8b93af98d77e67cd1a1` |
| `doxygen-awesome-sidebar-only.css` | `909d17055552149555fc87c5e0cf171a41d09a9e358c389a51b25ddfafd462af` |
| `doxygen-awesome-sidebar-only-darkmode-toggle.css` | `c1939ca910d2282068482abc72e9edcf9835e4de153ebe8b428cbace92ed4c2c` |
| `doxygen-awesome-darkmode-toggle.js` | `11951aeb28a182af457a354073b8c05c9bb3c39121e5704e44eabaca8d86d5ff` |
| `doxygen-awesome-fragment-copy-button.js` | `7241deb83fb629ddf0848bc22f12b59184282526e7d7f18e662025d0a2b576c8` |
| `doxygen-awesome-paragraph-link.js` | `fb6fd1075dedc8cada45dc522e0d206acc72e8cd1a3452ea03905a3e942c5795` |
| `doxygen-awesome-interactive-toc.js` | `a7d6a4d59809b650afd011af6fc8805075aeb5e310940fb9583a42652fe87ba8` |

## Configuration the extensions require (from upstream `docs/extensions.md` at v2.5.0)

- Dark-mode toggle: `HTML_EXTRA_FILES` includes `doxygen-awesome-darkmode-toggle.js`; `HTML_EXTRA_STYLESHEET` includes `doxygen-awesome-sidebar-only-darkmode-toggle.css` (sidebar-only variant).
- Fragment copy button: `HTML_COPY_CLIPBOARD = NO` ("required with Doxygen >= 1.10.0").
- Interactive TOC: `PAGE_OUTLINE_PANEL = NO` ("Starting from Doxygen Version 1.14.0").
- Each script is included at the end of `<head>` in `header.html` and initialized with its `init()` call.

## Re-acquire or verify

```bash
SHA=46483f1e5a70ffb9ecd3b82d0a1cd1b24edf13da
curl -sL "https://github.com/jothepro/doxygen-awesome-css/archive/$SHA.tar.gz" -o "doxygen-awesome-css-$SHA.tar.gz"
shasum -a 256 "doxygen-awesome-css-$SHA.tar.gz"      # compare with the archive hash above
tar -xzf "doxygen-awesome-css-$SHA.tar.gz"
cd "doxygen-awesome-css-$SHA"
shasum -a 256 LICENSE doxygen-awesome.css doxygen-awesome-sidebar-only.css \
  doxygen-awesome-sidebar-only-darkmode-toggle.css doxygen-awesome-darkmode-toggle.js \
  doxygen-awesome-fragment-copy-button.js doxygen-awesome-paragraph-link.js \
  doxygen-awesome-interactive-toc.js                   # compare with the table above
# then copy exactly those eight files into theme/doxygen-awesome-css/
```

To verify the vendored copy in place: run the same `shasum` command inside
`theme/doxygen-awesome-css/` and compare with the table.

## Legacy `docs/awesome-css` entry (deferred cleanup)

The Git index still holds a gitlink at `scratch/mesh-sim/docs/awesome-css`
(mode 160000, commit `d52eafe3e9303399fda15661f3d7bb8fe3d7eabc`) with no root
`.gitmodules`; the directory is empty on disk. That commit is upstream tag
`v2.4.2` of this same theme. The entry is unused by the current `Doxyfile` and
is intentionally left untouched by the documentation shell; removing it is a
separate, later cleanup.
