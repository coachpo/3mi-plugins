# Steward

Steward 为 Codex 与 Claude Code 提供仓库精简、任务指令改写、项目文档、仓库调研与交付规划技能。两个宿主读取同一份 `skills/` 目录。

## 0.21.2 升级说明

两个文档技能共享的默认政策改为单一来源：设计与开发原则、兼容性政策的默认文本集中在 `write-project-docs/references/default-policies.md`。`write-project-docs` 据此在贡献指南中写出完整政策与理由，`write-agent-guides` 据此在根 `AGENTS.md` 中写出简短的可执行规则并链接权威文档，不再各自内嵌一份。working-state policy 仍只由 `write-agent-guides` 定义，`write-project-docs` 只排除运行态并指向该政策。默认政策内容不变。两个插件 manifest 的版本同步到 0.21.2。

## 0.21.1 升级说明

`write-agent-guides` 的 working-state policy 补齐三处：用户或项目已有进度约定时以其为准，否则写入默认策略；创建 `.agent-work/` 时若尚未被忽略，将其加入 `.gitignore`；每次验证单独存为 `evidence/` 文件，记录确切命令、工作目录、退出码和输出，`Done` 末项引用最近一次验证，恢复时按记录的命令和工作目录重跑。两个插件 manifest 的版本同步到 0.21.1。

## 0.21.0 升级说明

不兼容变更：删除 `execute-plan`、`plan-handoff` 及依赖它们的 `steward-executor` agent，不保留别名或兼容入口；技能目录、使用链路、模型分工、示例和执行记录说明同步清理，并移除已退役执行技能的专项审计报告。沿用 0.x 阶段删除旧能力时提升次版本的惯例，两个插件 manifest 同步到 0.21.0。

`write-agent-guides` 默认在根 `AGENTS.md` 写入 working-state policy：跨压缩或跨会话的进度仅存于 gitignored 的 `.agent-work/<task-slug>/progress.md` 与 `evidence/`，单上下文任务不创建目录。快照整体重写，固定 Goal、Done（逐项附证据路径）、Now、一条可直接执行的 Next、逐行 Decisions；长输出只记路径和退出码。恢复时先读快照、检查 Git 状态与差异，再重跑最后验证，以仓库为准修正记录；验证完成后迁移持久结论并删除本任务目录，其他任务目录只报告。子目录继承根策略，审查时将 AGENTS.md 中的任务进度、会话记录和临时 TODO 列为需移除内容。

`write-project-docs` 将任务进度、执行记录和证据排除在正式文档之外；status 只保留持久的生命周期、部署、支持、用户、数据及兼容性事实，事实变化时就地改写，不追加完成列表、下一步、日期日志或会话更新，事实很少时放在 README 小节。审查或迁移时标出零散进度文件、残留工作目录及 status 中的进度，迁移有效持久事实，其余报告为可删除候选；审查请求保持只读。

## 0.20.2 升级说明

根 README 改为引用统一的技能目录与使用说明，合并模型优先级的重复说明，并去除交接示例对 README 表格布局的无关依赖。技能契约、调用策略、宿主配置、许可证及历史审计保持不变。两个插件 manifest 的版本同步到 0.20.2。

## 0.20.1 升级说明

`simplify-repository` 明确多轮简化：验证后复查变化暴露的新候选及尚未审查的重要关系，按净维护收益继续推进；限定当前约束下简化基线的收敛条件，不宣称全局最优。结果区分已证实冗余、未决候选、待授权变更及环境／验证限制，受阻时报告局部完成，不以停止调查代替收敛结论。两个插件 manifest 的版本同步到 0.20.1。

## 0.20.0 升级说明

新增独立技能 `simplify-repository`，统一精简代码、测试、文档及其他仓库产物。分别保全现行行为与必要复杂度、独有回归覆盖、文档中有效决定／约束／适用前提／验收缺口，以及产物的消费者与必要保留义务。文档和产物清理是主要职责，不限于代码修改的附带清理；不按数量或文件类型机械删减，也不借清理改写业务契约或项目政策。两个插件 manifest 的版本同步到 0.20.0。

## 0.19.0 升级说明

`write-project-docs` 与 `write-agent-guides` 在新建与维护文档时，默认将“不保留向后兼容”明确写入相关政策章节，已有等价表述不重复；用户或当前有效项目规格、政策的明确兼容要求优先。这项文档默认值不自动授权删除现有兼容代码、修改公共 API 或扩大任务范围。两个插件 manifest 的版本同步到 0.19.0。

## 0.18.3 升级说明

`refine-task` 未指定目标时，在同一份提示词后分别给出 GPT-6.1 Sol 和 Claude Opus 5.5 的强度建议，不再按当前宿主二选一。

## 0.18.2 升级说明

`refine-task` 在未指定目标模型时按宿主给出建议：Codex 使用 GPT-6.1 Sol，Claude Code 使用 Claude Opus 5.5。显式目标和强度优先，不切换实际运行模型。

## 0.18.1 升级说明

`refine-task` 新增 Claude Opus 5.5 强度建议：以 Claude API 默认的 `medium` 为起点，按任务和目标客户端选择档位，不更改执行配置。插件链接和安装命令已切换至新仓库 `coachpo/3mi-plugins`；市场名仍是 `coachpo`。

## 0.18.0 升级说明

新增独立技能 `refine-task`。例如：“把‘查清重复扣款原因，先别修’写成给 gpt-6.1-sol 的提示词。”它返回可复制的调查指令，不调查也不修复。无需同时询问思考强度；建议按目标模型及其客户端的已知能力给出，不按编写提示词的宿主推断。目标未指定、是人或没有已知强度档位时，不附档位。它不是开发或正式交接的前置步骤。

## 0.17.0 升级说明

`write-agent-guides` 默认在项目根 `AGENTS.md` 中加入源文件内聚、易导航与必要拆分的可执行规则：新增或修改代码时，若文件规模或继续增长妨碍职责区分、行为定位或局部评审，在本次任务范围内按内聚职责拆分；沿用项目已有规模限制，不设通用行数上限，也不为缩短文件制造无意义的碎片或抽象。详细政策与理由仍由贡献指南等已有权威文档统一维护，根指引链接引用。项目已采纳不同政策时保持原政策。两个插件 manifest 的版本同步到 0.17.0。

## 0.16.1 升级说明

补齐 Codex 的模型角色建议：`gpt-6.1-sol` 用于常规分析、规划、代码级合同、`strong` 实现、执行协调和验收；`gpt-6.1-terra` 用于基于已核实事实的文案、结构及视觉材料理解；`gpt-6-astra` 用于最复杂的设计取舍、约束冲突和集成验收。相关技能正文同步这些建议，保留现有 Luna 调研分工；不自动切换主会话模型，不覆盖用户或宿主选择，不新增执行配置、调度或评测。两个插件 manifest 的版本同步到 0.16.1。

## 0.16.0 升级说明

新增 `execute-plan`，把已批准计划推进到工程交付，支持串行、并行和混合执行，负责合同与环境准备、派发、实际 diff 审查、最终集成验证，以及已有授权内的提交与资源清理。复用 `plan-delivery` 的范围与总体验收、`plan-handoff` 的代码级合同与证据验收；原技能保留各自职责。Codex Desktop 与 CLI／Claude Code 共用核心流程，仅在必要时读取宿主适配参考；技能不提供或保证会话管理工具。两个插件 manifest 的版本同步到 0.16.0。

## 0.15.0 升级说明

`write-project-docs` 在文档写入、更新和迁移时默认核对现有架构文档，并依据当前代码、配置和已采纳决策修正过时内容；创建或维护贡献指南时，默认加入源文件保持内聚、易导航并在影响理解或评审时拆分的原则，沿用已有项目限制且不设通用行数上限。两个插件 manifest 的版本同步到 0.15.0。

## 0.14.0 升级说明

`write-project-docs` 的贡献指南（通常为 `CONTRIBUTING.md`）角色新增设计与开发原则：默认采用乐观取向，按较宽松的平台能力、资源档位与配额设计并记录工作假设，不为假设的最坏情况预先收紧；默认绝大多数请求正常，不预置滥用防护与保守限流；默认选择最好情况分支，最坏情况处理必须是具名决策。`write-agent-guides` 在根 AGENTS.md 中以可执行规则承载同一默认，理由链接贡献指南或政策文档。乐观取向只作用于政策与设计取舍，未知限制仍以工作假设加复查条件表述，不写成已验证事实；项目已采纳不同政策时保持原政策。两个插件 manifest 的版本同步到 0.14.0。

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
codex plugin marketplace add coachpo/3mi-plugins --ref main
codex plugin add steward@coachpo
```

Claude Code：

```bash
claude plugin marketplace add coachpo/3mi-plugins@main
claude plugin install steward@coachpo
```

安装或更新后，新建 Codex 任务或 Claude Code 会话加载技能。Codex 调用形式为 `$steward:<skill-name>`，Claude Code 为 `/steward:<skill-name>`。

## 技能用途与边界

| 技能 | 主要结果与边界 |
| --- | --- |
| [refine-task](skills/refine-task/SKILL.md) | 改写工程需求，不执行原任务。显式目标优先；未指定目标时分别给出 GPT-6.1 Sol 和 Claude Opus 5.5 的强度建议，不切换模型。 |
| [simplify-repository](skills/simplify-repository/SKILL.md) | 联合精简代码、测试、文档及其他产物，保全行为、覆盖、有效知识和必要用途／保留义务。可独立实施与验证；审查只返回发现，不借清理下线功能、改写政策或重建文档体系。 |
| [analyze-change-request](skills/analyze-change-request/SKILL.md) | 结合仓库与公开来源分析变更需求，提供引用及可观察验收标准。显式调用；只读，不实施或执行项目。 |
| [parallel-repository-research](skills/parallel-repository-research/SKILL.md) | 至少两条独立调查线定位代码、梳理架构或追踪依赖，主代理核实证据。只读，不运行测试或判定行为风险。 |
| [plan-delivery](skills/plan-delivery/SKILL.md) | 创建、修订或审查实施计划和／或 Sprint Backlog，明确交付、责任、依赖及验收。只规划，不执行开发。 |
| [write-agent-guides](skills/write-agent-guides/SKILL.md) | 维护有依据的 AGENTS.md 层级，共享规则在根文件，子树仅记录局部差异。不维护 CLAUDE.md。 |
| [write-project-docs](skills/write-project-docs/SKILL.md) | 按仓库事实和既有约定维护正式项目文档，明确权威来源并同步相关链接。显式文档请求；局部更新不扩展为文档套件。 |

Codex 可以按意图隐式选择仓库精简、任务指令改写、仓库调查、交付规划和代理指南技能；其他技能保持各自的调用策略。审查请求只返回发现；创建、修改请求在指定范围内落盘。Claude Code 版另带只读调研插件 agent `steward-researcher`，用法见下文的模型分工一节。

## 仓库精简

使用 `simplify-repository` 清理已证实冗余的仓库内容，目标是只保留仍有用途或保留义务的内容，而不是让每类内容都减少。它拥有独立的文档归并和产物清理职责，其他文档技能提供专门方法，不排除这些清理范围；迁移、业务历史、许可证、测试基准和必要交付输入不能仅因陈旧或可重新生成就删除。

有界清理无需先建计划、任务合同、子代理或工作树。

```text
使用 $steward:simplify-repository 精简当前仓库的代码、测试、文档及其他产物，保全四类义务并完成验证，不提交或推送。
使用 /steward:simplify-repository 只审查当前目录的冗余候选及保留义务，不实施清理。
```

## 交付链路

一次代码变更可按下列链路使用技能；每一步都可单独调用，不需要的步骤可以跳过。

1. `analyze-change-request` 在对话中给出带来源和验收标准的需求分析，复杂仓库搜索配合 `parallel-repository-research`；由用户确认需求和决策。
2. 需要拆工作包或排 Sprint 时，用 `plan-delivery` 编写带修订号的实施计划和／或 Backlog；该技能到规划为止，不派发任务、不实施或验收。
3. 开发与验证由宿主按用户当前授权直接完成，Steward 不再提供专门的代码级合同或执行编排入口。
4. 变更影响文档时，用 `write-project-docs`、`write-agent-guides` 同步正式文档与代理指南；任务运行态不写入这些文档。

## 模型分工

共享技能不在元数据中固定模型：Codex 的 `openai.yaml` 没有模型字段，`SKILL.md` 的校验也不接受 Claude Code 的模型字段。技能正文提供 Codex 的角色建议，不会因为调用技能而自动切换主会话模型。用户明确指定的模型与 effort 优先；没有指定时沿用宿主默认。不能静默替换用户指定值，工具不支持时需先报告。规划和事实核验可在主会话进行，只读调研可交给其他模型。

| 角色 | Claude Code | Codex |
| --- | --- | --- |
| 规划、验收 | 主会话，例如 `claude --model opus` 或 `--model fable` | 主会话；常规任务建议 `gpt-6.1-sol`，最复杂任务建议 `gpt-6-astra` |
| 只读调研 worker | 插件 agent `steward-researcher`：`haiku`，只有读文件和搜索工具，查不了 Git 历史 | 委派工具的模型覆盖：`gpt-6-luna` |

下表按 Codex 工作角色给出建议，仅在需要模型选择建议时适用，并以当前账户与客户端可用的模型为准。Claude Code 的分工保持不变。

| Codex 模型 | 建议角色 | 适用技能或任务 |
| --- | --- | --- |
| `gpt-6.1-sol` | 常规分析、规划、代码事实与约束核验 | `analyze-change-request`、`plan-delivery`；两项文档技能中的代码事实、指令层级和一致性判断 |
| `gpt-6.1-terra` | 基于已核实事实的文案和结构整理，以及视觉材料理解；视觉结论仍需核对来源 | `write-project-docs`；`write-agent-guides` 中已核实规则的表达整理，不替代事实或指令作用域核验 |
| `gpt-6-astra` | 最复杂的歧义、架构取舍、跨工作包约束、权威或指令冲突，以及困难集成验收 | 分析与规划中的复杂判断；两项文档技能在请求范围内的复杂冲突处理 |
| `gpt-6-luna` | 保留现有的有界只读调研角色 | `parallel-repository-research` 与 `analyze-change-request` 的调研 worker |

这些角色建议参考 [OpenAI 官方模型说明](https://learn.chatgpt.com/docs/models#recommended-models)，不代表已完成跨模型评测，也不新增模型切换或自动派发能力。

## 文档与规划

文档维护沿用项目的语言、路径、信息结构和政策。README、项目状态、贡献指南、产品、架构与开发规范是可选文档角色，不是必建文件清单；写入、更新或迁移文档时，现有架构文档默认对照当前代码、配置和已采纳决策校正。贡献指南在创建或维护时，默认记录乐观设计原则，以及保持源文件内聚、易导航并在规模妨碍理解或评审时拆分的开发原则。`write-agent-guides` 默认将这些原则转为项目根 `AGENTS.md` 中的可执行约束，详细政策与理由链接贡献指南等已有权威文档。旧文档中有用的内容、翻译和托管标记继续保留；有仓库生成器管理的区域遵循其契约。没有活动生成器的旧 `write-project-docs:*` 区域可直接维护。

两个文档技能在新建与维护时，均在范围内的相关政策章节明确写入“本项目默认不保留向后兼容”，已有等价表述不重复；用户或当前有效项目规格、政策明确要求兼容时遵循该要求。默认不为旧接口、格式、配置或实现保留兼容层、别名、双轨路径及过渡代码；获授权替换实现时，同步更新相关调用方、配置、派生契约、测试及文档，移除不再需要的旧路径，不因“可能还有旧调用方”自动增加旧字段回退、双读双写或格式转换。清理限于当前任务；这项文档默认值不自动授权删除现有兼容代码或修改公共 API。`write-project-docs` 将政策写入贡献指南或已有权威政策文档；`write-agent-guides` 将可执行规则写入根 `AGENTS.md`，子树继承，范围外缺失只报告，审查请求仍只读。

任务进度、执行记录和证据属于 working state，不写进 AGENTS.md、README、status、其他正式文档或源码注释。跨压缩／跨会话工作遵循根 working-state policy，使用 gitignored 的 `.agent-work/<task-slug>/`；项目状态只维护持久事实，事实变化时就地改写，不承载进度、changelog、计划或日期工作日志。

文档技能不再附带固定开发等级目录、双语模板、通用行数上限政策及对应生成／验证脚本。已有项目若直接调用这些 helper CLI，需要改用项目自己的生成器或直接维护相关文档。

规划可以只处理实施计划、只处理 Backlog，或联合维护两者。实施计划拥有范围、工作包与总体验收，Backlog 拥有任务拆分、具体依赖和迭代安排；未知容量以假设表达。采用用户及项目的格式，没有约定时默认放在 `docs/planning/`。

计划文件沿用用户或项目指定位置；若放在本仓库被 `.gitignore` 忽略的 `/docs/` 下，跨工作区交付时必须另行传送该文件、代码差异和必要证据，不能假定 Git 会同步它。

```text
使用 $steward:write-project-docs 更新 README 中受本次变更影响的用法与链接。
使用 $steward:write-agent-guides 维护 packages/api/AGENTS.md 的局部命令差异。
使用 $steward:plan-delivery 根据已有实施计划创建 Sprint Backlog，只编写 Backlog。
```

## 只读调研

变更分析区分用户要求、实际约束和待决定建议，按目标版本核实代码与公开来源，并随用户纠正更新受影响证据。公开查询不携带私有源码、秘密或个人数据。

仓库调查使用宿主可用的委派工具。Claude Code 使用插件 agent `steward-researcher`：低价模型，只有读文件和搜索工具，只读由工具限制保证，Git 历史由主代理自己查。Codex 支持模型覆盖时，只读工作代理使用 `gpt-6-luna`；其他情况沿用宿主默认模型。子任务限定在仓库读取，主代理核实决定性证据；委派不可用时直接调查。并行能力不会扩大权限；在 Codex 和宿主默认 worker 上，只读仍只是提示词约束，不构成操作系统隔离。

```text
使用 $steward:analyze-change-request 分析批量导入需求，给出来源和验收条件，不修改文件。
使用 $steward:parallel-repository-research 调查两个独立服务的重试调用链，给出代码证据。
```

## 授权边界

技能遵循当前任务授权，发现技能不等于授权执行。实施请求允许范围内的本地准备、修改和验证；计划内容获批不自动授予执行或所有交付动作的权限。提交、推送、PR 变更／合并、发布、部署、外部写入、购买、破坏性操作和实质范围扩展需要相应明确授权；已经成立的授权可以继续使用，不重复确认。授权实施、提交、归档和删除本次任务工作树／分支时直接完成这些动作，不扩大到主会话、集成分支、无关来源会话或业务数据。

Codex Desktop 仅在用户明确要求新 chat 时使用相应创建工具；工作树会话遵循用户选择和实际工具规则，异步创建需取得真实 ID 后再协调。CLI／Claude Code 使用实际可用执行者和 Git 工作树，不强制安装额外插件。宿主有可恢复工作树归档机制时优先使用，必要的 ignored 材料另行保存；工作树清理与会话归档是两个操作，工具或权限缺失时如实报告保留状态。

## 许可证

Steward 按 [MIT](LICENSE) 许可证发布。
