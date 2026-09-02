# Steward

Steward 为 Codex 与 Claude Code 提供六个共享技能，组成三条彼此独立、可以按需衔接的工程工作流：

1. 维护 canonical 项目文档与 `AGENTS.md` 层级；
2. 执行只读仓库调研与变更请求分析；
3. 起草持久 GOAL，并在手动实施完成后维护可恢复的验证 campaign，完成修补、回归与 audit。

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

## 三条工作流

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

`analyze-change-request` 负责分析一项明确的软件变更请求。它按决策相关性核实仓库事实、项目实际版本的官方资料、适用约束和独立实践，输出带来源、可验收但尚未接受的候选需求。它不写文件、不生成 GOAL，也不开始实施。

```text
使用 $steward:parallel-repository-research 调研当前仓库中的实现位置、调用关系和测试覆盖，只返回可复核的仓库证据。
```

```text
使用 $steward:analyze-change-request 分析当前变更请求，输出带来源、验收标准、冲突和缺口的候选需求，不修改文件。
```

### GOAL 交付

`draft-consensus-goal` 从当前会话 cwd 绑定精确 Git worktree，并把已收敛决定保存到 `.steward/goals/<alias>/`。不可变 bundle 包含 canonical 七行中文 `goal.txt`、唯一 `context.md`、Draft 冻结的 `acceptance-plan.json` 和摘要 manifest。alias 使用小写字母、数字及单连字符；目录协议允许多个 alias，但一个 worktree 只起草一个 GOAL 是调用方约定。

用户或执行代理随后按 GOAL 实施。声明完成后，`run-closed-loop-verification` 用同一 alias 和同一物理目录验收：它把 acceptance intent 解析成不可变的精确 execution plan，捕获 Git 可见源码基线，并维护 hash-linked journal、attempt 和 artifacts。旧平铺 GOAL、context、Adapter 与 Campaign 路径完全不参与新流程。

项目源码失败只能在 repair 窗口内凭失败快照、根因位置和真实 delta 接受修补；随后先定向复测失败 case，再从 case 1 完整回归。非 repair 阶段源码漂移会阻塞并要求手动恢复。只有所有 required `C*` 获得同源最终 PASS 且 audit 当前有效时才报告完成。

```text
使用 $steward:draft-consensus-goal 在当前工作树以 goal-a 别名保存 canonical GOAL、context 和 acceptance plan；不要开始执行。
```

```text
重新使用 $steward:draft-consensus-goal 恢复 goal-a；只重放同一 worktree 中可精确恢复并重新校验的 payload，不执行 GOAL。
```

```text
使用 $steward:run-closed-loop-verification 验收当前工作树中的 goal-a；绑定其 acceptance plan，在 GOAL 范围内依据证据修补并定向复测，最后完成完整回归与 audit。
```

## 技能一览

| 技能 | 适用请求 | 主要结果 |
| --- | --- | --- |
| `write-agent-guides` | 审查或维护 `AGENTS.md` 层级 | 共享根规则、真实子树差异、可验证的导航与工程路由 |
| `write-project-docs` | 审查或维护 canonical 项目文档 | 单一事实权威、同步的索引与链接、范围内文档更新 |
| `parallel-repository-research` | 至少两个独立检索 lane 才能有效回答的仓库问题 | 主会话复核的路径或符号证据、冲突、未搜索范围和缺口 |
| `analyze-change-request` | 需要项目事实与外部证据的软件变更请求 | 带来源和验收标准、尚未接受的候选需求 |
| `draft-consensus-goal` | 已收敛讨论需要可评审或可执行合同 | alias-scoped GOAL、context、acceptance plan 与 manifest |
| `run-closed-loop-verification` | GOAL 已声称完成，需要闭环验收、修补与最终证明 | execution plan、可恢复 campaign、定向复测、完整回归和 audit |

Codex 可隐式选择 `write-agent-guides` 和 `parallel-repository-research`。`write-project-docs`、`analyze-change-request`、`draft-consensus-goal` 与 `run-closed-loop-verification` 只在明确请求相应工作流时调用。

## 工作树本地状态

Steward 的 GOAL 与验证控制产物位于当前 worktree 的 `.steward/goals/<alias>/` 中。整个 `.steward/` 由自身 ignore 规则挡在 Git 状态与源码指纹之外；bundle 绑定其创建时的精确 worktree，不支持复制、移动或重新绑定。

`.steward/` 是恢复事实源，不是普通缓存。Steward 在 GOAL 执行、阻塞、恢复、验收成功或 Git merge 后都保留它；创建新 GOAL 时使用新的 worktree。删除整个 worktree 会一并移除其中的本地控制状态。

## 权限与停止边界

- 只读调研不会运行项目代码、修改文件或连接私人账户。
- 文档技能只修改当前请求授权的项目文档或 `AGENTS.md`；不会创建或改写 `CLAUDE.md`。
- GOAL 起草只写 alias-scoped GOAL、context 和 acceptance plan，不实施源码变化。
- GOAL 验收只执行经过审查的本地 case，并只修补有证据支持且明确处于 GOAL 范围内的问题。
- execution plan 中的 executable、完整 `argv`、`cwd`、timeout、环境需求和副作用必须在执行前审查。
- 缺少可信 runner、必要平台、权限、证据或安全的本地替代时，技能报告准确 blocker 与最小下一步，不虚构命令或降低完成标准。
- 提交、推送、发布、部署、真实服务或设备访问、凭据、购买、破坏性操作及其他外部写入始终需要单独授权。

## 恢复与完成

恢复时从 cwd 重新绑定 worktree，按 alias 校验 manifest、GOAL、context、两个 plan 和 journal，再从未闭合阶段继续。持久 bundle 与 journal 是恢复和完成权威；聊天摘要不能替代精确 payload 或机器证据。

快速检查和定向复测只能证明局部反馈。最终完成要求一轮同源完整回归覆盖全部 runnable case；没有修补时完整初验即为该回归。当前 audit 验证 bundle、两个 plan、`C*` 映射、source identity、journal 与最终 artifact。

## 运行要求

- 技能脚本需要 PATH 中可用的 `python3`。
- worktree 绑定、源码观察和本地状态隔离需要 Git。
- 仅能通过 PTY 延迟输入的宿主需要 POSIX `termios` 运行内存 stdin bridge；能直接提供有限 pipe 的宿主不需要该兼容路径。
- 项目 case 使用项目已有工具与依赖；Steward 不替项目安装依赖或配置远程 runner。
- 安装后若技能入口没有出现，请新建宿主任务或会话再试。

## 许可证

Steward 按 [`MIT`](LICENSE) 许可证发布。
