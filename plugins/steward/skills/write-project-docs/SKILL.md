---
name: write-project-docs
description: Review, create, update, or migrate canonical repository documentation from verified project facts. Use only for an explicit documentation request. Use write-agent-guides for the AGENTS.md hierarchy.
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
| Contribution guide (commonly `CONTRIBUTING.md`) | Development setup, commands, workflow, completion checks, and the project's design and development principles. |
| Product documentation | Users, goals, scope, requirements, flows, and acceptance criteria. |
| Architecture documentation | Current components, responsibilities, dependencies, data flow, and design decisions. |
| Development rules | Established project-specific implementation and review constraints. |

For documentation write, update, and migration requests, inspect any existing
architecture documentation against the current source, manifests, configuration,
and accepted decisions. Update verified drift and architecture changes by
default so it describes the latest implemented system. Review-only requests
remain read-only. Create an architecture document when requested or when the
work requires documenting an architectural change and none exists; do not create
one just to complete a fixed document set.

Give shared facts and policies one authoritative home and link or summarize
them where useful. Preserve valuable specialized documents and intentional
translations. Add an index when it improves navigation. A focused edit changes
only the documents it affects. Include the default contributor principles below
when creating or maintaining a contribution guide; add other documents or
policies only when the request calls for them. Preserve existing project policy
unless changing it is requested.

## Write default design and development principles

A contribution guide owns the design and development principles contributors
follow. Whenever creating or maintaining a contribution guide, include these
defaults unless the project has already adopted a different policy. Record
uncertain capability choices as working assumptions, not as observed platform
behavior:

- Treat uncertain platform capability, resource tier, and quota as design
  space: choose the looser tier and record the assumption instead of
  pre-tightening defaults for an assumed worst case.
- Assume the overwhelming majority of requests are legitimate: do not require
  preemptive abuse handling, conservative rate limits, or adversarial hardening
  the product does not need.
- Choose the best-case branch by default; worst-case handling is a named
  project decision, not inherited caution.
- Keep source files cohesive and navigable. When a file's size makes its
  responsibilities hard to distinguish, important behavior difficult to find,
  or focused changes difficult to review, split it along cohesive
  responsibilities. Follow established project size limits; use cohesion,
  navigability, and reviewability to decide when to split if no limit exists.
  Do not impose a universal line-count cap.

State the chosen branch with the observation that would trigger a revisit. Do
not present an assumed limit or permission as verified, and do not drop a limit
or obligation the project has actually accepted. In review, flag unadopted
worst-case constraints and assumptions presented as verified facts. Agent
operational rules belong to the AGENTS.md hierarchy, not the contribution guide.

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
