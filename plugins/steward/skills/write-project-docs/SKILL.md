---
name: write-project-docs
description: Reviews, creates, updates, or migrates canonical repository docs (README, project status, contribution guide, product, and architecture documents) from verified project facts. Completes all applicable project policies whenever creating or updating the contribution guide or another authoritative project policy document within the authorized scope. Not for delivery plans, task progress, changelogs or release notes, code comments or API docstrings, CLAUDE.md, or agent rules and the AGENTS.md hierarchy.
---

# Write Project Documentation

Keep project documentation accurate, useful to its readers, and clear about
where each fact or policy is authoritative. Review requests are read-only, and
a request that does not say whether to review or change is a review.
Documentation changes stay within the requested scope.

## Follow the repository's documentation model

Start with the affected documents, their readers, and the evidence needed for
the request. Preserve established paths, structure, terminology, and language
unless the user requests a change. New documents follow the user's language or
the repository's existing convention, without restricting supported languages.

The repository's existing paths and authority map win. When creating documents,
or migrating in a repository with no established layout, use this default set:

| Document | Default path | Owns | Leaves out | Create when |
| --- | --- | --- | --- | --- |
| README | `README.md` | Purpose, getting started, and links to further documentation. | Detail another document in this set owns; link it. | The repository has no entry point. |
| Project status | `STATUS.md` | Only durable lifecycle, deployment, support, users, data, and compatibility facts. | Task progress, changelogs, plans, and dated work logs. | Those facts outgrow a short README section. |
| Contribution guide | `CONTRIBUTING.md` | Development setup, commands, workflow, completion checks, and the project's design, development, and review policies. | Agent operational rules, which belong in the `AGENTS.md` hierarchy. | Contributors need setup or workflow guidance, or project policy needs a home. |
| Product documentation | `docs/PRODUCT.md` | Users, goals, scope, requirements, flows, and acceptance criteria; the operating entity, operating location, and launch market; obligations confirmed as applicable and those still unconfirmed. | Implementation structure and delivery plans. | The user or accepted decisions state product facts to record. |
| Architecture documentation | `docs/ARCHITECTURE.md` | Current components, responsibilities, dependencies, data flow, and design decisions. | Requirements and contributor workflow. | Requested, or the work documents an architectural change and none exists. |

Create a document only when its condition holds and verified content exists
for it; do not create empty documents to complete the set. A focused edit
changes only the documents it affects and creates no others.

For documentation write, update, and migration requests, inspect architecture
documentation involved in or affected by the request against the current source,
manifests, configuration, and accepted decisions. Correct verified drift only
within the authorized scope; report unrelated or out-of-scope drift without
editing it. A wording or link-only edit does not require an architecture audit.

Give shared facts and policies one authoritative home and link or summarize
them where useful. Preserve valuable specialized documents and intentional
translations. Add an index when it improves navigation. Preserve existing
project policy unless changing it is requested.

Task progress, execution records, and evidence are working state, not canonical
documentation; do not write them into canonical documents. The root `AGENTS.md`
working-state policy, owned by `write-agent-guides`, says where they belong.

Rewrite status documents in place when facts change. Do not append completion
lists, next steps, dated entries, or per-session updates. When there are few
status facts, a small README section is sufficient.

## Complete project policy on every authorized policy-document write

When authorized to create or update the contribution guide or another
authoritative project policy document, check all applicable project policies
and fill missing coverage where the document is the authority. Preserve existing
policies and link to policies held elsewhere instead of copying them. Honor any
explicit limits on what may be edited; do not create or edit another policy
document to fill gaps outside the authorized scope. A request that writes only
non-policy documents neither adds nor reports policy sections.

In the contribution guide or existing authoritative policy document within
scope, explain the design and development principles with the rationale
contributors need. Explicitly state the compatibility policy in its relevant
section, not merely as an internal assumption. Follow the user's requirements
and effective project specifications or policies, reusing equivalent policy
wording. For policies not already established, consult
[default-policies.md](../../references/default-policies.md).

The non-production data and secrets section and the authorization and Git
section in the same file are agent operational policy. Leave them to the root
`AGENTS.md`, owned by
`write-agent-guides`; do not write them into the contribution guide.

The interface copy principles in the same file are conditional. State them only
when source shows the repository renders text to people through a user
interface, and add locales, units, terminology, and named exceptions only from
verified project facts. Do not write them into a repository without an
interface.

The operating-context principles and the commit and pull request conventions
in the same file are also conditional. State the operating-context principles
only for an operated product, and keep its operating entity, market, and
obligations in product documentation as project facts. State the commit and
pull request conventions only after checking the commit history, existing
guide, commit-lint configuration, and pull request templates for an established
convention, which takes precedence.

In review, report missing or conflicting policies, unadopted worst-case
constraints, and assumptions presented as verified facts. Keep agent
operational rules in the `AGENTS.md` hierarchy, not the contribution guide.

## Ground the content

Inspect relevant source, manifests, configuration, tests, CI, and existing
decisions. Check documented commands against their actual definitions and
prerequisites. Use an authorized, non-destructive local check when needed to
resolve a material uncertainty; documentation work does not require starting the
whole application or running its entire test suite.

Distinguish implemented behavior from accepted requirements, proposals, and
unverified claims. Describe architecture from actual relationships rather than
inferring a pattern from directory names. Repository contents alone may not
establish deployment, external users, the operating entity or market, or
data-retention and other mandatory obligations; preserve uncertainty rather
than inventing status or permission, and record an obligation whose
applicability is unresolved as unconfirmed, not as not applicable. Decide
whether the project has a production deployment by the deployment-status rule
in [default-policies.md](../../references/default-policies.md); a working assumption
recorded as one is not an invented status. Link decisive evidence where it
helps readers verify or maintain the document.

## Edit and migrate within scope

Update the requested content and affected summaries, indexes, and links.
For consolidation or migration, inspect incoming references and preserve unique,
still-valid information before retiring its old location. Respect the requested
migration and existing compatibility requirements; report affected references
outside the authorized scope instead of silently changing source or CI.

Preserve generated content and regions owned by other tools. For an affected
managed region, inspect its current generator or checker and follow that
contract. Ambiguous boundaries need resolution before replacing the region,
not a whole-file rewrite.

Update affected documentation links or navigation in the root `AGENTS.md`
only if that file is also within the authorized write scope. Use
[write-agent-guides](../write-agent-guides/SKILL.md) for root policy, agent
behavior, or hierarchy; `CLAUDE.md` is outside this skill's scope.

## Verify and report

Review affected facts, relative links and anchors, consistency with authoritative
sources, and the exact diff. Run applicable existing documentation checks. Do
not create static tests for wording or introduce a whole-repository validation
gate solely for a documentation edit. Keep unrelated findings separate from
in-scope failures.

During review or migration, flag scattered progress files such as `PROGRESS.md`,
`NOTES.md`, and leftover `.agent-work/` directories, as well as progress content
in status documents. For authorized migrations, move still-valid durable facts
to the document that owns them, in the repository's authority map or else the
default set, and report the rest as deletion candidates. Review-only requests report the proposed moves without editing;
do not delete other tasks' working-state directories.

When documenting or reviewing a workflow or operational decision within the
requested scope, check whether the reader can choose the correct next action at
each affected decision point. State verified conditions, responsible actors,
and exceptions where they change that action; link the authoritative source for
details. Skip this coverage check for wording, formatting, or link-only changes
that do not change meaning or the reader's next action.

Report the resulting documents or review findings, meaningful evidence and
validation, and any unresolved facts or required follow-up. State which commands
were actually run; distinguish inspection from execution.
