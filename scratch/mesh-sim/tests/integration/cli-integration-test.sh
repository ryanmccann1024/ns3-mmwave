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
MULTI="$MESH_SIM_DIR/inputs/baselines/p1-multi-smoke"

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

# Tests 4-12 need the baseline fixtures; a missing file would let the negative
# tests pass for the wrong reason.
for required in \
    "$SMOKE/run.ini" "$SMOKE/nodes.json" \
    "$JAMMER/run.ini" "$JAMMER/nodes.json" "$JAMMER/jammers.json" \
    "$MULTI/run.ini" "$MULTI/nodes.json"; do
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

# ---------------------------------------------------------------------------
# Tests 9-12: P1 centralized multi-node RL control (p1-multi-smoke).
# The JSON stream and positions.csv are checked with a small python3 helper so
# the assertions read on fields rather than on line offsets.
# ---------------------------------------------------------------------------
cat >"$TMP/check_p1.py" <<'PYEOF'
import json
import sys

stdout_path, pos_path = sys.argv[1], sys.argv[2]
errors = []


def eq(label, got, want):
    if got != want:
        errors.append(f"{label}: got {got!r}, want {want!r}")


def close(label, got, want, tol=1e-6):
    if abs(got - want) > tol:
        errors.append(f"{label}: got {got}, want {want}")


with open(stdout_path) as fh:
    msgs = [json.loads(line) for line in fh if line.strip()]

if not msgs:
    print("stdout is empty")
    sys.exit(1)

init = msgs[0]
eq("line 1 type", init.get("type"), "init")
eq("init.contract", init.get("contract"), "mesh_move_2d_v1")
eq("init.slot_node_ids", init.get("slot_node_ids"), ["node-b", "node-c", None])
eq("init.obs_dim", init.get("obs_dim"), 24)
eq("init.mask_dim", init.get("mask_dim"), 15)
eq("init.decision_interval_ticks", init.get("decision_interval_ticks"), 5)
eq("init.num_ticks", init.get("num_ticks"), 10)
eq("init.num_decisions", init.get("num_decisions"), 2)

steps = [m for m in msgs if m.get("type") == "step"]
eq("step line count", len(steps), 3)
if len(steps) == 3:
    eq("step ticks", [m["tick"] for m in steps], [0, 5, 10])
    eq("ticks_in_step", [m["ticks_in_step"] for m in steps], [1, 5, 5])
    eq("decisions", [m["decision"] for m in steps], [0, 1, 2])
    eq("final done", steps[-1]["done"], True)
    mask = steps[1]["mask"]
    eq("tick-5 mask length", len(mask), 15)
    if len(mask) == 15:
        eq("tick-5 mask[1] (slot 0 east)", mask[1], 0)
        eq("tick-5 mask[6] (slot 1 east)", mask[6], 0)
        for i in (4, 9, 14):
            eq(f"tick-5 mask[{i}] (hold)", mask[i], 1)
        for i in range(10, 14):
            eq(f"tick-5 mask[{i}] (padded slot)", mask[i], 0)

rows = []
with open(pos_path) as fh:
    for line in fh:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("time_s"):
            continue
        f = line.split(",")
        rows.append((float(f[0]), int(f[1]), float(f[2]), float(f[3]), float(f[4])))


def at(node, t):
    for (rt, rn, x, y, z) in rows:
        if rn == node and abs(rt - t) < 1e-9:
            return (x, y, z)
    errors.append(f"no positions.csv row for node {node} at t={t}")
    return None


b05 = at(1, 0.5)
if b05:
    close("node 1 x at t=0.5", b05[0], 100.0)
    close("node 1 y at t=0.5", b05[1], -5.0)
    close("node 1 z at t=0.5", b05[2], 10.0)

for t in (0.3, 0.4, 0.5):
    c = at(2, t)
    if c:
        close(f"node 2 x at t={t}", c[0], 100.0)
c10 = at(2, 1.0)
if c10:
    close("node 2 x at t=1.0", c10[0], 95.0)

for (rt, rn, x, y, z) in rows:
    if rn in (1, 2) and x > 100.0 + 1e-6:
        errors.append(f"node {rn} left x_max at t={rt} (x={x})")

a0, a1 = at(0, 0.0), at(0, 1.0)
if a0 and a1 and a0 == a1:
    errors.append("node 0 did not move (uncontrolled random walk)")

if errors:
    print("\n".join(errors))
    sys.exit(1)
sys.exit(0)
PYEOF

# --- Test 9: centralized RL run drives both controlled nodes ---
echo "Test 9: p1-multi-smoke centralized RL stream"
run9_ok=1
if ! printf '{"action":[2,1,4]}\n{"action":[4,0,4]}\n' \
        | "$BIN" --run-config="$MULTI/run.ini" --seed=1 --output-dir="$TMP/run9" \
          >"$TMP/run9.out" 2>"$TMP/run9.err"; then
    fail "p1-multi-smoke scripted run should exit 0"
    run9_ok=0
fi

if [[ $run9_ok -eq 1 ]]; then
    if ! check_out=$(python3 "$TMP/check_p1.py" "$TMP/run9.out" \
                     "$TMP/run9/seed-1/positions.csv" 2>&1); then
        fail "centralized stream/positions mismatch: $check_out"
    elif ! grep -Eq '^  rl\.control_mode +=  *centralized$' "$TMP/run9/run.log"; then
        fail "run.log should record rl.control_mode = centralized"
    elif ! grep -Eq '^  rl\.controlled_nodes +=  *node-b,node-c$' "$TMP/run9/run.log"; then
        fail "run.log should record rl.controlled_nodes = node-b,node-c"
    elif ! grep -Eq '^  rl\.decision_interval_ticks +=  *5$' "$TMP/run9/run.log"; then
        fail "run.log should record rl.decision_interval_ticks = 5"
    else
        pass "init/step stream, clipped positions and run.log provenance"
    fi
fi

# --- Test 10: the same scripted run is byte-identical ---
echo "Test 10: centralized determinism"
if printf '{"action":[2,1,4]}\n{"action":[4,0,4]}\n' \
        | "$BIN" --run-config="$MULTI/run.ini" --seed=1 --output-dir="$TMP/run10" \
          >"$TMP/run10.out" 2>"$TMP/run10.err"; then
    if [[ $run9_ok -ne 1 ]]; then
        fail "determinism needs the test 9 run to succeed"
    elif ! cmp -s "$TMP/run9.out" "$TMP/run10.out"; then
        fail "repeated scripted run produced different stdout"
    elif ! cmp -s "$TMP/run9/seed-1/positions.csv" "$TMP/run10/seed-1/positions.csv"; then
        fail "repeated scripted run produced different positions.csv"
    else
        pass "stdout and positions.csv byte-identical across repeats"
    fi
else
    fail "repeated p1-multi-smoke run should exit 0"
fi

# --- Test 11: centralized config errors ---
# Temporary copies only; the committed fixture is never modified.
echo "Test 11: centralized config errors"
err_ok=1
for case in ghost both profile; do
    mkdir -p "$TMP/bad-$case"
    cp "$MULTI/run.ini" "$MULTI/nodes.json" "$TMP/bad-$case/"
done
python3 - "$TMP" <<'PYEOF'
import sys

tmp = sys.argv[1]
edits = {
    "ghost": lambda line: "controlled_nodes      = node-b, ghost\n"
    if line.startswith("controlled_nodes") else line,
    "both": lambda line: "controlled_nodes      = node-b, node-c\n"
    "controlled_node_id    = node-b\n"
    if line.startswith("controlled_nodes") else line,
    "profile": lambda line: "action_profile        = move_3d\n"
    if line.startswith("action_profile") else line,
}
for case, edit in edits.items():
    path = f"{tmp}/bad-{case}/run.ini"
    with open(path) as fh:
        lines = fh.readlines()
    with open(path, "w") as fh:
        fh.writelines(edit(line) for line in lines)
PYEOF

check_err() {
    local case="$1" needle="$2"
    if "$BIN" --run-config="$TMP/bad-$case/run.ini" --seed=1 \
            --output-dir="$TMP/bad-$case/out" </dev/null \
            >/dev/null 2>"$TMP/bad-$case.err"; then
        fail "bad-$case should exit nonzero"
        err_ok=0
    elif ! grep -qF "$needle" "$TMP/bad-$case.err"; then
        fail "bad-$case stderr lacks \"$needle\""
        err_ok=0
    fi
}

check_err ghost "unknown node id 'ghost'"
check_err both "mutually exclusive"
check_err profile "'move_3d' is reserved"

if [[ $err_ok -eq 1 ]]; then
    pass "unknown id, mutually exclusive selectors and move_3d are rejected"
fi

# --- Test 12: legacy stream shape is unchanged ---
echo "Test 12: legacy RL stream shape"
if "$BIN" --run-config="$SMOKE/run.ini" --seed=1 --output-dir="$TMP/run12" \
        </dev/null >"$TMP/run12.out" 2>"$TMP/run12.err"; then
    line_count=$(grep -c '' "$TMP/run12.out" || true)
    if [[ "$line_count" -ne 5 ]]; then
        fail "legacy stdout should have 5 lines, got $line_count"
    elif grep -q '"type":"init"' "$TMP/run12.out"; then
        fail "legacy stdout must not contain an init message"
    elif ! head -n 1 "$TMP/run12.out" | grep -q 'controlled_pos'; then
        fail "legacy first line should contain controlled_pos"
    else
        pass "legacy stream is 5 step lines with no init message"
    fi
else
    fail "legacy p0-smoke run should exit 0"
fi

# --- Summary ---
echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ $FAIL -gt 0 ]]; then
    echo "SOME TESTS FAILED."
    exit 1
fi
echo "All tests passed."
