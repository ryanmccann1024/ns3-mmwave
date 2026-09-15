# Scout prompt

## Intended context

Use a fresh context. Suggested model: Opus, low effort.

## Human-provided placeholders

- `<task>`: use `mesh-sim-handoff-review`.
- `<task-brief>`: two to five sentences defining the handoff question.
- `<focus-areas>`: mesh-sim paths most likely to answer it.

## Authority and limits

Read `scratch/mesh-sim/CLAUDE.md`, the single review scope, and the files required to
trace the current behavior. Exploration is read-only except for exactly one
artifact: `scratch/mesh-sim/review-research/<task>/scout.md`.

Do not fix code or documentation, run builds/tests/Doxygen, mutate Git state,
inspect unrelated ns3-mmwave subsystems, or delegate work. Do not recursively
read or inventory input/output data. Generated outputs, custom datasets, caches,
and IDE metadata are out of scope. Read input documentation and at most one
representative tracked example only when needed to verify a claim. Record the
initial dirty-worktree state and preserve it byte-for-byte.

The scout artifact must contain:

1. Task restatement and explicit exclusions.
2. Current behavior and data flow, with paths and symbols as evidence.
3. Existing documentation and whether each item is accurate, stale, duplicated,
   misplaced, or already sufficient.
4. Contributor entry points, commands, dependencies, and verification paths.
5. Contracts and invariants that are easy to violate.
6. Documentation gaps ranked as blocking, useful, or optional.
7. Discovered code risks, clearly separated from authorized documentation work.
8. Open questions and a recommended smallest useful change set for the planner.

Do not paste raw file dumps. A no-change recommendation is valid.

## Prompt template

Work in `<absolute ns3-mmwave path>`. Review only `scratch/mesh-sim/` for
`<task>`. Task: `<task-brief>`. Focus areas: `<focus-areas>`. Read
`scratch/mesh-sim/CLAUDE.md` and the single review scope, explore read-only, and write
condensed evidence to
`scratch/mesh-sim/review-research/<task>/scout.md`. Separate documentation gaps
from code defects; recommend the smallest useful documentation set, including a
no-op if current coverage is sufficient. Write no other file, run no tests or
Doxygen, mutate no Git state, and do not delegate. Respond with a short summary
and the artifact path.
