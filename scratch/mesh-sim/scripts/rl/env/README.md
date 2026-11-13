@page scripts_rl_env scripts/rl/env

@brief Gymnasium adapter that runs the mesh-sim simulator as a subprocess and talks to it over the RL JSON protocol.

`MeshRlEnv` starts one simulator process per episode, validates every message
it sends back, and turns the reply into a Gymnasium observation, reward, and
`info` dict. It also writes the per-episode manifest and optional step
telemetry. The wire contract lives in [`src/rl/README.md`](@ref src_rl);
observation presets and reward components are specified in
[`src/rl/policy-inputs.md`](@ref src_rl_policy_inputs). This page does
not repeat them.

## 1\. Module layout

| Owner | Responsibility |
| --- | --- |
| `mesh_env.py`, `episode.py`, `protocol.py`, `mission_protocol.py` | Gymnasium lifecycle, simulator process, wire validation and native mission metadata. |
| `selection.py`, `config.py`, `normalization.py` | Resolve configuration and immutable identities; shared physical scales. |
| `rewards/` | Composer/registry plus `objectives.py` (binary and continuous), `shaping.py` (travel, boundary, signal, proximity, arrival), `mission_terms.py` (mission stages), `coordination.py` and `radio.py`. |
| `observations/` | Registry/schema plus `compact.py`, `coordination.py`, `mission.py` and `radio.py` feature layouts. |
| `state/` | `mission.py` and `coordination.py` track observable history; `measurements.py` supplies shared metrics; `extensions.py` attaches requested facts. |
| `recording/` | `artifacts.py` owns episode manifests; `telemetry.py` records/replays steps; `settings.py` and `decisions.py` own optional decision sidecars. |
| `geometry.py`, `curriculum.py`, `seeded_env.py`, `jammer_motion.py` | Legal paths, training-only staged starts, fresh environments per seed and reproducible jammer motion. |

## 2\. How one episode flows

### Reset

1. `MeshRlEnv.reset` stops any earlier episode (status `interrupted`).
2. `EpisodeSession.start` creates `episode-NNNN/` under the output root and
   launches the simulator with `--run-config`, `--rl-mode`, `--seed` and
   `--output-dir`, plus `--no-viz` for compact runs, `--jammer-onset-s` when an
   onset schedule applies (section 6), and `--band` when one was given.
3. The first message must be `init`; anything else is a protocol error. (The
   old single-node legacy mode, which started with `step`, is no longer
   supported.)
4. `CentralizedProtocol` validates `init`, spaces are built, the observation
   and reward schemas are recorded in the manifest, and the first `step`
   message becomes the reset observation.

### Step

1. `step(action)` checks the action shape (`CentralizedProtocol.joint_action`)
   and sends `{"action": ...}` to the simulator.
2. The reply is read and validated by the protocol object (contract, window
   sums, tick monotonicity).
3. The observation is built from `facts` by the selected preset; the default
   `raw_links_v1` reproduces the simulator's own vector.
4. The reward is the simulator's, or a `RewardComposer` weighted sum when
   `reward_components` is set. Components whose window is invalid are left out.
5. `EpisodeSession.record_step` updates the manifest and, if telemetry is on,
   appends a record to `steps.jsonl`.
6. When the reply has `done`, the session stops the simulator and marks the
   episode `completed`.

### Failure and close

Any protocol error, bad JSON, or early process exit marks the episode `failed`
and raises `RuntimeError` with the command, exit code, and stderr tail.
`close()` marks it `interrupted`. Every path stops the child process and the
stdout drain thread.

## 3\. Control and spaces

- Control is centralized: `[rl] controlled_nodes` selects the slots, the action
  space is `MultiDiscrete([5] * max_controlled_nodes)` and the observation is a
  `Box` whose size comes from `init` (or the preset).
- The simulator owns the action mask; `action_masks()` returns it unchanged.
- Spaces are unknown until the first `reset`. A later reset whose contract
  differs from the first is a protocol error and the original spaces stay.

## 4\. Output

Written under `<output_dir>/episode-NNNN/`, one directory per reset.

| File | Where it comes from |
| --- | --- |
| `rl_episode.json` | `EpisodeSession`; status `running`, `completed`, `interrupted`, or `failed`, plus totals and the contract, selection and schema hashes. |
| `sim_stderr.log` | Simulator stderr; its tail is shown in error messages. |
| `steps.jsonl` | `recording.telemetry.StepRecorder`, only when `telemetry = steps`; replay with `recording.telemetry.replay_file`. |
| `policy_decisions_manifest.json` | `recording.decisions.DecisionRecorder`, only with `--decision-records`; identity, coverage, and status of the decision records. |
| `policy_decisions.jsonl` | `recording.decisions.DecisionRecorder`, only with `--decision-records`; one reset record, then one record per saved decision. |
| Simulator outputs | Everything the simulator itself writes into `--output-dir`. |

## 5\. Seeded scenario checks {#scripts_rl_env_seeded}

Scenario checks use `SeededEnv` to run each policy on the prepared
configuration for a given diagnostic seed. For example, `reset(seed=202)`
selects `seed-202/run.ini` and reads seed 202's controller gate from the
case manifest. The wrapper closes the previous environment, creates a fresh
`MeshRlEnv`, and keeps the same output root so episode directories stay in
one sequence.

The scenario checker supplies `sub-6` as an explicit band override. Other
callers can supply a band or let the wrapper use the seed's `[channel] band`
setting, with `mmwave` as the simulator default.

## 6\. Python-only [rl] keys

These keys are read by the Python environment, not the simulator.

- **`manifest_every_decisions`** (positive integer, default 1).
  `EpisodeArtifacts` saves the in-progress `rl_episode.json` every that many
  decisions; reset, contract/selection changes and finalization always write.
  This reduces disk writes without dropping evaluation telemetry or final
  totals. An ungraceful OS kill can leave progress up to cadence−1 decisions
  behind.
- **`compact_training = true`** omits visualization CSVs and detailed step
  telemetry for training and selection runs, while keeping summaries, training
  history and selection results. The simulator receives `--no-viz`. Final
  evaluation keeps full telemetry.
- **`training_jammer_onsets_s`, `evaluation_jammer_onsets_s`**: comma-separated
  finite times in [0, `duration_s`); require `jammers_file`. Training cycles
  the list across resets; evaluation selects `seed % len(list)`. The episode
  command passes the chosen time as `--jammer-onset-s`, and the simulator
  enables the configured jammers from then to episode end. Under
  `arrive_hold_v1` (below) the onset comes from the archived motion inputs
  instead.
- **`jammer_motion_profile`** resolves reproducible per-episode jammer motion
  in `jammer_motion.py`, archived under `motion-inputs/` and recorded in
  episode manifest version 6. Ordinary episode schemas are unchanged. Both
  profiles require exactly one jammer.
  - `sweep_v1`: training cycles horizontal direction and onset; evaluation
    seed parity selects vertical direction and its seed-dependent timing.
    Every variant starts at the same position. Its waypoints assume a
    600-second, 400×400 m case; that is not validated.
  - `arrive_hold_v1`: a seeded route from an edge to a stop point, starting at
    the scheduled onset and arriving 60 s later; `duration_s` must exceed the
    arrival time.

**Dynamic reward components.** `fair_node_service` averages
sqrt(clipped per-node delivered/offered fractions), excluding zero-demand
nodes. `adaptive_movement_cost` charges
`(0.02 + 0.08 * previous_health) * travel_fraction`, with health the minimum of
delivery, fair service and coverage; composer health resets to zero each
episode. The lag, coefficients, normalizers and coverage configuration enter
the reward schema hash.

## 7\. Conventions

- Validate, never coerce: a malformed message raises `ProtocolError`.
- Saved presets are immutable. A change to features, dtype, or normalization
  needs a new `_vN` preset, because it changes the schema hash.
- `config.py` follows the C++ INI rules (inline comments stripped, `nodes_file`
  relative to `run.ini`).

## 8\. Dependencies

- Python packages: `gymnasium` and `numpy`; install as described in the
  [main README](@ref readme_python_environment).
- `scripts/sim_support.py` for the simulator environment and helpers.
- A built simulator binary passed as `sim_binary`; this package does not build it.
- Tests: @ref scripts_rl_tests.
