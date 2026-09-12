---
name: write-project-docs
description: Review, create, update, or migrate canonical repository documentation from verified project facts. Use only for an explicit documentation request; a focused edit does not initialize a document suite. Use write-agent-guides for the AGENTS.md hierarchy.
---

# Write Project Documentation

Keep project documentation accurate, useful to its readers, and clear about
where each fact or policy is authoritative. Review requests are read-only;
documentation changes stay within the requested scope.

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
| Project status | Verified lifecycle, deployment, support, users, data, and compatibility facts. |
| Contribution guide | Development setup, commands, workflow, and applicable completion checks. |
| Product documentation | Users, goals, scope, requirements, flows, and acceptance criteria. |
| Architecture documentation | Current components, responsibilities, dependencies, data flow, and design decisions. |
| Development rules | Established project-specific implementation and review constraints. |

Give shared facts and policies one authoritative home and link or summarize
them where useful. Preserve valuable specialized documents and intentional
translations. Add an index when it improves navigation. A focused edit does not
require missing documents, development tiers, generic engineering policies, or
new governance. Preserve existing project policy unless changing it is requested.

## Ground the content

Inspect relevant source, manifests, configuration, tests, CI, and existing
decisions. Check documented commands against their actual definitions and
prerequisites. Use an authorized, non-destructive local check when needed to
resolve a material uncertainty; documentation work does not require starting the
whole application or running its entire test suite.

Distinguish implemented behavior from accepted requirements, proposals, and
unverified claims. Describe architecture from actual relationships rather than
inferring a pattern from directory names. Repository contents alone may not
establish deployment, external users, or data-retention obligations; preserve
uncertainty rather than inventing status or permission. Link decisive evidence
where it helps readers verify or maintain the document.

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
affected by the requested documentation change. Agent behavior and hierarchy
belong to `write-agent-guides`; `CLAUDE.md` is outside this skill's scope.

## Verify and report

Review affected facts, relative links and anchors, consistency with authoritative
sources, and the exact diff. Run applicable existing documentation checks. Do
not create static tests for wording or introduce a whole-repository validation
gate solely for a documentation edit. Keep unrelated findings separate from
in-scope failures.

Report the resulting documents or review findings, meaningful evidence and
validation, and any unresolved facts or required follow-up. State which commands
were actually run; distinguish inspection from execution.
