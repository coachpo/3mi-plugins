# 3mi-plugins

CoachPo 的 Codex 与 Claude Code 插件市场。各插件的适用宿主见下表。

## 插件市场

- Marketplace ID：`coachpo`
- 显示名称：`CoachPo`
- 仓库：`github.com/coachpo/3mi-plugins`

| Plugin | 宿主 | 简介 |
| --- | --- | --- |
| [`repo-craft`](plugins/repo-craft/README.md) | Codex、Claude Code | 润色提示词、并行调查仓库、维护固定文档结构和项目规则、管理项目约束。 |

各技能的[调用示例](plugins/repo-craft/README.md#调用示例)和[调用策略与边界](plugins/repo-craft/README.md#调用策略与边界)见插件文档。各技能可按任务独立使用。

## Codex 安装

```bash
codex plugin marketplace add coachpo/3mi-plugins --ref main
codex plugin add repo-craft@coachpo
```

调用技能：

```text
$repo-craft:<skill-name>
```

## Claude Code 安装

```bash
claude plugin marketplace add coachpo/3mi-plugins@main
claude plugin install repo-craft@coachpo
```

调用技能：

```text
/repo-craft:<skill-name>
```

安装或更新后，新建 Codex 任务或 Claude Code 会话以加载当前技能。

## 许可证

Repo Craft 与仓库整合内容按 [`MIT`](LICENSE) 许可证发布。
