# Repo Craft

三项可分别使用的技能，面向 Codex 与 Claude Code；两个宿主读取同一份 `skills/` 目录。插件只提供技能指令、文档片段模板和一个只读调研子代理，不注册服务、钩子或凭据。

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

## 调用策略与边界

`polish-prompt` 在两个宿主都只接受主动调用：Codex 使用 `agents/openai.yaml` 的 `policy.allow_implicit_invocation: false`，Claude Code 使用 `SKILL.md` 的 `disable-model-invocation: true`。该 Claude Code 字段不替代 Codex 的调用策略；只接受通用 frontmatter 字段的校验器会拒绝它，须另用宿主原生的加载检查确认兼容性。两个宿主的调用控制分别见 [Codex 技能配置](https://learn.chatgpt.com/docs/build-skills#optional-metadata)与 [Claude Code 技能配置](https://code.claude.com/docs/en/skills#control-who-invokes-a-skill)。

并行调查可由问题触发，也可供其他技能取证。调用 `investigate-repo` 即授权范围内的只读委派，显式调用和被自动选中时相同；Claude Code 中文件搜索使用只有读取和搜索工具的插件子代理 `repo-craft:repo-researcher`，Git 历史由主 agent 自己查，其他宿主使用默认 subagent，只读在那里只是提示词约束。宿主没有可用的 subagent 或用户限制了委派时，只能报告串行或部分调查。

`maintain-docs-and-rules` 可只审查而不写入；只给出技能名、没有说是否写入时按审查处理。默认文档和规则都做，先文档后规则；请求只提其中一部分时只做那一部分。固定文档结构之外，端点表、状态机、数据格式等契约级细节写成 `docs/` 下的专题文档，按需建立、不建空占位；项目确立的产品与业务约束归贡献指南。没有证据的固定文档建为只含一行注释的占位文档。内容属于固定结构、却在固定位置之外的旧文档默认被取代：有效内容收进固定结构后删除原件，舍弃的内容在报告中逐项列出。子目录 `AGENTS.md` 只写该子树的构建、验证、生成文件处理差异，或只读父级就会违反的约束。技能不授予额外操作权限。

技能带两份模板：[根 AGENTS.md](skills/maintain-docs-and-rules/references/AGENTS.template.md) 规定 Agent 如何操作；[CONTRIBUTING.md](skills/maintain-docs-and-rules/references/CONTRIBUTING.template.md) 说明贡献者如何实现、验证和提交变更。初始化或维护时，目标缺失或为零字节就写入完整模板，空项目也不例外。非空文件按[规则](skills/maintain-docs-and-rules/references/template-merge.md)合并：等义不重复，缺失不冲突的直接补入，冲突的逐条询问是覆盖原政策还是跳过模板规则；属于另一份模板的条款，在对方文件已有后从这份文件删除。模板已有的主题，项目专有规则写在该小节的模板条款之后，不另起同主题的小节；模板条款逐字保留，一级标题可换成项目自己的标题。不按项目情况筛选模板条目。目标缺失时，用户已明确说明的项目规则取代与之矛盾的模板条款。

[验证记录](VERIFICATION.md)区分了宿主发现、隔离样例中的实际执行，Claude Code 安装后的加载与调用控制实测，以及未测试的 Codex 安装后路由。

## 许可证

Repo Craft 按 [MIT](LICENSE) 许可证发布。
