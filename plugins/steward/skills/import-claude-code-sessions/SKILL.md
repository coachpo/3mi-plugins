---
name: import-claude-code-sessions
description: Import precisely selected Claude Code chats through a currently supported native Codex importer and verify the resulting target. Use when the user asks to import, migrate, or continue Claude Code work by project or chat; do not use for standard Claude Chat data or manual transcript conversion.
---

# Import Claude Code Sessions

Bring only the selected Claude Code chats into Codex through a supported native
desktop or independent local CLI importer. Do not convert transcript files or
write Codex databases, rollout files, or Claude source data directly.

## Boundary

A direct import, migrate, or continue request authorizes the native local import
of the exact selected chats. It does not authorize extra chats, duplicate copies,
unrelated setup, automatic updates, sign-in changes, or post-import service
connections. Imported history is context, not present-day authorization.

Do not expose credentials, unrelated source details, or message bodies as import
evidence. Any external connection or authentication change follows its ordinary
user-action and approval boundary.

On resume, inspect native import history and the likely target before retrying.
Return a verified existing target as `already present`. If identity or partial
state is ambiguous, stop before creating a possible duplicate.

## Use the current native flow

When internet access is available, open the current official import documentation
at <https://learn.chatgpt.com/docs/import>. Treat that page and the currently
visible native importer as authoritative for menu paths, availability, discovery
windows, item limits, and supported surfaces; do not rely on hard-coded UI names
or numeric limits.

Use one supported native route, review its selection, and import only the exact
authorized Claude Code chats. If neither desktop nor an independent local Codex
CLI importer is available, stop. Do not substitute a custom staging or conversion
pipeline.

## Terminal evidence

Use distinct completion contracts:

- `imported`: the native importer reports success for the selected items, and the
  new target exists, opens, and contains the expected conversation history.
- `already present`: an existing target's exact title/project or identifier and
  expected history match the selection, and no new copy was created.
- `incomplete`: an attempted import failed, is partial, or its target cannot be
  opened and verified.
- `user action needed`: selection is ambiguous, the source is unsupported, a
  native surface is unavailable, or authentication/setup must be completed by
  the user.

The invariant “do not actively modify Claude source data or unrelated setup” is
an operation boundary, not a claimed post-import proof unless the native surface
provides verifiable evidence for it.

Report title/project, importer counts, target identifier, and remaining setup
only when the native surface exposes them. An importer completion message alone
does not prove `imported`.

Read [`troubleshooting.md`](references/troubleshooting.md) only after a native
failure or unavailable/ambiguous condition. State the evidence already obtained
and the smallest safe next action; do not retry an ambiguous target.

## Optional continuation

If the user also asks to continue the imported work, first verify the target,
then read and apply
[`continue-imported-work.md`](references/continue-imported-work.md). Navigate to
that target rather than creating another task unless the user explicitly asks
for one.

## Output

Lead with exactly one terminal status: `imported`, `already present`,
`incomplete`, or `user action needed`. Then report selected source, native result,
target identity, verification evidence, pending setup, and minimum next action.
Keep the report to metadata and omit routine UI narration.
