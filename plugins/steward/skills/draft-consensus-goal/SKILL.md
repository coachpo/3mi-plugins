---
name: draft-consensus-goal
description: Author Steward's sole machine-validated seven-line Chinese GOAL from accepted decisions and verified facts in one caller-provided target worktree. Use for a reviewable or executable contract, including full-loop input; always create one project-local handoff before returning the GOAL, without starting execution.
---

# Draft Consensus Goal

Return one complete GOAL contract for later review or execution. This is the
only Steward skill that authors a GOAL and owns its 4,000-code-point and
required-handoff contract.

This workflow requires an explicit user request for GOAL text or a GOAL input to
another explicitly requested Steward workflow.

## Target worktree

Require the main session or caller to provide exactly one already-resolved
session worktree root as `<target-worktree-root>`. Consume that value; never
derive it from the plugin directory, shell current directory, or another
worktree in the same repository.

Use that exact worktree for every repository fact, strategy read, and handoff
path. A missing, ambiguous, unresolved, mismatched, or changed binding is a
blocker before delivery; do not write a handoff or return an objective that
references one. The authoring contract owns normalization and drift checks.

## Authority

The request authorizes reading the caller-provided workspace root, read-only
fact checking there, and the text result. It does not authorize implementation,
changes to existing files, or reading, mutating, or reporting host Goal,
execution progress, or other host state. The only required local writes are one
new handoff, its necessary directory entries, and, when needed, its
self-ignoring rule. A caller with separate write authority may persist the
returned canonical objective outside this skill's write set.

## Author and hand off

Read and apply [`goal-authoring.md`](../../references/goal-authoring.md). Use its
detailed binding, evidence, strategy-authority, uncertainty, seven-line format,
compression, handoff, and bounded-validation rules. That contract requires one
handoff for every delivered GOAL and is the single source for its eligible
content, placement, write ordering, rollback, and blocking behavior.

## Output

If target binding, clarification, or handoff creation blocks, return only the
actual blocker and smallest next action. Otherwise return exactly the validator
`view` field `objective`, with no JSON, digest, introduction, or text after the
seventh line.
