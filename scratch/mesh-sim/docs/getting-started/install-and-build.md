# Install and build {#mesh_sim_install_build}

[TOC]

Build the simulator binary. Run every command from the ns3-mmwave repository
root, the folder that holds the `ns3` script.

## 1\. Prerequisites

| Tool | Minimum | Used for |
|---|---|---|
| Git | any | The checkout |
| Python 3 | any | Runs the `./ns3` wrapper. The simulator itself needs no Python packages. |
| CMake | 3.13 | Configuring the build |
| C++ compiler | C++20 support | Building ns-3 and Mesh-Sim |

The build is tested on Ubuntu 22.04 and macOS 14.

## 2\. Configure

```bash
./ns3 configure --build-profile=debug \
  --enable-modules=core,network,mobility,propagation,buildings \
  --disable-examples --disable-tests -- -DNS3_WARNINGS_AS_ERRORS=OFF
```

This enables only the five ns-3 modules Mesh-Sim needs and skips the ns-3
examples and tests, so the build stays small. It replaces any earlier
configuration in this checkout; to build the full ns-3 tree instead, see
\ref readme_build "Build" in the User guide.

**Checkpoint:** the summary at the end lists the five enabled modules.

## 3\. Build

```bash
./ns3 build scratch/mesh-sim/sim
```

**Checkpoint:** the build finishes without errors.

## 4\. Find the binary

```bash
ls build/scratch/mesh-sim/ns3*-sim-debug
```

**Checkpoint:** it prints `build/scratch/mesh-sim/ns3.42-sim-debug`.

The name is `ns<ns-3 version>-sim-<build profile>`. This is the `<BIN>` that
Python tools take as `--sim-binary <BIN>`. `./ns3 run` finds it on its own.

## 5\. Next

- \ref mesh_sim_first_run "Your first run": run a scenario with this binary.
- \ref readme_python_environment "Python environment": set up `.venv` for the
  plotting, RL, sweep and validation tools.

Previous: \ref mesh_sim_start_here "Start here" · Next: \ref mesh_sim_first_run "Your first run"
