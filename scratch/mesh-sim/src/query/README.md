@page src_query src/query

@brief `--channel-query`: scores candidate start layouts through the simulator's own channel path.

`--channel-query` turns the simulator binary into a long-lived worker that
scores node layouts on stdin/stdout. Each layout is evaluated with the run's
resolved band, per-node gains, buildings, jammers and propagation models. The
placement baselines (`scripts/baselines/`) use it to score the layouts they
propose. The only Python client is `scripts/baselines/planners/channel.py`
(`ChannelScorer`).

## 1\. Usage

The user builds the binary. A client launches it like this:

```bash
<BIN> --run-config=<staged run.ini> --channel-query --seed=<planning seed> \
      [--band=sub-6] [--rl-mode]
```

`sim.cc` loads and validates the config, applies `--run-id` / `--band` /
`--rl-mode`, resolves RL control, then calls `RunChannelQuery`. The worker
prints one init line, then answers one request per line until `shutdown` or
EOF.

| Rule | Behavior |
|------|----------|
| Seeds | Must resolve to exactly one value; otherwise `Error: --channel-query needs exactly one seed`, exit 1. |
| `--output-dir` | Ignored, with a note on stderr. |
| Disk output | None: no output directory, archive or `run.log`. |
| `[baseline]` guard | Not applied in this mode. |
| Streams | stdout carries only NDJSON; logs go to stderr. |
| Exit | `shutdown` or EOF ends the worker with exit code 0. |

## 2\. Wire contract mesh_channel_query_v1

One JSON object per line in each direction.

### 2.1 Init

The first stdout line:

```json
{"type":"init","contract":"mesh_channel_query_v1","isolation":"fork_per_layout",
 "node_ids":[...],"node_types":[...],"mobility":[...],
 "start_positions":[[x,y,z],...],"controlled_indices":[...],"rl_enabled":false,
 "band":"sub-6","band_source":"cli","seed":1,"run_id":1,"jammer_seed":1,
 "sinr_threshold_db":-6.7,"jammer_path_enabled":true,"num_buildings":0,
 "channel":{"frequency_ghz":2.4,"tx_power_dbm":30.0,"bandwidth_mhz":400.0,
            "noise_figure_db":5.0,"amc_model":"shannon","channel_model":"3gpp",
            "scenario":"RMa","condition_model":"static_los",
            "tx_array_gain_dbi":12.0,"rx_array_gain_dbi":12.0},
 "limits":{"max_layouts":1024,"max_probes":10000,
           "max_request_line_bytes":16777216,"max_child_response_bytes":16777216,
           "child_deadline_s":60.0,"terminate_grace_s":1.0,
           "max_response_bytes":67108864},
 "time_s":0.0}
```

| Field | Meaning |
|-------|---------|
| `seed` | The planning seed (the single resolved CLI/INI seed), passed to `RngSeedManager::SetSeed`. |
| `run_id` | Passed to `RngSeedManager::SetRun`. |
| `jammer_seed` | Seed `JammerModel` uses for `random` bursts. It equals the planning seed because `sim.cc` assigns the resolved run seed to `cfg.seed` before configuring the evaluator. It is reported separately so that a future simulator change stays visible to clients. |
| `start_positions` | From `ControlledStartPosition`: the first waypoint for waypoint mobility, otherwise `position`. |
| `channel` | The resolved channel defaults. Per-node gain overrides still apply inside the evaluation. |
| `limits` | The resolved worker limits (section 3). Clients derive serial batch budgets from them rather than copying worker deadlines. |

### 2.2 Requests

```json
{"type":"evaluate","request_id":7,"layouts":[[[x,y,z],...N],...],
 "probes":{"height_m":1.5,"rx_gain_dbi":12.0,"sinr_db":-6.7,"points":[[x,y],...]}}
{"type":"shutdown"}
```

- Each layout holds one `[x, y, z]` per node, in roster order.
- `probes` is optional; when present, all four fields are required.

### 2.3 Response

```json
{"type":"result","request_id":7,"layouts":[L,...],"wall_s":0.42}
```

Each `L` is either a result:

```json
{"links":[[i,j,sinr_db,capacity_mbps,is_los,connected],...],"coverage":[[k,...],...],"wall_s":0.01,"diagnostics":[]}
```

or `{"error":"..."}`.

| Field | Meaning |
|-------|---------|
| `links` | N(N-1)/2 rows in `EvaluateAll` order (i < j, row-major). SINR and capacity are the `LinkResult` values unchanged. |
| `connected` | `sinr_db >= sinr_threshold_db`. |
| `coverage` | `coverage[i]` lists the probe indices node i covers (`sinr_db >= probes.sinr_db`); `null` without probes. |
| `diagnostics` | String array of model-height warnings (section 4). |

### 2.4 Compatibility

The v1 contract is unchanged for existing clients: required fields and
evaluation order are the same. The budget fields in `limits` and the
`diagnostics` array are additive and advisory.

## 3\. Limits and errors

### 3.1 Limits

Configurable limits are set in the `[channel_query]` section of `run.ini`
(`src/config/query-config.cc`). Unknown keys and trailing numeric text are
errors. The resolved values appear in the init `limits`.

| Limit | `[channel_query]` key | Default | Valid range |
|-------|-----------------------|---------|-------------|
| Child deadline | `child_deadline_s` | 60 s | Finite, in (0,86400]. |
| Terminate grace | `terminate_grace_s` | 1 s | Finite, in (0,60]. |
| Child response | `max_child_response_bytes` | 16777216 (16 MiB) | Integer in [1024,16777216]. |
| Aggregate response | `max_response_bytes` | 67108864 (64 MiB) | Integer ≤ 268435456 (256 MiB); must hold one maximum child plus framing (at least child limit + 69632 bytes). |
| Request line | fixed | 16 MiB | Reading stops buffering at the limit and discards the rest of the line. |
| Layouts per request | fixed | 1024 | |
| Probe points | fixed | 10000 | |

The alarm backstop for a child is ceil(deadline + grace + 5) seconds. The
matching client configuration example is in the
[planner guide](../../scripts/baselines/planners/README.md).

### 3.2 Errors

| Level | Causes | Response |
|-------|--------|----------|
| Request | Malformed JSON, non-object, bad `request_id`, unknown `type`, wrong shapes, limits exceeded, non-finite numbers, oversized line. | `{"type":"error","request_id":<int\|null>,"message":"..."}`; the worker keeps serving. |
| Response overflow | The aggregate response exceeds `max_response_bytes`. | A request error asking for smaller batches; the worker keeps serving. |
| Layout | `ApplyLayout` errors (changed z, outside random-walk bounds); a non-finite SINR or capacity (never serialized as a number); a child that times out, exceeds the response limit, exits non-zero or is killed by a signal; unparsable child output. | `{"error":"..."}` in that layout's slot. |

## 4\. Height diagnostics

Each successful layout result carries a `diagnostics` string array with
warnings about the resolved propagation model's height assumptions. The same
warnings are logged on stderr once per request, before model evaluation, and
are kept in the final planning diagnostics. No coordinate is silently changed.

| Model | Lower endpoint | Higher endpoint |
|-------|----------------|-----------------|
| 3GPP RMa | 1..10 m | 10..150 m |
| 3GPP UMa | 1.5..22.5 m | 25 m |
| 3GPP UMi | [1.5,10) m | 10 m |

- A zero-height probe is outside the RMa assumptions. Choose probe and node
  heights together for the resolved model.
- NYU and indoor height validity is not checked, so the absence of a warning
  does not mean the heights are physically valid.
- Free-space floors and propagation behavior belong to the evaluator.

## 5\. Isolation and determinism

The worker process creates no ns-3 object or random variable and stays
single-threaded. Each layout is scored by a `fork()`ed child that:

1. Copies the config and applies the layout (`ApplyLayout`).
2. Sets `cfg.seed` to the planning seed and calls
   `RngSeedManager::SetSeed(seed)` / `SetRun(run_id)`.
3. Builds the topology (`TopologyBuilder`, with probes when requested).
4. Configures `LinkEvaluator` like `sim.cc`.
5. Runs `EvaluateAll(mobs, 0.0)`, then the probe links node-major (node
   0..N-1, probe 0..G-1).
6. Writes one JSON object (including height diagnostics) to its pipe and
   `_exit`s.

The event loop never runs before scoring, and jammer power is taken at
`t = 0`.

**Clean state.** Every child starts from the same global state as a fresh
simulator process: automatic RNG stream counter 0, empty node/building
registries, empty condition caches. ns-3 has no API to reset the stream
counter, so forking from a clean parent provides this; no per-variable
`AssignStreams` is needed. Probes are created without random variables (see
`src/setup/`), so mesh draws do not depend on whether probes were requested.

**Parity with an ordinary run:**

1. **Mechanics:** every candidate goes through `LinkEvaluator::Evaluate` with
   the run's resolved config.
2. **t = 0 realization:** the result matches the first seed of an ordinary run
   on the same effective inputs, seed and mode flag, because construction and
   evaluation order match and both start from counter 0. It does not match the
   second or later seed of a multi-seed run (stream-counter drift).
   `scripts/baselines/tests/test_real_binary.py` checks this parity against
   the real binary.

**Determinism is per layout.** The same scenario files, flags, seed, run ID,
layout and probe grid always give the same result, independent of request
order or batch composition. Draws for a given pair are not stable across
layouts: condition-dependent branches (shadowing, O2I, foliage) can change how
many draws earlier pairs consume, so two layouts that share a pair can see
different draws for it. Evaluating a subset of pairs would change the draw
indices, so every layout is a full `EvaluateAll` plus all probe links.

## 6\. Process cleanup

- The parent flushes its streams before each `fork`. The child redirects its
  stdin to `/dev/null` and stdout to stderr, so it can only answer through its
  pipe.
- The parent closes the pipe's write end and drains the read end with `poll`
  while the child runs, so large responses cannot deadlock. Then it `waitpid`s.
- On deadline, oversize or read failure, the parent sends `SIGTERM`, waits the
  resolved grace (default 1 s), sends `SIGKILL` and reaps. Every child is
  reaped; no zombie remains.
- `SIGTERM` / `SIGINT` / `SIGHUP` to the parent kill the active child before
  the parent exits. Clients should still run the worker in its own process
  group and clean up the whole group on cancellation.

## 7\. Module layout and tests

| File | Role |
|------|------|
| @ref channel-query.h "channel-query.h" | `RunChannelQuery(cfg, args, in, out)`. |
| `channel-query.cc` | Bounded serving loop and orchestration. |
| `query-protocol.h/cc` | NDJSON framing, request envelope/layout validation, init and error serialization. |
| `layout-evaluation.h/cc` | Layout application and simulator evaluation in the child. |
| `child-process.h/cc` | Fork, pipe draining, deadlines, termination and reaping; the callback runs only after fork. |
| `../eval/probe-diagnostics.h/cc` | Pure diagnostics for resolved propagation-model height assumptions. |
| `../config/query-config.h/cc` | Strict worker setting parsing and validation. |
| `CLAUDE.md` | Scope and invariants for contributors. |

| Tests | Covers |
|-------|--------|
| `make -C tests/unit/query test` | Protocol, process and diagnostic logic, with a stub scorer for the serving loop. |
| `scripts/baselines/tests/test_real_binary.py` | Real-binary parity and repeatability against direct runs. Skipped unless `MESH_SIM_BIN` points at a built binary. |
