# Steward

Steward 为 Codex 与 Claude Code 提供仓库精简、界面文案清理、任务指令改写、项目文档与仓库调研技能。两个宿主读取同一份 `skills/` 目录。

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

`simplify-repository` 和 `simplify-interface-text` 在两个宿主都仅允许显式调用：Codex 使用 `agents/openai.yaml` 的 `policy.allow_implicit_invocation: false`；Claude Code 使用共享 `SKILL.md` 的 `disable-model-invocation: true`。该 Claude Code 扩展字段不替代 Codex 的调用策略；Codex 运行时可加载带该字段的技能，但仅接受通用 frontmatter 字段的校验器会拒绝它，须另用宿主原生加载检查确认兼容性。两宿主的调用控制分别见 [Codex 技能配置](https://learn.chatgpt.com/docs/build-skills#optional-metadata)与 [Claude Code 技能配置](https://code.claude.com/docs/en/skills#control-who-invokes-a-skill)。

## 技能用途与边界

| 技能 | 主要结果与边界 |
| --- | --- |
| [refine-task](skills/refine-task/SKILL.md) | 改写工程需求，不执行原任务；调研、需求分析和实现任务的提示词都在范围内，开发前和开发中都可使用。提示词自足：写入会话中已确定且任务依赖的事实和决定，并与仍需执行方核实的内容分开。每次都分别给出 Codex 和 Claude Code 的推荐强度，不切换模型。 |
| [simplify-repository](skills/simplify-repository/SKILL.md) | 显式调用；联合精简代码、测试、文档及其他产物，保全行为、覆盖、有效知识和必要用途／保留义务。每次调用先审查并给出候选，问一次是否清理，确认后实施并验证；请求明说只审查时不询问，明说直接清理时不询问。确认即授权删除范围内已纳入版本控制的内容；未纳入版本控制或被忽略的文件在同一次询问里单独列出，确认明确覆盖时才删除。清理也把 AGENTS.md 层级和贡献指南里的规则清理到无重复，不改变规则含义；条件或范围不同的相近条款按冲突报告。审查只返回发现，不借清理下线功能、改写政策或重建文档体系。 |
| [simplify-interface-text](skills/simplify-interface-text/SKILL.md) | 显式调用；按角色和状态在渲染出的屏幕上走查界面文案，清理重复、常驻、讲内部机制和解说控件的文字，缩写必要但冗长的文字，保留确认、唯一信息和有功能的文字。每次调用先走查并给出清单，对整份清单问一次是否清理，确认后改完；请求明说只审查时不询问，明说直接改或给出已确认清单时不询问；缩写保留原文的事实、条件、数值、单位、专有名词和要求的动作，报告给出改前和改后文本；清理会改变可见输出，但不改命令、金额、存储事实或服务端契约。不负责新功能文案、翻译或视觉改版。 |
| [parallel-repository-research](skills/parallel-repository-research/SKILL.md) | 至少两条独立调查线定位代码、梳理架构或追踪依赖，主代理核实证据。调用即授权范围内的只读委派，用户显式调用和被自动选中时相同。只读，不运行测试或判定行为风险。 |
| [write-agent-guides](skills/write-agent-guides/SKILL.md) | 维护有依据的 AGENTS.md 层级，共享规则在根文件，子树仅记录局部差异。仓库指南不依赖用户级全局指令文件：只读取它们以发现冲突并报告。新建根 AGENTS.md 时写入适用的默认政策。不维护 CLAUDE.md、技能或子代理提示词，也不编辑用户级全局指令文件。 |
| [write-project-docs](skills/write-project-docs/SKILL.md) | 按仓库事实和既有约定维护正式项目文档，明确权威来源并同步相关链接。新建贡献指南时写入适用的默认政策；建立文档体系时沿用已有文档，有已核实的技术方案才建架构文档。局部更新不扩展为文档套件。 |

Codex 可以按意图隐式选择任务指令改写、仓库调查、项目文档和代理指南技能；其他技能保持各自的调用策略。审查请求只返回发现。显式调用 `write-agent-guides` 或 `write-project-docs` 默认更新授权范围内的项目事实；隐式选择且写入意图不清楚时只审查。两个技能不修改已有文件里的政策；新建根 `AGENTS.md` 或贡献指南时写入适用的默认政策。`simplify-repository` 和 `simplify-interface-text` 调用时不必说明审查还是清理：默认先审查，给出发现后询问一次，确认后清理。Claude Code 版另带只读调研插件 agent `steward:steward-researcher`，用法见下文。

## 仓库精简

使用 `simplify-repository` 清理已证实冗余的仓库内容，目标是只保留仍有用途或保留义务的内容，而不是让每类内容都减少。它拥有独立的文档归并和产物清理职责，其他文档技能提供专门方法，不排除这些清理范围；迁移、业务历史、许可证、测试基准和必要交付输入不能仅因陈旧或可重新生成就删除。

有界清理无需先建计划、任务合同、子代理或工作树。

```text
使用 $steward:simplify-repository 精简当前仓库的代码、测试、文档及其他产物，保全四类义务并完成验证，不提交或推送。
使用 /steward:simplify-repository
使用 /steward:simplify-repository 只审查当前目录的冗余候选及保留义务，不实施清理。
```

## 界面文案清理

使用 `simplify-interface-text` 清理已有界面上不改变用户行动、也不提供新信息的文字。重复和冗余只在渲染出的屏幕上成立，所以先按角色和状态走查，给出带替换文案的清单并询问一次，确认后清理；明说只审查时只出清单，明说直接改时不询问。必要但冗长的文字缩写后保留原文的全部事实，各语言按含义分别改写。到不了的状态从源码读取并注明。为复现页面状态，可在非生产环境创建并推进带标记的测试记录，请求本身即覆盖这一步；生产环境需要用户针对该环境的指示，审查时不在生产环境创建。审查不修改源码、文案、配置或既有记录。规则优先取项目贡献指南中已采纳的界面文案规则，没有时使用默认的界面文案原则。保存在实例里的设置或内容不是源码，单独列给内容所有者。它与 `simplify-repository` 的区别是会有意改变可见输出。

```text
使用 $steward:simplify-interface-text
使用 $steward:simplify-interface-text 只审查顾客端和员工端的界面文案，给出带页面、出现条件和源码位置的清单，不修改源码、文案、配置或既有记录。
使用 /steward:simplify-interface-text 直接简化顾客端的界面文案，不用询问，所有语言同步，完成验证并给出改前改后文本，不提交或推送。
```

## 交付链路

一次代码变更可按下列链路使用技能；每一步都可单独调用，不需要的步骤可以跳过。

1. 需要复杂仓库搜索时，用 `parallel-repository-research` 定位代码、梳理架构或追踪依赖。
2. 开发与验证由宿主按用户当前授权直接完成。
3. 变更影响文档时，用 `write-project-docs`、`write-agent-guides` 同步正式文档与代理指南，两者都用时先文档后指南；任务运行态不写入这些文档。多组件或多子树的仓库需要独立搜索时，两个技能可使用 `parallel-repository-research`。

## 模型分工

技能不改会话或调研 worker 的模型与 effort 设置，沿用用户或宿主配置。`refine-task` 只在改写结果中分别给出 Codex 和 Claude Code 的推荐强度。

## 项目文档

文档维护沿用项目的语言、路径、信息结构和权威划分。新建文档，或在没有既定布局的仓库里迁移时，按需使用默认路径：`README.md`（用途、上手、链接）、`STATUS.md`（持久项目状态）、`CONTRIBUTING.md`（开发环境、命令、流程和贡献政策）、`docs/PRODUCT.md`（产品需求、运营背景和义务）、`docs/ARCHITECTURE.md`（组件、职责、依赖、数据流和设计决策）。只在有已核实内容且需要该文档时创建；保留仍有效的内容、翻译和托管区域。

- **事实更新**：显式调用默认在授权范围内，依据当前源码、配置和已确认的项目事实更新命令、路径、部署状态和组件职责等内容。保留仍成立的事实。混合段落只改可核实的事实，不改变政策含义；两者无法分开时只报告。更新或重写已有文档不自动写入默认政策。
- **新建时的默认政策**：`write-agent-guides` 新建根 `AGENTS.md`、`write-project-docs` 新建贡献指南时，写入适用的 Steward 默认政策并在报告中列出。仓库没有根 `AGENTS.md` 时显式调用即新建；仓库还没有正式文档时，显式调用 `write-project-docs` 等同于建立文档体系；建立文档体系时，仓库没有贡献指南或其他政策权威来源即新建贡献指南。用户为项目说明的规则（例如保留向后兼容）取代与之矛盾的默认条款；与仓库现行政策冲突的默认条款不写入，只报告。
- **用户确立的规则**：用户要求记录时，只写入用户明确说成规则的内容；从用户的纠正或一次性指令归纳出的规则只列出候选和依据，用户说写入后再写。项目的设计、开发、评审政策写入贡献指南，代理操作规则写入 `AGENTS.md` 层级。
- **只读审查**：明确要求审查时不写文件。发现政策缺失或与 Steward 默认政策冲突时，只报告，不自行补齐，也不删除或改写现行条款。
- **政策变更**：已有文件里的政策，仅当用户明确要求修改指定政策或用 Steward 默认政策替换现行政策时，才在授权范围内增删或替换。保留用户点名保留的条款和已确认的强制义务。政策写在既有权威来源中；代理操作规则与默认 [working-state policy](skills/write-agent-guides/references/working-state-policy.md) 属于根 `AGENTS.md`，不写进贡献指南。Steward 的默认条款及适用条件见 [默认政策](references/default-policies.md)。

部署状态和生产标识是项目事实；只记录已核实的信息，区分工作假设，不写密钥值。更新部署信息不授权切换迁移政策。任务进度、执行记录和证据不写入正式文档；项目状态仅维护持久事实，不承载进度、更新日志或计划。

```text
使用 $steward:write-project-docs 更新 README 中受本次变更影响的用法与链接。
使用 $steward:write-agent-guides 维护 packages/api/AGENTS.md 的局部命令差异。
```

## 只读调研

仓库调查使用宿主可用的委派工具。Claude Code 使用插件 agent `steward:steward-researcher`：只有读文件和搜索工具，只读由工具限制保证，Git 历史由主代理自己查。Codex 和其他宿主沿用默认 worker，不指定模型。子任务限定在仓库读取，主代理核实决定性证据；调用 `parallel-repository-research` 即授权范围内的只读委派，显式调用和被自动选中时相同；委派不可用或用户限制时直接调查。并行能力不会扩大权限；在 Codex 和宿主默认 worker 上，只读仍只是提示词约束，不构成操作系统隔离。

```text
使用 $steward:parallel-repository-research 调查两个独立服务的重试调用链，给出代码证据。
```

## 授权边界

技能遵循当前任务授权，发现技能不等于授权执行。实施请求允许范围内的本地准备、修改和验证；计划内容获批不自动授予执行或所有交付动作的权限。提交、推送、PR 变更／合并、发布、部署、外部写入、购买、破坏性操作和实质范围扩展需要相应明确授权；已经成立的授权可以继续使用，不重复确认。授权实施、提交、归档和删除本次任务工作树／分支时直接完成这些动作，不扩大到主会话、集成分支、无关来源会话或业务数据。

Codex Desktop 仅在用户明确要求新 chat 时使用相应创建工具；工作树会话遵循用户选择和实际工具规则，异步创建需取得真实 ID 后再协调。CLI／Claude Code 使用实际可用执行者和 Git 工作树，不强制安装额外插件。宿主有可恢复工作树归档机制时优先使用，必要的 ignored 材料另行保存；工作树清理与会话归档是两个操作，工具或权限缺失时如实报告保留状态。

## 许可证

Steward 按 [MIT](LICENSE) 许可证发布。
