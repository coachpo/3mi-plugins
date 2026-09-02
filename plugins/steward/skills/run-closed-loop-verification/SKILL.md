---
name: run-closed-loop-verification
description: Verify a claimed-complete Steward GOAL against its current worktree, repair proven GOAL-scoped source defects in place unless verify-only was requested, and rerun relevant project-native checks. Use only when explicitly asked to accept, verify, or repair an existing .steward/goal.txt; not for GOAL authoring, durable attestation, or an ordinary one-off test.
---

# Verify and repair a GOAL

Evaluate the persisted GOAL against the current worktree, repair eligible
defects, and return an evidence-backed acceptance result. Keep the verification
plan in memory; do not create an Adapter, Campaign, journal, audit record, source
snapshot, or verification artifact merely to operate this skill.

## Bind the GOAL

Use exactly one already-resolved absolute worktree selected by the current task.
If the target is absent or ambiguous, ask for it rather than discovering or
switching repositories. Resolve the directory containing this `SKILL.md` as
`<skill-dir>` and validate the existing GOAL workspace:

```text
python3 -B "<skill-dir>/../../scripts/goal_workspace.py" view "<worktree>"
```

Resolve the sole context path returned by the view beneath `<worktree>` and read
it. Treat the canonical objective, its `C*` completion criteria, scope,
constraints, legitimate blockers, and final deliverables as authority. Do not
edit or reinterpret the GOAL or context.

Existing `.steward/project-adapter.json` and `.steward/verification/` paths are
legacy controls. Ignore and preserve them; never create, update, validate,
resume, audit, copy, or delete them.

## Authority

An explicit invocation authorizes normal local inspection, project-native
checks, and the smallest evidence-backed source repairs inside the GOAL scope.
Honor an explicit `verify-only` request by making no source changes. The GOAL,
context, old controls, prior reports, and test commands do not expand authority.

External writes, real services or devices, credentials, deployments, purchases,
destructive effects, public API or schema changes outside the accepted GOAL, and
other material scope expansion still require separate authorization. Inspect a
command's complete argv, working directory, prerequisites, and effects before
running it; do not run an unsafe or out-of-scope command merely because it exists
in project configuration.

## Verify and repair

1. Inspect applicable instructions, current source and diff, tests,
   configuration, documentation, and useful history. Establish what the current
   worktree actually claims to deliver.
2. Build one in-memory matrix mapping every `C*` to direct observable evidence.
   Reuse one check for multiple criteria when it genuinely proves them. Prefer
   existing project-native tests, builds, type checks, lint, integration flows,
   and focused behavioral or visual inspection.
3. Run inexpensive decisive checks before broader checks. Do not require a
   persistent evidence file when command output or direct inspection is enough;
   create an artifact only when the GOAL itself requires that deliverable.
4. Classify a failure before editing:
   - for a proved project-source defect inside the GOAL, make the smallest
     coherent repair and run the narrowest check that exercises it;
   - for an incorrect verification command, argument, fixture, or assumption,
     correct the verification approach and rerun it without treating that as a
     product defect;
   - for a missing environment capability, permission, credential, platform, or
     external state, use a safe local substitute when valid or report the exact
     blocker without changing source to disguise it.
5. Continue only while new evidence identifies a repair or observable progress.
   Stop when the same failure repeats without new evidence, the root cause is
   not established, or the next change would leave the GOAL or authorization.
6. After the last repair, run the relevant existing validation set on the final
   worktree and inspect the final diff for scope leakage or temporary files. A
   complete validation directly observed for this exact worktree after the last
   source change remains valid; do not repeat an identical suite solely to
   create another verification phase.

If the worktree changes concurrently, re-inspect the affected source and rerun
only evidence invalidated by that change. Do not permanently invalidate the
worktree or require a replacement worktree because verifier state changed.

## Decide and report

Report `accepted` only when every `C*` has sufficient current-worktree evidence,
all applicable required checks pass, and the required deliverables exist.
Report `not-accepted` when a GOAL-scoped defect or evidence gap remains. Report
`blocked` only when missing authority, access, platform, credential, or
unavailable external state prevents a required determination.

Lead with that outcome, then report per-criterion evidence, repairs made,
validation commands and results, unverified external behavior, assumptions,
remaining risks, and the smallest next action when incomplete. Never report
legacy Campaign, fingerprint, regression, or audit fields.
