---
name: write-project-docs
description: Reviews, creates, updates, or migrates canonical repository docs (README, project status, contribution guide, product, and architecture documents) from verified project facts. Writes applicable Steward default policies when creating the contribution guide; otherwise changes policy only with explicit authorization. Not for delivery plans, task progress, changelogs or release notes, code comments or API docstrings, CLAUDE.md, or agent rules and the AGENTS.md hierarchy.
---

# Write Project Documentation

## Separate facts from policy

Review-only requests return findings without editing. An explicit skill
invocation without a more specific request defaults to refreshing verified
project facts in the authorized scope. If selected implicitly and intent to
write is unclear, review only.

Invoking the skill, or asking to update or rewrite an existing document, does
not authorize policy changes to it, even for a contribution guide or other
policy authority. Preserve existing rules and their meaning; report relevant
missing policies or conflicts with Steward defaults without fixing them. In
mixed passages, edit only verifiable facts (such as command names, paths,
deployment status, and component responsibilities). If a fact cannot be
corrected without changing a rule's meaning, report it rather than rewriting
the rule.

Creating the contribution guide is the exception. A request to establish the
project's documentation creates it when the repository has no contribution
guide or other policy authority: the defaults to adopt are project policy that
needs a home. When this invocation creates it, write the applicable Steward
defaults into it as described under [Write policy](#write-policy) and list the adopted defaults in the report.
Where the user has stated a rule for the project, such as keeping backward
compatibility, write that rule in place of the default it contradicts. Omit a
default that conflicts with existing repository policy and report the
conflict. Other new documents get no defaults.

In an existing document, add, remove, or replace policy only when the user
explicitly requests a change to the specified policy or explicitly requests
replacing existing policy with Steward defaults. Stay within that authorization
and preserve any clauses the user asks to keep and any confirmed mandatory
obligations.

Record a rule the user established during the work when the user asks to
record it. A rule is established only when the user stated it as a rule, in the
request or earlier in the conversation. A rule inferred from the user's
corrections or from one-off task instructions is a candidate: list it with its
basis and write it only after the user says to. Project design, development,
and review policies belong in the contribution guide. Agent operational rules
belong in the `AGENTS.md` hierarchy: report them for
[write-agent-guides](../write-agent-guides/SKILL.md) instead of writing them
here. Report a conflict between a recorded rule and an existing one rather than
choosing between them.

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
| Architecture documentation | `docs/ARCHITECTURE.md` | Current components, responsibilities, dependencies, data flow, and design decisions. | Requirements and contributor workflow. | Requested; the work documents an architectural change and none exists; or the documentation set is being established and a verified technical design exists. |

Create a document only when its condition holds and verified content exists
for it; do not create empty documents to complete the set. An explicit
invocation in a repository that has no canonical documents yet is a request to
establish them. A request to establish the project's documentation creates each document whose condition
holds and adopts existing documents, such as an earlier product document, at
their current paths. A focused edit changes only the documents it affects and
creates no others.

For documentation write, update, and migration requests, inspect architecture
documentation involved in or affected by the request against the current source,
manifests, configuration, and accepted decisions. Correct verified drift only
within the authorized scope; report unrelated or out-of-scope drift without
editing it. A wording or link-only edit does not require an architecture audit.

Give shared facts and policies one authoritative home and link or summarize
them where useful. Preserve valuable specialized documents and intentional
translations. Add an index when it improves navigation.

Task progress, execution records, and evidence are working state, not canonical
documentation; do not write them into canonical documents. Follow any
applicable working-state policy in the root `AGENTS.md`.

Rewrite status documents in place when facts change. Do not append completion
lists, next steps, dated entries, or per-session updates. When there are few
status facts, a small README section is sufficient.

## Write policy

Use [Steward defaults](../../references/default-policies.md) to identify
relevant gaps and conflicts, and adopt defaults when creating the contribution
guide or as explicitly requested.
Apply the reference's conditions when adopting defaults. Use project evidence
for accompanying facts, such as interface locales or the operating market.

Make authorized changes in the contribution guide or other policy authority
within scope and give the rationale contributors need. If compatibility policy
is in scope for change, state the resulting rule explicitly. Link to policies
held elsewhere instead of copying them; leave agent operational policy to the
`AGENTS.md` hierarchy.

## Ground the content

Inspect relevant source, manifests, configuration, tests, CI, and existing
decisions. Check documented commands against their actual definitions and
prerequisites. Use an authorized, non-destructive local check when needed to
resolve a material uncertainty; documentation work does not require starting the
whole application or running its entire test suite.

Use [parallel-repository-research](../parallel-repository-research/SKILL.md)
when refreshing or establishing documentation for a repository with several
components needs independent searches. Handle a focused edit or a small
repository directly.

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
only if that file is also within the authorized write scope. When the same
work also runs write-agent-guides, run this skill first so the guide links
documents that exist. Use
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
