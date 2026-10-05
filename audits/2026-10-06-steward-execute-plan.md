# Steward execute-plan 实现与行为评估

日期：2026-10-06（Asia/Shanghai）。源码基线 `1b08f54`，Steward 包装版本由 0.15.0 升至 0.16.0。本报告记录本地实施与隔离评估的结果；该阶段没有修改安装缓存、安装插件、推送或发布，也没有读取或干预 ibkeeper 的主会话及执行 chats。后续提交与推送由用户另行授权。

## 交付内容

- [execute-plan/SKILL.md](../plugins/steward/skills/execute-plan/SKILL.md)：共享执行编排、可信起点、合同准备、三种调度方式、实际 diff 和证据验收、最终集成验证、恢复、授权提交与清理。
- [host-adapters.md](../plugins/steward/skills/execute-plan/references/host-adapters.md)：必要的 Desktop 与 CLI／Claude Code 适配；技能不提供工具，不依赖额外 MCP 服务或编排脚本。
- `execute-plan/agents/openai.yaml`：普通隐式发现，没有设置 explicit-only。
- [plan-handoff](../plugins/steward/skills/plan-handoff/SKILL.md) 和 [plan-delivery](../plugins/steward/skills/plan-delivery/SKILL.md)：新增执行编排路由，保留各自职责；standalone 串行与不执行验证的边界不限制新技能。合同结果支持授权提交或基线加保留 diff。
- 根／Steward README、两份 plugin manifest 和 Claude marketplace 说明同步新交付链路、模型优先级、授权边界与一致版本。`skills: "./skills/"` 保持原约定。

包装核对依据：[官方跨宿主包装说明](https://developers.openai.com/plugins/guides/submit-claude-plugin#review-what-openai-supports)支持保留技能及其引用材料，产品名称仅用于实际宿主特有行为；新技能核心不依赖 Claude 插件 agent。现有 Codex profile 示例按[官方配置说明](https://developers.openai.com/codex/config-advanced#profiles)核对，保持可选示例，不成为执行要求。

## 静态与包装校验

使用 `skill-creator` 的 `quick_validate.py`。默认 Python 缺少 PyYAML，第一次调用因 `ModuleNotFoundError` 未执行校验；随后仅在临时 venv 安装 PyYAML 6.0.3，使用该环境运行校验，未修改项目依赖或全局 Python。

| 检查 | 实际结果与边界 |
| --- | --- |
| `quick_validate.py` | execute-plan、plan-handoff、plan-delivery 均返回 `Skill is valid!`；检查格式，不证明行为正确 |
| UI YAML／调用策略 | 可解析，默认提示包含相应技能调用，隐式发现保持启用 |
| Manifest／marketplace | JSON 可解析，共享名称、版本 0.16.0、description、skills 入口一致；marketplace 本地路径能找到新技能 |
| 临时 ZIP 打包与解压 | 两份 manifest 均能找到解压后的共享技能目录；全部 7 项技能格式和 UI YAML 可解析，新技能引用文件随包可达 |
| 文档链接与空白 | 受影响 Markdown 本地文件链接可达，`git diff --check` 通过；新文件单独检查空白 |

## 独立前向行为评估

两个独立评估代理读取技能和引用，各自创建小型 Python 项目、已批准计划、真实 Git 基线及隔离工作树。内部执行子代理继承宿主默认模型和 effort，没有覆盖；实际模型标识未暴露，记录为 unknown。不是按技能措辞或正则打分，也没有启动可见新 chat。

调度场景包含两个独立行为、既定共享接口和一个依赖任务。执行者拥有不同源码写入责任、独立结果材料，主评估会话维护权威状态。ignored 合同和原样执行协议显式复制，真实提交、前置输出、任务修订、会话与工作树对应关系持续记录。

| 指定方式 | 实际行为 | 最终代码版本 | 主评估会话最终验证 |
| --- | --- | --- | --- |
| serial | 同一执行者与工作树依次完成 A→B→C；逐项验收后交接 | `1e1ad8ee` | 3 项测试，退出码 0 |
| parallel | A/B 同时派发到独立工作树；实际前置成果验收后执行 C | `01ede589` | 3 项测试，退出码 0 |
| mixed | A/B 独立派发；B 尚处于 active 检查点时，已验收 A 推进 C，随后 B/C 并行实现 | `4da2eebe` | 3 项测试，退出码 0 |

三模式主评估会话均重新打开实际源码、diff、命令退出码和原始输出，检查组合结果。测试覆盖规范化、空标签、负数／零排除、空集合及最终组合；最终检查后没有源码变更。串行 C 曾因补丁未落地而触发 `NotImplementedError`，同合同内修复并保留失败和成功证据。混合 C 的合同允许先验证实际 A 与既定 B 接口，B 的真实行为及整体渲染留到最终组合；替身探针被明确标为局部证据，不冒称实际 B 验收。

混合场景原始最终输出（退出码 0）：

```text
test_normalize (test_normalize.TestNormalize) ... ok
test_render (test_render.TestRender) ... ok
test_total (test_total.TestTotal) ... ok

----------------------------------------------------------------------
Ran 3 tests in 0.000s

OK

```

恢复场景含已有 A 中断 diff、B 返回的错误 `done` 声明、独立正常 C、未回交／未集成 D，以及缺失真实服务与设备条件。实际恢复复用现有工作树，没有重复创建或重复派发；B 的边界检查反证了返回声明，原结果保留，同合同返工，独立 C 继续推进。主评估会话审阅 A/B/C 实际 diff 后集成至 `8d510ba4`，未修改测试或降低验收，4 项测试及额外 UTC／组合行为探针通过。

B 原返回的实际失败输出（退出码 1）：

```text
F
======================================================================
FAIL: test_retry_boundaries (test_delivery.DeliveryTests)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/private/tmp/steward-recovery-eRiR85/wt-b/tests/test_delivery.py", line 13, in test_retry_boundaries
    self.assertEqual(delivery_action(3,3), "stop")
AssertionError: 'retry' != 'stop'
- retry
+ stop


----------------------------------------------------------------------
Ran 1 test in 0.000s

FAILED (failures=1)

```

恢复后的最终组合输出（退出码 0）：

```text
....
----------------------------------------------------------------------
Ran 4 tests in 0.000s

OK

```

## 资源保护与验收状态

三调度场景和恢复场景的已接受、已集成果均在 ignored 材料和证据保存、分支集成与干净状态核实后，通过非强制 `git worktree remove`／`git branch -d` 清理任务资源。集成工作区与分支保留。恢复场景 D 的分支、工作树、提交和 ignored capture 均保留，实际 ancestry 检查显示它未纳入集成。没有用其他成功结果为 D 提供清理许可。

恢复场景明确分别报告：A/B/C 的工程范围已验收，完整工程仍待 D；真实 courier 凭证与物理 gateway 条件缺失，产品验收待办；A/B/C Git 资源清理完成、D 保护性保留。整体计划保持 active。内部子代理完成与可见 chat 归档分别记录，未冒称实际聊天归档已执行。

原始映射、计划、源码、命令输出、diff、清理与恢复证据保留在本次本地隔离目录：

- [调度评估报告](/tmp/steward-modes-6QPIp3/report.md)，各模式的 `state.json`、`evidence/`、`recovery/` 和集成仓库。
- [恢复评估报告](/tmp/steward-recovery-eRiR85/report.md)，`recovery-inspection.json`、`integration-checks.json`、`cleanup-evidence.json`、`retained/`、集成仓库和受保护 D 工作树。

实现主会话已复核上述原始最终输出、实际组合 diff、合同与状态映射及清理证据，未观察到这些场景要求进一步修改技能规则。

## 真实局限

这是每个模式一次的合成项目实跑，不是广泛可靠性、耗时或成本证明。恢复场景的原执行者已不可用，验证了现有任务与 diff 的恢复，没有实测活进程重连。未实测原生插件安装／自动发现、CLI／Claude headless 适配、指定模型不可用、Desktop 异步可见 chat 创建及临时 ID、宿主管理可恢复工作树归档、真实会话归档、真实服务／设备、push、PR、部署或发布。上述宿主边界完成了指令与当前工具规则核对，不能据此宣称宿主生命周期已经端到端通过。没有将 ibkeeper 尚未完成的交付闭环当成本技能的实测证据。
