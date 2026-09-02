# Steward

Steward 为 Codex 与 Claude Code 提供六个共享技能，组成三条彼此独立、可以按需衔接的工程工作流：

1. 维护 canonical 项目文档与 `AGENTS.md` 层级；
2. 执行只读仓库调研与变更请求分析；
3. 起草持久 GOAL，并在手动实施完成后按 `repairPolicy` 修补、执行完整回归和 audit。

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

`draft-consensus-goal` 把已收敛的决定写成机器校验的七行中文 GOAL。调用方必须提供唯一、已解析的目标 worktree 根；技能将 canonical GOAL 保存为 `.steward/goal.txt`，并保存一份由 GOAL 引用的 `.steward/goal-context/<name>.md`。它不开始执行 GOAL。

若首次持久化在写入前因宿主 stdin transport 中断，可再次显式调用该技能，并提供同一绝对 worktree 与可读取的先前 task/session。技能恢复精确 payload 和已接受决定，重新复验绑定及 workspace 状态，再幂等重传一次；摘要不能替代 payload，partial 或冲突状态仍会停止。无法恢复精确 payload 时 replay 停止；只有从已接受决定重新完成事实核实与完整验证，才能作为 fresh authoring 继续。仅能通过 PTY 延迟注入长输入的宿主使用内置 raw-mode 内存桥，creator 本身始终从关闭的 pipe 读取。

用户或执行代理随后按 GOAL 手动完成实现。声明完成后，`run-closed-loop-verification` 从同一 worktree 的 GOAL 和 context 开始验收：缺少 adapter 时根据 `C*`、项目原生命令和可观察证据创建 adapter，缺少 campaign 时初始化一次；已有损坏、漂移或部分初始化的控制产物会使流程停止，不会被静默替换。

验收开始前冻结 `repairPolicy`：`within-goal` 允许在明确授权的 GOAL 范围内进行有证据支持的源码修补，`verify-only` 禁止源码写入。每次修补后执行定向复测；只有获得新的诊断证据或可观察进展时才继续。相同失败在没有新证据时再次出现、修补不再产生实质进展或下一步将超出 GOAL 时停止。随后执行同源完整回归和 audit；只有当前 `C*` 全部得到 required case 的最终通过证据且 `audit.ok` 时，才能报告完成。

```text
使用 $steward:draft-consensus-goal 消费主会话解析的唯一目标 worktree 根，保存 canonical GOAL 和一份 context；不要开始执行。
```

```text
重新使用 $steward:draft-consensus-goal 恢复明确引用的先前 task/session；继续绑定其中点名的同一绝对 worktree，只重放可精确恢复并重新校验的 payload，通过安全 stdin transport 完成持久化，不执行 GOAL。
```

```text
使用 $steward:run-closed-loop-verification 验收当前 worktree 中已声称完成的 .steward/goal.txt；读取 context，使用 repairPolicy=within-goal，按需创建 adapter 和 campaign，修补有进展的问题并完成完整回归与 audit。
```

## 技能一览

| 技能 | 适用请求 | 主要结果 |
| --- | --- | --- |
| `write-agent-guides` | 审查或维护 `AGENTS.md` 层级 | 共享根规则、真实子树差异、可验证的导航与工程路由 |
| `write-project-docs` | 审查或维护 canonical 项目文档 | 单一事实权威、同步的索引与链接、范围内文档更新 |
| `parallel-repository-research` | 至少两个独立检索 lane 才能有效回答的仓库问题 | 主会话复核的路径或符号证据、冲突、未搜索范围和缺口 |
| `analyze-change-request` | 需要项目事实与外部证据的软件变更请求 | 带来源和验收标准、尚未接受的候选需求 |
| `draft-consensus-goal` | 已收敛讨论需要可评审或可执行合同 | `.steward/goal.txt`、一份 goal context、同一七行 GOAL 文本 |
| `run-closed-loop-verification` | GOAL 已声称完成，需要验收、修补与最终证明 | adapter、可恢复 campaign、定向复测、完整回归和 audit |

Codex 可隐式选择 `write-agent-guides` 和 `parallel-repository-research`。`write-project-docs`、`analyze-change-request`、`draft-consensus-goal` 与 `run-closed-loop-verification` 只在明确请求相应工作流时调用。

## 工作树本地状态

Steward 的 GOAL 与验证控制产物位于目标 worktree 的 `.steward/` 中。整个目录由其自身的 ignore 规则挡在 Git 状态与项目源码指纹之外，因此不同 worktree 具有各自独立的目标、context、adapter、campaign 和证据。

`.steward/` 是恢复事实源，不是普通缓存。Steward 在 GOAL 执行、阻塞、恢复、验收成功或 Git merge 后都保留它；创建新 GOAL 时使用新的 worktree。删除整个 worktree 会一并移除其中的本地控制状态。

## 权限与停止边界

- 只读调研不会运行项目代码、修改文件或连接私人账户。
- 文档技能只修改当前请求授权的项目文档或 `AGENTS.md`；不会创建或改写 `CLAUDE.md`。
- GOAL 起草只写标准 `.steward/` GOAL 与 context，不实施源码变化。
- GOAL 验收只执行经过审查的本地 case；`within-goal` 只修补明确授权的 GOAL 范围，`verify-only` 保持源码只读。
- adapter 中的 executable、完整 `argv`、`cwd`、fixture、timeout、外部能力和副作用必须在执行前审查。
- 缺少可信 runner、必要平台、权限、证据或安全的本地替代时，技能报告准确 blocker 与最小下一步，不虚构命令或降低完成标准。
- 提交、推送、发布、部署、真实服务或设备访问、凭据、购买、破坏性操作及其他外部写入始终需要单独授权。

## 恢复与完成

恢复时重新绑定目标 worktree，校验 `.steward/goal.txt`、context、adapter 和 journal，再从第一个不完整状态继续。持久 workspace 仍是恢复与完成权威；当 workspace 尚未建立且当前用户明确引用先前 task/session 时，该来源只可用于恢复精确 authoring payload、绑定证据与已接受决定，宿主任务状态和助手摘要本身不构成权威。

快速检查和定向复测只能证明局部反馈。最终完成要求一轮独立的同源完整回归覆盖声明的 runnable case，并由当前 audit 验证 GOAL digest、`C*` 映射、source/catalog identity、journal、artifact 与最终结果保持一致。

## 运行要求

- 技能脚本需要 PATH 中可用的 `python3`。
- worktree 绑定、源码观察和本地状态隔离需要 Git。
- 仅能通过 PTY 延迟输入的宿主需要 POSIX `termios` 运行内存 stdin bridge；能直接提供有限 pipe 的宿主不需要该兼容路径。
- 项目 case 使用项目已有工具与依赖；Steward 不替项目安装依赖或配置远程 runner。
- 安装后若技能入口没有出现，请新建宿主任务或会话再试。

## 许可证

Steward 按 [`MIT`](LICENSE) 许可证发布。
