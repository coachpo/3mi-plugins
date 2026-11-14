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

#### Current-state cleanup (explicit request only)

Apply these rules only when the user explicitly requests documentation that
describes the current state rather than the history of work. This mode does not
relax the preservation obligations above or make historical content disposable
by default. Review requests remain read-only.

- Read the repository's applicable guides and documentation index, inventory
  documents in scope (including tracked Markdown where relevant), and read each
  scoped document in full. Check concrete claims against current source,
  configuration, manifests and migrations; do not infer live state from old logs.
- Remove execution/acceptance logs, operation transcripts, completed migration
  or repair narratives, and "previously X, then Y" accounts only when they carry
  no continuing obligation. Likewise remove obsolete resource/command descriptions,
  debugging notes, temporary conclusions, superseded TODOs/proposals and intermediate
  artifacts only when readers no longer need them to understand or operate the system.
- Preserve current architecture, contracts, domain rules, active resource identities
  and configuration, and security, privacy and financial boundaries. Preserve usable
  setup, deployment, migration, incident/reconciliation and backup/restore runbooks;
  instructions for repeatable operations are not execution logs. Keep historical
  data/protocol handling that current code still supports or requires.
- Distinguish execution dates from source-verification dates. Keep source links,
  verification dates, necessary provenance, required acceptance/audit evidence and
  unresolved validation gaps. A dated heading alone is not grounds for deletion.
- When retired-resource text prevents reuse or accidental operations, retain that
  warning as a current constraint without the chronology; keep identifiers needed
  for safe resource selection.
- Prefer deletion and necessary connective wording over rewriting valid content or
  adding feature descriptions. For partly stale sentences, remove only the obsolete
  clause; do not invent replacement facts. Repair empty sections, duplication,
  heading structure, indexes and affected links after deletion.
- Retain uncertain candidates and list them for user decision. In the handoff,
  identify changed sections by file with reasons, and separately report confirmed
  inconsistencies left unchanged. Do not turn inability to verify into a claim
  that a statement is false.

For documentation-only work, inspect retained commands, paths, relative links and
anchors and check whitespace. Do not start the application or add permanent wording
tests solely to validate this cleanup. The requested documentation scope does not
authorize source/configuration/test changes, remote operations or commits.

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

This skill owns repository simplification, including substantive documentation
and artifact cleanup. Other skills support specialized work; they do not exclude
those categories from this skill's scope.

- Use [parallel-repository-research](../parallel-repository-research/SKILL.md)
  when independent searches justify it. Workers return facts; the responsible
  executor owns removal and preservation judgments.
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

Distinguish confirmed redundancy and its disposition from unresolved candidates,
changes requiring additional authorization, and environment or validation limits.
State whether these prevent a baseline conclusion and identify any narrower
completed scope. Retaining an unresolved candidate proves neither necessity nor
redundancy.

Keep existing acceptance gaps explicit. For review-only work, do not describe
proposed changes as implemented or validated.
