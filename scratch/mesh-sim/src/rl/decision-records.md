@page src_rl_decision_records src/rl/decision-records

@brief Opt-in per-episode records of what a centralized policy saw, requested, and got back.

This file records what the policy saw and chose; it does not explain why. No influence or attribution output exists.
Each record pairs one centralized decision's pre-action observation identity and
joint mask with the requested action, its revalidation, and the outcome window that
followed. Recording never changes actions, observations, rewards, `rl_episode.json`
totals, or `steps.jsonl`. Obsolete single-node control is refused.
`outcome.legacy_reward` is the original simulator-computed reward used in
centralized runs; it is independent of the retired control protocol and stays available.

## Files

| File in `episode-NNNN/` | Writer rule |
| --- | --- |
| `policy_decisions_manifest.json` | All identity (episode, settings, schemas, contract, model, coverage, status). Written atomically at open with `status = writing` and again at close. |
| `policy_decisions.jsonl` | Append-only, one compact sorted-key JSON record per line, flushed per line: a `reset` record (decision 0), then one `decision` record per saved decision. |

When recording is on, `rl_episode.json` gains `"decision_records": {"manifest": ..., "file": ...}`;
when off, the key is absent and no file is written.

## Enable

The flags exist on `train.py` and `evaluate.py` (also with `--run-dir`); there is no `run.ini` key.

```bash
.venv/bin/python -m scripts.rl.evaluate --sim-binary <BIN> --run-dir <run> \
  --output-dir <out> --seeds 11 --policies model,hold --decision-records
.venv/bin/python -m scripts.rl.train --sim-binary <BIN> --run-config <run.ini> \
  --output-dir <out> --decision-records --decision-records-every 10 m-ppo
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--decision-records` | off | Opt in. Every other flag requires it. |
| `--decision-records-every N` | `1` | Save decision n when `n % N == 0` or it is terminal; reset is always saved. |
| `--decision-records-max-bytes B` | `67108864` | Per-episode cap on `policy_decisions.jsonl`; `0` = no cap. |
| `--decision-records-obs-vector` | `auto` | `auto` stores the vector only when `steps_ref` is null; `always` stores it on every record. |
| `--decision-records-preferences` | `auto` | `auto` captures preferences on evaluation `model` episodes; `off` never does. |

`settings.source` marks each key `cli` or `default`. `train.py` records training
episodes (`mode training`, `source train`) and callback evaluation episodes
(`mode evaluation`, `source train_eval`, `policy model`, no model identity or preferences).
The cap bounds the optional on-disk file only; it is not a simulator or Python
memory limit, since each record is flushed to disk as it is written.

## Join rules

- Record n's `input` is the state *before* action n: decision n−1's message
  (`input.source_decision == n − 1`). Never place `steps.jsonl` record n's mask beside action n.
- Join on integers: `input.tick == outcome.tick − outcome.ticks_in_step`.
  Compare `time_s` only with a tolerance. The outcome window is `(input.time_s, outcome.time_s]`.
- `input.steps_ref` names `steps.jsonl` record n−1 only when that record was saved;
  otherwise it is null and `input.obs_vector` carries the exact vector. A sampled row is never relabelled.
- Decision 0 has no action or outcome; the terminal observation is never an input.
- Node IDs are strings from `contract_identity.slot_node_ids`; padded slots are `null`.
  `targets` lists every active slot because the action is joint.

## Masks and hashes

`input.mask` is the full joint pre-action mask as integers 0/1. `mask_sha256` is SHA-256
of `json.dumps(mask, separators=(",", ":"))` over those integers; a boolean JSON form gives
a different digest. `obs_sha256` hashes the vector in the observation schema dtype, as in
`steps.jsonl`. `model_input_sha256` hashes the float32 cast the model consumes; the two
coincide only for float32 presets (`model_input.lossless_from_obs`).

## Requested, revalidated, applied

`action.requested` is the joint action Python sent. `revalidated_slots` are the
slot indexes the simulator replaced by hold (`hold_index = 4`). `applied` is
`requested` with 4 at those slots; `applied_status` is always `derived`. An empty
`revalidated_slots` proves `applied == requested` only for `MeshRlEnv` senders.

## Read one node's decision

This is an illustrative model-evaluation example, not an explanation of the
model's reasoning. Suppose `slot_node_ids[0]` is `node-b` and the contract's
action order is west, east, south, north, hold:

| Read | Example | Interpretation |
| --- | --- | --- |
| `input.source_decision`, `input.tick` | `7`, `35` | This is the observation before action 8. Join telemetry decision 7, not 8. |
| Slot 0's five `input.mask` entries | `[1, 0, 1, 1, 1]` | East is unavailable; west, south, north, and hold are allowed. |
| `preferences.masked_probs[0]` | `[0.60, 0.00, 0.10, 0.10, 0.20]` | West ranks highest among allowed moves. These are reconstructed probabilities, not influence scores. |
| `action.requested[0]` | `0` | The deterministic policy requested west for `node-b`. |
| `action.revalidated_slots`, `action.applied[0]` | `[0]`, `4` | The simulator replaced that request with hold. Read revalidation separately from the model's preference. |
| `outcome.tick`, `outcome.ticks_in_step` | `40`, `5` | The outcome covers ticks 36–40 after the request. |

Decode observation features using the pinned observation schema in
`rl_episode.json` or the telemetry header. Follow `input.steps_ref` and verify
its hash; when it is null, use `input.obs_vector`. Inspect telemetry's node
positions and link facts alongside that input and the later outcome. A higher
reward or better link after a move is an observed result; this record does not
establish that the move caused it. If preferences are null, show them as
unavailable, and inspect the manifest's preference error and coverage before
interpreting an absent record.

## Sampling, caps, coverage, status

Records are skipped only at whole-line boundaries. When the next line would exceed a
positive cap, writing stops (`capped`) but decisions are still counted. A positive cap
smaller than the reset line fails the sidecar before writing (`failed`, zero bytes and records, `decision_0_retained false`).

`coverage.records` is the line count; `saved_ranges` and `gaps` partition
`[1, decisions_expected]`; `terminal_decision` is the last decision whose outcome
was seen. With `record_every = 1`, `complete` has no gaps and `capped` has one trailing gap.

| `status` | Meaning |
| --- | --- |
| `writing` | Process still running or died; treat as incomplete. |
| `complete` | Episode reached `done`; every sampled record written. |
| `capped` | The cap stopped writing; records outside `saved_ranges` do not exist. |
| `interrupted` | Episode reset, closed, or failed before `done`; see `episode.status`, `error`. |
| `failed` | The writer itself failed; see `error`. |

## Failure isolation

On any recorder exception the sidecar becomes `failed` with `error`, the file is
closed, the manifest rewritten if possible, one `RuntimeWarning` emitted, and the
recorder dropped. Simulation, the policy, `steps.jsonl`, and `rl_episode.json` continue.

## Model identity

`model` is set only for `evaluate.py` episodes of the `model` policy: `model_sha256`
(the zip file as evaluated), `policy_weights_sha256` (the `policy.pth` zip entry; stable
across re-saves of identical weights), `model_selection`, `model_path_recorded` (relative
to the run directory when inside it), `num_timesteps`, `train_manifest_sha256`, and
`inference` versions. Training and callback episodes have `model = null`.

## Preferences and parity

On evaluation `model` episodes, a forward hook on `policy.action_net` copies the
float32 per-slot outputs computed inside the same `predict` call. Records store
them as `per_slot` (exact float32 values) plus `masked_probs` (softmax over
unmasked entries, masked entries exactly 0, 6 decimal places). The hook adds no
forward pass, RNG draw, or parameter access, so recording on or off yields the
same actions and identical `steps.jsonl` bytes (tests 16–17). Other policies record `preferences: null`.
If the optional copy fails, the hook keeps the inference output untouched,
clears its capture buffer, stops further captures, and stores the error in the
manifest. Earlier rows can have preferences while later rows have null;
`preferences.captured` means at least one row captured them, not that every row
did. Evaluation removes the hook on success or failure.

## Consumer rules

- Locate: `eval_manifest.json` `policies.<name>.episodes[].episode_dir` (or a
  training `episode-NNNN/`) → `policy_decisions_manifest.json`. No file means
  "Decision records not enabled for this episode".
- Identity is episode-relative (`episode.dir_name`, `index`, `seed`) plus `decision`;
  apply the join rules above.
- Render unavailable states: `writing`, `failed`, `interrupted`, `capped` (show `gaps`),
  `record_every > 1` (gaps by design), `steps_ref == null` (use `input.obs_vector`),
  `preferences == null`, `model == null`.
- Influence unavailable: show "Influence unavailable"; no decision-record field carries or implies it.

## Schema versions and consumer checks

The writer emits manifest `version: 2`. Validate it and every JSONL line with
[`docs/schemas/decision_record.v2.schema.json`](../../docs/schemas/decision_record.v2.schema.json)
(Draft 2020-12). JSONL rows inherit the version from their episode manifest.
The frozen schemas and SHA-256 pins are:

| Version | Schema SHA-256 |
| --- | --- |
| Historical v1 | `cbd03e343bcedcccb747db444d37d0ed0d2b0e9a9ed4f55ed07c6fcfa7ca49eb` |
| Current v2 | `2a150730e842974897ddbb4518d2028be210dc200cc66b3890d9235fe7f4be29` |

Keep [`decision_record.v1.schema.json`](../../docs/schemas/decision_record.v1.schema.json)
unchanged for historical records. A consumer chooses the schema by the manifest
version and checks the pinned file digest; unknown versions are unsupported.
Do not overwrite an old schema or silently validate v2 output with v1.

V2 replaces the fixed reward-name tables with numeric `components` and integer
0/1 `valid` maps. Consumers must check that both maps have identical keys and
that these keys match the resolved reward schema in `rl_episode.json`; verify
its SHA-256 against `reward_schema_sha256`. Adding a registered reward component
does not require adding its name to several decision-record tables.

V2 also records `manifest.scoring` (`warmup_s`, `reward_warmup`, `reward_window`)
when those fields are supplied by the validated simulator contract, and
`outcome.scored_ticks` when supplied by its validated outcome. The older bridge
on this review branch supplies neither, so they are null. Null means unknown,
not zero warmup or an unscored window. A zero scored-tick count means that no
time in that window contributed to scoring. `ticks_in_step` still describes
elapsed simulation ticks, including decisions during warmup. Readers check
`0 <= scored_ticks <= ticks_in_step` when the count is available.

### Downstream migration

PR #24 expanded the frozen v1 reward-name tables. When updating that PR, preserve
the historical v1 file and pin from here, use v2 for new records, and remove its
duplicate v1 reward-name additions. Carry the upstream protocol/scoring changes
through the review stack; do not infer scored time from the elapsed window.
Update writer, schema validation, replay/reader expectations, documentation, and
the GUI consumer together. The GUI consumer is outside this repository and must
explicitly adopt the pinned v2 schema before reading these new records.

### Ownership and extension

`env/decision_settings.py` owns recording defaults, allowed settings, provenance,
and validation. `cli_common.py` only exposes flags and delegates resolution.
`env/decisions.py` owns record construction, coverage, and persistence; record
format strings stay there. Action count and hold index come from `env/protocol.py`.
`policy/preferences.py` owns the optional model hook, with no simulator or
record-writer responsibility. Add format changes in a new versioned schema,
writer, consumer guide, and tests together; keep the v1 and v2 pins unchanged.

## Test map

All in `scripts/rl/tests/test_decision_records.py` unless noted; 16, 17, and 20 need `sb3_contrib`.

| Tests | Protects |
| --- | --- |
| 1 `test_settings_resolution_and_dependent_flags`, 22 `test_cli_dependent_flag_without_enable_exits_one` | Defaults, `cli`/`default` sources, rejection of bad values and dependent flags without opt-in. |
| 2 `test_disabled_by_default_writes_nothing` | Disabled runs write no sidecar, no `decision_records` key, identical `steps.jsonl`. |
| 3 `test_records_join_previous_step_at_every_one` | n−1 join, integer tick rule, coverage, file hash, `complete`. |
| 4 `test_sampled_steps_are_never_relabelled`, 5 `test_no_telemetry_stores_exact_vector`, 6 `test_obs_vector_always` | `steps_ref` only for saved rows; exact vector otherwise or on request. |
| 7 `test_float32_preset_hashes_coincide`, 8 `test_requested_revalidated_applied`, 9 `test_mask_hash_is_over_int_json` | Observation versus model-input hashes; requested/revalidated/applied; integer mask hash. |
| 10 `test_cap_stops_at_record_boundary`, 11 `test_record_every_two_partition`, 12 `test_zero_cap_means_no_cap`, 12a `test_cap_smaller_than_reset` | Cap boundary, sampling partition, unlimited cap, sub-reset cap failure. |
| 13 `test_writer_failure_is_isolated`, 14 `test_interrupted_episode_status` | Failure isolation and `interrupted` status. |
| 15 `test_string_ids_and_null_padding`, 20 `test_training_context_records`, 21 `test_legacy_mode_is_refused` | String IDs with `null` padding; training/callback labelling; legacy refusal. |
| 16 `test_model_evaluation_records_preferences_and_identity`, 17 `test_capture_on_off_parity` | Model identity, preference capture, on/off action and trace parity. |
| 18 `test_schema_well_formed_and_documents_validate`, `test_schema_matches_jsonschema_when_installed`, 19 `test_schema_v1_is_frozen` | Produced documents validate; independent Draft 2020-12 checks when installed; historical schema stays pinned. |
| `test_failed_preference_copy_keeps_actions_and_telemetry`, `test_evaluation_failure_removes_preference_hook` | Copy failure before/after the first capture preserves actions and telemetry, reports unavailable preferences, and removes the hook; cleanup also runs on evaluation failure. |
| `test_decision_record_contract.py` | Archived v1 documents/pin, v2 pin and extensible typed reward maps, explicit unavailable/zero/partial/full scored ticks; independent schema checks when installed. |
| `test_real_binary.py`: `test_decision_records_join_real_steps` | n−1 join and revalidation on the real bridge; skips without `MESH_SIM_BIN`. |

## TODO

Recording is CLI-only. A future `run.ini` control for on/off and size must decide
how it interacts with `run_ini_sha256` scenario identity before `source` gains a `run.ini` value.
