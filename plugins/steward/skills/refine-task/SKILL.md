---
name: refine-task
description: Rewrites an engineering request as a refined, copyable prompt without doing the task, and recommends an effort level for GPT-6.1 Sol and Claude Opus 5.5. Use when the user asks to rewrite, refine or turn a request into a prompt. Not for performing the task, analyzing requirements, writing a repository-grounded task contract, or polishing ordinary prose.
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
If only the user can resolve a question that changes the deliverable or authority,
label the prompt a draft and ask the smallest necessary question.

## Execution effort

Recommend an effort for executing the rewritten task, not for rewriting it.
Do not ask the user for an effort level.

Models:

- Always recommend one level for each of GPT-6.1 Sol and Claude Opus 5.5.
- If the task is unclear, still give the closest level and state what would
  change it.

Choosing a level:

- Start from the model's default, which is `medium` for both models.
- Move up when the task needs deeper planning, verification of edge cases,
  or long autonomous runs.
- Move down when the task is well scoped and the user reviews each result.
- Use `xhigh` or `max` only when a clear gain over the level below is
  expected. Most tasks need neither.
- Length or volume alone does not justify a higher level.
- Level names are calibrated per model. Judge each model by its own
  criteria and never carry a level over from another model.

### Model levels

GPT-6.1 Sol: `low`, `medium` (default), `high`, `xhigh`, `max`.

- `low`: clear method with few assumptions to check.
- `medium`: multiple bounded steps with routine verification.
- `high`: cross-module causality, competing hypotheses, or important boundary checks.
- `xhigh`: interacting constraints and a long chain of hard-to-obtain evidence.
- `max`: several dependent hard judgments; identify what extra reasoning beyond
  `xhigh` would resolve.

Claude Opus 5.5: `low`, `medium` (default), `high`, `xhigh`, `max`.

- `low`: straightforward work with little need for investigation.
- `medium`: routine agentic work that balances quality, latency, and cost; the default.
- `high`: difficult coding or reasoning that benefits from deeper investigation.
- `xhigh`: long-running agentic work that requires sustained reasoning across
  repeated rounds of tool use and verification.
- `max`: the most demanding analysis, where depth and completeness take priority
  over latency and token cost.

## Output

Put only the refined prompt in one copyable code block, in the language the
user requested or otherwise the user's language. After the block:

1. One effort line per model, naming the model, one level and the concrete
   reason. Mark a line provisional if it depends on an open question.
   - Chinese: 目标模型：`<model>`；建议推理强度：`<level>`。<任务理由>
   - English: Target model: `<model>`; recommended effort: `<level>`. <reason>
2. An open question, if any, prefixed `问题：` or `Question:`.

## Example

Request: 把“查清重复扣款原因，先别修”改写成提示词。

Output:

````text
```text
调查支付流程中重复扣款的根本原因。只调查，不修改代码、配置或数据，也不提交。
交付：根因结论，以及支撑它的证据（文件路径与行号、日志或复现步骤）。
如果证据不足以确定根因，列出仍待确认的假设和各自的验证方法。
```
目标模型：`GPT-6.1 Sol`；建议推理强度：`high`。需要在多个模块之间核对相互竞争的假设。
目标模型：`Claude Opus 5.5`；建议推理强度：`high`。要在现有代码中查证边界情况，验证比速度更重要。
````
