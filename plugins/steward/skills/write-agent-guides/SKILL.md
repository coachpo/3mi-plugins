---
name: write-agent-guides
description: Review or maintain an evidence-based AGENTS.md hierarchy with shared root guidance and material subtree differences. Use for agent instructions, not canonical project documentation or CLAUDE.md.
---

# Write AGENTS.md Guides

Maintain concise repository instructions that help agents choose where to work,
respect project-specific constraints, and validate changes. Put shared rules at
the root and only useful local differences in nested files. Review requests
return findings without editing; maintenance requests change the affected
`AGENTS.md` files. This skill does not maintain `CLAUDE.md`.

## Resolve scope and evidence

Identify the repository boundaries and effective instruction hierarchy for each
affected path. Account for the host's overrides, configured fallback files, and
visibility limits where applicable. A shadowed or truncated file may not supply
the guidance its author expects.

Ground repository facts in relevant code, configuration, manifests, CI, and
existing documents. Verify commands, their working directories, component
responsibilities, and constraints before publishing them as instructions.
Explicit user requirements establish working preferences; they do not need code
evidence. Preserve accurate existing rules and mark material facts that remain
unverified.

## Choose and write the hierarchy

Keep or create a nested file when the subtree has an evidenced command,
responsibility, or constraint difference that would be misleading or cumbersome
as shared root guidance. A directory inventory or repetition of the parent is
not sufficient. A valid parent need not be rewritten for a subtree-only change;
report any necessary parent correction outside the requested write scope.

Write guidance that changes agent behavior: change locations, commands,
non-obvious invariants, generated boundaries, and explicit working preferences.
Link authoritative project documents instead of copying their contents. Avoid
generic engineering advice and exhaustive repository descriptions.

Use the requested language, otherwise preserve the effective root language or
the established repository-document language. Preserve unrelated content and
managed regions; an authorized change to managed content must account for the
mechanism that owns it.

## Verify and hand off

Re-read changed files in their effective hierarchy. Check scopes, conflicts,
parent repetition, links, command accuracy, and the value of nested files. Use
the smallest non-destructive checks that resolve uncertainty in the changed
guidance; a prose or preference update does not require unrelated project tests.

Return the changed paths or review findings, meaningful hierarchy decisions,
checks actually performed, and any remaining uncertainty or obsolete-file
removal candidates. Do not describe an unexecuted command as successfully run.
