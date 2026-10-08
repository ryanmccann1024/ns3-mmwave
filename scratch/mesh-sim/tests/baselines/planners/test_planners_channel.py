"""ChannelScorer (mesh_channel_query_v1 client) edge cases: fake_query.py and custom workers.

No real simulator is started. Gaps over scripts/baselines/tests/test_channel.py: batch
splits at exactly max_layouts / the byte limit, probe-limit boundary, init type and
tolerance edges, framing (split lines, stray lines, echoed ids), the worker's own
`connected` flags, worker death between/mid requests, and cleanup on exceptions.
"""

import json
import time

import numpy as np
import pytest

from scripts.baselines.effective_inputs import start_position
from scripts.baselines.planners.channel import ChannelScorer, PlannerError
from scripts.baselines.tests.conftest import NODES, SCENARIO_SECTIONS, fake_query_binary

from ._planner_support import (CUSTOM_ROSTER, CUSTOM_STARTS, assert_gone, make_worker,
                               read_records)

ROSTER = [node["id"] for node in NODES]
STARTS = np.array([start_position(node) for node in NODES])
PAIRS = len(ROSTER) * (len(ROSTER) - 1) // 2
FAKE_ENV = ("FAKE_QUERY_FAULT", "FAKE_QUERY_FAULT_AT", "FAKE_QUERY_INIT_PATCH",
            "FAKE_QUERY_PAD_BYTES", "FAKE_QUERY_RANGE_M", "FAKE_QUERY_RECORD",
            "FAKE_QUERY_PID_FILE", "CUSTOM_PID", "CUSTOM_RECORD")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Scenario for fake_query.py (seed 7, run_id 1), shim, record/PID files and log."""
    for name in FAKE_ENV:
        monkeypatch.delenv(name, raising=False)
    scenario = tmp_path / "scenario"
    scenario.mkdir()
    (scenario / "run.ini").write_text(SCENARIO_SECTIONS.replace("seed = 1", "seed = 7"))
    (scenario / "nodes.json").write_text(json.dumps(NODES, indent=2) + "\n")
    paths = {"ini": scenario / "run.ini", "bin": fake_query_binary(tmp_path / "bin"),
             "record": tmp_path / "record.jsonl", "pids": tmp_path / "pids.json",
             "custom_pid": tmp_path / "custom.pid", "custom_record": tmp_path / "custom.jsonl",
             "log": tmp_path / "planner.log", "tmp": tmp_path}
    monkeypatch.setenv("FAKE_QUERY_RECORD", str(paths["record"]))
    monkeypatch.setenv("FAKE_QUERY_PID_FILE", str(paths["pids"]))
    monkeypatch.setenv("CUSTOM_PID", str(paths["custom_pid"]))
    monkeypatch.setenv("CUSTOM_RECORD", str(paths["custom_record"]))
    with open(paths["log"], "w", encoding="utf-8") as log:
        paths["stream"] = log
        yield paths


def _fake(env, *, mode="standalone", band=None, roster=None, starts=None, **kwargs):
    return ChannelScorer(env["bin"], env["ini"], 7, 1, band, mode,
                         ROSTER if roster is None else roster,
                         STARTS if starts is None else starts, 7, env["stream"], **kwargs)


def _custom(env, body, **kwargs):
    binary = make_worker(env["tmp"] / "custom", body)
    return ChannelScorer(binary, env["ini"], 7, 1, None, "standalone", CUSTOM_ROSTER,
                         CUSTOM_STARTS, 7, env["stream"], **kwargs)


def _custom_pid(env) -> int:
    deadline = time.monotonic() + 5.0
    while not env["custom_pid"].exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    return int(env["custom_pid"].read_text())


def _patch_init(monkeypatch, patch: dict) -> None:
    monkeypatch.setenv("FAKE_QUERY_INIT_PATCH", json.dumps(patch))


def _expected_connected(layout) -> np.ndarray:
    layout = np.asarray(layout, dtype=float)
    distance = np.linalg.norm(layout[:, None, :] - layout[None, :, :], axis=2)
    connected = distance <= 100.0
    np.fill_diagonal(connected, False)
    return connected


# ---------------------------------------------------------------------------------------
# Constructor validation happens before any worker is launched.

@pytest.mark.parametrize("kwargs,roster,starts", [
    ({"request_timeout_s": 0.0}, None, None),
    ({"request_timeout_s": -1.0}, None, None),
    ({"max_layouts": 0}, None, None),
    ({"max_layouts": True}, None, None),
    ({"max_layouts": 2.0}, None, None),
    ({}, ["only"], [[0.0, 0.0, 1.0]]),
    ({}, ["a", "a"], [[0.0, 0.0, 1.0], [1.0, 0.0, 1.0]]),
    ({}, None, STARTS[:-1]),
    ({}, None, np.vstack([STARTS[:-1], [[np.inf, 0.0, 1.0]]])),
])
def test_invalid_constructor_arguments_never_launch_a_worker(env, kwargs, roster, starts):
    with pytest.raises(ValueError):
        _fake(env, roster=roster, starts=starts, **kwargs)
    assert not env["record"].exists(), "a worker was launched for invalid arguments"


@pytest.mark.parametrize("mode,band", [("planning", None), ("standalone", "5g")])
def test_invalid_mode_or_band_never_launch_a_worker(env, mode, band):
    with pytest.raises(ValueError):
        _fake(env, mode=mode, band=band)
    assert not env["record"].exists()


# ---------------------------------------------------------------------------------------
# Init handshake edges.

@pytest.mark.parametrize("patch,needle", [
    ({"node_ids": ROSTER + ["extra"]}, "node_ids"),
    ({"node_ids": ROSTER[:-1]}, "node_ids"),
    ({"seed": 7.0}, "seed"),
    ({"run_id": "1"}, "run_id"),
    ({"jammer_seed": True}, "jammer_seed"),
    ({"rl_enabled": 0}, "rl_enabled"),
    ({"limits": {"max_layouts": True}}, "limits"),
    ({"limits": {"max_probes": 10000.0}}, "limits"),
    ({"limits": {"max_child_response_bytes": -1}}, "limits"),
    ({"sinr_threshold_db": True}, "sinr_threshold_db"),
    ({"channel": {"rx_array_gain_dbi": None}}, "rx_array_gain_dbi"),
    ({"contract": "MESH_CHANNEL_QUERY_V1"}, "contract"),
])
def test_init_type_and_count_mismatches_abort(env, monkeypatch, patch, needle):
    _patch_init(monkeypatch, patch)
    with pytest.raises(PlannerError, match=needle):
        _fake(env)
    assert_gone(json.loads(env["pids"].read_text())["worker"])


def test_init_node_count_mismatch_with_matching_prefix(env, monkeypatch):
    extra = STARTS.tolist() + [[1.0, 1.0, 1.0]]
    _patch_init(monkeypatch, {"node_ids": ROSTER + ["x"], "start_positions": extra})
    with pytest.raises(PlannerError, match="node_ids.*start_positions"):
        _fake(env)


@pytest.mark.parametrize("shift,ok", [(5e-7, True), (1e-6, True), (2e-6, False)])
def test_init_start_position_tolerance_is_one_micrometre(env, monkeypatch, shift, ok):
    starts = STARTS.copy()
    starts[3, 0] += shift
    _patch_init(monkeypatch, {"start_positions": starts.tolist()})
    if ok:
        with _fake(env) as scorer:
            assert scorer.init["start_positions"][3][0] == starts[3, 0]
    else:
        with pytest.raises(PlannerError, match="start_positions"):
            _fake(env)


def test_unknown_extra_init_fields_are_accepted(env, monkeypatch):
    _patch_init(monkeypatch, {"future_field": {"a": 1}, "channel": {"new_knob": 3}})
    with _fake(env) as scorer:
        assert scorer.init["future_field"] == {"a": 1}
        assert scorer.channel["new_knob"] == 3


def test_init_band_from_ini_is_fine_when_no_band_was_requested(env, monkeypatch):
    _patch_init(monkeypatch, {"band": "sub-6", "band_source": "run.ini"})
    with _fake(env) as scorer:
        assert scorer.band == "sub-6"


@pytest.mark.parametrize("body,needle", [
    ("emit('hello')", "malformed JSON in init line"),
    ("emit('{\"type\": \"init\", \"sinr_threshold_db\": NaN}')", "malformed JSON"),
    ("emit([1, 2, 3])", "did not start with an init line"),
    ("sys.exit(5)", "ended before the init line; it exited with code 5"),
])
def test_bad_or_missing_init_line_aborts_and_reaps(env, body, needle):
    with pytest.raises(PlannerError, match=needle):
        _custom(env, body)
    assert_gone(_custom_pid(env))


def test_silent_worker_times_out_on_init_and_is_reaped(env):
    started = time.monotonic()
    with pytest.raises(PlannerError, match="timed out waiting for the init line"):
        _custom(env, "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                     "while True:\n    time.sleep(0.1)",
                init_timeout_s=0.5, terminate_wait_s=0.3)
    assert_gone(_custom_pid(env))
    assert time.monotonic() - started < 15


def test_worker_stderr_reaches_the_planner_log(env):
    body = ("sys.stderr.write('custom-worker-diagnostic\\n'); sys.stderr.flush()\n"
            "emit(init_obj())\nfor req in requests():\n    emit(result(req))")
    with _custom(env, body):
        pass
    env["stream"].flush()
    assert "custom-worker-diagnostic" in env["log"].read_text()


# ---------------------------------------------------------------------------------------
# Batching boundaries.

@pytest.mark.parametrize("count,override,expected", [
    (1024, None, [1024]),
    (1025, None, [1024, 1]),
    (1025, 5000, [1024, 1]),     # an override never raises the published limit
    (6, 3, [3, 3]),
    (7, 1, [1] * 7),
])
def test_batches_split_at_exactly_max_layouts(env, count, override, expected):
    layouts = [STARTS] * count
    with _fake(env, max_layouts=override) as scorer:
        results = scorer.evaluate(layouts)
        stats = scorer.stats
    records = read_records(env["record"], "evaluate")
    assert [r["layouts"] for r in records] == expected
    assert [r["request_id"] for r in records] == list(range(1, len(expected) + 1))
    assert all(r["problem"] is None for r in records)
    assert len(results) == count
    assert stats["requests"] == len(expected) and stats["layouts"] == count
    assert stats["links"] == count * PAIRS and stats["probe_links"] == 0


def _byte_env(monkeypatch, extra: int) -> int:
    one = len(json.dumps(STARTS.tolist(), separators=(",", ":")))
    fixed = len('{"type":"evaluate","request_id":%d,"layouts":[]}\n' % 10 ** 18)
    limit = fixed + extra(one) if callable(extra) else fixed + extra
    _patch_init(monkeypatch, {"limits": {"max_request_line_bytes": limit}})
    return limit


@pytest.mark.parametrize("extra,expected", [
    (lambda one: 2 * one + 1, [2, 2, 1]),   # exactly two layouts plus the comma fit
    (lambda one: 2 * one, [1, 1, 1, 1, 1]),  # one byte short of two
    (lambda one: one, [1, 1, 1, 1, 1]),      # exactly one layout fits
])
def test_byte_limit_split_boundaries(env, monkeypatch, extra, expected):
    limit = _byte_env(monkeypatch, extra)
    with _fake(env) as scorer:
        results = scorer.evaluate([STARTS] * 5)
    records = read_records(env["record"], "evaluate")
    assert [r["layouts"] for r in records] == expected
    assert all(r["bytes"] <= limit and r["problem"] is None for r in records)
    assert len(results) == 5


def test_one_byte_below_a_single_layout_aborts_before_sending(env, monkeypatch):
    _byte_env(monkeypatch, lambda one: one - 1)
    with _fake(env) as scorer:
        with pytest.raises(PlannerError, match="max_request_line_bytes"):
            scorer.evaluate([STARTS])
        assert scorer.closed
    assert not read_records(env["record"], "evaluate")


def test_results_keep_input_order_across_batches_and_probes_ride_every_batch(env):
    probes = [[150.0, 180.0], [400.0, 400.0]]
    layouts = []
    for k in range(5):
        layout = STARTS.copy()
        layout[1, 0] += 40.0 * k   # uav-a drifts away from gw step by step
        layouts.append(layout)
    with _fake(env, max_layouts=2) as scorer:
        scorer.set_probes(probes)
        results = scorer.evaluate(layouts)
        stats = scorer.stats
    for layout, result in zip(layouts, results):
        assert np.array_equal(result.connected, _expected_connected(layout))
    records = read_records(env["record"], "evaluate")
    assert [r["layouts"] for r in records] == [2, 2, 1]
    assert all(r["probes"]["points"] == probes for r in records)
    assert stats["probe_links"] == 5 * len(ROSTER) * len(probes)


def test_layout_error_index_counts_across_batches(env, monkeypatch):
    monkeypatch.setenv("FAKE_QUERY_FAULT", "layout_error")
    monkeypatch.setenv("FAKE_QUERY_FAULT_AT", "2")
    with _fake(env, max_layouts=2) as scorer:
        with pytest.raises(PlannerError, match=r"^layout 2 failed"):
            scorer.evaluate([STARTS] * 5)
        worker = scorer.pid
        assert scorer.stats["requests"] == 1  # the failed request is not counted
    assert_gone(worker)


@pytest.mark.parametrize("count,ok", [(3, True), (4, False)])
def test_probe_count_boundary_is_max_probes(env, monkeypatch, count, ok):
    _patch_init(monkeypatch, {"limits": {"max_probes": 3}})
    points = [[float(k), 0.0] for k in range(count)]
    with _fake(env) as scorer:
        if ok:
            scorer.set_probes(points)
            (result,) = scorer.evaluate([STARTS])
            assert len(result.coverage) == len(ROSTER)
        else:
            with pytest.raises(PlannerError, match="max_probes"):
                scorer.set_probes(points)
            assert scorer.probes is None and not scorer.closed


@pytest.mark.parametrize("points,kwargs", [
    ([], {}),
    ([1.0, 2.0], {}),
    ([[1.0, 2.0, 3.0]], {}),
    ([[float("nan"), 0.0]], {}),
    ([[1.0, 2.0]], {"height_m": -0.1}),
    ([[1.0, 2.0]], {"height_m": float("inf")}),
    ([[1.0, 2.0]], {"sinr_db": float("nan")}),
    ([[1.0, 2.0]], {"rx_gain_dbi": float("-inf")}),
])
def test_invalid_probe_settings_are_value_errors(env, points, kwargs):
    with _fake(env) as scorer:
        with pytest.raises(ValueError):
            scorer.set_probes(points, **kwargs)
        assert scorer.probes is None and not scorer.closed


def test_probe_height_zero_is_allowed(env):
    with _fake(env) as scorer:
        scorer.set_probes([[0.0, 0.0]], height_m=0.0)
        assert scorer.probes["height_m"] == 0.0


def test_layout_result_diagonals(env):
    with _fake(env) as scorer:
        (result,) = scorer.evaluate([STARTS])
    diag = np.arange(len(ROSTER))
    assert np.all(np.isneginf(result.sinr_db[diag, diag]))
    assert np.all(result.capacity_mbps[diag, diag] == 0.0)
    assert not result.is_los[diag, diag].any() and not result.connected[diag, diag].any()
    assert np.array_equal(result.capacity_mbps, result.capacity_mbps.T)


# ---------------------------------------------------------------------------------------
# Framing and response validation through custom workers.

SERVE = "emit(init_obj())\nfor req in requests():\n"


def test_response_split_across_many_writes_is_reassembled(env):
    body = SERVE + ("    text = json.dumps(result(req)) + '\\n'\n"
                    "    for k in range(0, len(text), 13):\n"
                    "        sys.stdout.write(text[k:k + 13]); sys.stdout.flush()\n"
                    "        time.sleep(0.001)\n")
    with _custom(env, body) as scorer:
        first, second = scorer.evaluate([CUSTOM_STARTS, CUSTOM_STARTS])
    assert np.array_equal(first.connected, _expected_connected(CUSTOM_STARTS))
    assert np.array_equal(first.sinr_db, second.sinr_db)


def test_worker_connected_flags_are_used_verbatim(env):
    # The worker says the strong 0-1 link is down and the weak 0-2 link is up; the client
    # must not re-derive `connected` from sinr_db or sinr_threshold_db.
    body = ("emit(init_obj(sinr_threshold_db=50.0))\nfor req in requests():\n"
            "    out = result(req)\n"
            "    for entry in out['layouts']:\n"
            "        entry['links'] = [[0, 1, 40.0, 1.0, True, False],\n"
            "                          [0, 2, -90.0, 0.0, False, True],\n"
            "                          [1, 2, -6.7, 0.0, False, False]]\n"
            "    emit(out)\n")
    with _custom(env, body) as scorer:
        assert scorer.sinr_threshold_db == 50.0
        (result,) = scorer.evaluate([CUSTOM_STARTS])
    assert result.connected.tolist() == [[False, False, True], [False, False, False],
                                         [True, False, False]]
    assert result.sinr_db[0, 1] == 40.0 and result.sinr_db[2, 0] == -90.0
    assert result.is_los[0, 1] and not result.is_los[0, 2]


def _mutate(code: str) -> str:
    """Worker that applies `code` (with `out` and `req` in scope) before replying."""
    return SERVE + "    out = result(req)\n" + "".join(
        f"    {line}\n" for line in code.splitlines()) + "    emit(out)\n"


@pytest.mark.parametrize("code,needle", [
    ("out['request_id'] = True", "echoes request_id"),
    ("out['request_id'] = float(req['request_id'])", "echoes request_id"),
    ("out['request_id'] = req['request_id'] - 1", "echoes request_id"),
    ("del out['wall_s']", "wall_s"),
    ("out['wall_s'] = 'fast'", "wall_s"),
    ("out['layouts'].append(out['layouts'][0])", "expected 1 layout results"),
    ("out['layouts'] = {}", "expected 1 layout results"),
    ("out['type'] = 'results'", "unexpected response type"),
    ("out = [out]", "not a JSON object"),
    ("out['layouts'][0]['error'] = 'boom'", "layout 0 failed.*boom"),
    ("out['layouts'][0] = 'oops'", "not a JSON object"),
    ("del out['layouts'][0]['wall_s']", "layout 0: wall_s"),
    ("out['layouts'][0]['links'][0][:2] = [1, 0]", r"is not \[0, 1"),
    ("out['layouts'][0]['links'][0][:2] = [0.0, 1.0]", r"is not \[0, 1"),
    ("out['layouts'][0]['links'][0].append(0)", r"is not \[0, 1"),
    ("out['layouts'][0]['links'][0][2] = '3.0'", "non-finite"),
    ("out['layouts'][0]['links'][0][3] = None", "non-finite"),
    ("out['layouts'][0]['links'][0][4] = 1", "not boolean"),
    ("out['layouts'][0]['links'][0][5] = 0", "not boolean"),
    ("out['layouts'][0]['links'].reverse()", r"is not \[0, 1"),
    ("out['layouts'][0]['coverage'] = [[]] * 3", "coverage returned without probes"),
])
def test_malformed_responses_abort_without_results(env, code, needle):
    with _custom(env, _mutate(code)) as scorer:
        with pytest.raises(PlannerError, match=needle):
            scorer.evaluate([CUSTOM_STARTS])
        assert scorer.closed
    assert_gone(_custom_pid(env))


@pytest.mark.parametrize("code,needle", [
    ("out['layouts'][0]['coverage'] = None", "one list per node"),
    ("out['layouts'][0]['coverage'] = [[0], [0]]", "one list per node"),
    ("out['layouts'][0]['coverage'][0] = [-1]", "probe index outside 0..1"),
    ("out['layouts'][0]['coverage'][0] = [2]", "probe index outside 0..1"),
    ("out['layouts'][0]['coverage'][0] = [True]", "probe index"),
    ("out['layouts'][0]['coverage'][0] = [0.0]", "probe index"),
    ("out['layouts'][0]['coverage'][0] = 0", "probe index"),
])
def test_malformed_coverage_aborts(env, code, needle):
    with _custom(env, _mutate(code)) as scorer:
        scorer.set_probes([[0.0, 0.0], [500.0, 500.0]])
        with pytest.raises(PlannerError, match=needle):
            scorer.evaluate([CUSTOM_STARTS])


def test_duplicate_and_unsorted_coverage_indices_are_normalised(env):
    with _custom(env, _mutate("out['layouts'][0]['coverage'][0] = [1, 0, 1, 0]")) as scorer:
        scorer.set_probes([[0.0, 0.0], [10.0, 0.0]])
        (result,) = scorer.evaluate([CUSTOM_STARTS])
    assert result.coverage[0] == [0, 1]


def test_unknown_extra_response_fields_are_accepted(env):
    code = "out['debug'] = {'x': 1}\nout['layouts'][0]['extra'] = [1, 2]"
    with _custom(env, _mutate(code)) as scorer:
        (result,) = scorer.evaluate([CUSTOM_STARTS])
    assert result.connected[0, 1]


def test_stray_line_before_the_result_aborts(env):
    body = SERVE + ("    emit({'type': 'error', 'request_id': None, 'message': 'stray'})\n"
                    "    emit(result(req))\n")
    with _custom(env, body) as scorer:
        with pytest.raises(PlannerError, match="rejected.*stray"):
            scorer.evaluate([CUSTOM_STARTS])
        assert scorer.closed
    assert_gone(_custom_pid(env))


def test_nonfinite_token_in_a_response_is_malformed(env):
    body = SERVE + ("    text = json.dumps(result(req))\n"
                    "    emit(text.replace('\"wall_s\": 0.01', '\"wall_s\": Infinity'))\n")
    with _custom(env, body) as scorer:
        with pytest.raises(PlannerError, match="malformed JSON"):
            scorer.evaluate([CUSTOM_STARTS])


# ---------------------------------------------------------------------------------------
# Worker death and cleanup.

def test_worker_exit_between_requests(env):
    body = SERVE + "    emit(result(req))\n    sys.exit(0)\n"
    scorer = _custom(env, body, terminate_wait_s=0.5)
    pid = scorer.pid
    (first,) = scorer.evaluate([CUSTOM_STARTS])
    assert first.connected[0, 1]
    with pytest.raises(PlannerError, match="ended before|stopped reading"):
        scorer.evaluate([CUSTOM_STARTS])
    assert scorer.closed
    scorer.close()  # idempotent, no exception after the abort
    assert_gone(pid)


def test_worker_death_mid_batch_returns_nothing(env):
    body = ("emit(init_obj())\n"
            "for n, req in enumerate(requests(), 1):\n"
            "    if n == 2:\n        os._exit(0)\n"
            "    emit(result(req))\n")
    with _custom(env, body, max_layouts=1) as scorer:
        with pytest.raises(PlannerError, match="ended before the response to request 2.*"
                                               "exited with code 0"):
            scorer.evaluate([CUSTOM_STARTS] * 3)
        assert scorer.stats["requests"] == 1
    assert len(read_records(env["custom_record"], "evaluate")) == 2


def test_closed_stdout_while_running_is_reported_and_killed(env):
    body = ("emit(init_obj())\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "for req in requests():\n"
            "    os.close(1)\n"
            "    while True:\n        time.sleep(0.1)\n")
    with _custom(env, body, terminate_wait_s=0.3) as scorer:
        with pytest.raises(PlannerError, match="still running"):
            scorer.evaluate([CUSTOM_STARTS])
    assert_gone(_custom_pid(env))


def test_close_kills_a_worker_that_ignores_shutdown_and_sigterm(env):
    body = ("emit(init_obj())\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "for req in requests():\n    emit(result(req))\n"
            "while True:\n    time.sleep(0.1)\n")
    scorer = _custom(env, body, shutdown_grace_s=0.3, terminate_wait_s=0.3)
    pid = scorer.pid
    scorer.evaluate([CUSTOM_STARTS])
    started = time.monotonic()
    scorer.close()
    assert time.monotonic() - started < 10
    assert read_records(env["custom_record"], "shutdown"), "shutdown was not sent"
    assert_gone(pid)


def test_value_error_on_bad_layout_keeps_the_worker_usable(env):
    with _fake(env) as scorer:
        with pytest.raises(ValueError, match="layout 1"):
            scorer.evaluate([STARTS, STARTS[:, :2]])
        assert not read_records(env["record"], "evaluate")
        (result,) = scorer.evaluate([STARTS])
        assert scorer.stats["requests"] == 1
    assert np.array_equal(result.connected, _expected_connected(STARTS))
