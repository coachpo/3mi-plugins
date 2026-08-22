# Strict semantic-review handoff

Read this reference only for `strict-handoff` mode, after a coordinator has
supplied the frozen inputs. The Reviewer remains read-only throughout.

## Required coordinator inputs

The coordinator owns target selection, path selection, source observation,
request construction, and every persistent artifact. Before invoking the
Reviewer it supplies:

- the exact project root and `source` or `diff` target;
- sorted exact requested regular-file paths;
- the validated adapter's `observe-source` fingerprint;
- canonical GOAL and invariant-map digests for referenced `C*` and `INV-*`;
- a frozen canonical `reviewRequest` stored at a source-excluded project path.

The Reviewer never chooses, widens, refreshes, or saves those values. If an input
is missing or inconsistent, return a strict blocker instead of constructing a
replacement.

The coordinator creates the request with the read-only validator. For source:

```text
python3 -B "<validator>" request-view --target-kind source --source-fingerprint "<source-fingerprint>" --requested-path "<path>" [--requested-path "<path>" ...]
```

For diff, also provide exact identities:

```text
python3 -B "<validator>" request-view --target-kind diff --source-fingerprint "<source-fingerprint>" --base-identity "<base>" --head-identity "<head>" --requested-path "<path>" [--requested-path "<path>" ...]
```

`request-view` reads and writes no project file. Its canonical JSON stdout binds
the target, normalized requested paths, source fingerprint, optional diff
identities, and `requestSha256`. Only the coordinator may persist those bytes,
under the already-authorized project-local write set.

## Manifest contract

Use [`semantic-review-v1.schema.json`](../../../references/semantic-review-v1.schema.json).
A new strict manifest contains both `reviewRequest` and `attestation`.

The attestation binds:

- the exact source fingerprint and canonical GOAL/invariant digests;
- a deterministic non-empty scope of project-relative regular files and their
  SHA-256 values, including every evidence, trigger, runner-source, fixture, and
  requested path;
- one outcome: `findings`, `no-findings`, or `incomplete`;
- structured `RG-*` gaps only for `incomplete`, using
  `insufficient-evidence`, `unreviewed-scope`, or `unavailable-context` and the
  concrete needed evidence.

Every requested path must appear in attestation scope for a complete result.
Missing requested paths require `unreviewed-scope` gaps whose normalized path
union is exactly the missing set. Never return complete `findings` or
`no-findings` for partial requested coverage.

Admit an `RF-*` only when the entry has exact evidence locations, a contiguous
feasible trigger path, an observable consequence, a falsifiable minimal
counterexample, and a case candidate mapped to the same `C*`, `INV-*`, and
`RF-*`. Use `observed` only for already-available execution proof and
`code-supported` for a complete static trace. Missing runner evidence leaves the
candidate runner `null` with concrete conversion blockers; never invent argv,
fixtures, capabilities, or success artifacts.

## Validate against the frozen request

Set `<validator>` to `"<skill-dir>/../../scripts/semantic_review.py"` and
validate the final JSON through standard input:

```text
python3 -B "<validator>" check - --project-root "<project-root>" --expected-review-request "<expected-request>"
python3 -B "<validator>" view - --project-root "<project-root>" --expected-review-request "<expected-request>"
```

Strict success requires exit zero plus `scopeVerified=true` and
`bindingsVerified=true`. Deliver the canonical JSON emitted by `view`, not the
draft's formatting. A baseline or request drift error requires retracing the
affected paths; never refresh a digest merely to make an old review pass.

If strict validation cannot run or fails, do not deliver strict JSON. Return the
exact error and smallest next check. A compatibility result without the frozen
binding is allowed only when the user explicitly requested compatibility output,
and must state `bindingsVerified=false`; it cannot initialize a strict campaign.

## Post-fix review

A post-fix review preserves all initialized `RF-*` IDs, required flags, and
byte-identical case-candidate bindings. Retrace each finding against the fixed
source and update only evidence-supported state. Every finding named by the fix
must become `resolved` or `invalidated`; otherwise it remains open.

The coordinator freezes a fresh expected request and uses a distinct,
source-excluded path inside the operation's frozen write set for each request and
Review handoff. The Reviewer returns
canonical stdout but never writes it. A changed finding/candidate set requires a
new campaign rather than rebinding the initialized campaign.
