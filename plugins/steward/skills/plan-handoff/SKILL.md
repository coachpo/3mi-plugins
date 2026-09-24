---
name: plan-handoff
description: Create, revise, or review repository-grounded implementation task contracts for another executor. Use for code-level handoff from requirements or a Backlog, or to accept results or revise contracts from execution evidence; not for ordinary small fixes, requirements analysis, or Sprint scheduling.
---

# Plan Handoff

Turn accepted requirements into a bounded implementation contract that a qualified
executor can complete from the contract and repository without choosing the
architecture or reinterpreting the request. Not every task warrants a handoff:
simple work can be done directly, major unknowns need bounded investigation
first, and tightly coupled exploratory work may be better completed by the
planner.

This skill plans, hands off, and decides acceptance from returned evidence. It
does not dispatch tasks, implement changes, or run the executor's validation. A
request to analyze or review is read-only; create or revise files only in the
requested scope. Follow existing authorization for local writes and seek
separate authority for external or destructive actions.

## Establish authority and evidence

Use accepted requirements and decisions as the source of behavior. If an upstream
implementation plan or Backlog exists, cite its entry and revision; do not
silently rewrite it. No upstream plan is required. `analyze-change-request` owns
requirement analysis and tradeoff advice; `parallel-repository-research` can
collect read-only facts; `plan-delivery` owns work packages, Backlog, dependency
and Sprint planning. This skill owns code-level decisions, the executor
contract, and acceptance of returned results.

Inspect the actual implementation, callers, tests, configuration, and relevant
history. Reopen decisive evidence yourself, including delegated findings.
Separate observed facts from assumptions and validations not run. Settle user
behavior, interfaces, error semantics, boundaries, compatibility, data and
dependency choices, module responsibilities, migrations, acceptance, and the
exact latitude left to the executor. An unresolved choice that changes these
decisions is a planning question, not executor discretion.

## Shape ready work

Make each task one cohesive, independently acceptable behavior or deliverable
change. It may include code, tests, and necessary documentation and may depend
on a specific prior output. Do not split work by file, function, line count, or
tiny changes sharing the same context. Refine only the next stable batch; leave
future unknown work `draft` with the investigation or decision needed to make it
ready. Mark a task `ready` only when necessary design is settled, dependency
outputs actually exist and are usable, scope is bounded, and acceptance is
observable. A task waiting for a planned predecessor is still `draft` (or
`blocked` if execution has reached that missing prerequisite), even when its
design is settled; do not label it "conditionally ready."
State whether the executor may perform mechanical readiness checks and promote
a settled task once its listed prerequisites are met. Open design choices
remain with the planner; changing execution status does not revise the contract.

Use [task-contract.md](references/task-contract.md) when writing or reviewing a
handoff. Start with one `task-plan.md` at the user's or project's location;
split it only when size warrants. Include the execution and recovery protocol in
the artifact itself. Assign final integration acceptance, an owner, and coverage
of the overall requirements during planning. Completing component tasks does
not establish overall completion. Ordinary tasks with mechanical acceptance do
not each need a separate planner sign-off.

## Hand off, revise, and accept

Default to serial execution and one writer. Before execution, compare the
contract, dependency results, and relevant code with their recorded baselines
and attributable checkpoint diffs.
Unrelated drift need not trigger a full replan; a contradicted assumption or
unclear impact requires handback. Allow only concrete, described adjustments.
The executor may choose local names, code organization, existing pattern reuse,
and test data within the contract, but may not redesign behavior or relax
acceptance. It must verify facts and report contrary evidence rather than
implementing a stale plan mechanically.

On a handback, revise the affected tasks and dependencies, identify invalidated
evidence, and preserve prior results. Bind every result to plan and task
revisions, actual dependency output versions, and code state. Keep interrupted
work recoverable. A file ignored by Git does not travel between workspaces:
state how the plan, diff, and necessary evidence will actually be delivered.

To accept returned results, judge the recorded results and actual diff, not the
executor's summary. Confirm that each result binds to current plan and task
revisions, actual dependency outputs, and the reviewed code state; that the diff
stays within scope, fixed decisions, and listed discretion; and that recorded
validation output meets the pass criteria, with unrun checks named. Check the
integration evidence against every overall requirement. Missing or unverifiable
evidence, or an in-contract defect, reopens the affected task as `ready` with
the failed criterion, along with dependents whose evidence no longer applies.
Revise the contract only for a disproven assumption, design error, or
requirement gap. Write the decision, reviewed revisions, and evidence to the
acceptance record before marking the plan `done`; acceptance never lowers
criteria.

Review the final contract for requirement coverage, decisions left to the
executor, executable validation, drift and failure handling, and integration
ownership. Report the handoff location and any tasks still `draft` or `blocked`;
after an acceptance decision, report it with any reopened or revised tasks.
