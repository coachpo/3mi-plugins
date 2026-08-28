# Consensus GOAL authoring

This is the single authoring contract for a new seven-line GOAL, and
`draft-consensus-goal` is its sole skill owner. Other skills consume an explicit
validated GOAL or delegate an already-converged request to that skill; they do
not independently draft, compress, or externalize one.

## Establish the source facts

Treat the current user request and later accepted decisions as the authority for
the result, scope, and allowed effects. Verify workspace facts only as needed to
make the outcome, paths, commands, constraints, and completion checks accurate.
Repository evidence can constrain an implementation, but it cannot expand the
request.

Do not treat assistant suggestions, rejected options, silence, examples, stale
summaries, or superseded decisions as consensus. A reasonable assumption may be
used only when it cannot materially change outcome, scope, authority, cost, or
risk; label it with `假设：` in `约束与授权`. Otherwise ask the smallest question
and do not emit a GOAL.

## Use project strategy without expanding the contract

For an engineering GOAL, inspect the managed Current Development Strategy when
it intersects the request. First validate the exact `STATUS.md` development-tier
line, complete static asset catalog, and selected managed block through the
read-only project-docs validator. Read the consumer rules in
[`development-tiers.md`](../skills/write-project-docs/references/development-tiers.md)
only in that case.

The static tier strategy is an execution default, not user consensus,
authorization, exclusion proof, or a new fact source. It may choose among
already-authorized approaches. Put an item from it into `结果`, `范围`, or a `C*`
criterion only when the user accepted that item or a governing hard requirement
independently requires it. If doing so would materially change the requested
result, scope, or completion definition, ask the user instead. User requirements,
hard invariants, real data, existing users, compatibility commitments, and
reachable risks take precedence over tier defaults.

## Write and validate the contract

Resolve the calling skill directory as `<skill-dir>`, then use
[`goal-template.txt`](goal-template.txt) exactly. The output has seven logical
lines, in the template order, with the exact labels and full-width colon. Fill
every placeholder. `结果`, `范围`, `完成标准`, and `最终交付` require substantive
content; the other fields may be `无` when nothing applies.

Write independently verifiable completion outcomes as `(C1) ...；(C2) ...`,
with unique consecutive IDs starting at `C1`. Keep those IDs stable within the
same canonical objective and digest. Do not put case IDs, adapter paths, or
digests in the GOAL.

Describe the destination and proof, not unnecessary implementation steps. Keep
the contract self-contained and at most 4,000 Unicode code points. Do not add a
title, preface, Markdown list, code fence, XML/HTML wrapper, or an eighth line.

Validate the candidate through standard input:

```text
python3 -B "<skill-dir>/../../scripts/goal_contract.py" view -
```

Never put the GOAL in argv or create a temporary validation file. Correct a
validation error only while it identifies a new, locally repairable defect. If
the same failure repeats, the validator is unavailable, an I/O error occurs, or
no evidence-backed correction remains, stop with the actual error and smallest
next action instead of looping or emitting an unvalidated contract.

## Externalize useful background

Keep the GOAL lean whether or not it approaches the limit: remove repeated
background and unnecessary implementation detail, then use precise
existing-project references where they preserve enough evidence. Always retain
the result, scope, authority boundary, evidence needed for completion, `C*`,
legitimate blockers, and final delivery.

Before final validation, identify verified material in `证据与上下文` that will
help a later reviewer or executor independently recheck a source, reproduce
relevant current behavior or failure, or understand a material interface or
specification. Read and apply [`handoff-file.md`](handoff-file.md) when such
material exists, when the ordinarily compressed inline contract still exceeds
the limit before externalization, or when the user explicitly asks for a
context file. That contract exclusively defines eligible content, default and
required creation, the no-content branch, placement, write ordering, fallback,
and blocking behavior; GOAL length is not the default-creation gate.

The authoring skill may create only the disclosed handoff, its necessary
directory entries, and its self-ignoring rule beneath `.steward/handoffs/`.
Never emit an unvalidated objective.
