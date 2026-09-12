---
name: draft-consensus-goal
description: Create or resume drafting a persistent Steward GOAL from accepted requirements for another executor. Use only when explicitly asked to draft that task contract; does not implement the work.
---

# Draft Consensus Goal

Create an immutable GOAL bundle at `.steward/goals/<alias>/` in the Git worktree
containing the current cwd. Use the supplied alias or choose a concise one:
lowercase ASCII letters/digits joined by single hyphens, at most 64 characters.
Reuse a compatible planning task ID when useful, and the existing alias on resume.

Draft the GOAL as a task assigned to another executor. Its outcome, scope,
authorization, blockers, and deliverables describe that executor's work using the
user's accepted requirements. Your role in this skill is to check repository
facts and create the ignored GOAL bundle; you do not implement or verify the
target work, touch external state, or activate a host-managed GOAL. Those limits
on your drafting role are not constraints on the executor's task.

Use [goal-authoring.md](../../references/goal-authoring.md) for the bundle format,
acceptance-plan contract, and creation command. These are runtime requirements
shared with verification. The creator validates them during creation; a separate
preflight is optional. On resume, load and validate the existing bundle using
`goal_workspace.py view --goal <alias>`; preserve its accepted intent and binding.

On success, return the alias, `.steward/goals/<alias>/`, and the canonical
seven-line GOAL. Do not expose creator JSON, digests, or internal verification
state. On failure, report the exact blocker and smallest recovery action.
