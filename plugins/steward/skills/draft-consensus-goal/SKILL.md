---
name: draft-consensus-goal
description: Persist an accepted seven-line Chinese GOAL, one verified context, and its acceptance intent under a caller-chosen alias in the current Git worktree. Use only when explicitly asked to create or resume that contract; do not implement or verify it.
---

# Draft Consensus Goal

Create one immutable GOAL bundle at `.steward/goals/<alias>/` in the Git
worktree containing the current session cwd. Require the caller to choose an
alias matching lowercase ASCII letters/digits joined by single hyphens, at most
64 characters. Always use that same alias when the GOAL is later verified.

Explicit invocation authorizes repository fact checking and creation of the
selected ignored GOAL bundle. It does not authorize implementing the GOAL,
running acceptance cases, or touching external state.

Read and apply [goal-authoring.md](../../references/goal-authoring.md). Read
[goal-context.md](../../references/goal-context.md) when composing the context.

On success, return the alias, `.steward/goals/<alias>/`, and the canonical
seven-line GOAL. Do not expose creator JSON, digests, or internal verification
state. On failure, report the exact blocker and smallest recovery action.
