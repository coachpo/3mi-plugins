---
name: draft-consensus-goal
description: Persist an accepted seven-line Chinese GOAL, one verified context, and its acceptance intent under a caller-chosen alias in the current Git worktree, including declared waived non-required cases and writable case-byproduct files. Use only when explicitly asked to create or resume that contract; do not implement or verify it.
---

# Draft Consensus Goal

Create one immutable GOAL bundle at `.steward/goals/<alias>/` in the Git
worktree containing the current session cwd. Require the caller to choose an
alias matching lowercase ASCII letters/digits joined by single hyphens, at most
64 characters. Always use that same alias when the GOAL is later verified.

Explicit invocation authorizes repository fact checking and creation of the
selected ignored GOAL bundle. It does not authorize implementing the GOAL,
running acceptance cases, touching external state, or creating, starting, or
activating a host-managed GOAL.

Read and apply [goal-authoring.md](../../references/goal-authoring.md). Read
[goal-context.md](../../references/goal-context.md) when composing the context.
The GOAL must stay within 4,000 Unicode code points and follow the canonical
seven-line template; write the context and acceptance plan to their bundle
paths as-is. Create the bundle with the single staged-file command
`goal_workspace.py create-from --goal <alias> <staging-dir>` (plain files, no
JSON quoting); `create` with strict stdin JSON remains the alternative
transport. Declare tolerance only in the plan: a non-required case may carry
`onFailure: "waive-with-report"`, and byproduct files a case must write go into
`sourcePolicy.writable`; anything else stays strict.

On success, return the alias, `.steward/goals/<alias>/`, and the canonical
seven-line GOAL. Do not expose creator JSON, digests, or internal verification
state. On failure, report the exact blocker and smallest recovery action.
