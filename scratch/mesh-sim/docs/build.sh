#!/bin/sh
# Build the documentation site into html/. Run from anywhere: ./docs/build.sh
#
# Doxygen names a Python module after every parent folder that holds an
# __init__.py. scratch/ and scratch/mesh-sim/ both have one (for imports), so
# building straight from ../scripts names every module
# scratch.mesh-sim.scripts..., and the hyphen breaks Doxygen's parsing. This
# script copies only the .py files into .api-src/scripts/, where scripts/ is the
# top package, then regenerates the API groups and runs Doxygen. README pages
# under scripts/ are still read from ../scripts so their relative links work.
set -eu
cd "$(dirname "$0")"
rm -rf .api-src
mkdir -p .api-src
rsync -a --prune-empty-dirs --include '*/' --include '*.py' --exclude '*' \
    --exclude '__pycache__/' ../scripts .api-src/
python3 diagrams/api-groups.py

# Private pages are encrypted with git-crypt (see ../.gitattributes). In a
# locked checkout they hold ciphertext, which starts with "\0GITCRYPT\0", so
# leave them out of the build; the Doxyfile reads these two variables. In an
# unlocked checkout the research evidence files are copied into the site.
MESH_SIM_LOCKED_DOCS=""
MESH_SIM_PRIVATE_EXTRA_FILES=""
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    private=$(git ls-files -- .. | git check-attr --stdin filter \
        | sed -n 's/: filter: git-crypt$//p')
    for f in $private; do
        if [ "$(head -c 10 "$f" | tr -d '\000')" = "GITCRYPT" ]; then
            MESH_SIM_LOCKED_DOCS="$MESH_SIM_LOCKED_DOCS $f"
        else
            case "$f" in
                research/evidence/*) MESH_SIM_PRIVATE_EXTRA_FILES="$MESH_SIM_PRIVATE_EXTRA_FILES $f" ;;
            esac
        fi
    done
fi
# Untracked evidence files (before the first encrypted commit) are plain text.
for f in research/evidence/research-source-manifest.json research/evidence/research-slide-text.txt; do
    if [ -f "$f" ] && ! git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
        MESH_SIM_PRIVATE_EXTRA_FILES="$MESH_SIM_PRIVATE_EXTRA_FILES $f"
    fi
done
if [ -n "$MESH_SIM_LOCKED_DOCS" ]; then
    echo "build.sh: checkout is locked; leaving out the private pages:$MESH_SIM_LOCKED_DOCS"
fi
export MESH_SIM_LOCKED_DOCS MESH_SIM_PRIVATE_EXTRA_FILES

# Doxygen does not remove pages for deleted modules from an existing site.
rm -rf html
doxygen Doxyfile
