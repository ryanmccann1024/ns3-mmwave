@page Contributing Contributing

Start with the [main README](@ref index) for setup and the
[RL bridge contract](@ref src_rl) for centralized control. Keep generated
outputs, trained models, large regression snapshots, and local virtual
environments out of Git. Add a focused test only when it checks behavior the
existing tests do not cover; the [RL test map](@ref scripts_rl_tests)
shows the current coverage and inputs/outputs.

Before changing a user-visible behavior, check the affected layers:

| Change | Update together |
| --- | --- |
| `run.ini` or CLI option | Loader, resolution/validation, [documented options](README.md#centralized-multi-node-control), example, and one valid/invalid configuration check. |
| RL action, observation, mask, cadence, or reward semantics | C++ bridge and simulator loop, Python protocol/environment, [contract](src/rl/README.md), focused fake-simulator and real-binary checks. |
| Placement engine or query contract | Component/strategy owners, settings/hash, C++ query owners, client/fake worker, [engine workflow](scripts/baselines/planners/README.md), query units and real-binary checks. |
| Placement seeds, penalties or provenance | INI/CLI owner, preparation and seed-role preflight, runtime identity, baseline artifacts, examples, and a fake-worker check. |
| Comparison metrics | `policy/metrics.py` registry, evaluation writer, comparison JSON/CSV, schema versions, tests and fetch include rules. Keep initial relocation separate from scored travel. |
| Training or episode output | Writer, any reader, [output layout](README.md#where-output-lands), and a test of the changed fields. |
| Scenario identity | `read_scenario_identity` in `scripts/rl/env/config.py`, saved training manifest, relevant tests, and the [identity description](src/rl/README.md#saved-scenario-identity). |

The C++/Python `contract` name (`mesh_move_2d_v2`) describes the wire and
action meaning. Change it for incompatible protocol semantics or layout, not
for a refactor that preserves behavior. A saved JSON `manifest_version`
describes a file's schema: increment the *relevant* version when fields or
their meanings change, then update writers, readers, examples, and tests.
Currently `train_manifest.json` uses version 7;
`rl_episode.json` uses version 6, including scored tick counts and a consistent
pre-handshake failure schema. `eval_manifest.json` uses version 6 for scored
metrics, initial relocation and planning seed roles; comparison JSON uses
version 2 and validates the evaluation version and scoring metadata. Baseline
manifest/plan and plan fingerprints use version 3; mapping JSON uses version 2.
Existing outputs must be regenerated rather than relabeled. Telemetry uses version 3
for resolved input parameters and movement-context inputs; experiment plans use
version 2 for resolved parameter identities. Versions do not
increment for each run. The SHA-256
fields in `scenario_identity` are file fingerprints, not schema versions;
change them only by changing the corresponding input files or the identity
definition.

For a protocol or simulator change, run the small Python contract suite,
the C++ configuration tests, and the real-binary integration checks listed
in the [test map](@ref scripts_rl_tests) against a fresh build. Record
any known platform limitation; matching results on one platform do not prove
cross-platform bit-for-bit equality.

Keep CLI modules to parsing and delegation. Configuration belongs beside its
domain owner; preparation, child lifecycle, artifacts, and runtime provenance
have separate owners. Use the shared artifact I/O implementation instead of
copying helpers into scripts. New planner modules must enter the automatic
code identity; test Python defaults against the actual C++ configuration loader.
Keep optimizer, channel-planning, training, selection and evaluation seeds
separate. An explicit overlap override marks diagnostics, not held-out results.
See the [placement walkthrough](scripts/baselines/walkthrough.md) for the full
zero-cost/penalized workflow and the limits of planner predictions.

Training version 7 records all PPO settings and the full validation seed set. Episode version 6 adds optional jammer-motion metadata and configurable progress persistence. Evaluation version 6 adds optional coverage, service, safety and delayed-jammer metrics; unavailable optional measurements remain null and are omitted from paired comparisons.
