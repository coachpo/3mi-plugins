# Consensus GOAL authoring

This is the single authoring contract for a new seven-line GOAL, and
`draft-consensus-goal` is its sole skill owner. Other skills consume an explicit
validated GOAL or delegate an already-converged request to that skill; they do
not independently draft, compress, or externalize one.

## Bind the target worktree

The caller supplies exactly one already-resolved absolute
`<target-worktree-root>`. If an invoking Steward workflow already froze the
canonical binding for that exact root, consume the supplied `view` unchanged and
do not create a second binding. Otherwise resolve the calling skill directory as
`<skill-dir>`, validate the target once, and freeze canonical stdout in memory:

```text
python3 -B "<skill-dir>/../../scripts/worktree_binding.py" view "<target-worktree-root>"
```

Never derive or replace the target from `<skill-dir>`, shell cwd, repository
discovery, or a sibling worktree. Run every repository command with
`git -C "<target-worktree-root>"` or an equivalent explicit workdir, clearing
`GIT_DIR`, `GIT_WORK_TREE`, and related repository-selection overrides.

Revalidate the frozen root, Git-directory, and common-directory binding on resume
or context loss, after actual evidence of target drift, and immediately before a
permitted write. Supply the frozen `view` on standard input. This detects changes
to those binding fields; it does not attest to host or conversation state or
prove that a repository recreated at identical filesystem paths is unchanged:

```text
python3 -B "<skill-dir>/../../scripts/worktree_binding.py" verify-view "<target-worktree-root>" -
```

When a command reports a project root, validate it with `verify-root`. Missing
or multiple candidates, resolution failure, a normalized Git top-level different
from the supplied root, a sibling worktree, or binding drift blocks delivery
before further writes. Keep absolute binding paths internal; the GOAL and its
goal-context reference use project-relative paths.

## Establish the source facts

Treat the current user request and later accepted decisions as the authority for
the result, scope, and allowed effects. Verify workspace facts only as needed to
make the outcome, paths, commands, constraints, and completion checks accurate.
Repository evidence can constrain an implementation, but cannot expand the
request. Read every repository fact from `<target-worktree-root>`.

Do not treat assistant suggestions, rejected options, silence, examples, stale
summaries, or superseded decisions as consensus. Use a reasonable assumption
only when it cannot materially change outcome, scope, authority, cost, or risk;
label it with `假设：` in `约束与授权`. Otherwise ask the smallest question and do
not emit a GOAL.

## Use project strategy without expanding the contract

For an engineering GOAL, inspect the managed Current Development Strategy only
when it intersects the request. Validate the exact `STATUS.md` development-tier
line, complete static asset catalog, and selected managed block through the
read-only project-docs validator with `<target-worktree-root>` as its explicit
project-root argument. Read
[`development-tiers.md`](../skills/write-project-docs/references/development-tiers.md)
only in that case.

The static tier strategy is an execution default, not user consensus,
authorization, exclusion proof, or a new fact source. It may choose among
already-authorized approaches. Put an item from it into `结果`, `范围`, or a `C*`
criterion only when the user accepted that item or a governing hard requirement
independently requires it. Ask when doing so would materially change the result,
scope, or completion definition. User requirements, hard invariants, real data,
existing users, compatibility commitments, and reachable risks take precedence.

## Write and validate the contract

Use [`goal-template.txt`](goal-template.txt) exactly. The output has seven
logical lines in template order, with the exact labels and full-width colon.
Fill every placeholder. `结果`, `范围`, `完成标准`, and `最终交付` require substantive
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

## Create the required goal context

Keep the GOAL lean while retaining its result, scope, authority boundary,
completion evidence, `C*`, legitimate blockers, and final delivery. For every
GOAL, read and apply [`goal-context.md`](goal-context.md) and create exactly one
new context file before delivery. Record verified sources and useful background,
including the current request or later accepted decisions when no richer
repository context is needed.

The context contract exclusively defines eligible content, placement,
non-overwrite behavior, validation-before-write ordering, ignore rule, rollback,
and failure handling. The only authoring writes are those it permits below
`<target-worktree-root>/.steward/goal-context/`. Successful context creation is
required before returning the validated objective.
