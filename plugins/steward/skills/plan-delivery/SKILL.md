---
name: plan-delivery
description: Create, revise, or review implementation plans and Sprint Backlogs from requirements and accepted decisions. Use for delivery planning, not development execution.
---

# Plan Delivery

Produce the requested implementation plan, Sprint Backlog, or review so an
executor can tell what to deliver, what can start, who is responsible, and how
to accept the result. A request for one document does not require the other;
review requests return findings without editing files.

Use the user's paths, language, and structure, then project conventions. If
none exist, save new artifacts under `docs/planning/implementation-plan.md` and
`docs/planning/sprint-backlog.md`. Adapt the level of detail to the work; no fixed
template or extra planning infrastructure is required.

## Establish the planning baseline

Read the requirements, accepted decisions, and affected existing planning
content. Distinguish accepted decisions from suggestions, assumptions, and open
choices. Identify the effect of missing inputs without inventing approval,
owners, evidence, or a settled solution. Complete unaffected planning when a
decision blocks only part of the work.

An implementation plan owns requirement scope, work packages, responsibilities,
dependencies, and overall acceptance. A Backlog decomposes that plan into tasks,
task dependencies, iteration placement, and completion conditions. For a
Backlog-only request, use the existing plan as authoritative and report gaps
that prevent readiness; creating or changing the plan needs to be in scope.

## Make the work executable

- Connect requirements to concrete work-package outputs and acceptance. Give
  each package a stable reference, a scope boundary, accountable and acceptance
  roles, necessary collaborators, dependencies, and handoffs.
- For a Backlog, relate tasks to package obligations. Give near-term tasks
  concrete outputs, start conditions, responsibility, and observable completion
  criteria. Retain future obligations and their missing refinement or readiness
  conditions rather than dropping uncertain work.
- Arrange Sprints around useful increments, priorities, dependencies, and actual
  capacity. Roles do not imply staffing or parallel capacity. With unknown
  availability or estimates, present a proposed sequence and its assumptions
  rather than committed dates or durations.
- Define acceptance by the outcome, verification method, necessary conditions,
  and expected evidence. Include explicit work and ownership for shared business
  results and final integration. Planned evidence is still evidence to collect.

Use existing IDs and preserve them across revisions or Sprint moves. Maintain a
traceable mapping for splits, merges, or retirements. Coverage views should refer
to authoritative entries rather than duplicate their scope and completion rules.

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

Review the final requested artifacts for traceability, coverage, dependencies,
responsibility, capacity assumptions, and acceptance. When both documents change,
check their final versions together. Report paths or findings and material gaps,
including unread or unavailable inputs that limit the consistency review.

This workflow ends at delivery planning. Use `plan-execution` when the request
needs repository-grounded, code-level contracts for a separate executor; that
handoff can also start directly from accepted requirements. This skill does not
dispatch tasks, implement changes, perform acceptance, or create a GOAL.
