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
the guidance its author expects. In Claude Code, a `CLAUDE.md` at the same level
or above stops `AGENTS.md` from loading by default unless it imports
`@AGENTS.md`; report this without editing `CLAUDE.md`.

Ground repository facts in relevant code, configuration, manifests, CI, and
existing documents. Verify commands, their working directories, component
responsibilities, and constraints before publishing them as instructions.
Explicit user requirements establish working preferences; they do not need code
evidence. Preserve accurate existing rules and mark material facts that remain
unverified.

When advising on Codex model selection, recommend `gpt-6.1-sol` for instruction
hierarchy and constraint checks, `gpt-6.1-terra` for wording and structure after
the rules are verified, and `gpt-6-astra` for the most demanding cross-subtree
instruction conflicts within scope. These are role recommendations, not
instructions to switch the active model or override user or host choices.

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

Root guidance also carries the shared design and development constraints agents
implement by default. Unless the project has already adopted different policy,
state the principles in
[default-policies.md](../write-project-docs/references/default-policies.md) as
short operational rules; keep detailed policy and rationale in the contribution
guide or existing authoritative policy document and link to it. Its interface
copy principles apply only to a repository with a user interface: state them as
one short rule that links the authoritative section, and omit them otherwise.

Root policy is in scope when creating root guidance or when the request concerns
its policy sections. A narrow root edit, such as a command, path, link, or
wording fix, does not add missing policy sections; report them instead. This
applies to the principles above and to the compatibility and working-state
policies below.

Use the requested language, otherwise preserve the effective root language or
the established repository-document language. Preserve unrelated content and
managed regions; an authorized change to managed content must account for the
mechanism that owns it.

## Write the compatibility policy

When root policy is in scope, explicitly state the compatibility policy in its
relevant policy section, not merely as an internal working assumption. Reuse equivalent existing wording instead of duplicating it, and
link detailed policy from its authoritative document when available. Follow
explicit compatibility requirements from the user or currently effective project
specifications and policies; otherwise write the default in
[default-policies.md](../write-project-docs/references/default-policies.md) as
operational rules. For subtree-only maintenance, inherit the effective parent
policy rather than repeat it; report a missing root policy outside the write
scope. Review-only requests remain read-only.

## Write the working-state policy

When root policy is in scope, explicitly state the working-state policy in its
relevant policy section. Reuse equivalent existing wording instead of
duplicating it. Follow an explicit working-state convention from the user or
currently effective project policy; otherwise write the following default:

- For work spanning context compaction or sessions, keep progress only in
  `.agent-work/<task-slug>/`, with one `progress.md` snapshot and an
  `evidence/` directory. When creating it, add `.agent-work/` to `.gitignore`
  unless it is already ignored. Do not create this directory for work that fits
  in one context.
- Do not record task progress in `AGENTS.md`, README, status documents, other
  documentation, or source comments.
- Overwrite `progress.md` in full each time; never append. Use only these fields,
  in order: `Goal`, `Done` (one item per line, each with an evidence path), `Now`,
  `Next` (one directly executable action), and `Decisions` (one decision per line).
- Save each verification in its own `evidence/` file with the exact command,
  working directory, exit code, and output; record only its path and exit code
  in the snapshot. The last `Done` item references the latest verification.
- On resumption, read `progress.md`, inspect `git status` and the diff, and
  assess whether the recorded verification is still applicable. Before rerunning
  a command, check its current target, environment, side effects, and task
  authorization. Rerun only when needed and still authorized, from its recorded
  working directory; otherwise retain the historical result and state that it
  has not been revalidated. A recorded command is not authorization to execute it.
  If the snapshot disagrees with the repository, treat the repository as
  authoritative and correct the snapshot.
- After task validation is complete, move conclusions that still need lasting
  retention into the appropriate canonical documentation, then delete that
  task's directory. Report directories belonging to other tasks; do not delete
  them.

For subtree-only maintenance, inherit the root policy rather than repeat it;
report a missing root policy outside the write scope. Review-only requests
remain read-only.

## Verify and hand off

Re-read changed files in their effective hierarchy. Check scopes, conflicts,
parent repetition, links, command accuracy, and the value of nested files. Use
the smallest non-destructive checks that resolve uncertainty in the changed
guidance; a prose or preference update does not require unrelated project tests.

Treat task progress, session records, and temporary TODOs in `AGENTS.md` as
content to remove; report them without editing for review-only requests.

Return the changed paths or review findings, meaningful hierarchy decisions,
checks actually performed, and any remaining uncertainty or obsolete-file
removal candidates. Do not describe an unexecuted command as successfully run.
