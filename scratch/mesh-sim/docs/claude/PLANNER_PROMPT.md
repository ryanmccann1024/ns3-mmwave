# Planner prompt

## Intended context

Use a fresh context with a condensed scout handoff. Suggested model: Fable,
high effort.

## Human-provided placeholders

- `<task>`: use `mesh-sim-handoff-review`.
- `<task-brief>`: approved review objective.
- `<scout-findings>`: condensed, self-contained evidence from `scout.md`.
- `<constraints>`: corrections, exclusions, and files that must not change.

## Authority and limits

Planning only. Read `scratch/mesh-sim/CLAUDE.md`, the pasted handoff, and only
the targeted repository files needed to verify load-bearing facts. Write exactly
one file: `scratch/mesh-sim/review-research/<task>/plan.md`.

The plan must optimize for a new contributor's ability to work safely, not for
documentation volume. It must preserve accurate existing text, avoid style-only
rewrites, and exclude behavior changes. Every proposed addition must answer a
specific contributor question. If no edit clears that bar, write a no-op plan.

The plan must contain:

1. Objective, current baseline, and exclusions.
2. Documentation decisions: keep, correct, consolidate, add, or remove—with
   evidence and rationale.
3. Exact changes per file and an exact `Files touched` list.
4. For source comments, exact symbols and the non-obvious contract being
   documented.
5. Ordered verification matrix, distinguishing read-only checks, lightweight
   local checks, Doxygen, and user-run ns-3 build/run commands.
6. Dirty-worktree ownership and preservation rules.
7. Stop conditions, acceptance criteria, open risks, and deferred code defects.

Run no checks and mutate no Git state. Do not delegate.

## Prompt template

Work in `<absolute ns3-mmwave path>`. Plan the `scratch/mesh-sim/` handoff review
`<task>`. Objective: `<task-brief>`. Scout findings: `<scout-findings>`.
Constraints: `<constraints>`. Verify only load-bearing facts with targeted reads,
then write `scratch/mesh-sim/review-research/<task>/plan.md`. Specify the
smallest useful documentation change set, an exact Files touched list, ordered
verification, and stop conditions. Behavior changes and paths outside
`scratch/mesh-sim/` are excluded. Write no other file, run no tests, mutate no
Git state, and do not delegate. Respond with a short summary and the artifact
path.
