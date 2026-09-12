# GOAL bundle contract

Draft from the user's accepted requirements and decisions. Repository evidence
informs feasibility and acceptance; it does not authorize additional work.
Resolve routine drafting choices yourself. Ask only for a missing decision that
materially changes the executor's outcome, scope, authority, cost, or risk.

## Files and acceptance intent

The immutable bundle contains `manifest.json`, `goal.txt`, `context.md`, and
`acceptance-plan.json` under `.steward/goals/<alias>/`.

`goal.txt` uses the exact seven labels in [goal-template.txt](goal-template.txt),
at most 4,000 Unicode code points, and consecutive `(C1)...(Cn)` criteria. Each
line describes the executor's task, including authorized implementation and
verification, rather than the drafter's role. The `证据与上下文` line references
`.steward/goals/<alias>/context.md` exactly once.

`context.md` contains verified sources and useful background, without duplicating
the GOAL or adding authority. Cite project-relative paths and relevant symbols;
for external sources include URL, applicable version, and the supported fact.
Use UTF-8 without BOM/NUL/CR and one final LF. Keep machine-specific absolute
paths out of the GOAL and context. Do not invent evidence to fill the context.

Acceptance plan version 1 has exactly these top-level fields:

- `schemaVersion: 1`;
- `sourcePolicy`: either `{"mode":"git-visible"}` or
  `{"mode":"files","files":["src/example.py"]}` with a non-empty safe
  project-relative file set;
- `cases`: an ordered, non-empty list.

Each case contains `id`, `required`, `platform`, `coversCriteria`, `assertion`,
`runnerHint`, and `evidence`. Evidence contains `requiredFiles` and
`nonEmptyFiles`; non-empty files must also be required. Every `C*` must be covered
by a required case. Freeze observable acceptance intent, not runtime argv; the
executor may still need to implement a runner. Avoid placeholders or assertions
that cannot be checked.

Two optional fields express accepted tolerance:

- A non-required case may carry `onFailure: "waive-with-report"`; its failure is
  recorded and reported without blocking completion. Other failures remain strict.
- `sourcePolicy.writable` lists safe project-relative byproduct files a case may
  change. Verification captures and restores them, excluding them from the source
  fingerprint. They must be disjoint from an explicit `files` set. A runner that
  could need repair belongs in protected source, not this list.

## Create and resume

Write `goal.txt`, `context.md`, and `acceptance-plan.json` in a temporary staging
directory, then run from the target worktree:

```text
python3 -B "<plugin-dir>/scripts/goal_workspace.py" create-from --goal <alias> <staging-dir>
```

The creator validates the format, criterion coverage, paths, and exact worktree
binding, then creates the manifest. Keep staging until success and remove your
temporary files afterwards. `validate-create-from` is an optional dry run.
Alternatively, `create --goal <alias> -` accepts a finite stdin JSON payload with
`objective`, `context`, and `acceptancePlan` fields; normal shell redirection or
a subprocess input pipe is sufficient.

Identical creation is idempotent. Conflicting, partial, tracked, linked, moved,
or tampered bundles are rejected without replacement. Resume with
`view --goal <alias>` and use the returned validated payload; do not reconstruct
it from a chat summary. `list` discovers aliases in the current worktree.
Commands resolve the worktree from cwd themselves. Existing bundles remain
immutable and bound to their original physical worktree.
