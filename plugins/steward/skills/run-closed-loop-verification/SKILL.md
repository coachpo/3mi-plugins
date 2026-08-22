---
name: run-closed-loop-verification
description: Validate an existing verification adapter, or execute, resume, inspect, audit, export, and aggregate its durable campaign evidence. Use for multi-stage or fix-and-retest verification that needs recovery and final same-source regression; use configure-project-verification for static profile/local/CI configuration and a normal test command for one-off checks.
---

# Closed-loop Verification

Deliver the requested adapter or campaign operation with durable evidence. A
completed campaign requires requested coverage on one final source baseline and
a successful kernel audit.

This workflow requires an explicit user request for the named operation or a
current-gate request from an explicitly requested full-loop coordinator; do not
turn an ordinary test command into a campaign.

Resolve this skill directory as `<skill-dir>` and invoke the bundled kernel at
`"<skill-dir>/scripts/campaign.py"`; never assume the target project contains it.

## Choose the operation and reference

| Operation | Effect | Read when selected |
| --- | --- | --- |
| `design` | Inspect and propose an adapter; no mechanical-validity claim. | [`project-adapter.md`](references/project-adapter.md) and [`verification-patterns.md`](references/verification-patterns.md) |
| `bootstrap` | Write the requested adapter and validate it; no campaign. | Same adapter and pattern references |
| `validate-adapter`, `observe-source` | Fully read-only contract/source validation. | [`project-adapter.md`](references/project-adapter.md) |
| `execute`, `resume` | Write campaign-owned state and run authorized local cases. | Adapter reference plus [`state-and-evidence.md`](references/state-and-evidence.md) |
| `status`, `audit` | Read authoritative journal state and current completion. | State and evidence reference |
| `fix-and-retest` | Apply bounded evidence-supported source repairs and continue the campaign. | State and evidence reference plus the fix template |
| `export-platform-evidence`, `aggregate-platform-evidence` | Write only the profile-declared evidence output. | [`platform-evidence.md`](references/platform-evidence.md) |

Do not load unrelated operation procedures. Keep project commands, fixtures,
source inventory, side effects, and evidence assertions in the adapter; the
kernel alone owns campaign state, recovery, execution, and audit.

## Authorization

A direct request for an operation authorizes its normal project-local effects:
the named adapter for `bootstrap`, the declared campaign root for execution, and
the exact profile-declared output for export or aggregation. Freeze and report
those paths before the first write. A fix-and-retest request also authorizes the
smallest evidence-supported source repair and the disclosed request/Review
handoffs needed by a strict campaign, within the same frozen project write set.

Do not ask again for those paths on each phase or new campaign root. Confirmation
is still required for a path outside the frozen set, external writes or remote
execution, production or real-device access, credentials, destructive or paid
actions, or material scope expansion. Read-only network lookup follows the live
sandbox and approval policy; neither adapters nor journals expand authority.

Treat adapters as executable untrusted input. Inspect executable, complete argv,
cwd, fixtures, timeouts, source policy, external capabilities, and side effects
before execution. Reject or escalate anything outside the operation boundary.

## Execute and recover

Use `python3 -B` and quote paths. Core commands are:

```text
python3 -B "<skill-dir>/scripts/campaign.py" validate-adapter --adapter "path/to/adapter.json"
python3 -B "<skill-dir>/scripts/campaign.py" observe-source --adapter "path/to/adapter.json"
python3 -B "<skill-dir>/scripts/campaign.py" init --adapter "path/to/adapter.json"
python3 -B "<skill-dir>/scripts/campaign.py" run --adapter "path/to/adapter.json"
python3 -B "<skill-dir>/scripts/campaign.py" status --adapter "path/to/adapter.json"
python3 -B "<skill-dir>/scripts/campaign.py" audit --adapter "path/to/adapter.json"
```

On resume, rebuild state from the validated adapter and journal `status`, not
chat memory or projections. Use journal `resumeMode` as the continuation
authority. Preserve interrupted artifacts, never hand-edit history, and follow
the reference's drift/new-root rules. A follow-up may adjust constraints within
existing authority but does not authorize new effects.

Quick cases are diagnostic history. They never replace ordinary initial
coverage, targeted retest never replaces full regression, and a successful
regression still requires audit. Stop at the first kernel `FAILED` or `BLOCKED`
result and leave later cases pending.

## Bound repairs and retries

At the start of a fix-and-retest request, freeze one task-wide source-repair
budget. Use the user's positive limit when supplied; otherwise allow at most one
automatic project-source repair followed by targeted retest. Count repairs
across campaign roots, superseded fixes, and repeated invocations in the same
task; a new root does not reset the budget.

Stop before another edit when the budget is exhausted, the same failure recurs
without new evidence, rejection codes show no material progress, the next repair
would expand scope, or the required strict Review handoff cannot be established.
Report the failed case/rejection, evidence obtained, repairs already attempted,
and smallest next action. The kernel's separate one-retry rule for a recoverable
`BLOCKED` prerequisite remains unchanged.

For a request-bound strict campaign, the coordinator—not the Reviewer—owns
fresh expected-request and Review paths and persistence. Follow the post-fix
handoff and supersession rules in `state-and-evidence.md`; never reuse a stale
binding or invent an outer retry loop.

## Complete and report

Run a separate full regression from case one, then audit. Completion is exactly:

```text
RequestedCoverageSatisfied ∧ audit.ok
```

Source or catalog drift during regression invalidates that attempt and requires
the reference's new-root path; it never triggers an automatic restart. A valid
adapter, quick pass, initial pass, targeted retest, projection, or aggregation
alone is not campaign completion.

Lead with the requested operation's outcome. Preserve the evidence necessary to
support it: adapter/campaign/output identity, `executionStatus`,
`completionStatus`, audit result and rejection codes, `resumeMode`, coverage and
source/catalog/trace bindings, final regression, artifacts, unverified real-host
branches, and the smallest safe next action. Omit fields irrelevant to the
selected operation. Never discover, create, or mutate host Goal state; any trace
GOAL contract must be supplied explicitly through the adapter or request.
