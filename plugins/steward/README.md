# Steward

Steward 为 Codex 与 Claude Code 提供七个技能，按需支持项目文档、仓库调研、交付规划与 GOAL 验收。两个宿主读取同一份 `skills/` 目录。

## 0.9.0 升级说明

精简七个技能的重复流程、模板和约束。文档生成／验证 helper CLI 已退役，文档维护改为沿用项目自身的语言、路径和检查器。已有文档与托管标记保持原样；直接调用旧 helper 的项目需调整调用方式。GOAL v1 格式、持久化和闭环验收运行时保持兼容。

## 安装与调用

Codex：

```bash
codex plugin marketplace add coachpo/plugins --ref main
codex plugin add steward@coachpo
```

Claude Code：

```bash
claude plugin marketplace add coachpo/plugins@main
claude plugin install steward@coachpo
```

安装或更新后，新建 Codex 任务或 Claude Code 会话加载技能。Codex 调用形式为 `$steward:<skill-name>`，Claude Code 为 `/steward:<skill-name>`。

## 技能用途与边界

| 技能 | 主要结果与边界 |
| --- | --- |
| [analyze-change-request](skills/analyze-change-request/SKILL.md) | 结合仓库与公开来源分析变更需求，提供引用及可观察验收标准。显式调用；只读，不实施或执行项目。 |
| [draft-consensus-goal](skills/draft-consensus-goal/SKILL.md) | 将已接受需求保存为供另一执行者使用的 GOAL、上下文及验收计划。显式调用；不实施或验收目标工作。 |
| [parallel-repository-research](skills/parallel-repository-research/SKILL.md) | 至少两条独立调查线定位代码、梳理架构或追踪依赖，主代理核实证据。只读，不运行测试或判定行为风险。 |
| [plan-delivery](skills/plan-delivery/SKILL.md) | 创建、修订或审查实施计划和／或 Sprint Backlog，明确交付、责任、依赖及验收。只规划，不执行开发。 |
| [run-closed-loop-verification](skills/run-closed-loop-verification/SKILL.md) | 对已有 GOAL 进行可恢复验收，诊断失败、修复授权范围内的源码问题并复测。显式调用；不用于普通单次测试。 |
| [write-agent-guides](skills/write-agent-guides/SKILL.md) | 维护有依据的 AGENTS.md 层级，共享规则在根文件，子树仅记录局部差异。不维护 CLAUDE.md。 |
| [write-project-docs](skills/write-project-docs/SKILL.md) | 按仓库事实和既有约定维护正式项目文档，明确权威来源并同步相关链接。显式文档请求；局部更新不扩展为文档套件。 |

Codex 可以隐式选择仓库调查、交付规划和代理指南技能，其余技能的 `agents/openai.yaml` 保持仅显式调用。审查请求只返回发现；创建、修改请求在指定范围内落盘。

## 文档与规划

文档维护沿用项目的语言、路径、信息结构和政策。README、项目状态、贡献指南、产品、架构与开发规范是可选文档角色，不是必建文件清单。旧文档中有用的内容、翻译和托管标记继续保留；有仓库生成器管理的区域遵循其契约。没有活动生成器的旧 `write-project-docs:*` 区域可直接维护。

文档技能不再附带固定开发等级目录、双语模板、通用源码规模政策及对应生成／验证脚本。已有项目若直接调用这些 helper CLI，需要改用项目自己的生成器或直接维护相关文档；已有 GOAL bundle 和验证状态不受影响。

规划可以只处理实施计划、只处理 Backlog，或联合维护两者。实施计划拥有范围、工作包与总体验收，Backlog 拥有任务拆分、具体依赖和迭代安排；未知容量以假设表达。采用用户及项目的格式，没有约定时默认放在 `docs/planning/`，不要求模板、状态库或自动创建 GOAL。

```text
使用 $steward:write-project-docs 更新 README 中受本次变更影响的用法与链接。
使用 $steward:write-agent-guides 维护 packages/api/AGENTS.md 的局部命令差异。
使用 $steward:plan-delivery 根据已有实施计划创建 Sprint Backlog，只编写 Backlog。
```

## 只读调研

变更分析区分用户要求、实际约束和待决定建议，按目标版本核实代码与公开来源，并随用户纠正更新受影响证据。公开查询不携带私有源码、秘密或个人数据。

仓库调查使用宿主可用的委派工具与模型默认值。子任务限定在仓库读取，主代理核实决定性证据；委派不可用时直接调查。并行能力不会扩大权限，提示词中的只读限制也不构成操作系统隔离。

```text
使用 $steward:analyze-change-request 分析批量导入需求，给出来源和验收条件，不修改文件。
使用 $steward:parallel-repository-research 调查两个独立服务的重试调用链，给出代码证据。
```

## GOAL 起草与验收

GOAL 起草在当前 cwd 所属 Git worktree 中创建 `.steward/goals/<alias>/`。alias 使用小写字母、数字及单连字符，至多 64 字符；未提供时自行选择。不可变 bundle 包含七行中文 `goal.txt`、`context.md`、`acceptance-plan.json` 与摘要 manifest。起草者的职责限制不写成执行者的任务限制。

执行者完成目标工作后，验收技能用同一 alias、同一物理 worktree 将验收意图绑定到项目真实命令，保存 execution plan、campaign 状态、源码快照和证据。运行前核实命令、副作用与现有授权。存储与执行契约分别见 [GOAL 格式](references/goal-authoring.md)和[执行绑定](skills/run-closed-loop-verification/references/execution-plan.md)。

```text
使用 $steward:draft-consensus-goal 将已接受需求保存为 GOAL，不开始实施。
使用 $steward:run-closed-loop-verification 验收当前 worktree 中的 goal-a，修复授权范围内的问题。
```

常用命令：

```bash
python3 -B "<plugin-dir>/scripts/goal_workspace.py" list
python3 -B "<plugin-dir>/scripts/goal_workspace.py" view --goal <alias>
python3 -B "<skill-dir>/scripts/campaign.py" status --goal <alias>
python3 -B "<skill-dir>/scripts/campaign.py" advance --goal <alias>
```

这里 `<skill-dir>` 为 `run-closed-loop-verification` 目录。创建 bundle 可以使用 `create-from` 读取暂存文件；结构化 stdin 输入使用普通重定向或有限 pipe，不需要 PTY 桥接器。

`advance` 自动推进 case、定向复测、修补后的全量回归和完成检查。`REPAIR_REQUIRED` 只说明运行失败，需要先区分源码、环境与命令绑定原因；只对确认属于 GOAL 授权范围的源码问题记录修补。无修补的成功 campaign 不额外重跑全套测试。

`COMPLETE` 是历史验收事实。报告当前源码通过前，还需比较当前源码指纹与完成记录；行为受影响或影响不明时必须重新证明。Draft 明确声明的非必需 case 豁免仍列为未满足的可选意图，不隐藏失败。

## 本地状态与恢复

`.steward/` 被自身 ignore 规则排除在 Git 状态之外，是恢复事实源，完成后继续保留。bundle 不支持移动或重新绑定；聊天摘要不能替代持久合同或机器证据。

临时环境阻塞解除后可继续 `advance`；同执行计划的 `init` 幂等加载现有 campaign。更换执行绑定或重新证明已完成目标时，先完整保留旧验证目录及证据，再在既有明确授权下替换活动 campaign；缺少删除授权时先完成准备再请求。细节见[恢复与证据](skills/run-closed-loop-verification/references/state-and-evidence.md)。

技能遵循当前任务授权。提交、推送、发布、部署、外部写入、购买、破坏性操作和范围扩展需要明确授权；已经成立的授权可以继续使用。

## 运行要求与维护检查

文档、指南、研究和规划技能不依赖附带脚本。GOAL bundle 与验收引擎需要 `python3`、Git，以及目标项目实际使用的本地 runner。依赖或环境缺失时，按任务授权补齐或报告具体阻塞项。

确定性运行时的回归检查使用临时仓库和本地 fixture：

```bash
python3 -B -m unittest discover -s plugins/steward/tests -p 'test_*.py'
python3 -B -m unittest discover -s plugins/steward/skills/run-closed-loop-verification/tests -p 'test_*.py'
```

以上命令从本插件仓库根执行，验证 bundle 完整性、worktree 绑定、修补与恢复、证据和完成条件；它们不证明所有自然语言技能任务均能成功。

## 许可证

Steward 按 [MIT](LICENSE) 许可证发布。
