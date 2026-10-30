# Research record: RL and placement evolution {#research_rl_placement_evolution}

[TOC]

Across the September 25, October 2 and October 9 decks the RL study grew from five scenarios with one seed to twelve scenarios with one training seed and five evaluation seeds, placement baselines moved from two movable UAVs with a Friis reach and gateway penalties to every movable peer scored by the simulated channel, and reward design remained an open concern; the October 9 result table's run identity is unidentified.

Back to \ref mesh_sim_research "Research records" · sources: \ref mesh_sim_research_sources "Research sources".

## Question and context

How did RL training/evaluation and placement assumptions change across the late-September to October decks, and what were the evaluation limits? The three decks are consecutive weekly updates; this record traces what each recorded without inferring that a later design retired an earlier one.

## Recorded choice, alternatives and tradeoffs

- **R12 (09-25)**: five scenarios, 300 episodes, one seed (slides 4–5); observation of neighbor positions, SNR and capacity; actions N/S/E/W; hold and random baselines (slide 6); three reward functions (slide 7). Takeaways: more and longer episodes needed; SNR-only reward "performed the best"; the movement penalty "may be too high" (slide 9). Notes: SNR "probably not enough"; coverage should be measured but "how to quantify coverage?" is open; movement-penalty design is a reward-optimization problem (slide 12).
- **R13 (10-02)**: placement baselines assumed only two movable UAVs, a Friis link budget, a 400 × 400 m grid with about 400 candidates, and point scoring with heavy gateway-disconnection penalties plus separate relocation costs (slides 4, 6–8, text and notes). Slide 12's notes describe the two-node limit as "that's what was sent"; slides 7–8 describe some modes as not active yet. The supplier is not identified. RL ran four scenarios with one training seed and one evaluation seed, 300 episodes (slide 9), five reward functions all with a collision term (slide 10). Recorded concerns: hold was best when unjammed, the 2 m unsafe-proximity threshold was a "poor choice?", the travel penalty was small against the SINR reward (notes: 109 versus 0.39 points), and one evaluation episode "is not enough" (slides 12–14). Slide 14 proposes scenarios without fixed nodes or gateways and adding area coverage to the reward.
- **R14 (10-09)**: placement now includes every movable peer, coverage planning uses the simulated channel, building and collision constraints apply, and initial placement stays fixed during evaluation (slide 4). Twelve scenarios with 3 or 6 movable peers, 100 training episodes of 10 minutes, one training seed and five evaluation seeds, 1 m safety distance (slides 5–6). Five reward strategies and six PPO profiles (slide 7, text and notes); the hidden slide 9 notes describe the normalization and coverage terms. Slide 10 tabulates one selected reward/profile per scenario; its notes say holding and moving jammers are weaknesses, "no one reward function or configuration ... is a definite winner", and "dynamic balance with stable PPO is a good start". Slide 13 asks why movement rose up to 3×, proposes 10–15-node scenarios, and asks whether collisions should be masked or learned.

Motivation for removing the earlier gateway assumptions: R13 slide 14 records "no fixed nodes/gws" as a scenario idea to test what was holding PPO back, and R13 slide 13 notes a gateway near the jammer could not move. Beyond those remarks, no recorded rationale found in the inspected sources for the R14 gateway-free design.

## Evidence

| Citation | Class | What it supports |
|---|---|---|
| R12 "09-25 ARPO Weekly Update.pptx", slides 4–7 (text) | observed behavior | Reported scenario set, seed and observation/action/baseline/reward definitions; design description, not a validated outcome |
| R12 "09-25 ARPO Weekly Update.pptx", slide 9 (text) | exploratory outcome | SNR-only reward best; movement penalty possibly too high; more episodes needed |
| R12 "09-25 ARPO Weekly Update.pptx", slide 12 (text) | unresolved question | Coverage quantification; movement-penalty design |
| R13 "10-02 ARPO Weekly Update.pptx", slides 4, 6–8 (text; speaker notes on slides 6–8) | observed behavior | Reported two-movable-UAV, Friis-reach and gateway-penalty placement design, including relocation costs |
| R13 "10-02 ARPO Weekly Update.pptx", slides 9–10 (text; speaker notes on slide 10) | observed behavior | Reported scenario, seed, reward and PPO settings |
| R13 "10-02 ARPO Weekly Update.pptx", slide 12 (speaker notes; slide is a figure) | exploratory outcome | Hold best when unjammed; reported two-node limit described as "that's what was sent", with supplier unidentified; not jamming-aware |
| R13 "10-02 ARPO Weekly Update.pptx", slides 13–14 (text; speaker notes on slide 13) | unresolved question | 2 m threshold questioned; travel penalty swamped; one evaluation episode insufficient; coverage and gateway-free scenarios proposed |
| R14 "10-09 ARPO Weekly Update.pptx", slide 4 (text) | observed behavior | Reported placement update: all movable peers, simulator scoring, constraints and fixed initial placement |
| R14 "10-09 ARPO Weekly Update.pptx", slides 5–7 (text; speaker notes on slide 7) | observed behavior | Reported scenarios, seed counts, reward strategies and PPO profiles; not independent verification |
| R14 "10-09 ARPO Weekly Update.pptx", slide 9 (hidden; speaker notes) | observed behavior | Reported reward definitions, not validated findings or reasons for selecting each coefficient |
| R14 "10-09 ARPO Weekly Update.pptx", slide 10 (text and speaker notes) | exploratory outcome | Per-scenario selected reward/profile table; "no definite winner"; Dynamic Balance plus Stable PPO "a good start" |
| R14 "10-09 ARPO Weekly Update.pptx", slide 13 (text) | unresolved question | Movement up to 3× higher; XL scenarios; mask-or-learn collisions |
| `scripts/baselines/README.md` (brief: "gateway-free geometric and optimization node placements ... scored by the simulator channel"; "There is no gateway or root.") | observed behavior | Current placement is gateway-free and simulator-scored; source-inspected, not executed in this batch |

## Status

- Gateway-free, simulator-scored placement with every movable peer: **current** (source-inspected \ref scripts_baselines). The R13 two-UAV/Friis/gateway-penalty description: **superseded description** as a design (R14 slide 4 and the current owner describe the replacement); whether every earlier code path was removed is not established.
- R12/R13 scenario sets, seeds and rewards are **dated experiment designs**. Private results and local planning records are not bundled. Their existence establishes neither execution nor retirement.
- One training seed with five evaluation seeds (R14 slide 5): an **evaluation limitation** — five evaluation seeds do not show variability across independently trained models.
- "Dynamic Balance with Stable PPO is a good start" (R14 slide 10 notes): an **exploratory judgment at that date**, attributed to the presenters; not today's recommendation.
- Private experiment outputs and local planning records are not bundled with this site. They were not independently validated by this source review; their existence establishes neither execution nor scientific validity.
- Reward concerns (movement penalty magnitude, coverage quantification, collision handling): **unresolved** in the inspected decks; later phases may address them (not audited here).

## Current owners

- \ref src_rl "rl" — the C++/Python bridge contract (actions, masks, cadence).
- \ref src_rl_policy_inputs_selection "Policy inputs" — observation and reward input selection.
- \ref scripts_rl "scripts/rl" — environment, training, evaluation and experiment tooling.
- \ref scripts_baselines "scripts/baselines" and \ref mesh_sim_placement_start "Placement baselines" — current placement planners and their limits.
- Source-backed formulas: `scripts/rl/env/rewards/` and the mission reward reference.

## Consequences, limits and open questions

- Cross-deck comparisons require aligned scenario, metric, seed and baseline definitions. Unlike reward returns must not be ranked together; delivery or coverage comparisons need their actual metric and evaluation identities. Rows within R14 slide 10 vary by scenario, reward and profile and are not a controlled reward ranking.
- No campaign outcome is audited and no metric or run identity is invented.
- Open: the R14 slide 10 run/model/metric identity and binary; seed coverage of later campaigns (training seeds in particular); whether the recorded reward concerns were resolved in later phases; who supplied the R13 heuristics.
