#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# CLI integration tests for mesh-sim.
#
# Usage:
#   tests/integration/cli-integration-test.sh [path-to-sim-binary]
#
# Binary selection order: $MESH_SIM_BIN, then the optional positional argument,
# then the unique executable match of build/scratch/mesh-sim/ns3*-sim-*.
#
# Requires the binary to be built first (the test does NOT build it).
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MESH_SIM_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
NS3_ROOT="$(cd "$MESH_SIM_DIR/../.." && pwd)"

if [[ -n "${MESH_SIM_BIN:-}" ]]; then
    BIN="$MESH_SIM_BIN"
elif [[ -n "${1:-}" ]]; then
    BIN="$1"
else
    candidates=()
    for candidate in "$NS3_ROOT"/build/scratch/mesh-sim/ns3*-sim-*; do
        [[ -x "$candidate" ]] && candidates+=("$candidate")
    done
    if [[ ${#candidates[@]} -eq 0 ]]; then
        echo "Error: no executable matched $NS3_ROOT/build/scratch/mesh-sim/ns3*-sim-*"
        echo "Build first, pass the path as an argument, or set MESH_SIM_BIN."
        exit 1
    fi
    if [[ ${#candidates[@]} -gt 1 ]]; then
        echo "Error: multiple sim binaries matched; set MESH_SIM_BIN to pick one:"
        printf '  %s\n' "${candidates[@]}"
        exit 1
    fi
    BIN="${candidates[0]}"
fi

if [[ ! -x "$BIN" ]]; then
    echo "Error: binary not found or not executable: $BIN"
    echo "Either pass the path as an argument, set MESH_SIM_BIN, or build first."
    exit 1
fi

# ns-3 shared libraries live next to the binary's build tree.
export DYLD_LIBRARY_PATH="$NS3_ROOT/build/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
export LD_LIBRARY_PATH="$NS3_ROOT/build/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

SMOKE="$MESH_SIM_DIR/inputs/baselines/p0-smoke"
JAMMER="$MESH_SIM_DIR/inputs/baselines/p0-jammer-smoke"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0
FAIL=0

# Plain arithmetic assignment: ((PASS++)) returns 1 when PASS is 0, which
# would abort the run under `set -e`.
pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

echo "Running CLI integration tests..."
echo "Binary: $BIN"
echo ""

# --- Test 1: --PrintHelp exits 0 and mentions run-config ---
echo "Test 1: --PrintHelp"
if output=$("$BIN" --PrintHelp 2>&1) && echo "$output" | grep -q "run-config"; then
    pass "--PrintHelp shows run-config"
else
    fail "--PrintHelp should exit 0 and mention run-config"
fi

# --- Test 2: Missing --run-config exits nonzero ---
echo "Test 2: missing --run-config"
if "$BIN" 2>/dev/null; then
    fail "should exit nonzero without --run-config"
else
    pass "exits nonzero without --run-config"
fi

# --- Test 3: Nonexistent config file exits nonzero ---
echo "Test 3: nonexistent config file"
if "$BIN" --run-config=/nonexistent/path/run.ini 2>/dev/null; then
    fail "should exit nonzero for nonexistent config"
else
    pass "exits nonzero for nonexistent config"
fi

# Tests 4-8 need the baseline fixtures; a missing file would let the negative
# tests pass for the wrong reason.
for required in \
    "$SMOKE/run.ini" "$SMOKE/nodes.json" \
    "$JAMMER/run.ini" "$JAMMER/nodes.json" "$JAMMER/jammers.json"; do
    if [[ ! -f "$required" ]]; then
        echo "Error: missing required fixture: $required"
        exit 1
    fi
done

# --- Test 4: Bad seed value is rejected with the seed parser's message ---
echo "Test 4: bad seed value"
if "$BIN" --run-config="$SMOKE/run.ini" --seeds=abc --output-dir="$TMP/run4" \
        </dev/null >/dev/null 2>"$TMP/run4.err"; then
    fail "should exit nonzero for bad seed"
elif grep -q "invalid seed value" "$TMP/run4.err"; then
    pass "exits nonzero for bad seed value with 'invalid seed value'"
else
    fail "exited nonzero but stderr lacks 'invalid seed value'"
fi

# --- Test 5: Nonexistent positions-override is reported as missing ---
echo "Test 5: nonexistent positions-override"
if "$BIN" --run-config="$SMOKE/run.ini" --positions-override=/nonexistent/pos.json \
        --output-dir="$TMP/run5" </dev/null >/dev/null 2>"$TMP/run5.err"; then
    fail "should exit nonzero for nonexistent positions-override"
elif grep -q "positions-override file not found" "$TMP/run5.err"; then
    pass "exits nonzero with 'positions-override file not found'"
else
    fail "exited nonzero but stderr lacks 'positions-override file not found'"
fi

# --- Test 6: Valid run produces run.log and per-seed outputs ---
# p0-smoke has [rl] enabled, so stdout carries the RL JSON stream and stdin is
# the action channel; closed stdin makes every action a Stay.
echo "Test 6: valid run produces run.log"
if "$BIN" --run-config="$SMOKE/run.ini" --seed=1 --output-dir="$TMP/run6" \
        </dev/null >/dev/null 2>"$TMP/run6.err"; then
    if [[ ! -f "$TMP/run6/run.log" ]]; then
        fail "run.log not created"
    elif ! grep -q "seeds:" "$TMP/run6/run.log" || \
         ! grep -q "CLI overrides:" "$TMP/run6/run.log"; then
        fail "run.log exists but missing expected content"
    elif [[ ! -f "$TMP/run6/seed-1/summary.json" ]]; then
        fail "seed-1/summary.json not created"
    elif [[ ! -f "$TMP/run6/seed-1/links.csv" ]]; then
        fail "seed-1/links.csv not created"
    else
        pass "run.log, summary.json and links.csv created"
    fi
else
    fail "valid run should exit 0"
fi

# --- Test 7: --band on the CLI overrides the scenario band ---
echo "Test 7: CLI band precedence"
if "$BIN" --run-config="$SMOKE/run.ini" --band=sub-6 --seed=1 \
        --output-dir="$TMP/run7" </dev/null >/dev/null 2>&1; then
    if [[ ! -f "$TMP/run7/run.log" ]]; then
        fail "run.log not created for --band override"
    elif grep -Eq '^  band +=  *sub-6$' "$TMP/run7/run.log" && \
         grep -Eq '^  band_source +=  *cli$' "$TMP/run7/run.log"; then
        pass "run.log records band = sub-6 and band_source = cli"
    else
        fail "run.log does not record band = sub-6 with band_source = cli"
    fi
else
    fail "run with --band=sub-6 should exit 0"
fi

# --- Test 8: jammer scenario differs between sub-6 and mmwave ---
echo "Test 8: jammer A/B across bands"
jam_ok=1
if ! "$BIN" --run-config="$JAMMER/run.ini" --band=sub-6 --seed=1 \
        --output-dir="$TMP/jam-sub6" </dev/null >/dev/null 2>&1; then
    fail "jammer run with --band=sub-6 should exit 0"
    jam_ok=0
fi
if ! "$BIN" --run-config="$JAMMER/run.ini" --band=mmwave --seed=1 \
        --output-dir="$TMP/jam-mmwave" </dev/null >/dev/null 2>&1; then
    fail "jammer run with --band=mmwave should exit 0"
    jam_ok=0
fi

if [[ $jam_ok -eq 1 ]]; then
    if ! grep -Eq 'jammer_path_enabled *= *true' "$TMP/jam-sub6/run.log" 2>/dev/null; then
        fail "sub-6 run.log should record jammer_path_enabled = true"
    elif ! grep -Eq 'jammer_path_enabled *= *false' "$TMP/jam-mmwave/run.log" 2>/dev/null; then
        fail "mmwave run.log should record jammer_path_enabled = false"
    elif [[ ! -f "$TMP/jam-sub6/seed-1/links.csv" || ! -f "$TMP/jam-mmwave/seed-1/links.csv" ]]; then
        fail "both jammer runs should produce seed-1/links.csv"
    else
        # Match rows on (time_s,node_a,node_b) and count sinr_db differences.
        cmp_out=$(awk -F, '
            function strip(s) { gsub(/\r/, "", s); return s }
            FNR == 1 { file++ }
            /^#/ { next }
            !hdr[file] {
                for (i = 1; i <= NF; i++) {
                    k = strip($i)
                    if (k == "sinr_db") sinr[file] = i
                    if (k == "time_s")  t[file] = i
                    if (k == "node_a")  a[file] = i
                    if (k == "node_b")  b[file] = i
                }
                hdr[file] = 1
                next
            }
            {
                key = strip($(t[file])) "," strip($(a[file])) "," strip($(b[file]))
                if (file == 1) { v1[key] = strip($(sinr[file])); n1++ }
                else           { v2[key] = strip($(sinr[file])); n2++ }
            }
            END {
                diff = 0; missing = 0
                for (k in v1) {
                    if (!(k in v2)) missing++
                    else if (v1[k] != v2[k]) diff++
                }
                for (k in v2) if (!(k in v1)) missing++
                print diff, missing, n1, n2
            }
        ' "$TMP/jam-sub6/seed-1/links.csv" "$TMP/jam-mmwave/seed-1/links.csv")
        read -r n_diff n_missing rows1 rows2 <<<"$cmp_out"
        if [[ "$n_missing" -ne 0 || "$rows1" -ne "$rows2" ]]; then
            fail "links.csv key sets differ ($n_missing unmatched, $rows1 vs $rows2 rows)"
        elif [[ "$n_diff" -ge 1 ]]; then
            pass "jammer band A/B differs in $n_diff matched links"
        else
            fail "no matched link differs in sinr_db between sub-6 and mmwave"
        fi
    fi
fi

# --- Summary ---
echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ $FAIL -gt 0 ]]; then
    echo "SOME TESTS FAILED."
    exit 1
fi
echo "All tests passed."
