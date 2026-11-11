# Coordination smoke batch

A portable, public batch example: one sub-6 rural coverage case with three
peers (pedestrian and vehicle at 1.5 m, drone at 20 m), one building and
scripted reference routes. The run.ini resolves to 64 decisions per episode
(64 s, 0.1 s ticks, 1 s decisions). Training uses 256 decisions with
post-update checkpoints at 128 and 256; four operations (frozen deterministic,
frozen sampled and both online protocols) run on diagnostic seeds 201 and 202.

Run the single-case capability probe with
`python -m scripts.rl.operate preflight`. See the
[policy operations guide](../../../../scripts/rl/policy/README.md) for its
arguments and supported capabilities. The batch schema reserves `preflight`;
run the probe separately from this batch.

The replay check inherits the scenario case and defaults to `comparison:
"strict_v1"`, no parent and `contact_audit: false`. For older saved telemetry,
a check may explicitly set `comparison: "pre_contact_source_v1"`,
`parent: {"run_dir": "/absolute/completed-training-run", "model": "final"}`
and `contact_audit: true`. This is only appropriate for a source that predates
boundary-contact telemetry; it is not a way to accept other changed physics.

## Preview the plan

From `scratch/mesh-sim/`, use the
[batch planning API](../../../../scripts/rl/experiments/README.md) to validate
the inputs and print the dependency graph.

```bash
.venv/bin/python - <<'PYTHON'
from scripts.rl.experiments.config import load_matrix_v2
from scripts.rl.experiments.plan import build_batch_plan, describe_expansion

matrix = load_matrix_v2("inputs/experiments/examples/coordination-smoke/batch.json")
plan = build_batch_plan(matrix)
print("\n".join(describe_expansion(plan)))
PYTHON
```

The preview uses static Python validation. A native smoke run is still
pending.
