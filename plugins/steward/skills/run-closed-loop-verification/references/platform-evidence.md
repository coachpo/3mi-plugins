# Platform evidence and aggregation

Read this reference only for `export-platform-evidence` or
`aggregate-platform-evidence`, after the underlying shard campaigns have been
audited successfully.

A CI-plan-derived full campaign remains an ordinary `coverageMode: "narrow"`
campaign with its journal and immutable artifacts as execution authority. Its
`verification.tier: "full"` requires every local shard case in initial and
regression, but its audit proves only that narrow entry partition even when the
base catalog is `coverageMode: "full"`. Export a platform/shard evidence bundle
only after that campaign's ordinary audit returns `ok`. The bundle contains only
successful final-regression case bindings, artifact-manifest bindings, and
declared evidence hashes; quick, initial, targeted-retest, failed, and incomplete
results never count.

The bundle binds two source identities:

- `executionSourceFingerprint` is host-sensitive and must match every exported
  final case before and after execution.
- `commit` plus `sourceFingerprint` is the portable Git identity recomputed from
  the project for cross-host comparison. Portable evidence requires a clean Git
  worktree outside the base adapter's exact `source.excludes`.

It also binds the full provider-neutral verification catalog, profile, CI plan,
and shard-specific campaign catalog. A direct export request authorizes only the
frozen deterministic `<entryId>.json` below profile
`outputs.evidenceBundles`; an aggregation request authorizes only the frozen
profile `outputs.aggregation` path. Both paths must be source-excluded. Neither
operation may overwrite an adapter, campaign file, profile, CI-plan input, input
bundle, or arbitrary excluded path.

Aggregation treats every bundle as untrusted structured input. It revalidates
bundle self-fingerprints, current profile and CI plan, portable source identity,
and the exact non-overlapping union of entries, cases, shards, and required
platforms. It fails closed on any missing, duplicate, unknown, or drifted
binding.

A successful aggregation proves only that the declared final-regression evidence
partition closes under those contracts. It does not prove semantic correctness,
remote CI policy or runner identity, authorization, artifact-transport
authenticity, or global `C*`/`INV-*`/`RF-*`/fix/guardrail semantics across
trace-stripped shards. A trace-enabled cross-platform completion claim still
needs separate same-source global audit evidence.
