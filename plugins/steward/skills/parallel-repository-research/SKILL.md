---
name: parallel-repository-research
description: Run parallel, read-only repository research when a question benefits from at least two independent search lanes, such as locating code, mapping architecture, inventorying implementations, or tracing dependencies. Do not use for single-point lookups, code changes or test execution, or semantic-risk adjudication handled by review-semantic-risks.
---

# Parallel Repository Research

Collect verifiable repository evidence without changing the target worktree. The
current main-session model is always the coordinator: it plans the search,
dispatches workers when useful, verifies their evidence, and writes the final
research answer. Do not assume or require a particular coordinator model.

Users may invoke this skill explicitly as
`$steward:parallel-repository-research` in Codex or
`/steward:parallel-repository-research` in Claude Code. It may also be selected
implicitly for a matching research request.

## Decide whether to fan out

Fan out only when the question can be split into at least two independently
useful lanes whose evidence can be collected concurrently. Good lanes cover
distinct components, entry points, dependency directions, implementation
families, or bounded directory groups.

An explicit invocation does not force delegation. For a single symbol, file, or
tightly serial lookup, perform the narrow read-only search directly and do not
spawn workers. Do not use this skill to edit code, run tests, or decide semantic
risk findings. Neutral evidence gathered here may support a later review, but
findings, severity, counterexamples, `RF-*` records, and campaign cases belong to
`review-semantic-risks`.

## Freeze the research contract

Resolve the exact target repository before dispatch. Give every worker a
self-contained lane prompt with these bindings:

- `targetRoot`: the exact worktree root; all paths and searches stay beneath it;
- `researchGoal`: the question the final answer must resolve;
- `include` and `exclude`: requested paths, file classes, generated/vendor
  boundaries, and other scope limits;
- `sourceBinding`: the applicable baseline, diff, revision, or observed source
  identity when the request depends on one;
- `laneObjective`: one non-overlapping evidence question assigned to this worker;
- `evidenceBudget`: the intended search depth, time or evidence limit, and the
  stopping condition;
- `outputContract`: the result fields defined below;
- host controls: Codex `reasoningEffort` or Claude `searchDepth`, never treating
  one as the other.

Do not invent a baseline or diff when it is irrelevant. A worker must be able to
complete its lane from its prompt without relying on the main conversation,
unstated repository rules, or another worker's result.

## Plan lanes and capacity

Create one worker per useful independent lane, bounded by the host's currently
available worker slots. The coordinator chooses the lane count; there is no
fixed worker default. Dispatch independent lanes concurrently. If useful lanes
outnumber available slots, run them in batches without duplicating a completed
lane.

Workers must not delegate to further agents. Start a later batch only for a new
evidence gap, a deliberate independent cross-check, or a lane invalidated by
source drift. Repeating this skill later in the same investigation is valid, but
do not repeat already satisfied searches without one of those reasons.

## Use the host adapter

### Codex

Spawn each lane with model `gpt-5.6-luna`. The current coordinator selects a
per-lane `reasoning_effort` from `low`, `medium`, `high`, `xhigh`, or `max`
according to the lane's ambiguity and depth; do not derive it from the
coordinator's model or apply one fixed value to every lane.

When overriding the worker model, set `fork_turns` to `"none"` or to the smallest
positive turn count that supplies indispensable context. Never omit it or use
`"all"` with the model override. Prefer `"none"` because the frozen lane prompt
is self-contained.

### Claude Code

Use the built-in `Explore` subagent for every lane and request `model: haiku` on
each invocation. Pass one of `quick`, `medium`, or `very thorough` as the lane's
`searchDepth`. This controls search work, not model reasoning effort; report
Claude `reasoningEffort` as not applicable rather than claiming equivalence.

Do not rely on Explore inheriting the main conversation or its complete rules.
Repeat `targetRoot`, scope, lane objective, read-only restrictions, stopping
condition, and output contract in every Explore prompt.

### Sequential fallback

When the host has no subagent capability, no usable worker slot, or the required
worker model is unavailable, perform the same lanes sequentially in the current
coordinator. Report `sequential-fallback` and the reason. Limited capacity alone
uses batches when at least one worker slot remains; it is not a reason to drop
lanes or silently broaden their scope.

## Keep the scan read-only

The coordinator and workers may read files, inspect tests and configuration as
text, search text or symbols, list directories, and use read-only Git inspection.
They must not:

- create, edit, delete, format, generate, or redirect output into repository
  files;
- run project code, tests, builds, formatters, code generation, package managers,
  installers, migrations, or other commands that may alter the worktree;
- perform Git writes, network requests, or external-service calls;
- seek, copy, or return secret values;
- use the research request as authority for a fix or any other mutation.

Describe enforcement accurately. Use `sandbox` only when an actual read-only
sandbox enforces the boundary, `tool-restricted` for Claude Explore's restricted
tool surface, and `instruction-only` when Codex or the sequential fallback lacks
mechanical read-only enforcement. Never present prompt restrictions as a
mechanical guarantee.

## Return lane evidence

Each worker returns a structured conversational result with all of these fields:

- `status`: `complete`, `partial`, `blocked`, or `drifted`;
- `directAnswer`: the lane's concise answer, without final cross-lane judgment;
- `evidence`: project-relative `path:line` citations or symbols, with the fact
  each location proves;
- `searched`: paths, symbols, history, and strategies actually examined;
- `unsearched`: requested or relevant scope not examined;
- `conflicts`: contradictory evidence or source disagreement;
- `gaps`: unanswered questions and the smallest search needed to close each one;
- `execution`: host adapter, requested worker model, `reasoningEffort` binding,
  `searchDepth` binding, and `readOnlyEnforcement`.

Use `complete` only when the lane objective and bounded scope are satisfied.
Use `partial` when useful evidence exists but the stopping condition arrived
first, `blocked` when the lane could not be searched, and `drifted` when cited
source changed enough to invalidate the result.

## Verify and synthesize

The coordinator reopens decisive evidence, confirms paths against the current
source, deduplicates overlaps, and reconciles conflicts before answering. Rerun
only the affected lanes when source drift invalidates evidence. Preserve
material disagreement when the repository does not resolve it.

Deliver the answer to the original research question with verified citations,
then state meaningful unsearched scope, conflicts, gaps, fallback use, and
read-only enforcement limitations. Stop at repository facts and evidence; do
not turn the synthesis into semantic-risk adjudication or implementation work.
