---
name: draft-consensus-goal
description: Create or resume Steward's machine-validated seven-line Chinese GOAL and sole context in one caller-provided worktree. Use only when explicitly asked to persist a new contract or continue a named interrupted invocation.
---

# Draft Consensus Goal

Persist one reviewable GOAL contract for later manual execution and
`run-closed-loop-verification`. This is the only Steward skill that authors it.

## Authority and target

Explicit invocation authorizes read-only fact checking in the supplied worktree
and the `.steward/` control writes defined by the referenced contracts. It does
not authorize implementing or verifying the GOAL, external effects, or changes
outside `.steward/`.

Require the main session or caller to provide exactly one already-resolved
`<target-worktree-root>`. Never derive it from the plugin directory, shell cwd,
repository discovery, or a sibling worktree.

## Workflow

Read and apply [`goal-authoring.md`](../../references/goal-authoring.md) for
binding, accepted evidence, new or resumed invocation handling, seven-line
format, validation, transport, and persistence. Read and apply
[`goal-context.md`](../../references/goal-context.md) for the sole context file
and its project-relative GOAL reference.

## Output

On success, return exactly `goalContract.objective` from the canonical workspace
view, with no JSON, digest, introduction, or text after the seventh line. On a
resumable blocker, name `$steward:draft-consensus-goal`, the absolute target,
observed workspace state, exact recovery source, and payload SHA-256/UTF-8 byte
count when an exact payload was recovered, followed by the smallest next action;
do not print the payload. For other blockers, return only the actual blocker and
smallest next action.
