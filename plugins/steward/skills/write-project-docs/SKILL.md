---
name: write-project-docs
description: Review or maintain a repository's canonical product, status, architecture, development, contributing, and source-responsibility documentation from verified project facts. Use for focused document work, full documentation initialization/migration, STATUS-controlled static development-tier strategies, or an existing/requested invariant map; use write-agent-guides for AGENTS.md hierarchy and engineering routing.
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
document. `.steward/invariants.json` is a machine map, not documentation; create
or maintain it only when it already exists or the user explicitly requests
profile/invariant work. `CLAUDE.md` is not a canonical document and is outside
this skill's write set.

## Mode and authority

A review, explanation, diagnosis, or report request is read-only. A create,
maintain, merge, standardize, repair, or migrate request authorizes local edits
only to the documents and managed blocks affected by that request, plus relevant
non-destructive validation. It does not authorize filling every missing canonical
document.

Deletion, moves, archive/cleanup, external writes, source/configuration/CI edits,
or material scope expansion require explicit authority. Preserve generated and
other-skill managed regions. The only root `AGENTS.md` write owned here is an
existing eligible document-navigation block through its updater; engineering
routing belongs to `write-agent-guides`. Neither documentation maintenance nor
agent-guide maintenance creates or rewrites `CLAUDE.md`.

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
5. Read the shared invariant and architecture-selection contracts only when the
   invariant map exists or profile/invariant maintenance was requested. Then run
   the deterministic `architecture_profiles.py validate → select → compile`
   chain with evidence-based tri-state capabilities; never guess profiles,
   execute profile checks, or create an index for ordinary document work.
6. Update only affected and authorized files. Use the bundled updaters for owned
   marker blocks; do not hand-edit those regions or copy their implementation
   details into documentation.
7. Validate, inspect the exact diff, and correct only in-scope errors.

For a single-document request, steps concerning unrelated canonical documents,
development tier/strategy, profile/invariants, language migration, and managed
navigation are skipped. Full initialization/migration may traverse the whole
route because that outcome was explicitly requested.

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
authorized migration or cleanup. A validator proves structure, the complete
static tier catalog, selected-strategy consistency, managed-block consistency,
and local link validity; it does not inspect or require `CLAUDE.md`, and it does
not replace semantic review of the prose.
If an invariant map changed, hand engineering-router synchronization explicitly
to `write-agent-guides` before claiming the whole route is current. This skill
does not rewrite user instruction files outside its existing root navigation
block.

On resume, re-resolve the project, language, canonical paths, exact development
tier, write set, managed boundaries, and affected asset snapshots. Preserve
non-overlapping user changes; old validation is stale after a relevant input
change.

## Complete and report

Complete a write task only when every affected required document has substantive
content, owned blocks and links validate, applicable repository checks pass, and
the diff contains no out-of-set change. For migration/cleanup, strict diagnostics
must pass or the remaining unauthorized cleanup must be reported exactly.

Lead with the outcome, then list changed and deliberately preserved files,
canonical evidence, language and development-tier decisions, validation results,
cleanup candidates, unverified items, router follow-up, and the smallest
remaining action. Omit routine process narration.
