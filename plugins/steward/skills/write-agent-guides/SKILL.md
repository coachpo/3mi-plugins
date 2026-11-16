---
name: write-agent-guides
description: Reviews, creates, or updates a repository's evidence-based AGENTS.md hierarchy with shared root guidance and material subtree differences. Changes policy only with explicit authorization. Not for canonical project documentation, CLAUDE.md, skill or subagent prompts, or user-level global instruction files.
---

# Write AGENTS.md Guides

## Separate facts from policy

Review-only requests return findings without editing. An explicit skill
invocation without a more specific request defaults to refreshing verified
project facts in the authorized scope. If selected implicitly and intent
to write is unclear, review only. Change only the affected repository
`AGENTS.md` files.

Invoking the skill, creating a guide, or asking to update or rewrite one
does not authorize policy changes. Preserve existing rules and their meaning;
report relevant missing policies or conflicts with Steward defaults without
fixing them. Do not insert defaults into new guidance either. In mixed passages,
edit only verifiable facts (such as command names, paths, deployment status, and
component responsibilities). If a fact cannot be corrected without changing a
rule's meaning, report it rather than rewriting the rule.

Add, remove, or replace policy only when the user explicitly requests a change
to the specified policy or explicitly requests replacing existing policy with
Steward defaults. Stay within that authorization and preserve any clauses the
user asks to keep and any confirmed mandatory obligations.

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
Keep facts that are still accurate and mark material facts that remain
unverified. Explicitly authorized working preferences do not need code evidence.

When documenting deployment in the root guide, put the status and production
identifiers inline using [production facts](references/production-facts.md).
Changing deployment facts does not authorize adding or replacing a migration
rule. Report any resulting conflict with the existing rule.

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

## Write authorized policy

For authorized policy changes, keep shared rules at the root and avoid
duplicating them in subtrees. If the root is outside the write scope, report
root policy findings without editing it.

State shared design and development constraints as short operational rules.
Link the authoritative policy section for detail and rationale where one
exists; otherwise state the rule without a link, and do not create a
contribution guide for this purpose. When compatibility or working-state
policy is authorized for change, state the resulting rule explicitly.
Use these references to check for policy gaps or conflicts and, only when
explicitly requested, to adopt the defaults in scope:

- [Default policies](../../references/default-policies.md) for
  design, development, compatibility, non-production data and secrets,
  authorization and Git, and commit and pull request conventions. When
  adopting defaults, apply the conditions in the reference; summarize
  applicable interface copy principles as one short rule and state any
  adopted agent operational sections in full.
- [Working-state policy](references/working-state-policy.md) for the default
  root rule on task progress and evidence.

## Verify and hand off

Re-read changed files in their effective hierarchy. Check scopes, conflicts,
repetition of a parent `AGENTS.md` in the repository, links, command accuracy, and the value of nested files. Use
the smallest non-destructive checks that resolve uncertainty in the changed
guidance; a prose or preference update does not require unrelated project tests.

Flag task progress, session records, and temporary TODOs in `AGENTS.md`;
remove them only within authorized cleanup scope.

Return the changed paths or review findings, meaningful hierarchy decisions,
checks actually performed, and any remaining uncertainty or obsolete-file
removal candidates. Do not describe an unexecuted command as successfully run.
