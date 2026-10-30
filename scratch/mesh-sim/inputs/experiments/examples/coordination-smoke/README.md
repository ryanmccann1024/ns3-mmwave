# Coordination smoke batch

A portable, public batch example: one sub-6 rural coverage case with three
peers (pedestrian and vehicle at 1.5 m, drone at 20 m), one building and
scripted reference routes. The run.ini resolves to 64 decisions per episode
(64 s, 0.1 s ticks, 1 s decisions). Training uses 256 decisions with
post-update checkpoints at 128 and 256; four operations (frozen deterministic,
frozen sampled and both online protocols) run on diagnostic seeds 201 and 202.

The batch has no `preflight` check: physical preflight checks are a separate
human-run step via `python -m scripts.rl.preflight_campaign` until a batch
adapter is approved.

The replay check inherits the scenario case and defaults to `comparison:
"strict_v1"`, no parent and `contact_audit: false`. For older saved telemetry,
a check may explicitly set `comparison: "pre_contact_source_v1"`,
`parent: {"run_dir": "/absolute/completed-training-run", "model": "final"}`
and `contact_audit: true`. This is only appropriate for a source that predates
boundary-contact telemetry; it is not a way to accept other changed physics.
The matrix validator refuses `preflight` checks before creating a plan.

Provenance: proposed and unverified. Static Python validation only; the native
smoke run is a human-run check and has not been executed.

See [the batch reference](../../../../docs/rl/batch-reference.md) and
[experiments and operations](../../../../docs/rl/experiments-and-operations.md).

```bash
bash scripts/rl/run-experiments.sh validate --matrix inputs/experiments/examples/coordination-smoke/batch.json
```
