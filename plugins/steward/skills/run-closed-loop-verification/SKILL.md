---
name: run-closed-loop-verification
description: Verify one existing alias-scoped Steward GOAL in the current Git worktree through a frozen execution binding, resumable evidence journal, proven repairs, targeted retests, final same-source regression, and audit. Use only for explicit GOAL acceptance, not ordinary one-off testing.
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

Use `advance --goal <alias>` for the next journal-directed phase and
`status --goal <alias>` for read-only inspection. On a proven project-source
failure, make the smallest authorized repair and record its structured evidence:

```text
python3 -B "<skill-dir>/scripts/campaign.py" record-repair --goal <alias> --repair -
```

Read [state-and-evidence.md](references/state-and-evidence.md) when diagnosing
failure, interruption, source drift, artifact integrity, or audit rejection.

Explicit invocation authorizes reviewed local cases, per-GOAL ignored controls,
and evidence-backed source repairs inside the accepted GOAL. It does not grant
external effects, credentials, destructive restoration, commits, deployment,
or broader implementation authority. Report `complete`, `incomplete`, or
`blocked` with the GOAL alias, decisive case/criterion evidence, repairs, final
regression, audit, and remaining limitation.
