---
name: draft-consensus-goal
description: Author Steward's sole machine-validated seven-line Chinese GOAL from accepted decisions and verified facts. Use for a reviewable or executable contract, including full-loop input; return it without starting execution, and externalize verified, eligible evidence by default when it will help later review or execution.
---

# Draft Consensus Goal

Return one complete GOAL contract for later review or execution. This is the
only Steward skill that authors a GOAL and owns its 4,000-code-point and
handoff branches.

This workflow requires an explicit user request for GOAL text or a GOAL input to
another explicitly requested Steward workflow.

## Authority

The request authorizes read-only fact checking and the text result. It does not
authorize implementation, changes to existing files, or reading, mutating, or
reporting host Goal or execution state. The only conditional local writes are
one new handoff, its necessary directory entries, and, when needed, its
self-ignoring rule. A caller with separate write authority may persist the
returned canonical objective outside this skill's write set.

## Author and hand off

Resolve this skill directory as `<skill-dir>`, then read and apply
[`goal-authoring.md`](../../references/goal-authoring.md). Use its detailed
evidence, strategy-authority, uncertainty, seven-line format, compression,
handoff, and bounded-validation rules. That contract is the single source for
whether a handoff is default, required, or forbidden and for its fallback or
blocking behavior.

## Output

If clarification or a required handoff blocks, return only the actual blocker
and smallest next action. Otherwise return exactly the validator `view` field
`objective`, with no JSON, digest, introduction, or text after the seventh line.
