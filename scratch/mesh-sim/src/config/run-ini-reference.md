@page src_config_run_ini_reference src/config/run-ini-reference

@brief Every run.ini key the simulator reads, with defaults and units.

This page lists every `run.ini` key the simulator reads, plus the `[rl]` and
`[baseline]` keys that Python reads.

- Omitted keys use the defaults below.
- The simulator silently ignores unknown keys, except in `[channel_query]`,
  where they are errors. Python rejects unknown `[baseline]` keys.
- Input-file paths are relative to `run.ini`.

Related pages: the [RL bridge](../rl/README.md) for action and reward behavior,
the [jammer model](../jammer/README.md) for `jammers.json`, and the
[CLI guide](../cli/README.md) for command-line overrides.

## 1\. [scenario] and [output]

| Key | Default | Controls |
| --- | --- | --- |
| `name` | `unnamed` | Scenario label. |
| `seed` | `42` | Simulation random seed; CLI `--seed`/`--seeds` can override it. |
| `run_id` | `1` | Run identifier; CLI `--run-id` can override it. |
| `duration_s` | `10` | Simulated duration in seconds. |
| `warmup_s` | `0` | Initial seconds excluded from output metrics. RL rewards still count them. |
| `tick_s` | `0.1` | Simulation time advanced per tick, in seconds. |
| `nodes_file` | `nodes.json` | Mesh-node input file. |
| `buildings_file` | blank | Optional building input file. |
| `jammers_file` | blank | Optional jammer input file. Jamming requires `band = sub-6`. |
| `[output] dir` | timestamped `outputs/` path | Output root; a relative value resolves from `run.ini`. CLI `--output-dir` overrides it. |
| `[output] viz_tick_ms` | `100` | Milliseconds between visualization CSV snapshots. |

## 2\. [channel]

| Key | Default | Controls |
| --- | --- | --- |
| `band` | `mmwave` | `mmwave` or `sub-6`; CLI `--band` overrides it. |
| `frequency_ghz` | `28` | Link carrier frequency in GHz. |
| `tx_power_dbm` | `30` | Mesh-node transmitter power in dBm. |
| `scenario` | `UMi` | Propagation setting: `UMi`, `UMa`, `RMa`, `InH`, or `InF`. |
| `channel_model` | `3gpp` | Propagation model: `3gpp` or `nyu`. |
| `condition_model` | `auto` | `auto` or `static_los` channel-condition selection. |
| `blockage_enabled` | `true` | Parsed and stored; the link evaluator does not read it. |
| `beamforming_model` | `svd` | Parsed and stored; the link evaluator does not read it. |
| `amc_model` | `shannon` | SINR-to-capacity method: `shannon`, `table`, or `silvus`. |
| `bandwidth_mhz` | `400` | Link bandwidth used for noise floor and capacity, in MHz. |
| `noise_figure_db` | `5` | Receiver noise figure in dB. |
| `tx_array_gain_dbi` | `12` | Default mesh-node transmit antenna gain in dBi. |
| `rx_array_gain_dbi` | `12` | Default mesh-node receive antenna gain in dBi. |

**Band:**

- `band` chooses a simulator mode. It is never inferred from `frequency_ghz`.
- Resolution order: `--band` on the command line, then `[channel] band`, then
  the default `mmwave`. `run.log` records the result as `band` and
  `band_source` (`cli`, `run.ini`, or `default`).
- Jammers contribute interference only in `sub-6` mode. The jammer's
  `target_freq` then filters the carrier frequency.

## 3\. [nyu_channel]

These keys apply only when `[channel] channel_model = nyu`.
`rf_bandwidth_mhz` is parsed but not applied.

| Key | Default | Controls |
| --- | --- | --- |
| `rf_bandwidth_mhz` | `800` | Stored NYU RF bandwidth; not applied. |
| `shadowing_enabled` | `true` | NYU shadow fading. |
| `pressure_mbar` | `1013.25` | Atmospheric pressure. |
| `humidity_pct` | `50` | Relative humidity. |
| `temperature_c` | `20` | Air temperature. |
| `rain_rate_mm_hr` | `0` | Rain rate. |
| `atmospheric_loss_enabled` | `false` | Molecular absorption loss. |
| `foliage_loss_enabled` | `false` | Foliage excess loss. |
| `foliage_loss_db_m` | `0.4` | Foliage loss per meter. |
| `o2i_loss_type` | `Low Loss` | Outdoor-to-indoor loss class (`Low Loss` or `High Loss`). |

## 4\. [traffic] and [routing]

Traffic is flow-level demand; there are no packets. The
[traffic](@ref src_traffic) and [routing](@ref src_routing) modules own the
code.

| Key | Default | Controls |
| --- | --- | --- |
| `[traffic] model` | `constant` | `constant` (flows stay active), `poisson` (flows start randomly), or `on_off` (flows alternate sending and silence). |
| `demand_mbps` | `10` | Requested rate per active flow. |
| `arrival_rate_hz` | `1` | New flows per second in `poisson` mode. |
| `on_time_s`, `off_time_s` | `1`, `1` | Mean on/off phase lengths in `on_off` mode; finite, nonnegative, and not both zero. |
| `holding_time_s` | `0` | Flow lifetime in seconds; `0` means no expiry. |
| `flow_topology` | `all_pairs` | `all_pairs` (every pair), `random_pairs` (sampled pairs), `gateway` (each other node to one gateway), or `explicit_pairs` (the listed pairs). |
| `random_pair_count` | `3` | Number of flows with `random_pairs` topology. |
| `gateway_node_id` | blank | Gateway node ID, required with `gateway` topology. |
| `pairs` | `[]` | JSON array of explicit source-to-destination traffic pairs with per-pair demand; only valid with `flow_topology=explicit_pairs`. See [Explicit traffic pairs](@ref src_config_traffic_pairs). |
| `[routing] algorithm` | `shortest_path` | `shortest_path` (inverse-capacity shortest path), `max_throughput` (widest-capacity path), or `min_hop` (fewest hops). |
| `max_hops` | `5` | Maximum hops per route; `0` means unlimited. |

### Explicit traffic pairs {#src_config_traffic_pairs}

`[traffic] flow_topology=explicit_pairs` requires `model=constant` and a
nonempty `pairs` JSON array, for example:

```ini
pairs = [{"src":"ground-1","dst":"vehicle-1","demand_mbps":6}]
```

- Each pair's `src` and `dst` must name existing nodes and must differ.
- Each pair's `demand_mbps` must be finite and positive and sets that flow's
  rate. The global `demand_mbps` scalar is still validated.
- Duplicate directed pairs are rejected. Reverse-direction pairs are distinct
  flows.
- A nonempty `pairs` value requires `flow_topology=explicit_pairs`.
- For equal per-source load q across N nodes (N > 1), include every ordered
  pair among those nodes with `demand_mbps` set to q/(N-1).

## 5\. [rl]

With `enabled = false`, the other C++ RL keys do not control the run. CLI
`--rl-mode` turns RL on even if the file says `false`. The jammer-only smoke
scenario uses `enabled = false`, so its `[rl]` block is inert in the regression
run.

### Simulator keys

| Key | Default | Controls |
| --- | --- | --- |
| `enabled` | `false` | Enable the simulator's action/observation bridge. |
| `controlled_node_id` | blank | Legacy single-node selector; blank selects the last mesh node. |
| `controlled_nodes` | absent | Centralized selector: `all` or comma-separated node IDs. Its presence selects centralized mode; cannot coexist with `controlled_node_id`. |
| `max_controlled_nodes` | `0` | Centralized action positions; `0` sizes to the selected nodes. Maximum `64`. |
| `action_type` | `discrete` | Legacy: `discrete` or `continuous`; centralized requires `discrete`. |
| `action_profile` | `move_2d` | Centralized movement profile; only `move_2d` is implemented. |
| `decision_interval_s` | `0` | Seconds between centralized decisions; `0` means `tick_s`, otherwise an integer multiple of it. |
| `reward_type` | `throughput` | C++ reward: `throughput` or `all_links_los`. `mean_sinr` is a deprecated alias for `all_links_los`: it still runs, prints a warning on stderr, and `run.log` records it as `rl.reward_alias`. |
| `step_size_m` | `50` | Nominal discrete move per simulation tick, capped by node speed in centralized mode. |
| `arrival_threshold_m` | `1` | Legacy continuous-target arrival distance, in meters. |
| `x_min`, `x_max` | `-1000`, `2000` | Allowed east/west movement bounds, in meters. Each min must be below its max (same for y and z). |
| `y_min`, `y_max` | `-1000`, `1000` | Allowed north/south movement bounds, in meters. |
| `z_min`, `z_max` | `0`, `100` | Allowed height bounds, in meters; centralized `move_2d` does not change height. |

- In centralized mode, `all_links_los` is true only when every controlled node
  has at least one peer link and all of them are line-of-sight.
- `action_set` and `dimensions` are not keys; the loader ignores them.

### Python keys

These five keys are read by Python's centralized RL environment; the C++
simulator does not read them. Each also has a training CLI override; see
[Selecting observations, rewards, and telemetry](@ref src_rl_policy_inputs_selection).

| Key | Default | Controls |
| --- | --- | --- |
| `observation_preset` | `raw_links_v1` | Observation representation given to the policy. |
| `reward_components` | absent | Comma-separated Python reward components; absent uses C++ `reward_type`. |
| `reward_weights` | `1` per component | Comma-separated weight for each selected component. |
| `telemetry` | `none` | `none` or `steps` decision-level records. |
| `telemetry_every` | `1` | Record every Nth decision when `telemetry = steps`. |

### Safety and live coverage

| Key | Default | Controls |
| --- | --- | --- |
| `unsafe_separation_m` | `1` | Finite positive distance, in meters. |
| `avoid_buildings` | `false` | When true, centralized swept movement may not enter a building. Nodes must not start inside a building's clearance. |
| `building_clearance_m` | `0` | Clearance around walls and roofs, in meters; finite and nonnegative. |
| `mask_building_moves` | `true` | `false` permits proposals that the movement physics then rejects. |
| `avoid_node_collisions` | `false` | Rejects joint paths closer than `unsafe_separation_m`. Requires centralized control. |
| `coverage_enabled` | `false` | Live coverage measurement. Requires centralized control. |

**`avoid_node_collisions = true`:** all initial mesh-node pairs must meet
`unsafe_separation_m`. Unsafe joint horizontal paths are held and revalidated,
using 3D distance and clipped bounds. Scenarios that do not set the key keep
their configured behavior.

**`coverage_enabled = true`** reads its coverage settings from `[baseline]`.
They apply even when `[baseline] algorithm=none`:

| `[baseline]` key | RL default |
| --- | --- |
| `coverage_grid_cells` | `100` (integer 1–10000) |
| `grid_min_resolution_m` | `5` m |
| `coverage_probe_height_m` | `1.5` m |
| `coverage_probe_rx_gain_dbi` | resolved channel RX gain |
| `coverage_sinr_db` | `-6.7` dB |

The actual clipped grid is capped at 10000 probes. Example:

```ini
[rl]
controlled_nodes = all
unsafe_separation_m = 1.0
avoid_buildings = true
coverage_enabled = true
reward_components = delivery_ratio, coverage_fraction, span_travel_fraction
reward_weights = 1.0, 0.5, -2.5
```

### Deployment gate (`control_start_s`)

`[rl] control_start_s` defaults to `0`, which leaves behavior unchanged. A
positive value:

- must be finite and below `duration_s`
  (`rl.control_start_s must be finite in [0,duration_s)`);
- must align to a decision boundary;
- requires enabled centralized control.

Native masks and velocity application hold controlled peers until that time.
The gate is experimental. It constrains movement only; the actor does not
receive it as an input.

### Moving jammer (Python)

`[rl] jammer_motion_profile = sweep_v1` is read by the Python episode launcher;
the C++ loader does not read it.

- It resolves one jammer into archived waypoint inputs per episode on the
  600-second 400×400 m scenarios.
- The actual motion and its seed-dependent variant appear in `rl_episode.json`
  version 6.
- A raw simulator invocation uses the configured `jammers.json` directly. Use
  the RL launchers for varied routes.

## 6\. [baseline]

Selects a placement baseline.

- The C++ simulator reads only `algorithm` and never plans placements. A direct
  run with `geometric` or `optimization` exits with an error unless the CLI
  passes `--rl-mode`, in which case it prints a notice and uses the scenario
  layout. `[rl] enabled = true` alone does not bypass this guard.
- Python (`scripts/baselines/config.py`) owns every key below and rejects
  unknown keys and values. The binary ignores keys other than `algorithm`.
- `gateway_node_id` and `rf_config` are removed keys; Python rejects them with
  a message to delete the key.
- The active traffic gateway must stay outside placement selection and RL
  control.

| Key | Default | Controls |
| --- | --- | --- |
| `algorithm` | `none` | `none`, `geometric`, or `optimization`; an absent section or key means `none`, and the binary also treats a blank value as `none`. |
| `objective` | none | `coverage`, `balanced`, or `resilience`; required when active. |
| `application` | `initial_positions` | Only `initial_positions` is accepted. |
| `movable_nodes` | none | Distinct, non-empty comma-separated node IDs the planner may move; `all` is not accepted. Required when active. |
| `seed` | none | Planner seed (integer ≥ 0), required for `optimization`; independent of the simulation seed. |
| `max_iterations` | none | Optimizer iterations (integer > 0), required for `optimization`. |
| `waypoint_policy` | `reject` | `reject` or `translate` for selected waypoint nodes. |
| `planning_seed` | none | Required dedicated channel-planning seed in [1,2147483647]; `--planning-seed` overrides it. Independent of optimizer and evaluation seeds. |
| `mapping_file` | none | Optional version 2 rectangular geofence/platform mapping; absent requires all four RL x/y bounds explicitly and resolves platforms from `node_type`. |
| `aerial_fixed_cost_m2`, `ground_fixed_cost_m2` | `150000` | Per-node one-time relocation cost in square-meter-equivalent objective units; zero disables it. |
| `aerial_cost_m2_per_m`, `ground_cost_m2_per_m` | `500`, `100` | Cost per meter of initial x/y relocation; zero disables it. |
| `aerial_max_displacement_m`, `ground_max_displacement_m` | none | Optional positive initial relocation caps in meters. |
| `candidate_grid_cells`, `coverage_grid_cells` | `400`, `400` | Positive target grid cell counts. |
| `grid_min_resolution_m` | `5` | Positive minimum grid spacing in meters. |
| `coverage_sinr_db` | `-6.7` | Finite SINR threshold used to count probe coverage. |
| `coverage_probe_height_m`, `coverage_probe_rx_gain_dbi` | `1.5`, resolved node receive gain | Probe receiver height and optional gain; both must be non-negative. |

See the [baseline guide](../../scripts/baselines/README.md) for ownership and
seed rules and [Placement baselines](@ref mesh_sim_placement_start) for
running and reading a plan.

## 7\. [channel_query] and placement-engine settings

`[channel_query]` sets the `--channel-query` worker limits
(`query-config.cc`). Unknown keys are errors. The resolved values appear in the
`mesh_channel_query_v1` init handshake.

| Key | Default | Valid range |
| --- | --- | --- |
| `child_deadline_s` | `60` s | Finite, in (0,86400]. |
| `terminate_grace_s` | `1` s | Finite, in (0,60]. |
| `max_child_response_bytes` | `16777216` | Integer in [1024,16777216]. |
| `max_response_bytes` | `67108864` | Integer ≤ 268435456, and at least the child limit + 69632 bytes. |

Python engine settings use `[placement_objective]`, `[placement_optimizer]` and
`[channel_query_client]`; see the complete
[planner parameter example](../../scripts/baselines/planners/README.md#configuration-and-extension).
Both baseline CLIs and the placement evaluation policies pass these sections to
the channel-scored engine.

## 8\. [mission] {#src_config_mission_controls}

`kind` defaults to `none`. `coverage`, `investigation` and `recovery` require
centralized RL with `coverage_enabled = true`. See
`inputs/custom/10-16/README.md` for examples and outcome rules.

| Key | Default | Valid values |
| --- | --- | --- |
| `kind` | `none` | `none`, `coverage`, `investigation`, `recovery`. |
| `investigator_id` | blank | `investigation`: an existing, controlled peer with no scheduled dropout. |
| `goal_x`, `goal_y` | `345`, `300` | Finite coordinates. Investigation requires them inside the RL x/y bounds. |
| `arrival_radius_m` | `15` | Finite and positive. |
| `coverage_radius_m` | `50` | Finite and positive. |
| `dwell_s` | `30` | Finite and positive. |
| `goal_coverage_target` | `0.8` | (0,1]; [0,1] for `investigation`, where 0 disables the gate. |
| `recovery_delivery_target` | `0.9` | (0,1]. |
| `recovery_coverage_ratio` | `0.9` | [0,1]. |
| `recovery_worst_target` | `0.8` | (0,1]. |
| `team_investigation` | `false` | Requires `kind = investigation`. Requires the available team near the goal. |
| `team_radius_m` | `50` | Finite and positive. |
| `team_delivery_target` | `0.8` | (0,1]; [0,1] for `investigation`, where 0 disables the gate. |

**Node dropout.** `failure_at_s` in `nodes.json` schedules a node failure; the
default -1 disables it. A dropout requires:

- `kind = recovery`;
- a finite time strictly inside the episode, in (0,`duration_s`), aligned with
  a simulator tick;
- at least two surviving peers.

A `recovery` mission requires at least one dropout. Original demand is kept,
and survivor measurements are reported separately. Recovery can preserve only
critical survivor flows ([explicit traffic pairs](@ref src_config_traffic_pairs))
while failed-source demand stays visible in original-demand totals. The failed
node retains its roster index and is excluded from radio service, coverage,
and peer-collision checks. Set
`recovery_coverage_ratio = 0` when recovery concerns survivor traffic rather
than replacing the failed aerial coverage footprint.

**Investigation.** A positive `goal_coverage_target` or `team_delivery_target`
keeps its usual meaning. The scenario-check all-peer arrival metric is
separate from native mission success, which also requires connected peers.
Goal coverage uses outdoor probe centers inside the goal radius. A positive
target requires at least one such center. A zero target still permits
measurement when probes exist. An empty region reports zero.

**Buildings.** Each `buildings.json` entry needs six explicit numeric bounds,
nested under `bounds` or flat. Conflicting representations and missing bounds
are errors.
