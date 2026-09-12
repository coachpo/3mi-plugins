# Steward 七技能审核与组件消融

基线：`103b0e6`，Steward 0.8.9。修改位置：`plugins/steward/`。安装缓存中的技能与审核前源码一致；本报告记录升级发布前的源码审核与试验，安装缓存状态以随后执行的更新结果为准。

七个技能保留用户指定的用途与边界。删除 45 个组件文件，插件文件数由 77 降至 32；七个技能入口由 767 行、42,395 字符降至 421 行、23,056 字符，字符数减少约 46%。保留的六个 GOAL／验收运行时脚本及其 38 项测试与基线逐字节一致。

方法参考 [OpenAI 的技能与提示词文章](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra)：保留任务专属信息，按需提供细节，去掉重复或过度规定流程的指导。具体删减还依据调用关系、行为对照和运行时回归；没有把文章解释为删除所有脚本或测试的要求。

## 逐技能结论

| 技能 | 消融和删除 | 保留的必要功能 | 入口行数 |
| --- | --- | --- | ---: |
| [analyze-change-request](../plugins/steward/skills/analyze-change-request/SKILL.md) | 删除重复 research-contract、固定 ResearchBrief／状态协议、冻结调查线、固定重试次数及额外机械隔离门槛。 | 显式调用；仓库与公开资料、版本适用性、脱敏查询、用户纠正、来源与可观察验收标准；只读不执行项目。 | 129 → 63 |
| [draft-consensus-goal](../plugins/steward/skills/draft-consensus-goal/SKILL.md) | 合并单独的 context 参考；删除无人调用的 PTY 桥接器及其参数测试、重复且没有消费者的 JSON schema；精简重复授权及格式说明。 | 为执行者起草任务；持久 bundle、验收意图、别名、同 worktree 恢复及格式校验。共享格式参考和真实创建脚本继续保留。 | 48 → 28 |
| [parallel-repository-research](../plugins/steward/skills/parallel-repository-research/SKILL.md) | 删除两份宿主适配器、硬编码模型、固定重试次数、冻结调查线及结果状态仪式。 | 至少两条独立调查线、宿主当前工具与模型默认值、只读、不运行测试、不判定行为风险；主代理复核与必要回退。 | 124 → 45 |
| [plan-delivery](../plugins/steward/skills/plan-delivery/SKILL.md) | 删除两个模板、重复 planning-rules 清单、与 GOAL 命名的无关耦合及重复流程规定。 | 计划／Backlog 权威区分，工作包、责任、交接、真实前置依赖和验收；保持用户格式、容量假设与局部修订范围，只规划。 | 124 → 82 |
| [run-closed-loop-verification](../plugins/steward/skills/run-closed-loop-verification/SKILL.md) | 压缩状态参考与重复流程描述，按需读取修补载荷；取消无执行器支持的单 worktree 单 GOAL 惯例。 | 显式 GOAL 验收、先诊断后修复、恢复、定向复测、修补后的最终回归、当前源码与历史完成区分、证据完整性。未删除真实运行时或其回归测试。 | 85 → 68 |
| [write-agent-guides](../plugins/steward/skills/write-agent-guides/SKILL.md) | 删除通用权限复述、固定搜索次数、语言判断特例和重复核查要求。原本没有附带脚本或测试。 | 有效 AGENTS 层级、根共享规则、子树实际差异、命令与范围证据、用户偏好、托管区块保护；不维护 CLAUDE.md。 | 104 → 55 |
| [write-project-docs](../plugins/steward/skills/write-project-docs/SKILL.md) | 删除 10 个生成／验证脚本、22 个双语模板、两份固定政策参考，以及随子系统退役的六项测试。取消固定八文档套件、七档策略、双语路径限制和通用源码规模政策。 | 按已验证事实维护正式文档、单一权威、既有语言与路径、局部范围、迁移信息保全、托管区块所有权、实际链接与文档检查。 | 153 → 80 |

研究、规划、代理指南和项目文档五个技能现在均只需要 `SKILL.md` 与调用配置。所有显式／隐式调用策略保持原样。说明同步到 [插件 README](../plugins/steward/README.md)。

## 删除与保留的依据

文档脚本原本解决固定模板体系的生成和一致性，并非一般文档维护必需能力：局部更新会受其他语言路径、缺少套件文档或无关等级模板影响；全套验证主要检查结构及模板一致性，不验证本地链接有效性。调用检查没有发现该子系统之外的代码消费者。新技能沿用项目自己的结构、语言、检查器和政策，能直接完成原任务。

PTY 桥接器没有活动调用方；现有 staged-file transport、shell 重定向和有限 stdin pipe 已能提供输入。删除的 JSON schema 没有运行时消费者，且不能替代 Python 中完整的字段一致性与验收覆盖检查。

相反，GOAL 脚本实现不可变合同、worktree 绑定、幂等创建、路径与摘要检查；验收引擎实现可恢复状态、真实失败与修补记录、证据绑定及最终回归。这些是实际机械保证，不能用一句模型提示词等价替代。保留七行格式、4,000 字符上限和 v1 序列化以兼容已有 bundle；本次没有重设计协议。

删除的七项测试随退役子系统一起移除，没有削弱保留代码的测试，也没有新增匹配文案或标题的静态测试。

## 行为对照设计

使用 GPT-6 Astra、reasoning effort `high`、Codex CLI 0.154.0。在独立临时 Git 仓库中比较三组：

- **原包**：完整 103b0e6 运行时组件。
- **精简包**：本次精简后的提示词、脚本、模板和测试。
- **移除目标提示词**：精简包中移除当前目标技能的入口和局部参考，其他技能与共享 GOAL 合同保留。

七项核心任务各运行三组，另对项目自定义文档体系运行原包与精简包，共 23 次。fixture 创建与机械判分固定使用原包作为独立 oracle，避免删除组件导致试验装置失效，或用受测实现证明自身正确。三组统一排除 README、插件 manifest 与 UI 默认提示词，以供应的技能目录进行选择；这不测试原生安装或自动发现。

每次使用新会话、独立工作区、固定请求及随机顺序。记录输入、源码快照、模型事件、产物、用量和包哈希。所有包在试验前后均未被改写。独立评审者读取用户请求、产物及命令证据，不读取组别或实现结论；格式检查不充当语义评审。

## 核心对照结果

23 次均正常完成，机械检查全部通过。独立评审为 20 次通过、3 次部分核验。三个部分核验全部来自并行调查的 CLI 委派证据缺失：调查内容和主代理源码复核正确，但记录中只有接收者为空的等待事件，不能据此确认已启动两个子代理，也不能断言它们从未运行。

| 样本 | 原包 | 精简包 | 移除目标提示词 |
| --- | --- | --- | --- |
| 变更分析：纠正后的 SDK 3、单条兼容、顺序与部分失败 | 通过 | 通过 | 通过 |
| GOAL：未给 alias，正确保存执行者合同 | 通过 | 通过 | 通过 |
| 仓库调查：两条幂等调用链 | 内容通过；委派未核实 | 内容通过；委派未核实 | 内容通过；委派未核实 |
| 规划：仅生成 Backlog、保留主计划及真实接入义务 | 通过 | 通过 | 通过 |
| 验收：源码变化后拒绝沿用历史 COMPLETE | 通过 | 通过 | 通过 |
| AGENTS：仅补充子树偏好并保留父层关系和托管块 | 通过 | 通过 | 通过 |
| 文档：仅修复一个托管区块的失效引用 | 通过 | 通过 | 通过 |
| 文档扩展：西班牙语、handbook 自定义路径、preview-interna 阶段、既有正文及外部托管块 | 通过 | 通过 | 未运行 |

文档扩展的两组都只修改六个授权路径；原包 31 个、精简包 37 个相对链接均可达，源代码、测试、配置与 STATUS.md 不变。没有把文档里的命令示例误计为项目执行。

针对 CLI 的记录缺口，额外使用原生 `collaboration.spawn_agent` 对精简版进行正向测试。实际观察到 `http_upload` 与 `queue_export` 两个独立只读子代理，主代理收到结果后重新打开决定性代码；最终调用链、返回值及跳过操作的判断正确。该结果单独记录，不回写为三份 CLI 样本“完整通过”。

## 修复闭环扩展

另运行原包与精简包各一次真实修补任务，共两次，补齐只检查历史源码漂移所不能证明的主要能力。固定 GOAL 明确授权只修复 app.py，两个 required case 中边界行为初始通过，大小写行为初始失败。

两组均先读取实际失败及源码位置，再仅将 `.upper()` 修成 `.lower()`；记录修补后定向复测失败 case，最后回归全部两个 case。当前源码指纹与完成记录相同，结果为 COMPLETE，失败历史、测试、GOAL 和执行计划保留。每组 13 项机械／oracle 检查和独立语义评审均通过。两轮使用相同的基线与候选包快照。

合计 25 次对照全部正常完成且机械检查通过；独立评审 22 次完整通过、3 次内容通过但委派未核实。原生并行补验不计入这 25 次。

## 验证与兼容性

以下检查均通过：

```bash
python3 -B -m unittest discover -s plugins/steward/tests -p 'test_*.py'
# 18 tests: OK
python3 -B -m unittest discover -s plugins/steward/skills/run-closed-loop-verification/tests -p 'test_*.py'
# 20 tests: OK
```

七个技能的 `quick_validate.py`、调用策略及默认提示一致性、插件 JSON 及技能路径检查、文档相对文件链接检查和 `git diff --check` 均通过。格式检查只证明文件可解析；功能判断来自上述产物评审及真实运行时检查。

原文档 helper CLI 不再提供。直接调用它们的下游项目需要改用自己的生成器或直接维护；已有文档及 markers 不会被这次改动迁移或删除。有活动生成器的托管区域继续遵循其契约。已有 GOAL bundle 与 campaign 使用相同运行时，保持格式与校验兼容。审核时安装缓存为原 0.8.9；升级为 0.9.0 后需刷新插件并在新任务中加载。

## 结论的限度

本轮支持删除已识别的组件和重复约束，未观察到精简版相对原包的任务能力退化；它不证明每项技能必不可少。移除目标提示词的样本也完成了主要内容，说明当前模型能独立处理这些简单任务；其他技能和共享合同仍在，因此不能解释成完全无技能或无运行时也等价。

每个条件只运行一次，样本为合成任务，组件按组删除，不能估计每个文件的独立贡献或普遍可靠性。未覆盖真实公网研究、在线用户中途纠正、所有文档迁移、原生技能发现、其他模型及全部故障组合。共享主机负载影响了首批耗时，CLI 也未提供可完整归属的子代理用量，因此不作稳定提速或费用下降的结论。

## 原始证据

[完整证据归档](../experiments/steward-ablation/runs/component-20260912-220333.tar.gz)已保存在现有忽略目录的新文件中，未覆盖此前实验。归档包含试验装置、固定包快照、全部 trial、独立评审及原生补验记录；SHA-256：`b92921250baeaef74218f61eb8d213ea5bfcaa3712649d342656ba074b5158c4`。临时路径失效后仍可读取归档证据；其中绑定原 worktree 的 GOAL 不能直接搬迁后继续执行，复现应重新创建 fixture。

- [核心运行清单](/tmp/steward-component-ablation-C9d9Wc/runs/20260912-220333/manifest.json)、[机械结果](/tmp/steward-component-ablation-C9d9Wc/runs/20260912-220333/results.json)、[独立评审](/tmp/steward-component-ablation-C9d9Wc/runs/20260912-220333/semantic-reviews.json)、[汇总](/tmp/steward-component-ablation-C9d9Wc/runs/20260912-220333/summary.json)。
- [修复闭环运行清单](/tmp/steward-component-ablation-C9d9Wc/repair-extension/runs/20260912-222036/manifest.json)、[结果](/tmp/steward-component-ablation-C9d9Wc/repair-extension/runs/20260912-222036/results.json)、[独立评审](/tmp/steward-component-ablation-C9d9Wc/repair-extension/runs/20260912-222036/semantic-reviews.json)。
- [原生并行补验](/tmp/steward-component-ablation-C9d9Wc/runs/20260912-220333/native-parallel-forward-test.json)。
- 每个 trial 保留具体请求、命令事件、最终回答、工作区和试验前后包指纹。临时试验装置与记录不属于发布插件组件。
