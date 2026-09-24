# Task contract and executor protocol

Use this shape in the delivered `task-plan.md`, adapting headings to the
project. It is a human-readable contract, not a schema or execution engine.
Record only decisions and evidence relevant to the work; replace placeholders
before marking a task ready. Keep the execution protocol in the handoff even
when the executor has not loaded this skill.

## Plan header

- **Plan ID / revision / status:** stable identifier; increment the revision
  when decisions, task scope, dependencies, or acceptance change. Use only
  `draft`, `ready`, `active`, `blocked`, or `done` for plan and task status; a
  mixed plan may remain `draft` while its next task is `ready`. Name the ready
  tasks instead of inventing a composite status.
- **Requirements and decisions:** authoritative request or upstream plan and
  Backlog entries with versions; map each overall requirement to a task or the
  final integration check. When a requirement or decision was accepted only in
  conversation, record its accepted wording, acceptance criteria, and who
  accepted it and when, so later sessions need not rely on the transcript.
  State exclusions and open questions separately.
- **Authority and delivery:** authorized writes and prohibited external effects;
  plan location and how this file, code diff, and evidence reach the executor or
  another workspace. An ignored path needs an explicit transfer, not an
  assumption that Git carries it.
- **Baseline and shared decisions:** repository/worktree, revision or observed
  code state, evidence checked, cross-module design, compatibility and migration
  rules, and assumptions. Say which validations were not run.
- **Order and integration:** task IDs, dependencies, owner for execution, owner
  of final integrated acceptance, and what proves the whole request is done.
  Plan final integration now, but keep its task `draft` until required outputs
  actually exist; a condition on future outputs does not make it `ready`.
- **Acceptance record:** written only by the acceptance owner: decision,
  reviewed plan/task revisions, result versions and code state, evidence
  examined, and reopened or revised tasks. The plan becomes `done` only with an
  accepting record.

## Task card (repeat for each cohesive change)

| Field | Content |
| --- | --- |
| ID / revision / status | Stable ID, task revision, `draft`/`ready`/`active`/`blocked`/`done`. |
| Goal and source | Observable outcome and exact requirement or upstream entry/version. |
| Dependencies and entry | Specific output IDs/versions and usable artifacts; environment and decisions required before start. State whether the executor may check these and mark a settled task `ready`. `none` if truly independent. |
| Code facts | Observed behavior, callers, tests, configuration, relevant history, and reopenable paths/lines or commits. Label assumptions and unrun checks. |
| Scope and preservation | Allowed paths or symbols, required behavior to keep, excluded changes, and authorization boundary. |
| Fixed implementation | Chosen interfaces, errors, data model, module ownership, order/migration, and invariants. State enough that another executor need not pick an architecture. |
| Local discretion | Exact choices left to the executor, such as names, organization within an allowed module, existing pattern reuse, or fixture values. |
| Acceptance | Observable successful and failure behavior, boundary cases, compatibility, and evidence required. Do not equate a checklist title with proof. |
| Validation | Commands, cwd, environment/preconditions, pass criteria, evidence location, and what remains unrun. Include a final integration check where needed. |
| Exception and handback | Relevant drift, missing prerequisites, failed checks, and decisions that must return to the planner. |
| Result | Executor-owned record: result ID/version, plan/task revisions, actual dependency result versions, code state or diff identity, actions, commands and results, evidence, remaining differences, status, and next action after interruption. |

## Protocol to copy into the handoff

1. Before editing, read the current plan and task revisions, actual dependency
   outputs, worktree status, and relevant code. Preserve existing changes. If
   their source cannot be distinguished, hand back; never overwrite or reset
   them. Compare against the recorded baseline plus accepted dependency outputs
   and this task's recorded, attributable checkpoint diff. Those expected edits
   do not themselves require replanning. Unrelated changes do not either. If
   relevant drift goes beyond that expected state or its effect is unclear,
   stop the affected task and send evidence to the planner. A permitted
   adjustment must be named in the task card; “keep it equivalent” is not
   permission to redesign.
2. Start new work only from `ready`, with dependencies and authorization checked.
   If the card delegates readiness checks, the executor may mark a settled
   `draft` task `ready` after recording evidence that every listed prerequisite
   holds; unresolved design choices still go to the planner. After step 1,
   resume an interrupted `active` task without resetting its status. For a
   `blocked` task, record evidence that the blocker was resolved within the
   contract and existing authority, then return to `ready` if unstarted or
   `active` if resuming. Design, acceptance, or unclear-drift blockers remain
   with the planner. Status changes do not authorize contract changes.
   Choose only the listed local details. Do not change requirements,
   architecture, acceptance, or the planner-owned contract. Record work in the
   result area and move status to `active` or `blocked`/`done` as observed.
3. Run the specified validation. Classify a failure: implementation defect,
   environment prerequisite, command binding, plan/design error, requirement
   gap, or pre-existing test failure. Fix and rerun in-contract defects;
   restore environment within existing authority; adjust commands only inside
   an explicitly allowed binding range. Do not ignore failures or lower pass
   criteria. If further diagnosis adds no evidence, or a new design decision is
   needed, hand back. Set a specific diagnosis budget only for an actual cost or
   risk, not a universal retry count.
4. Handback states the disproven assumption, observation and source, affected
   task and acceptance, attempts and results, and decision needed. The executor
   cannot edit the contract to accept its own work. The planner revises affected
   contracts and dependencies, preserves past result records, and marks which
   evidence no longer applies.
5. After interruption, record the last validation actually run and its result,
   unfinished diff, current code state, and next action. On resumption repeat
   step 1. Mark `done` only with the stated evidence. After the final
   integration task is `done`, hand its evidence to the acceptance owner; only
   an accepting record completes the overall request.

## Worked example: Add a read-only metadata review skill

This illustrates a contract for an *assumed, accepted* request to add an
explicitly invoked skill that reviews Steward's plugin metadata, then document
how to invoke it. This is not an active request or a claim of completed
validation. The repository facts below were inspected at `478e595`; a planner
using this example must capture the actual code state and recheck affected
facts before marking work ready.

**Plan:** `STEW-META`, revision 1, overall status `draft`; `META-01` is the ready
next task. Source: the example's accepted request for a read-only review of
Steward metadata across its two host manifests and repository marketplace,
with invocation by name only.
Authority: local skill and documentation edits only; no commit, installation,
publication, external write, or mutation of installed plugin copies. Baseline:
`478e595`, with affected paths inspected and no validation run for this example.
Deliver the tracked code diff and this `task-plan.md` together; if the plan is
saved under the repository's ignored `/docs/`, transfer it and its evidence
explicitly. `META-01` provides the review behavior, `META-02` makes it visible
in product documentation, and `INT-01` checks the integrated result. Execute
serially with one writer; the planner owns final integration acceptance, and
the acceptance record stays empty until `INT-01` is reviewed.

**Task `META-01`, revision 1, `ready`: Add the metadata review skill.**

- **Source and dependencies:** the accepted request above; no predecessor
  output. Entry requires the observed manifest and skill layout at `478e595`,
  or a drift review before editing.
- **Observed facts:** both `plugins/steward/.codex-plugin/plugin.json` and
  `plugins/steward/.claude-plugin/plugin.json` use `"skills": "./skills/"`.
  `.claude-plugin/marketplace.json` points its Steward entry to
  `./plugins/steward`. Existing skill folders contain `SKILL.md` and
  `agents/openai.yaml`; `analyze-change-request` shows an explicit-only policy.
  These are inspected file facts, not loader or validation results.
- **Scope and preservation:** add only
  `plugins/steward/skills/review-steward-metadata/SKILL.md` and its
  `agents/openai.yaml`. Preserve existing skill invocation policies and
  manifest values. Documentation belongs to `META-02`.
- **Fixed implementation:** the skill is explicit-only and read-only. It
  accepts a repository root (defaulting to the current directory) and compares
  the two host manifests' `name`, `version`, and `description`, checks that
  each `skills` path resolves to the shared directory, and checks that the
  repository marketplace entry names Steward, resolves to its plugin
  directory, and has the same `description` as the manifests. Report each
  mismatch with both source paths and the observed values; distinguish absent
  or unreadable inputs from a match. Do not make automatic repairs or create a
  helper script.
- **Local discretion:** concise wording, section headings, and the UI display
  text in `agents/openai.yaml`; no change to the compared fields or write policy.
- **Acceptance:** when invoked for this repository, the skill directs a
  reviewer to inspect all three sources and report their actual agreement or
  specific differences with file evidence. A missing file produces a stated
  evidence gap, never a clean result. Its frontmatter and UI metadata validate.
- **Validation:** from the repository root, with the bundled skill-creator
  available, run
  `python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" plugins/steward/skills/review-steward-metadata`;
  require exit 0. Invoke the skill against the actual repository and a
  temporary copy of its three metadata files with the marketplace
  `description` changed; record both reports without changing repository
  manifests. Record which checks were performed; no result is assumed here.
- **Handback:** if discovery requires a registration entry despite the
  inspected directory settings, report the loader evidence and affected
  acceptance to the planner. Do not widen the card to change manifests.
- **Result:** pending. Assign a result ID/version when work is recorded; bind
  it to plan revision 1, task revision 1, dependency result versions (`none`),
  code-state or diff identity, commands and findings, status, and the next
  action after interruption.

**Task `META-02`, revision 1, `draft`: Document the new review entry.**

- **Source and dependencies:** the same accepted request; consume the actual
  result ID/version produced under `META-01` task revision 1, skill files, and
  successful validation evidence. The executor may mark this settled card
  `ready` only after recording that `META-01` is `done`, those outputs exist,
  and they remain applicable to the current code state.
- **Observed facts:** `README.md` has a Steward workflow table and links to
  `plugins/steward/README.md`; that plugin README has a skill table and example
  invocations. The manifest directory setting already covers a new skill
  folder. The repository `.gitignore` ignores `/docs/`. These observations
  do not establish that the proposed skill works.
- **Scope and preservation:** edit `README.md` and
  `plugins/steward/README.md` only. Keep the existing workflows and links
  accurate; do not change plugin manifests or marketplace metadata in this
  card.
- **Fixed implementation:** add the explicit invocation
  `$steward:review-steward-metadata` and
  `/steward:review-steward-metadata` to the Steward
  README, describe its read-only checks and evidence-gap behavior, and give the
  root README a concise link to that entry. Do not imply that it repairs
  metadata or that a review has already passed.
- **Local discretion:** placement and Chinese wording of the new documentation.
- **Acceptance:** a reader can find the skill's purpose, invocation, and
  read-only boundary from the two READMEs; relative links resolve to tracked
  files, and the description agrees with the actual `META-01` output.
- **Validation:** from the repository root, inspect the changed Markdown links
  against their containing directories and compare the usage text with the
  delivered `SKILL.md` and `agents/openai.yaml`. Run `git diff --check` and
  require exit 0; save the inspected paths and command result. Do not claim a
  review result before this card is executed.
- **Handback:** if the delivered skill name or invocation policy differs from
  the fixed contract, provide the files and discrepancy to the planner; do not
  silently redefine the documentation target.
- **Result:** pending. Assign a result ID/version and bind it to plan revision
  1, task revision 1, the actual `META-01` result ID/version and code state;
  record the diff, checks, status, and next action after interruption.

**Task `INT-01`, revision 1, `draft`: Integrated acceptance.**

- **Source and dependencies:** the full example request; consume the actual
  result IDs/versions and code-state identities of `META-01` and `META-02`.
  The executor may mark this card `ready` only after both tasks are `done` and
  their evidence still applies.
- **Observed facts and scope:** the three metadata sources are the two plugin
  manifests and `.claude-plugin/marketplace.json`. Check their actual contents,
  the new skill, both README entries, and the complete diff. Integration may
  record results, but it may not change planner-owned decisions.
- **Fixed acceptance and discretion:** confirm that both manifests point to the
  shared skill folder, all three `description` values agree, the skill reports
  matched values or precise mismatches without writing files, and both
  documented invocations match its policy.
  Confirm the request's full coverage; component completion alone is not
  sufficient. Evidence formatting is the only local choice.
- **Validation:** from the repository root, run the same `quick_validate.py`
  command from `META-01` and
  `python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator/scripts/validate_plugin.py" plugins/steward`;
  both must exit 0. Run `git diff --check`, resolve changed relative links,
  and inspect the complete diff and the review-scenario evidence. Record actual
  command outputs and any checks not run.
- **Handback and result:** diagnose failed checks without lowering acceptance.
  Fix defects inside the accepted cards; return contradicted design assumptions
  or requirement gaps to the planner. Result pending; assign its ID/version
  and bind it to plan/task revisions, both actual dependency result versions,
  final code state, and evidence. After this card is `done`, the planner
  reviews its evidence and marks the overall plan `done` only with an accepting
  record.
