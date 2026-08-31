---
name: run-closed-loop-verification
description: Operate a claimed-complete Steward GOAL in one explicit worktree with durable evidence. Inspect is read-only; resume and audit act only on an existing Campaign; accept alone may initialize, run, and make evidence-bound GOAL-scoped repairs. Use ordinary project commands for one-off testing.
---

# Closed-loop GOAL verification

Choose exactly one operation from the request. Run the complete `accept-goal`
workflow only for `accept`; never escalate `inspect`, `resume`, or `audit`.

A Campaign is `COMPLETE` only when one final source has all required and runnable
optional cases passing a fresh full regression, every GOAL `C*` has a required
final-pass case, and `audit.ok`. An unavailable optional case may be `NOT_RUN`;
an unavailable required platform is a blocker.

## Bind the GOAL

Resolve this directory as `<skill-dir>`, its plugin root as `<plugin-dir>`, and
the caller-provided absolute worktree as `<worktree>`. Run scripts with
`python3 -B` and quoted paths. Bind the GOAL before every operation:

```text
python3 -B "<plugin-dir>/scripts/goal_workspace.py" view "<worktree>"
```

Read the returned sole context and use the view's objective, digest, and `C*` as
authority. Stop without writing if the workspace is absent, partial, linked,
tracked, inconsistent, or bound to another objective. The fixed control paths
are `.steward/project-adapter.json` and `.steward/verification/campaign` beneath
`<worktree>`. Preserve `.steward/` through every outcome.

## Route the operation

| Operation | Route |
| --- | --- |
| `inspect` | Run `status` only when both fixed controls exist. Report no Campaign when neither exists, or the preserved partial/invalid state when exactly one exists or validation fails. |
| `resume` | Require both controls to be valid, read [`state-and-evidence.md`](references/state-and-evidence.md), run `resume` once, and report without starting another phase. |
| `audit` | Require both controls to be valid, read [`state-and-evidence.md`](references/state-and-evidence.md), run `audit` once, and report. |
| `accept` | Follow the complete workflow below. |

```text
python3 -B "<skill-dir>/scripts/campaign.py" status --adapter "<worktree>/.steward/project-adapter.json"
python3 -B "<skill-dir>/scripts/campaign.py" resume --adapter "<worktree>/.steward/project-adapter.json"
python3 -B "<skill-dir>/scripts/campaign.py" audit --adapter "<worktree>/.steward/project-adapter.json"
```

## Authority and repair policy

`inspect` authorizes reads only. `resume` authorizes only kernel control writes
needed for its one journal-directed recovery operation. `audit` authorizes only
audit reads and a successful kernel-owned audit event. Neither authorizes source
edits, initialization, or additional phases.

`accept` authorizes the fixed `.steward` controls. Before initializing a new
Campaign, choose `<repair-policy>` once: honor an explicit `verify-only` request;
otherwise use `within-goal`. An existing Campaign keeps its persisted policy and
is never reinitialized or widened.

Source repair is authorized only during `accept` under persisted `within-goal`
when the latest failure is bound, the root cause proved, the exact delta recorded,
and the edit remains inside the GOAL. External writes, real services or devices,
credentials, deployments, purchases, destructive effects, and GOAL-external
repairs require separate authorization. Inspect every Adapter argv, fixture,
capability, and effect as untrusted executable input before running it.

## Accept the GOAL

- When both controls are absent, read
  [`project-adapter.md`](references/project-adapter.md) and
  [`verification-patterns.md`](references/verification-patterns.md). Design and
  review the schema-2 Adapter in memory; create it only when every `C*` has a
  trustworthy required case. Never write a placeholder.
- When both exist, validate them and continue from journal authority without
  rebuilding or reinitializing. If current `status` remains `COMPLETE`, report it
  immediately.
- When exactly one exists, or either is partial, invalid, or obsolete, preserve
  the controls and stop.

For a new Campaign, validate and observe before initialization:

```text
python3 -B "<skill-dir>/scripts/campaign.py" validate-adapter --adapter "<worktree>/.steward/project-adapter.json"
python3 -B "<skill-dir>/scripts/campaign.py" observe-source --adapter "<worktree>/.steward/project-adapter.json"
python3 -B "<skill-dir>/scripts/campaign.py" init --adapter "<worktree>/.steward/project-adapter.json" --repair-policy "<repair-policy>"
```

Read [`state-and-evidence.md`](references/state-and-evidence.md) before mutation
or recovery and let it own journal, repair, retry, drift, regression, and audit
details. Complete initial acceptance, any eligible repair and targeted retest,
remaining initial cases, a fresh regression from case one, and final audit.
Never hand-edit journal state or projections.

## Report

Lead with the selected operation's outcome and include only evidence that exists
and matters to it. Report Campaign fields only when a Campaign exists, and final
fingerprints, regression, or audit only after those results exist. For an early
blocker or Campaign-free `inspect`, report the validated GOAL binding, exact
blocker or absence, and smallest safe next action. Never invent terminal fields
or do extra work merely to populate the report.
