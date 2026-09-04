---
name: write-agent-guides
description: "Review or maintain an evidence-based AGENTS.md hierarchy for a code repository: shared root guidance and only material subtree differences. Use write-project-docs for canonical project documentation."
---

# Write AGENTS.md Guides

Produce durable, concise repository guidance that tells coding agents where to
work, which project-specific constraints apply, and how to validate changes.
Root guidance carries shared rules; nested files contain only evidence-backed
local deltas.

## Outcome and authority

Success means every written rule has repository evidence and a clear scope, the
effective hierarchy has no harmful conflict or parent repetition, commands are
verified, and changed files plus relevant checks are reported accurately.

Review, explanation, diagnosis, report, and planning requests are read-only.
Create, repair, refresh, or update requests authorize the affected local
`AGENTS.md` edits plus non-destructive validation. Confirm external writes,
destructive replacement, unusually expensive actions, or material scope
expansion.

`CLAUDE.md` is outside this skill's write set. Do not create, repair, rewrite,
or delete it. Existing host-specific instruction files may be read when needed
to resolve applicable guidance, but this skill maintains only the `AGENTS.md`
hierarchy.

Root write permission is required only when the root file itself must change. If
an existing effective parent is valid and the user requests a proven subtree-only
delta, the authorized nested file may be updated without rewriting root. Stop
when a nested file would become an ungrounded or misleading island.

## Resolve the effective hierarchy

Detect the real repository root in multi-repository workspaces, submodules, and
nested repositories. For each affected path, read effective
`AGENTS.override.md`, `AGENTS.md`, and configured fallback files in inheritance
order. Verify which non-empty file wins in each directory and how the merged
size limit affects visibility.

Preserve accurate user rules and other managed regions. Investigate shadowed
files, parent/child conflict, active fallbacks, and uncertain provenance before
editing.

## Establish evidence

For every proposed rule, identify repository evidence for its scope: component
responsibility, entry points, change ownership, build/development/validation
commands, generated/vendor boundaries, and non-obvious safety, compatibility, or
high-risk constraints. Prefer structured code tools for symbols and boundaries;
cross-check commands against manifests, task definitions, tests, and CI. Omit or
label facts that remain uncertain after one meaningful alternative check.

## Choose hierarchy and language

Create or keep a nested `AGENTS.md` only when all are true: the subtree has a
verified local command, constraint, responsibility, or risk difference; putting
it in root would mislead other areas; and a delta-only file has independent
value. Parent repetition, directory inventories, and guesses do not qualify.
List obsolete nested files as removal candidates; deletion still needs authority.

Use the user's requested language. Otherwise preserve the effective root
guidance language, then the established repository-document language. New nested
files follow root. Never infer Simplified Chinese from a CJK percentage or use it
as a fallback for another language.

## Write and verify

Keep root independently useful, then add only necessary subtree deltas. Link
canonical project documents rather than copying their prose. Write only guidance
that changes agent behavior: responsibilities, change locations, verified
commands, project-specific invariants, generated boundaries, and high-risk areas.
Omit generic software advice, timestamps, commits, exhaustive trees, and facts
already obvious from names.

Preserve all foreign managed blocks byte-for-byte; this skill owns no managed
block of its own.

Re-read every changed file and verify hierarchy, evidence, commands, managed
boundaries, nested-file value, and merged visibility. Run
the smallest relevant non-destructive repository checks and state what was not
run. On resume, use the current working tree and effective instructions;
revalidate after relevant drift and preserve non-overlapping user changes.

## Deliver

Complete only when the intended root or subtree result exists, hierarchy choices
are evidence-backed, changed files are rechecked, and relevant validation passed
or is precisely blocked. Lead with the outcome, then only applicable material
details: changed `AGENTS.md` paths, evidence, language decision, validation,
meaningful omissions, removal candidates, risks, and the smallest next action.
