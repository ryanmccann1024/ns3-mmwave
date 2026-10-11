# scripts/baselines

Read [README.md](README.md) for the versioned configuration example, source
coordinate/objective explanations, and active-planner extension steps.

- Keep CLIs to argument parsing and delegation. Do not put configuration,
  schema, node-authority, or planner search logic in them.
- `config.py` owns INI/options validation; `mapping.py` owns mapping/geofence
  validation. Keep defaults and accepted values beside their owner.
- `adapter.py` owns node mapping, gateway/control authority and plan validation.
  `preparation.py` coordinates planning, snapshots and preparation metadata.
  `execution.py` owns child cleanup and standalone outcomes; `runner.py`
  only parses arguments and delegates.
- `effective_inputs.py` owns snapshots and effective scenario rewriting.
  `artifacts.py` owns baseline schemas, transitions, and fingerprint fields.
- Reuse `scripts/artifact_io.py` for generic JSON I/O, hashes, and timestamps.
  It uses only the standard library; baselines must not import RL CLI helpers.
- Keep planner mechanics and settings with the solver/method owner. RL placement
  setup and matrix execution belong in their policy owners, not CLI modules.
- Exclude the active traffic gateway from placement selection and RL control.
  Keep initial relocation cost distinct from episode movement and measured
  performance. Decisions continue during warmup; scored facts begin at warmup.
- Preserve all nine pinned `third_party/arpo_placement` source files. Put
  explanations in documentation and runtime adaptations outside that tree.
- The active contract is mapping v2, baseline manifest/plan v3, evaluation v5
  and comparison v2. RF planning has been removed. Delegate to the engine
  [guide](planners/README.md) and keep binary/library identity in
  `runtime_identity.py`, separate from artifact schemas and generic I/O.
- Require a dedicated channel-planning seed and record optimizer, training,
  selection and held-out roles separately. Never select a plan from the first
  evaluation seed. Explicit overlap is diagnostic and cannot enter held-out groups.
- Cross-language loader parity belongs in `test_simulator_defaults.py`; do not
  scatter additional copied fallbacks without updating that contract check.
- Tests write to temporary directories. Parsing and fake-planner/channel
  checks do not establish simulator performance. Never run `./ns3 build` or
  `./ns3 run`; real simulator execution is outside this review's checks.
