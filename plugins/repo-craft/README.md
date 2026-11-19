# Repo Craft

四项可分别使用的技能，面向 Codex 与 Claude Code；两个宿主读取同一份 `skills/` 目录。插件只提供技能指令、文档片段模板和一个只读调研子代理，不注册服务、钩子或凭据。

## 安装与调用

Codex：

```sh
codex plugin marketplace add coachpo/3mi-plugins --ref main
codex plugin add repo-craft@coachpo
```

Claude Code：

```sh
claude plugin marketplace add coachpo/3mi-plugins@main
claude plugin install repo-craft@coachpo
```

安装或更新后，新建 Codex 对话或 Claude Code 会话以加载技能。Codex 使用 `$repo-craft:<技能名>`，Claude Code 使用 `/repo-craft:<技能名>`。

要安装本地源码，在**包含本插件源码的市场仓库根目录**把上面的市场来源换成 `.`。市场已有同名来源时，先核对来源是否指向包含本插件的版本，勿把尚未发布的本地代码当作远程版本。

打包上，根目录的 `plugin.json` 采用 [Codex 支持的根清单与技能发现机制](https://developers.openai.com/plugins/build/plugins)，`.claude-plugin/plugin.json` 是 Claude Code 的清单；两份清单的名称、版本和描述保持一致。`skills/*/SKILL.md` 提供技能，`agents/` 提供 Claude Code 的插件子代理。

## 调用示例

| 技能 | 可以这样请求 |
| --- | --- |
| `polish-prompt` | `$repo-craft:polish-prompt 把这段初稿改成可交接的任务：“只读排查重试为何失效。”` |
| `investigate-repo` | `$repo-craft:investigate-repo 分别查明导入与导出走哪个入口，给出直接证据。` |
| `maintain-docs-and-rules` | `$repo-craft:maintain-docs-and-rules 初始化固定文档结构和项目规则，只在验证要求不同的模块下写局部规则。` |
| `constraint-manager` | `$repo-craft:constraint-manager 盘点这个项目的约束候选，先不写入。` |

## 调用策略与边界

各技能的行为、边界和授权规则以各自的 `SKILL.md` 为准：[`polish-prompt`](skills/polish-prompt/SKILL.md)、[`investigate-repo`](skills/investigate-repo/SKILL.md)、[`maintain-docs-and-rules`](skills/maintain-docs-and-rules/SKILL.md)、[`constraint-manager`](skills/constraint-manager/SKILL.md)。技能不授予额外操作权限。本节只写技能正文之外的宿主差异。

- **调用控制**：`polish-prompt` 在两个宿主都只接受主动调用。Codex 使用 `agents/openai.yaml` 的 `policy.allow_implicit_invocation: false`，Claude Code 使用 `SKILL.md` 的 `disable-model-invocation: true`；后者不替代前者。只接受通用 frontmatter 字段的校验器（如 Skill Creator 的 `quick_validate.py`）会拒绝这个字段，须另用宿主原生的加载检查确认兼容性。两个宿主的调用控制分别见 [Codex 技能配置](https://learn.chatgpt.com/docs/build-skills#optional-metadata)与 [Claude Code 技能配置](https://code.claude.com/docs/en/skills#control-who-invokes-a-skill)。
- **并行调查**：Claude Code 中文件搜索使用只有读取和搜索工具的插件子代理 `repo-craft:repo-researcher`；其他宿主使用默认 subagent，只读在那里只是提示词约束。宿主没有可用的 subagent 或用户限制了委派时，只能报告串行或部分调查。
- **模板**：`maintain-docs-and-rules` 带两份模板：[根 AGENTS.md](skills/maintain-docs-and-rules/references/AGENTS.template.md) 规定 Agent 如何操作，[CONTRIBUTING.md](skills/maintain-docs-and-rules/references/CONTRIBUTING.template.md) 说明贡献者如何实现、验证和提交变更。写入与合并按[模板合并规则](skills/maintain-docs-and-rules/references/template-merge.md)处理。

[验证记录](VERIFICATION.md)给出验证方法、已验证的行为和未验证的范围。

## 许可证

Repo Craft 按 [MIT](LICENSE) 许可证发布。
