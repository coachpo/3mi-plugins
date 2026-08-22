# plugins-codex

CoachPo 的 Codex 与 Claude Code 插件市场。两个宿主从同一个 Git 仓库安装同一个 `steward` 插件，并共享同一套技能、机器契约和项目状态。

## 插件市场

- Marketplace ID：`coachpo`
- 显示名称：`CoachPo`
- 仓库：`github.com/coachpo/plugins-codex`

| Plugin | Category | 简介 |
| --- | --- | --- |
| [`steward`](plugins/steward/README.md) | Productivity | 面向 Coding Agent 的工程控制面，通过七个共享技能连接项目指引、文档、GOAL、语义风险、验证流水线与可恢复的工程闭环。 |

## Codex 安装

```bash
codex plugin marketplace add coachpo/plugins-codex --ref main
codex plugin add steward@coachpo
```

调用共享技能：

```text
$steward:<skill-name>
```

## Claude Code 安装

```bash
claude plugin marketplace add coachpo/plugins-codex@main
claude plugin install steward@coachpo
```

调用共享技能：

```text
/steward:<skill-name>
```

安装或更新后，请新建 Codex 任务或 Claude Code 会话以加载最新技能。

## 许可证

Steward 与仓库整合内容按 [`MIT`](LICENSE) 许可证发布。
