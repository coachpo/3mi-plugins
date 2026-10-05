# plugins

CoachPo 的 Codex 与 Claude Code 插件市场。两个宿主从同一个 Git 仓库安装插件，并共享插件内的技能。

## 插件市场

- Marketplace ID：`coachpo`
- 显示名称：`CoachPo`
- 仓库：`github.com/coachpo/plugins`

| Plugin | Category | 简介 |
| --- | --- | --- |
| [`steward`](plugins/steward/README.md) | Productivity | 项目文档、只读调研、交付规划、代码级交接与计划执行。 |

## Steward 工作流

| 工作流 | 技能 |
| --- | --- |
| 调研分析 | `parallel-repository-research`、`analyze-change-request` |
| 开发规划 | `plan-delivery` |
| 代码级交接与验收 | `plan-handoff` |
| 计划执行与集成 | `execute-plan`（串行、并行或混合） |
| 项目文档 | `write-project-docs`、`write-agent-guides` |

一次代码变更可经过需求分析、交付规划（按需）、代码级交接，再由 `execute-plan` 编排执行、证据审查与最终集成验证，在已有授权内提交与清理；文档技能可单独使用。执行方式及模型／effort 优先遵循用户选择，否则采用依赖、容量和宿主／执行档位默认。Claude Code 版附带 `steward-researcher` 和 `steward-executor` 两个 agent，其他宿主使用实际可用执行者。各步交接物、模型分工、完整用法和权限边界见 [Steward 文档](plugins/steward/README.md)。

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
