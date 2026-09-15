# Git and pull-request prompt

## Intended context

Use after a PASS review and progress record. Suggested model: Opus, low effort.
This is the only workflow step authorized to mutate Git state.

## Human-provided placeholders

- `<task>`: use `mesh-sim-handoff-review`.
- `<branch-name>`: focused branch, normally `docs/mesh-sim-<topic>`.
- `<commit-title>`: Conventional Commit subject.
- `<deferred-checks>`: exact deferred gates and reasons, or `None`.

## Authorized result

One branch from the current `fork/arpo-main`, one or more focused commits
containing exactly the audit's `Files changed` list, and one non-draft pull
request into `arpo-main` on the user's fork. Never merge.

Make no code or documentation edits. If a gate or diff reveals a required edit,
stop and send the task back through implementation and review.

## Required procedure

1. Confirm the worktree is on `arpo-main` and record its status.
2. Fetch `fork`, then confirm local `arpo-main` equals `fork/arpo-main`. Stop if
   they differ; do not reset, merge, or rebase automatically.
3. Create `<branch-name>` from `arpo-main`.
4. Stage every path from the audit's `Files changed` list explicitly. Never use
   `git add -A` or `git commit -a`; selectively stage shared dirty files.
5. Verify `git diff --cached --name-only` exactly matches the audit list.
6. Run exactly the approved pre-PR gates from the plan. Report blocked gates as
   deferred, never passed. Never run `./ns3 build` or `./ns3 run`.
7. Commit using the mesh-sim Conventional Commit rules, push to `fork`, and open
   a non-draft PR into `arpo-main` with summary, files changed, documentation
   decisions, risks, checks, and `<deferred-checks>`.
8. Report branch, commits, PR URL, gate results, and deferrals. The human merges.

Preserve all unrelated dirty changes. Stop if the branch baseline differs, the
staged list cannot match the audit, a gate fails, or the audit is incomplete.
Do not delegate.

## Prompt template

Work in `<absolute ns3-mmwave path>`. For mesh-sim review `<task>`, fetch
`fork` and confirm local `arpo-main` equals `fork/arpo-main`, create
`<branch-name>`, stage exactly the audit's Files changed list, and verify the
cached path list. Run the approved gates, commit as `<commit-title>`, push to
`fork`, and open a non-draft PR into `arpo-main`, reporting
`<deferred-checks>` honestly. Make no content edits, never use `git add -A` or
`git commit -a`, never merge, and do not delegate. Respond with the branch,
commits, PR URL, gates, and deferrals.
