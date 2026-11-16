---
name: simplify-repository
disable-model-invocation: true
description: Reviews or removes evidenced redundancy in repository code, tests, docs, and other artifacts while preserving behavior, coverage, knowledge, consumers, and retention obligations. Use when the user asks to simplify, deduplicate, or clean up a repository or subtree. Explicit invocation only. Not for feature retirement, visible copy changes, policy redesign, or delivery orchestration.
---

# Simplify Repository

Retain repository content that still has a purpose or retention obligation.
Review the relevant code, tests, documentation, and other artifacts together;
documentation and artifact cleanup do not depend on code or test changes.
Remove evidenced redundancy to reduce maintenance burden, not to meet deletion
quotas. No category must shrink; finding no safe deletion is valid.

Review requests return findings without cleanup changes. Implementation
requests carry the in-scope changes through validation. A request that does
not say which it is gets a review.

## Establish scope and authority

Identify the requested repository or subtree, explicit exclusions, authoritative
requirements and policies, accepted decisions, known validation baseline, and
material gaps.

Inspect actual relationships among implementation, callers, tests, documentation,
configuration, generators, assets, scripts, and development or delivery entry
points. Follow dependencies far enough to judge affected candidates without
turning a bounded request into an unrelated repository redesign.

Current contracts come from effective requirements, policies, and accepted
decisions. Existing implementation is evidence, not automatically a requirement.
Historical assumptions and permissions do not establish current facts.

Follow effective compatibility requirements. Preserving current contracts does
not mean retaining every historical API or compatibility path. Conversely, a
default against backward compatibility does not itself authorize removing
existing behavior or changing public APIs. Do not establish or rewrite project
policy as a side effect of cleanup.

An explicit implementation request for this skill authorizes deletion of
version-controlled content within scope once the evidence below supports it,
without per-file confirmation.

List untracked or ignored deletion candidates and obtain explicit confirmation
before deleting them.

## Preserve four classes of obligations

A candidate can carry more than one obligation. Classify by actual purpose,
not filename, extension, directory, or whether it was generated.

| Content | Obligations to preserve |
| --- | --- |
| Code | Current behavior and necessary complexity: required inputs, outputs, errors, side effects, invariants, and applicable runtime, data, security, privacy, concurrency, or migration constraints. |
| Tests | Unique detection of meaningful regressions, including relevant boundaries, failure branches, concurrency conditions, and forbidden side effects. |
| Documentation | Still-valid decisions, constraints, applicability conditions, assumptions, necessary provenance, acceptance evidence, and unresolved validation gaps. Preserve distinctions between requirements, proposals, observations, and historical results. |
| Other artifacts | Actual development, build, runtime, validation, or delivery consumers, plus licensing, audit, reproducibility, and other established retention obligations. |

An obligation may be preserved through consolidation rather than keeping every
original file. Preserve original material when the obligation specifically
requires it.

Business history, migration chains, licenses, test baselines, and required
delivery inputs are not expendable merely because they are old or not
application source.

## Identify and justify candidates

Look for duplicated behavior or information, unused consumers or outputs,
unreachable branches, superseded paths, redundant coverage, outdated reports,
non-baseline screenshots, scaffolding leftovers, completed transitional switches,
and generated artifacts without a continuing purpose.

These are candidate categories, not deletion rules. Being reproducible,
generated, historical, or absent from text searches is not sufficient evidence
for removal.

Open decisive evidence in context. Where relevant, inspect dynamic registration,
configuration, packaging, CI, generators, runtime paths, external interfaces,
and useful history. Distinguish “no consumer found yet” from an established lack
of purpose or retention obligation.

For each meaningful candidate group, establish:

- Its current purpose and applicable obligations.
- Evidence supporting removal or consolidation.
- Where continuing obligations will be carried afterward.
- Any explicitly retired obligation and the accepted basis for its retirement.
- Validation that can support the decision, and remaining uncertainty.

Keep this correspondence compact; do not require a permanent inventory or
report. Investigate or retain unresolved candidates rather than presenting
them as confirmed redundancy.

When retention depends on a fact the repository cannot establish, such as
deployment state, live data, or client-held records, name that fact and group
the candidates it decides rather than reporting each as retained.

## Simplify connected content

### Code

Compare call conditions, validation order, error behavior, state changes,
rollback, and other relevant effects before merging similar implementations.

When duplicates have already diverged, report the divergence and which side
is authoritative. Consolidating them is a behavior change that needs its own
decision.

A production member referenced only by tests is a candidate, not confirmed
dead. Determine whether it is a deliberate test seam, a fixture that belongs
with the tests, or a superseded path whose coverage should move to the live path.

Before removing a wrapper, guard, compatibility path, or helper, determine
whether it carries an independent contract or necessary complexity.

Before removing a field or state that other values derive from, trace the
derived symbols, interfaces, and copy, not just the original name. Use the
scope to decide whether it needs its own batch.

When removing a field in a type-checked codebase, remove it from its contract
type and use type checking to enumerate typed sites. Check handwritten SQL
fixtures, strict runtime schemas that reject extra fields, translation
dictionaries and dynamic keys, and browser and end-to-end tests separately.
Search documentation by concept as well as by identifier.

When removal depends on the shape of stored data, apply
[persisted data cleanup](references/persisted-data-cleanup.md).

### Tests

Compare setup assumptions, input boundaries, failure branches, concurrency
conditions, assertions, and side-effect checks. Traversing the same code does
not establish equivalent regression detection.

Before removing valid coverage, identify retained assertions that detect the
same meaningful failures, or migrate unique assertions into suitable tests.
Do not assume a higher-level test subsumes lower-level or property coverage.
If setup depends on a removed state, change the setup when the same contract
is still observable on new data; remove the test only if the contract no longer applies.

Distinguish fragile implementation-detail assertions and one-time cleanup
checks from durable contracts. Rejection paths and forbidden side effects
can provide essential negative coverage. After tightening constraints, recheck
each expected rejection to ensure it fails for the intended reason.

### Documentation

Consolidate duplicated information and retire obsolete material while giving
continuing facts and decisions an appropriate authoritative home.

Before deleting a document, verify that unique, still-valid information and
necessary historical context have been carried forward. Preserve unresolved
acceptance gaps rather than converting past partial results into current
completion claims.

Repair affected navigation, links, anchors, and cross-references. Do not rebuild
the documentation system, impose a document set, or rewrite project policy
merely to complete cleanup.

For an explicit request to describe the current state rather than the history of
work, also apply [current-state cleanup](references/current-state-cleanup.md).

### Other artifacts

Check actual consumers and retention obligations before removing assets,
screenshots, reports, generated files, configuration, dependencies, or scripts.

For operator-run tools, the consumer is the documented scenario, such as setup,
release, recovery, or account maintenance. Absence of code callers is not
evidence of redundancy.

For screenshots, distinguish disposable captures from comparison baselines,
required evidence, and documentation assets. For generated files, distinguish
recreatable intermediates from required checked-in build or delivery inputs.

Clean supporting fixtures, helpers, dependencies, scripts, and references when
their remaining purpose has actually disappeared.

## Validate the four preservation responsibilities

Review both the remaining content and the removed material:

- **Behavior:** current contracts and necessary complexity remain implemented.
- **Coverage:** retained tests still detect the meaningful regressions protected
  by removed or consolidated tests.
- **Knowledge:** valid decisions, constraints, applicability conditions, and
  acceptance gaps remain accurately represented.
- **Consumers and retention:** required workflows, artifacts, and established
  retention obligations remain supported.

Removing production logic and its corresponding assertions together does not
establish safety merely because the remaining suite passes. Likewise, valid
links do not prove complete information transfer, and successful regeneration
does not prove that an artifact was unnecessary.

Use the known baseline and check relevant pre-change behavior when needed to
interpret results. Choose checks appropriate to affected obligations and run
the repository's required validation. If relying on a slow browser or end-to-end
suite to judge the change, run it before editing to establish a baseline.

Use behavior tests for affected code, assertion-level review for coverage
replacement, content and link checks for documentation, and relevant consumer
or packaging checks for artifacts. Do not impose unrelated application tests
for an isolated prose change or a universal coverage or mutation-testing gate.

Investigate failures as product regressions, test fragility, tooling defects,
or environment limitations before choosing a remedy. Compare with the baseline
and trace the failing assertion to the affected code, including indirect effects,
to distinguish existing failures from new regressions. Subsequent edits
invalidate affected validation evidence.

Use temporary checks for one-time deletion and reference cleanup. Do not retain
permanent tests solely to prove that this cleanup happened. Durable behavioral
or compatibility constraints remain legitimate tests.

Review the final combined diff against all affected obligation classes.
Passing checks and deletion metrics support, but do not replace, this review.

## Iterate to a simplification baseline

For implementation requests, repeat candidate discovery, obligation and consumer
checks, justified removal or consolidation, and validation. After each validated
round, inspect new candidates exposed by the changes and remaining unreviewed
relationships material to the requested scope. Continue while safe, authorized
changes with concrete maintenance benefit remain; do not require a full repository
rescan each round.

Judge net maintenance benefit, including any added abstraction, indirection,
configuration, or coupling. Do not consolidate merely for uniformity or introduce
abstractions whose maintenance cost outweighs their benefit.

Report a simplification baseline under current constraints only when, within the
reviewed scope, no remaining simplification is supported as safe and meaningfully
beneficial, implemented changes have passed applicable validation, and no material
unresolved candidate or validation gap prevents that conclusion. State the reviewed
boundary and effective constraints; this is not proof of a global optimum.

Do not repeat unchanged investigations without new evidence, relationship changes,
or actionable work. If unresolved evidence, additional authorization, or environment
limits prevent further judgment or validation, retain the affected content and
report partial completion and the specific limits. Stopping investigation does not
establish a simplification baseline.

## Compose with other Steward skills

- Use [parallel-repository-research](../parallel-repository-research/SKILL.md)
  when independent searches are useful. Workers return facts;
  the responsible executor owns removal and preservation judgments.
- Use [write-project-docs](../write-project-docs/SKILL.md) for specialized
  canonical-document maintenance within scope.
- Use [write-agent-guides](../write-agent-guides/SKILL.md) when agent behavior
  or AGENTS.md hierarchy genuinely requires maintenance.
- For cleanup that changes visible copy, suggest
  [simplify-interface-text](../simplify-interface-text/SKILL.md), which requires
  explicit invocation and is outside this skill's behavior-preserving scope.

Read another skill only when using it. Its defaults do not expand the cleanup
scope or authorize new policy. Do not require a plan, contract, subagent, or
new worktree for a bounded task.

## Report the result

Summarize:

- What was removed, consolidated, or deliberately retained, and why.
- How each affected obligation class remains protected.
- Validation actually performed and its results. List checks not run separately
  from passing checks, by suite or file, and state material unverified scope.

Distinguish confirmed redundancy and its disposition from unresolved candidates,
changes requiring additional authorization, and environment or validation limits.
State whether these prevent a baseline conclusion and identify any narrower
completed scope. Retaining an unresolved candidate proves neither necessity nor
redundancy.

Keep existing acceptance gaps explicit. For review-only work, do not describe
proposed changes as implemented or validated.
