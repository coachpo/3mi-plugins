# Verification patterns

## Coverage tiers

A `coverageMode: "full"` campaign includes at least one required case in all five risk tiers. This is a machine-enforced adapter contract: validation rejects full mode when any tier is absent or represented only by optional cases. The labels describe observed risk rather than a required framework or tool.

| Category | Verify | Typical local evidence |
| --- | --- | --- |
| `smoke` | The build or entry point starts and its critical health path is reachable. | Exit status, startup marker, minimal response fixture. |
| `functional` | A focused requirement plus validation and error boundaries. | Deterministic input/output, assertion log, boundary fixture. |
| `integration` | Contracts across modules, services, storage, queues, or adapters. | Loopback or fake dependency, request/response proof, state snapshot. |
| `workflow` | A multi-step user or operator journey, including persistence and recovery. | Step ledger, fixture state, transition proof. |
| `role-play` | An end-to-end actor scenario, including handoffs, permissions, and failure recovery. | Redacted transcript, actor/action ledger, final invariants. |

For a narrower campaign, use `coverageMode: "narrow"`, translate the user's explicit scope into observable required and optional cases, and report what is outside requested coverage. The normalized coverage summary derives `presentTiers` from required cases and lists every absent required tier in `missingTiers` and `outOfScopeTiers`; campaign status and audit separately show which required tiers have final-regression proof. Mark a case required when omitting it would invalidate that stated purpose. A full campaign cannot omit a required tier merely because it needs a local substitute.

Treat `coverageMode` as the breadth of one campaign's local catalog, not as a CI tier label. A base adapter may be `full` because its complete catalog has all five risk tiers, while every CI-plan-derived shard is deliberately `narrow` because it contains only one exact entry partition. Its separate `verification.tier: "full"` still requires initial and regression execution of every shard case. Preserve the base `verificationCatalogFingerprint`; only exact aggregation of all plan entries proves the declared global case partition, and no individual shard audit may be reported as base/global full coverage.

Treat a `write-project-docs` Current Development Strategy as valid only after its read-only validator confirms the exact `STATUS.md` development tier, complete static asset catalog, and selected managed block. Then use its must-complete items and non-negotiable boundaries together with the Goal and reachable risks to decide which actual purposes need required cases. Do not add a case only because a hypothetical future state could make it useful, and do not turn work that the tier does not pursue by default into exclusion IDs, digests, or audit proof. In full mode all five risk categories still apply to the current purpose, but the verification labels do not by themselves require load, capacity, high-availability, or production-scale testing unless the static tier, Goal, hard constraints, or reachable risks require them. Narrow mode may omit a category only as explicitly reported out of scope. A `full` campaign covers the whole current catalog, not every imaginable future scenario; user requirements, hard invariants, real data, existing users, compatibility commitments, and supported reachable review findings override tier defaults.

## Traceable coverage and scenarios

When the adapter references stable contracts, design a coverage matrix before initialization:

- Map every required GOAL `C*` criterion to one or more required `coversCriteria` cases.
- Map every triggered hard invariant from the shared loader to one or more required `coversInvariants` cases.
- Map every required review finding to one or more required `reviewFindingIds` cases and keep actual resolution claims in fix audits.
- For each `traceability.requiredScenarios` value, tag at least one **required** case with the same `scenarioTags` value. That case must be runnable and `PASS` in the final full regression; an optional or unsupported `NOT_RUN` case does not satisfy the scenario.

The supported required-scenario tags are `failure`, `compatibility`, and `platform`. Use a tag only when the case's assertions and evidence actually exercise that scenario. A single case may carry several tags when its evidence proves each one, but do not use broad tagging to hide a missing counterexample or environment branch.

Use `quick: true` for deterministic, low-cost, high-signal cases. Quick cases are a front-loaded diagnostic subset, not a separate acceptance scope: they run again during ordinary initial and full regression coverage, and only their final-regression passes satisfy mappings.

Add concrete counterexamples where a happy-path assertion could pass while the contract is still broken. In particular, consider:

- malformed, missing, denied, duplicated, reordered, stale, or out-of-range input;
- old persisted data, prior schema/API versions, upgrade and downgrade boundaries, and incompatible peers;
- interrupted multi-step work, retry/replay, partial state, restart, rollback, and idempotent recovery;
- scope leakage across tenant, user, workspace, filesystem root, transaction, cache, or authorization boundary;
- platform-specific path identity, encoding, permissions, process cleanup, unavailable capability, and substitute behavior.

For compatibility journeys, preserve representative old data or wire fixtures and prove both intended acceptance and explicit rejection. For platform journeys, prefer real-host evidence; when only a substitute is authorized, state that limitation and do not claim the untested platform branch. For recovery journeys, prove the durable checkpoint and post-restart invariant, not only that the command returned successfully.

## Local evidence design

Prefer a simulator or fake to a real device, payment rail, cloud service, or production endpoint; a fixture database or ephemeral store to shared data; loopback transport to external network; and seeded data, fake identity, and deterministic time to live credentials. Declare each substitute in the fixture and keep its observable behavior in the evidence contract.

For every case, establish the actor or boundary, precondition, argv executable, bounded timeout, platform, dependencies, criterion/invariant/finding mappings, scenario tags, pass/fail invariant, and required evidence. Use `CLOSED_LOOP_EVIDENCE_DIR` for command-owned proof. Split long journeys at meaningful checkpoints so the first failure identifies one broken transition.

Order inexpensive, high-signal checks before broad workflows, while keeping each real dependency earlier than its consumer. Do not over-serialize unrelated design dependencies: execution remains intentionally single-runner and fail-stop.

A timeout, missing success evidence, nondeterministic fixture, or unexpected result is `FAILED`. An unavailable required platform or authorized prerequisite is `BLOCKED`. An optional platform-specific case may be `NOT_RUN` only when the current platform cannot run it. Later cases after fail-stop remain `PENDING`.

Before initialization, confirm that the source inventory is reproducible, campaign artifacts are precisely excluded, all trace references match their shared-loader digests, all commands and side effects fit the current authorization, local substitutes cover external boundaries, each required scenario has a required runnable case, and every evidence contract can be produced without secrets. After a fix and targeted retest, require a clean full regression and final audit; never hand-edit state or reuse an artifact directory.
