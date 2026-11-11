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
# Doxygen does not remove pages for deleted modules from an existing site.
rm -rf html
doxygen Doxyfile
