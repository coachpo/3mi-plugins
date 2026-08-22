# plugins-codex

CoachPo 的 Codex 插件市场，从一个 GitHub 仓库统一发布和维护可复用插件。

## 插件市场

- Marketplace ID：`coachpo`
- 显示名称：`CoachPo`
- 仓库：`github.com/coachpo/plugins-codex`

| Plugin | Category | 简介 |
| --- | --- | --- |
| [`stitch-ui-ux-codex`](plugins/stitch-ui-ux-codex/README.md) | Creativity | 基于独立配置的 Google Stitch Remote MCP，提供 UI/UX 设计、评审、设计系统提取和 React 交付工作流。 |
| [`steward`](plugins/steward/README.md) | Productivity | 从自然语言项目状态与交付目的派生当前迭代策略，并以薄编排器和稳定机器契约连接 GOAL、技术栈 profiles、项目不变量、项目事实驱动的 local quick/CI full、语义风险审查、永久护栏与可恢复的同源回归审计；Claude Code 会话导入作为独立侧路。 |

## 安装

```bash
codex plugin marketplace add coachpo/plugins-codex --ref main
codex plugin add stitch-ui-ux-codex@coachpo
codex plugin add steward@coachpo
```

安装或更新后，请新建 Codex 任务以加载插件技能。

## 许可证

- Steward 与仓库整合内容：[`MIT`](LICENSE)
- Stitch UI/UX for Codex：[`Apache-2.0`](plugins/stitch-ui-ux-codex/LICENSE)，并保留其 [`NOTICE`](plugins/stitch-ui-ux-codex/NOTICE)、[`THIRD_PARTY_NOTICES.md`](plugins/stitch-ui-ux-codex/THIRD_PARTY_NOTICES.md) 和 [`UPSTREAM.md`](plugins/stitch-ui-ux-codex/UPSTREAM.md)
