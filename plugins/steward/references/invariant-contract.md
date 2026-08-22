# Project invariant contract v1

`.steward/invariants.json` is an optional, project-local machine index.
It is not a ninth canonical document and does not replace architecture or
development prose. When the index is absent, all project-document and AGENTS
workflows retain their legacy behavior without a warning.

## Ownership

- Canonical project documents own the policy text and one explicit
  `<a id="<lower-case-invariant-id>"></a>` authority anchor for each locally
  selected invariant.
- The index binds that authority to a stable invariant, scope, applicability,
  evidence, audit status, and enforcement route.
- `write-agent-guides` alone renders the derived AGENTS router inside
  `write-agent-guides:engineering-router` markers.
- `write-project-docs` preserves that router byte-for-byte. It may maintain
  authority anchors and the index only when the index already exists or the
  user explicitly requests invariant/profile maintenance.

## Index shape

The root object has `schemaVersion` (integer `1`), `bindings` (an array sorted
by `invariantId`), and optional `profileSelection`. `profileSelection` has exact
fields `path` and `digest`: the path is a safe project-relative selection JSON
produced by the bundled selector, and the digest must equal that artifact's
validated `contentDigest`. Maps without profile bindings omit it and retain the
legacy canonical bytes, digest, and behavior. Every binding has:

- `invariantId`: `INV-<STACK>-<12 uppercase hex>`; IDs are never renumbered or
  reused. One binding carries every applicable `scopes` entry rather than
  duplicating the ID per component.
- `source`: either a pinned architecture profile
  (`kind`, `profileId`, `profileVersion`, `profileDigest`) or a project source
  (`kind`, `version`, `digest`). Profile references must match the bundled
  catalog, profile digest, and invariant membership. A project digest binds the
  locally accepted source version; semantic changes keep the ID but advance
  the version and digest.
- `scopes`: sorted, unique project-relative POSIX paths; `.` means the root.
- `trigger`: a single-line task/change condition used in the AGENTS router.
- `authority`: one selected canonical Markdown `path` and an `anchor` equal to
  the lower-case invariant ID.
- `applicability`: `applicable`, `not_applicable`, or `unverified`.
- `applicabilityByScope`: required for bindings tied to `profileSelection` and
  forbidden for project sources. Its sorted `{scope,state}` rows exactly match
  the binding scopes and the deterministically recompiled profile invariant.
  Legacy profile bindings may omit it only when the map omits
  `profileSelection`.
- `status`: `direct`, `equivalent`, `not_applicable`, `unverified`,
  `noncompliant`, `accepted_deviation`, or `migrating`.
- `evidence`: sorted project-relative path or `path#anchor` references.
- `equivalentControl`: present exactly when `status` is `equivalent`.
- `notApplicableReason`: present exactly when applicability and status are both
  `not_applicable`; the binding must also carry non-empty capability/scope
  evidence.
- `enforcement`: `kind` (`manual` or `mechanical`), sorted repository evidence,
  and optional `validationEntry`. A mechanical claim requires both resolvable
  evidence and a non-empty validation entry.

Unknown fields, duplicate JSON keys or invariant IDs, unsafe paths, table-cell
injection, broken authorities, duplicate/missing anchors, stale profile pins,
selection/catalog/content-digest drift, invented or lost per-scope
applicability, and missing mechanical validation are errors. The loader reads
and validates the pinned selection, recompiles it in memory, and requires one
binding for every compiled hard invariant; it never trusts a persisted
compiled result. The index is evidence, never authorization to execute a
command or widen scope.

When compiled profile evidence has several scope states for one invariant, the
single binding applicability is conservative: any `applicable` scope wins;
otherwise any `unverified` scope wins; `not_applicable` is allowed only when
every selected scope is not applicable and the binding records resolvable
capability/scope evidence plus `notApplicableReason`. The digest-bound compiled
scope matrix remains canonical evidence. Audit `status` is independent of this
applicability aggregation.

## AGENTS router

The derived block uses these non-nested markers:

```markdown
<!-- write-agent-guides:engineering-router:start -->
...
<!-- write-agent-guides:engineering-router:end -->
```

It contains exactly one four-column table: trigger, authority, invariant IDs,
and validation entry. Each trigger carries only its binding's triggered scopes;
per-scope `not_applicable` rows never leak into a mixed binding's route. Nested
`AGENTS.md` files inherit the root router and do not duplicate its managed
block or invariant IDs. The existing `write-project-docs:document-navigation`
block remains separate and unchanged.
