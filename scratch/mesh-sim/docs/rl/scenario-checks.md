# Scenario checks {#mesh_sim_rl_scenario_checks}

Use `scripts.rl.scenario_check` to verify legal routes and healthy, disrupted
and restored conditions before training. The [package guide](../../scripts/rl/scenario_check/README.md)
owns that workflow and its inputs.

For stationary feature/difficulty checks, the retained compatibility command is:

```bash
.venv/bin/python -m scripts.rl.preflight_campaign --inputs <folder> --sim-binary <BIN> --output-root <fresh-folder>
```

`<folder>/campaign.json` lists `scenarios` (folders containing `run.ini`) and
optional `preflight.seeds` (default `[201]`) and `challenge_delivery_max`.
It verifies measured coverage, building avoidance, separation and configured
hold-service limits, writing `preflight.json`. `--check` reads a completed
report and verifies its binary/input identity without launching anything.
The implementation is `scripts/rl/scenario_check/preflight.py`; it calls the
policy evaluation library, not another CLI. This compatibility check is separate
from batch replay gates; matrix-v2's reserved `preflight` task remains rejected.

These commands launch a simulator unless `--check` is used. They are user-run;
no native verification was performed during the organization cleanup.
