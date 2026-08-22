---
name: draft-consensus-goal
description: Draft a machine-validated seven-line Chinese GOAL from accepted decisions and verified facts. Use when the user wants reviewable goal text without creating, inspecting, or executing a persistent Goal; a disclosed local handoff is allowed only when the compact text still exceeds the contract limit or the user requests one.
---

# Draft Consensus Goal

Return one complete GOAL contract for later review or execution. This skill is
explicit-only and never calls `get_goal`, `create_goal`, or `update_goal`.

## Boundary

The request authorizes read-only fact checking and the text result. It does not
authorize implementation or changes to existing files. The only conditional
local write is the handoff and its self-ignoring rule described by the shared
authoring contract; do not create them unless that branch is reached.

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
