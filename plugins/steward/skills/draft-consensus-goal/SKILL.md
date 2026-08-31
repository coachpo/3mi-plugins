---
name: draft-consensus-goal
description: Author and persist Steward's machine-validated seven-line Chinese GOAL from accepted decisions and verified facts in one caller-provided worktree. Use only when explicitly invoked to create the canonical .steward/goal.txt and its sole context file for later manual execution; do not start implementation.
---

# Draft Consensus Goal

Create the single reviewable GOAL contract that a user will execute manually and
`run-closed-loop-verification` can later accept. This skill alone authors that
GOAL and owns its 4,000-code-point, context, and workspace contracts.

Explicit invocation authorizes only the project-local control writes described
here. It does not authorize implementation, verification, external effects, or
changes outside `.steward/`.

## Bind the target worktree

Require the main session or caller to provide exactly one already-resolved
`<target-worktree-root>`. Never derive it from the plugin directory, shell cwd,
repository discovery, or a sibling worktree.

Read and apply [`goal-authoring.md`](../../references/goal-authoring.md). It owns
worktree binding, evidence, strategy authority, uncertainty, the seven-line
format, and bounded validation. Read and apply
[`goal-context.md`](../../references/goal-context.md) while assembling the sole
context file and the project-relative reference embedded in the GOAL.

## Persist the canonical workspace

After the candidate and context are complete in memory, invoke the shared
workspace creator exactly once as described by `goal-authoring.md`. It validates
the input, creates or validates the exact root self-ignore, writes the context,
and writes `.steward/goal.txt` last.

The allowed result is one complete workspace: canonical `goal.txt`, exactly one
referenced context file, and any unrelated untracked Steward controls that were
already present. An identical complete workspace may be reused idempotently. A
different GOAL, tracked control path, symbolic path, invalid ignore rule, or
partial workspace blocks; do not overwrite, clean, convert, or choose another
worktree.

## Output

On success, return exactly `goalContract.objective` from the creator's canonical
view, with no JSON, digest, introduction, or text after the seventh line. On a
blocker, return only the actual blocker and smallest next action. Never start
executing the GOAL.
