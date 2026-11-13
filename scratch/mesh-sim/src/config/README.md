@page src_config src/config

@brief Loads `run.ini` and its JSON files into a `SimConfig` and checks it for errors.

This directory needs no ns-3. Five pieces turn the scenario files into a
checked `SimConfig`, and `sim.cc` calls them at startup:

- the **loader** reads `run.ini` and its JSON files;
- the **validator** reports every problem it finds;
- the **RL resolver** turns the `[rl]` settings into controlled-node slots and
  tick counts;
- the **layout override** moves node starts to a candidate layout for
  `--channel-query`;
- the **query config** parses and checks the `[channel_query]` worker budgets.

You only edit this directory to add or change a `run.ini` key or a validation
rule. For every supported `run.ini` key, its default and what it controls, see
the [run.ini settings reference](@ref src_config_run_ini_reference). The
[RL bridge](@ref src_rl) explains action and reward behavior; the
[jammer model](@ref src_jammer) explains `jammers.json`.

## 1\. Module layout

| File | Role |
|------|------|
| @ref config-loader.h "config-loader.h" | `ConfigLoader::Load()`; the header lists every `run.ini` section, key, default and JSON field. |
| @ref config-loader.cc "config-loader.cc" | INI and JSON parsing, output-directory defaulting, positions override. |
| @ref config-validator.h "config-validator.h" | `ValidationResult` and `ValidateConfig()`; the header lists all rules. |
| @ref config-validator.cc "config-validator.cc" | The checks; every rule runs even after an earlier failure. |
| @ref rl-control.h "rl-control.h" | `ResolveRlControl()`, `ApplyRlControl()`, `ComputeTickCount()`, `ControlledStartPosition()`. |
| @ref rl-control.cc "rl-control.cc" | Selector, slot-count, cadence and start-position resolution. |
| @ref layout-override.h "layout-override.h" / `.cc` | `ApplyLayout()`: moves node start x/y to a candidate layout (validated as a whole first; z, jammers and mobility kinds unchanged). |
| `query-config.h` / `.cc` | Strict `[channel_query]` parsing and budget validation; defaults come from `domain/query-config.h`. See the [query guide](@ref src_query). |
| `run-ini-reference.md` | The [run.ini settings reference](@ref src_config_run_ini_reference). |
| `CLAUDE.md` | Scope and change notes for AI assistants. |

## 2\. Run the unit tests

There is no executable here. From `scratch/mesh-sim/`:

```bash
make -C tests/unit/config test
```

The suite compiles the five `.cc` files here plus `src/util/` with a plain
C++17 compiler; nothing else needs installing. Do not use the top-level
`make test` on Linux (its lint step needs macOS `xcrun`).

## 3\. Input files

Paths inside `run.ini` are resolved against the `run.ini` directory.

| Input | Read by | Notes |
|-------|---------|-------|
| `run.ini` | `ConfigLoader::Load` | Sections `[scenario]`, `[output]`, `[channel]`, `[nyu_channel]`, `[traffic]`, `[routing]`, `[rl]`, `[baseline]`, `[mission]`; `[channel_query]` is owned by `query-config`. |
| nodes file (`[scenario] nodes_file`, default `nodes.json`) | `ConfigLoader::Load` | Required. |
| `[scenario] jammers_file` | `ConfigLoader::Load` | Optional. |
| `[scenario] buildings_file` | `ConfigLoader::Load` | Optional. |
| positions override JSON | `ConfigLoader::Load` | Optional second argument; node id to `[x, y, z]`. |

## 4\. Output

| Step | Where |
|------|-------|
| `ConfigLoader::Load` | Returns a `SimConfig`. Throws `std::runtime_error` for an unopenable file or content it cannot represent (an unknown `channel_model`, non-numeric building fields, a malformed `traffic.pairs`, or no mesh-sim root for the default output folder). Creates no files. |
| `ValidateConfig` | Returns a `ValidationResult`; `errors` holds one string per problem. |
| `ResolveRlControl` | Returns an `RlControlResolution`; `ApplyRlControl` copies it into `cfg.rl`. |
| `ApplyLayout` | Returns one string per problem; on an empty result `cfg.nodes` start positions were rewritten. |

## 5\. Conventions

- Validation rules only append to `errors`; they never throw or stop early.
- Loaders fill `SimConfig` fields directly and do not range-check.
- Comments use Doxygen `/** */` blocks; full docs live in the headers.

## 6\. Dependencies

- C++17, `third_party/json.hpp` (nlohmann/json).
- `src/domain/` (config and spec types) and `src/util/` (`ini-parser.h`,
  `string-utils.h`).
