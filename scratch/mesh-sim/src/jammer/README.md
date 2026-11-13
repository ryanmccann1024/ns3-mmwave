@page src_jammer src/jammer

@brief Adds interference from jammer emitters to per-link SINR in the sub-6 band.

This module adds jammer power to each link's SINR. Without jammers, SINR is
signal power over the thermal noise floor. With jammers, each active jammer's
received power is added to the noise in the SINR
(signal-to-interference-plus-noise ratio) denominator:

`SINR = 10·log10(signalWatt / (noiseWatt + jamWatt))`

The model is active only when `band == sub-6` and `jammers.json` defines at
least one enabled jammer. Jammers are looked up through `SimConfig::jammers`.

## 1\. Usage

The model has no executable; it runs inside the simulator. To add jammers to a
scenario:

1. Write a `jammers.json` beside `run.ini`, by hand or with `make_jammers.py`
   (section 5).
2. Point `run.ini` at it: `jammers_file = jammers.json` under `[scenario]`.
3. Set the band to sub-6: `--band=sub-6` on the command line, or
   `[channel] band = sub-6` in `run.ini`.

Example scenario with a jammer: `inputs/baselines/p0-jammer-smoke/`. Its
`jammers.json` holds one omnidirectional constant jammer:

```json
[
  {
    "id": "jammer-0",
    "enabled": true,
    "type": "constant",
    "target_freq": [2400.0],
    "tx_power_dbm": 30.0,
    "tx_array_gain_dbi": 12.0,
    "duty_cycle": 1.0,
    "max_range_m": 0.0,
    "beamwidth_deg": 360.0,
    "azimuth_deg": 0.0,
    "zenith_deg": 90.0,
    "position": {"x": 50.0, "y": 0.0, "z": 10.0}
  }
]
```

## 2\. jammers.json fields

The file is a JSON array with one object per jammer. Every field is optional;
the defaults are those `ConfigLoader` applies when a key is absent.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `id` | string | empty | Label (logs, validation, random-burst seed). |
| `enabled` | bool | **`false`** | `false` drops the jammer in `JammerModel::Configure`. |
| `type` | string | `constant` | `constant` or `random`. |
| `target_freq` | number[] | empty (all) | Target band in MHz. 1 value = spot ±2.5 MHz; 2 or more values = the band from their minimum to maximum. |
| `tx_power_dbm` | number | 25 | Transmit power (dBm). |
| `tx_array_gain_dbi` | number | 12 | Antenna gain (dBi), added to EIRP. |
| `duty_cycle` | number | 1 | 0 to 1; meaning depends on `type` (section 3). |
| `max_range_m` | number | 0 | Range cutoff (m); 0 disables the cutoff. |
| `beamwidth_deg` | number | 360 | Full cone angle (deg), in (0, 360]; 360 is omni. |
| `azimuth_deg` | number | 0 | Horizontal pointing, degrees from North (0=N, 90=E). |
| `zenith_deg` | number | 0 | Vertical pointing (0=up, 90=horizontal, 180=down). |
| `position` | {x,y,z} | | Location (ENU meters, same frame as nodes). |
| `velocity`, `waypoints` | object / array | | Optional jammer motion, same shapes as node mobility. Waypoints take precedence, then a non-zero velocity; otherwise the jammer is fixed. |
| `random_walk` | object | | Parsed, and its bounds are validated for `type = random`, but jammers never move by random walk. |
| `intervals` | {start,end}[] | empty (always on) | Active windows in sim seconds from scenario start. |

`ConfigValidator` checks `type`, `duty_cycle`, `beamwidth_deg` and `intervals`.

@warning The default `zenith_deg = 0` points a directional beam straight
**up**, so ground receivers fall outside a narrow upward cone. A ground emitter
normally uses `zenith_deg = 90`; `make_jammers.py` defaults to 90. An omni beam
ignores the pointing angles.

- **Hard cone:** a 60-degree beam accepts receivers within 30 degrees of the
  pointing vector. There is no sidelobe roll-off.
- **`max_range_m = 0`** disables only the cutoff; path loss still reduces power.

## 3\. duty_cycle

| `type` | Effect of `duty_cycle` | At 0.5 |
|--------|------------------------|--------|
| `random` | At each whole second, a seed-dependent draw decides whether the jammer is on **at full power**. | On about half the seconds. |
| `constant` | Always on; its power is multiplied by `duty_cycle`. | Adds half the watts (about 3 dB less). |

At 0 neither type contributes; at 1 both contribute full power.

## 4\. How jammer power is computed

Each tick, for each receiver, the model sums the received power of every
jammer that passes all five gates, in this order:

-# **Time**: sim time is inside one of the jammer's `intervals` (half-open; empty means always on).
-# **Random burst**: for `type=random`, a seed-dependent on/off draw per whole second (probability `duty_cycle`). `type=constant` is always on.
-# **Frequency**: the link carrier is inside `target_freq` (empty means no filtering; also skipped if the carrier is unset).
-# **Range**: the receiver is within `max_range_m` (0 means unlimited).
-# **Beam**: the receiver is inside the 3-D cone from `azimuth_deg`, `zenith_deg`, `beamwidth_deg` (omni when `beamwidth_deg >= 360`).

A passing jammer contributes `CalcRxPower(tx_power_dbm + tx_array_gain_dbi)`
through the same propagation model as mesh links. Under 1 m it contributes its
EIRP (effective isotropic radiated power) directly. No receive-side gain is
applied.

`LinkEvaluator` calls `JammerModel::InterfPowerAtReceiver` at both ends of a
link and uses the larger value in the SINR.

## 5\. Generating jammers.json from field data

`make_jammers.py` converts an EW (electronic warfare) trials CSV into a
`jammers.json`. Run from `scratch/mesh-sim/`:

```bash
python3 -m scripts.validation.make_jammers \
    --trials <ew_trials.csv> --trace <gps_all_nodes_trace.csv> \
    -o <scenario_dir>/jammers.json --run-ini <scenario_dir>/run.ini
```

| Flag | Default | Description |
|------|---------|-------------|
| `--trials <csv>` | required | EW trials CSV. |
| `--trace <csv>` | required | The scenario's `gps_all_nodes_trace.csv` (epoch reference and ENU fit). |
| `-o`, `--output <path>` | required | `jammers.json` to write. |
| `--trial <name>` | all trials overlapping the trace window | Single trial name. |
| `--beamwidth <deg>` | 60 | `beamwidth_deg` for directional jammers. |
| `--gain <dBi>` | 12 | `tx_array_gain_dbi` when the CSV cell is blank. |
| `--z <m>` | 2 | Jammer height. |
| `--zenith <deg>` | 90 | `zenith_deg` (0=up, 90=horizontal, 180=down). |
| `--run-ini <path>` | none | Adds `jammers_file = <name>` under `[scenario]`. |

CSV-to-field mapping:

| CSV column | Jammer field | Conversion |
|------------|--------------|------------|
| `start` / `end` (epoch) | `intervals` | Epoch minus scenario-start epoch, clipped to `[0,duration]`. |
| `ew_strength (W)` | `tx_power_dbm` | `10*log10(W)+30` |
| `ew_approx_lat` / `lon` | `position.x/y` | ENU, fit from the trace's paired lat/lon and east/north. |
| `ew_approx_heading (deg from N)` | `azimuth_deg` | Direct. |
| `ew_band_range` | `target_freq` | `"2210-2215"` becomes `[2210,2215]`. |
| `ew_type` | `beamwidth_deg` | `directional` gives `--beamwidth` (default 60); otherwise 360. |
| `ew_type = none` | none | No jammer (baseline trial). |

## 6\. Limitations

- **Beamwidth is an assumption.** The CSV logs heading but not beamwidth; widen
  `--beamwidth` (up to 360) if nodes are jammed outside a narrow cone.
- **Hard-edged cone.** Full power just inside the beam, none just outside.
- **One power and heading per spec.** A sweep is modeled as several specs (one
  per trial); `make_jammers.py` does this when `--trial` is omitted.
- **Negative SINR.** Jammer power may drive SINR below zero; below −6.7 dB a
  link has zero capacity. There is no artificial 0 dB floor.

## 7\. Module layout

| File | Role |
|------|------|
| @c src/jammer/jammer-spec.h | @ref mesh_sim::JammerSpec and `Interval`: one jammer's parameters (plain data, loaded from `jammers.json`). |
| @c src/jammer/jammer-model.h / .cc | @ref mesh_sim::JammerModel : total received jammer power (W) at a receiver, applying the gates in section 4. |
| @c src/eval/link-evaluator.cc | Calls `JammerModel::InterfPowerAtReceiver` at both link ends and folds the larger into SINR. |
| @c src/config/config-loader.cc | Reads `jammers.json` into `cfg.jammers` (`parseJammerSpec`). |
| @c src/config/config-validator.cc | Validates `type`, `duty_cycle`, `beamwidth_deg`, and `intervals`. |
| @c src/setup/topology-builder.cc | Builds one ns-3 mobility model per jammer, in `cfg.jammers` order. |
| @c scripts/validation/make_jammers.py | Host-side generator: EW trials CSV to `jammers.json`. |
| @c tests/unit/eval-jammer/ | Unit tests: `make -C tests/unit/eval-jammer test` compiles `jammer-model.cc` against ns-3 stubs. |

## 8\. Dependencies

| Dependency | Reason |
|------------|--------|
| `ns3/propagation-loss-model.h`, `ns3/mobility-model.h` | Path loss and jammer/receiver positions. |
| `ns3/log.h` | `NS_LOG` debug output in `jammer-model.cc`. |
| `src/domain/node-spec.h` | `Position`, `Velocity`, `Waypoint`, `RandomWalkParams` used by `JammerSpec`. |
| Python 3 (repo `.venv`) | `scripts/validation/make_jammers.py` only. |
