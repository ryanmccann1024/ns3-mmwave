# Run scenario checks {#mesh_sim_rl_scenario_check_runner}

Use the scenario checker to see whether the prepared scenarios have enough
headroom for the mission objective. Each case compares hold, random valid,
and scripted policies on the same two diagnostic seeds. Coverage cases may
also run geometric and optimized initial-placement baselines. The results
measure feasibility on those seeds.

## Plan and run

From `scratch/mesh-sim`, validate the input fingerprints and preview the
number of cases and episodes.

```bash
python -m scripts.rl.scenario_check --inputs /path/to/scenario-check --plan-only
```

Run the campaign with a built simulator and a fresh output directory.

```bash
python -m scripts.rl.scenario_check \
  --inputs /path/to/scenario-check \
  --sim-binary /path/to/mesh-sim \
  --output /path/to/scenario-check-results \
  --workers 4
```

The input manifest is `scenario-check.json`. It names the cases, maps each
seed to its INI and controller gate, and records the input hashes. The runner
archives those inputs under `inputs/` in the output directory. References in
each INI resolve from its original directory before they are pinned to the
archive. Each worker runs a case, including its policies and seeds, in order.
The runner defaults to four concurrent cases. Set `--workers` from 1 to 4.
Interrupting a run cancels queued cases and closes the active environments.

## Diagnostic settings

The shared campaign defaults live in
[`scripts/rl/scenario_check/defaults.py`](defaults.py).
The table lists the fixed settings for the prepared campaign.

| Setting | Value |
| --- | --- |
| Evaluation seeds | 201 and 202 |
| Channel-planning and optimizer seeds | 311 and 7, respectively |
| Radio band | `sub-6` |
| Placement bounds | 400 × 400 m horizontally, altitude bounds 0–60 m |
| Building clearance and minimum peer separation | 2 m and 5 m, respectively |
| Candidate grid and coverage grid | 144 and 400 cells, respectively, with 5 m minimum grid resolution |
| Coverage probe | 1.5 m above ground, 3 dBi receive gain, 10 dB SINR threshold |
| Placement optimizer | 75 iterations, balanced core fraction 0.5, zero movement costs |

The placement baselines use the same prepared endpoints for both evaluation
seeds. Each writes its planner result, displacement, and seed roles to
`planning/<case>/<policy>/placement.json`. For how a seed selects its INI and
controller gate, see [Seeded scenario checks](@ref scripts_rl_env_seeded).

## Read the results

`scenario_check_status.json` records progress by case. Open `RESULTS.md` for
the final verdicts and `scenario_episodes.csv` for per-episode metrics. Each
`Main/<case>/` directory contains the evaluation manifest and a scenario
report. Its episode directories contain the decision trace, mission and link
timelines, and safety and replay results. An exit code of 0 means all cases
passed their acceptance checks. Exit 2 means cases finished with results
that require review. Exit 1 means execution or auditing failed.

`followup.py` prepares the second diagnostic batch from a prior
run's archived inputs and reports. It selects 17 cases, updates specific
reference routes and event settings, and writes a new campaign with 102
episodes. The follow-up records its source fingerprints and changes in
`preparation.json`.

The separate `scripts.rl.preflight_campaign` command checks simulator
features and stationary scenario difficulty for training inputs.
Its `--check` mode verifies an existing passing report against the current
binary and input fingerprints.
