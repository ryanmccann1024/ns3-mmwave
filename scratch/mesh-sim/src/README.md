# src

The C++ simulator, split by concern. The entry point is `../sim.cc`, and all
code lives in namespace `mesh_sim`. Only `setup/` creates ns-3 objects;
`domain/` holds plain types that every other module depends on.

| Module | What it does |
| --- | --- |
| [domain](domain/README.md) | Plain-struct configuration and result types shared by every simulator layer. |
| [config](config/README.md) | Loads `run.ini` and its JSON files into a `SimConfig` and checks it for errors. |
| [cli](cli/README.md) | Command-line parsing and pre-simulation setup. |
| [setup](setup/README.md) | Creates the ns-3 nodes, mobility models, buildings and propagation models for a run. |
| [eval](eval/README.md) | Computes radio link quality for every node pair each tick. |
| [jammer](jammer/README.md) | Adds jammer interference to per-link SINR in the sub-6 band. |
| [traffic](traffic/README.md) | Flow-level traffic demand generation. |
| [routing](routing/README.md) | Flow-level routing over the mesh link graph, with congestion scaling and latency. |
| [io](io/README.md) | Writes the output files: per-tick CSVs, a per-seed JSON summary, a run log and progress. |
| [rl](rl/README.md) | The stdin/stdout JSON bridge to the Python Gymnasium environment. |
| [query](query/README.md) | `--channel-query`: scores candidate start layouts through the simulator's own channel. |
| [util](util/README.md) | String, path and INI helpers shared by config, cli and io. |

How a run moves through these modules is described in
[How a run works](../docs/how-a-run-works.md). Unit tests are under
[`../tests/`](../tests/README.md). The full documentation is the docs site; see
[Generating the docs](../docs/generating-the-docs.md).
