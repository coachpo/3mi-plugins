# Steward

Steward 为 Codex 与 Claude Code 提供七个共享技能，组成四条彼此独立、可以按需衔接的工程工作流：

1. 维护 canonical 项目文档与 `AGENTS.md` 层级；
2. 执行只读仓库调研与变更请求分析；
3. 将需求与已确认方案转为实施计划，再按需细化为待执行的 Sprint Backlog；
4. 起草持久 GOAL，并在手动实施完成后维护可恢复的验证 campaign，完成修补、回归与 audit。

两个宿主加载同一个 `skills/` 目录。仓库事实、用户已接受的决定、七行 GOAL 和工作树本地验证证据各有明确职责；技能不会把搜索结果、聊天摘要或一次测试通过直接当作完成证明。

## 安装

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

安装或更新后，新建 Codex 任务或 Claude Code 会话以加载当前技能。

调用形式：

```text
# Codex
$steward:<skill-name>

# Claude Code
/steward:<skill-name>
```

## 0.8.4 升级说明

本版精简根 `AGENTS.md` 文档导航中的重复档位政策，按相关事实与约束的核实需要限定读取范围，并允许复用本轮任务中来源未变化且仍适用的信息。

插件升级不会自动刷新下游项目中已生成的导航区块。使用新版 `validate_project_docs.py` 检查旧区块时，会报告“根 AGENTS.md 的文档区块已漂移”错误（不是警告），并返回非零退出码。对需要升级导航的项目，使用新版技能附带的 updater 同步后再验证：

```bash
python3 -B "<skill-dir>/scripts/update_agents_navigation.py" "<project-root>"
python3 -B "<skill-dir>/scripts/validate_project_docs.py" "<project-root>"
```

`<skill-dir>` 指新版 `write-project-docs` 技能目录，`<project-root>` 指目标项目根目录。updater 整块替换现有根 `AGENTS.md` 的托管文档导航，并按既有规则修正托管块外的旧规范链接；不会创建缺失的根 `AGENTS.md`。同步后检查实际 diff；validator 仍会报告项目其他文档的既有问题。

## 四条工作流

### 项目文档

先用 `write-project-docs` 维护 canonical 项目文档、索引和链接，再用 `write-agent-guides` 维护 `AGENTS.md` 层级。规范正文留在其权威文档中；根级 `AGENTS.md` 保存共享规则，子树文件只记录真实的局部差异和必要路由。

```text
使用 $steward:write-project-docs 基于仓库事实维护本次请求影响的 canonical 项目文档，并同步索引和链接。
```

```text
使用 $steward:write-agent-guides 基于仓库事实维护本次请求影响的 AGENTS.md 层级，并验证命令、链接和作用域。
```

### 调研分析

`parallel-repository-research` 负责复杂仓库问题的只读定位、架构映射、实现盘点和依赖追踪。它冻结互不重叠的检索 lane，在宿主能够机械限制 worker 为只读且无网络时并发，否则由主会话顺序执行；最终结果必须说明证据、冲突、未搜索范围和缺口。

`analyze-change-request` 负责分析一项明确的软件变更请求。它按决策相关性核实仓库事实、项目实际版本的官方资料和独立实践，必要时才纳入适用的强制性约束，输出带来源、可验收但尚未接受的候选需求。它不写文件、不生成 GOAL，也不开始实施。

```text
使用 $steward:parallel-repository-research 调研当前仓库中的实现位置、调用关系和测试覆盖，只返回可复核的仓库证据。
```

```text
使用 $steward:analyze-change-request 分析当前变更请求，输出带来源、验收标准、冲突和缺口的候选需求，不修改文件。
```

### 开发规划

[`plan-delivery`](skills/plan-delivery/SKILL.md) 提供两个可分别进入的规划阶段。实施计划围绕工作包、责任分工、依赖关系和验收标准组织内容，并维护需求范围及总体验收。角色数量不代表实际人员或并行容量。

Backlog 阶段可直接接收已有实施计划，结合优先级、容量、当前条件和迭代目标，维护任务分解、任务依赖、迭代安排及完成条件，并引用计划的范围和验收。任务以 Sprint 为主组织，工作包视图只保留追溯索引；工作包可跨 Sprint，Sprint 可包含多个工作包。容量或日期未知时提供建议顺序及成立条件。

技能支持仅创建、修订或审查实施计划，直接创建、修订或审查 Backlog，连续交付两份文档，以及授权范围内的联合修订。仅请求计划不强制生成 Backlog，审查不写文件。保存位置和格式沿用项目约定，无既有约定时默认保存到仓库根下的 `docs/planning/implementation-plan.md` 和 `docs/planning/sprint-backlog.md`，不加入 `write-project-docs` 的 canonical 文档集。

修改前读取现有两份产物及输入基线，在授权范围内同步受影响内容。执行技能的会话模型按[共享规则和检查清单](skills/plan-delivery/references/planning-rules.md)核对标识、具体交付与验收覆盖、任务或交付物级前置依赖、顺序、责任及容量。启动前置、接口协作和最终集成关系分别处理，不要求工作包汇总图绝对无环，也不按 Sprint 名称推断全局顺序。验收记录实际所需条件与预期证据，分别保留 Placeholder 和真实接入义务。

交付或联合修订两份文档时检查最终文档对；单阶段交付检查该阶段及相关已知关系。只改 Backlog 时保持主计划权威，关联文档缺失、不可读或尚未同步时明确限制。检查由模型完成，不新增文档校验脚本、解析协议、状态库或控制目录。

```text
使用 $steward:plan-delivery 将现有需求与已确认方案整理为实施计划并保存，暂不生成 Backlog。
```

```text
使用 $steward:plan-delivery 直接基于已有实施计划修订待执行的 Sprint Backlog，只修改 Backlog。
```

```text
使用 $steward:plan-delivery 交付实施计划和配套 Sprint Backlog，并联合检查两份文档。
```

```text
使用 $steward:plan-delivery 根据已确认的需求变更同步修订实施计划和 Sprint Backlog，并检查受影响的交付、依赖及验收。
```

规划产物描述后续开发工作，交付文档不表示任务已启动或完成。规划流程不实施研究工作流、进度跟踪、任务派发、开发执行或 GOAL 自动生成，也不自动调用项目文档维护流程。本地验收标签不构成 GOAL case 契约或执行授权。

### GOAL 交付

`draft-consensus-goal` 从当前会话 cwd 绑定精确 Git worktree，并把已收敛决定保存到 `.steward/goals/<alias>/`。不可变 bundle 包含 canonical 七行中文 `goal.txt`、唯一 `context.md`、Draft 冻结的 `acceptance-plan.json` 和摘要 manifest。alias 使用小写字母、数字及单连字符；目录协议允许多个 alias，但一个 worktree 只起草一个 GOAL 是调用方约定。容错只能由 Draft 事先声明：非必需 case 可携带 `onFailure: "waive-with-report"`（失败记录证据但不开修补窗口），case 副作用文件可声明进 `sourcePolicy.writable`（验证明确捕获并回滚，源码指纹排除它们）；其余全部保持严格。

用户或执行代理随后按 GOAL 实施。声明完成后，`run-closed-loop-verification` 用同一 alias 和同一物理目录验收：它把 acceptance intent 解析成不可变的精确 execution plan，捕获 Git 可见源码基线，并维护一份原子写入的 campaign 状态文件、attempt 和 artifacts。被 Draft 声明 waive 的非必需 case 失败会记录在其所属 attempt 中，并在完成报告中列为未满足的可选意图；其余失败照旧进入修补闭环。旧平铺 GOAL、context、Adapter 与 Campaign 路径完全不参与新流程。

项目源码失败只能在 repair 窗口内凭失败快照、根因位置和真实 delta 接受修补；随后只定向复测被修补的 case，换来快速反馈，其余 case 先沿用已有证据。但修补证明不了它没碰过的 case 是否还成立，所以只要这次 campaign 发生过修补，等全部失败项都解决后，收尾核验前会自动补一次针对当前基线的全量回归；这一趟如果又测出别的 case 被连带弄坏，会重新回到 `REPAIR_REQUIRED` 走同一套流程。全程零修补时不需要这一步，初次通过本身就是对最终源码的证明。一条 `advance` 会连续执行全部机械阶段（case、定向复测、按需的全量回归、内联完成检查），只在需要执行方介入或决策的停点返回：`REPAIR_REQUIRED`、`BLOCKED`（含未通过的完成检查）或 `COMPLETE`；每个阶段仍各自保存状态，中断后原地续跑。两次 `advance` 之间发生的源码改动会被记录为漂移提示并自动纳入新基线，不阻塞流程；但某个 case 在自身运行过程中修改了受保护源码，会被当作需要修补的失败处理。只有每个 case 的最新证据都满足要求、且所有 required `C*` 都有当前有效的 PASS 证据时才报告完成。

```text
使用 $steward:draft-consensus-goal 在当前工作树以 goal-a 别名保存 canonical GOAL、context 和 acceptance plan；不要开始执行。
```

```text
重新使用 $steward:draft-consensus-goal 恢复 goal-a；只重放同一 worktree 中可精确恢复并重新校验的 payload，不执行 GOAL。
```

```text
使用 $steward:run-closed-loop-verification 验收当前工作树中的 goal-a；绑定其 acceptance plan，在 GOAL 范围内依据证据修补并定向复测，完成内联的收尾核验。
```

## 技能一览

| 技能 | 适用请求 | 主要结果 |
| --- | --- | --- |
| `write-agent-guides` | 审查或维护 `AGENTS.md` 层级 | 共享根规则、真实子树差异、可验证的导航 |
| `write-project-docs` | 审查或维护 canonical 项目文档 | 单一事实权威、同步的索引与链接、范围内文档更新 |
| `parallel-repository-research` | 至少两个独立检索 lane 才能有效回答的仓库问题 | 主会话复核的路径或符号证据、冲突、未搜索范围和缺口 |
| `analyze-change-request` | 需要项目事实与外部证据的软件变更请求 | 带来源和验收标准、尚未接受的候选需求 |
| `plan-delivery` | 创建、修订或审查实施计划、Sprint Backlog 或两份文档 | 工作包、责任分工、依赖关系和验收标准，按 Sprint 组织的待执行任务，阶段或联合一致性检查 |
| `draft-consensus-goal` | 已收敛讨论需要可评审或可执行合同 | alias-scoped GOAL、context、acceptance plan 与 manifest |
| `run-closed-loop-verification` | GOAL 已声称完成，需要闭环验收、修补与最终证明 | execution plan、可恢复 campaign、定向复测、内联收尾核验 |

Codex 可隐式选择 `write-agent-guides`、`parallel-repository-research` 和 `plan-delivery`。`write-project-docs`、`analyze-change-request`、`draft-consensus-goal` 与 `run-closed-loop-verification` 只在明确请求相应工作流时调用。

## 工作树本地状态

Steward 的 GOAL 与验证控制产物位于当前 worktree 的 `.steward/goals/<alias>/` 中。整个 `.steward/` 由自身 ignore 规则挡在 Git 状态与源码指纹之外；bundle 绑定其创建时的精确 worktree，不支持复制、移动或重新绑定。

`.steward/` 是恢复事实源，不是普通缓存。Steward 在 GOAL 执行、阻塞、恢复、验收成功或 Git merge 后都保留它；创建新 GOAL 时使用新的 worktree。删除整个 worktree 会一并移除其中的本地控制状态。

## 权限与停止边界

- 只读调研不会运行项目代码、修改文件或连接私人账户。
- 文档技能只修改当前请求授权的项目文档或 `AGENTS.md`；不会创建或改写 `CLAUDE.md`。
- 开发规划只创建、修订或检查请求中的规划文档；计划内的开发、外部依赖获取和验收另行执行。
- GOAL 起草只写 alias-scoped GOAL、context 和 acceptance plan，不实施源码变化。
- GOAL 验收只执行经过审查的本地 case，并只修补有证据支持且明确处于 GOAL 范围内的问题。
- execution plan 中的 executable、完整 `argv`、`cwd`、timeout、环境需求和副作用必须在执行前审查。
- 缺少可信 runner、必要平台、权限、证据或安全的本地替代时，技能报告准确 blocker 与最小下一步，不虚构命令或降低完成标准。
- 提交、推送、发布、部署、真实服务或设备访问、凭据、购买、破坏性操作及其他外部写入始终需要单独授权。

## GOAL 恢复与完成

恢复时从 cwd 重新绑定 worktree，按 alias 校验 manifest、GOAL、context、两个 plan 和 campaign 状态文件，再从未闭合阶段继续。持久 bundle 与 campaign 状态是恢复和完成权威；聊天摘要不能替代精确 payload 或机器证据。

快速检查和定向复测只能证明局部反馈。完成检查为每个 case 取其跨 attempt 的最新证据，再校验 bundle、两个 plan、相关 artifact 与 required `C*` 映射；发生过修补的 campaign，这份"最新证据"在完成检查前已经来自同一次全量回归，不是东拼西凑的旧结果——不要求每次修补后都立刻重跑全部 case，但收尾前必须补齐这一趟。

## 运行要求

- 技能脚本需要 PATH 中可用的 `python3`。
- worktree 绑定、源码观察和本地状态隔离需要 Git。
- 仅能通过 PTY 延迟输入的宿主需要 POSIX `termios` 运行内存 stdin bridge；能直接提供有限 pipe 的宿主不需要该兼容路径。
- 项目 case 使用项目已有工具与依赖；Steward 不替项目安装依赖或配置远程 runner。
- 安装后若技能入口没有出现，请新建宿主任务或会话再试。

## 许可证

Steward 按 [`MIT`](LICENSE) 许可证发布。
