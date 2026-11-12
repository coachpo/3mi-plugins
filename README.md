# 3mi-plugins

CoachPo 的 Codex 与 Claude Code 插件市场。两个宿主从同一个 Git 仓库安装插件，并共享插件内的技能。

## 插件市场

- Marketplace ID：`coachpo`
- 显示名称：`CoachPo`
- 仓库：`github.com/coachpo/3mi-plugins`

| Plugin | Category | 简介 |
| --- | --- | --- |
| [`steward`](plugins/steward/README.md) | Productivity | 仓库精简、任务指令改写、项目文档、只读调研与交付规划。 |

## Steward 工作流

Steward 的[技能用途与边界](plugins/steward/README.md#技能用途与边界)、[交付链路](plugins/steward/README.md#交付链路)、[模型分工](plugins/steward/README.md#模型分工)和[授权边界](plugins/steward/README.md#授权边界)见插件文档。各技能可按任务独立使用，不要求经过完整交付链路。

## Codex 安装

```bash
codex plugin marketplace add coachpo/3mi-plugins --ref main
codex plugin add steward@coachpo
```

调用共享技能：

```text
$steward:<skill-name>
```

## Claude Code 安装

```bash
claude plugin marketplace add coachpo/3mi-plugins@main
claude plugin install steward@coachpo
```

调用共享技能：

```text
/steward:<skill-name>
```

安装或更新后，新建 Codex 任务或 Claude Code 会话以加载当前技能。

## 许可证

Steward 与仓库整合内容按 [`MIT`](LICENSE) 许可证发布。
