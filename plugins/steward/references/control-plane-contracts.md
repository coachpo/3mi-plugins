# Engineering control-plane contracts

Steward is a thin coordinator over independently usable skills and
versioned machine contracts. The contracts carry stable identities and
evidence between stages; they do not grant authority, replace canonical
project documentation, or prove semantic correctness by themselves.

## Contract index

| Artifact | Stable identity and digest | Authority | Validator or consumer |
| --- | --- | --- | --- |
| Seven-line GOAL | `C1..Cn`; SHA-256 of the canonical GOAL view | The accepted Goal objective defines the requested result and completion criteria. | [`goal_contract.py`](../scripts/goal_contract.py) and [`goal-contract-v1.schema.json`](goal-contract-v1.schema.json) |
| Architecture profile package | `INV-*`, profile version, profile digest, and catalog digest | The bundled profiles are plugin-owned, versioned engineering outcomes; they are not project-local facts. | [`architecture_profiles.py`](../scripts/architecture_profiles.py) and [`architecture-profiles/`](architecture-profiles/) |
| Project invariant map | `INV-*`; SHA-256 of the canonical map view; optional profile-selection content digest | Linked project documents own policy text; `.steward/invariants.json` binds selected-profile pins, exact per-scope applicability, authority, evidence, equivalent controls, and enforcement. | [`invariant_contract.py`](../scripts/invariant_contract.py) and [`invariant-contract.md`](invariant-contract.md) |
| Semantic review | `RF-*`; SHA-256 of the canonical review `view`; optional canonical `reviewRequest` over source/diff identity, exact requested paths, and request digest; optional attestation over source fingerprint, scoped file hashes, GOAL/invariant digests, outcome, and path-bound `RG-*` gaps | Exact source evidence, a feasible trigger path, an observable consequence, and a falsifiable counterexample support each finding. Strict consumption requires scope and request bindings verified against a trusted expected request; the independent Reviewer still owns discovery and gains no write or execution authority. | [`semantic_review.py`](../scripts/semantic_review.py) and [`semantic-review-v1.schema.json`](semantic-review-v1.schema.json) |
| Project verification profile | Profile content digest plus the derived base-adapter catalog fingerprint and case IDs | The persisted provider-neutral input records reviewed project facts: Git change sources, package dependencies, guards, quick/full tiers, concrete platforms, runtime commands, and nine project-relative outputs. `validate-profile` returns a distinct validation-report envelope while keeping its nested `normalizedProfile` input-schema compatible. | [`project_verification.py`](../scripts/project_verification.py), [`verification_pipeline.py`](../scripts/verification_pipeline.py), and [`verification-profile-v1.schema.json`](project-verification/verification-profile-v1.schema.json) |
| Impact plan | Content digest; profile, verification-catalog, portable-source, Git head/tree, merge-base, and change-snapshot bindings | Re-observed committed, staged, unstaged, and untracked changes plus the profile dependency graph determine quick selection. Untrusted ownership, Git state, merge-base, high-impact paths, or selector evidence fails closed to full. | [`impact-plan-v1.schema.json`](project-verification/impact-plan-v1.schema.json) and the public `plan-impact` / `validate-impact` commands |
| CI full plan | Content digest; profile and verification-catalog fingerprints; exact entry, shard, platform, and case partition | The provider-neutral profile determines required concrete platforms and the complete full catalog. Full ignores the impact selector; selector self-tests receive their own required entry. | [`ci-plan-v1.schema.json`](project-verification/ci-plan-v1.schema.json) and the public `build-ci-plan` / `validate-ci-plan` commands |
| Verification campaign | Case IDs, `coverageMode`, source/catalog fingerprints, trace-input and Review-request digests, schema-4 per-path source snapshots, immutable run evidence, `resumeMode`, `executionStatus`, `completionStatus`, and audit rejection codes | The adapter declares project-derived runners and narrow/full coverage; the journal records what ran and the exact fix delta. Regression pass is `AUDIT_REQUIRED`; only a current successful audit is final `COMPLETE`. | [`run-closed-loop-verification`](../skills/run-closed-loop-verification/SKILL.md) |
| Platform evidence bundle and aggregation | Bundle or aggregation fingerprint plus commit, portable source, profile, verification catalog, CI plan, entry, case, and concrete-platform bindings | An already audited full shard contributes final-`PASS` artifacts only. Aggregation requires the exact non-overlapping entry/case union and every required `darwin`, `linux`, or `windows` platform. | [`platform-evidence-v1.schema.json`](project-verification/platform-evidence-v1.schema.json), [`platform-evidence-aggregation-v1.schema.json`](project-verification/platform-evidence-aggregation-v1.schema.json), and the closed-loop evidence exporter/aggregator |
| Fix audit, Review handoff, supersession, and guardrail | Failed case/attempt/round, exact changed-file delta, violated `INV-*`, root-cause source, resolved `RF-*`, post-fix Review/source/request digest, append-only stale-binding supersession, and guardrail evidence | The authorized source change, request-bound fresh read-only Review, and final-regression evidence establish the effective repair while superseded attempts remain history. | The closed-loop fix-audit, `review_handoff_recorded`, `pending_fix_superseded`, and final audit contracts |

Cross-stage handoff and trace-reference paths persisted by these contracts are
project-relative. A closed-loop journal may additionally record the absolute
`projectRoot` and `campaignRoot` resolved for its local execution. Canonical
digests are computed by the shared loaders, not from ad hoc JSON formatting or
raw GOAL bytes. IDs are carried by reference and are never renumbered or
assigned a new meaning merely to make a campaign pass.

The full-loop handoffs normally live beneath `.steward/`: canonical
`goal.txt`, deterministic `profile-selection.json` when architecture profiles
are selected, `invariants.json`, canonical `semantic-review.json`, distinct
source-excluded post-fix Review handoffs when needed, the verification adapter,
and its campaign root. Project verification adds a
provider-neutral profile, impact plan, CI full plan, derived adapters, campaign
directories, platform evidence bundles, and an aggregation report at the nine
distinct project-relative output paths declared by that profile. An explicit
full-loop request authorizes the standard project-local control artifacts needed
for that loop when the coordinator resolves, freezes, and discloses their exact
write set before the first write. It does not authorize source changes beyond
the original engineering request, paths outside that set, external mutation,
destructive or paid actions, credentials, or material scope expansion.
Draft-only and standalone read-only skills do not write full-loop artifacts. The
two Goal-authoring skills
may additionally create one handoff file and its self-ignoring rule beneath
`.steward/handoffs/`, as specified by [`handoff-file.md`](handoff-file.md);
only that temporary subtree is ignored. It is not a full-loop handoff, carries
no digest or authority, and stays out of the Git source inventory precisely because it is ignored,
while sibling control-plane files retain their existing Git behavior. The
full-loop coordinator may persist canonical Review stdout and frozen expected
Review requests only at the exact project-relative paths in the disclosed write
set. New post-fix handoffs stay within that set and do not require path-by-path
confirmation. Before source observation, the coordinator must pre-exclude those
request and Review paths, future Review handoffs, and any
adapter/control artifact that will still change; otherwise it must freeze the
source-included artifact first. A strict trace-enabled adapter binds the GOAL,
invariant, Review manifest, and `reviewRequestSha256` by their shared-loader digests. A
profile-backed invariant map also binds `profileSelection.path` and the
selection artifact's validated `contentDigest`; the invariant loader recompiles
it and rejects profile, catalog, scope, or per-scope applicability drift.

## Configuration and execution boundary

[`project_verification.py`](../scripts/project_verification.py) exposes ten
public subcommands: `validate-profile`, `plan-impact`, `validate-impact`,
`build-ci-plan`, `validate-ci-plan`, `render-adapter`, `render-local`,
`render-github`, `review`, and `configure`. It validates and renders
configuration but never executes project cases, exports or aggregates platform
evidence, or decides completion. `review`, renderer `--check`, renderer
`--expected`, and `build-ci-plan` stdout are read-only; direct renderer writes
and `build-ci-plan --output` fail closed. `configure` is the only static
projection writer and can write only its frozen, profile-declared allowlist.
The closed-loop campaign CLI is the
sole execution, evidence-export, aggregation, recovery, and audit kernel. Its
thirteen public commands are `validate-adapter`, `init`, `status`,
`observe-source`, `run`, `resume`, `record-fix`, `record-review`,
`supersede-fix`, `retest`, `audit`,
`export-platform-evidence`, and `aggregate-platform-evidence`. Its read-only
`validate-adapter` command emits a validation report without creating or
loading a campaign; its read-only `observe-source` command exposes the
adapter-selected source identity;
its `record-review` command consumes an already persisted, validated post-fix
Review under the campaign's existing write authorization and never performs
risk discovery. Source-target requests are deterministically rebound to the
fixed fingerprint; diff-target requests additionally require a separately
authorized `--expected-review-request` binding with the original kind, base,
and requested paths plus a fresh head identity. Its explicit
`supersede-fix --fix-id <exact-id>` transition is
limited to a strict pending fix whose source or recorded Review manifest is
verified stale; it appends the invalidation, preserves history, and does not
silently replace a fix or Review.

The persisted profile input requires `runtime.pluginRoot` (a project-relative
runtime path or `null`), shell-safe PATH-resolved POSIX and Windows Python
command names, and portable output path segments safe across generated Bash
and PowerShell commands for exactly these nine outputs: `profile`, `impactPlan`, `ciPlan`, `localEntry`,
`workflow`, `derivedAdapters`, `campaigns`, `evidenceBundles`, and
`aggregation`. A `validate-profile` result has schema ID
`steward.verification-profile-validation`; its top-level
`profileFingerprint`, `verificationCatalogFingerprint`, and `adapterCaseIds`
bind derived facts, while the nested `normalizedProfile` remains compatible
with the strict persisted input schema.

The generated local entry resolves the runtime from
`STEWARD_PLUGIN_ROOT` first and otherwise uses a non-null
`runtime.pluginRoot`. The GitHub projection owns the environment binding to the
pre-existing repository variable of that name. If the profile fallback is
`null`, that remote variable must point to a checked-out, repository-relative
runtime. Configuration never creates or changes the variable and must report it
as unverified.

Provider-neutral profile, impact, CI-plan, adapter, and evidence contracts do
not depend on GitHub. The GitHub renderer is one deterministic projection: it
maps `linux`, `darwin`, and `windows` to fixed hosted-runner labels, uses fixed
major versions of checkout and artifact actions, and emits no branch or path
filter or default-branch guess. It does not copy project test commands into the
workflow; generated entries delegate to the same closed-loop kernel.

## Traceability

The supported links are:

```text
C*    -> required verification case
INV-* -> triggered invariant -> required verification case
RF-*  -> falsifiable counterexample -> required verification case
fix   -> failed case + violated invariant + root-cause source
      -> fresh Review handoff -> permanent guardrail
      -> required final-regression case and evidence
stale pending fix/Review
      -> append-only supersession -> replacement fix + fresh Review handoff
```

A trace-enabled adapter binds all three control inputs—GOAL, invariant map, and
semantic-review manifest—by relative path, contract version where applicable,
and canonical digest. Every Review finding's own `criteriaIds`, `invariantIds`,
source references, runner inputs, and candidate binding are validated globally,
not only when a case already links it. The adapter maps cases to
`coversCriteria`, `coversInvariants`, `reviewFindingIds`, evidence-derived
`scenarioTags`, and an optional `quick` classification. An absent semantic
finding is represented by a complete attested empty review with outcome
`no-findings`, not by omitting the bound input. Outcome `incomplete` preserves
structured `RG-*` gaps but cannot enter a campaign.

New traceable Reviews use the optional v1 attestation to bind one source
fingerprint, scoped file hashes, and the pinned GOAL/invariant digests. Existing
unattested v1 manifests retain their previous canonical digest and remain
loadable, but do not provide machine proof of that baseline or require post-fix
re-Review. This compatibility mode must not be reported as equivalent evidence.
Strict baseline validation checks every line-bound evidence, trigger, and runner
location against the same bounded byte snapshot that established its scope hash,
then re-observes the scope so replacement drift cannot mix source observations.
The semantic loader reports `REVIEW_BASELINE_DRIFT` for stale scoped files; the
closed-loop consumer reports `REVIEW_ATTESTATION_INCOMPLETE` when a structured
incomplete outcome is offered as campaign input. Post-fix and final-audit
failures use `REVIEW_HANDOFF_REQUIRED`, `REVIEW_HANDOFF_INCOMPLETE`,
`REVIEW_HANDOFF_DRIFT`, and `SOURCE_BASELINE_MISMATCH` as documented by the
campaign evidence contract.

## Drift and completion

Changing a bound GOAL, invariant map, review manifest, adapter catalog, source
inventory, rule package, or source baseline invalidates the corresponding
evidence. Refreshing a digest without revalidating and rerunning the affected
work is not recovery. When an authorized repair changes an attested source, the
strict transition is `record-fix -> fresh read-only Review -> authorized
canonical handoff -> record-review -> retest -> same-source full regression ->
audit`. The journal binds each handoff digest and scope to its fix; the latest
Review source must equal the final-regression and currently observed source.
If source or the excluded handoff drifts before retest, the bounded recovery is
`supersede-fix -> revised record-fix -> fresh Review -> distinct handoff`.
Supersession requires the exact pending fix ID and kernel-verified source or
manifest drift; it preserves the old fix/handoff, clears only the stale pending
binding, grants no authority, and is not repair or completion.
In every schema-4 campaign, source or catalog drift during regression preserves
the attempt as `INVALIDATED`, transitions the campaign to `BLOCKED`, and
requires a new campaign root. No schema-4 campaign automatically restarts an
invalidated regression or adopts the changed source as a new baseline. The old
schema-3 bounded-restart history remains replayable only through read-only
`status` and `audit`; it is not a continuation path for the current kernel.

Quick checks and targeted retests are diagnostic evidence only. Completion is:

```text
RequestedCoverageSatisfied && audit.ok
```

For a trace-enabled campaign, requested coverage includes every required `C*`,
every triggered hard `INV-*`, every required `RF-*` through its counterexample,
each scenario class explicitly declared required by the adapter, and every
applicable permanent guardrail. An attested campaign also requires every
non-superseded post-fix Review handoff and its final source binding. All required cases must
pass one final full regression on the same source fingerprint. Quick and
`RETEST_PASSED` remain diagnostic history. Audit proves this evidence closure;
it does not claim that unmodeled behavior is semantically correct.

Project verification follows two connected paths: local changes are observed
into a validated impact plan and run as quick feedback or fail-closed full;
an exact clean CI commit is partitioned into full shards, each shard completes
ordinary closed-loop audit, and only then exports a platform evidence bundle.
Portable export and aggregation require a clean Git worktree outside the base
adapter's exact `source.excludes`; runtime outputs beneath those excludes remain
allowed. Aggregation reloads the current profile and CI plan and requires the
exact final-`PASS` entry/case partition for every required concrete platform.

CI shard adapters deliberately strip global trace mappings to contain an exact
case partition. Consequently, successful aggregation does **not** replay global
`C*`, `INV-*`, `RF-*`, fix-history, or permanent-guardrail semantics. A
trace-enabled Goal still needs separate same-source global closed-loop audit
evidence. Neither `aggregation.ok` nor `audit.ok` is semantic truth, and neither
quick nor `RETEST_PASSED` substitutes for final full regression.

The generated workflow and its platform matrix have not been run on real remote
GitHub Actions in this release. In particular, GitHub-hosted Windows and macOS
runner behavior remains unverified; local macOS execution and synthetic fixtures
are not remote-platform evidence.
