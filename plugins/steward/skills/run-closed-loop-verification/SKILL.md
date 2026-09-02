---
name: run-closed-loop-verification
description: Accept an existing Steward GOAL in one explicit worktree through a recoverable local Campaign, evidence-backed GOAL-scoped repairs, targeted retests, one final full regression, and a current audit. Use only for explicit acceptance of .steward/goal.txt; use ordinary project commands for one-off testing.
---

# Closed-loop GOAL verification

Accept a claimed-complete GOAL through one recoverable local Campaign. Repair only
proven project-source defects inside the GOAL and report completion only when every
GOAL `C*` has required final-pass evidence on one current source and the final
audit succeeds.

## Bind the GOAL

Require one caller-resolved absolute worktree and validate its canonical GOAL:

```text
python3 -B "<plugin-dir>/scripts/goal_workspace.py" view "<worktree>"
```

Read the sole context and use the GOAL result, scope, constraints, blockers,
criteria, and deliverables as authority. The GOAL validator owns only
`.steward/goal.txt`, its context, and the root ignore contract; verification
state is validated by this skill.

## Prepare the Campaign

When both controls are absent, read
[project-adapter.md](references/project-adapter.md) and
[verification-patterns.md](references/verification-patterns.md). Create the
minimal schema-2 Adapter only after every `C*` has a trustworthy required case.
The fixed paths are `.steward/project-adapter.json` and
`.steward/verification/campaign`.

Initialize once:

```text
python3 -B "<skill-dir>/scripts/campaign.py" init --adapter "<worktree>/.steward/project-adapter.json"
```

Initialization validates the Adapter and current source before creating the
hash-chained journal. The journal is the sole durable Campaign authority; status
and summaries are derived in memory. If exactly one control exists, or an
existing control is invalid or incompatible, preserve it and report the blocker.

## Advance acceptance

Use one command for the next journal-directed action:

```text
python3 -B "<skill-dir>/scripts/campaign.py" advance --adapter "<worktree>/.steward/project-adapter.json"
```

It resumes an interrupted attempt, runs pending initial cases, performs a
targeted retest, starts the final regression, or completes the audit according to
current state. One invocation performs one phase and returns the next state.

A complete initial pass with no repair is already the required same-source full
regression and proceeds directly to audit. After any repair, a passing targeted
retest is followed by one fresh full regression from case one.

For a failed project-source case:

1. Prove the root cause and make the smallest coherent GOAL-scoped repair.
2. Fill [repair-note.template.json](assets/repair-note.template.json) at
   `<worktree>/.steward/repair-note.json`. Supply only the diagnosis, source
   location, and fix summary; the kernel derives failure IDs, source fingerprints,
   affected criteria, failed-file digest, and exact source delta.
3. Record the repair, then call `advance` again:

```text
python3 -B "<skill-dir>/scripts/campaign.py" record-fix --adapter "<worktree>/.steward/project-adapter.json" --fix "<worktree>/.steward/repair-note.json"
python3 -B "<skill-dir>/scripts/campaign.py" advance --adapter "<worktree>/.steward/project-adapter.json"
```

Continue only while a new failure fingerprint or changed failed-source digest
provides observable progress. Stop when the root cause is unproved, the same
machine-bound failure recurs, a repair would leave the GOAL, or a required
environment or capability is unavailable. Source drift invalidates only the
affected regression attempt; restoring the recorded baseline permits a fresh
regression.

Inspect without mutation with:

```text
python3 -B "<skill-dir>/scripts/campaign.py" status --adapter "<worktree>/.steward/project-adapter.json"
```

Read [state-and-evidence.md](references/state-and-evidence.md) when diagnosing a
failure, interruption, drift, artifact problem, or audit rejection.

## Authority and report

Explicit invocation authorizes reviewed local cases, the fixed Steward controls,
and evidence-backed project-source repairs inside the accepted GOAL. Other effects
retain their existing authorization requirements. Review every command and side
effect before execution.

Lead with `complete`, `incomplete`, or `blocked`. Include the GOAL binding,
relevant case and criterion evidence, repairs, final regression, audit result, and
remaining limitation. Never infer completion from chat history or a targeted
retest.
