# Changing mesh-sim safely

Start with the [main README](README.md) for setup and the
[RL bridge contract](src/rl/README.md) for centralized control. Keep generated
outputs, trained models, large regression snapshots, and local virtual
environments out of Git. Add a focused test only when it checks behavior the
existing tests do not cover; the [RL test map](scripts/rl/tests/README.md)
shows the current coverage and inputs/outputs.

Before changing a user-visible behavior, check the affected layers:

| Change | Update together |
| --- | --- |
| `run.ini` or CLI option | Loader, resolution/validation, [documented options](README.md#centralized-multi-node-control), example, and one valid/invalid configuration check. |
| RL action, observation, mask, cadence, or reward semantics | C++ bridge and simulator loop, Python protocol/environment, [contract](src/rl/README.md), focused fake-simulator and real-binary checks. |
| Training or episode output | Writer, any reader, [output layout](README.md#where-output-lands), and a test of the changed fields. |
| Channel query wire (`mesh_channel_query_v1`) | `src/query/channel-query.cc`, `scripts/baselines/planners/channel.py`, the fake worker `scripts/baselines/tests/fake_query.py`, the [contract](src/query/README.md), and the CLI integration query tests. Rename the contract for incompatible changes. |
| Placement baseline manifest, plan, or fingerprint | `scripts/baselines/artifacts.py` (`MANIFEST_VERSION`, `PLAN_VERSION`, `fingerprint`, `eval_metadata`), the adapter that fills them, the reader `scripts/rl/policy/compare.py` (groups by `baseline.fingerprint`), the [outputs description](scripts/baselines/README.md#outputs), and `scripts/baselines/tests`. |
| Scenario identity | `read_scenario_identity` in `scripts/rl/env/config.py`, saved training manifest, relevant tests, and the [identity description](src/rl/README.md#saved-scenario-identity). |

The C++/Python `contract` name (`mesh_move_2d_v1`) describes the wire and
action meaning. Change it for incompatible protocol semantics or layout, not
for a refactor that preserves behavior. A saved JSON `manifest_version`
describes a file's schema: increment the *relevant* version when fields or
their meanings change, then update writers, readers, examples, and tests.
Currently `train_manifest.json` uses version 4;
`rl_episode.json` uses version 1 for legacy control, version 2 for
centralized control, and version 3 once the policy selection and schema
digests are recorded; `eval_manifest.json` uses version 2 and
`comparison.json` version 1; `baseline_manifest.json` and `baseline-plan.json` use
version 2 (the `baseline` block in `eval_manifest.json` carries
`baseline_manifest_version`, while `eval_manifest_version` stays 2). Versions do not increment for each run. The SHA-256
fields in `scenario_identity` are file fingerprints, not schema versions;
change them only by changing the corresponding input files or the identity
definition.

For a protocol or simulator change, run the small Python contract suite,
the C++ configuration tests, and the real-binary integration checks listed
in the [test map](scripts/rl/tests/README.md) against a fresh build. Record
any known platform limitation; matching results on one platform do not prove
cross-platform bit-for-bit equality.
