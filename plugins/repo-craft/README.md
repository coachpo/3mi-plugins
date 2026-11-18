# Repo Craft

五项可分别使用的 Codex 技能。插件只提供技能指令和文档片段模板，不注册服务、钩子或凭据。Claude Code 是提示词强度建议的对象，不是本插件的安装目标。

## 安装

在**包含本插件源码的本地市场仓库根目录**，如需自行安装：

```sh
codex plugin marketplace add .
codex plugin add repo-craft@coachpo
```

安装后新建 Codex 对话，使用 `$repo-craft:<技能名>`。市场已有同名来源时，先核对来源是否指向包含本插件的版本，勿把尚未发布的本地代码当作远程版本。打包采用 [Codex 支持的根清单与技能发现机制](https://developers.openai.com/plugins/build/plugins)：`plugin.json` 标识插件，`skills/*/SKILL.md` 提供技能。

## 调用示例

| 技能 | 可以这样请求 |
| --- | --- |
| `polish-prompt` | `$repo-craft:polish-prompt 把这段初稿改成可交接的任务：“只读排查重试为何失效。”` |
| `investigate-repo` | `$repo-craft:investigate-repo 分别查明导入与导出走哪个入口，给出直接证据。` |
| `maintain-agent-rules` | `$repo-craft:maintain-agent-rules 初始化项目规则，只在验证要求不同的模块下写局部规则。` |
| `maintain-project-docs` | `$repo-craft:maintain-project-docs 初始化固定文档结构，保留现有手册。` |
| `consolidate-implementation` | `$repo-craft:consolidate-implementation 按已定方案统一到解析器 B，保留公开 CLI 参数；迁完调用方后可移除 A。本次不操作数据库。` |

提示词润色只支持主动调用；并行调查可由问题触发，也可供两个维护技能取证。宿主没有可用或获准的 subagent 时，只能报告串行或部分调查。项目规则和文档均可只审查而不写入；清零式收敛须明确请求和确认设计，不能用普通清理请求代替。技能不授予额外操作权限。

两个维护技能各自带一份模板：[根 AGENTS.md 片段](skills/maintain-agent-rules/references/AGENTS.template.md)规定 Agent 如何操作；[CONTRIBUTING.md 片段](skills/maintain-project-docs/references/CONTRIBUTING.template.md)说明贡献者如何实现、验证和提交变更。新建时只写适用且不冲突的片段；维护已有文件不自动补入默认政策。空项目初始化固定文档仍只建空占位，不填贡献模板。两份模板都不依赖用户主目录。

[验证记录](VERIFICATION.md)区分了宿主发现、隔离样例中的实际执行，以及未测试的安装后路由。
