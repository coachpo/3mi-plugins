# Planning rules and review checklist

These rules serve both phases of `plan-delivery`. They describe semantic checks
for the executing session model, not a document parser or execution protocol.

## Information ownership and baseline

The implementation plan maintains requirement scope, work packages, responsibility
boundaries, major dependencies, and overall acceptance. The Backlog maintains
task decomposition, task dependencies, iteration arrangements, and task completion
conditions. It references the plan and preserves its necessary obligations.
Priorities, available capacity, current inputs, and iteration goals inform the
Backlog; its arrangement is not determined by package order alone.

Record identifiable source versions, dates, or locators actually available in
the requirements, solution decisions, plan, and Backlog. For conversations, use
the relevant conversation reference and decision date when known. Mark unread or
unavailable sources as gaps. Do not invent approval, owners, hashes, or evidence.

Distinguish confirmed requirements and decisions, unaccepted suggestions,
provisional assumptions with their basis, and open choices. Preserve unresolved
conflicts and identify their effects. A repeated assumption does not become an
accepted decision. Existing execution facts may be retained when supported, but
creating or revising a plan does not start or complete its planned work.

## Identity and traceability

Reuse project terminology and IDs. New entries need stable identifiers unique
within the project's agreed scope; require no fixed prefixes. If requirements
lack IDs, use durable source sections or clearly identified local references
without silently renumbering the source. Qualify a reference when an ID is unique
only within one document or Sprint.

Keep IDs stable across revisions and Sprint moves. If an entry is split, merged,
or retired, preserve a mapping that makes earlier references understandable.
Each task has one authoritative record; work-package and requirement views are
coverage indexes, not competing copies of scope, dependencies, or completion rules.

Trace required deliverables and applicable acceptance items to concrete tasks
or explicitly retained work awaiting refinement or conditions. One task bearing
a package ID does not prove that package's remaining deliverables or acceptance
are covered. An implementation plan alone needs package/requirement coverage,
not invented task IDs. Supporting packages use their own completion conditions;
do not force them to reference unrelated business acceptance criteria.

## Responsibility and capacity

Name accountable roles, collaborators, handoff recipients, and acceptance owners
where needed for each package and task. Task acceptance ownership may refer to
the package or Sprint when unambiguous. Mark unknown people as unassigned. A
single person may hold several roles, including acceptance when appropriate;
roles do not imply extra people or independent review capacity.

Responsibility groups are optional. Add them only when their boundaries,
interfaces, and handoffs clarify collaboration. Keep role coverage, group
organization, people, and available time distinct. State estimate and capacity
assumptions; do not infer firm dates, durations, or staffing commitments from
unknown resources.

## Dependencies, order, and readiness

Distinguish three relationships:

- **Start prerequisite:** a task needs a specific usable output or condition
  before that work can begin; identify the provider or predecessor and input.
- **Collaboration or interface:** parties coordinate a shared boundary; this
  does not by itself require either whole package to finish first.
- **Final integration dependency:** a shared result needs contributing outputs
  for joint verification, without necessarily blocking earlier component work.

Check explicit prerequisite cycles at concrete task or deliverable granularity.
A package summary can legitimately have links in both directions: standard
inventory may enable a mobile client, while final cross-device acceptance owned
by the inventory package later needs that client. Do not require an acyclic
package summary graph or treat collaboration links as blocking edges. A real
prerequisite cycle needs its affected work and a resolution; insufficient detail
means the cycle or order cannot yet be judged.

Depend on an entire package only when its complete output is necessary.
Otherwise identify the subset or intermediate handoff that unlocks a task or
its independent portion. Distinguish current input readiness from assignment
and actual scheduling capacity.

Check the proposed order against explicit prerequisites. Tasks within one Sprint
may have internal order. Conditional iterations may start when their own
conditions hold, including before other named Sprints finish. Do not derive a
global sequence solely from Sprint names or numbers. Where necessary timing or
conditions are unspecified, state what cannot be determined.

Track distinct conditions separately: business decisions, environment/toolchain,
protocol and specification, service availability, access permission, equipment,
source data, and personnel confirmation. For example, an unavailable Android
development environment, inaccessible printer, missing device protocol, and
unconfirmed accounting export fields affect different work. Independent backend,
contract, or sample-data work need not wait for every condition.

## Acceptance and shared results

For each acceptance item, record an observable outcome, verification method,
required conditions, and expected evidence. Conditions may include environments,
devices, services, access, data, documents, and people's confirmation or
participation. A local/external label alone is insufficient. For a mixed item,
split meaningful subchecks or explicitly record all necessary conditions and
evidence; satisfying one part does not close the rest.

Tests, demonstrations, business reconciliation, and human acceptance are valid
when appropriate. Define evidence to collect later, such as test results tied
to a version, a demonstrated flow, matched business records, or an identified
reviewer's confirmation. Do not claim that expected evidence already exists.

Placeholder, mock, simulator, or document acceptance has its own scope. Preserve
real implementation, integration, device verification, and final acceptance as
separate obligations when required. Assign shared business and integration
results explicit work, contributing deliverables, handoffs, an accountable owner,
and joint verification. Component completion alone does not prove the business
loop is complete. Task criteria must not weaken the plan's required acceptance.

## Coordinated revision

Before relevant modifications, read both existing planning artifacts and their
source baselines where available. Respect the user's write scope and retain
unrelated content and accepted decisions. Follow an input change through required
deliverables, package/task references, successors, handoffs, Sprint placement,
responsibility, and acceptance conditions and evidence.

When both documents may change, synchronize the necessary edits and check their
final versions together. When only one may change, keep the other authoritative
within its domain and report any required follow-up to it. Do not silently
rewrite upstream scope through Backlog refinement. A missing, unreadable, or
unsynchronized counterpart limits the consistency claim; complete independent
authorized work and explain the exact limit.

Use existing paths, format, language, and document structure unless the user asks
otherwise. Defaults are `docs/planning/implementation-plan.md` and
`docs/planning/sprint-backlog.md`; neither joins the canonical document set of
`write-project-docs`. This skill owns their specialized planning content and
relationship checks, without requiring a separate versioning, approval, status,
or GOAL system.

## Model review before delivery

Use the checklist at the level available to the requested deliverable. For a
plan-only request, check the implementation phase and relevant known relationships.
For a Backlog, check it against the available plan. For delivery or joint revision
of both documents, check the final pair. Review-only requests write no files.

1. **Identity and references:** IDs are stable and unique in their agreed scope;
   referenced entries exist; scope, terms, and authority agree across read inputs.
2. **Delivery and acceptance coverage:** every necessary deliverable and applicable
   acceptance item has work or an explicit retained gap. Inspect the actual
   obligation, not just package presence in a Sprint. Supporting work has its
   own completion conditions.
3. **Dependencies and order:** distinguish prerequisite, interface, and final
   integration relationships; check concrete prerequisite cycles and order
   contradictions without inventing a global package or Sprint ordering.
4. **Acceptance conditions and evidence:** each item has its method, actual
   necessary conditions, and expected evidence; mixed and Placeholder checks
   preserve all remaining real obligations.
5. **Handoff quality:** task scope and outputs are concrete; accountable and
   acceptance roles, resource assumptions, business loops, and integration
   ownership are clear. Unknown capacity is not presented as a schedule promise.
6. **Revision and claims:** final authorized artifacts are consistent or their
   remaining mismatch is identified. State exactly which inputs, versions, and
   relationships were reviewed, including missing or unread material.

Correct in-scope defects before delivery. Keep the review handoff concise and
accurate about remaining conditions. A model review is not machine proof,
development completion, or real acceptance evidence. Local acceptance labels do
not satisfy a GOAL case contract or grant execution authority. Do not write
document-validation scripts or add parsing protocols, state stores, control
directories, or test infrastructure. Templates are adaptable presentation aids,
not exact-heading or fixed-row contracts.
