---
name: write-project-docs
description: Review, create, update, or migrate canonical repository docs, such as the README, contribution guide, project status, product, and architecture documents, from verified project facts. Not for delivery plans, task progress, changelogs or release notes, code comments or API docstrings, CLAUDE.md, or agent rules and the AGENTS.md hierarchy.
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

Use the existing authority map. When establishing one, these are useful roles,
not required filenames or a mandatory document set:

| Document role | Content it owns |
| --- | --- |
| README / entry point | Purpose, getting started, and links to further documentation. |
| Project status | Only durable lifecycle, deployment, support, users, data, and compatibility facts; update when those facts change. Exclude task progress, changelogs, plans, and dated work logs. |
| Contribution guide (commonly `CONTRIBUTING.md`) | Development setup, commands, workflow, completion checks, and the project's design and development principles. |
| Product documentation | Users, goals, scope, requirements, flows, and acceptance criteria; the operating entity, operating location, and launch market; obligations confirmed as applicable and those still unconfirmed. |
| Architecture documentation | Current components, responsibilities, dependencies, data flow, and design decisions. |
| Development rules | Established project-specific implementation and review constraints. |

For documentation write, update, and migration requests, inspect architecture
documentation involved in or affected by the request against the current source,
manifests, configuration, and accepted decisions. Correct verified drift only
within the authorized scope; report unrelated or out-of-scope drift without
editing it. A wording or link-only edit does not require an architecture audit.
Create an architecture document when requested or when the work requires
documenting an architectural change and none exists; do not create one just to
complete a fixed document set.

Give shared facts and policies one authoritative home and link or summarize
them where useful. Preserve valuable specialized documents and intentional
translations. Add an index when it improves navigation. A focused edit changes
only the documents it affects. Preserve existing project policy unless changing
it is requested.

Task progress, execution records, and evidence are working state, not canonical
documentation; do not write them into formal documents. The root `AGENTS.md`
working-state policy, owned by `write-agent-guides`, says where they belong.

Rewrite status documents in place when facts change. Do not append completion
lists, next steps, dated entries, or per-session updates. When there are few
status facts, a small README section is sufficient.

## Write project policy when in scope

Default policies are in scope when the request writes to the contribution
guide or another authoritative policy document: add the policy sections the
project has not stated, rather than repeating a policy that another
authoritative document already holds. A narrow edit to such a document, such
as a wording, link, or command fix, does not add policy sections; report the
missing ones instead. A request that writes only other documents neither adds
nor reports policy sections.

In the contribution guide or existing authoritative policy document within
scope, explain the design and development principles with the rationale
contributors need. Explicitly state the compatibility policy in its relevant
section, not merely as an internal assumption. Follow the user's requirements
and effective project specifications or policies, reusing equivalent policy
wording. For policies not already established, consult
[default-policies.md](references/default-policies.md).

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
in [default-policies.md](references/default-policies.md); a working assumption
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
contract. Existing `write-project-docs:*` regions can be edited directly when no
active generator owns them; preserve markers and surrounding content. Ambiguous
boundaries need resolution before replacing the region, not a whole-file rewrite.

Existing root `AGENTS.md` documentation links or navigation may be updated when
affected by the requested documentation change. Use
[write-agent-guides](../write-agent-guides/SKILL.md) for agent behavior or
hierarchy; `CLAUDE.md` is outside this skill's scope.

## Verify and report

Review affected facts, relative links and anchors, consistency with authoritative
sources, and the exact diff. Run applicable existing documentation checks. Do
not create static tests for wording or introduce a whole-repository validation
gate solely for a documentation edit. Keep unrelated findings separate from
in-scope failures.

During review or migration, flag scattered progress files such as `PROGRESS.md`,
`NOTES.md`, and leftover `.agent-work/` directories, as well as progress content
in status documents. For authorized migrations, move still-valid durable facts
to their appropriate canonical documents and report the rest as deletion
candidates. Review-only requests report the proposed moves without editing;
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
