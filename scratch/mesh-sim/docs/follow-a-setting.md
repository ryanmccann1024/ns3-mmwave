# Follow a setting: [traffic] demand_mbps {#mesh_sim_setting_trace}

[TOC]

One setting, every hop. \ref mesh_sim_change_one_setting "Change one setting" changes this value and compares two runs; this page explains what happens to it between the INI file and the output files. The surrounding stage order is in \ref mesh_sim_run_flow "How a run works".

```ini
[traffic]
demand_mbps = 10.0
```

`demand_mbps` is the offered traffic per flow in Mbit/s. `10.0` is also the loader's default when the key is absent, so a scenario that omits it behaves as if this excerpt were present.

## Hop by hop

| Hop | Where (contract) | What happens |
|---|---|---|
| Load | `ConfigLoader::Load` (\ref src_config "config"; key table in the \ref src_config_run_ini_reference "run.ini reference") | parsed into `cfg.mesh.traffic.demand_mbps`; default `10.0` |
| Validate | `ValidateConfig` (\ref src_config "config") | must be positive, otherwise the run is rejected with a `traffic.demand_mbps` error before anything is written |
| Record | `WriteRunLog` → `run.log` at the batch root (\ref src_io "io") | the loaded scalar is written as `traffic.demand_mbps = <value>`; explicit pairs also have `traffic.pair = src,dst,demand` lines |
| Create flows | `TrafficMatrix::MakeFlow` (\ref src_traffic "traffic") | copied into each `Flow::demand_mbps`; with `flow_topology = explicit_pairs` the per-pair `demand_mbps` from the pair list replaces it |
| Route | `MeshRouter::Route` (\ref src_routing "routing", which owns the scaling rule) | the tick's effective demand is `Flow::demand_mbps` for an active, ON-phase flow and `0` otherwise; on a routable path `delivered_mbps` starts equal to demand and is reduced only if a link is oversubscribed. An unroutable flow delivers `0` |
| Snapshot | `VizWriter::WriteFlows` → `flows.csv` (\ref src_io_output "Output", \ref src_io_timing "Sampling and warmup") | one row per flow at each saved snapshot time, with the effective `demand_mbps` and the derived `delivered_mbps` |
| Summarize | `MetricsWriter` → `summary.json` (\ref src_io_output "Output", \ref src_io_timing "Sampling and warmup") | each `per_flow` bucket groups observations by `<src-id>-><dst-id>` and averages `demand_mbps` and `delivered_mbps` over that pair's included `FlowResult` observations with `t >= warmup_s` |

## Three values, not one

- **Configured demand**: the scalar `traffic.demand_mbps` in `run.log`, recorded once per batch. With `explicit_pairs`, per-pair values in the `traffic.pair` lines supply the flows' demand instead; the scalar still has to pass validation.
- **Effective demand**: `demand_mbps` in `flows.csv` for each flow at a saved tick, averaged in `per_flow[...].demand_mbps` in `summary.json`. OFF-phase flows have zero demand; expired flows are removed before routing and have no later CSV rows. For constant traffic, a flow's demand equals its configured scalar or per-pair value while it exists.
- **Delivered rate**: `delivered_mbps` in the same two places. Derived by the router from the path and the link capacities; never read from the INI.

Summary averages use accumulated flow observations rather than sampled CSV rows. Multiple simultaneous Poisson flows with the same source/destination enter the same bucket as separate observations, so their rates are averaged, not summed into a pair total. A bucket does not add observations for times when that pair has no flow.

## Easy to get wrong

- **IDs vs indices.** `summary.json` keys use node IDs from `nodes.json` (for the tracked two-node baseline the key form is `node-a->node-b`); `flows.csv` `src` / `dst` use zero-based node indices.
- **Warmup.** Rows with `time_s < warmup_s` are in `flows.csv` but excluded from every `summary.json` average.
- **`--no-viz`.** Suppresses only the Snapshot hop. The archived inputs, `run.log` and `summary.json` are still written.

## Next

- \ref mesh_sim_change_one_setting "Change one setting": change this value and compare two runs.
- \ref mesh_sim_run_flow "How a run works": the stages around these hops.
- \ref src_routing "routing": how delivered rates are derived.
- \ref mesh_sim_add_capacity_model "Add a capacity model": extend `SinrToCapacity` with a local illustrative model.
