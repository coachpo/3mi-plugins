---
name: simplify-repository
description: Review or simplify repository contents across code, tests, documentation, and other artifacts. Remove evidenced redundancy while preserving current behavior, unique regression coverage, valid project knowledge, and necessary consumers or retention obligations. Use for repository cleanup, consolidation, or ablation; not feature retirement, policy redesign, or delivery orchestration.
---

# Simplify Repository

Retain repository content that still has a purpose or retention obligation.
Remove evidenced redundancy and reduce maintenance burden, rather than
targeting fewer files, lines, tests, documents, or dependencies.

Treat code, tests, documentation, and other artifacts as connected parts of
the repository. Documentation and artifact cleanup are primary responsibilities,
not merely follow-up work after code or test changes.

Inspect the categories relevant to the requested scope. Do not require every
category to change or shrink. Finding no safe deletion is a valid outcome.

Review requests return findings without cleanup changes. Implementation
requests carry the in-scope changes through validation.

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
non-baseline screenshots, and generated artifacts without a continuing purpose.

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

## Simplify connected content

Organize cohesive changes around obligations and consumer relationships, not
separate deletion quotas for code, tests, documents, or artifacts.

### Code

Compare call conditions, validation order, error behavior, state changes,
rollback, and other relevant effects before merging similar implementations.

Before removing a wrapper, guard, compatibility path, or helper, determine
whether it carries an independent contract or necessary complexity.

### Tests

Compare setup assumptions, input boundaries, failure branches, concurrency
conditions, assertions, and side-effect checks. Traversing the same code does
not establish equivalent regression detection.

Before removing valid coverage, identify retained assertions that detect the
same meaningful failures, or migrate unique assertions into suitable tests.
Do not assume a higher-level test subsumes lower-level or property coverage.

Distinguish fragile implementation-detail assertions and one-time cleanup
checks from durable contracts. Rejection paths and forbidden side effects
can provide essential negative coverage.

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

### Other artifacts

Check actual consumers and retention obligations before removing assets,
screenshots, reports, generated files, configuration, dependencies, or scripts.

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
the repository's required validation.

Use behavior tests for affected code, assertion-level review for coverage
replacement, content and link checks for documentation, and relevant consumer
or packaging checks for artifacts. Do not impose unrelated application tests
for an isolated prose change or a universal coverage or mutation-testing gate.

Investigate failures as product regressions, test fragility, tooling defects,
or environment limitations before choosing a remedy. Subsequent edits
invalidate affected validation evidence.

Use temporary checks for one-time deletion and reference cleanup. Do not retain
permanent tests solely to prove that this cleanup happened. Durable behavioral
or compatibility constraints remain legitimate tests.

Review the final combined diff against all affected obligation classes.
Passing checks and deletion metrics support, but do not replace, this review.

## Compose with other Steward skills

This skill owns repository simplification, including substantive documentation
and artifact cleanup. Other skills support specialized work; they do not exclude
those categories from this skill's scope.

- Use [parallel-repository-research](../parallel-repository-research/SKILL.md)
  when independent searches justify it. Workers return facts; the responsible
  executor owns removal and preservation judgments.
- Use [plan-handoff](../plan-handoff/SKILL.md) when handing bounded work to
  another executor. Carry the obligations and validation into the contract.
- Use [execute-plan](../execute-plan/SKILL.md) for coordinated execution of an
  approved plan and final integration.
- Use [write-project-docs](../write-project-docs/SKILL.md) for specialized
  canonical-document maintenance within the requested cleanup.
- Use [write-agent-guides](../write-agent-guides/SKILL.md) when agent behavior
  or AGENTS.md hierarchy genuinely requires maintenance.

Read another skill only when using it. Its defaults do not expand the cleanup
scope or authorize new policy. Do not require a plan, contract, subagent, or
new worktree for a bounded task.

## Report the result

Summarize:

- What was removed, consolidated, or deliberately retained, and why.
- How each affected obligation class remains protected.
- Validation actually performed, its results, and material unverified scope.

Keep existing acceptance gaps explicit. For review-only work, distinguish
supported candidates from unresolved ones and do not describe proposed changes
as implemented or validated.
