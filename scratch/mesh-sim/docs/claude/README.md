# Human-controlled mesh-sim workflow

This workflow is for restrained code review and contributor handoff
documentation within `scratch/mesh-sim/`. Every step is started by the human in
a session the human opens. Delegation may happen only inside an approved
implementation stage; it cannot start another stage or run unattended.

## Canonical sequence

1. Scout explores the complete scoped review and writes
   `review-research/mesh-sim-handoff-review/scout.md`.
2. The human opens a fresh planning context with a condensed, self-contained
   handoff from the scout artifact.
3. Planner writes `review-research/mesh-sim-handoff-review/plan.md`.
4. The human and Codex inspect and correct the plan until it is approved.
5. Implementer makes only the approved documentation changes and writes
   `review-research/mesh-sim-handoff-review/audit.md`.
6. A fresh Reviewer checks the scoped diff and returns PASS or FAIL.
7. Failures return to the planning and implementation loop; review repeats.
8. Progress records the accepted result in
   `review-research/mesh-sim-handoff-review/progress.md`.
9. Git/PR creates a focused branch and pull request into `arpo-main`.
10. The human merges the single review PR.

This is one Scout/Planner/Implementer/Reviewer cycle and at most one pull
request. If the scout or planner determines that existing documentation is
already accurate and sufficient, record that conclusion and skip implementation
and the pull request. A no-op is a valid result.

## Roles

| Document | Purpose | Suggested model/effort |
| --- | --- | --- |
| [SCOUT_PROMPT.md](SCOUT_PROMPT.md) | Trace behavior and find handoff gaps | Opus, low |
| [PLANNER_PROMPT.md](PLANNER_PROMPT.md) | Convert evidence into a minimal plan | Fable, high |
| [ORCHESTRATOR_PROMPT.md](ORCHESTRATOR_PROMPT.md) | Coordinate parallel implementation within one approved phase | Fable, high |
| [IMPLEMENTER_PROMPT.md](IMPLEMENTER_PROMPT.md) | Apply one approved implementation scope or worker slice | Opus, medium/high |
| [REVIEWER_PROMPT.md](REVIEWER_PROMPT.md) | Check accuracy, restraint, and scope | Opus, high |
| [TESTER_PROMPT.md](TESTER_PROMPT.md) | Execute the Reviewer's approved test charter (runtime phases only) | Opus, medium |
| [PROGRESS_PROMPT.md](PROGRESS_PROMPT.md) | Preserve the phase handoff | Opus, low |
| [GIT_PR_PROMPT.md](GIT_PR_PROMPT.md) | Branch, commit, push, and open the PR | Opus, low |

Model names describe the current routing policy, not a permanent capability
claim. Fable may coordinate substantial implementation, but runtime, C++,
Python, and test changes go to capable Opus workers. Fresh context, explicit
ownership, and role separation remain mandatory.

## Delegated implementation

For a substantial approved phase, the human supplies one phase-specific prompt
to the Fable Orchestrator. The Orchestrator may assign independent,
non-overlapping concerns to parallel Opus Implementers. Each assignment names
exact files, requirements, checks, and stop conditions. Shared files have one
owner. Workers report back without creating extra audits; the Orchestrator
reviews and integrates every result and maintains the single phase audit.

This delegation stays inside implementation. The human still starts Reviewer,
Tester, and Git/PR separately. No worker mutates Git, runs a human-only build or
simulator command, expands the plan, or advances the workflow. Small tasks may
remain with one Opus Implementer when parallelism would add coordination risk.

## Runtime phases

The sequence above is the documentation-only review workflow and its
`review-research/mesh-sim-handoff-review/` paths are unchanged. A phase that
changes runtime behavior (such as P0 under `docs/rl-program/<phase>/`) uses this
extended sequence after the human approves its plan:

1. The Orchestrator coordinates the approved implementation, integrates the
   Opus workers' results, and writes the single phase audit.
2. The Reviewer reads the plan, scout report, audit, and diff, and writes
   `<phase-dir>/…-review-and-test-charter.md` instead of a bare verdict.
3. The Tester executes that charter against a binary the human built and writes
   `<phase-dir>/…-test-results.md` back to the Reviewer.
4. The Reviewer reads the results, rechecks any fixes, and writes
   `<phase-dir>/…-completion-report.md` with `accept` or `return`.
5. Only after `accept` does the Git/PR role branch, commit, push, and open the
   PR; the human merges. No other role mutates Git state.

The Reviewer does not run builds, and the Tester does not edit code.

## Ground rules

- The working boundary is `scratch/mesh-sim/`; other ns3-mmwave paths are
  read-only dependencies unless the human expands scope.
- Preserve existing documentation that is accurate and useful. Do not normalize
  prose across the tree or chase comment coverage.
- Documentation must help a new contributor navigate, run, verify, or safely
  modify the system. If it does none of those, do not add it.
- In the documentation-only workflow, source edits are limited to approved
  comments/Doxygen annotations. Runtime phases authorize only their planned
  code and test changes.
- Do not edit tracked inputs merely to make examples look cleaner. Do not touch
  `data/`, `inputs/custom/`, generated Doxygen HTML/LaTeX, or IDE metadata.
  Runtime-phase checks may create disposable outputs, temporary test inputs,
  caches, and a test venv only where the plan or charter authorizes them.
- Only the approved implementation stage edits planned content; only Git/PR
  mutates Git state; the human merges.
- Artifacts are the handoff. If a fact is not in `scout.md`, `plan.md`,
  `audit.md`, or `progress.md`, it is not part of the accepted review record.
