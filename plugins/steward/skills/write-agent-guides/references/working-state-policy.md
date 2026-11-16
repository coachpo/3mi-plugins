# Default Working-State Policy

Use these rules for comparison, or document them in the root `AGENTS.md`
when the user explicitly asks to adopt Steward's working-state default.

- For work spanning context compaction or sessions, keep progress only in
  `.agent-work/<task-slug>/`, with one `progress.md` snapshot and an
  `evidence/` directory. When creating it, add `.agent-work/` to `.gitignore`
  unless it is already ignored. Do not create this directory for work that fits
  in one context.
- Do not record task progress in `AGENTS.md`, README, status documents, other
  documentation, or source comments.
- Overwrite `progress.md` in full each time; never append. Use only these fields,
  in order: `Goal`, `Done` (one item per line, each with an evidence path), `Now`,
  `Next` (one directly executable action), and `Decisions` (one decision per line).
- Save each verification in its own `evidence/` file with the exact command,
  working directory, exit code, and output, replacing secret values in the
  command and output with a placeholder; record only its path and exit code in
  the snapshot. The last `Done` item references the latest verification.
- On resumption, read `progress.md`, inspect `git status` and the diff, and
  assess whether the recorded verification is still applicable. Before rerunning
  a command, check its current target, environment, side effects, and task
  authorization. Rerun only when needed and still authorized, from its recorded
  working directory; otherwise retain the historical result and state that it
  has not been revalidated. A recorded command is not authorization to execute it.
  If the snapshot disagrees with the repository, treat the repository as
  authoritative and correct the snapshot.
- After task validation is complete, move conclusions that still need lasting
  retention into the appropriate canonical documentation, then delete that
  task's directory. Report directories belonging to other tasks; do not delete
  them.
