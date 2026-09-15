# P0 Baseline Scout Report

All paths are relative to `scratch/mesh-sim/` unless marked `(repo root)`. This was a read-only scout: nothing was built, run, or tested. Findings marked **Confirmed** come from reading the code. Findings marked **Suspected** or **Not verified** have not been executed. The user moved the completed report into `docs/rl-program/p0-baseline/` so subsequent phase artifacts have durable, descriptive names.

## 1. Repository Snapshot

| Item | Value | Source |
| --- | --- | --- |
| Branch | `arpo-main` | Read-only `git branch --show-current` verification during report review |
| HEAD | `a4e700d9` "Merge pull request #4 from CharlamadaV2/baseline_validation" | Read-only `git rev-parse HEAD` and `git log -1 --oneline` verification |
| Remote defaults | `origin/HEAD -> origin/new-handover`; `fork/HEAD -> fork/arpo-main` | Read-only `git symbolic-ref` verification |
| Workflow PR base | The current untracked workflow explicitly targets `arpo-main` on the user's fork | `docs/claude/GIT_PR_PROMPT.md:17-19` |
| Current uncommitted paths | `M CLAUDE.md`; untracked `docs/ORCHESTRATION.md`, `docs/claude/`, and `docs/rl-program/p0-baseline/` (this report) | Read-only `git status --short` verification, updated after the user-approved move |
| Phase artifact directory | `docs/rl-program/p0-baseline/` with descriptive filenames; neither `feature-research/` nor `review-research/` is the intended P0 destination | User decision after Scout review |

## 2. Applicable Instructions and Execution Boundaries

- Instructions read: `CLAUDE.md` and the `CLAUDE.md` files in `src/rl`, `src/cli`, `src/eval`, `src/config`, `src/setup`, `src/io`, `tests`, and `inputs`. During report review, every file under `docs/claude/` and `docs/ORCHESTRATION.md` was also read in full.
- `CLAUDE.md` forbids running `./ns3 build` or `./ns3 run`; the user runs builds. It also requires any new source file to be added to `CMakeLists.txt`.
- Architecture rule: `setup/` is the only layer that creates ns-3 objects, and `config/` must contain no ns-3 headers (`CLAUDE.md` Architecture section).
- The external Scout execution rule originally allowed only `feature-research/<task>/scout.md`; the Scout therefore wrote there before the user moved the completed report.
- **Artifact path decision and remaining template conflict:**
  - `CLAUDE.md` ("Manual review workflow") and `docs/claude/README.md:9-20` put every artifact under `review-research/mesh-sim-handoff-review/`.
  - The repository's own Scout template also requires `review-research/<task>/scout.md` (`docs/claude/SCOUT_PROMPT.md:15-17, 42-49`), and every later role template uses the same directory.
  - The user has now selected `docs/rl-program/p0-baseline/` and descriptive filenames for P0 artifacts. Later phases receive their own descriptive subdirectories. The one-time P0 Planner handoff is supplied directly in chat; the repository role templates still require alignment before reuse. An external role whose runtime rules prohibit the selected path must stop rather than silently writing somewhere else.
  - `CLAUDE.md` links the review scope as `docs/review-research/README.md`, and `docs/ORCHESTRATION.md:16` links it as `review-research/README.md`. Neither file exists.

## 3. Build and Dependency Setup

| Topic | Finding | Evidence |
| --- | --- | --- |
| ns-3 build commands | Run from the repo root: `./ns3 clean`, `./ns3 configure --build-profile=debug -- -DCMAKE_OSX_ARCHITECTURES=arm64`, `./ns3 build` | `README.md:9-13` |
| Run command | `./ns3 run scratch/mesh-sim/sim -- --run-config=... --band=sub-6 --seeds=... --output-dir=...` | `README.md:28` |
| CMake target | `scratch_mesh-sim_sim`, built by a hand-written add_executable with an explicit source list | `CMakeLists.txt:10-30, 54` |
| mesh-sim wrapper around `./ns3` | None exists. The sweep runner looks up the binary itself and sets `DYLD_LIBRARY_PATH`/`LD_LIBRARY_PATH` to `build/lib` | `scripts/sweep/runner.py:101-107, 233-237` |
| Library path in the RL env | `MeshRlEnv` does **not** set `DYLD_LIBRARY_PATH` | `scripts/rl/env/mesh_env.py:80-87` |
| Python environment setup | No one-command setup was found. There is no `pyproject.toml`, `requirements*.txt`, lock file, `setup.py`, `environment.yml`, or `.python-version` in mesh-sim | Glob returned no files |
| Python version implied | 3.10 or newer, because the code uses `X \| None` type hints and `match` statements | `scripts/rl/env/mesh_env.py:30`; `scripts/validation/build_config_files.py:605` |
| RL dependencies implied | `gymnasium`, `numpy`, `sb3_contrib` (MaskablePPO, which brings in `stable_baselines3` and `torch`) | `scripts/rl/env/mesh_env.py:7-9`; `scripts/rl/agents/mask_ppo.py:6-9` |
| Analysis dependencies implied | `pandas`, `matplotlib`, `numpy` | `scripts/plotting/*.py`, `scripts/validation/*.py` |
| Optuna | No imports found | grep of `scripts/` |
| Version pins | None documented | Not found |

## 4. Existing Test Map

| Suite | Location | Command | Notes |
| --- | --- | --- | --- |
| Unit: config | `tests/unit/config/config-validator-test.cc` | `cd tests && make test` | Compiles `config-validator.cc`, `config-loader.cc`, and util sources without ns-3 (`tests/unit/config/Makefile:5-21`) |
| Unit: eval | `tests/unit/eval/eval-test.cc` | same | Covers SinrToCapacity and LinkTable |
| Unit: routing | `tests/unit/routing/mesh-router-test.cc` | same | |
| Unit: traffic | `tests/unit/traffic/traffic-matrix-test.cc` | same | Uses an ns-3 stub |
| Lint | clang-tidy over the standalone sources | `make lint` (`make test` runs it first) | Silently skipped if clang-tidy is missing; `|| true` means lint never fails the run (`tests/Makefile:41-54`) |
| CLI integration (real binary) | `tests/integration/cli-integration-test.sh` | `cd tests && make integration`, or run the script with the binary path | It intends to auto-detect `ns3.42-sim-debug` and similar names, but its root calculation is wrong; pass the binary explicitly until repaired (`:15-33`) |
| Simulator-backed RL, jammer, or band tests | None found | | |

- **Confirmed path defects in the integration test:** `MESH_SIM_DIR` resolves to `scratch/mesh-sim/tests/`, not the mesh-sim root, and `REPO_ROOT` consequently resolves to `scratch/`, not the ns3-mmwave root (`tests/integration/cli-integration-test.sh:15, 21-33`). Auto-detection therefore searches the wrong build tree. Tests 4-6 then resolve their fixture references under nonexistent `tests/inputs/scenarios/triangle/` (`:44, 79, 87, 105`).
  - Test 6 should fail, because loading `nodes_file` fails.
  - Tests 4 and 5 pass for the wrong reason: the missing config file causes the exit, not the bad seed or the bad positions file.
  - `tests/CLAUDE.md:25-26` correctly places the script under `tests/integration/`, while the script's usage line incorrectly says `./tests/cli-integration-test.sh` (`:6`).
- **The "two configuration-test failures" from earlier reports:** no logs or artifacts were found. Not verified.
- **Coverage gaps:** the jammer model, the `--band` gating, the RL bridge (reward, action, clamping), the Python env, and the train CLI have no tests (grep of `tests/` for jammer/band/sub-6 found only bandwidth checks).

## 5. Current RL End-to-End Path

| Step | Behavior | Evidence |
| --- | --- | --- |
| Config parsing | The `[rl]` keys are read, with defaults `reward_type=throughput`, `step_size_m=50`, `z_min=0`, and `z_max=100` | `src/config/config-loader.cc:302-312`; `src/domain/sim-config.h:67-86` |
| Validation | Checks `action_type`, `reward_type ∈ {throughput, mean_sinr}`, x/y bounds, and that the controlled node ID exists. **z_min < z_max is not checked** | `src/config/config-validator.cc:199-238` |
| Gym registration | `register(id="mesh_sim/MeshEnv-v0", entry_point="mesh_sim.scripts.rl.env.mesh_env:MeshEnv")`. The class is actually named `MeshRlEnv`, and `mesh_sim` is not an importable package (the directory is `mesh-sim`). `gym.make` will fail. train.py never calls `gym.make`, so this path is unused | `scripts/rl/__init__.py:3-6`; `scripts/rl/env/mesh_env.py:12` |
| Env construction | `MeshRlEnv(sim_binary, run_config, seed, output_dir)`; spaces are set on the first reset | `scripts/rl/env/mesh_env.py:30-53` |
| Subprocess launch | `[bin, --run-config, --rl-mode, --seed?, --output-dir?]`. **No `--band`**. stderr goes to `<out>/sim_stderr.log` or `/dev/null` | `mesh_env.py:66-87` |
| Diagnostics | If stdout closes, the only error is "exit code N". stderr is not tailed. A JSON parse error is not caught | `mesh_env.py:187-194` |
| C++ step message | Every tick sends `{type, tick, time_s, obs{controlled_pos[x,y,z], link_sinrs, link_capacities}, reward, done, action_type}`. The first message (tick 0) is the reset observation | `src/rl/rl-bridge.cc:65-101`; `sim.cc:244-252` |
| Observation | A flat vector `[x, y, z, sinr_j, cap_j, ...]` for every other node j. The docstring wrongly says `[ctrl_x, ctrl_y, ...]`. Length is 3 + 2(N−1), fixed at the first reset | `mesh_env.py:211-223, 99-103` |
| Action space | Discrete(7): `0:-X 1:+X 2:-Y 3:+Y 4:-Z 5:+Z 6:Stay`. The continuous Box has shape (2,), while C++ accepts an optional third element | `mesh_env.py:105-111`; `rl-bridge.cc:125-136, 184-207` |
| Action validation | A bad JSON line or closed stdin sets action 0 (**−X**), although the comment says "stay". Out-of-range integers fall through to Stay. A missing or short continuous array is not guarded | `rl-bridge.cc:111-123, 204-206, 127-131` |
| Action masking | Python reads bounds from `[rl]` using **its own defaults** (0-500, −250-250), which differ from the C++ defaults (−1000-2000, −1000-1000). Z moves are masked only if z bounds are in the ini, but C++ always clamps z to [0, 100] | `mesh_env.py:249-263` vs `src/domain/sim-config.h:81-86`; `rl-bridge.cc:211-213` |
| Controlled node | Defaults to the last node, N−1; an unmatched ID silently falls back to that default (the validator catches it earlier). Jammers live in a separate mobility vector, so they cannot be selected | `sim.cc:170-185, 146-147`; `src/setup/topology-builder.cc:140-187` |
| Movement | Applied through `ConstantVelocityMobilityModel::SetVelocity`. **No-op if the node uses another mobility model** (no error). Speed = min(dist/tick, MaxSpeedForType): drone 20, vehicle 15, pedestrian 1.5 m/s | `rl-bridge.cc:231-244`; `src/domain/node-spec.h:113-117` |
| Decision timing | One decision per tick, and the velocity holds for exactly one `tick_s`. In `rl-test` (tick 0.1 s, step 25 m, drone), the node moves at most 2 m per decision, not 25 m | `sim.cc:195-252`; `inputs/baselines/rl-test/run.ini:7,34` |
| Reward | See section 7 | `rl-bridge.cc:28-59` |
| Shutdown | `done` is true on the last tick; C++ skips reading and exits; Python waits 10 s, then kills. `reset()` kills any running process | `sim.cc:246`; `mesh_env.py:126-127, 226-246` |
| Output directory | train.py uses `outputs/YYYY-MM/DD/HH-MM-SS` relative to the **working directory** with `exist_ok=True`. Every episode reuses the same `--output-dir` and seed, so `seed-<N>/`, `run.log`, `inputs/`, and `sim_stderr.log` (opened with `"w"`) are overwritten on each reset | `scripts/rl/train.py:27-35`; `mesh_env.py:73-79`; `sim.cc:99-121` |
| Seed propagation | `env.reset(seed=cfg.seed)` sets `self._seed`, and later resets reuse it, so every episode runs the same ns-3 seed | `train.py:42`; `mesh_env.py:61-62, 71-72` |
| Training entry point | `train.py`: MaskablePPO via `ActionMasker`. Top-level options (`--sim-binary`, `--run-config`, `--output-dir`, `--verbose`) must come **before** `m-ppo`; `--seed` and the PPO options must come after it. The docstring usage puts `m-ppo` first, which argparse rejects. The docstring paths assume the repo root, but `-m scripts.rl.train` only imports from `scratch/mesh-sim` | `train.py:6-9, 52-75` |
| Model save/load | Saves `<out>/maskable_ppo_mesh(.zip)`. No load or eval path exists. `q_learning.py` exists but is not wired into train.py | `train.py:46`; `scripts/rl/agents/mask_ppo.py:48-49` |
| 2D/3D | Mixed: position, discrete actions, and clamping are 3D; the continuous Box is 2D; `TODO.md:22-25` still describes RL as x/y only | as cited |

## 6. Radio-Band Data Flow

In plain terms: the band exists **only as a CLI flag**. No scenario file contains it, and it never reaches the loaded `SimConfig`.

| Stage | Status | Evidence |
| --- | --- | --- |
| `run.ini` | Absent; no `band` key is parsed | grep of `src/config/config-loader.cc` |
| CLI | `--band`, default `"mmwave"`; only `mmwave` or `sub-6` are accepted | `src/cli/cli-parser.h:53`; `src/cli/cli-parser.cc:50-53, 70-75` |
| Validator | Not involved | `src/config/config-validator.cc` |
| Forwarded to | `LinkEvaluator::Configure(..., args.band, ...)`, which sets `m_computeInterference = (band == "sub-6")` | `sim.cc:152`; `src/eval/link-evaluator.cc:63` |
| Direct launch | The README example passes `--band=sub-6` | `README.md:28` |
| RL launch | **Omitted** | `scripts/rl/env/mesh_env.py:66-74` |
| Sweep launch | **Omitted** | `scripts/sweep/runner.py:228-229` |
| Validation batch | **Omitted** | `scripts/validation/run_batch.py:104-109` |
| Config generator | `build_config_files.py --band` is required, but it only reaches a print statement and a mode check; it is not written to `run.ini` | `scripts/validation/build_config_files.py:425, 506-508, 605-618` |
| Archive and logs | `run.log` records seeds, run-id, and positions override but **not `--band`**. Its comment says every `CliArgs` field is recorded, yet `output_dir`, `debug_links`, `rl_mode`, and `band` are also omitted. Archived inputs contain no band because the scenario contains none | `src/io/run-logger.h:101-130`; `src/cli/cli-parser.cc:117-132` |
| Evidence available after a run | Only indirect: sweep and batch logs record their full `Command:` (`runner.py:239`, `run_batch.py:112`), but those commands currently omit band and therefore document use of the default `mmwave`, not an explicit selection. A direct launch leaves no durable band record; clipped SINR in `links.csv` is suggestive but not sufficient provenance | as cited |

## 7. Reward Audit

**Claim confirmed.** Code at `src/rl/rl-bridge.cc:33-50`:

- **Inputs:** only `linkTable.Get(controlled, j).is_los`. Mobility models and flows are ignored for this reward type, and SINR is never read.
- **Links considered:** every link from the controlled node to each other node j (j ≠ controlled) across all N nodes. Jammers are not in the node list.
- **Calculation:** `(count > 0 && losCount == count) ? 1.0 : -1.0`.
- **Empty case:** with N = 1, `count` is 0, so the reward is −1. Disconnected but LOS links still earn +1.
- **The name does not match the calculation.** The output is an all-links-LOS indicator in {+1, −1}.
- **Other reward:** the default `throughput` returns the sum of `delivered_mbps` over all flows (`rl-bridge.cc:52-58`).
- **Configuration:** the loader default is `throughput` (`config-loader.cc:304`), the validator allows only `{throughput, mean_sinr}` (`config-validator.cc:203-204`), and `rl-test` uses `mean_sinr` (`inputs/baselines/rl-test/run.ini:33`).
- **Documentation mismatch:** `src/domain/sim-config.h:59-72` documents a reward table. Not verified whether it describes `mean_sinr` accurately.

## 8. Jamming Audit

| Aspect | Confirmed behavior | Evidence |
| --- | --- | --- |
| Source | `[scenario] jammers_file` is a JSON array parsed into `JammerSpec`. Defaults: `enabled=false`, `type=constant`, 25 dBm, 12 dBi, `duty=1`, `range=0` (unlimited), `beamwidth=360`, `az=0`, `zen=0` | `src/config/config-loader.cc:89-133, 332-346` |
| Band gating | Jammer power is added only when `band == "sub-6"` and at least one jammer is enabled | `src/eval/link-evaluator.cc:63, 166-171` |
| Frequency match | An empty `target_freq` matches everything. One entry matches within ±2.5 MHz of the carrier. Two or more entries are treated as a [min, max] range. The carrier comes from `channel.frequency_ghz` | `src/jammer/jammer-model.cc:100-114`; `link-evaluator.cc:86` |
| Bandwidth/overlap | Not modeled: the gate is a pass/fail check on the carrier only, and power is not scaled by overlap | `jammer-model.cc:100-114, 229-244` |
| Range | Skipped when `max_range_m > 0` and distance exceeds it | `jammer-model.cc:216-219` |
| Beam direction | 3D cone from azimuth (from North) and zenith (0 = up), half-angle = beamwidth/2; ≥360 means omnidirectional. The zenith default of 0 points straight up, so a directional jammer with defaults misses ground receivers | `jammer-model.cc:123-152`; `config-loader.cc:103` |
| Receiver antenna | The receiver array gain is not applied to jammer power but is applied to the signal | `link-evaluator.cc:116, 154`; `jammer-model.cc:229-237` |
| Time | `intervals` gate the jammer; an empty list means always on | `jammer-model.cc:75-90` |
| Duty-cycle modes | `constant`: power × duty. `random`: on or off per whole second, from a hash of (id, seed, floor(t)) compared with duty | `jammer-model.cc:162-178, 240-243` |
| Seed/repeatability | Uses `cfg.seed`, which is updated per seed before Configure, so results are deterministic per (id, seed, second) | `sim.cc:120, 152`; `link-evaluator.cc:86` |
| Multiple jammers | Linear power sum in watts | `jammer-model.cc:189-251` |
| Link ownership | Evaluated once per undirected pair, using `max(jam at rx, jam at tx)` | `link-evaluator.cc:165-171, 204-219` |
| SINR | When jammer power > 0: `10log10(S/(N+J))`, **then clipped to at least 0 dB**. Without jamming, SNR is not clipped | `link-evaluator.cc:175-183` |
| Threshold | `SINR_MIN_DB = -6.7`; `ConnectedLinkCount` and `IsConnected` default to −6.7 | `src/eval/sinr-capacity.h:46`; `src/eval/link-table.h:87, 99` |
| Capacity | Taken from the clipped SINR | `link-evaluator.cc:184-185` |
| Jammer mobility | Waypoints, then constant velocity, then stationary. **`random_walk` is parsed but never installed.** The validator requires random_walk bounds when `type=="random"`, which mixes up the random burst mode with random-walk movement | `topology-builder.cc:153-184`; `config-loader.cc:121-133`; `config-validator.cc:278-284` |
| Logged evidence | Debug log lines only (`JammerModel` and `LinkEvaluator` log components). run.log and summary.json contain nothing about jammers | `jammer-model.cc:246-248`; `src/io/run-logger.h` |
| Tests | None | grep of `tests/` |

Earlier observations checked against the code:

| Observation | Verdict |
| --- | --- |
| Jammed SINR is clipped to 0 dB | **Confirmed** (`link-evaluator.cc:181`) |
| The disconnection threshold is about −6.7 dB | **Confirmed** (`sinr-capacity.h:46`; `link-table.h:87, 99`) |
| Clipping prevents jamming from disconnecting a link | **Confirmed.** Worse, an already-weak link (SNR < 0) that gets jammed is *raised* to 0 dB, which improves its SINR and capacity (`link-evaluator.cc:175-183`) |
| Jamming activates only with `--band=sub-6` | **Confirmed** (`link-evaluator.cc:63, 166`) |
| Some launchers omit the band | **Confirmed:** RL, sweep, and validation `run_batch` (section 6) |
| Jammer random-walk values are parsed but not applied | **Confirmed** (`topology-builder.cc:153-184`) |

## 9. Claude Pipeline and Missing Tester Handoff

- **Order** (`docs/claude/README.md:9-22`): Scout (`scout.md`), then the human condenses it, Planner (`plan.md`), human/Codex approval, Implementer (edits plus `audit.md`), Reviewer (PASS/FAIL), loop back on failure, Progress (`progress.md`), Git/PR (branch, commits, PR into `arpo-main`), and finally the human merges.

| Artifact | Written by | Evidence |
| --- | --- | --- |
| `scout.md` | Scout | `docs/claude/README.md:9-10` |
| `plan.md` | Planner | `docs/claude/README.md:13` |
| `audit.md` | Implementer | `docs/claude/IMPLEMENTER_PROMPT.md:14-16, 33-35` |
| Verdict | Reviewer, as a **chat reply only** with no file | `docs/claude/REVIEWER_PROMPT.md:34-36` |
| `progress.md` | Progress, from the plan, the audit, and a **pasted** verdict | `docs/claude/PROGRESS_PROMPT.md:15-22` |

- **Tester role:** there is no Tester template. The Implementer runs the plan's verification matrix (`IMPLEMENTER_PROMPT.md:24-26`). The Reviewer runs no checks (`REVIEWER_PROMPT.md:17-18`), and Git/PR runs "approved pre-PR gates" (`GIT_PR_PROMPT.md:33-34`).
- **Scope:** the whole workflow is limited to documentation. Every template hardcodes `<task>` = `mesh-sim-handoff-review` and limits source edits to comments (`docs/claude/README.md:24-27, 51-52`). P0 involves runtime changes, which these templates do not authorize.
- **Model-routing conflict:** the current untracked workflow recommends Fable for both Planner and Implementer (`docs/claude/PLANNER_PROMPT.md:3-6`; `IMPLEMENTER_PROMPT.md:3-6`; `docs/claude/README.md:33-36`). The P0 program decision permits Fable for planning only and requires a non-Fable implementation/testing model, so these templates cannot be reused unchanged.
- **Planner limitation:** the repository Planner template excludes behavior changes and authorizes exactly one documentation plan under `review-research/` (`docs/claude/PLANNER_PROMPT.md:15-24, 39-50`). The one-time P0 implementation brief and condensed Scout findings must therefore be supplied directly in chat rather than stored as another prompt artifact.
- **PR requirements:** local `arpo-main` must equal `fork/arpo-main`, only the audit's file list may be staged explicitly, gates are reported honestly, the PR is non-draft, and the human merges (`GIT_PR_PROMPT.md:24-38`).
- **Files a Planner would need for a reviewer/tester evidence loop:**
  - `docs/claude/README.md`
  - `docs/claude/SCOUT_PROMPT.md`
  - `docs/claude/PLANNER_PROMPT.md`
  - `docs/claude/IMPLEMENTER_PROMPT.md`
  - `docs/claude/REVIEWER_PROMPT.md`
  - `docs/claude/PROGRESS_PROMPT.md`
  - `docs/claude/GIT_PR_PROMPT.md`
  - `docs/ORCHESTRATION.md`
  - `CLAUDE.md` (Manual review workflow section)
- **Scout limitation:** the current Scout prompt is likewise scoped to a single documentation review and recommends only documentation changes (`docs/claude/SCOUT_PROMPT.md:13-38`). Its `review-research/` destination conflicted with the external `feature-research/` restriction used during the Scout run; the user subsequently standardized the completed artifact under `docs/rl-program/p0-baseline/`.

## 10. Confirmed Blockers

1. Jammer SINR clipping to 0 dB means jamming can never disconnect a link and can improve weak links (`src/eval/link-evaluator.cc:181`).
2. The RL, sweep, and validation launchers do not pass `--band`, so jammers are silently inactive (`mesh_env.py:66-74`, `runner.py:228-229`, `run_batch.py:104-109`). The band is also not recorded in `run.log` (`run-logger.h:102-111`).
3. The `mean_sinr` reward is an all-links-LOS ±1 indicator (`rl-bridge.cc:33-50`).
4. RL output directories are overwritten on every episode, and every episode uses the same seed (`train.py:27-35`; `mesh_env.py:61-79`).
5. The train.py usage in its docstring is invalid for argparse's subcommand ordering (`train.py:6-9, 52-75`).
6. Gym registration points to a module and class that do not exist (`scripts/rl/__init__.py:5`).
7. There is no Python dependency manifest or setup command (section 3).
8. The integration test computes both its mesh-sim and repository roots incorrectly, then depends on missing `tests/inputs/scenarios/triangle/` fixtures (`tests/integration/cli-integration-test.sh:15-33, 44, 79-105`).

Important but not blocking:

- Malformed or closed action input defaults to −X instead of Stay (`rl-bridge.cc:114, 121`).
- Python and C++ use different bound defaults, and z is not validated (`mesh_env.py:258-263`; `sim-config.h:81-86`; `config-validator.cc:215-218`).
- RL movement silently does nothing unless the controlled node uses `constant_velocity` (`rl-bridge.cc:240-244`).
- The effective move per decision is limited by speed × tick, not `step_size_m` (`rl-bridge.cc:234`).
- Subprocess error messages are weak, and `DYLD_LIBRARY_PATH` is not set for the RL env (`mesh_env.py:187-194`).
- Jammer `random_walk` parsing is dead code, and the validator ties it to `type=random` (`config-validator.cc:278-284`).
- The receiver antenna gain is not applied to jammer power (section 8).
- The repository workflow templates still use the older documentation-only `review-research/` convention (section 9); the one-time P0 Planner handoff must override that scope explicitly in chat.

## 11. Claims Requiring Reproduction

- The two earlier-reported configuration unit-test failures: no evidence was found. Run `cd tests && make test`.
- Integration test 6 fails, and tests 4 and 5 pass for the wrong reason.
- `python -m scripts.rl.train m-ppo --sim-binary ...` is rejected by argparse.
- `gymnasium.make("mesh_sim/MeshEnv-v0")` raises on import.
- The sim binary launched by `MeshRlEnv` finds its ns-3 shared libraries without `DYLD_LIBRARY_PATH` (or fails without it).
- In a `--band=sub-6` run with an active jammer, `links.csv` shows SINR at a floor of 0 dB; without `--band`, the same run shows no jammer effect.
- Episodes in the RL env are identical across resets, and output files are overwritten.
- The ns-3 logs and progress output go to stderr and never corrupt the stdout JSON stream. The code suggests this (`src/io/CLAUDE.md` says progress goes to stderr, and the only `std::cout` is at `rl-bridge.cc:100`), but it is not verified at runtime.

## 12. Jammer Developer Responses and Remaining TODOs

The jammer developer supplied the following intent after the read-only audit. A response marked “probably,” “I believe,” or “ask Kyle” is useful direction but not a frozen scientific contract.

| Topic | Developer response | Comparison with current code | P0 disposition |
| --- | --- | --- | --- |
| Disconnection | The jammer reduces SINR by adding interference, and the developer believes the simulator should react to 0 dB by disconnecting links. | Current connectivity uses approximately −6.7 dB, so a jammed link clipped to 0 dB remains connected. The expected “0 dB disconnects” behavior is not implemented. | **Blocked semantic change.** Ask the team one concrete question: should the link be unusable at 0 dB, or should the 0 dB floor be removed so SINR can cross the existing −6.7 dB threshold? Do not choose between those models in P0. |
| Band selection | The developer says sub-6 is the default and frequencies can be changed through CLI and configuration. | Code defaults `--band` to `mmwave`; `frequency_ghz` is configurable, but band itself is CLI-only and omitted by several launchers. | **Safe plumbing plus one TODO.** Persist/forward/log the resolved band in P0. Before changing the historical default, confirm whether new scenarios should default to `sub-6` and how old scenarios retain prior behavior. |
| Link endpoint | The developer would probably use both ends and wants team confirmation. | Current undirected evaluation already computes jammer power at both endpoints and uses the larger value. | **Keep current behavior provisionally.** Add observability/test coverage without changing it; record team confirmation as a TODO. |
| Frequency overlap | The developer leans toward bandwidth overlap because the jammer disrupts a band, but asks Kyle. | Current implementation tests only the carrier center (single target within ±2.5 MHz or a min/max target range) and does not calculate channel/jammer spectral overlap. | **TODO for Kyle; no P0 physics change.** Log enough frequency/bandwidth data to diagnose behavior and defer overlap math. |
| Jammer movement | The developer confirms that Sherpa jammers moved. | `JammerSpec` and topology setup can consume waypoints or velocity, but `scripts/validation/make_jammers.py` emits one static `position` per trial interval. Parsed `random_walk` values are not installed for jammers. | **Requirement accepted; representation unresolved.** Identify the authoritative time-position source and whether to emit recorded waypoints, velocity, or synthetic random walk. Record as a P0 TODO unless that source/format is supplied. Do not substitute random walk for recorded Sherpa motion. |
| Antenna direction | The developer says the model currently uses pointing direction/degrees to select affected nodes and the propagation model to calculate received interference; Kyle should answer further detail. | Current code has the directional cone gate and propagation calculation, but victim receive-array gain/pattern is not applied to jammer power. | **Test current direction gate; ask Kyle only about receive-side antenna treatment.** Do not change gain/pattern physics in P0. |

Additional unresolved question: should a constant jammer with 50% duty be continuously scaled to half average power, while `type=random` is fully on for half the time, or should both use the same temporal interpretation? Current code implements those two different meanings.

Safe P0 jammer work is therefore limited to band propagation, retained configuration, diagnostics/observability, and regression tests for behavior already confirmed. Disconnection semantics, spectrum-overlap math, receive-side antenna treatment, and the source/representation of Sherpa jammer movement remain explicit TODOs.

## 13. Relevant Files for the Planner

- **C++:**
  - `sim.cc`
  - `src/rl/rl-bridge.cc`, `src/rl/rl-bridge.h`
  - `src/eval/link-evaluator.cc`, `src/eval/sinr-capacity.h`, `src/eval/link-table.h`
  - `src/jammer/jammer-model.cc`, `src/jammer/jammer-model.h`, `src/jammer/jammer-spec.h`
  - `src/cli/cli-parser.cc`, `src/cli/cli-parser.h`
  - `src/io/run-logger.h`
  - `src/config/config-loader.cc`, `src/config/config-validator.cc`
  - `src/domain/sim-config.h`, `src/domain/node-spec.h`
  - `src/setup/topology-builder.cc`
  - `CMakeLists.txt`
- **Python:**
  - `scripts/rl/__init__.py`
  - `scripts/rl/env/mesh_env.py`
  - `scripts/rl/train.py`
  - `scripts/rl/agents/mask_ppo.py`
  - `scripts/sweep/runner.py`
  - `scripts/validation/run_batch.py`
  - `scripts/validation/build_config_files.py`
  - `scripts/validation/make_jammers.py`
- **Inputs:** `inputs/baselines/rl-test/run.ini`, `inputs/baselines/rl-test/nodes.json`
- **Tests:**
  - `tests/Makefile`
  - `tests/CLAUDE.md`
  - `tests/unit/config/config-validator-test.cc`
  - `tests/integration/cli-integration-test.sh`
- **Workflow:** `docs/claude/*.md`, `docs/ORCHESTRATION.md`, `CLAUDE.md`

## 14. Human/Tester Commands for Later Execution

Run from `scratch/mesh-sim/` unless noted. Per `CLAUDE.md`, the human runs all build and run commands.

| Purpose | Command |
| --- | --- |
| Configure and build (repo root) | `./ns3 configure --build-profile=debug -- -DCMAKE_OSX_ARCHITECTURES=arm64` then `./ns3 build` |
| Fast suite | `cd tests && make test` |
| Integration suite | Until auto-detection is repaired, run `./tests/integration/cli-integration-test.sh <binary>` from mesh-sim; `cd tests && make integration` currently relies on the broken auto-detection path |
| Direct run with jamming (repo root) | `./ns3 run scratch/mesh-sim/sim -- --run-config=<run.ini> --band=sub-6 --seed=1 --output-dir=<dir>` |
| RL smoke test (valid argument order) | `python -m scripts.rl.train --sim-binary <bin> --run-config inputs/baselines/rl-test/run.ini --output-dir <dir> m-ppo --total-timesteps 1024` |
| Sweep | `python -m scripts.sweep.cli --config <sweep.ini>` |

## 15. P0 Non-Goals

- No final observation or reward research choices.
- No long training runs and no Optuna campaign.
- No full experiment campaign.
- No duplicate C++ build system and no new experiment-file format.
- No speculative changes to jammer physics until the developer answers section 12.
- No broad GUI implementation and no large documentation expansion.
