---
name: start-consensus-goal
description: Create a machine-validated persistent Goal from accepted decisions, or resume a compatible active Goal from its current machine state. Use only when the user explicitly asks to start, resume, or finish Goal-scoped work; do not use for draft-only text, plans, status summaries, or paused Goals.
---

# Start Consensus Goal

Create a new persistent Goal only when no compatible Goal exists and the user
explicitly asks to start one. Otherwise resume the compatible current Goal. The
Goal preserves the current sandbox, approval policy, project instructions, and
request scope.

## Resolve the current Goal first

Resolve this skill directory as `<skill-dir>`, then call `get_goal` before
drafting or executing anything.

- If the read fails, do not create, update, or execute a Goal. A new-goal request
  may still receive a validated candidate plus the read error; a resume request
  receives the error and smallest retry only.
- If no Goal exists, create one only for an explicit start/create request. A
  resume, finish, status, or explanation request does not authorize creation.
- A paused Goal or a blocked Goal not restored by the host is report-only. A
  complete Goal is not repeated; a materially new request is a new objective.
- For an active Goal, treat the latest `status` and complete `objective` as the
  only state authority. Classify the objective by sending it unchanged to
  `python3 -B "<skill-dir>/../../scripts/goal_contract.py" view -`. A strict v1
  result carries stable `C*`; any other compatible objective retains its
  original contract. A classification failure is not permission to replace it.
- Continue an active Goal only when the new request is compatible with its
  result, completion criteria, scope, and authority. Ask one necessary question
  for a material conflict; never complete or block a Goal merely to replace it.

Only after these checks show that a new Goal is required, read and apply
[`goal-authoring.md`](../../references/goal-authoring.md). Restoring an existing
Goal does not load the authoring or handoff procedure.

## Create and execute

Create a new Goal with the validator's canonical `objective` exactly. Pass
`token_budget` only when the user explicitly requested one. If creation fails,
return the validated text and actual error without inventing an alternative
command.

After creation or on resume, continue in the same task. Before each major phase,
after interruption or compaction, and before any `update_goal`, call `get_goal`
again. Stop if the state is unavailable or not active. If the objective changed,
reclassify it, rebuild the remaining criteria, and revalidate affected evidence;
never complete a changed Goal with stale evidence.

Use current workspace and durable journal/campaign state to find the first
incomplete step. Treat prior progress as a clue until its source and rule state
are current. Continue while Goal-scoped, authorized work remains available; do
not repeat completed work.

For a strict v1 Goal, bind evidence obtained after the latest relevant change to
every `C*` and the current objective digest. Mark it complete only after every
criterion is verified and no required work remains. A compatible legacy Goal
uses its original completion contract. Mark blocked only when the current Goal
tool's blocking threshold is satisfied and no material progress remains; never
use difficulty, elapsed time, or budget pressure as a completion/blocking proxy.

## Deliver

Lead with the outcome. Report actual changes, evidence per `C*` or legacy
criterion, current contract digest when available, validation results, unrun
checks, assumptions, residual risks, and remaining gaps. For a budgeted Goal,
include the final token usage returned by the Goal tool after completion.
