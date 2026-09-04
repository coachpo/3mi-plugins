---
name: write-project-docs
description: Review or maintain a repository's canonical product, status, architecture, development, contributing, and source-responsibility documentation from verified project facts. Use for focused document work, full documentation initialization/migration, or STATUS-controlled static development-tier strategies; use write-agent-guides for AGENTS.md hierarchy.
---

# Write Project Documentation

Keep each verified project fact or policy in one canonical document and link it
from other surfaces. A focused request changes only the affected documents; the
complete canonical set is created only for an explicit initialization or
migration request.

This workflow requires an explicit documentation request; do not expand an
ordinary engineering task into documentation maintenance.

Resolve this skill directory as `<skill-dir>`; bundled resources and scripts are
relative to it.

## Canonical boundaries

| Path | Authority |
| --- | --- |
| `README.md` | Entry, installation, ordinary startup, derived status summary, and links. |
| `STATUS.md` | Required development tier plus lifecycle, deployment, users, data, compatibility, and allowed/prohibited change facts. |
| `CONTRIBUTING.md` | Development setup, commands, workflow, the validated static current development strategy, shared principles, and definition of done. |
| `docs/README.md` | Documentation index and authority map. |
| `docs/产品说明.md` or `docs/product.md` | Product problem, users, goals, scope, flows, requirements, and acceptance. |
| `docs/架构说明.md` or `docs/architecture.md` | Current architecture, component responsibility, boundaries, dependencies, risks, and exceptions. |
| `docs/开发规范.md` or `docs/development-rules.md` | Project-specific technical and review rules. |
| `docs/源代码规模与职责规则.md` or `docs/source-code-size-and-responsibility-rules.md` | Shared source responsibility policy rendered from bundled assets. |

Root `AGENTS.md` is a navigation/agent-behavior surface, not a ninth canonical
document. `CLAUDE.md` is not a canonical document and is outside this skill's
write and validation scope.

## Mode and authority

A review, explanation, diagnosis, or report request is read-only. A create,
maintain, merge, standardize, repair, or migrate request authorizes local edits
only to the documents and managed blocks affected by that request, plus relevant
non-destructive validation. It does not authorize filling every missing canonical
document.

File deletion, moves, archival, cleanup outside the authorized document or
managed-block write set, external writes, source/configuration/CI edits, or
material scope expansion require explicit authority. Preserve generated and
other-skill managed regions. The only root `AGENTS.md` write owned here is an
existing eligible document-navigation block through its updater; engineering
routing belongs to `write-agent-guides`.

## Preserve language intent

Use the user's explicit language when supplied. Otherwise preserve the effective
root documentation/AGENTS language, then the repository's established document
language. New files follow that language. Do not use a CJK percentage heuristic
or silently convert Japanese, Traditional Chinese, or another language to
Simplified Chinese.

Bundled canonical paths and managed assets currently support Simplified Chinese
and English. If a requested managed block or new canonical path requires an
unsupported language, keep existing content unchanged and ask for the smallest
language/path decision rather than falling back to Chinese. Switching an existing
project between supported canonical language sets is an explicit migration.

## Route only the selected work

1. Resolve the actual project root, applicable instructions, affected canonical
   documents, managed boundaries, and exact write set.
2. Inspect only repository evidence needed for those documents: relevant
   manifests, source, configuration, tests, CI, commands, and existing docs.
3. Read [`document-rules.md`](references/document-rules.md) completely only when
   detailed canonical content, managed-block, merge, or migration rules are
   needed. A narrow task that does not need those details does not load it.
4. Read [`development-tiers.md`](references/development-tiers.md) completely
   when the request creates, updates, validates, migrates, or consumes the
   required development tier or managed strategy. The exact `STATUS.md` tier
   selects one bundled static strategy and never creates new authority.
5. Update only affected and authorized files. Use the bundled updaters for owned
   marker blocks; do not hand-edit those regions or copy their implementation
   details into documentation.
6. Validate, inspect the exact diff, and correct only in-scope errors.

For a single-document request, steps concerning unrelated canonical documents,
development tier/strategy, language migration, and managed navigation are
skipped. Full initialization/migration may traverse the whole route because
that outcome was explicitly requested.

## Deterministic updates and validation

Use `python3 -B` for the bundled scripts. Update source facts and the exact
development-tier line before managed blocks. When applicable, use the dedicated
development-rules, contributing, and AGENTS navigation updaters; each must
preserve other managed regions and fail closed on ambiguous markers or drift.
`update_contributing.py` is the only strategy updater and atomically migrates a
structurally valid retired dynamic-strategy block.

Run:

```text
python3 -B "<skill-dir>/scripts/validate_project_docs.py" "<project-root>"
```

Also run relevant repository documentation checks. Use strict diagnostics for an
authorized migration, file removal, archival, or other destructive cleanup. A
validator proves structure, the complete static tier catalog, selected-strategy
consistency, and managed-block consistency; it does not replace semantic review
of the prose or check local link validity — report broken or stale links you
notice while reading, but do not treat link-checking as automated.

On resume, re-resolve the project, language, canonical paths, exact development
tier, write set, managed boundaries, and affected asset snapshots. Preserve
non-overlapping user changes; old validation is stale after a relevant input
change.

## Complete and report

Complete a write task only when every affected required document has substantive
content, owned blocks validate, applicable repository checks pass, and the diff
contains no out-of-set change. For migration or destructive cleanup, strict
diagnostics must pass or the remaining unauthorized cleanup must be reported
exactly.

Lead with the outcome, then list changed and deliberately preserved files,
canonical evidence, language and development-tier decisions, validation results,
cleanup candidates, unverified items, and the smallest remaining action. Omit
routine process narration.
