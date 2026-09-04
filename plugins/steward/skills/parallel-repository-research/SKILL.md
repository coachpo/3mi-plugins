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

## Plan the research lanes

Resolve the exact target worktree, then define each lane's `laneId`, whether it
is `required`, and its optional `crossCheckOf`. Give each lane a self-contained,
non-overlapping objective; once a lane is dispatched, its own scope and prompt do
not change — a lane that needs a different objective is a new lane, not an edit.

Add a lane whenever the research actually needs one, including after an earlier
lane's result opens a genuinely new, useful direction. Do not split or broaden a
lane already dispatched, and do not add a lane for a direction that would not
change the answer.

Set `maxConcurrent` to the number of worker slots available, or to `1` for the
sequential fallback.

### Worker input contract

Give every lane a self-contained prompt with exactly these fields:

- `laneId`: lane identifier;
- `required`: whether aggregate completeness depends on this lane;
- `crossCheckOf`: another lane identifier or `not-applicable`;
- `targetRoot`: resolved worktree root; searches stay beneath it;
- `researchGoal`: question the aggregate answer must resolve;
- `include`: paths and file classes inside scope;
- `exclude`: generated, vendor, or otherwise excluded scope;
- `sourceBinding`: relevant revision, baseline, diff, or observed source identity;
- `laneObjective`: one bounded, non-overlapping evidence question;
- `applicableInstructions`: governing instructions needed to execute the lane;
- `evidenceBudget`: search depth or evidence limit and stopping condition;
- `outputContract`: the lane-result schema below;
- `constraints`: `read-only`, `no-network`, `no-secrets`, and `no-delegation`.

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

Use delegated workers only when the host mechanically restricts their tools to
repository reads and read-only Git inspection with network access disabled. This
is `delegationGate=mechanical-read-only-no-network`; prompt restrictions alone do
not pass it. Otherwise use `fallbackRoute=sequential` and execute every lane in
the coordinator without dropping or broadening scope.

The coordinator and any worker may inspect files, configuration, tests as text,
symbols, directories, and read-only Git history. The fixed constraints prohibit
file or Git writes; project code, tests, builds, package tools, installers, and
migrations; network or external-service calls; seeking, copying, or returning
secret values; and further delegation.

## Return the lane result

Every lane returns all of these fields:

- `laneId`: lane identifier;
- `status`: `complete`, `partial`, `blocked`, or `drifted`;
- `sourceBinding`: the binding actually searched and cited;
- `directAnswer`: concise lane answer without cross-lane judgment;
- `evidence`: project-relative `path:line` or symbol locators and the fact proved;
- `searched`: paths, symbols, history, and strategies examined;
- `unsearched`: requested or relevant scope not examined;
- `conflicts`: contradictory repository evidence;
- `gaps`: unanswered questions and the smallest missing evidence;
- `stoppingReason`: satisfied, budget exhausted, transient retry exhausted,
  blocked, or drifted.

A lane is `complete` only when its objective and scope are satisfied, `partial`
when useful evidence exists but material scope remains, `blocked` when it cannot
be searched, and `drifted` when its source binding or cited source is no longer
valid.

## Verify and aggregate

The coordinator reopens decisive evidence, confirms it against the bound source,
deduplicates overlaps, and preserves material conflicts. Return exactly:

- `status`: aggregate `complete`, `partial`, `blocked`, or `drifted`;
- `directAnswer`: answer to the original research goal;
- `evidence`: coordinator-verified citations and claims;
- `searched`: combined verified search coverage;
- `unsearched`: requested or relevant scope not covered;
- `conflicts`: unresolved repository disagreement;
- `gaps`: missing evidence and limitations;
- `laneResults`: one final result for every lane run.

Use `complete` only when every required lane is complete and coordinator
verification succeeds. If useful evidence exists but any required lane is not
complete, or a material gap remains, use `partial`. Use `blocked` when missing
access or tooling prevents any useful evidence-backed answer. Use `drifted` when
a bound source changed or a required lane drifted; do not synthesize invalidated
evidence. State meaningful unsearched scope, conflicts, gaps, and any sequential
fallback or read-only-enforcement limitation that affects trust in the final
answer's prose.
