# scripts/baselines

Read [README.md](README.md) for the versioned configuration example, source
coordinate/objective explanations, and active-planner extension steps.

- Keep CLIs to argument parsing and delegation. Do not put configuration,
  schema, node-authority, or planner search logic in them.
- `config.py` owns INI/options validation; `mapping.py` owns mapping/geofence
  validation. Keep defaults and accepted values beside their owner.
- `effective_inputs.py` owns snapshots and effective scenario rewriting.
  `artifacts.py` owns baseline schemas, transitions, and fingerprint fields.
- Reuse `scripts/artifact_io.py` for generic JSON I/O, hashes, and timestamps.
  It uses only the standard library; baselines must not import RL CLI helpers.
- Keep planner mechanics and settings in their method module, and plan
  authority checks in the adapter when it is introduced downstream.
- Preserve all nine pinned `third_party/arpo_placement` source files. Put
  explanations in documentation and runtime adaptations outside that tree.
- Mapping version 1/RF integration in this review is replaced downstream by
  PRs #25/#26. Consult the active contract before changing or extending it.
- Tests write to temporary directories. Parsing and fake-planner/channel
  checks do not establish simulator performance. Never run `./ns3 build` or
  `./ns3 run`; real simulator execution is outside this review's checks.
