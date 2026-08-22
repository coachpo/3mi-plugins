---
name: draft-consensus-goal
description: Author Steward's sole machine-validated seven-line Chinese GOAL from accepted decisions and verified facts. Use for a reviewable or executable contract, including full-loop input; return it without starting execution, and create a disclosed local handoff only when compression still exceeds the limit or the user requests one.
---

# Draft Consensus Goal

Return one complete GOAL contract for later review or execution. This is the
only Steward skill that authors a GOAL or owns its 4,000-code-point and
conditional-handoff branch. It does not create, inspect, mutate, or report any
host execution state.

This workflow requires an explicit user request for GOAL text or a GOAL input to
another explicitly requested Steward workflow.

## Boundary

The request authorizes read-only fact checking and the text result. It does not
authorize implementation or changes to existing files. The only conditional
local write is the handoff and its self-ignoring rule described by the shared
authoring contract; do not create them unless that branch is reached. A caller
that already has separate write authority may persist the returned canonical
objective, but that is outside this skill's write set.

## Draft and validate

Resolve this skill directory as `<skill-dir>`, then read and apply
[`goal-authoring.md`](../../references/goal-authoring.md). Use its evidence,
strategy-authority, uncertainty, seven-line format, compression, handoff, and
bounded-validation rules without restating them here.

If a handoff is needed, first confirm that the resolved project root is the same
project named by the GOAL evidence. Write only below `.steward/handoffs/`. A
failed handoff requested explicitly by the user makes the delivery incomplete;
an automatic over-limit branch may fall back to a revalidated inline objective
only when it fits without the reference.

## Output

If clarification or a required handoff blocks, return only the actual blocker
and smallest next action. Otherwise return exactly the validator `view` field
`objective`, with no JSON, digest, introduction, or text after the seventh line.
