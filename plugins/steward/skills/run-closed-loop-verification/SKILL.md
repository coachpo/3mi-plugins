---
name: run-closed-loop-verification
description: Accept a claimed-complete Steward GOAL in one explicit target worktree through durable initial checks, evidence-bound GOAL-scoped repairs, targeted retests, a fresh same-source regression, and final audit. Use only when explicitly asked to accept, resume, inspect, or audit that GOAL; use an ordinary project command for one-off testing.
---

# Closed-loop GOAL verification

Run `accept-goal` as a skill-level workflow over the bundled kernel. Completion
requires every GOAL criterion to have required final-pass evidence, the complete
case catalog to pass on one final source, and `audit.ok`.

Resolve this directory as `<skill-dir>`, its plugin root as `<plugin-dir>`, and
the caller-provided absolute worktree as `<worktree>`. Invoke scripts with
`python3 -B` and quoted paths. Never assume the target project contains the
kernel.

## Bind the claimed GOAL

Require exactly one explicit target worktree; do not infer it from another task,
repository, branch, or current shell directory. Run:

```text
python3 -B "<plugin-dir>/scripts/goal_workspace.py" view "<worktree>"
```

Use the returned goal-workspace v1 view as the authority for
`.steward/goal.txt`, its canonical objective and digest, its sole context path,
and all `C*` IDs. Read that context before designing or running acceptance.
Stop without writing if the workspace is absent, partial, linked, tracked,
inconsistent, or belongs to a different objective.

The control paths are fixed:

- adapter: `<worktree>/.steward/project-adapter.json`
- campaign: `<worktree>/.steward/verification/campaign`

`.steward/` is worktree-local control state. Preserve it through execution,
failure, recovery, merge, regression, and audit. Do not clean it up; it ends only
when the user removes the entire worktree.

## Prepare acceptance

Read [`references/project-adapter.md`](references/project-adapter.md) and
[`references/verification-patterns.md`](references/verification-patterns.md)
when an adapter must be designed. Inspect project-native commands, fixtures,
source inventory, side effects, and evidence boundaries. Design the complete
adapter in memory and review every argv before writing it.

Create the schema-2 adapter only when both adapter and campaign are absent. Each
GOAL `C*` needs at least one required case. If no trustworthy runner can prove a
criterion, report that blocker and write no placeholder. An existing invalid
adapter, a campaign without its adapter, or a partial campaign must be preserved
and reported, not overwritten or rebuilt.

Validate before initialization:

```text
python3 -B "<skill-dir>/scripts/campaign.py" validate-adapter --adapter "<worktree>/.steward/project-adapter.json"
python3 -B "<skill-dir>/scripts/campaign.py" observe-source --adapter "<worktree>/.steward/project-adapter.json"
python3 -B "<skill-dir>/scripts/campaign.py" init --adapter "<worktree>/.steward/project-adapter.json" --repair-policy within-goal
```

The default `within-goal` policy authorizes `.steward` control artifacts and
GOAL-scoped project-source repairs supported by failure evidence. A user may
select `verify-only` before initialization; that restriction cannot be widened
on resume. External writes, real services or devices, credentials, deployments,
purchases, destructive effects, and repairs outside the GOAL still require
separate authorization.

Treat the adapter as untrusted executable input. Stop or obtain the required
authorization before running an argv, fixture, capability, or effect outside
the frozen local boundary.

## Execute the closed loop

Read [`references/state-and-evidence.md`](references/state-and-evidence.md)
before mutating or recovering a campaign.

1. Run initial acceptance in declared order:

   ```text
   python3 -B "<skill-dir>/scripts/campaign.py" run --adapter "<worktree>/.steward/project-adapter.json" --mode initial
   ```

   Stop at the first `FAILED` or `BLOCKED` case.

2. For a proven project-source defect under `within-goal`, make the smallest
   evidence-supported repair. Fill the fix-audit v1 template with the latest
   failure binding, root-cause source, affected `C*`, new evidence, and exact
   added/modified/deleted/mode-only delta. Then run `record-fix` and `retest`.
   Continue remaining initial cases after a passing retest.

3. Repairs have no numeric limit, but each must establish new root-cause
   evidence or observable progress. Stop before editing when the same failure
   recurs without new evidence, the next edit uses the same disproved premise,
   the root cause is unproven, source drift is uncontrolled, the repair exceeds
   GOAL scope, or the failure is an environment/capability blocker.

4. Once initial acceptance is complete, run a fresh regression from case one:

   ```text
   python3 -B "<skill-dir>/scripts/campaign.py" run --adapter "<worktree>/.steward/project-adapter.json" --mode regression
   ```

   Source drift invalidates that campaign; do not restart it on a new baseline.

5. Run final audit:

   ```text
   python3 -B "<skill-dir>/scripts/campaign.py" audit --adapter "<worktree>/.steward/project-adapter.json"
   ```

Use `status` for a read-only projection and `resume` to recover an interrupted
operation from journal authority. Never hand-edit the journal or projections.

## Report

Lead with `completionStatus`. Report the GOAL digest, adapter and campaign
identity, `executionStatus`, `resumeMode`, repair policy and count, failed or
blocked case, criterion coverage, final source/catalog fingerprints, final
regression, audit result and rejection codes, unverified runtime branches, and
the smallest safe next action. Do not claim completion from adapter validation,
initial success, or targeted retest alone.
