---
name: plan-delivery
description: Create, revise, or review implementation plans and Sprint Backlogs from requirements and accepted solution decisions. Use for work-package planning, task and iteration planning from an existing plan, or coordinated revisions of both documents; this skill plans delivery without executing development.
---

# Plan Delivery

Turn requirements and accepted solution decisions into an implementation plan
and, when requested, a pending Sprint Backlog. Developers should be able to tell
what to deliver, what can start, who is responsible, and how to accept the result.

Follow explicit user instructions over defaults here. Complete authorized
planning with reasonable, stated assumptions; ask only when missing information
materially affects scope, a decision, or the usefulness of the result. Continue
independent planning while awaiting an answer. If a rule here causes a pause or
departure from the request, link this file, quote the rule, and explain its effect.

## Select the requested work

| Request | Entry and deliverable |
| --- | --- |
| Create or revise an implementation plan | Use the implementation phase; a Backlog is not required. |
| Create or revise a Backlog from an existing plan | Enter the Backlog phase directly; keep the plan authoritative. |
| Deliver both documents | Establish the implementation plan, then develop its Backlog and review the final pair. |
| Revise both documents | Trace the requested changes across both phases and synchronize the authorized artifacts. |
| Review either document or the pair | Inspect the relevant phase and relationships; return findings without writing files. |

Read [planning rules and review checklist](references/planning-rules.md) for
baseline, dependency, acceptance, coverage, and revision decisions. Before a
relevant change, read the existing plan, Backlog, and their input baselines where
available. Identify the authorized write set and affected scope, references,
dependencies, and acceptance obligations. Missing or unreadable related inputs
limit the checks you can claim; they do not stop independent planning.

Distinguish accepted requirements and decisions from research suggestions,
planning assumptions, and open choices. Use only source and conversation content
actually read; inspect further project evidence only where it affects planning.
An unresolved choice needs its effect and clarification or validation work,
not an invented accepted solution.

Use the user's requested paths, language, and format, then project conventions.
Without an established convention, use `docs/planning/implementation-plan.md`
and `docs/planning/sprint-backlog.md` under the repository root. These are
planning artifacts; they do not extend the canonical document set maintained by
`write-project-docs` or require invoking that workflow.

## Implementation phase

The implementation plan owns requirement scope, work packages, responsibility
boundaries, major dependencies, and overall acceptance. Include:

- Goals, scope and exclusions, priorities, constraints, source baseline,
  accepted decisions, assumptions, risks, and open questions with affected work.
- Stable work-package IDs, linked requirements, intended results, scope
  boundaries, necessary deliverables, accountable roles, collaborators, and
  acceptance owners. Unknown people remain unassigned.
- Required upstream outputs or usable subsets, collaboration/interface
  relationships, and final integration dependencies, with clear handoffs.
- Observable acceptance outcomes, verification methods, required conditions,
  and expected evidence, including shared business and integration results.

Use [the implementation template](assets/implementation-plan.md) for a new plan
without an established structure. Adapt its presentation; keep detail
proportional to the project and use concise prose or tables as appropriate.
Add responsibility groups only when their boundaries and handoffs aid
collaboration. Roles and groups do not establish staffing or parallel capacity.

Cover each requirement with delivery and acceptance arrangements, or state what
still needs clarification or decomposition. Supporting work has its own useful
completion conditions; it need not inherit an unrelated business acceptance ID.

## Backlog phase

Use an existing implementation plan directly. If its gaps affect task planning,
complete unaffected work and identify entries that cannot yet be made ready.
When no usable plan exists, identify the missing baseline; create one only when
the request includes that work.

The Backlog owns task decomposition, task dependencies, iteration placement, and
task completion conditions, while referencing the plan's scope and acceptance.
Plan-constrained refinement still requires judgment about priorities, capacity,
current conditions, and iteration goals; it is not a mechanical rearrangement.

Use [the Backlog template](assets/sprint-backlog.md) when no existing structure
applies. Organize scheduled task records under Sprints, with a single location
for unscheduled work. Coverage views reference those records. A work package can
span Sprints, and a Sprint can combine packages.

For each Sprint, give its delivery goal, expected business increment, tasks,
order or conditional placement, capacity basis, and joint acceptance arrangement.
Each task needs a stable ID, source package and requirement references where
applicable, concrete scope and deliverables, accountable role and collaborators,
specific prerequisite outputs and start conditions, completion criteria,
verification method and conditions, expected evidence, and unresolved inputs.

Make near-term work handoff-ready. Keep uncertain future work with its retained
obligations and missing refinement or start conditions. Explain estimates and
resource assumptions; unknown capacity or dates warrant a proposed sequence,
not committed durations. Preserve independent work, conditional implementation,
and eventual real acceptance when Placeholder work can proceed sooner.

## Review, save, and hand off

Apply the shared checklist to the requested stage and its affected relationships.
When both documents are delivered or jointly revised, review the final document
pair after edits. For a plan-only request, finish the implementation-phase check;
do not generate a Backlog just to satisfy a joint check.

Synchronize necessary changes within the authorized write set. A Backlog-only
revision must preserve upstream scope and acceptance; report needed plan changes
without silently editing the plan or changing accepted decisions. If a related
document is missing, unreadable, or still out of sync, state that limitation
instead of claiming the pair passed joint review.

The session model performs the semantic checks. Do not create document-validation
scripts, parsing protocols, state stores, or control directories for this work.
For write requests, save only the requested artifacts. Return their paths or
review findings, the actual review scope, and material unresolved conditions.
Planned methods and local acceptance labels are not evidence of implementation,
real acceptance, a valid GOAL case contract, or execution authorization. This
skill does not perform research workflows, runtime tracking, task dispatch,
development, or automatic GOAL creation.
