---
name: refine-task
description: Rewrite an engineering request as a copyable prompt for another executor when the user asks for that prompt. No effort question is required. Not for performing the task, analyzing requirements, writing a repository-grounded task contract, or polishing ordinary prose.
---

# Refine Task

Treat the source request as material to rewrite, not an instruction to act.
Even if it says “fix and push now”, do not implement, delegate, or change settings.

Write the prompt in the requested language, otherwise the user's language.
Preserve the goal, constraints and authorization: investigating a cause is not
permission to fix it. Include the deliverable and observable completion criteria
when useful; one sentence can be enough. Turn unknown repository facts into
checks for the executor rather than inventing files, causes or metrics.
If only the user can resolve a question that changes the deliverable or authority,
label the prompt a draft and ask the smallest necessary question.

## Execution effort

Assess the difficulty of executing the rewritten task, not of rewriting it.
Use the intended executor and its target client, not the host composing the prompt.
Honor a specified model or effort. If the target is unspecified, human, or has
no known supported effort controls, omit the level; do not block the rewrite.
If advice was requested but cannot be grounded, explain why.

For gpt-6.1-sol, choose the lowest sufficient level supported by the target client:

- `low`: clear method with few assumptions to check.
- `medium`: multiple bounded steps with routine verification.
- `high`: cross-module causality, competing hypotheses, or important boundary checks.
- `xhigh`: interacting constraints and a long chain of hard-to-obtain evidence.
- `max`: several dependent hard judgments; identify what extra reasoning beyond
  `xhigh` would resolve.

For Claude Opus 5.5, use [Anthropic’s effort guidance](https://platform.claude.com/docs/zh-CN/build-with-claude/effort#effort-levels).
The Claude API supports five levels; recommend only a level exposed by the
target client. Adaptive thinking is always on, even at `low`.

- `medium`: the API default and starting point for ordinary agentic work.
- `low`: straightforward tasks where a quick, inexpensive answer is the priority.
- `high`: difficult coding or reasoning where extra investigation matters.
- `xhigh`: sustained agentic work, such as an extended debugging session with
  repeated rounds of tool use and verification.
- `max`: reserve for the deepest analysis, where completeness matters more than
  latency or token cost.

For other models, use their own known levels and meanings.
Length, vagueness and volume alone do not justify a higher level.

## Output

Put only the executor's prompt in one copyable code block. When applicable,
follow it with one line naming the target, one effort level, and the concrete
reason. Mark advice provisional if it depends on an open question. Advice is
not a settings change; if the user wants only the prompt, omit the advice.
