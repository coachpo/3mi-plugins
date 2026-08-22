---
name: run-engineering-control-loop
description: Coordinate a requested full Steward loop from an explicit seven-line GOAL or converged engineering request through profiles, invariants, semantic review, durable verification, same-source regression, and audit. Use only around an authorized engineering change, not for ordinary coding, one test, standalone review, or documentation work.
---

# Run Engineering Control Loop

The outcome is an accepted seven-line GOAL bound to durable project-local
evidence, with its required engineering change implemented within scope and
proven by `RequestedCoverageSatisfied ∧ audit.ok`. Host conversation, task, or
continuation state is never recovery or completion authority.

This workflow requires an explicit user request for the complete loop; never
infer it from ordinary implementation, review, or test work.

Resolve this skill directory as `<skill-dir>` and the shared validator as
`"<skill-dir>/../../scripts/goal_contract.py"`.

## Authority and write set

An explicit full-loop request and its scoped engineering change authorize normal
project-local controls beneath `.steward/`: canonical GOAL, selected profile,
invariant map, frozen semantic request, Review handoff, adapter, and
campaign/evidence roots. Resolve, freeze, and disclose the exact write set before
writing; do not reconfirm individual paths while artifacts stay inside it.

This authority does not add source changes beyond the original engineering
request. Confirm before writing outside the frozen set, overwriting unrelated
user content, external or remote mutation, deployment, credentials, destructive
or paid actions, or material scope expansion. Existing artifacts and prior
conversation or control state never expand authority.

Read [the shared control-plane contracts](../../references/control-plane-contracts.md)
before cross-gate persistence. Bind artifacts by project-relative path and
digest, carrying stable IDs rather than copied contract text.

## Bind the accepted GOAL

Resolve the project root. Input is either explicit seven-line GOAL text or a
user-identified path, or an accepted current request with materially complete
result, scope, authority boundary, criteria, and blockers. Validate inline input
through standard input with:

```text
python3 -B "<skill-dir>/../../scripts/goal_contract.py" view -
```

For a supplied path, quote it and replace `-` with that path. Never repair,
reinterpret, or renumber explicit input. For a converged request, use
[`draft-consensus-goal`](../draft-consensus-goal/SKILL.md) as the sole author and
ask only when a material contract decision is missing.

Freeze `.steward/goal.txt` in the disclosed write set, persist the canonical
objective exactly, and bind its digest. Reuse an existing file only after
validation and request-compatibility checks; presence alone grants no authority.
An explicit resume request may identify this standard path by role. Revalidate
and obtain its canonical digest with:

```text
python3 -B "<skill-dir>/../../scripts/goal_contract.py" view "<project-root>/.steward/goal.txt"
python3 -B "<skill-dir>/../../scripts/goal_contract.py" digest "<project-root>/.steward/goal.txt"
```

## Resume the first invalid gate

On entry, resume, or context loss, revalidate `.steward/goal.txt`, inspect the
current campaign journal `status` when one exists, and validate only the existing
`.steward/` handoffs needed to find the first incomplete or invalid gate. These
validated project-local artifacts and the repository evidence they bind are the
only durable recovery authority. Do not repeat a completed gate, infer progress
from chat memory, or make drifted evidence current by rebinding it.

Read a validator-confirmed managed Current Development Strategy only when its
static tier affects the gate.
Re-derive architecture-profile evidence on entry to a dependent gate, after its
inputs change, and before final trace binding. Do not recompute unrelated
artifacts; changed input invalidates dependent gates in order.

## Gate contract

| Gate | Required observable outcome | Owner |
| --- | --- | --- |
| GOAL contract | Accepted v1 GOAL persisted at `.steward/goal.txt` with stable `C*` and its canonical digest. | [`draft-consensus-goal`](../draft-consensus-goal/SKILL.md) for authoring; `goal_contract.py` for validation |
| Profiles | Repository evidence deterministically selects and compiles only relevant versioned profiles. | `architecture_profiles.py validate`, `select`, and `compile` plus [selection evidence v1](../../references/architecture-profiles/selection-evidence.md) |
| Invariants | Canonical docs own final anchors and `.steward/invariants.json` validly binds applicable hard invariants. | [`write-project-docs`](../write-project-docs/SKILL.md), only when those document/index writes are in scope |
| Router | Root `AGENTS.md` exposes a short trigger/authority/INV/validation route when the invariant map requires it. | [`write-agent-guides`](../write-agent-guides/SKILL.md), only when that root write is in scope |
| Impact and implementation | Reachable impact is mapped; the smallest authorized implementation passes bounded project-native checks. | Repository-native work; quick evidence is not completion |
| Adapter and source | A validated, uninitialized adapter establishes the final source policy and a read-only source observation before Review binding. | `run-closed-loop-verification` `design/bootstrap` or `validate-adapter`, then `observe-source`; do not initialize yet |
| Semantic review | The exact requested source/diff has a complete request-bound read-only Review, or the loop stops with its precise gap. | Coordinator freezes request; [`review-semantic-risks`](../review-semantic-risks/SKILL.md) runs `strict-handoff` mode |
| Trace binding | Adapter pins the canonical Review digest and request SHA, revalidates, and remains source-consistent. | Coordinator updates only the frozen adapter path and revalidates it |
| Closed loop | Campaign completes initial coverage, bounded repair/recovery, fresh strict post-fix Reviews when needed, and readiness for final regression. | [`run-closed-loop-verification`](../run-closed-loop-verification/SKILL.md) |
| Acceptance | One full regression covers the runnable catalog on one source fingerprint and the final audit succeeds. | `RequestedCoverageSatisfied ∧ audit.ok` |

## Cross-gate ownership

The coordinator owns source policy, request/Review paths, the read-only
`semantic_review.py request-view` call, and canonical validator stdout in the
frozen write set. The Reviewer never selects paths, writes, tests, or fixes;
closed-loop consumes the validated handoff without rewriting findings.

For a supported required finding, return to implementation only within the
`run-closed-loop-verification` repair budget. Delegate its strict post-fix
Review, supersession, retest, recovery, new-root, and audit contracts; add no
outer retry loop.

## Complete or stop

Do not report the engineering loop complete from implementation, quick checks,
targeted retest, semantic Review, regression alone, or aggregation alone.
Immediately before completion, revalidate `.steward/goal.txt` and require its
canonical digest to match the adapter and campaign trace input. Then require
every current `C*` and `RequestedCoverageSatisfied ∧ audit.ok`.

Use the accepted GOAL's legitimate blockers and the campaign stopping rules.
When evidence, a safe local substitute, a valid accepted GOAL, required
platform, or authority is unavailable, preserve artifacts and report the failed
gate, affected stable IDs, evidence obtained, and smallest next action.

Lead with the outcome and supporting evidence: changes, per-criterion proof,
current contract/source/catalog identities, semantic result, repairs, final
regression/audit, validation, unverified platforms, risks, and gaps.
