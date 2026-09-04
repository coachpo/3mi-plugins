# Alias-scoped GOAL authoring

## Bind and establish consensus

Operate in the Git worktree containing the current session cwd. Every
`goal_workspace.py` command re-resolves and revalidates its canonical root,
Git directory, and common directory at invocation time, so a separate
binding precheck is never needed. Repository evidence constrains the contract
but does not expand the user's result, scope, authorization, or completion
criteria.

Use only current and explicitly accepted decisions as consensus. Ask when a
missing decision can materially change outcome, scope, authority, cost, or
risk. Keep the canonical seven-line format from
[goal-template.txt](goal-template.txt) — its seven line labels are required
exactly as written — and consecutive `C1...Cn` criteria.

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
`assertion`, `runnerHint`, and `evidence`, plus an optional
`onFailure: "waive-with-report"` that only a non-required case may carry: a
failed waived case is reported but does not open the repair window or block a
passing attempt. Evidence contains only `requiredFiles` and `nonEmptyFiles`;
non-empty files must also be required. Every `C*` needs a required case. Freeze
observable acceptance intent, not runtime argv: a runner may be planned even
when implementation will create it, but placeholders and unverifiable
assertions are invalid.

`sourcePolicy` accepts an optional `writable` list of safe project-relative
files that cases may create or modify, such as coverage or lockfile byproducts
or an ignored runner's outputs that verification must keep out of the source
identity. `writable` files must be disjoint from an explicit `files` source
set; a runner that is itself a repair target must instead be tracked or
declared in a `files` source set, not hidden in `writable`.

Serialize one strict payload in memory:

```json
{"objective":"<seven lines>","context":"<verified Markdown>","acceptancePlan":{"schemaVersion":1,"sourcePolicy":{"mode":"git-visible"},"cases":[]}}
```

The GOAL must stay within 4,000 Unicode code points and follow the canonical
seven-line template. The JSON transport normalizes the context string.

Preflight and create with the current worktree as command cwd, choosing one
transport for the whole flow:

```text
python3 -B "<plugin-dir>/scripts/goal_workspace.py" create --goal <alias> -
```

or the staged-file transport, which needs no JSON quoting at all. Write the
canonical GOAL, context, and plan as three plain files, then create:

```text
<staging-dir>/goal.txt
<staging-dir>/context.md
<staging-dir>/acceptance-plan.json
python3 -B "<plugin-dir>/scripts/goal_workspace.py" create-from --goal <alias> <staging-dir>
```

`create-from` stages exactly what lands in the bundle: `goal.txt` is parsed
with the same 4,000-code-point seven-line contract, `acceptance-plan.json` is
parsed strictly, and `context.md` must already be canonical (UTF-8, LF only,
no BOM/NUL/CR, one final LF). Relative staging paths resolve against the
worktree root; keep the staged files until create confirms success.

Use `validate-create` or `validate-create-from` with the same payload for an
optional dry run that returns the canonical manifest view without writing
anything. Freeze the exact successfully preflighted input before the single
create call. Identical content is idempotent; any conflicting, partial,
tracked, linked, moved, or tampered bundle blocks without replacement.

The new implementation ignores legacy flat GOAL, context, Adapter, and
Campaign paths. Their presence neither supplies authority nor blocks a valid
alias-scoped bundle. The calling workflow convention is one drafted GOAL per
worktree, but the storage contract deliberately permits independent aliases.
