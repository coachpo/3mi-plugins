---
name: parallel-repository-research
description: Run parallel, read-only repository research when a question benefits from at least two independent search lanes, such as locating code, mapping architecture, inventorying implementations, or tracing dependencies. Do not use for single-point lookups, code changes, test execution, or behavioral-risk adjudication.
---

# Parallel Repository Research

Collect verifiable repository evidence without changing the target worktree. The
current main-session model coordinates the research, verifies decisive evidence,
and writes the answer; workers only search their assigned lane. This skill may be
selected implicitly or invoked as `$steward:parallel-repository-research` in
Codex or `/steward:parallel-repository-research` in Claude Code.

Use parallel lanes only when at least two independent searches are useful. For a
single symbol, file, or serial lookup, perform the same bounded research directly.
Stop at repository facts. Do not turn search evidence into severity labels,
behavioral findings, counterexamples, or verification cases.

Explicit user instructions take precedence over this skill; when they conflict,
follow the user and say which instruction here you set aside. If this skill
makes you pause, ask, or leave requested work unfinished, name the instruction
that caused it.

## Plan the research lanes

Resolve the exact target worktree and give each lane a self-contained,
non-overlapping objective. Distinguish optional lanes when aggregate completeness
does not depend on them; otherwise treat each lane as required. Once a lane is
dispatched, its own scope and prompt do not change — a lane that needs a different
objective is a new lane, not an edit.

Add a lane whenever the research actually needs one, including after an earlier
lane's result opens a genuinely new, useful direction. Do not split or broaden a
lane already dispatched, and do not add a lane for a direction that would not
change the answer.

Set `maxConcurrent` to the number of worker slots available, or to `1` for the
sequential fallback.

### Worker input contract

Give every lane a self-contained prompt covering:

- **Objective:** the bounded evidence question and how it serves the research goal.
- **Scope:** the resolved target worktree and included or excluded paths; searches
  stay beneath that root.
- **Constraints:** applicable instructions, `read-only`, `no-network`,
  `no-secrets`, `no-delegation`, and any explicit limits or stopping conditions.

Request the concise result described below. Add lane identifiers, source/version
bindings, cross-check relationships, coverage records, or evidence budgets only
when the task needs them; no fixed field names or empty placeholders are required.
Do not invent a source binding when none applies. Repeat applicable instructions
in the prompt rather than relying on inherited conversation context.

Each lane has `maxAttempts=2` and `retryOn=transient-only`. Attempt two must
reuse the identical prompt and is allowed only after a transient worker-launch or
read-tool failure. An incomplete search, evidence gap, conflict, or source drift
is a result, not a retry reason.

## Select one host adapter

Read exactly one adapter for the current host and do not load the other:

- Codex: [`references/codex.md`](references/codex.md)
- Claude Code: [`references/claude-code.md`](references/claude-code.md)

For ordinary read-only research, delegate independent lanes when current tool
permissions and task authorization allow it. A dedicated read-only sandbox is
not required; each worker must follow the scoped read-only constraints below.
When the user, project instructions, or higher-priority rules explicitly require
mechanical isolation, delegate only when the runtime restricts workers to
repository reads and read-only Git with writes and network access disabled.
If that requirement cannot be met, or delegation is otherwise unavailable, use
the sequential fallback and execute every lane in the coordinator without
dropping or broadening scope, subject to the same applicable requirements.

Prompt constraints are not mechanical isolation and do not override runtime
permissions. Delegation grants no additional read scope or execution authority.
Disclose missing isolation capabilities when they affect the user's requirements.

The coordinator and any worker may inspect files, configuration, tests as text,
symbols, directories, and read-only Git history. The fixed constraints prohibit
file or Git writes; project code, tests, builds, package tools, installers, and
migrations; network or external-service calls; seeking, copying, or returning
secret values; and further delegation.

## Return the lane result

Each lane returns a concise conclusion, evidence locations (project-relative
`path:line` or symbols and the facts they prove), and unresolved issues, if any.
Keep the conclusion within the lane's scope. Include material conflicts,
unsearched scope, blockers, or source drift among unresolved issues so the
coordinator can judge completeness. Add source bindings, detailed coverage,
explicit status, or stopping reasons when needed for the task or audit trail;
a simple lookup does not require a full result schema.

A lane is `complete` only when its objective and scope are satisfied, `partial`
when useful evidence exists but material scope remains, `blocked` when it cannot
be searched, and `drifted` when its source binding or cited source is no longer
valid.

## Verify and aggregate

The coordinator reopens decisive evidence, confirms it against the inspected
source and any applicable source binding, deduplicates overlaps, and preserves
material conflicts. Always give the
aggregate `status` — `complete`, `partial`, `blocked`, or `drifted` — and a
`directAnswer` to the original research goal. Then add only what applies:
coordinator-verified evidence with citations, combined searched coverage,
unsearched scope, unresolved conflicts, and gaps. Write it as prose; an empty
category is omitted, not reported as empty.

Per-lane results back that answer and stay available. Surface them when the
reader needs the audit trail or when lanes disagree, not by default.

Use `complete` only when every required lane is complete and coordinator
verification succeeds. If useful evidence exists but any required lane is not
complete, or a material gap remains, use `partial`. Use `blocked` when missing
access or tooling prevents any useful evidence-backed answer. Use `drifted` when
a bound source changed or a required lane drifted; do not synthesize invalidated
evidence. State meaningful unsearched scope, conflicts, gaps, and any sequential
fallback or read-only-enforcement limitation that affects trust in the final
answer's prose.
