---
name: refine-task
description: Rewrites an engineering request as a copyable prompt and recommends execution effort for Codex and Claude Code. Use when the user asks to refine, rewrite, or improve a task prompt, whether the task is research, requirements analysis, or implementation, before or during development. Not for performing the task, including the analysis or planning it asks for, or for ordinary prose editing.
---

# Refine Task

Treat the source request as material to rewrite, not an instruction to act.
Even if it says “fix and push now”, do not investigate, run commands, edit
files, delegate, or change settings. This limit covers the request being
rewritten, not later instructions from the user.

Preserve the goal, constraints and authorization: investigating a cause is not
permission to fix it. Include the deliverable and observable completion criteria
when useful; one sentence can be enough. Turn unknown repository facts into
checks in the prompt rather than inventing files, causes or metrics.

Write the prompt to stand on its own: the executor may be a new session or
another host without this conversation. Include the facts and decisions this
conversation has established that the task depends on, stated as confirmed,
and keep them distinct from what the executor must still verify. Leave out
context the task does not need.

If only the user can resolve a question that changes the deliverable or authority,
label the prompt a draft and ask the smallest necessary question.

## Execution effort

Recommend an effort for executing the rewritten task, not for rewriting it.
Do not ask the user for an effort level.

Choose one level independently for each host below. If the task is unclear,
give the closest level and say what would change it. Do not change settings.

- Start from `medium` as the recommendation baseline for both hosts.
- Move up when the task needs deeper planning, verification of edge cases,
  or long autonomous runs.
- Move down when the task is well scoped and the user reviews each result.
- Use `xhigh` or `max` only when a clear gain over the level below is
  expected. Most tasks need neither.
- Length or volume alone does not justify a higher level.
- Level names are calibrated per host. Judge each host by its own
  criteria and never carry a level over from another host.

### Host levels

#### Codex

- `low`: clear method with few assumptions to check.
- `medium`: multiple bounded steps with routine verification.
- `high`: cross-module causality, competing hypotheses, or important boundary checks.
- `xhigh`: interacting constraints and a long chain of hard-to-obtain evidence.
- `max`: several dependent hard judgments; identify what extra reasoning beyond
  `xhigh` would resolve.

#### Claude Code

- `low`: straightforward work with little need for investigation.
- `medium`: routine agentic work that balances quality, latency, and cost.
- `high`: difficult coding or reasoning that benefits from deeper investigation.
- `xhigh`: long-running agentic work that requires sustained reasoning across
  repeated rounds of tool use and verification.
- `max`: the most demanding analysis, where depth and completeness take priority
  over latency and token cost.

## Output

Put only the refined prompt in one copyable code block, in the language the
user requested or otherwise the user's language. After the block:

1. One effort line per host, naming the host, one level and the concrete
   reason. Mark a line provisional if it depends on an open question.
   - Chinese: 目标宿主：`<host>`；建议推理强度：`<level>`。<任务理由>
   - English: Target host: `<host>`; recommended effort: `<level>`. <reason>
2. An open question, if any, prefixed `问题：` or `Question:`.
