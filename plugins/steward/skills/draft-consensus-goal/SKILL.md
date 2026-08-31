---
name: draft-consensus-goal
description: Author Steward's sole machine-validated seven-line Chinese GOAL from accepted decisions and verified facts in one caller-provided target worktree. Use only when explicitly invoked for a reviewable or executable contract, including full-loop input; the invocation writes exactly one ignored project-local file below .steward/goal-context/ before returning the GOAL, without starting execution.
---

# Draft Consensus Goal

Return one complete GOAL contract for later review or execution. This is the
only Steward skill that authors a GOAL and owns its 4,000-code-point and
required goal-context contract.

This workflow requires an explicit user request for GOAL text or a GOAL input to
another explicitly requested Steward workflow. That explicit invocation
authorizes the narrow local write disclosed below.

## Target worktree

Require the main session or caller to provide exactly one already-resolved
session worktree root as `<target-worktree-root>`. Consume that value; never
derive it from the plugin directory, shell current directory, or another
worktree in the same repository.

Use that exact worktree for repository facts, strategy reads, and the permitted
goal-context write. The authoring contract owns binding and drift checks. A
missing, ambiguous, unresolved, mismatched, or changed binding blocks delivery.

## Authority

The request authorizes reading the caller-provided workspace root, read-only
fact checking there, and the text result. It does not authorize implementation,
changes to existing files, or reading, mutating, or reporting host Goal,
execution progress, or other host state. Its only local writes are one new file
below `.steward/goal-context/`, missing directory entries for that subtree, and,
when absent, its new self-ignoring rule. Do not overwrite existing content. A
caller with separate write authority may persist the returned canonical
objective outside this skill's write set.

## Author and preserve context

Read and apply [`goal-authoring.md`](../../references/goal-authoring.md). Use its
binding, evidence, strategy-authority, uncertainty, seven-line format,
compression, context, and bounded-validation rules. It is the single source for
goal-context eligibility, placement, write ordering, rollback, and failure
behavior.

## Output

If target binding, clarification, or goal-context creation blocks, return only
the actual blocker and smallest next action. Otherwise return exactly the
validator `view` field `objective`, with no JSON, digest, introduction, or text
after the seventh line.
