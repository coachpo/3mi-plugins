# Project adapter contract

## Trust and path boundary

An adapter is executable, untrusted project input, not proof of user authorization. Before `init` or execution, review the selected executable, every argv element, `cwd`, fixture behavior, expected side effects, external capabilities, timeout, source inventory, and evidence contract. Use argv arrays without implicit shell parsing; remember that an explicitly selected executable can itself be a shell.

Use adapter `schemaVersion: 1`. Resolve a relative `projectRoot` from the adapter directory and all other project paths from `projectRoot`. Keep `campaignRoot`, case working directories, fixtures, source files or manifest, and evidence within the project root. The kernel rejects traversal, NUL bytes, unsafe path encodings, and symlink/reparse aliases component by component. Campaign journal/state ownership is limited to `campaignRoot` and descendants. A direct platform export or aggregation request authorizes only the exact frozen profile-declared `outputs.evidenceBundles/<entryId>.json` or `outputs.aggregation` path outside `campaignRoot`.

Place the campaign directory under the project root and cover it with a precise `source.excludes` entry. Do not exclude the entire project or use an alias that can reach the campaign directory through another path.

## Schema

Use the bundled [`project-adapter.template.json`](../assets/project-adapter.template.json) as a starting point. The required shape is:

```json
{
  "schemaVersion": 1,
  "projectId": "sample-project",
  "projectRoot": ".",
  "campaignRoot": ".closed-loop-verification",
  "coverageMode": "narrow",
  "source": {
    "provider": "manifest",
    "manifest": "verification-source.json",
    "excludes": [".closed-loop-verification"]
  },
  "localOnly": {
    "enabled": true,
    "allowedExternalCapabilities": []
  },
  "cases": []
}
```

Kernel-owned objects reject unknown fields and wrong JSON types. In particular, `localOnly.enabled` and each case's `required` are booleans, `timeoutSeconds` is finite and within the kernel limit, and `platform` is one of `any`, `darwin`, `linux`, `windows`, or `posix`. Arrays must contain only the documented element type. Fixture objects remain project-defined, but every value participates in secret scanning and the catalog fingerprint.

The optional top-level `coverageMode` is `narrow` or `full` and defaults to `narrow`. Full mode requires at least one required case in every supported risk tier: `smoke`, `functional`, `integration`, `workflow`, and `role-play`; an optional-only tier does not count, and adapter validation fails if any required tier is missing. Narrow mode accepts a smaller catalog but the normalized coverage report derives `presentTiers` from required cases and lists every absent required category in both `missingTiers` and `outOfScopeTiers`. A full report has an empty `missingTiers` and `outOfScopeTiers`; campaign status and audit additionally expose `verifiedTiers` and `unverifiedTiers` from required-case final-regression `PASS` evidence. `coverageMode` participates in adapter normalization and the catalog fingerprint; changing it requires a new campaign root.

The traceability extension is optional. An existing schema-version-1 adapter without `traceability`, `coversCriteria`, `coversInvariants`, `reviewFindingIds`, `scenarioTags`, or `quick` remains valid and keeps its legacy coverage semantics. The independent `quick` flag may be used without traceability; the four mapping/tag arrays must be absent or empty in that mode. Do not add empty placeholder trace inputs to a legacy campaign.

## Optional traceability references

When stable project contracts already exist, add this top-level object:

```json
{
  "traceability": {
    "goalContract": {
      "path": ".steward/goal.txt",
      "contractVersion": 1,
      "sha256": "sha256:replace-with-canonical-goal-contract-digest"
    },
    "invariants": {
      "path": ".steward/invariants.json",
      "sha256": "sha256:replace-with-invariant-contract-digest"
    },
    "reviewFindings": {
      "path": ".steward/semantic-review.json",
      "sha256": "sha256:replace-with-review-contract-digest",
      "reviewRequestSha256": "sha256:replace-with-request-binding-digest"
    },
    "requiredScenarios": ["failure", "compatibility", "platform"]
  }
}
```

The top-level `traceability` object is optional. When present, `goalContract`, `invariants`, and `reviewFindings` are all required exact references; this keeps trace-enabled and legacy modes unambiguous. `reviewRequestSha256` is optional only for compatibility, but a manifest with `reviewRequest` requires it and a pin requires the manifest request. Their canonical request digests must match exactly. `requiredScenarios` is optional and defaults to an empty array. Reference paths are project-relative regular files within `projectRoot` and outside `campaignRoot`, with no traversal or symlink/reparse component. Digests use `sha256:` followed by 64 lowercase hexadecimal characters. `requiredScenarios` is a unique array drawn from `failure`, `compatibility`, and `platform`; it declares scenario classes that final acceptance must prove.

- `goalContract` references the shared seven-line GOAL contract. `contractVersion` is `1`. Its digest is SHA-256 of the canonical version-1 JSON view returned by `python3 -B "<skill-dir>/../../scripts/goal_contract.py" digest "<goal-contract-path>"`, excluding the transport newline; it is not a digest of the raw GOAL file bytes or a source-checkout-specific path.
- `invariants` references a versioned manifest accepted by the shared invariant contract loader. Use the loader's canonical digest. Every authority file, exact anchor, project-source digest, and evidence reference must validate against `projectRoot`; a broken referenced file is trace-input drift even when the invariant-map JSON and digest are unchanged. Audit derives the currently triggered hard-invariant IDs from that validated contract.
- `reviewFindings` references a versioned manifest accepted by the shared review-finding contract loader. Use the loader's canonical `view` digest. Every finding, including optional or not-yet-linked findings, must reference only GOAL criteria and triggered hard invariants exposed by the other two trace inputs. Every finding evidence and trigger location, path-valued fixture, runner execution input, and runner source-evidence location must be a regular non-link file in the effective source inventory.

For new traceable campaigns, include `attestation` and the coordinator-frozen `reviewRequest` in `semantic-review v1`, then pin the request digest in the adapter. The request records a `source` or `diff` target, its source fingerprint, sorted unique requested project paths, and its canonical digest. The attestation records the same observed `sourceFingerprint`, exact GOAL/invariant canonical digests, one complete `findings` or `no-findings` outcome, a non-empty scope of project-relative file SHA-256 bindings, and an empty gaps array. An `incomplete` outcome carries structured `RG-*` gaps and is valid Review output but not valid campaign input; the consumer rejects it as `REVIEW_ATTESTATION_INCOMPLETE`. Complete strict input must cover every requested path plus every finding and runner reference. Its hashes and whole-source fingerprint must match one source observation. During strict baseline validation, all line-bound finding and runner locations are checked against the same bounded bytes that established each scope hash, followed by an exact scope re-observation; independent file reads cannot silently mix baselines. Use the read-only command below to obtain that fingerprint rather than reimplementing the provider:

```text
python3 -B "<skill-dir>/scripts/campaign.py" observe-source --adapter "path/to/adapter.json"
```

The result contains `sourceFingerprint`, sorted `paths`, and sorted present-file `{path, sha256}` entries under `files`. It does not write or initialize a campaign. Before invoking it for an initial attestation, ensure that the intended Review handoff, future post-fix handoffs, and every adapter/control artifact that will still be modified are excluded from this source inventory; alternatively freeze any source-included artifact before observation. Writing a source-included Review afterward makes its claimed fingerprint stale.

`reviewRequest` remains optional only for compatibility. A v1 manifest without it retains readable earlier trace semantics, including when an old attestation is present, but is classified `legacy`, never `bindingsVerified`, and does not enable strict post-fix `record-review` requirements. Use a new campaign root with an attestation, request, and adapter digest pin when exact requested-scope evidence is required.

The kernel validates the supplied digests when initializing, records the normalized trace contracts, full request, `bindingsVerified`, and immutable finding/candidate bindings in journal schema 4, and observes the references again for status, execution, and audit. A missing reference, content change, version change, path substitution, request change, attested-scope change, source-baseline mismatch, or digest mismatch is `TRACE_INPUT_DRIFT`; do not edit old journal state or update a pinned digest in place. Adapter trace references and all case mappings participate in the catalog fingerprint. Public commands report the pinned mode as exactly `none`, `legacy`, or `attested`; the former means no traceability object, `legacy` means the exact request binding is absent, and `attested` means attestation, request, adapter pin, and verified binding all agree.

## Optional verification-profile binding

Adapters deterministically derived from a provider-neutral verification profile add this top-level object:

```json
{
  "verification": {
    "contractVersion": 1,
    "profile": {
      "path": ".steward/verification-profile.json",
      "sha256": "sha256:replace-with-canonical-profile-digest"
    },
    "verificationCatalogFingerprint": "sha256:replace-with-full-catalog-digest",
    "tier": "quick",
    "impactPlan": {
      "path": ".steward/runtime/impact-plan.json",
      "sha256": "sha256:replace-with-canonical-impact-plan-digest"
    },
    "ciPlan": null
  }
}
```

All referenced paths are project-relative regular files within `projectRoot` and outside `campaignRoot`. The profile and selected plan are reloaded and digest-checked whenever the adapter is validated. The exact `verification` value participates in the campaign catalog fingerprint and is preserved in the initialized journal catalog; a stale profile, plan, source observation, case selection, or fingerprint is a configuration error rather than a new campaign baseline.

- A `quick` adapter binds exactly one quick-mode impact plan, retains the complete base catalog, and mirrors `impact.selectedCaseIds` through case `quick` flags. It may run `--phase quick`; ordinary initial and regression commands still execute the complete catalog.
- A local `full` fallback adapter binds exactly one full-mode impact plan, retains the complete base catalog, and preserves the base `coverageMode`. A CI `full` adapter instead binds one CI plan and `entryId`, contains exactly that entry's case partition, emits `coverageMode: "narrow"`, and omits global traceability and case trace mappings. Here `verification.tier: "full"` means run every case in that shard through initial and regression; it does not let one shard claim the five-tier breadth of a base `coverageMode: "full"` catalog. The shard keeps the base `verificationCatalogFingerprint`, while its own campaign catalog fingerprint remains shard-specific. Current aggregation reloads that base fingerprint and the exact CI-plan partition to prove all declared entries/cases reached final PASS, but does not replay global C*/INV*/RF*, fix-history, or permanent-guardrail trace semantics across those shards. An explicit quick phase is rejected for every full-tier adapter.
- A legacy adapter without `verification` remains valid and does not need the profile/configuration layer.

Source providers are:

- `git`: fingerprint tracked and non-ignored untracked entries after exact excludes; require the Git root to equal `projectRoot`.
- `manifest`: read a JSON array of relative paths or an object containing a `files` array; fingerprint the manifest and each listed entry. The manifest itself cannot be excluded.
- `files`: fingerprint the explicit relative paths in `source.files`.

The fingerprint binds raw relative path identity, content, size, and mode. The effective project-source inventory after excludes must remain non-empty for every provider; a manifest control file alone is not project source. On POSIX, a backslash remains a filename character rather than becoming a separator. Gitlink entries bind their mode and object ID. Fail closed when a path cannot be represented without changing its identity.

## Cases and evidence

Each case has this shape:

```json
{
  "id": "smoke-cli",
  "category": "smoke",
  "required": true,
  "quick": true,
  "platform": "any",
  "dependsOn": [],
  "coversCriteria": ["C1"],
  "coversInvariants": ["INV-CORE-0123456789AB"],
  "reviewFindingIds": ["RF-EXAMPLE-001"],
  "scenarioTags": ["failure"],
  "argv": ["python3", "-c", "..."],
  "cwd": ".",
  "timeoutSeconds": 30,
  "fixture": null,
  "externalCapabilities": [],
  "evidence": {
    "requiredFiles": ["proof.json"],
    "nonEmptyFiles": ["proof.json"]
  }
}
```

The four trace mapping/tag arrays and the independent `quick` flag are optional. When omitted, `quick` is false and each ID/tag list is empty. Without top-level `traceability`, the mapping/tag arrays must remain absent or empty, while `quick` remains available.

- `coversCriteria` contains unique stable IDs matching `C[1-9][0-9]*` and exposed by the referenced GOAL contract.
- `coversInvariants` contains unique stable IDs matching `INV-[A-Z][A-Z0-9]*-[0-9A-F]{12}` and exposed by the referenced invariant contract.
- `reviewFindingIds` contains unique stable IDs matching `RF-[A-Z0-9][A-Z0-9-]*` and exposed by the referenced review-finding contract.
- `scenarioTags` is a unique subset of `failure`, `compatibility`, and `platform` describing scenario classes the case actually proves.
- `quick: true` makes the case eligible for a low-cost `quick` attempt. It does not exclude the case from ordinary initial or regression execution. Keep quick dependencies earlier and quick-eligible so a quick attempt never relies on an unexecuted full-only prerequisite.

Unknown IDs, duplicate IDs, trace-mapping fields without a top-level `traceability` object, or case mappings inconsistent with the loaded contracts are configuration errors. The same global ID checks apply to each Review finding's own `criteriaIds` and `invariantIds` even when no adapter case links that finding. A mapping asserts relevance only; it does not by itself prove coverage or resolve a finding.

A case linked through `reviewFindingIds` must exactly bind its finding's executable `caseCandidate.runner`. The candidate runner must be non-null with empty `conversionBlockers`; adapter `argv`, normalized `cwd`, `timeoutSeconds`, fixture, capabilities, and evidence contract must match it. Its project execution inputs require source evidence even if the finding is optional or not linked. A prose-only candidate cannot be replaced with an arbitrary always-passing command.

Use a non-empty string array for `argv`; do not add `shell`, `command`, `env`, interpolation, credentials, or secret-bearing values. Dependencies must name earlier cases. The child receives its fresh evidence directory through `CLOSED_LOOP_EVIDENCE_DIR`. Declared evidence paths are relative to that directory and must be regular, non-symlink files; each entry named in `nonEmptyFiles` must also be non-empty. A generic adapter may declare empty evidence arrays. A semantic Review candidate runner requires non-empty `requiredFiles` and `nonEmptyFiles`, and its linked adapter case must match that stricter contract exactly.

Use a project-relative fixture path or a descriptive JSON object. The kernel records the contract but does not mutate or clean arbitrary fixture locations. Put setup and bounded cleanup in a project-owned local runner.

Set `localOnly.enabled` to `true` for these campaigns. A case capability must also appear in `allowedExternalCapabilities`, but that declaration is only validation input: it neither grants permission nor enforces OS isolation. Prefer fixtures, fakes, simulators, and loopback services. Stop for separate authorization before network access, external writes, real devices, production credentials, or any other undeclared effect.

Do not place secrets in adapter fields, argv, paths, fixtures, fix audits, output, or evidence. The kernel filters common secret-bearing environment variables and blocks recognizable secret-like input or output, but it is not a secret manager.

## Selection rule

Choose a stable source provider and exact inventory for the campaign lifetime. Adapter content, `coverageMode`, normalized case metadata, fixture values, source policy, and capability declarations all participate in the catalog fingerprint. Changing any of them is catalog drift and requires a new campaign root; never edit old state to accept a revised adapter.

A quick attempt runs only cases marked `quick: true`, is available only before full execution begins, and is durable diagnostic history. A quick result alone never establishes initial completion, final coverage, finding resolution, or a final baseline. Ordinary initial execution still starts full coverage from case 1, and final regression reruns every required and runnable optional case from case 1 on one source fingerprint.

For trace-enabled completion, at least one required final-regression `PASS` case must cover every required GOAL criterion and every triggered hard invariant. Every required review finding must be linked by at least one required case and resolved according to the review contract and recorded fix history. Each declared required scenario must be tagged by at least one required case that `PASS`es final regression; an optional case or an unsupported `NOT_RUN` case never satisfies trace coverage. Initial, quick, and targeted-retest results do not satisfy those final coverage requirements. Full coverage mode additionally proves the five-tier catalog requirement. Narrow completion proves only the declared catalog and must carry its reported missing tiers as explicit out-of-scope categories.
