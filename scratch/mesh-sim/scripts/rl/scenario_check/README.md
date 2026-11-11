# October 23 scenario checks

This package validates the approved reset before any reward or PPO training.
The separate `inputs/custom/10-23/run-scenario-check.sh` launcher runs 24 cases:
coverage, investigation, recovery and jamming in rural RMa and urban UMa with
3, 6 and 9 mobile peers. Seeds 201 and 202 are diagnostics, not held-out tests.
Hold, random-valid and scripted references give 144 episodes. Geometric and
optimization initial placements add 24 coverage episodes, for 168 total.

`inputs.py` materializes approved coordinates, equal per-source traffic and
seeded jammer routes. Stop positions and approach sides are counterbalanced
by seed index; onset is pseudorandom. Seeds 201/202 approach from opposite
ends of y=200 and stop at (195,200)/(220,200) at 160/180 s, respectively. The generated `scenario-check.json` fingerprints every
input. `geometry.py` builds cardinal A* routes with 3 m building clearance and
reservations around other starts/endpoints. The reference controller uses live
native masks and a joint swept-distance guard; C++ remains the safety authority.
Geometry alone does not establish joint completion or RF feasibility.

`placement.py` adapts the existing placement solver rather than implementing
another optimizer. Both methods maximize connected-core outdoor probe coverage
at 10 dB, on the same 400 nominal cells as the simulator. Indoor probe centers
are excluded at 1.5 m height, including footprint edges. Candidate grid 144,
optimizer iterations 75, planning seed 311, optimizer seed 7; no evaluation seed
selects a plan. Building clearance is 2 m, peer separation 5 m, heights fixed.
The existing greedy anchor restriction still applies; annealing is bounded
keep-best search, not a global optimum. All movement costs and noncoverage
objective weights are zero. Initial relocation is recorded separately and
placements hold during episodes. Their outcomes cannot prove common-start
navigation feasibility and never satisfy scripted mission acceptance gates.

`execution.py` archives and rebases inputs before launching, checks the binary
mtime against sources, records binary/linked-library and Python code identities,
and reuses standard version 8 evaluation manifests. Four worker threads each
own one case; at most four simulator/query children run at once. Numeric library
threads are limited to one by the shell launcher. No total runtime cutoff,
training import, PPO model or automatic next stage exists. Existing output
roots are refused instead of overwritten or mixed. Ctrl-C cancels queued jobs
and closes active episode sessions; existing channel-client protocol deadlines
still guard broken query responses, not total campaign duration.

`reports.py` verifies exact building geometry, physical paths and replay parity,
then writes per-episode `scenario_timeline.csv`, `mission_trace.csv`,
`scenario_check_metrics.json` and native mission metrics. Mission-first checks:

| Mission | Held reference | Scripted reference |
| --- | --- | --- |
| Coverage | Compact starting footprint | Final-minute area gain at least 0.05 and delivery at least 0.90 |
| Investigation | Must never complete | Every peer within 50 m of (345,300) throughout final 30 s |
| Recovery | Pre-failure delivery at least 0.90, final survivor delivery below 0.60 | Final survivor delivery at least 0.90, worst service at least 0.80, sustained final 30 s |
| Jamming | Pre-emission delivery at least 0.90, final active delivery below 0.60 | Same 0.90/0.80 final service gates, sustained final 30 s |

Both seeds must pass. Coverage additionally needs one common threshold between
the worst scripted and best held result with at least 0.05 headroom; the midpoint
is a proposed future reward target requiring review. Investigation's simple
all-peer arrival metric is separate from native mission success, which also
requires a connected core. Mission metric averages, final values, LOS/SINR,
travel, goal distance and disruption are saved separately. Event boundary
windows are excluded; failed recovery delay is null, never zero or discarded.

At the output root, `scenario_check_status.json` records case progress;
`scenario_check_report.json`, `scenario_episodes.csv`, and `RESULTS.md` describe
all cases. Exit 0 means all gates passed; 2 means checks finished with cases
needing revision; 1 means execution/audit errors. No result advances to training.
For the GUI, open `outputs/custom/10-23/scenario-check/Main`, then the desired
case, or select an individual case as a standalone baseline-only evaluation.
There are deliberately no trained reward-function cards in this stage.

The old `run-baseline.sh` and `campaign.json` belong to the earlier design and
are retained as history. They are not launchers for this approved reset.

Verification is pure only: `test_scenario_check.py` blocks subprocess creation.
C++ configuration tests and a rebuilt real binary must be run by the user.
No static check validates propagation, target completion, throughput severity,
planner runtime or GUI playback of files that have not yet been produced.

## Correction pass after the first user run

Use `run-scenario-check-02.sh`. Its version 2 inputs are a separate immutable
17-case / 102-episode reference batch, without placement searches. It reruns
all investigation and jamming cases, urban recovery at every size, and
three-peer coverage in both environments. Starting positions, buildings,
traffic, radio, failures, jammer power and all acceptance thresholds are
retained. Original outputs are never overwritten.

Investigation zero secondary targets are accepted consistently by C++ and
Python. Fixed jammer intervals no longer inherit training/evaluation onset
schedules. The controller reset and post-episode audit both reject a command
override, a gate mismatch or emission ending at the final sample. Successful
checks write `event_timing.json` before any reference movement. Seed 201 now
emits at 160 s, seed 202 at 180 s, both through 600.5 s.

Urban recovery reference endpoints use x=180 and x=220, reducing each paired
survivor gap from 60 to 40 m. Urban three-peer coverage targets are ground
(195,100), drone (195,200), vehicle (195,300); all are reference endpoints,
not policy formation goals. Rural coverage uses rounded endpoints from the
previous seed-311 optimization: ground (190,15), drone (130,305), vehicle
(365,305), reached through obstacle-safe routes from the original start.
Rounded positions and routes require new measured RF validation. Nine-peer
jamming can remain rejected if redundancy makes holding effective; its
severity is deliberately unchanged.

A new standalone C++ configuration test parses every corrected scenario/seed.
The user must run that test and rebuild before launching. The configuration
check is not a simulation. The launcher still never trains or builds anything.
