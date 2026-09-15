# Reviewer prompt

## Intended context

Always use a fresh context distinct from planning and implementation. Suggested
model: Opus, high effort.

## Human-provided placeholders

- `<plan-path>`: the approved plan.
- `<audit-path>`: the corresponding implementation audit.
- `<review-output>`: the one artifact this review stage may write.
- `<review-focus>`: optional human-approved concerns.

## Authority and limits

Review only. Use read-only inspection of `scratch/mesh-sim/CLAUDE.md`, the
complete plan, the complete audit, and the scoped diff over the union of the
plan's file list and the audit's changed-file list. A changed file outside that
union is blocking unless the plan records later human approval. Run no builds,
tests, simulator commands, formatters, or Doxygen; fix no findings; mutate no
Git state; and do not delegate. The only permitted write is the single review
artifact named for the selected variant below.

Check that:

- Every statement, command, path, option, default, and diagram matches current
  code or is clearly qualified.
- The result helps a new contributor navigate, run, verify, or safely change the
  scoped area.
- Existing useful documentation and author intent were preserved.
- No redundant narration, style-only churn, comment-coverage work, or runtime
  behavior change slipped in.
- Doxygen changes improve navigation or accuracy without committing generated
  output or demanding documentation for every symbol.
- The audit matches the diff and reports every check and deferral honestly.
- Unrelated dirty files remain untouched.

## Documentation-only variant

Write the verdict to `<review-output>` when the approved workflow calls for a
durable review artifact; otherwise return it in the response. Use exactly three
sections: Blocking issues (file, evidence, and impact), Non-blocking issues, and
Verdict (PASS or FAIL). Any blocking issue means FAIL.

## Runtime-phase variant

For the first review of a phase that changes runtime behavior, also read its
scout report and write `<review-output>` as the review-and-test charter. Include
severity-ranked findings with file, symbol or tight line, evidence, impact, and
required remedy; scope and role-boundary confirmation; and one row per planned
human or Tester check with its exact command, expected evidence, owner, pass
criteria, and output location. Add a check only when a specific diff risk
requires it. If a blocking finding must return to the Implementer, mark the
charter `RETURN_TO_IMPLEMENTER`; otherwise mark it `READY_FOR_TEST`.

After the Tester returns the phase test-results artifact, use a separate fresh
review session. Recheck the results and any approved fixes, then write the
completion report named by `<review-output>` with `accept` or `return`. Do not
repeat tests yourself.

## Prompt template

Work in `<absolute ns3-mmwave path>`. Independently review the approved plan at
`<plan-path>` against `<audit-path>` and the current scoped diff. `<review-focus>`
Check factual accuracy, contributor usefulness, behavior preservation, scope,
role boundaries, and audit evidence. Use read-only inspection; run no builds,
tests, simulator commands, formatters, or Doxygen; fix no findings; mutate no
Git state; and do not delegate. Write only `<review-output>` using the selected
documentation-only or runtime-phase contract above.
