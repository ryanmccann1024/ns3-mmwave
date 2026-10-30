#!/usr/bin/env bash
# Maintained launcher for RL experiment batches: validate, plan, run, status, resume.
# Full guide: docs/rl/batch-reference.md. Bash 3.2+; needs the mesh .venv and,
# for plan/run, an already-built simulator (--sim-binary or MESH_SIM_BIN).
# The launcher only locates the root, normalizes path flags against the invoking
# directory, quotes and forwards arguments, and execs Python. It never builds,
# schedules, retries, or chooses scientific or thread settings.
set -euo pipefail

usage() {
  cat <<'HELP'
Usage: bash scripts/rl/run-experiments.sh [--dry-run] <command> [options]

Commands (see `<command> --help` for every option):
  validate --matrix M [--rows R]
  plan     --matrix M --sim-binary B [--output-root O] [--rows R]
  run      --matrix M --sim-binary B [--output-root O] [--rows R]
           [--workers N] [--threads-per-worker N] [--failure-policy continue|stop] [--nice N]
  status   --output-root O [--json]
  resume   --output-root O [--sim-binary B] [--prepare-only] [execution options]

--sim-binary falls back to MESH_SIM_BIN. Relative --matrix, --output-root,
--sim-binary and MESH_SIM_BIN values resolve against the current directory.
--dry-run prints the shell-escaped command without starting Python.
Workers are limited per launcher; two terminals add their workers unless the
batch declares a shared execution.resource_pool.
HELP
}

die() { printf 'run-experiments: %s\n' "$*" >&2; exit 1; }

if [[ $# -eq 0 ]]; then usage; exit 1; fi
case "$1" in -h|--help) usage; exit 0 ;; esac

INVOKED_FROM="$PWD"
absolute() {
  case "$1" in
    /*) printf '%s' "$1" ;;
    *) printf '%s/%s' "$INVOKED_FROM" "$1" ;;
  esac
}

DRY_RUN=0
ARGS=()
EXPECT_PATH=""
for arg in "$@"; do
  if [[ -n "$EXPECT_PATH" ]]; then
    ARGS+=("$(absolute "$arg")")
    EXPECT_PATH=""
    continue
  fi
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --matrix|--output-root|--sim-binary) ARGS+=("$arg"); EXPECT_PATH=1 ;;
    --matrix=*|--output-root=*|--sim-binary=*)
      flag="${arg%%=*}"
      value="${arg#*=}"
      if [[ -n "$value" ]]; then value="$(absolute "$value")"; fi
      ARGS+=("$flag=$value") ;;
    *) ARGS+=("$arg") ;;
  esac
done
if [[ -n "${MESH_SIM_BIN:-}" ]]; then
  MESH_SIM_BIN="$(absolute "$MESH_SIM_BIN")"
  export MESH_SIM_BIN
fi

is_mesh_root() { [[ -f "$1/sim.cc" && -d "$1/scripts/rl" ]]; }
if [[ -n "${MESH_SIM_ROOT:-}" ]]; then
  MESH_ROOT="$(absolute "$MESH_SIM_ROOT")"
  is_mesh_root "$MESH_ROOT" || die "MESH_SIM_ROOT is not a mesh-sim root: $MESH_ROOT"
else
  MESH_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
  while ! is_mesh_root "$MESH_ROOT"; do
    [[ "$MESH_ROOT" != / ]] || die "cannot find the mesh-sim root; set MESH_SIM_ROOT"
    MESH_ROOT="$(dirname -- "$MESH_ROOT")"
  done
fi
cd -- "$MESH_ROOT"
MESH_ROOT="$PWD"
PYTHON="$MESH_ROOT/.venv/bin/python"
[[ -x "$PYTHON" ]] || die "missing $PYTHON; run python3 scripts/rl/bootstrap_venv.py from mesh-sim"

COMMAND=("$PYTHON" -u -m scripts.rl.experiment)
# Bash 3.2 treats an empty array expansion as unset under nounset.
if [[ ${#ARGS[@]} -gt 0 ]]; then
  COMMAND+=("${ARGS[@]}")
fi

if [[ "$DRY_RUN" == 1 ]]; then
  printf 'Preview only; command not executed:\n'
  printf 'cd -- %q &&' "$MESH_ROOT"
  if [[ -n "${MESH_SIM_BIN:-}" ]]; then printf ' MESH_SIM_BIN=%q' "$MESH_SIM_BIN"; fi
  printf ' %q' "${COMMAND[@]}"
  printf '\n'
  exit 0
fi
# Replace the launcher so Ctrl-C and exit codes reach the Python command directly.
exec "${COMMAND[@]}"
