---
name: finalize-implementation
description: Use when asked to converge on one chosen implementation or review that cutover. Rebuilds a single database baseline where allowed and retires superseded paths across code, configuration, tests, and docs. Not for routine refactoring, ordinary migrations, or generic repository cleanup.
---

# Finalize Implementation

Carry out an authorized replacement or retirement, not just behavior-preserving
deduplication. Leave one current implementation without removing obligations
that the target still needs to satisfy.

## Establish the target and scope

Use the user's decisions, effective contracts, and repository evidence to identify
the authoritative target, behavior to preserve, and contracts explicitly retired.
Names, timestamps, and default flag values do not establish which path wins.
If the target is undecided or evidence conflicts materially, identify the missing
decision and pause only dependent changes. Do not choose the final architecture.

Design and review requests stay read-only. If write intent is unclear, review
only. A clear implementation request authorizes the scoped local changes and
their validation; do not ask for approval file by file. Do not infer permission
to remove unrelated work, commit, push, release, deploy, or make external writes.

## Decide separately for target data and migration history

- **Target data:** Verify the database the command actually targets before
  resetting it. Apply the project's data rules. If the scoped non-production
  data is disposable, reset or reseed it directly as needed, without adding
  preservation machinery. The user must explicitly authorize each production
  migration, destructive action in production, or use of production or
  real-account credentials for the specific target.
- **Repository migration history:** Check the effective migration policy,
  deployment and release evidence, and upgrade, recovery, and retention
  obligations. If the project follows the [Steward migration policy](../../references/default-policies.md#compatibility-policy),
  assess deployment status using the [project evidence criteria](../../references/default-policies.md#deployment-status),
  not the environment of the current command. Do not rewrite or remove released
  migrations protected by policy or still needed by a supported upgrade or
  recovery path merely because the local database can be discarded. Keep the
  protected chain, report what blocks rebaselining, and continue independent
  authorized changes. Do not bypass the block by changing policy or adding a
  parallel development baseline.

When replacement is allowed, leave one authoritative empty-database
initialization path per independent database in scope, not necessarily one SQL
file. Build it from the final schema, constraints, indexes, and required initial
data. Leave out obsolete backfills, old-format conversions, and sample data with
no current purpose. Use the same baseline for schema initialization in development,
tests, and CI, following the project's migration tooling. Keep scenario fixtures
that exercise current behavior; they build on the baseline and are not a second
initialization path.

## Switch consumers before removing old paths

Trace actual callers, dynamic registrations, config and feature flags, scripts,
CI, and documented or external consumers. Identify which continuing contracts
each path serves. For persisted states, check writers, readers, and retained
data before removing support for a shape; an old reader can still have a live
consumer even if current code no longer writes that shape.

Move active consumers to the target, then remove superseded implementations,
aliases, fallbacks, dual paths, transitional switches, and dependencies or
intermediate artifacts used only by those paths. Move still-valid assertions and
documentation facts to the current path, including setup instructions and links.
Retain material with continuing consumers or recovery, audit, or other retention
obligations. If material consumer evidence is unresolved, keep the dependent
path and identify the gap; absence of static references alone is not enough.
Leave pre-existing untracked or ignored artifacts alone unless their removal
is authorized.

## Verify and report the result

Use the actual supported database engine and normal initialization entry point
on an authorized empty database. Exercise core reads and writes plus affected
constraints and failure cases with targeted behavior tests.

If the change affects retained data or a supported upgrade or recovery path,
verify that behavior in isolation even if migration files are unchanged. Use
fixtures with representative existing records for read/write checks. For an
affected upgrade or recovery path, exercise its normal entry point from a
representative supported prior database state or backup. A fresh-install check
does not substitute for these checks.

Inspect the combined diff and search affected entry points and references for
one-time cleanup. Keep tests that enforce current behavior, not tests whose only
purpose is to prove a file or symbol was removed.

Report full consolidation only when active entry points use the chosen target,
requested baselines are in place and verified from empty databases, core
behavior and any affected retained-data, upgrade, or recovery behavior are
verified, and retired paths are removed with no remaining required consumers.
Report the checks actually run. Distinguish completed scope (such as the runtime
cutover) from blocked scope (such as rebaselining), with retained items, their
reasons, and validation gaps. Keep this evidence in the handoff, not a permanent
cleanup log.
