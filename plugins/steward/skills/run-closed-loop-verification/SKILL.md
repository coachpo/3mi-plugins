---
name: run-closed-loop-verification
description: Verify an existing Steward GOAL, repair confirmed in-scope failures, and resume its acceptance campaign. Use only for explicit GOAL acceptance, not ordinary one-off testing.
---

# Closed-loop GOAL verification

Require the alias of an existing `.steward/goals/<alias>/` bundle in the Git
worktree containing the current session cwd. Draft and verification operate on
that same physical directory. The workflow convention is one verified GOAL per
worktree; no cross-alias selector or global lock enforces it.

Explicit user instructions take precedence over this skill; when they conflict,
follow the user and say which instruction here you set aside. If this skill
makes you pause, ask, or leave requested work unfinished, name the instruction
that caused it.

For an existing campaign, inspect `status --goal <alias>` and continue its saved
execution binding with `advance --goal <alias>`. For first initialization, read
[execution-plan.md](references/execution-plan.md), bind the immutable acceptance
intent to exact commands, and initialize with a finite stdin pipe:

```text
python3 -B "<skill-dir>/scripts/campaign.py" init --goal <alias> --execution-plan -
```

Use `advance --goal <alias>` to drive the campaign and `status --goal <alias>`
for read-only inspection. One `advance` runs every mechanical phase in
sequence (cases, targeted retest of any repaired case, a final regression if
any repair happened, an integrated completion check) and stops only where the
verifier must act or decide: a failing case (`REPAIR_REQUIRED`), a blocker
(`BLOCKED`, including a failed completion check), or `COMPLETE`.

`REPAIR_REQUIRED` means a case exited non-zero, timed out, or did not produce
its declared evidence — not that project source is the proven cause. Diagnose
before repairing: `lastFailure` carries `exitCode`, `timedOut`,
`missingEvidence`, `emptyEvidence`, and `artifactDir` for that run. Repair
only a confirmed project-source root cause; an execution-binding or
environment cause takes the recovery route in
[state-and-evidence.md](references/state-and-evidence.md) instead. For a
source root cause, make the smallest authorized repair and record it:

```text
python3 -B "<skill-dir>/scripts/campaign.py" record-repair --goal <alias> --repair -
```

The payload accepts exactly these three fields, and `rootCauseSource` accepts
exactly these keys plus an optional `symbol`:

```json
{
  "rootCause": "why the case failed, bound to the source location below",
  "rootCauseSource": {"path": "src/x.py", "lineStart": 10, "lineEnd": 24},
  "fixSummary": "the one smallest change made"
}
```

An interrupted `advance` resumes its in-progress attempt. After recorded
repairs, it runs targeted retests and then an all-cases sweep against the final
source before the completion check. Any newly failing case returns the campaign
to `REPAIR_REQUIRED`; campaigns with no repairs skip the extra sweep. A happy
path is `init` plus one `advance`; a repair cycle is `record-repair` plus one
`advance`.

Read [state-and-evidence.md](references/state-and-evidence.md) when diagnosing
failure, interruption, source drift, artifact integrity, or a rejected
completion check.

Before reporting completion, require `completionStatus: COMPLETE` and compare
the report's `sourceFingerprint` with `completion.sourceFingerprint`. A completed
campaign preserves its historical result and `advance` does not rerun it. If
the fingerprints differ, inspect the actual changes and state which acceptance
evidence still applies. Report current acceptance as incomplete if relevant
behavior changed or its effect is uncertain; re-proving it requires a new
campaign through the recovery route above. If the changes cannot affect the
accepted behavior, explain that basis in the completion report.

Explicit invocation authorizes reviewed local cases, per-GOAL ignored controls,
and evidence-backed source repairs inside the accepted GOAL. It does not grant
external effects, credentials, destructive restoration, commits, deployment,
or broader implementation authority. Report `complete`, `incomplete`, or
`blocked`, then only the applicable details: the GOAL alias, decisive
case/criterion evidence, repairs, the completion check, every waived
non-required failure listed as an unmet optional intent, and remaining
limitation.
