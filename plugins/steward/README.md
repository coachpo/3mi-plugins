# Steward

Steward 为 Codex 与 Claude Code 提供仓库精简、任务指令改写、项目文档、仓库调研与交付规划技能。两个宿主读取同一份 `skills/` 目录。

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
| [refine-task](skills/refine-task/SKILL.md) | 改写工程需求，不执行原任务；每次都分别给出 GPT-6.1 Sol 和 Claude Opus 5.5 的推荐强度，不切换模型。 |
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
3. 开发与验证由宿主按用户当前授权直接完成。
4. 变更影响文档时，用 `write-project-docs`、`write-agent-guides` 同步正式文档与代理指南；任务运行态不写入这些文档。

## 模型分工

共享技能不在元数据中固定模型：Codex 的 `openai.yaml` 没有模型字段，`SKILL.md` 的校验也不接受 Claude Code 的模型字段。技能正文提供 Codex 的角色建议，不会因为调用技能而自动切换主会话模型。用户明确指定的模型与 effort 优先；没有指定时沿用宿主默认。不能静默替换用户指定值，工具不支持时需先报告。规划和事实核验可在主会话进行，只读调研可交给其他模型。

| 角色 | Claude Code | Codex |
| --- | --- | --- |
| 规划、验收 | 主会话，例如 `claude --model opus` 或 `--model fable` | 主会话；常规任务建议 `gpt-6.1-sol`，最复杂任务建议 `gpt-6-astra` |
| 只读调研 worker | 插件 agent `steward-researcher`：`haiku`，只有读文件和搜索工具，查不了 Git 历史 | 委派工具的模型覆盖：`gpt-6-luna` |

下表按 Codex 工作角色给出建议，仅在需要模型选择建议时适用，并以当前账户与客户端可用的模型为准。

| Codex 模型 | 建议角色 | 适用技能或任务 |
| --- | --- | --- |
| `gpt-6.1-sol` | 常规分析、规划、代码事实与约束核验 | `analyze-change-request`、`plan-delivery`；两项文档技能中的代码事实、指令层级和一致性判断 |
| `gpt-6.1-terra` | 基于已核实事实的文案和结构整理，以及视觉材料理解；视觉结论仍需核对来源 | `write-project-docs`；`write-agent-guides` 中已核实规则的表达整理，不替代事实或指令作用域核验 |
| `gpt-6-astra` | 最复杂的歧义、架构取舍、跨工作包约束、权威或指令冲突，以及困难集成验收 | 分析与规划中的复杂判断；两项文档技能在请求范围内的复杂冲突处理 |
| `gpt-6-luna` | 有界只读调研 | `parallel-repository-research` 与 `analyze-change-request` 的调研 worker |

这些角色建议参考 [OpenAI 官方模型说明](https://learn.chatgpt.com/docs/models#recommended-models)，不代表跨模型评测结果，技能也不会切换模型或自动派发。

## 文档与规划

文档维护沿用项目的语言、路径、信息结构和政策。README、项目状态、贡献指南、产品、架构与开发规范是可选文档角色，不是必建文件清单；写入、更新或迁移文档时，现有架构文档默认对照当前代码、配置和已采纳决策校正。贡献指南在创建或维护时，默认记录乐观设计原则，以及保持源文件内聚、易导航并在规模妨碍理解或评审时拆分的开发原则。`write-agent-guides` 默认将这些原则转为项目根 `AGENTS.md` 中的可执行约束，详细政策与理由链接贡献指南等已有权威文档。已有文档中有用的内容、翻译和托管标记予以保留；有仓库生成器管理的区域遵循其契约。没有活动生成器的旧 `write-project-docs:*` 区域可直接维护。

两个文档技能在新建与维护时，均在范围内的相关政策章节明确写入“本项目默认不保留向后兼容”，已有等价表述不重复；用户或当前有效项目规格、政策明确要求兼容时遵循该要求。默认不为旧接口、格式、配置或实现保留兼容层、别名、双轨路径及过渡代码；获授权替换实现时，同步更新相关调用方、配置、派生契约、测试及文档，移除不再需要的旧路径，不因“可能还有旧调用方”自动增加旧字段回退、双读双写或格式转换。清理限于当前任务；这项文档默认值不自动授权删除现有兼容代码或修改公共 API。`write-project-docs` 将政策写入贡献指南或已有权威政策文档；`write-agent-guides` 将可执行规则写入根 `AGENTS.md`，子树继承，范围外缺失只报告，审查请求仍只读。

任务进度、执行记录和证据属于 working state，不写进 AGENTS.md、README、status、其他正式文档或源码注释。跨压缩／跨会话工作遵循根 working-state policy，使用 gitignored 的 `.agent-work/<task-slug>/`；项目状态只维护持久事实，事实变化时就地改写，不承载进度、changelog、计划或日期工作日志。

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
