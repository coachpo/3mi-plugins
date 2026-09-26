# Steward

Steward 为 Codex 与 Claude Code 提供项目文档、仓库调研、交付规划和代码级任务交接技能。两个宿主读取同一份 `skills/` 目录。

## 0.13.0 升级说明

`plan-handoff` 的任务卡新增执行档位、入口检查和尝试预算，把漂移、越界和升级判断改成命令、路径和次数，便于交给低价模型执行；结果区要求记录每条命令的退出码和原始输出。执行协议改为技能附带的 `executor-protocol.md`，由规划者原样复制进 `task-plan.md`；完整范例移到 `task-plan-example.md`，按需读取。Claude Code 版新增两个插件 agent：`steward-researcher`（`haiku`，只读工具）承担调研 worker，`steward-executor`（`sonnet`）执行 ready 任务；你要求执行时，`plan-handoff` 会把 ready 任务逐个派发给它。已有 `task-plan.md` 可继续按其中附带的协议执行。两个插件 manifest 的版本同步到 0.13.0。

## 0.12.0 升级说明

`plan-execution` 更名为 `plan-handoff`，旧的 `$steward:plan-execution` 与 `/steward:plan-execution` 调用失效，没有别名或兼容入口。该技能新增验收职责：验收负责人依据结果记录和实际 diff 决定结项、退回任务或修订合同。任务合同头部新增两项要求：只在对话中确认的需求要写进合同，验收结论写入验收记录；`plan-delivery` 的实施计划与 Backlog 增加修订号。已有 `task-plan.md` 可继续使用，验收时补写验收记录。两个插件 manifest 的版本同步到 0.12.0。

## 0.9.1 升级说明

Codex 中的只读调研工作代理在委派工具支持模型覆盖时使用 `gpt-6-luna`；其他宿主和不支持模型覆盖的工具继续使用宿主默认模型。主任务模型不受技能控制。

## 0.9.0 升级说明

文档生成／验证 helper CLI 已退役，文档维护沿用项目自身的语言、路径和检查器。已有文档与托管标记保持原样；直接调用旧 helper 的项目需调整调用方式。

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
| [parallel-repository-research](skills/parallel-repository-research/SKILL.md) | 至少两条独立调查线定位代码、梳理架构或追踪依赖，主代理核实证据。只读，不运行测试或判定行为风险。 |
| [plan-delivery](skills/plan-delivery/SKILL.md) | 创建、修订或审查实施计划和／或 Sprint Backlog，明确交付、责任、依赖及验收。只规划，不执行开发。 |
| [plan-handoff](skills/plan-handoff/SKILL.md) | 根据已定需求与仓库证据创建、修订或审查供另一执行者（可以是低价模型）使用的代码级任务合同，并依据回交证据验收或修订合同；你要求执行时，在 Claude Code 中把 ready 任务逐个派发给 `steward-executor`。不实施，也不替执行者运行验证。 |
| [write-agent-guides](skills/write-agent-guides/SKILL.md) | 维护有依据的 AGENTS.md 层级，共享规则在根文件，子树仅记录局部差异。不维护 CLAUDE.md。 |
| [write-project-docs](skills/write-project-docs/SKILL.md) | 按仓库事实和既有约定维护正式项目文档，明确权威来源并同步相关链接。显式文档请求；局部更新不扩展为文档套件。 |

Codex 可以按意图隐式选择仓库调查、交付规划、代码级任务交接和代理指南技能；其他技能保持各自的调用策略。审查请求只返回发现；创建、修改请求在指定范围内落盘。Claude Code 版另带 `steward-researcher` 和 `steward-executor` 两个插件 agent，用法见下文的模型分工一节。

## 交付链路

一次代码变更可按下列顺序使用技能；每一步都可单独调用，不需要的步骤可以跳过。

1. `analyze-change-request` 在对话中给出带来源和验收标准的需求分析，复杂仓库搜索配合 `parallel-repository-research`；由用户确认需求和决策。
2. 需要拆工作包或排 Sprint 时，用 `plan-delivery` 编写带修订号的实施计划和／或 Backlog。
3. `plan-handoff` 把已确认的需求或计划条目写成 `task-plan.md` 任务合同，并为每个任务指定执行档位、入口检查和尝试预算。
4. 另一执行者按合同内的协议实施并记录结果，无需加载 Steward，可以是低价模型。入口检查失败或合同前提不成立时交回规划者；尝试预算用完时先升一档重跑。
5. 验收负责人用 `plan-handoff` 核对结果记录和实际 diff，决定结项、退回任务或修订合同。
6. 变更影响文档时，用 `write-project-docs`、`write-agent-guides` 同步，也可以直接把文档更新写进任务卡。

## 模型分工

共享技能不指定模型：Codex 的 `openai.yaml` 没有模型字段，`SKILL.md` 的校验也不接受 Claude Code 的模型字段。分工落在宿主配置上：规划和验收在你选的高价模型主会话里做，调研 worker 和执行者交给低价模型。

| 角色 | Claude Code | Codex |
| --- | --- | --- |
| 规划、验收 | 主会话，例如 `claude --model opus` 或 `--model fable` | 主会话 |
| 只读调研 worker | 插件 agent `steward-researcher`：`haiku`，只有读文件和搜索工具，查不了 Git 历史 | 委派工具的模型覆盖：`gpt-6-luna` |
| 执行者 | 插件 agent `steward-executor`：`sonnet`，`effort: medium`；`basic` 档派发时改用更便宜的模型 | `codex exec -p <profile>`，在 profile 里设 `model` 和 `model_reasoning_effort` |

任务卡的执行档位决定交给谁：`basic` 只接短小、可机械验收的任务，用最便宜的模型；`strong` 用执行者的默认模型；`planner` 不交出去。尝试预算用完时先升一档重跑，设计或需求问题才回到规划者。

Codex 执行 profile 示例（`$CODEX_HOME/steward-executor.config.toml`，模型按实测选择）：

```toml
model = "gpt-6-luna"
model_reasoning_effort = "medium"
```

```bash
codex exec -p steward-executor "按 task-plan.md 的执行协议实施 META-01 并记录结果"
```

在 Claude Code 里，也可以不经规划会话派发，单独用低价模型执行：

```bash
claude -p --model sonnet --effort medium "按 task-plan.md 的执行协议实施 META-01 并记录结果"
```

交接本身有成本：规划、写合同、验收和返工都由高价模型承担。活能拆成多个可独立验收的任务时，分工才划算；一个上下文就能做完的单条依赖链，让规划模型调低 effort 直接做往往更便宜。推广前先挑几个真实需求，对比三种做法的验收通过率和总成本：高价模型单跑、高价模型调低 effort 单跑、高价规划加低价执行。headless 运行（`claude -p --output-format json`、`codex exec --json`）输出结构化记录，便于按角色汇总用量。

## 文档与规划

文档维护沿用项目的语言、路径、信息结构和政策。README、项目状态、贡献指南、产品、架构与开发规范是可选文档角色，不是必建文件清单。旧文档中有用的内容、翻译和托管标记继续保留；有仓库生成器管理的区域遵循其契约。没有活动生成器的旧 `write-project-docs:*` 区域可直接维护。

文档技能不再附带固定开发等级目录、双语模板、通用源码规模政策及对应生成／验证脚本。已有项目若直接调用这些 helper CLI，需要改用项目自己的生成器或直接维护相关文档。

规划可以只处理实施计划、只处理 Backlog，或联合维护两者。实施计划拥有范围、工作包与总体验收，Backlog 拥有任务拆分、具体依赖和迭代安排；未知容量以假设表达。采用用户及项目的格式，没有约定时默认放在 `docs/planning/`。

`plan-handoff` 接受已定需求，也可引用现有计划或 Backlog 的条目及修订号，不强制先创建 Sprint 文档；只在对话中确认的需求，连同验收标准和确认来源写进合同。它为下一批稳定工作固定代码级实现、兼容和错误语义、允许裁量、可观察验收、验证命令、执行档位、入口检查、尝试预算及反证回交规则；未来未知工作保持 `draft`。默认从一个 `task-plan.md` 开始，末尾原样附上技能自带的执行／恢复协议，任务状态和结果绑定版本与代码状态。规划者指定最终集成验收负责人；负责人依据结果记录和实际 diff 验收，证据缺失或无法核验不算通过，写下验收记录后计划才标为 `done`。执行者不能用修改合同或降低标准来接受自己的实现。单纯需求分析、Sprint 排期与普通小修复不必走此交接。

计划文件沿用用户或项目指定位置；若放在本仓库被 `.gitignore` 忽略的 `/docs/` 下，跨工作区交付时必须另行传送该文件、代码差异和必要证据，不能假定 Git 会同步它。

```text
使用 $steward:write-project-docs 更新 README 中受本次变更影响的用法与链接。
使用 $steward:write-agent-guides 维护 packages/api/AGENTS.md 的局部命令差异。
使用 $steward:plan-delivery 根据已有实施计划创建 Sprint Backlog，只编写 Backlog。
使用 $steward:plan-handoff 根据已定需求和当前代码创建下一批任务合同，供另一执行者实施。
在 Claude Code 中使用 /steward:plan-handoff 编写合同，再把 ready 任务逐个派发给 steward-executor 执行。
按 task-plan.md 中的执行协议实施下一个 ready 任务并记录结果；合同前提不成立时交回规划者。
使用 $steward:plan-handoff 验收 task-plan.md 的执行结果，决定结项、退回任务或修订合同。
```

## 只读调研

变更分析区分用户要求、实际约束和待决定建议，按目标版本核实代码与公开来源，并随用户纠正更新受影响证据。公开查询不携带私有源码、秘密或个人数据。

仓库调查使用宿主可用的委派工具。Claude Code 使用插件 agent `steward-researcher`：低价模型，只有读文件和搜索工具，只读由工具限制保证，Git 历史由主代理自己查。Codex 支持模型覆盖时，只读工作代理使用 `gpt-6-luna`；其他情况沿用宿主默认模型。子任务限定在仓库读取，主代理核实决定性证据；委派不可用时直接调查。并行能力不会扩大权限；在 Codex 和宿主默认 worker 上，只读仍只是提示词约束，不构成操作系统隔离。

```text
使用 $steward:analyze-change-request 分析批量导入需求，给出来源和验收条件，不修改文件。
使用 $steward:parallel-repository-research 调查两个独立服务的重试调用链，给出代码证据。
```

## 授权边界

技能遵循当前任务授权。提交、推送、发布、部署、外部写入、购买、破坏性操作和范围扩展需要明确授权；已经成立的授权可以继续使用。

## 许可证

Steward 按 [MIT](LICENSE) 许可证发布。
