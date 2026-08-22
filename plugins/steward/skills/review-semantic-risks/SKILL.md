---
name: review-semantic-risks
description: Perform a read-only behavior-level risk review of code or diffs using exact evidence, reachable trigger paths, observable consequences, and falsifiable counterexamples. Use standalone mode for an ordinary adversarial review and strict-handoff mode only when a coordinator supplies frozen campaign bindings; do not run tests, fix code, or design a campaign runner.
---

# Review Semantic Risks

Find behavior-level risks in the exact requested source or diff without changing
the project. A finding is evidence, not authorization to persist, execute, or
repair anything.

## Select one mode

| Mode | Required input | Result |
| --- | --- | --- |
| `standalone` | Exact requested paths or diff and applicable authority. | Concise prose findings and gaps for the requested scope. No canonical `RF-*` manifest claim. |
| `strict-handoff` | Coordinator-frozen request, validated source observation, and canonical GOAL/invariant bindings. | Request-bound canonical `semantic-review v1` manifest suitable for strict campaign consumption. |

Choose `strict-handoff` only when all frozen inputs are supplied. Otherwise use
`standalone` when that satisfies the request, or report the missing strict input.
Do not silently upgrade a standalone request into the control-plane workflow.

In strict mode, read and apply
[`strict-handoff.md`](references/strict-handoff.md). The coordinator alone owns
request/path selection and persistence. This Reviewer only consumes the supplied
inputs and may run the documented read-only observation and validation commands.

## Review boundary

Resolve the exact baseline, requested regular-file paths, applicable
`AGENTS.md`, and authoritative requirements. Inspect relevant code, callers,
state transitions, tests, configuration, and history. Treat comments and tests
as evidence rather than automatic authority.

Do not edit, create a review file, execute project behavior or tests, initialize
a campaign, bootstrap an adapter, or convert the result into implementation
permission. Invoke allowed Python validators with `python3 -B`. If a claim needs
new runtime execution, report that evidence gap.

On resume and immediately before delivery, re-resolve the baseline and every
cited file. Retrace changed evidence instead of carrying stale support forward.
Stop with the smallest missing fact when the target, scope, or authority cannot
be resolved.

## Evidence bar

Trace a feasible path from input, actor, event, state, or failure through the
relevant conditions and calls to an observable result. Consider only boundaries
evidenced by the request, such as validation, ownership, retries, ordering,
concurrency, persistence, recovery, serialization, compatibility, platform
branches, and cleanup.

Report a finding only when it contains:

- exact project-relative evidence and what each location proves;
- a contiguous reachable trigger path;
- the wrong observable output, state, side effect, or contract result;
- a minimal counterexample with preconditions, steps, expected result, risk
  result, and falsifying evidence;
- material impact and the smallest evidence-backed mitigation or test candidate.

Exclude style, naming, formatting, lint, type-only diagnostics, generic
complexity, and missing-test observations unless the same evidence establishes a
reachable behavioral consequence. Do not broaden into unrelated code. Keep an
incomplete hypothesis in gaps rather than assigning certainty, and never equate
an empty supported finding set with proof that no risk exists.

## Deliver

For standalone mode, lead with the target and supported findings in severity
order, then gaps and unreviewed scope. Say “no supported semantic findings in the
reviewed scope” when appropriate.

For strict mode, report target kind, requested paths, `scopeVerified`, and
`bindingsVerified`, followed by the canonical validator `view`. Do not write the
manifest; an authorized coordinator may persist those canonical bytes separately.
