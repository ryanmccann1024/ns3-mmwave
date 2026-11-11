# Research record: jammer model {#research_jammer_model}

[TOC]

The September sources describe jammer received power in the SINR denominator and several assumed parameters. The reported 0 dB SINR floor disagrees with current code, which preserves negative SINR. A later note calls mmWave jamming "Not useful", but does not establish why the code uses its sub-6 gate; the accuracy question was left open.

Back to \ref mesh_sim_research "Research records" · sources: \ref mesh_sim_research_sources "Research sources".

## Question and context

What did the jammer interference model assume, and how was it scoped? R10 describes interference for field-logged jamming and asks whether its agreement with field data was close enough. R11 asks whether jamming should work on mmWave and records "Not useful"; neither source explicitly links that note to the current code gate.

## Recorded choice, alternatives and tradeoffs

- **Model and owners** (R10 slide 6): the jammer is configured from `jammer-spec.h`, beam logic in `jammer-model.cc`, mobility in `topology-builder.cc`, and SINR in `link-evaluator.cc` as `10·log10(signal / (noise + jam))`, with "SINR's min is capped to 0.0". The slide records the structure; no alternative structure is recorded.
- **Assumed parameters** (R10 slides 7–8): in the example scenario, missing jammer fields were defaulted (gain 12.0, z 2.0, beamwidth 60.0°, zenith 0.0°); the run used `noise_figure_db = 5.0` "instead of 20.0 because of the Jammer". No reason beyond that phrase is recorded for the 5 dB choice, and no recorded rationale found for the default values.
- **Agreement** (R10 slide 11): "average mean SINR: ± ~9 dBm", with the open question "Is this SINR margin close enough?". The unit is reproduced as written; SINR and its dB differences are not power measurements in dBm. The wording is kept intact in the evidence asset and is not treated as a newly verified numerical result here.
- **Band-scope question** (R11 slide 18): "Should jamming work on mmWave?" answered "Not useful". The sources do not link that brief judgment to the current sub-6 code gate; its implementation rationale remains unresolved.

## Evidence

| Citation | Class | What it supports |
|---|---|---|
| R10 "9-11 ARPO Weekly Update.pptx", slide 6 (text) | observed behavior | Reported file owners/equation and minimum-SINR description; not a verified historical implementation |
| R10 "9-11 ARPO Weekly Update.pptx", slide 7 (text) | observed behavior | Reported example scenario with assumed gain, z, beamwidth and zenith values; not a measured outcome |
| R10 "9-11 ARPO Weekly Update.pptx", slide 8 (text) | recorded rationale | Channel configuration used; noise figure 5.0 "because of the Jammer" (reason not elaborated) |
| R10 "9-11 ARPO Weekly Update.pptx", slide 11 (text) | exploratory outcome | Mean SINR agreement stated in "dBm"; no independent reproduction and slides 9–10 heatmaps not inspected |
| R10 "9-11 ARPO Weekly Update.pptx", slide 11 (text) | unresolved question | Whether the reported agreement is close enough |
| R11 "09-18 ARPO Weekly Update.pptx", slide 18 (text) | unresolved question | mmWave jamming judged "Not useful"; no link to the current gate's implementation decision is recorded |
| `src/eval/link-evaluator.cc` (function `LinkEvaluator::Configure`, `m_computeInterference = (band == "sub-6")`; shared function `LinkEvaluator::EvaluateLink`, jammer block guarded by `m_computeInterference && m_jammerModel.HasJammers()`) | observed behavior | Current code adds jammer power only on the sub-6 band and only when jammers are loaded; source-inspected, not executed in this batch |
| `src/eval/link-evaluator.cc` (shared function `LinkEvaluator::EvaluateLink`, `r.sinr_db = 10.0 * std::log10(signalWatt / (noiseWatt + jamWatt))` with no clamp) | observed behavior | Current SINR preserves negative values; there is no 0 dB floor; source-inspected |
| `src/jammer/README.md` (section "Negative SINR": "There is no artificial 0 dB floor") and `src/eval/CLAUDE.md` | observed behavior | Owner documentation agrees with the code; source-inspected |
| `src/eval/link-evaluator.h` (`Evaluate` step list and `EvaluateProbe` documentation) and `src/eval/README.md` (section "Probe links") | observed behavior | Current owner descriptions preserve negative SINR for mesh and probe links; source-inspected |

## Status

- Jammer interference gated to sub-6: **current** (source-inspected `link-evaluator.cc`). R11 slide 18 records "Not useful" but does not establish the gate's rationale.
- SINR = signal / (noise + jammer) with negative values preserved, no 0 dB floor: **current** (source-inspected `link-evaluator.cc`, `src/jammer/README.md`).
- R10 slide 6's "min is capped to 0.0": **superseded description** — it disagrees with the current source. Whether and when an implementation matched that description is **unresolved**; this record does not assume a floor was implemented and later removed.
- Owner descriptions in `src/eval/link-evaluator.h` (`Evaluate` and `EvaluateProbe`) and `src/eval/README.md` ("Probe links"): **current**, matching the unclamped calculation; source-inspected.
- Default jammer parameters and the 5 dB noise figure: **recorded assumptions as of R10**; whether they are current defaults is not established here (no code citation; owner: \ref src_jammer).
- Agreement with field data: **unresolved** (R10 slide 11 asks the question and does not answer it).

## Current owners

- \ref src_jammer "jammer" — jammer specification, beam and schedule semantics, negative-SINR behavior.
- \ref src_eval "eval" — SINR computation and band gating.
- Repository paths: `src/eval/link-evaluator.cc`, `src/eval/link-evaluator.h`, `src/jammer/README.md`.

## Consequences, limits and open questions

- In current code jamming affects only sub-6 runs; the inspected sources do not establish why this gate was chosen.
- Because current SINR can go negative, capacity falls to zero below the documented threshold (\ref src_jammer). A comparison with any historical implementation would need its actual equation and scoring identity, rather than assuming that it used the floor described in a slide.
- No accuracy claim is made; the "± ~9" figure is a dated statement with a unit problem and an uninspected heatmap basis.
- Open: whether and when the historical implementation matched the slide's floor description, and the provenance of any change; whether the brief "Not useful" note records a reason beyond its wording; provenance of the jammer default values and the 5 dB noise figure.
