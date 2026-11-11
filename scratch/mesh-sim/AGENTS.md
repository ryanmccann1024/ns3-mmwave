# AGENTS.md — scratch/mesh-sim

Scoped instructions for any agent or engineer working in `scratch/mesh-sim`.
This file is an index; it does not restate the guidance it links to.

## Read first

1. The human's task direction, whether a chat request or a written plan.
2. [CLAUDE.md](CLAUDE.md) — project rules, build/run authority, and conventions.
3. [CONTRIBUTING.md](CONTRIBUTING.md) — the update-together checklist and
   schema/version ownership.
4. [docs/documentation-standard.md](docs/documentation-standard.md) — how
   documentation, comments, tutorials, figures and research citations are written
   and verified for both the simulator and the visualizer.

## Every task must

- Read the human's task direction and applicable project guidance before editing.
- Preserve unrelated changes; this tree has active concurrent work. Start from the
  current file content, never from a summary.
- Stay within the scope the human authorized. Honor any explicit file limits
  or ownership boundaries; otherwise choose the files needed to complete the task.
- Report out-of-scope needs or unresolved material instruction conflicts. Apply
  the governing instruction hierarchy and explicit human task direction.
- For role outputs, use paths the human specifies; otherwise use the role
  instructions' documented defaults. A read-only role returns its findings in chat
  unless its instructions permit saving them.

## Execution authority

Agents do not run `./ns3 build` or `./ns3 run`. Tools that launch an existing simulator
use `--sim-binary <BIN>`. Documentation tasks may edit their authorized files;
command execution and verification follow the human's task direction and applicable
project rules. See [CLAUDE.md](CLAUDE.md) and the documentation standard.
