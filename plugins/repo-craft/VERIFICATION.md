# 验证记录

## 0.2.0 · 双宿主与技能调整 · 2026-11-19

本版删除了 `consolidate-implementation`，新增 `simplify-repo`、`simplify-interface-text` 和 Claude Code 子代理 `repo-researcher`，改动了其余四个技能和根规则模板的“操作授权”“环境与数据操作”“凭据处理”三节，并加入 Claude Code 清单和市场条目。只做了打包与宿主发现层面的检查，没有重跑任何行为试验。

已验证：

- 两份市场清单和两份插件清单均可解析。根 `plugin.json` 的顶层字段、必填项、名称格式、`author` 字段和 `extensions` 结构逐项对照 Agent Plugins 1.0.0 schema 相符；两份插件清单的名称、版本、描述和元数据逐字段相同。
- Claude Code 2.1.322 的 `claude plugin validate plugins/repo-craft` 和 `claude plugin validate .` 均通过。前者报一条 `ICON_MISSING` 警告：目录图标只接受 PNG 或 JPEG，包内的 SVG 不被采用。
- Codex CLI 0.167.0 在空白的临时 `CODEX_HOME` 下执行 `codex plugin marketplace add <仓库根目录>` 后，`codex plugin list` 只列出未安装的 `repo-craft@coachpo`。这是宿主发现验证，不是安装后执行。
- Skill Creator 的 `python3 -B quick_validate.py <技能目录>`：`investigate-repo`、`maintain-agent-rules`、`maintain-project-docs` 通过。
- 六个 `SKILL.md` 和子代理文件的 frontmatter 可解析，名称与目录或文件名一致；三份 `agents/openai.yaml` 均解析为 `allow_implicit_invocation: false`。
- 包内文档和仓库根 README 的相对链接及锚点全部可解析。
- 一次独立的只读文本审查逐句对照了 `simplify-repo`（含两份参考）和 `simplify-interface-text` 与其英文原文，并核对了其余技能的补入条款。据此修正了一处译反的句子、一处术语和一条不完整的边界，给 `maintain-project-docs` 补上“只给技能名按审查处理”，并新增三条规则：文档侧的用户确立规则记录、新建文件时用户规则取代矛盾的模板条款、精简时保留固定结构的空占位。这是文本层面的核对，不是行为试验。

未通过：

- `polish-prompt`、`simplify-repo`、`simplify-interface-text` 的 `quick_validate.py` 以 `Unexpected key(s) in SKILL.md frontmatter: disable-model-invocation` 失败。该校验器只接受通用字段；这个字段是 Claude Code 仅显式调用所需的，保留不改。

未验证：

- 新增和改动技能的实际行为。两个新技能是英文原文的中文等义翻译，只做过上述文本核对；`polish-prompt` 的强度分档与输出格式、`investigate-repo` 的委派授权与新增边界、两个维护技能的新增条款均未做样例试验。
- 根规则模板改动后，没有重做全量写入与逐条合并样例；下文的模板记录针对的是改动前的模板。
- 安装后的行为：Claude Code 中技能加载、`disable-model-invocation` 是否生效、`repo-craft:repo-researcher` 能否被委派；Codex 加载带该 frontmatter 字段的技能和包含 `agents/` 目录的插件。

以下各节记录于 2026-11-18，其中的“五个技能”指当时的技能集合。

## 模板全量写入与逐条合并

按本地技能源码在隔离项目验证。一个项目没有目标文件，另一个已有两个零字节目标；只读审查均未写入。初始化后，两处的根规则与贡献指南分别与对应模板逐字节一致，其余四个固定文档仍为空，ADR 目录无占位文件。再次维护时文件树和内容均未变化。

非空样例中，两个技能都先补入无冲突部分，列出冲突并等待选择。逐项答复后，根规则保留禁止提交的原约定，替换快照交接政策；贡献指南采用英文提交描述但保留中文 PR 正文。两份文件中的项目专有规则未变，等义的不可逆操作确认没有重复。

## 根规则与贡献指南模板（旧版按适用条件写入）

按本地源码路径运行两个维护技能，检查隔离项目中实际生成的文件及前后差异。两项 Skill Creator 校验通过；模板可由各自的技能和插件 README 在包内找到。未安装或重新发布插件。

| 样例 | 验证结果 |
| --- | --- |
| 空仓、已有人工约定的仓库 | 只读审查没有写入。空仓初始化只产生五个零字节文件和空 ADR 目录；普通维护未填入政策。已有指南只在明确要求时增加指定条款，原有约定不变，重复采纳无差异。 |
| 有界面、使用 PR 的运营产品 | 界面文案、提交与 PR 格式、已发布迁移的保留规则只写进贡献指南；根规则写操作授权、环境与凭据边界，并链接贡献政策。普通维护未重复追加。 |
| 使用自定义 commitlint、不用 PR 的库 | 保留既定提交类型，没有套用默认类型、PR 格式、界面文案或运营背景。分别在无 Git、仅 Git、使用 PR 的样例重验根规则，只有相应工作流存在时才输出提交、推送或 PR 的专项授权条款。 |
| 有迁移和既有 PR 模板，但部署状态未知 | 贡献指南引用项目的 PR 模板，没有另写一份正文格式，也没有推断迁移可以重写。用户确认从未生产部署、无历史保留义务并明确采纳后，仅增加适用的迁移条款。 |

## 0.1.1 · Plugin Creator 格式审核

按 Plugin Creator 0.1.28 的本地插件规范检查了根清单、市场条目、技能前置字段、调用策略及包内资源路径。五个技能均通过 Skill Creator 校验。目录和输入框共用的 SVG 经 `sips` 成功渲染为 128 × 128 像素。

在隔离的离线本地市场中，Codex CLI 0.167.0 的 `plugin/list` 找到未安装的 `repo-craft@coachpo`；`plugin/read` 返回全部五个技能、顺序正确的两个示例提示，以及均指向搬移后 SVG 的两个图标路径。未测试桌面界面的实际显示或点击示例后的执行。此次只调整展示信息，未更改技能正文或策略，也未重跑下列行为试验。

## 0.1.0 · 初始验证

将插件复制到一个只含这一个插件的临时本地市场，另建相互独立的项目样例。未安装或启用插件。

### 打包与宿主发现

- 对五个技能分别运行 Skill Creator 的 `python3 -B quick_validate.py <技能目录>`，五项均通过。另行解析清单、市场条目和调用策略，检查名称与目录一致、包内相对链接可解析、无指向包外的运行资源；用 `cmp` 确认项目级模板副本与输入逐字节一致。
- 运行本机 Codex CLI 0.167.0 的 `app-server --stdio`。子进程使用空白临时用户目录，禁止联网、读取真实用户文件（CLI 程序自身除外）及写入样例区以外的文件。完成握手后，向 `plugin/list` 传入临时市场根目录和 `marketplaceKinds: ["local"]`，实际找到 `repo-craft@coachpo`。
- 用临时市场清单路径及 `pluginName: "repo-craft"` 调用 `plugin/read`：显示名为 **Repo Craft**，`installed: false`、`enabled: false`。返回的五个 `repo-craft:` 技能名和源码路径与包内五个 `SKILL.md` 一一对应。这是宿主发现验证，不是安装后执行。

### Codex 行为试验

让独立 Codex 执行者按**搬移后的技能文件路径**处理请求。写入只发生在隔离样例；复核了答复、调查证据、前后文件树和实际产物，而非匹配技能中的措辞。

| 场景 | 观察结果 |
| --- | --- |
| 润色含写文件指令、用词尚待用户决定的初稿 | 返回独立可复制的草稿、一个待确认问题和两个宿主各自的执行强度。目标目录仍为空。 |
| 并行调查宽度的导入、导出是否无损 | 调查主 agent 与一个子代理并行分查两个方向，汇总前重读四个文件。以乘 1000 后取整和固定三位小数输出给出精度损失反例，并指出合法输入精度未知。样例前后相同。 |
| 为验证入口不同的模块维护规则 | 保留根文件的人工索引约定；仅为 reader、writer 添加局部规则，各自的 `make verify-layout`、`npm run verify-wire` 实际通过。没有给共享常量目录写规则，也没有将缺少测试目录的根命令列为可用步骤。另一个样例的人工发版规则要求 `make attest`，但 Makefile 没有这个目标；执行者保留原文并提问，没有拿 `check` 或 `verify` 代替。 |
| 初始化空项目和不完整项目，再维护一次 | 空项目恰有五个零字节文件和空 ADR 目录；已有项目保留 README 原文，补入经过运行的导出示例以及指向架构、旧投影说明的入口，旧说明和代码未变。无新证据再运行，两棵文件树的路径和文件内容均未变。 |
## 未验证的范围

未在已安装插件的新桌面对话中测试 `$repo-craft:<技能名>` 路由、选择器展示或自然语言触发率。已核对润色的 `allow_implicit_invocation: false`，但按源码路径调用不等于实测安装后“仅提及不触发”。没有使用真实凭据或远程数据库。
