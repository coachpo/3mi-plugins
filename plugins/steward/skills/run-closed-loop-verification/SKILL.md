---
name: run-closed-loop-verification
description: Verify one existing alias-scoped Steward GOAL in the current Git worktree through a frozen execution binding, a durable resumable campaign state, proven repairs, and targeted retests with an integrated completion check. Honors Draft-declared waived non-required cases and writable files; use only for explicit GOAL acceptance, not ordinary one-off testing.
---

# Closed-loop GOAL verification

Require the alias of an existing `.steward/goals/<alias>/` bundle in the Git
worktree containing the current session cwd. Draft and verification operate on
that same physical directory. The workflow convention is one verified GOAL per
worktree; no cross-alias selector or global lock enforces it.

Read [execution-plan.md](references/execution-plan.md) before initialization.
Create the exact execution binding from the immutable acceptance intent, then
initialize with a finite stdin pipe:

```text
python3 -B "<skill-dir>/scripts/campaign.py" init --goal <alias> --execution-plan -
```

Use `advance --goal <alias>` to drive the campaign and `status --goal <alias>`
for read-only inspection. One `advance` runs every mechanical phase in
sequence (cases, targeted retest of any repaired case, a final regression if
any repair happened, an integrated completion check) and stops only where the
verifier must act or decide: a proven project-source failure
(`REPAIR_REQUIRED`), a blocker (`BLOCKED`, including a failed completion
check), or `COMPLETE`. On a proven project-source failure, make the smallest
authorized repair and record its structured evidence:

```text
python3 -B "<skill-dir>/scripts/campaign.py" record-repair --goal <alias> --repair -
```

Campaign state lives in one state file per GOAL, rewritten atomically after
each phase; a crash mid-advance resumes the in-progress attempt exactly where
it stopped. A repair's own retest only reruns the case(s) it fixed, for fast
feedback — but a fix proves nothing about the cases it did not touch, so once
every outstanding failure is resolved, a campaign that repaired anything owes
exactly one more all-cases sweep against the final source before the
completion check runs; that sweep can itself surface a case the repair broke,
sending the campaign back to `REPAIR_REQUIRED` for it. A campaign that never
needed a repair skips this — its one clean pass already stands against the
source being accepted. A happy path is `init` plus one `advance`; a repair
cycle is `record-repair` plus one `advance`.

Read [state-and-evidence.md](references/state-and-evidence.md) when diagnosing
failure, interruption, source drift, artifact integrity, or a rejected
completion check.

Explicit invocation authorizes reviewed local cases, per-GOAL ignored controls,
and evidence-backed source repairs inside the accepted GOAL. It does not grant
external effects, credentials, destructive restoration, commits, deployment,
or broader implementation authority. Report `complete`, `incomplete`, or
`blocked` with the GOAL alias, decisive case/criterion evidence, repairs, the
completion check, every waived non-required failure listed as an unmet
optional intent, and remaining limitation.
