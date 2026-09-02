# Consensus GOAL authoring

This is the single contract for authoring and persisting a seven-line GOAL,
including interrupted-persistence recovery. `draft-consensus-goal` is its sole
owner; other skills consume the persisted GOAL rather than drafting one.

## Bind the target worktree

The caller supplies exactly one already-resolved absolute
`<target-worktree-root>`. Resolve the calling skill directory as `<skill-dir>`,
validate that exact target once, and freeze canonical stdout in memory:

```text
python3 -B "<skill-dir>/../../scripts/worktree_binding.py" view "<target-worktree-root>"
```

Never derive or replace the target from `<skill-dir>`, shell cwd, repository
discovery, or a sibling worktree. Run repository commands with
`git -C "<target-worktree-root>"` or an equivalent explicit workdir after
clearing `GIT_DIR`, `GIT_WORK_TREE`, and related repository-selection overrides.

Revalidate the frozen root, Git directory, and common directory after resume or
context loss, after actual drift evidence, and immediately before the workspace
write. Supply the frozen view on standard input:

```text
python3 -B "<skill-dir>/../../scripts/worktree_binding.py" verify-view "<target-worktree-root>" -
```

When another command reports a project root, validate it with `verify-root`.
Missing or multiple candidates, resolution failure, a normalized Git top-level
different from the supplied root, a sibling worktree, or binding drift blocks
delivery. The binding does not attest to conversation state or prove that a
repository recreated at identical filesystem paths is the same repository.
Keep absolute paths out of the GOAL and context; use project-relative paths.

## Resume an interrupted invocation

A later explicit invocation may replay the same logical GOAL only for the same
absolute target and exact prior creator payload, supplied directly or recovered
read-only from a named task, session, or blocker handoff. Accepted user
decisions define consensus. Prior validator and creator outputs are evidence to
recheck; assistant summaries, host status, and remembered drafts are leads only.

Revalidate the frozen binding and candidate, then inspect the target workspace.
Make at most one creator call per invocation: replay the exact payload when the
workspace is absent or complete and identical; block on partial, unsafe, or
conflicting state. Never retry within the same invocation, run concurrent
attempts, change replay bytes, or switch worktrees.

If exact payload recovery fails, the replay path stops. Fresh authoring may
restart from accessible accepted decisions and current verified facts, with the
full validation path rerun; treat it as a new candidate and block if result,
scope, or authority is unclear.

## Establish source facts

Treat the current request and later accepted decisions as authority for result,
scope, and allowed effects. Verify repository facts only as needed to make the
outcome, paths, commands, constraints, and completion checks accurate, and read
all such facts from `<target-worktree-root>`. Repository evidence constrains an
implementation but cannot expand the request.

Do not treat assistant suggestions, rejected options, silence, examples, stale
summaries, or superseded decisions as consensus. Use an assumption only when it
cannot materially change outcome, scope, authority, cost, or risk, and label it
with `假设：` in `约束与授权`. Otherwise ask the smallest question and do not emit
or persist a GOAL.

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
criterion only when the user accepted it or a governing hard requirement
independently requires it. Ask when that would materially change result, scope,
or completion. User requirements, hard invariants, real data, existing users,
compatibility commitments, and reachable risks take precedence.

## Write the seven-line contract

Use [`goal-template.txt`](goal-template.txt) exactly. The output has seven
logical lines in template order, with exact labels and full-width colons. Fill
every placeholder. `结果`, `范围`, `完成标准`, and `最终交付` require substantive
content; the other fields may be `无` when nothing applies.

Write independently verifiable outcomes as `(C1) ...；(C2) ...`, with unique
consecutive IDs starting at `C1`. Keep IDs stable for the same objective. Do not
put verification case IDs, adapter paths, or digests in the GOAL.

Describe destination and proof, not unnecessary implementation steps. Keep the
contract self-contained and at most 4,000 Unicode code points. Do not add a
title, preface, Markdown list, code fence, wrapper, or eighth line.

Read and apply [`goal-context.md`](goal-context.md). Build exactly one context
file in memory, derive its safe project-relative path, and place that sole
reference in `证据与上下文`. The GOAL remains authoritative and self-contained;
the context carries only verified sources and useful background.

## Create the workspace

Validate the candidate before any write:

```text
python3 -B "<skill-dir>/../../scripts/goal_contract.py" view -
```

Correct an error only while it identifies a new, locally repairable defect. If
the same failure repeats, a validator is unavailable, I/O fails, or no
evidence-backed correction remains, stop instead of looping or persisting an
unvalidated contract.

Serialize one strict UTF-8 JSON object in memory; do not put the GOAL or context
in argv or a temporary file:

```json
{
  "objective": "<the complete seven-line GOAL>",
  "context": {
    "path": ".steward/goal-context/<safe-slug>.md",
    "content": "<verified context Markdown>"
  }
}
```

Before the sole creator call, validate the exact serialized creator payload
through the creator's own request parser:

```text
python3 -B "<skill-dir>/../../scripts/goal_workspace.py" validate-create -
```

This preflight is mandatory even after `goal_contract.py view`: the contract
validator cannot compare the separate context object with the context reference
or derive its path from `结果`. Never guess, abbreviate, or manually reproduce
the safe slug. If preflight reports an expected path, use that exact
project-relative path in both `证据与上下文` and `context.path`, rebuild the
payload, and preflight again. Freeze the bytes of the successful payload in
memory; do not edit or reserialize them between successful preflight and create.

After the frozen binding is revalidated, send those exact validated bytes to the
workspace creator:

```text
python3 -B "<skill-dir>/../../scripts/goal_workspace.py" create "<target-worktree-root>" -
```

Every `-` input above must be a finite non-TTY pipe whose writer closes after the
payload. Merely setting a command tool to non-TTY does not work when it closes
stdin immediately and has no input field.

When a host can inject delayed input only through a PTY, use the bundled
in-memory bridge for both `validate-create -` and `create <target> -`. Serialize
the creator request as compact single-line JSON and start the applicable command
in a PTY; the create form is:

```text
python3 -B "<skill-dir>/../../scripts/pty_stdin_bridge.py" --line -- python3 -B "<skill-dir>/../../scripts/goal_workspace.py" create "<target-worktree-root>" -
```

After `READY STEWARD_PTY_STDIN`, send the compact JSON plus one LF, without
Ctrl-D. For input containing literal LF, replace `--line` with its exact UTF-8
byte count and send exactly those bytes without a delimiter. The bridge relays
input in memory, restores the terminal, and puts no content in argv or a file.
Never connect a `-` input directly to a PTY; canonical buffering can truncate it.

The creator accepts exactly those fields. It validates the GOAL and its sole
context reference, establishes `.steward/.gitignore` with the exact bytes `*\n`,
creates the context, and writes canonical `.steward/goal.txt` last. An identical
complete workspace returns the same view without rewriting. Any different,
tracked, symbolic, malformed, or partial workspace fails closed and remains in
place. Existing unrelated untracked controls are retained. Do not clean,
convert, relocate, or retry in another worktree; a new GOAL requires a new
worktree.
