---
name: draft-consensus-goal
description: Persist an accepted seven-line Chinese GOAL, one verified context, and its acceptance intent under a task alias in the current Git worktree, including declared waived non-required cases and writable case-byproduct files. Use only when explicitly asked to create or resume drafting a task contract for an executor.
---

# Draft Consensus Goal

Create one immutable GOAL bundle at `.steward/goals/<alias>/` in the Git
worktree containing the current session cwd. Use a caller-provided alias when
present; otherwise choose one without asking for it or seeking confirmation.
Aliases must match lowercase ASCII letters/digits joined by single hyphens, at
most 64 characters. For planned work, prefer the task's ID when it meets these
rules; otherwise derive a concise alias from the task. Reuse the existing alias
when resuming a GOAL, and always use that same alias when it is later verified,
so the bundle, the plan, and the verification campaign refer to the same work
without a separate status record.

Draft the GOAL as a task assigned to another executor. Its outcome, scope,
authorization, blockers, and deliverables describe that executor's work using the
user's accepted requirements. Your role in this skill is to check repository
facts and create the ignored GOAL bundle; you do not implement or verify the
target work, touch external state, or activate a host-managed GOAL. Those limits
on your drafting role are not constraints on the executor's task.

Explicit user instructions take precedence over this skill; when they conflict,
follow the user and say which instruction here you set aside. If this skill
makes you pause, ask for permission or confirmation, leave requested work
unfinished, or diverge from the user's intent, name and link to the exact
SKILL.md you read, quote the relevant instruction (and link its referenced file
if applicable), and explain how it applies. Distinguish an explicit requirement
from your interpretation.

Read and apply [goal-authoring.md](../../references/goal-authoring.md). Read
[goal-context.md](../../references/goal-context.md) when composing the context.
The GOAL must stay within 4,000 Unicode code points and follow the canonical
seven-line template in
[goal-template.txt](../../references/goal-template.txt), whose seven line
labels are required exactly as written; write the context and acceptance plan
to their bundle paths as-is. Create the bundle with the single staged-file command
`goal_workspace.py create-from --goal <alias> <staging-dir>` (plain files, no
JSON quoting); `create` with strict stdin JSON remains the alternative
transport. Declare tolerance only in the plan: a non-required case may carry
`onFailure: "waive-with-report"`, and byproduct files a case must write go into
`sourcePolicy.writable`; anything else stays strict.

On success, return the alias, `.steward/goals/<alias>/`, and the canonical
seven-line GOAL. Do not expose creator JSON, digests, or internal verification
state. On failure, report the exact blocker and smallest recovery action.
