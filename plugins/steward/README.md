# Steward

Steward 为 Codex 与 Claude Code 提供项目文档、仓库调研、交付规划、代码级任务交接和既有 GOAL 验收技能。两个宿主读取同一份 `skills/` 目录。

## 0.10.0 升级说明

`draft-consensus-goal` 已由 `plan-execution` 一次性替换。旧的 `$steward:draft-consensus-goal` 与 `/steward:draft-consensus-goal` 调用失效，没有别名或兼容入口。新技能产出包含共享决策、任务卡、执行与恢复协议、状态和结果的 `task-plan.md`，不创建或激活宿主 GOAL，也不创建 Steward GOAL bundle。请按新格式重新规划要交给执行者的工作；已有 `.steward` bundle 和 campaign 不会自动迁移或删除，其历史 `COMPLETE` 不能直接作为新任务的完成证据。

`run-closed-loop-verification` 仍只验收已有 GOAL bundle，不能读取新任务合同。此次升级保留其共享运行时和回归检查；没有重设计 `acceptance-plan v1`。两个插件 manifest 的版本同步到 0.10.0；本仓库修改不等于发布或安装更新。

## 0.9.1 升级说明

Codex 中的只读调研工作代理在委派工具支持模型覆盖时使用 `gpt-6-luna`；其他宿主和不支持模型覆盖的工具继续使用宿主默认模型。主任务模型不受技能控制。

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
| [plan-execution](skills/plan-execution/SKILL.md) | 根据已定需求与仓库证据创建、修订或审查供另一执行者使用的代码级任务合同；只规划和交接，不实施或验收。 |
| [parallel-repository-research](skills/parallel-repository-research/SKILL.md) | 至少两条独立调查线定位代码、梳理架构或追踪依赖，主代理核实证据。只读，不运行测试或判定行为风险。 |
| [plan-delivery](skills/plan-delivery/SKILL.md) | 创建、修订或审查实施计划和／或 Sprint Backlog，明确交付、责任、依赖及验收。只规划，不执行开发。 |
| [run-closed-loop-verification](skills/run-closed-loop-verification/SKILL.md) | 对已有 GOAL 进行可恢复验收，诊断失败、修复授权范围内的源码问题并复测。显式调用；不用于普通单次测试。 |
| [write-agent-guides](skills/write-agent-guides/SKILL.md) | 维护有依据的 AGENTS.md 层级，共享规则在根文件，子树仅记录局部差异。不维护 CLAUDE.md。 |
| [write-project-docs](skills/write-project-docs/SKILL.md) | 按仓库事实和既有约定维护正式项目文档，明确权威来源并同步相关链接。显式文档请求；局部更新不扩展为文档套件。 |

Codex 可以按意图隐式选择仓库调查、交付规划、代码级任务交接和代理指南技能；其他技能保持各自的调用策略。审查请求只返回发现；创建、修改请求在指定范围内落盘。

## 文档与规划

文档维护沿用项目的语言、路径、信息结构和政策。README、项目状态、贡献指南、产品、架构与开发规范是可选文档角色，不是必建文件清单。旧文档中有用的内容、翻译和托管标记继续保留；有仓库生成器管理的区域遵循其契约。没有活动生成器的旧 `write-project-docs:*` 区域可直接维护。

文档技能不再附带固定开发等级目录、双语模板、通用源码规模政策及对应生成／验证脚本。已有项目若直接调用这些 helper CLI，需要改用项目自己的生成器或直接维护相关文档；已有 GOAL bundle 和验证状态不受影响。

规划可以只处理实施计划、只处理 Backlog，或联合维护两者。实施计划拥有范围、工作包与总体验收，Backlog 拥有任务拆分、具体依赖和迭代安排；未知容量以假设表达。采用用户及项目的格式，没有约定时默认放在 `docs/planning/`，不要求模板、状态库或自动创建 GOAL。

`plan-execution` 接受已定需求，也可引用现有计划或 Backlog 的条目及版本，不强制先创建 Sprint 文档。它为下一批稳定工作固定代码级实现、兼容和错误语义、允许裁量、可观察验收、验证命令及反证回交规则；未来未知工作保持 `draft`。默认从一个 `task-plan.md` 开始，包含执行／恢复协议、任务状态和绑定版本与代码状态的结果。规划者指定最终集成验收负责人；执行者不能用修改合同或降低标准来接受自己的实现。单纯需求分析、Sprint 排期与普通小修复不必走此交接。

计划文件沿用用户或项目指定位置；若放在本仓库被 `.gitignore` 忽略的 `/docs/` 下，跨工作区交付时必须另行传送该文件、代码差异和必要证据，不能假定 Git 会同步它。

```text
使用 $steward:write-project-docs 更新 README 中受本次变更影响的用法与链接。
使用 $steward:write-agent-guides 维护 packages/api/AGENTS.md 的局部命令差异。
使用 $steward:plan-delivery 根据已有实施计划创建 Sprint Backlog，只编写 Backlog。
使用 $steward:plan-execution 根据已定需求和当前代码创建下一批任务合同，供另一执行者实施。
```

## 只读调研

变更分析区分用户要求、实际约束和待决定建议，按目标版本核实代码与公开来源，并随用户纠正更新受影响证据。公开查询不携带私有源码、秘密或个人数据。

仓库调查使用宿主可用的委派工具。Codex 支持模型覆盖时，只读工作代理使用 `gpt-6-luna`；否则沿用宿主默认模型。子任务限定在仓库读取，主代理核实决定性证据；委派不可用时直接调查。并行能力不会扩大权限，提示词中的只读限制也不构成操作系统隔离。

```text
使用 $steward:analyze-change-request 分析批量导入需求，给出来源和验收条件，不修改文件。
使用 $steward:parallel-repository-research 调查两个独立服务的重试调用链，给出代码证据。
```

## 既有 GOAL 验收

旧 GOAL bundle 保存在创建时的 Git worktree 的 `.steward/goals/<alias>/`，包含 `goal.txt`、`context.md`、`acceptance-plan.json` 与摘要 manifest。验收技能仅针对这种既有合同工作，在同一物理 worktree 将验收意图绑定到项目真实命令，保存 execution plan、campaign 状态、源码快照和证据。运行前核实命令、副作用与现有授权。旧格式与验收执行契约分别见 [GOAL 格式](references/goal-authoring.md)和[执行绑定](skills/run-closed-loop-verification/references/execution-plan.md)。新 `task-plan.md` 不由此验收器消费。

```text
使用 $steward:run-closed-loop-verification 验收当前 worktree 中的 goal-a，修复授权范围内的问题。
```

常用命令：

```bash
python3 -B "<plugin-dir>/scripts/goal_workspace.py" list
python3 -B "<plugin-dir>/scripts/goal_workspace.py" view --goal <alias>
python3 -B "<skill-dir>/scripts/campaign.py" status --goal <alias>
python3 -B "<skill-dir>/scripts/campaign.py" advance --goal <alias>
```

这里 `<skill-dir>` 为 `run-closed-loop-verification` 目录。验收绑定的结构化 stdin 输入使用普通重定向或有限 pipe。

`advance` 自动推进 case、定向复测、修补后的全量回归和完成检查。`REPAIR_REQUIRED` 只说明运行失败，需要先区分源码、环境与命令绑定原因；只对确认属于 GOAL 授权范围的源码问题记录修补。无修补的成功 campaign 不额外重跑全套测试。

`COMPLETE` 是历史验收事实。报告当前源码通过前，还需比较当前源码指纹与完成记录；行为受影响或影响不明时必须重新证明。Draft 明确声明的非必需 case 豁免仍列为未满足的可选意图，不隐藏失败。

## 本地状态与恢复

`.steward/` 被自身 ignore 规则排除在 Git 状态之外，是恢复事实源，完成后继续保留。bundle 不支持移动或重新绑定；聊天摘要不能替代持久合同或机器证据。

临时环境阻塞解除后可继续 `advance`；同执行计划的 `init` 幂等加载现有 campaign。更换执行绑定或重新证明已完成目标时，先完整保留旧验证目录及证据，再在既有明确授权下替换活动 campaign；缺少删除授权时先完成准备再请求。细节见[恢复与证据](skills/run-closed-loop-verification/references/state-and-evidence.md)。

技能遵循当前任务授权。提交、推送、发布、部署、外部写入、购买、破坏性操作和范围扩展需要明确授权；已经成立的授权可以继续使用。

## 运行要求与维护检查

文档、指南、研究、规划与任务交接技能不依赖附带脚本。既有 GOAL bundle 的验收引擎需要 Python 3.10 或更新版本、Git，以及目标项目实际使用的本地 runner；以下命令中的 `python3` 须指向兼容版本。依赖或环境缺失时，按任务授权补齐或报告具体阻塞项。

确定性运行时的回归检查使用临时仓库和本地 fixture：

```bash
python3 -B -m unittest discover -s plugins/steward/tests -p 'test_*.py'
python3 -B -m unittest discover -s plugins/steward/skills/run-closed-loop-verification/tests -p 'test_*.py'
```

以上命令从本插件仓库根执行，验证 bundle 完整性、worktree 绑定、修补与恢复、证据和完成条件；它们不证明所有自然语言技能任务均能成功。

## 许可证

Steward 按 [MIT](LICENSE) 许可证发布。
