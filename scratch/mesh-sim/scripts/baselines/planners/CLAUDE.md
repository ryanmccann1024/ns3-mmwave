# Placement engine owners

Read [README.md](README.md) for the API, configuration, limits and extension path.
Keep objective terms and parameter metadata in `components.py`, presets and
physical scoring context in `objective.py`, graph facts in `graph.py`, bounded
reuse in `cache.py`, and algorithm mechanics/settings with each strategy.
`planner_config.py` delegates INI meaning to those owners; `solver.py` coordinates.

Use registered terms/presets/strategies rather than adding name branches to
composition. Record resolved values, component versions, worker limits and the
settings hash. Changes to defaults or calculations must change saved identity.
Stream candidates and retain bounded batches plus current/best layouts; request
batching alone does not bound retained results. Cache byte accounting is an
estimate with conservative object overhead, not a whole-process RSS guarantee.

Use the advertised serial child deadlines for client budgets. Keep valid limits,
invalid-value checks and tests with their owner. Preserve exact-layout draw order,
2D selected-node movement, active-gateway exclusion and separate planning/search/
held-out seeds. Explain capacity-insensitive default objectives and keep t=0
placement costs separate from scored episode travel. Update the fake worker,
protocol guide, consumers and tests together for wire changes. Never build/run
the simulator here; fake checks and syntax checks leave real parity/timing open.
