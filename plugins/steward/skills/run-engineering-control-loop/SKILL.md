---
name: run-engineering-control-loop
description: Coordinate an explicitly requested complete Steward engineering loop from a persistent Goal through profiles/invariants, semantic review, durable verification, final same-source regression, and audit. Use only for the full loop around an already-authorized engineering change, not for ordinary coding, a single test, standalone review, or one documentation task.
---

# Run Engineering Control Loop

Coordinate the specialized Steward skills without copying their state machines.
The outcome is a compatible persistent Goal whose required engineering change is
implemented within scope and proven by `RequestedCoverageSatisfied ∧ audit.ok`.

## Authority and write set

An explicit request for this complete loop, together with the engineering change
it places in scope, authorizes the loop's normal project-local control artifacts
beneath `.steward/`: Goal handoff, profile selection when used, invariant map,
frozen semantic request, canonical Review handoff, adapter, and campaign/evidence
roots. Resolve, freeze, and disclose the exact write set before the first write.
Do not request path-by-path confirmation again while artifacts stay in that set.

This authority does not add source changes beyond the original engineering
request. Confirm before writing outside the frozen set, overwriting unrelated
user content, external or remote mutation, deployment, credentials, destructive
or paid actions, or material scope expansion. Existing artifacts and prior Goal
state never expand authority.

Read [the shared control-plane contracts](../../references/control-plane-contracts.md)
before persisting cross-gate handoffs. Bind canonical artifacts by project-relative
path and digest and carry stable IDs rather than copied contract text.

## Resume the first invalid gate

On entry, resume, or context loss, call `get_goal`, inspect current campaign
`status` when one exists, and validate only the existing handoffs needed to find
the first incomplete or invalid gate. Do not recreate a compatible Goal, repeat
a completed gate, or rebind drifted evidence.

Read and validate a managed Current Iteration Strategy only when it exists and
affects the current gate. Re-derive architecture-profile evidence when entering
a profile-dependent gate, when its source inputs changed, and immediately before
final trace binding; do not recompute unrelated downstream artifacts on every
resume. A changed input invalidates the dependent gates in order.

## Gate contract

| Gate | Required observable outcome | Owner |
| --- | --- | --- |
| Goal | Compatible active v1 Goal with stable `C*` and canonical digest. | [`start-consensus-goal`](../start-consensus-goal/SKILL.md) |
| Profiles | Repository evidence deterministically selects and compiles only relevant versioned profiles. | `architecture_profiles.py validate`, `select`, and `compile` plus [selection evidence v1](../../references/architecture-profiles/selection-evidence.md) |
| Invariants | Canonical docs own final anchors and `.steward/invariants.json` validly binds applicable hard invariants. | [`write-project-docs`](../write-project-docs/SKILL.md), only when those document/index writes are in scope |
| Router | Root `AGENTS.md` exposes a short trigger/authority/INV/validation route when the invariant map requires it. | [`write-agent-guides`](../write-agent-guides/SKILL.md), only when that root write is in scope |
| Impact and implementation | Reachable impact is mapped; the smallest authorized implementation passes bounded project-native checks. | Repository-native work; quick evidence is not completion |
| Adapter and source | A validated, uninitialized adapter establishes the final source policy and a read-only source observation before Review binding. | `run-closed-loop-verification` `design/bootstrap` or `validate-adapter`, then `observe-source`; do not initialize yet |
| Semantic review | The exact requested source/diff has a complete request-bound read-only Review, or the loop stops with its precise gap. | Coordinator freezes request; [`review-semantic-risks`](../review-semantic-risks/SKILL.md) runs `strict-handoff` mode |
| Trace binding | Adapter pins the canonical Review digest and request SHA, revalidates, and remains source-consistent. | Coordinator updates only the frozen adapter path and revalidates it |
| Closed loop | Campaign completes initial coverage, bounded repair/recovery, fresh strict post-fix Reviews when needed, and readiness for final regression. | [`run-closed-loop-verification`](../run-closed-loop-verification/SKILL.md) |
| Acceptance | One full regression covers the runnable catalog on one source fingerprint and the final audit succeeds. | `RequestedCoverageSatisfied ∧ audit.ok` |

The Adapter and source gate intentionally precedes Semantic review. Its adapter
has the final source policy but no Review binding. After the Reviewer returns,
the Trace binding gate adds the canonical Review/request identities, revalidates
the adapter, and only then initializes the campaign. This breaks the previous
adapter↔Review dependency cycle.

## Cross-gate ownership

The coordinator owns source policy, exact request/Review paths, the read-only
`semantic_review.py request-view` call, and persistence of canonical validator
stdout within the frozen write set. The Reviewer never selects paths, writes a
handoff, runs tests, or fixes code. Closed-loop consumes the validated handoff;
it does not discover or rewrite findings.

For a supported required finding, return to Impact and implementation only while
the task-wide repair budget in `run-closed-loop-verification` remains. Then use
that skill's strict post-fix Review, supersession, retest, recovery, new-root, and
audit contracts. Do not reproduce their commands or add an outer retry loop.

Profile evidence, invariant/router bindings, source observation, request, Review,
adapter, and campaign form one dependency chain. When one changes, return to the
first affected gate; never make a stale downstream digest current by refreshing
it in place.

## Complete or stop

Do not complete the Goal from implementation, quick checks, targeted retest,
semantic Review, regression alone, or aggregation alone. Immediately before
completion, call `get_goal` and require its current objective/digest to match the
Goal handoff and campaign trace input. Then require every current Goal criterion
and `RequestedCoverageSatisfied ∧ audit.ok`.

Use the underlying Goal and campaign stopping rules. When evidence, a safe local
substitute, compatible Goal, required platform, or authority is unavailable,
preserve artifacts and report the failed gate, affected stable IDs, evidence
obtained, and smallest next action.

Lead final delivery with the outcome and only the evidence needed to support it:
actual changes, per-criterion proof, current contract/source/catalog identities,
semantic result, repair attempts, final regression/audit, validation, unverified
platforms, residual risks, and remaining gaps.
