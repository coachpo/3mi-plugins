# Alias-scoped GOAL authoring

## Bind and establish consensus

Operate in the Git worktree containing the current session cwd. Freeze and
revalidate its canonical root, Git directory, and common directory through
`worktree_binding.py`. Repository evidence constrains the contract but does not
expand the user's result, scope, authorization, or completion criteria.

Use only current and explicitly accepted decisions as consensus. Ask when a
missing decision can materially change outcome, scope, authority, cost, or
risk. Keep the existing canonical seven-line format and consecutive `C1...Cn`
criteria.

## Build the immutable bundle

The selected alias identifies:

```text
.steward/goals/<alias>/
  manifest.json
  goal.txt
  context.md
  acceptance-plan.json
```

The `证据与上下文` line must reference
`.steward/goals/<alias>/context.md` exactly once. Read
[goal-context.md](goal-context.md) for eligible content.

Create acceptance plan schema version 1 with exactly:

- `schemaVersion: 1`;
- `sourcePolicy`, either `{"mode":"git-visible"}` or a non-empty safe
  project-relative `files` set;
- an ordered non-empty `cases` list.

Each case contains only `id`, `required`, `platform`, `coversCriteria`,
`assertion`, `runnerHint`, and `evidence`. Evidence contains only
`requiredFiles` and `nonEmptyFiles`; non-empty files must also be required.
Every `C*` needs a required case. Freeze observable acceptance intent, not
runtime argv: a runner may be planned even when implementation will create it,
but placeholders and unverifiable assertions are invalid.

Serialize one strict payload in memory:

```json
{"objective":"<seven lines>","context":"<verified Markdown>","acceptancePlan":{"schemaVersion":1,"sourcePolicy":{"mode":"git-visible"},"cases":[]}}
```

Preflight and create with the current worktree as command cwd:

```text
python3 -B "<plugin-dir>/scripts/goal_workspace.py" validate-create --goal <alias> -
python3 -B "<plugin-dir>/scripts/goal_workspace.py" create --goal <alias> -
```

Use a finite non-TTY pipe, or `pty_stdin_bridge.py` when delayed PTY input is
the only transport. Freeze the exact successfully preflighted bytes before the
single create call. Identical content is idempotent; any conflicting, partial,
tracked, linked, moved, or tampered bundle blocks without replacement.

The new implementation ignores legacy flat GOAL, context, Adapter, and
Campaign paths. Their presence neither supplies authority nor blocks a valid
alias-scoped bundle. The calling workflow convention is one drafted GOAL per
worktree, but the storage contract deliberately permits independent aliases.
