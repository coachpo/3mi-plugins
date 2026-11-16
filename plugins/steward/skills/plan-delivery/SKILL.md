---
name: plan-delivery
description: Create, revise, or review a persisted implementation plan, Sprint Backlog, or both from requirements and accepted decisions. Plan work, order, dependencies, and acceptance, not schedules or staffing. Not for an in-conversation coding plan, plan mode, or execution.
---

# Plan Delivery

Produce the requested implementation plan, Sprint Backlog, or review so an
executor can tell what to deliver, what can start, in what order, and how to
accept the result. A request for one document does not require the other;
review requests return findings without editing files.

Plan content, order, and dependencies only. Do not compute or write dates,
durations, deadlines, milestones, release timelines, effort or capacity
estimates, staffing, owner or role assignments, budgets, or organizational
process, and do not add empty fields for them. Keep such fields when the user
supplies their values or an existing document already has them; do not derive
or fill them yourself. A Sprint is an ordered group of tasks, not a calendar
period.

Use the user's paths, language, and structure, then project conventions. If
none exist, save new artifacts under `docs/planning/implementation-plan.md` and
`docs/planning/sprint-backlog.md`. Adapt the level of detail to the work; no fixed
template or extra planning infrastructure is required.

## Establish the planning baseline

Read the requirements, accepted decisions, and affected existing planning
content. Distinguish accepted decisions from suggestions, assumptions, and open
choices. Identify the effect of missing inputs without inventing approval,
evidence, or a settled solution. Complete unaffected planning when a decision
blocks only part of the work.

An implementation plan owns requirement scope, work packages, dependencies, and
overall acceptance. A Backlog decomposes that plan into tasks, task
dependencies, Sprint placement and order, and completion conditions. For a
Backlog-only request, use the existing plan as authoritative and report gaps
that prevent readiness; creating or changing the plan needs to be in scope.

## Make the work executable

- Connect requirements to concrete work-package outputs and acceptance. Give
  each package a stable reference, a scope boundary, dependencies, and handoffs.
- For a Backlog, relate tasks to package obligations. Give near-term tasks
  concrete outputs, start conditions, and observable completion criteria.
  Retain future obligations and their missing refinement or readiness
  conditions rather than dropping uncertain work.
- Arrange Sprints around useful increments, priorities, and dependencies. Give
  each Sprint its content and its place in the sequence, and state the
  assumptions that sequence depends on.
- Define acceptance by the outcome, verification method, necessary conditions,
  and expected evidence. Include explicit work for shared business results and
  final integration. Planned evidence is still evidence to collect.

Use existing IDs and preserve them across revisions or Sprint moves. Give each
delivered plan and Backlog a revision, following any existing convention, and
increment it when an entry's scope, outputs, dependencies, or acceptance
change. Maintain a traceable mapping for splits, merges, or retirements.
Coverage views should refer to authoritative entries rather than duplicate
their scope and completion rules.

## Check dependencies and acceptance

A start prerequisite needs a specific usable output or condition. Interface
collaboration and final integration needs do not automatically block earlier
component work. Check cycles and order at the task or deliverable level: mutual
package links can be valid when they describe different handoffs. Depend on a
whole package only when its complete output is needed. Sprint names or numbers
alone do not establish a global execution order.

Assess distinct missing conditions by the work they affect. A missing device,
environment, access grant, or business decision need not block independent work.
Mocks, placeholders, documents, and simulators have limited acceptance scope;
retain required real implementation, integration, and final acceptance as
separate obligations. Component completion or one task referencing a package
does not establish coverage of every package deliverable and acceptance item.

## Revise and deliver

For revisions, follow the affected scope, outputs, dependencies, handoffs, and
acceptance into related entries. Synchronize only authorized artifacts; a
Backlog revision must not silently change upstream requirements or acceptance.
Preserve unrelated content and decisions.

Review the final requested artifacts for traceability, coverage, order,
dependencies, and acceptance. When both documents change,
check their final versions together. Report paths or findings and material gaps,
including unread or unavailable inputs that limit the consistency review.

Do not dispatch tasks, implement changes, or perform acceptance.
