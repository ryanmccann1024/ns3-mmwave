# Progress prompt

## Intended context

Fresh context is optional after a PASS review. Suggested model: Opus, low
effort.

## Human-provided placeholders

- `<task>`: use `mesh-sim-handoff-review`.
- `<review-verdict>`: reviewer verdict and accepted non-blocking notes.

## Authority and limits

Read the plan, audit, and pasted PASS verdict. Write exactly one file:
`scratch/mesh-sim/review-research/<task>/progress.md`. Edit nothing else, run no
checks, mutate no Git state, and do not delegate.

Record the review objective, what changed or why the result was no-op, the exact
Files changed list, verification and deferrals, review outcome, deferred code
risks, unresolved documentation questions, and the recommended follow-up, if
any. Make no claim not supported by the artifacts.

## Prompt template

Work in `<absolute ns3-mmwave path>`. The review for `<task>` finished:
`<review-verdict>`. From the plan and audit, write
`scratch/mesh-sim/review-research/<task>/progress.md` with the accepted outcome,
files changed, checks and deferrals, open risks, and recommended follow-up.
Write no other file, run no checks, mutate no Git state, and do not delegate.
Respond with a short summary and the artifact path.
