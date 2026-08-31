# plugins

CoachPo 的 Codex 与 Claude Code 插件市场。两个宿主从同一个 Git 仓库安装插件，并共享插件内的技能、机器合同和项目状态约定。

## 插件市场

- Marketplace ID：`coachpo`
- 显示名称：`CoachPo`
- 仓库：`github.com/coachpo/plugins`

| Plugin | Category | 简介 |
| --- | --- | --- |
| [`steward`](plugins/steward/README.md) | Productivity | 六技能、三工作流：项目文档维护，只读调研分析，以及 GOAL 起草、手动实施后的验收与修补闭环。 |

## Steward 工作流

| 工作流 | 技能 |
| --- | --- |
| 项目文档 | `write-project-docs`、`write-agent-guides` |
| 调研分析 | `parallel-repository-research`、`analyze-change-request` |
| GOAL 交付 | `draft-consensus-goal`、`run-closed-loop-verification` |

完整用法、权限边界和 `.steward/` 工作树本地状态约定见 [Steward 文档](plugins/steward/README.md)。

## Codex 安装

```bash
codex plugin marketplace add coachpo/plugins --ref main
codex plugin add steward@coachpo
```

调用共享技能：

```text
$steward:<skill-name>
```

## Claude Code 安装

```bash
claude plugin marketplace add coachpo/plugins@main
claude plugin install steward@coachpo
```

调用共享技能：

```text
/steward:<skill-name>
```

安装或更新后，新建 Codex 任务或 Claude Code 会话以加载当前技能。

## 许可证

Steward 与仓库整合内容按 [`MIT`](LICENSE) 许可证发布。
