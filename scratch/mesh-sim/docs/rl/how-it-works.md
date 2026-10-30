# How a decision works {#mesh_sim_rl_how_it_works}

[TOC]

What happens between the simulator and Python each time the policy chooses:
the timing of ticks and decisions, what the policy sees, which moves it may
make, and one real decision traced from the run's own records.

## 1\. Before you start

- You read \ref mesh_sim_rl_example "The example scenario", so you know the
  layout and why +15.6 is the best return.
- The trace in sections 6 and 8 comes from the evaluation you run on
  \ref mesh_sim_rl_evaluate "Evaluate and compare": the trained model on
  held-out seed 11, file `$OUT/eval/model/episode-0000/steps.jsonl`. Read this
  page now for the ideas; run the command in section 8 after that page.

## 2\. One decision, end to end

\htmlonly
<div class="ms-gates">
<div class="ms-gate"><strong>1. Ticks</strong><span>C++ moves nodes, sums reward</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>2. Step line</strong><span>obs, mask, reward, facts</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>3. Env</strong><span>Python builds obs and reward</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate"><strong>4. Policy</strong><span>one masked move per slot</span></div><span class="ms-gate-arrow">&rarr;</span>
<div class="ms-gate ms-gate-end"><strong>5. Apply</strong><span>C++ checks again, moves</span></div>
</div>
\endhtmlonly

1. **Ticks.** `sim.cc` runs the ticks of the decision window. Before each
   tick, `src/rl/rl-bridge.cc` clamps each controlled node's velocity at the
   walls. After it, the simulator evaluates every link, routes traffic, and
   adds the tick's reward and measurements to the window.
2. **Step line.** At the decision tick, the bridge computes the mask for the
   next decision and writes one JSON line to stdout: the raw observation, the
   mask, the window's mean reward and the facts.
3. **Env.** `scripts/rl/env/mesh_env.py` validates the message. It builds the
   observation the selected preset asks for and the reward the selected
   components ask for, and returns them from `step()`.
4. **Policy.** MaskablePPO picks one action per slot, sampling only from moves
   the mask allows. The env writes `{"action":[…]}` to the simulator's stdin.
5. **Apply.** The bridge checks the action again. A masked move, or a non-hold
   on a padded slot, becomes hold, and the slot is listed in the next
   message's `revalidated_slots`. The bridge sets the node's velocity, and the
   action stays in force for the whole next window.

Each episode is a separate simulator process. `reset()` starts it with
`--rl-mode --seed=<S> --output-dir=<episode folder>`, reads the one-time `init`
line and the tick-0 `step` line, and returns the first observation. The full
message sequence is drawn on \ref mesh_sim_rl_add_algorithm "Add an RL algorithm".

## 3\. Ticks, windows and warmup

\image html rl-timing.svg "The first 30 ticks of two real episodes. Top: building-bypass-smoke, trained model, held-out seed 11 (outputs/rl-tutorial/eval). Bottom: channel-scored-example, trained model, held-out seed 801 (outputs/rl-tutorial/placement/zero-cost/eval). Each square is a tick; the counts come from each decision's ticks_in_step and scored_ticks in steps.jsonl."

The simulator runs ticks 0 to 200 inclusive (201 ticks) for a 20 s scenario
with 0.1 s ticks. A tick is a **decision tick** when its index is a multiple of
the decision interval in ticks, \f$k\f$ = `decision_interval_s / tick_s` = 10
here. The last tick always sends a step, with `done = true`.

| Ticks | What happens | What Python receives |
|---|---|---|
| 0 | Links evaluated at the start positions. Tick 0 is the only tick in the reset window. | The first observation, from `reset()`. Its reward is not a learning step. |
| 1–10 | The first action is in force. | At tick 10, `step()` returns the mean of ticks 1–10. |
| 11–20 | The second action is in force. | The mean of ticks 11–20, at tick 20. |
| … | | |
| 191–200 | The 20th action is in force. | At tick 200: the last reward and `done = true`. No action is read. |

The number of learning steps is \f$\lceil \mathtt{num\_ticks} / k \rceil\f$ =
\f$\lceil 200 / 10 \rceil\f$ = 20 (`num_decisions` in `init`). When
`duration_s / decision_interval_s` is not a whole number, the last window is
shorter; `ticks_in_step` gives its length.

**Warmup** (`[scenario] warmup_s`) excludes ticks with `time_s < warmup_s`
from the reward and from every metric. The example has no warmup. The bottom
row of the figure is `channel-scored-example`, with `warmup_s = 2.0` and
5-tick decisions:

- **Nodes move from tick 0.** Decisions and movement start immediately,
  during warmup, so a move made in warmup pays off later.
- **A window entirely inside warmup returns reward 0.** Decisions 1–3 there
  have 0 of 5 scored ticks, and their step reward is 0.
- **The tick at exactly `warmup_s` is scored.** When `warmup_s` falls on a
  decision tick, that first scored tick is the last tick of the window that
  ends there. Decision 4 ends at tick 20 (t = 2.0 s) and has 1 of 5 scored
  ticks. Its reward is the mean of that one tick. This partly scored window is
  what makes `travel_m_total` null on that scenario
  (\ref mesh_sim_rl_assumptions "Every assumption", section 8).

## 4\. What the policy sees

The simulator sends a raw vector in every step line (`obs`, 6 numbers here:
active flag, x, y, z, then SINR and capacity for the one peer). The policy does
not see that vector. Python rebuilds the observation from `facts` with the
selected preset. The example selects `local_links_v1`: 8 numbers per slot.

\image html rl-observation.svg "local_links_v1 at two real decisions of the trained model on held-out seed 11: decision 0 (reset, NLOS) and decision 3 (first LOS window). Rebuilt from steps.jsonl facts with the preset's own builder by docs/diagrams/rl-tutorial.py."

| Feature | Formula | Decision 0 | Decision 3 |
|---|---|---|---|
| `active` | 1 for a controlled slot, 0 for padding | 1 | 1 |
| `x_n` | \f$2\,(x - x_{\min}) / (x_{\max} - x_{\min}) - 1\f$, clipped to ±1 | 2 · 200/250 − 1 = 0.60 | 0.60 |
| `y_n` | the same with the y bounds | 0.00 | 2 · 40/200 − 1 = −0.60 |
| `z_n` | the same with the z bounds | 2 · 10/50 − 1 = −0.60 | −0.60 |
| `peer.present` | 1 for each real peer | 1 | 1 |
| `peer.sinr_valid` | 1 if the SINR is finite and above −900 dB | 1 | 1 |
| `peer.sinr_n` | \f$(\text{SINR} + 20) / 60\f$, clipped to [0, 1] | (6.61 + 20)/60 = 0.44 | (29.19 + 20)/60 = 0.82 |
| `peer.cap_n` | \f$\log_{10}(1 + C) / 4\f$, clipped to [0, 1], \f$C\f$ in Mbps | log10(993.4)/4 = 0.75 | log10(3880.9)/4 = 0.90 |

What the policy does **not** see with this preset: the building, whether the
link is LOS (only its SINR), the time or the decision number, traffic, and the
other node's position. The policy must infer "I am in the shadow" from low
SINR at its position. Section 4 of \ref mesh_sim_rl_configure "Configure an RL scenario"
lists the other presets.

## 5\. Masks, walls and hold

| Rule | What happens | Seen in the trace |
|---|---|---|
| Mask | A direction is allowed only if the node is more than \f$10^{-6}\f$ m from the bound on that side. Hold is always allowed. A padded slot's mask is `[0,0,0,0,1]`. | At y = −100 (decision 5) south is masked: `[1,1,0,1,1]`. |
| Wall | A move that would cross a bound is shortened, tick by tick, so the node stops exactly on the bound. It does not bounce. That direction is masked at the next decision. | East from x = 240 ends at x = 250, not 260 (decision 8). |
| Hold | Action 4 sets the velocity to zero until the next decision. It does not repeat the previous move. | |
| Speed | `min(step_size_m / tick_s, the node type's top speed)`, fixed for the run, reported in `init.slot_speed_mps`. Top speeds: drone 20, vehicle 15, pedestrian 1.5 m/s. | 20 m/s: 20 m per 1 s decision. |
| Bad message | Malformed JSON or a wrong-length action makes every slot hold, with one warning on stderr. A masked move makes only that slot hold. | `revalidated_slots` is empty on every decision. |

Optional rules mask more: buildings (`avoid_buildings`), peers
(`avoid_node_collisions`) and a start time (`control_start_s`). See
\ref mesh_sim_rl_configure "Configure an RL scenario", section 8.

## 6\. A real episode, decision by decision

The trained model on held-out seed 11. Each row is one line of the episode's
`steps.jsonl`. The action in a row is the one that **produced** that row's
window; the mask in a row is the one for the **next** decision.

<!-- Source: outputs/rl-tutorial/eval/model/episode-0000/steps.jsonl;
     replay_file reported 0 observation and 0 reward mismatches. Model
     outputs/rl-tutorial/train/maskable_ppo_mesh.zip, seed 11. -->

| Decision | Tick | Action that produced it | node-b (x, y) | Link | SINR dB | Step reward | Mask W,E,S,N,H |
|---|---|---|---|---|---|---|---|
| 0 | 0 | none (reset) | (200, 0) | NLOS | 6.6 | none | `1,1,1,1,1` |
| 1 | 10 | south | (200, −20) | NLOS | 8.2 | −1.0 | `1,1,1,1,1` |
| 2 | 20 | south | (200, −40) | NLOS | 10.7 | −1.0 | `1,1,1,1,1` |
| 3 | 30 | south | (200, −60) | LOS | 29.2 | +0.6 | `1,1,1,1,1` |
| 4 | 40 | south | (200, −80) | LOS | 28.9 | +1.0 | `1,1,1,1,1` |
| 5 | 50 | south | (200, −100) | LOS | 23.1 | +1.0 | `1,1,0,1,1` |
| 6 | 60 | east | (220, −100) | LOS | 24.8 | +1.0 | `1,1,0,1,1` |
| 7 | 70 | east | (240, −100) | LOS | 22.4 | +1.0 | `1,1,0,1,1` |
| 8 | 80 | east | (250, −100) | LOS | 20.7 | +1.0 | `1,0,0,1,1` |
| 9–20 | 90–200 | north, south, north, … | (250, −80) and (250, −100) in turn | LOS | 20.0–27.2 | +1.0 each | |

\image html rl-trace.svg "The same episode tick by tick: link SINR with LOS and NLOS ticks marked, the per-tick all_links_los reward against the step reward the learner receives, and node-b's x and y. Vertical lines are decision ticks. Trained model, building-bypass-smoke, held-out seed 11, 200 ticks."

What the trace shows:

- **The reward is a window mean.** Decision 3 scores +0.6. The link turned LOS
  at tick 23 (y = −46): 8 LOS ticks at +1 and 2 NLOS ticks at −1 average to
  +0.6. The window's own facts agree: `los_pairs_sum` 8,
  `legacy_reward_sum` 6, `scored_ticks` 10.
- **The step reward is always the window that just ended.** Decision 1 carries
  the reward for the move chosen at decision 0.
- **Walls mask directions.** At y = −100 south is masked; at x = 250 east is
  masked too. The model never sent a masked move.
- **The policy does what its reward asks, and nothing more.** After decision 3
  every move scores +1, so the reward is indifferent between holding and
  moving. The model went east to the corner and then alternates north and
  south. That is 390 m of travel for no gain in reward. A movement penalty
  would change it (\ref mesh_sim_rl_configure "Configure an RL scenario", section 5).
- **The return** is the sum of the 20 step rewards: −1 − 1 + 0.6 + 17 = 15.6,
  the best possible on this scenario.

## 7\. What the simulator sends

Two message types go from the simulator to Python, and one comes back.

| Message | When | Key fields |
|---|---|---|
| `init` | Once, the first line | Contract name, slot-to-node map, `obs_dim`, `mask_dim`, `num_decisions`, bounds, speeds, `reward_type`, `warmup_s`, `wall_policy: clip` |
| `step` | At tick 0, at every decision tick and at the last tick | `tick`, `time_s`, `decision`, `ticks_in_step`, `scored_ticks`, `obs`, `mask`, `reward`, `done`, `revalidated_slots`, `facts` |
| `{"action":[…]}` | After every `step` that is not `done` | One integer 0–4 per slot |

`facts` is the raw material for every observation preset and reward
component:

- `facts.nodes`: x, y, z, vx, vy, vz and slot (−1 if not controlled) per node;
- `facts.links`: SINR (dB), capacity (Mbps) and LOS (0/1) per node pair, in
  the order (0,1), (0,2), …, (1,2), …;
- `facts.window`: sums over the window's scored ticks: `scored_ticks`,
  `demand_mbps_sum`, `delivered_mbps_sum`, `flow_ticks_with_demand`,
  `unroutable_flow_ticks`, `connected_pairs_sum`, `los_pairs_sum`,
  `legacy_reward_sum`;
- `facts.node_service`: demand and delivery sums per node;
- `facts.safety`: unsafe ticks, the closest pair distance and the slots whose
  move was rejected or touched a wall.

On every reset Python compares the new `init` with the first episode's. A
change mid-training is an error, because one policy needs one fixed layout.
Every field, with units: \ref src_rl "src/rl", sections 5 and 6.

## 8\. Check it yourself

After \ref mesh_sim_rl_evaluate "Evaluate and compare", print the first nine
records of the trace:

```bash
.venv/bin/python - "$OUT/eval/model/episode-0000/steps.jsonl" <<'PY'
import json, sys
for line in list(open(sys.argv[1]))[1:10]:
    r = json.loads(line)
    x, y = r["facts"]["nodes"][1][:2]
    sinr, cap, los = r["facts"]["links"][0]
    reward = r["reward"]["total"] if r["reward"] else None
    print(r["decision"], r["tick"], r["action_sent"], (x, y), los, round(sinr, 1), reward, r["mask"])
PY
```

**Checkpoint:**

```
0 0 None (200.0, 0.0) 0 6.6 None [1, 1, 1, 1, 1]
1 10 [2] (200.0, -20.0) 0 8.2 -1.0 [1, 1, 1, 1, 1]
2 20 [2] (200.0, -40.0) 0 10.7 -1.0 [1, 1, 1, 1, 1]
3 30 [2] (200.0, -60.0) 1 29.2 0.6 [1, 1, 1, 1, 1]
4 40 [2] (200.0, -80.0) 1 28.9 1.0 [1, 1, 1, 1, 1]
5 50 [2] (200.0, -100.0) 1 23.1 1.0 [1, 1, 0, 1, 1]
6 60 [1] (220.0, -100.0) 1 24.8 1.0 [1, 1, 0, 1, 1]
7 70 [1] (240.0, -100.0) 1 22.4 1.0 [1, 1, 0, 1, 1]
8 80 [1] (250.0, -100.0) 1 20.7 1.0 [1, 0, 0, 1, 1]
```

Your SINR values match only with the same binary and seed; the positions,
masks and rewards should match whenever your model makes the same moves.

## 9\. Going further

- \ref src_rl "src/rl": the full wire contract, including invalid actions and
  every optional feature.
- \ref src_rl_policy_inputs "Policy inputs": every preset feature and reward
  formula.
- \ref mesh_sim_rl_assumptions "Every assumption": the timing and observation
  rules on this page, with their code locations.

Previous: \ref mesh_sim_rl_example "The example scenario" · Next: \ref mesh_sim_rl_configure "Configure an RL scenario"
