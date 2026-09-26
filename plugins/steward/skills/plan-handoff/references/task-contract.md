# Task contract

Use this shape in the delivered `task-plan.md`, adapting headings to the
project. It is a human-readable contract, not a schema or execution engine.
Record only decisions and evidence relevant to the work; replace placeholders
before marking a task ready. Append [executor-protocol.md](executor-protocol.md)
unchanged; the executor needs it even when it has not loaded this skill.
[task-plan-example.md](task-plan-example.md) shows a filled-in plan; read it
only when the shape below leaves a question open.

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
| Executor tier | `basic`, `strong`, or `planner`, chosen by risk and judgment density; the host maps tiers to models. Use `basic` only for short tasks with mechanical acceptance; `planner` work is not handed off. |
| Dependencies and entry | Specific output IDs/versions and usable artifacts; environment and decisions required before start. State whether the executor may check these and mark a settled task `ready`. `none` if truly independent. |
| Entry check | Commands that must pass before editing, such as `git diff --quiet <baseline> -- <allowed paths>`. A failure means handback, not a judgment call. |
| Code facts | Observed behavior, callers, tests, configuration, relevant history, and reopenable paths/lines or commits. Label assumptions and unrun checks. |
| Scope and preservation | Allowed paths or symbols, required behavior to keep, excluded changes, and authorization boundary. |
| Fixed implementation | Chosen interfaces, errors, data model, module ownership, order/migration, and invariants. State enough that another executor need not pick an architecture. |
| Local discretion | Exact choices left to the executor, such as names, organization within an allowed module, existing pattern reuse, or fixture values. |
| Acceptance | Observable successful and failure behavior, boundary cases, compatibility, and evidence required. Do not equate a checklist title with proof. |
| Validation | Commands, cwd, environment/preconditions, pass criteria, evidence location, and what remains unrun. Include a final integration check where needed. |
| Attempt budget | Fix-and-validate cycles allowed for in-contract failures, then the escalation target: a stronger tier first, the planner for design or requirement issues. |
| Exception and handback | Relevant drift, missing prerequisites, failed checks, and decisions that must return to the planner. |
| Result | Executor-owned record: result ID/version, plan/task revisions, actual dependency result versions, code state as commit and diff summary, actions, each command with its exit code and raw output or saved output path, evidence, remaining differences, status, and next action after interruption. |
