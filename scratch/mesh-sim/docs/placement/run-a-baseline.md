# Run a baseline {#mesh_sim_placement_run}

[TOC]

Check a scenario's placement settings, plan it with both methods, and see
what it takes for the nodes to actually move.

<!-- Every output on this page comes from runs on 2026-10-28: mesh-sim commit
     b54bfbe7 plus the working tree, binary build/scratch/mesh-sim/ns3.42-sim-debug
     SHA-256 d7a2f4d1eb52c30abb0c6cecc8480aa29232afd12730fcc402caa0fc446c9fe2,
     outputs under scratch/mesh-sim/outputs/my-baselines/. -->

\htmlonly
<div class="ms-gates">
<div class="ms-gate"><strong>3. Check</strong><span>settings only</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>4. Plan and run</strong><span><code>geometric</code></span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>5. Other method</strong><span><code>optimization</code></span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate ms-gate-end"><strong>6. Free movement</strong><span>nodes move</span></div>
</div>
\endhtmlonly

## 1\. Before you start

- **Built binary:** `build/scratch/mesh-sim/ns3.42-sim-debug` exists
  (\ref mesh_sim_install_build "Install and build").
- **Python environment:** `.venv` exists
  (\ref readme_python_environment "Python environment"). Placement needs only
  `numpy`, which it already has.
- **Working directory:** run every command from `scratch/mesh-sim/`, not the
  repository root. The baseline tools are Python modules run as
  `python -m scripts.<package>.<module>`.

Set two variables once per shell:

```bash
SIM_BIN="$(cd ../.. && pwd)/build/scratch/mesh-sim/ns3.42-sim-debug"
EX=inputs/baselines/channel-scored-example
```

`SIM_BIN` must be an absolute path. The runner launches the binary twice:
once as the channel query while planning, then for the simulation itself.

## 2\. The scenario

`inputs/baselines/channel-scored-example/` is the placement example.

| Setting | Value |
|---|---|
| Nodes | `air-a` (drone) at (120, 120, 30), `air-b` (drone) at (280, 120, 30), `ground-peer` (vehicle) at (200, 280, 1.5); all fixed |
| Area | 400 × 400 m, from the `[rl]` x/y bounds |
| Time | 10 s in 0.1 s ticks, 2 s warmup |
| Channel | 28 GHz mmWave, NYU UMi, always line of sight |
| Movable nodes | `air-a`, `air-b` |
| Objective | `balanced` |
| Movement cost | 150,000 m² to move at all, plus 500 m² per meter (drones); at most 100 m per node |
| Seeds | planning seed 701, optimizer seed 201, simulation seed 801 |

The folder holds two settings files. `run.ini` uses the movement costs above.
`run-zero-cost.ini` is identical except that all four cost keys are `0`.

## 3\. Check the settings

Reading the settings needs no binary, so catch mistakes here first:

```bash
.venv/bin/python - <<'PY'
from scripts.baselines.config import load_baseline, read_ini, require_method
from scripts.baselines.mapping import load_mapping
cfg = load_baseline("inputs/baselines/channel-scored-example/run.ini")
require_method(cfg, cfg.algorithm)
mapping = load_mapping(cfg.mapping_file, read_ini(cfg.run_config))
print(cfg.algorithm, cfg.objective, cfg.movable_nodes, cfg.planning_seed)
print(mapping.rectangle)
PY
```

**Checkpoint:** it prints

```
geometric balanced ('air-a', 'air-b') 701
{'x_min': 0.0, 'x_max': 400.0, 'y_min': 0.0, 'y_max': 400.0}
```

- `load_baseline` reads `[baseline]` and rejects unknown keys and bad values.
- `require_method` checks that the keys the method needs are present.
- `load_mapping` works out where nodes may go. This scenario has no mapping
  file, so the area is the `[rl]` x/y bounds.

## 4\. Plan and run `geometric`

```bash
.venv/bin/python -m scripts.baselines.runner \
  --sim-binary "$SIM_BIN" --run-config "$EX/run.ini" \
  --output-dir outputs/my-baselines/geometric
```

- The method comes from `[baseline] algorithm`, here `geometric`.
- With no `--seeds`, it simulates the `[scenario] seed`, 801.
- `--output-dir` must be new or empty.

**Checkpoint:** after about four seconds it prints

```
Baseline run complete: .../scratch/mesh-sim/outputs/my-baselines/geometric
```

and `echo $?` prints `0`. The planner's decisions are in `planner.log`:

```bash
grep '^geometric' outputs/my-baselines/geometric/planner.log
```

```
geometric: air-a stays put (best marginal -164120 m2)
geometric: air-b stays put (best marginal -164120 m2)
```

Neither drone moved. The best move for each would have **lowered** the score
by 164,120 m². Most of that is the 150,000 m² fixed cost of moving at all, on
an area of only 160,000 m². \ref mesh_sim_placement_read "Understand the plan"
explains each number.

## 5\. Plan with `optimization`

Same scenario, other method:

```bash
.venv/bin/python -m scripts.baselines.runner \
  --sim-binary "$SIM_BIN" --run-config "$EX/run.ini" \
  --algorithm optimization --output-dir outputs/my-baselines/optimization
```

`--algorithm` overrides `[baseline] algorithm`. `optimization` also reads
`seed = 201` and `max_iterations = 100` from the same section; `geometric`
ignores both, so one settings file serves both methods.

**Checkpoint:** it completes, and

```bash
grep '^optimization' outputs/my-baselines/optimization/planner.log
```

```
optimization: sa iters=100 accepts=0 rejected=25 score=160,181 m2-equivalent (seed: geometric)
```

`optimization` starts from the `geometric` plan, then makes 100 random
proposals. 25 were invalid and never scored: they left the allowed area, or
were "teleport to an uncovered spot" when every spot was already covered. The
other 75 were scored, all scored lower, and none was accepted. It ends where
`geometric` did.

## 6\. Make movement free

Run `geometric` on the zero-cost copy:

```bash
.venv/bin/python -m scripts.baselines.runner \
  --sim-binary "$SIM_BIN" --run-config "$EX/run-zero-cost.ini" \
  --output-dir outputs/my-baselines/geometric-zero-cost
```

**Checkpoint:** both drones move.

```bash
grep '^geometric' outputs/my-baselines/geometric-zero-cost/planner.log
```

```
geometric: air-a -> (60.000, 60.000) marginal 49.1697 m2
geometric: air-b -> (340.000, 60.000) marginal 64.8364 m2
```

Each drone moved about 85 m outward. The gains are tiny, 49 and 65 m² on a
160,000 m² area. Coverage was already complete, so the only thing left to
gain was spreading the nodes apart. The next page shows what that did to the
simulation.

## 7\. Going further

- \ref scripts_baselines "scripts/baselines": every runner option, exit code
  and `[baseline]` key, including movement caps and grid sizes.
- \ref mesh_sim_rl_start "Reinforcement learning": run `geometric` and
  `optimization` as policies beside a trained model, with
  `scripts.rl.evaluate --policies`.

Previous: \ref mesh_sim_placement_start "Placement baselines" · Next: \ref mesh_sim_placement_read "Understand the plan"
