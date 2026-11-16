---
name: write-agent-guides
description: Reviews, creates, or updates a repository's evidence-based AGENTS.md hierarchy with shared root guidance and material subtree differences. Use when agent instructions, commands, or constraints in AGENTS.md need writing or checking. Adds default project policies to the root AGENTS.md only when asked or when creating it. Not for canonical project documentation, CLAUDE.md, skill or subagent prompts, or user-level global instruction files.
---

# Write AGENTS.md Guides

Review requests return findings without editing, and a request that does not
say whether to review or change is a review. For maintenance, change only the
affected `AGENTS.md` files in the repository.

## Resolve scope and evidence

Identify the repository boundaries and effective instruction hierarchy for each
affected path. Account for the host's overrides, configured fallback files, and
visibility limits where applicable. A shadowed or truncated file may not supply
the guidance its author expects. User-level global instruction files are part
of the effective hierarchy to read, not files this skill edits. Read them only
to find conflicts with repository guidance, and report those. Repository
guidance must stand without them: keep a rule the repository needs even when a
user-level file states it too.

Ground repository facts in relevant code, configuration, manifests, CI, and
existing documents. Verify commands, their working directories, component
responsibilities, and constraints before publishing them as instructions.
Explicit user requirements establish working preferences; they do not need code
evidence. Preserve accurate existing rules and mark material facts that remain
unverified.

## Choose and write the hierarchy

Keep or create a nested file when the subtree has an evidenced command,
responsibility, or constraint difference that would be misleading or cumbersome
as shared root guidance. Otherwise keep common rules at the root. A directory
inventory or repetition of the parent is not sufficient. Report any necessary
parent correction outside the requested write scope.

Write guidance that changes agent behavior: change locations, commands,
non-obvious invariants, generated boundaries, and explicit working preferences.
Link authoritative project documents instead of copying their contents. Avoid
generic engineering advice and exhaustive repository descriptions.

Use the requested language, otherwise preserve the effective root language or
the established repository-document language. Preserve unrelated content and
managed regions; an authorized change to managed content must account for the
mechanism that owns it.

## Write root policy when in scope

Write root policy only when the user asks for it or when the request creates
the repository's root `AGENTS.md`: add the policies it lacks. Any other root
edit does not add policies; report the missing ones instead. Subtrees
inherit root policy without repeating it; for a request that writes only
nested files, report root gaps instead.

State shared design and development constraints as short operational rules.
Link the authoritative policy section for detail and rationale where one
exists; otherwise state the rule without a link, and do not create a
contribution guide for this purpose. In the relevant sections, explicitly state
compatibility and working-state policies rather than treating them as internal
assumptions. Follow the user's requirements and effective project
specifications or policies, reusing equivalent wording. Where no applicable
policy exists, consult:

- [Default policies](../../references/default-policies.md) for
  design, development, compatibility, non-production data and secrets, and
  commit and pull request conventions.
  For repositories with a user interface, state the copy principles as one
  short rule; omit it for repositories without one. State the
  operating-context principles and the commit and pull request conventions
  only when the conditions stated in that file hold.
- [Working-state policy](references/working-state-policy.md) for the default
  policy to document in the root `AGENTS.md`.

State the project's deployment status and production identifiers inline,
following [production facts](references/production-facts.md) and the
deployment-status rule in the default policies. They are the
exception to linking instead of copying. State the branch of the migration
policy that the deployment status selects.

## Verify and hand off

Re-read changed files in their effective hierarchy. Check scopes, conflicts,
repetition of a parent `AGENTS.md` in the repository, links, command accuracy, and the value of nested files. Use
the smallest non-destructive checks that resolve uncertainty in the changed
guidance; a prose or preference update does not require unrelated project tests.

Treat task progress, session records, and temporary TODOs in `AGENTS.md` as
content to remove; report them without editing for review-only requests.

Return the changed paths or review findings, meaningful hierarchy decisions,
checks actually performed, and any remaining uncertainty or obsolete-file
removal candidates. Do not describe an unexecuted command as successfully run.
