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
  final integration check. State exclusions and open questions separately.
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
| Result | Executor-owned record: plan/task revisions, actual dependency result versions, code state or diff identity, actions, commands and results, evidence, remaining differences, status, and next action after interruption. |

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
   step 1. Mark `done` only with the stated evidence. Complete the final
   integration task before claiming the overall request is complete.

## Worked example: Steward skill replacement

Illustration of a contract at the historical `fcbb072` baseline, not an active
task or a statement that this request has already passed validation. The source
paths and entry points below were inspected at that baseline. A real planner
would record the current revision and update any changed line locators.

**Plan:** `STEW-HANDOFF`, revision 1, overall status `draft`; `STEW-01` is the
ready next task. Source: accepted
request to replace the GOAL drafting skill with a code-level handoff skill.
Authority: local plugin source and documentation edits, including deletion of
the old skill; no commit, publication, external write, or deletion of user
`.steward` state. Baseline: `fcbb072`; no tests run when this example was
written. Git delivery: tracked `plugins/steward/` and root README diff; if a
plan is instead saved under ignored `/docs/`, transfer its file separately.
Overall coverage: `STEW-01` provides the new skill and contract format;
`STEW-02` removes the old entry and updates active descriptions; `INT-01`
checks their integration and the preserved verifier. Final integration owner:
the planner. Execute serially, with one writer.

**Task `STEW-01`, revision 1, `ready`: Add the new handoff skill.**

- **Source and dependencies:** accepted replacement decision above; no prior
  task output. Entry requires the unchanged `fcbb072` skill layout or a drift
  review before editing.
- **Observed facts:** `plugins/steward/skills/draft-consensus-goal/SKILL.md`
  creates an immutable GOAL bundle; its `agents/openai.yaml` disables implicit
  invocation. `plugins/steward/skills/plan-delivery/SKILL.md` owns plans and
  Backlogs. Both plugin manifests discover `./skills/`; no per-skill registry
  edit is needed. `plugins/steward/skills/run-closed-loop-verification/scripts/verifier.py`
  calls `goal_workspace.view_goal_bundle()` and still needs that shared runtime.
  These are file observations, not test results.
- **Scope and preservation:** add only
  `plugins/steward/skills/plan-execution/{SKILL.md,agents/openai.yaml,references/task-contract.md}`
  in this card. Preserve the existing verifier and GOAL runtime. Deletion of
  the old skill and documentation changes belong to later cards.
- **Fixed implementation:** normal implicit discovery; planning and handoff
  only; no GOAL bundle or executor engine. The entrypoint must route to a
  single-file task contract with plan/task revisions, evidence, fixed decisions,
  bounded executor latitude, observable acceptance, the recovery protocol,
  and a final integration owner. Keep execution results separate from
  planner-owned decisions. The new format is not `acceptance-plan v1`.
- **Local discretion:** concise wording and headings, and the illustrative
  fixture values within these files. No alternate architecture or state store.
- **Acceptance:** a replacement executor can use the delivered artifact and
  repository alone to identify permitted edits, exact validation, drift
  handback, and completion evidence; a missing prerequisite or contradicted
  fact blocks only affected work. The skill validator accepts the new entry;
  the old verifier remains operable on its own GOAL contract.
- **Validation:** from repository root, with skill-creator installed at the
  standard Codex location, run
  `python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" plugins/steward/skills/plan-execution`;
  pass is exit 0. Inspect links and perform an independent executor scenario
  review, saving observations with the handoff. Runtime suites are assigned to
  final integration, so they are not claimed by this card before being run.
- **Handback:** if the skill loader requires an undocumented registration or
  existing callers require GOAL compatibility, report the exact caller and
  decision needed. Do not add an alias or GOAL adapter on this task.
- **Result:** pending. Executor records plan revision, task revision, dependency
  output versions (`none` here), worktree diff identity, actual commands and
  evidence, status, and next action if interrupted.

**Task `STEW-02`, revision 1, `draft`: Replace the old entry and documentation.**

- **Source and dependencies:** same accepted replacement decision; consume the
  actual `STEW-01` revision 1 skill files and validation result. If unavailable,
  this task cannot start. The design below is settled, but the task cannot move
  to `ready` until this result exists and is checked.
- **Observed facts:** at `fcbb072`, the root README, Steward README, Codex and
  Claude manifests, and Claude marketplace description advertise GOAL drafting.
  The Codex default prompt calls the old skill. Both manifests discover the
  whole `./skills/` directory. `audits/2026-09-12-steward-skills.md` links the
  old file as historical evidence. The repo `.gitignore` ignores `/docs/`.
  These are inspected files, not passing validation results.
- **Scope and preservation:** remove only the two files under
  `plugins/steward/skills/draft-consensus-goal/`; edit `README.md`,
  `plugins/steward/README.md`, the two plugin manifests,
  `.claude-plugin/marketplace.json`, and the one historical audit link. A
  one-sentence routing change in `plan-delivery/SKILL.md` is allowed. Preserve
  all shared GOAL scripts, references, and verifier tests; do not touch user
  `.steward` state or the per-plugin Codex marketplace entry.
- **Fixed implementation:** set both plugin versions to `0.10.0`; replace every
  active old-skill invocation with `plan-execution`. Explain that the old call
  fails, new `task-plan.md` is a different format, old state is not migrated,
  and the independent verifier still accepts only GOAL bundles. Pin the audit
  link to the historical `180c0eb` file rather than changing its conclusion.
  Do not introduce an alias, adapter, or changed `acceptance-plan v1`.
- **Local discretion:** concise wording, section placement, and link labels;
  the compatibility and routing claims above are fixed.
- **Acceptance:** a reader can select the new handoff skill for code-level
  planning and cannot find a live old-skill entry. JSON manifests parse, local
  links resolve, and the audit still points to the reviewed historical file.
- **Validation:** from repository root run `python3 -m json.tool` separately on
  `plugins/steward/.codex-plugin/plugin.json`,
  `plugins/steward/.claude-plugin/plugin.json`, and
  `.claude-plugin/marketplace.json`, redirecting formatted output to `/dev/null`;
  each must exit 0. Run
  `python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator/scripts/validate_plugin.py" plugins/steward`;
  require exit 0. Resolve each relative Markdown link in changed active docs
  against its containing directory, and inspect
  `rg -n 'draft-consensus-goal' README.md plugins/steward .claude-plugin/marketplace.json`
  so only upgrade and historical example mentions remain. Save outputs with
  the result. The verifier suites belong to `INT-01`.
- **Handback:** a newly discovered live caller or incompatible plugin loader
  requires a planner decision; do not create a compatibility entry.
- **Result:** pending. Bind to plan revision 1, task revision 1, actual
  `STEW-01` result version and code state; record commands, diff, evidence,
  status, and interruption handoff.

**Task `INT-01`, revision 1, `draft`: Integrated acceptance.**

- **Source and dependencies:** the full replacement request; consume the
  actual revision 1 results and code states of `STEW-01` and `STEW-02`. Mark
  `ready` only after both outputs actually exist and remain applicable.
- **Observed facts and scope:** at `fcbb072`, the verifier calls
  `goal_workspace.view_goal_bundle()`; its shared runtime and the two existing
  unittest suites must remain. Inspect the final diff and run checks, without
  changing planner-owned decisions or user state.
- **Fixed acceptance and discretion:** verify overall requirement coverage,
  no active old skill or alias, the new handoff/recovery protocol, correct
  versions and links, and unchanged independent GOAL consumption. The owner
  may choose evidence formatting only. Component completion is insufficient.
- **Validation:** from repository root, using Python 3.10 or newer, run
  `python3 -B -m unittest discover -s plugins/steward/tests -p 'test_*.py'`
  and `python3 -B -m unittest discover -s plugins/steward/skills/run-closed-loop-verification/tests -p 'test_*.py'`;
  both must exit 0. Also require `git diff --check` exit 0 and inspect the
  complete diff. Record the interpreter version and actual command results.
- **Handback and result:** a failing existing test needs diagnosis, not a
  relaxed gate. Return design or requirement gaps to the planner; fix only
  in-contract implementation defects. Result pending, bound to plan/task
  revisions, both actual dependency result versions, final code state, and
  evidence. Mark overall done only after this task is done.
