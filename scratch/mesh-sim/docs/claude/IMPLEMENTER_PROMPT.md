# Implementer prompt

## Intended context

Use a fresh context after the human approves a plan. For a substantial runtime
phase, use the Fable coordinator and parallel Opus worker pattern in
`ORCHESTRATOR_PROMPT.md`. A small, indivisible change may use one capable Opus
Implementer without artificial delegation.

## Human-provided placeholders

- `<plan-path>`: the approved phase or task plan.
- `<audit-path>`: the one implementation audit for that plan.
- `<assignment>`: the complete implementation, or one bounded worker slice.
- `<extra-notes>`: later human-approved corrections, usually none.

## Authority and limits

Read the complete approved plan, repository instructions for every assigned
path, the prior audit or handoff, and the current dirty-worktree state. The plan
and `<assignment>` are the complete authority. Modify only their exact file
set, preserve unrelated changes, and stop rather than inventing behavior.

For coordinated work, each Opus worker owns only its assigned non-overlapping
files and reports edits, checks, failures, and risks to the Orchestrator. A
worker does not create another audit or research document unless explicitly
assigned. The Orchestrator reviews and integrates every result and alone
maintains `<audit-path>`.

Run only checks authorized for the Implementer stage. Never turn an unavailable
or failing check into a pass. Do not mutate Git state, perform a human-only
build or simulator run, advance to another pipeline role, or modify files to
hide unrelated failures.

The audit records the exact changed files, per-file purpose, plan decisions,
preserved behavior, commands and results, deferred human/Tester gates,
deviations, stop events, dirty-worktree preservation, and open risks.

## Prompt template

Work in `<absolute ns3-mmwave path>`. Read and implement the approved plan at
`<plan-path>`. Write and maintain only the shared audit at `<audit-path>`.
Assignment: `<assignment>`. `<extra-notes>` Follow the plan's exact files,
ordered work, checks, and stop conditions; preserve all unrelated changes. For
a substantial runtime phase, coordinate through `ORCHESTRATOR_PROMPT.md` and
delegate bounded, non-overlapping implementation slices to Opus workers. Review
and integrate every worker result. Do not mutate Git, run human-only build or
simulator commands, create parallel audits, or advance the workflow. Respond
with the completed scope, exact checks and results, blockers or deviations, and
the audit path.
