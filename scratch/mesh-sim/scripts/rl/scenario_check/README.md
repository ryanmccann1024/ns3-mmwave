@page scripts_rl_scenario_check scripts/rl/scenario_check

@brief Checks-only package: runs reference policies on fixed diagnostic seeds to validate scenarios before training.

`scripts.rl.scenario_check` validates the approved scenarios before any reward
or PPO training. It runs reference policies (hold, random valid, scripted and
placement baselines) on fixed diagnostic seeds and reports whether each case
has enough headroom for its mission. It never trains, builds or advances to a
later stage.

The package was built for the October 23 campaign; its default input and output
paths point at that campaign's local folders (`inputs/custom/10-23/` and
`outputs/custom/10-23/`). To run it, follow
[Run scenario checks](@ref mesh_sim_rl_scenario_check_runner); this page is the
reference for what it checks and how.

## 1\. What a run covers

- **24 cases:** coverage, investigation, recovery and jamming missions, in rural
  RMa and urban UMa, with 3, 6 and 9 mobile peers. The launcher is
  `inputs/custom/10-23/run-scenario-check.sh`.
- **Seeds 201 and 202** are diagnostics, not held-out tests.
- **168 episodes:** hold, random-valid and scripted references give 144;
  geometric and optimization initial placements add 24 coverage episodes.

## 2\. Modules

| Module | Role |
| --- | --- |
| `inputs.py` | Materializes the approved scenarios: coordinates, equal per-source traffic and seeded jammer routes; writes the `scenario-check.json` manifest. |
| `geometry.py` | Re-exports the route owners in `scripts/rl/env/geometry.py`. |
| `placement.py` | Adapts the existing placement solver for the placement baselines. |
| `execution.py` | Archives inputs, records identities and runs cases on worker threads. |
| `reports.py` | Verifies geometry, paths and replay parity; writes the per-episode and campaign reports. |
| `followup.py` | Prepares the follow-up batch from a completed run (section 6). |

**Inputs (`inputs.py`).**

- Stop positions and approach sides are counterbalanced by seed index; onset
  is pseudorandom.
- Seeds 201 and 202 approach from opposite ends of y=200 and stop at (195,200)
  and (220,200) at 160 s and 180 s, respectively.
- `scenario-check.json` fingerprints every input.

**Routes.** `scripts/rl/env/geometry.py` builds cardinal A* routes with 3 m
building clearance and reservations around other starts and endpoints. The
reference controller (`policy/scripted.py`) uses live native masks and a joint
swept-distance guard; C++ remains the safety authority. Geometry alone does not
establish joint completion or RF feasibility.

**Placement baselines (`placement.py`).** Both methods maximize connected-core
outdoor probe coverage on the same 400 nominal cells as the simulator; indoor
probe centers are excluded at 1.5 m height, including footprint edges. The
fixed settings are in the
[diagnostic settings table](@ref mesh_sim_rl_scenario_check_runner). In
addition:

- No evaluation seed selects a plan.
- The existing greedy anchor restriction still applies; annealing is a bounded
  keep-best search, not a global optimum.
- All movement costs and non-coverage objective weights are zero. Initial
  relocation is recorded separately, and placements hold during episodes.
- Placement outcomes cannot prove common-start navigation feasibility and never
  satisfy scripted mission acceptance gates.

**Execution (`execution.py`).**

- Archives and rebases inputs before launching, checks the binary's mtime
  against the sources, records binary, linked-library and Python code
  identities, and reuses standard version 8 evaluation manifests.
- Four worker threads each own one case; at most four simulator or query
  children run at once. The shell launcher limits numeric library threads to
  one.
- There is no total runtime cutoff, training import, PPO model or automatic
  next stage. Existing output roots are refused instead of overwritten or
  mixed.
- Ctrl-C cancels queued jobs and closes active episode sessions; channel-client
  protocol deadlines still guard broken query responses, not total campaign
  duration.

## 3\. Acceptance gates

`reports.py` verifies exact building geometry, physical paths and replay parity,
then applies mission-first gates:

| Mission | Held reference | Scripted reference |
| --- | --- | --- |
| Coverage | Compact starting footprint | Final-minute area gain at least 0.05 and delivery at least 0.90 |
| Investigation | Must never complete | Every peer within 50 m of (345,300) throughout the final 30 s |
| Recovery | Pre-failure delivery at least 0.90, final survivor delivery below 0.60 | Final survivor delivery at least 0.90, worst service at least 0.80, sustained for the final 30 s |
| Jamming | Pre-emission delivery at least 0.90, final active delivery below 0.60 | Same 0.90/0.80 final service gates, sustained for the final 30 s |

- Both seeds must pass.
- Coverage also needs one common threshold between the worst scripted and best
  held result, with at least 0.05 headroom; the midpoint is a proposed future
  reward target that needs review.
- Investigation's simple all-peer arrival metric is separate from native
  mission success, which also requires a connected core.
- Mission metric averages, final values, LOS/SINR, travel, goal distance and
  disruption are saved separately. Event boundary windows are excluded; a failed
  recovery delay is null, never zero or discarded.

## 4\. Outputs and exit codes

- **Per episode:** `scenario_timeline.csv`, `link_timeline.csv`,
  `mission_trace.csv`, `scenario_check_metrics.json` and native mission metrics.
- **At the output root:** `scenario_check_status.json` records case progress;
  `scenario_check_report.json`, `scenario_episodes.csv` and `RESULTS.md`
  describe all cases.
- **Exit codes:** 0 means all gates passed; 2 means checks finished with cases
  needing revision; 1 means execution or audit errors. No result advances to
  training.
- **GUI:** open `outputs/custom/10-23/scenario-check/Main`, then the case, or
  select one case as a standalone baseline-only evaluation. There are
  deliberately no trained reward-function cards at this stage.
- The old `run-baseline.sh` and `campaign.json` belong to the earlier design and
  are kept as history; they are not launchers for this reset.

## 5\. Verification

- `experiments/test_scenario_check.py` is pure: it blocks subprocess creation.
- C++ configuration tests and a rebuilt real binary must be run by the user.
- No static check validates propagation, target completion, throughput
  severity, planner runtime, or GUI playback of files not yet produced.

## 6\. History: the correction pass after the first run

After the first user run, a follow-up batch was prepared with `followup.py` and
is launched with `run-scenario-check-02.sh`.

- Its version 2 inputs are a separate, immutable 17-case / 102-episode
  reference batch without placement searches. It reruns all investigation and
  jamming cases, urban recovery at every size, and three-peer coverage in both
  environments.
- Starting positions, buildings, traffic, radio, failures, jammer power and all
  acceptance thresholds are unchanged. Original outputs are never overwritten.

Corrections made in that batch:

- Investigation with zero secondary targets is accepted consistently by C++
  and Python.
- Fixed jammer intervals no longer inherit training/evaluation onset schedules.
  The controller reset and post-episode audit both reject a command override, a
  gate mismatch, or emission ending at the final sample. Successful checks write
  `event_timing.json` before any reference movement. Seed 201 now emits at
  160 s and seed 202 at 180 s, both through 600.5 s.
- Urban recovery reference endpoints use x=180 and x=220, reducing each paired
  survivor gap from 60 m to 40 m.
- Urban three-peer coverage targets are ground (195,100), drone (195,200) and
  vehicle (195,300); all are reference endpoints, not policy formation goals.
- Rural coverage uses rounded endpoints from the earlier seed-311 optimization:
  ground (190,15), drone (130,305) and vehicle (365,305), reached through
  obstacle-safe routes from the original start. Rounded positions and routes
  need new measured RF validation.
- Nine-peer jamming can remain rejected if redundancy makes holding effective;
  its severity is deliberately unchanged.

A standalone C++ configuration test parses every corrected scenario and seed.
The user must run that test and rebuild before launching; the configuration
check is not a simulation, and the launcher never trains or builds anything.
