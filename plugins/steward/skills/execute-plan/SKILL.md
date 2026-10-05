---
name: execute-plan
description: Execute an approved implementation plan through task contracts, serial, parallel, or mixed dispatch, reviewed results, integration validation, and authorized delivery and cleanup. Use for carrying a plan through engineering delivery; not for planning-only requests or ordinary small fixes.
---

# Execute Plan

Own the execution loop and final integrated engineering result. Reuse
`plan-delivery` for scope, work packages, dependencies, and overall acceptance;
reuse `plan-handoff` for repository-grounded code contracts and evidence-based
acceptance. Their planning-only and standalone dispatch boundaries do not limit
this skill's authorized implementation, orchestration, or integration checks.
Do not move the execution loop into those skills or invent another planning
system. An approved plan fixes intent; approval of its content alone does not
authorize execution or every delivery action.

## Establish the execution baseline

Read the accepted plan and decisions, applicable guidance, current repository
state, and existing execution records. Confirm scope, integration owner, execution
mode, and already granted authority. Review requests stay read-only. Reuse granted
implementation, commit, and task-resource cleanup authorization without asking
again; distinguish each from push, PR mutation or merge, release, publication,
deployment, business data deletion, and unrelated chat/resource changes. Follow
the actual tool's creation, messaging, and deletion rules. Skill discovery is not
permission to create a visible chat or perform another restricted action.

Identify a trusted baseline and integration workspace, including relevant local
changes and their ownership. Do not reset existing work. A base commit omits
uncommitted and ignored inputs: explicitly deliver the accepted plan, contracts,
unchanged [executor protocol](../plan-handoff/references/executor-protocol.md),
dependency outputs, and necessary source/environment materials. Verify that each
executor can read the intended versions. Use project locations and existing records.

Prepare or refine contracts using
[task-contract.md](../plan-handoff/references/task-contract.md). Split by cohesive,
independently acceptable behavior, not file counts. Settle interfaces and shared
write ownership before dispatch. Keep tasks `draft` or `blocked` until actual
prerequisites exist and are usable; settled design with a future predecessor is
not `ready`. Bind contracts to plan revisions and actual outputs. Choose entry
checks and attempt budgets for this work, without universal counts.

Keep a compact execution record alongside the existing task plan: task/revision
→ executor or session → worktree → branch → result version and commit or retained
diff. Include baseline, dependency versions, actual model/effort when known,
status, evidence locations, integration decision, next action, and ownership of
resources created for this run. Use `none` for unavailable identifiers; a commit
is not mandatory without commit authority. Track engineering acceptance, required
product/external acceptance, and resource cleanup separately.

## Select and dispatch ready work

The user's serial, parallel, or mixed choice takes precedence. Otherwise choose
from dependencies, shared writes, isolation, real capacity, and handoff cost;
record the choice. Do not fix a worker count or require a new session or worktree
for every task.

- **Serial:** dispatch one ready task, inspect and accept its result, then hand
  the accepted output to the next task. Reuse a suitable executor/session and
  workspace after checking state and refreshing the assignment.
- **Parallel:** dispatch only independent ready tasks within real capacity.
  Assign distinct file/interface write responsibility and suitable isolation;
  separate worktrees do not resolve conflicting designs or shared writes.
- **Mixed:** run independent ready work concurrently while each dependency chain
  advances serially from accepted outputs. Converge through one integration owner.

All modes share contracts, evidence, recovery, and cleanup. Each assignment names
task/revision, readable plan/protocol/material locations, baseline and dependency
outputs, allowed writes, validation, attempt budget, handback conditions, result
location, and delivery authority. Avoid concurrent writes to a shared plan/result
file: use separate result artifacts or executor copies and let the integration
owner reconcile authoritative status and records.

Use the user's explicit model and effort; otherwise use host or configured
executor-tier defaults. Do not silently replace a specified model, apply a sample
model as a universal default, or upgrade against an explicit choice. If a setting
cannot be honored, report it before dependent dispatch and seek a choice only
where needed. A spent budget invokes its agreed escalation; design or requirement
issues return for contract revision rather than blind retries. `planner` tasks
stay with the integration owner. Use available executors; do not require a
particular plugin agent when another authorized execution path exists.

Read [host-adapters.md](references/host-adapters.md) for the actual host when
preparing or coordinating executors. This skill supplies instructions, not tools.
Continue independent authorized work when a capability blocks only one lane.

## Review, integrate, and validate

Review each actual diff and reopen decisive code and evidence yourself. Check
scope, contract/revisions, dependency outputs, code state, exit codes, and raw
validation output. A summary, worker `done` status, or component test pass does
not establish acceptance. Preserve returned artifacts before changing resources.
Accept or reopen tasks using `plan-handoff` criteria and record the decision.
For an in-contract defect, return the failed criterion for repair; for a
disproven assumption, design error, or gap, revise affected contracts and
invalidate dependent evidence. Never lower acceptance to fit the result.

Integrate accepted results into the integration workspace using the project's
workflow and actual authority: commits/cherry-picks when authorized, attributable
patches or diffs otherwise. Resolve integration defects within scope; route new
design decisions to the contract owner. Review the combined diff and run required
integration checks on the same final implementation version. Changes after a
check invalidate affected evidence. The main session owns final integration
validation even if an executor helps collect it; all lanes passing separately
does not prove that the combination passes.

Keep required real product/external checks explicit. Missing hardware, credentials,
live service access, or business conditions block only affected acceptance;
finish independent engineering work and record the pending condition and owner.
Simulators and fixtures do not prove real-condition results. Write acceptance
against every overall requirement. Mark the overall plan `done` only when its
required acceptance is satisfied; engineering may be accepted while the plan
still awaits product acceptance.

## Recover and finish delivery

After interruption, inspect records, existing executors, worktrees, branches,
results, and unfinished diffs before creating or dispatching anything. Reconnect
or resume suitable work after rechecking entry conditions and evidence; do not
dispatch the same active task twice. Preserve checkpoints and uncertain ownership.
A failed lane does not automatically cancel unrelated healthy work. If recovery
or a tool fails, record observed state and the smallest missing input; continue
unaffected work without assuming an operation succeeded.

When commits are authorized, commit coherent accepted changes under project
conventions and record the revision and applicable validation. Otherwise leave a
reviewable local result; implementation or plan approval does not imply commit
or push permission.

Clean only resources owned by this run, after their results are accepted and
included in the integration branch/workspace and evidence plus necessary recovery
materials are preserved. Protect failed, unreturned, or unintegrated work even
if another task succeeded. Preserve needed ignored files explicitly; a Git
snapshot may exclude them. Prefer host recoverable worktree archival where
available. Within granted cleanup authority, archive execution chats, remove
their worktrees, and delete task branches after verifying integration and
references. Worktree archival/removal and chat archival are separate operations:
verify and record each. Reused or unrelated source chats are not automatically
owned cleanup targets. Never remove the main chat, integration branch/workspace,
or unrelated resources. If cleanup lacks authority, tools, or prerequisites,
retain resources and report the exact remaining action.

Report delivered changes/revisions, inspected diffs and validation, engineering
acceptance, product/external acceptance with pending conditions, and cleanup
status. Name unverified areas and retained resources; do not claim the entire
delivery loop succeeded while required acceptance or cleanup is pending.
