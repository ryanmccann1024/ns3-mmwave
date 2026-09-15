# Orchestrator prompt

## Intended context

Use for an approved implementation phase when independent work can proceed in
parallel. Suggested coordinator: Fable at high effort. Suggested implementation
workers: Opus at medium or high effort, calibrated to the assigned risk.

The human supplies a phase-specific prompt. That prompt and the approved plan
remain authoritative; this file supplies the reusable delegation contract.

## Delegation contract

The Orchestrator reads the complete plan, audit or prior handoff, repository
instructions, and dirty-worktree state before assigning work. It then:

1. Splits only genuinely independent concerns, with exact files, requirements,
   tests, and stop conditions for each worker.
2. Assigns runtime, C++, Python, and test implementation to capable Opus
   workers. Fable coordinates; it does not directly implement those changes.
3. Prevents overlapping edits. Shared files stay with the Orchestrator or one
   explicitly named integration owner.
4. Requires workers to preserve unrelated changes, avoid Git mutation, obey
   human-only build/run gates, and report results back without creating extra
   audit or research files.
5. Reviews every worker result against the plan, integrates it, runs only the
   checks authorized for the implementation stage, and maintains the single
   phase audit.
6. Stops on a plan contradiction, scope expansion, unresolved shared-file
   conflict, prohibited command, or failure without an authorized remedy.

Delegation never advances the workflow. The human starts and approves each
Scout, Planner, Implementer, Reviewer, Tester, and Git/PR stage. Reviewer,
Tester, Progress, and Git/PR remain independent roles and do not inherit the
implementation workers.

## Prompt template

Work in `<absolute ns3-mmwave path>`. Coordinate implementation of the approved
plan at `<plan-path>`, using `<audit-path>` as the single audit. Read all
applicable instructions and the current dirty-worktree state first. Delegate
independent runtime/code/test concerns to parallel Opus workers with exact,
non-overlapping file ownership, acceptance criteria, permitted checks, and stop
conditions. Keep shared integration files with one owner. Review and integrate
every result, run only Implementer-authorized checks, preserve unrelated work,
and keep the audit current. No worker may mutate Git, run a human-only build or
simulator command, expand scope, create a parallel audit, or advance to review,
testing, or Git/PR. Stop and report any unresolved conflict or out-of-plan need.
