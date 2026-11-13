@page src_eval src/eval

@brief Computes radio link quality for every node pair each simulation tick.

Given the current node positions and ns-3 propagation models, this module
produces path loss, SINR (signal-to-interference-plus-noise ratio), capacity,
and MCS (modulation and coding scheme) index for each link. It stores the
results in a symmetric matrix for O(1) lookup by the routing, metrics, and RL
layers. In the sub-6 band it also adds jammer power (see @ref src_jammer).

## 1\. Module layout

| File | Role |
|------|------|
| `link-evaluator.h` / `.cc` | `LinkEvaluator`: `Configure`, `Evaluate` (one link), `EvaluateAll` (all pairs), `EvaluateProbe` (mesh node to query probe). Wraps ns-3 propagation and channel-condition models. |
| `sinr-capacity.h` | Header-only, no ns-3: MCS tables (3GPP-style and Silvus), `SinrToMcsIndex`, `SinrToSilvusMcsIndex`, `SinrToCapacity`. |
| `link-table.h` / `.cc` | `LinkTable`: symmetric N×N matrix with `Update`, `Get`, `MaxCapacity`, `ConnectedLinkCount`, `IsConnected`. |
| `coverage-grid.h` / `.cc` | Clipped receiver cells and the covered area of the largest connected mesh component (section 4). |
| `probe-diagnostics.h` / `.cc` | Advisory checks of 3GPP endpoint-height assumptions for query probes (section 4). |
| `CLAUDE.md` | Scope notes and invariants for contributors. |

## 2\. Run the unit tests

This module is a library used by `sim.cc`; it has no executable of its own.
Its standalone unit tests (no ns-3 needed) run from `scratch/mesh-sim/`:

```bash
make -C tests/unit/eval test
```

The Makefile (C++17) builds and runs two binaries. `eval-test` covers the
Shannon/table capacity, unknown-name rejection, CQI `SinrToMcsIndex`,
`link-table.cc` and `coverage-grid.cc`; it has no Silvus capacity/index checks.
`reconfigure-test` compiles the real `link-evaluator.cc`
and `jammer-model.cc` against local ns-3 stubs (a deterministic loss model and
a fixed LOS condition model) and checks one thing: that calling `Configure`
again without jammers clears the old jammer. Neither exercises a real
propagation model or the full simulator; checking those requires full-simulator
execution rather than this stub suite.

## 3\. Output

No files are written. Two in-memory structures are produced each tick.

| Step | Where |
|------|-------|
| `LinkEvaluator::EvaluateAll` returns `std::vector<LinkResult>`: one entry per unordered pair, N·(N−1)/2 total, in (i < j) order. | Passed to `LinkTable::Update` in `sim.cc`. |
| `LinkTable::Update` builds a symmetric N×N matrix; `Get(i, j)` equals `Get(j, i)`. | Read by `routing/`, `io/`, and `rl/`. |

`LinkResult` (defined in `src/domain/link-result.h`) fields:

| Field | Description |
|-------|-------------|
| `tx_id`, `rx_id` | Node indices for this link (`tx_id < rx_id` from `EvaluateAll`). |
| `distance_m` | 3-D Euclidean distance (m). |
| `is_los` | `true` if Line-of-Sight. |
| `path_loss_db` | Path loss (dB): model value, floored at free-space loss. |
| `rx_power_dbm` | Received power after TX power, both array gains, and path loss (dBm). |
| `sinr_db` | SINR (dB). Default `-999.0` only for a default-constructed result (for example the `LinkTable` diagonal). |
| `capacity_mbps` | Capacity from the AMC (adaptive modulation and coding) model (Mbps). |
| `mcs_index` | MCS index chosen by the AMC model. |
| `condition_from_buildings` | `true` when buildings are configured (set for every link in that case). |

## 4\. Conventions

### Physics
- **Noise floor.** `-174 + 10·log10(bandwidth_Hz) + noise_figure_dB` (dBm).
- **No inter-node interference.** SINR is signal vs. noise floor. Only jammer power is added, and only in sub-6.
- **Array gains.** `rx_power_dbm` adds the TX node's `tx_array_gain_dbi` and the RX node's `rx_array_gain_dbi`. A per-node override in `nodes.json` wins over the channel default.
- **Free-space floor.** Path loss is never below free-space path loss at `max(distance, 1 m)`. This removes SINR spikes at short range and at `d = 0`.
- **Jammer handling.** Uses the larger of the jammer power at the RX and TX ends. Negative SINR is preserved, allowing interference to drive capacity to zero below −6.7 dB.

### Capacity models ([channel] amc_model)
- `shannon`: `B·log2(1+SINR)`.
- `table`: CQI spectral efficiency times bandwidth (16 entries, indices 0–15).
- `silvus`: Silvus single-stream MCS 0–6, scaled from 20 MHz to the configured bandwidth.
- Any SINR below `SINR_MIN_DB` (−6.7 dB) gives 0 Mbps; `SinrToCapacity` returns this before it reads the model name.
- `amc_model` has no validator whitelist. An unknown name therefore passes `ValidateConfig` and throws `std::runtime_error` from `SinrToCapacity` only when a link is at or above the threshold, part-way through a run. `main` does not catch this exception around the evaluation loop. Archiving and the run-log attempt precede it, but `run.log` may have failed to open and the seed's outputs may be incomplete (@ref src_io_run_record "What a run records").
- MCS selection is separate from capacity: `link-evaluator.cc` uses `SinrToSilvusMcsIndex` only when the name is exactly `silvus`; every other name uses `SinrToMcsIndex` (the CQI path). Capacity is converted first, then the index is chosen.
- To extend the capacity selector, see @ref mesh_sim_add_capacity_model "Add a capacity model".

### Connectivity
- `LinkTable::IsConnected` and `ConnectedLinkCount` default to `sinr_db >= -6.7`, a literal that matches `SINR_MIN_DB`.
- `metrics-writer.cc` skips links with `sinr_db <= -900` as invalid (the `-999` sentinel).

### Probe links
- `EvaluateProbe` (used only by `src/query/`) runs the same private body as `Evaluate`; only the RX gain comes from the request instead of a node's gain, and `rx_id` is `LinkEvaluator::kProbeRxId`. Path-loss floors, jammer path (larger of probe-end and TX-end power) and the unclamped SINR calculation are identical; negative SINR is preserved.

### Coverage and probe diagnostics
- `coverage-grid.h/cc` builds clipped receiver cells and computes the covered
  area of the largest connected mesh component (ties by smallest roster index).
  `sim.cc` evaluates node-to-probe links at decision endpoints when RL coverage
  is enabled.
- Mission coverage excludes a cell if its center lies inside a building at the
  configured receiver height. Each retained cell contributes its clipped area
  once if any available peer in the core covers it. Investigation goal coverage
  uses the same calculation over centers within the goal radius.
- `probe-diagnostics.h/cc` checks resolved 3GPP RMa/UMa/UMi endpoint height
  assumptions without ns-3 objects. The [query guide](@ref src_query) describes
  its advisory output; it does not alter propagation or certify all models.

### Call order
- `LinkEvaluator::Configure` must run before `Evaluate`, `EvaluateProbe` or `EvaluateAll`. It throws `std::runtime_error` on a null model pointer.
- `EvaluateAll` evaluates only i < j; `LinkTable::Update` mirrors each result and throws `std::runtime_error` if the result count is not N·(N−1)/2.

## 5\. Dependencies

| Dependency | Used by | Reason |
|------------|---------|--------|
| `ns3/propagation-loss-model.h` | `link-evaluator` | `CalcRxPower` per link. |
| `ns3/channel-condition-model.h` | `link-evaluator` | LOS/NLOS per link. |
| `ns3/mobility-model.h` | `link-evaluator` | Distance and positions. |
| `ns3/log.h` | `.cc` files | `NS_LOG` debug output. |
| `src/domain/` (`link-result.h`, `sim-config.h`) | all | Shared POD types. |
| `src/jammer/jammer-model.h` | `link-evaluator` | Jammer interference. |
| g++ with C++17 | unit tests | `make -C tests/unit/eval test`. |
