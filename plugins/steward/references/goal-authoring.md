# Consensus GOAL authoring

This is the single authoring contract for a new seven-line GOAL, and
`draft-consensus-goal` is its sole skill owner. Other skills consume an explicit
validated GOAL or delegate an already-converged request to that skill; they do
not independently draft, compress, or externalize one.

## Bind the target worktree

The main session or caller must supply exactly one already-resolved session
worktree root as `<target-worktree-root>`. Resolve the calling skill directory
as `<skill-dir>`, then validate the supplied absolute path through:

```text
python3 -B "<skill-dir>/../../scripts/worktree_binding.py" view "<target-worktree-root>"
```

Freeze the canonical `view` in memory. Do not discover or replace the target
from `<skill-dir>`, shell cwd, a repository match, or any other worktree. Before
each fact-gathering phase and each conditional write, require the caller to
freshly provide `<current-session-worktree-root>` and pass it to `verify-view`
with the frozen view on standard input. The fresh value comes from the caller's
session workspace binding, never cwd. When a command reports a project root,
validate it with `verify-root`; run repository commands with
`git -C "<target-worktree-root>"` or an equivalent explicit workdir, with
repository-selecting `GIT_DIR`, `GIT_WORK_TREE`, and related overrides cleared.

Missing or multiple candidates, resolution failure, a normalized Git top-level
different from the supplied root, a sibling substituted for or observed instead
of the frozen target, or binding drift is a blocker. Stop without writing a
handoff or returning a GOAL. Keep absolute binding paths internal; the
seven-line GOAL and every handoff reference use project-relative paths.

## Establish the source facts

Treat the current user request and later accepted decisions as the authority for
the result, scope, and allowed effects. Verify workspace facts only as needed to
make the outcome, paths, commands, constraints, and completion checks accurate.
Repository evidence can constrain an implementation, but it cannot expand the
request. Read every repository fact from `<target-worktree-root>`.

Do not treat assistant suggestions, rejected options, silence, examples, stale
summaries, or superseded decisions as consensus. A reasonable assumption may be
used only when it cannot materially change outcome, scope, authority, cost, or
risk; label it with `假设：` in `约束与授权`. Otherwise ask the smallest question
and do not emit a GOAL.

## Use project strategy without expanding the contract

For an engineering GOAL, inspect the managed Current Development Strategy when
it intersects the request. First validate the exact `STATUS.md` development-tier
line, complete static asset catalog, and selected managed block through the
read-only project-docs validator with `<target-worktree-root>` as its explicit
project-root argument. Read the consumer rules in
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

Use [`goal-template.txt`](goal-template.txt) exactly. The output has seven
logical lines, in the template order, with the exact labels and full-width
colon. Fill every placeholder. `结果`, `范围`, `完成标准`, and `最终交付` require
substantive content; the other fields may be `无` when nothing applies.

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
directory entries, and its self-ignoring rule beneath
`<target-worktree-root>/.steward/handoffs/`. Never emit an unvalidated
objective.
