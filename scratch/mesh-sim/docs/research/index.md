# Research records {#mesh_sim_research}

[TOC]

Dated research rationale behind Mesh-Sim design choices, recovered from fifteen presentation decks (R01–R15) and tied to the pages that own current behavior. Written for experienced developers and AI engineers with no project history. Current behavior lives in the linked owner pages; these records explain what was recorded, when, with what evidence, and what remains unknown. The source catalog is \subpage mesh_sim_research_sources "Research sources".

This record set is deliberately partial. It covers five topics, not the roughly ten-month program, and it does not audit every experiment. Later local program plans and campaign outputs exist (git-ignored or untracked when reviewed; see the coverage limits below); they are pointed to, not audited here.

## Research questions

1. Which network layers can a positioning study abstract while staying credible and runnable?
2. What beamforming, capacity and routing assumptions does the link model make, and what do they trade?
3. How were field data aggregated and smoothed, and what calibration limits were recorded?
4. What did the jammer interference model assume, and how was it scoped?
5. How did RL training/evaluation and placement assumptions change across the late-September to October decks, and what were the evaluation limits?

## Chronology

Sequence only. Order does not establish causation, retirement of an earlier design, or today's defaults. Dates are shown as the source records them; filename labels, directory-year context and title-slide dates are kept distinct. See the catalog for all fifteen sources.

| Date/label as recorded | Source | Topic | Record |
|---|---|---|---|
| Filename `03-26` (directory `Spring 2026`); title slide undated | R02 "03-26 ns3 Continued.pptx" | Asks how much each stack layer affects a positioning algorithm (slide 56, speaker notes) | \ref research_flow_abstraction |
| Filename `04-02` (directory `Spring 2026`); title slide undated | R03 "04-02 mmWave Mesh.pptx" | Mesh-Sim bootstrap: abstracted layers, tick order, beamforming/noise/capacity and routing assumptions | \ref research_flow_abstraction, \ref research_link_model |
| Filename `05-06` (directory `Spring 2026`); no title date | R05 "05-06.pptx" | Per-second maximum across MAC addresses and a 30 s running median for field traces | \ref research_field_calibration |
| Filename `05-14` (directory `Summer 2026`); title slide reads `05/21/2026` — unresolved | R07 "05-14 Update.pptx" | Calibration unknowns (Tx power, array gains, noise figure, heights), per-node gains, LOS/NLOS concern | \ref research_field_calibration |
| Title "June 16th Update" (filename `June-16-2026`); slides 11–13 carry `2025-05-14/15/16` data-day labels | R08 "June-16-2026.pptx" | Accuracy inconsistent between datasets; suspected dataset-script bug | \ref research_field_calibration |
| Title "June 23, 2026 Update"; slide 2 lists UTC windows without a year | R09 "June-23-2026.pptx" | UTC scenario splitting; assumed +4-hour adjustment; limits of one shared noise setting | \ref research_field_calibration |
| Title `09/11/26` (filename `9-11`) | R10 "9-11 ARPO Weekly Update.pptx" | Jammer model file owners, assumed defaults, SINR floor description, open RL questions | \ref research_jammer_model |
| Title reads `09-18 ARPO Weekly Update` (no year) | R11 "09-18 ARPO Weekly Update.pptx" | mmWave jamming judged "Not useful"; its link to the current sub-6 gate is not established | \ref research_jammer_model |
| Title reads `09-25 ARPO Weekly Update` (no year) | R12 "09-25 ARPO Weekly Update.pptx" | First RL study: 5 scenarios, 300 episodes, 1 seed; reward concerns | \ref research_rl_placement_evolution |
| Title reads `10-02 ARPO Weekly Update` (no year) | R13 "10-02 ARPO Weekly Update.pptx" | Gateway/Friis placement baselines; 4-scenario RL with 1 training and 1 evaluation seed | \ref research_rl_placement_evolution |
| Title reads `10-09 ARPO Weekly Update` (no year) | R14 "10-09 ARPO Weekly Update.pptx" | All movable peers in placement; 12 scenarios; 1 training seed, 5 evaluation seeds | \ref research_rl_placement_evolution |
| Filename `10-23`; no native text or notes extracted | R15 "10-23 ARPO Weekly Update.pptx" | No slide-level content; no meeting or completion date is inferred from the filename | — |

R06 "Potential Modeling Techniques.pptx" is undated in the indexed material and is not covered by a record. R01 and R04 are background (see the catalog).

## Research records

| Record | Question | Primary sources |
|---|---|---|
| \subpage research_flow_abstraction "Flow abstraction" | Which layers can a positioning study abstract? | R03 slides 5, 9–12, 25; R02 slides 54–56 |
| \subpage research_link_model "Link model assumptions" | What does the link model assume about beamforming, noise, capacity and routing? | R03 slides 13–17, 21–23 |
| \subpage research_field_calibration "Field calibration limits" | How were field data aggregated, and what calibration limits were recorded? | R05 slide 2; R07 slides 13–14, 21; R08 slides 10, 14; R09 slides 2, 12 |
| \subpage research_jammer_model "Jammer model" | What did the jammer model assume, and how was it scoped? | R10 slides 6–8, 11; R11 slide 18 |
| \subpage research_rl_placement_evolution "RL and placement evolution" | How did RL/placement evaluation change, and what were its limits? | R12 slides 4–7, 9, 12; R13 slides 4, 6–10, 12–14; R14 slides 4–7, 9, 10, 13 |

Each record covers the question, what was chosen and why, the evidence, and where the behavior lives now. Records are topic pages, not a sequence: read any one on its own and return here or to the catalog.

## Evidence classes

Every cited item carries one of four classes (from the \ref documentation_standard "documentation standard", section 9):

- **recorded rationale** — an explicit reason or tradeoff stated in the cited text or notes. An unexplained assumption is not itself a rationale.
- **observed behavior** — a reported historical design/behavior or current source-inspected behavior. Each citation states which; neither label implies independent experimental verification.
- **exploratory outcome** — a result or judgment reported in a deck for a particular dated experiment; not independently reproduced.
- **unresolved question** — a question the sources raise or leave open, or a historical statement that no inspected source resolves.

Status per claim is **current** (matches source-inspected behavior), **superseded description** (replacement or disagreement is established by cited evidence) or **unresolved** (not matched either way). An unmatched historical statement is unresolved, not proof of a retired implementation.

## Coverage limits

- Image-only slide content has not been comprehensively inspected; 62 of 288 slides have no native text (see the catalog).
- All fifteen original deck SHA-256 hashes were verified against the manifest. That establishes file identity only, not scientific validity.
- The run/model/metric mapping behind R14 slide 10 is unidentified. No result table is recreated or ranked here.
- Private experiment outputs and local planning records are not bundled with this site. They were not independently validated by this source review; their existence establishes neither execution nor scientific validity.
- Code citations establish behavior as read in this batch; they never establish historical motivation. Where no reason was recorded, a record says "no recorded rationale found".
- This batch covers five topics. Gaps between decks are gaps in the source set, not evidence that work stopped.

## Sources and downloads

\ref mesh_sim_research_sources "Research sources" catalogs all fifteen decks with identities, hashes and extraction limits, and explains the two portable evidence files shipped with this site: <a href="research-source-manifest.json">research-source-manifest.json</a> (normalized source manifest) and <a href="research-slide-text.txt">research-slide-text.txt</a> (native slide text and speaker notes, plain text). The original decks are not bundled.
