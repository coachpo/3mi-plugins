# GOAL 上下文契约

每个新 GOAL 在交付前必须持久化一份且只持久化一份上下文文件。GOAL
长度、背景多少以及用户是否另行要求文件都不改变该要求。七行 GOAL 始终
自包含并独自定义结果、范围、授权、完成与停止边界；上下文只保存已核实
来源和辅助背景，不携带授权、digest 或完成判定。

## 目标与权限边界

只消费 `goal-authoring.md` 已冻结的 `<target-worktree-root>`。所有检查与
写入都针对该精确 worktree；不从插件目录、shell cwd、仓库发现结果或同仓库
sibling worktree 重新选根。实际创建前必须复验冻结绑定。

显式调用仅授权在该 worktree 的 `.steward/` 中建立根忽略规则、canonical
`goal.txt` 和一份 context。不得实施 GOAL、触碰外部状态、覆盖既有内容、
清理损坏或部分 workspace，或把同一 GOAL 写到另一个 worktree。

## 合格内容

上下文至少包含一项已核实来源或合格背景，例如当前用户请求、后来明确
接受的决定、相关项目相对文件与符号、当前行为、错误或日志、接口说明，或
规范来源。未经核实的线索、被否决或取代的决定、无来源推断以及起草过程
元信息都不写；排除这些内容后为空则阻塞交付，不虚构背景。

每个项目内来源写明项目相对路径和必要的符号或段落位置。每个外部来源写明：

- 标题；
- 规范 URL；
- 适用版本或章节；
- 核实日期；
- 与 GOAL 的关系；
- 足以支持该关系的简短摘要。

结果、范围、约束与授权、完成标准、正当阻塞项和最终交付留在 GOAL 中。
上下文不写 `C*`、验证 case ID、adapter 路径、digest，也不使用授权、停止或
完成判定措辞。执行方读不到上下文时，按 GOAL 中保留的来源自行核实，在
最终交付说明缺口，不推测文件内容。

## 唯一路径与引用

上下文路径固定为
`.steward/goal-context/<安全标识>.md`。从 `结果` 字段派生安全标识：ASCII
字母转为小写，保留 ASCII 数字，以单个连字符替换其余连续字符，去掉首尾
连字符，截取前 64 个字符后再次去掉末尾连字符；结果为空时使用
`goal-context`。文件名必须匹配小写 ASCII 字母、数字和单个连字符组成的
安全标识，不能选择后缀路径来绕过既有文件。

不得凭观察结果文字人工猜测、截短或重现该路径。构建完整 creator JSON 后，
必须先把其精确 UTF-8 字节交给 `goal_workspace.py validate-create -`；只有该
预检成功的相同字节才能进入一次性 create。若预检返回 expected path，须把
该完整项目相对路径同时写入 `证据与上下文` 引用和 `context.path`，重建
payload 后再次预检。

把该路径作为唯一 context 引用并入 `证据与上下文` 字段，不另起第八行：

```text
补充背景见 .steward/goal-context/retry-backoff.md；该文件仅作辅助上下文，执行前先读取；读不到时按本字段其余来源自行核实，不推测其内容，并在最终交付中说明
```

文件使用 UTF-8、无 BOM、仅 LF 换行并以 LF 结尾。按来源分块并标明出处，
让执行方能回到原处复核；不复制第二份 GOAL，不加授权或完成结论。

## Workspace 合同

整个 `.steward/` 是 worktree-local 运行控制目录。根
`.steward/.gitignore` 的内容必须是精确字节 `*\n`，因此 `goal.txt`、
`goal-context/` 和其他控制产物都不进入 Git status。不得修改项目根
`.gitignore`、`.git/info/exclude` 或共享 Git 配置。已有的无关、未跟踪
Steward 控制文件必须原样保留。

使用 `goal_workspace.py create <target-worktree-root> -` 和
`goal-authoring.md` 定义的严格 JSON 输入一次性创建 workspace。创建器必须：

1. 验证精确 worktree 绑定、`.steward` 未被跟踪且本流程拥有的 GOAL 路径均非符号链接；
2. 在内存中验证七行 GOAL、唯一 context 引用、context 路径与内容；
3. 建立或验证根忽略规则，创建 sole context，再把 `goal.txt` 作为完整
   workspace 标记最后写入；
4. 失败时只回滚本次新建且仍保持本次内容的文件，并由深到浅移除本次新建
   且仍为空的目录；既有或后来变化的内容不删除、不截断、不改写；
5. 对相同完整 GOAL、相同路径和相同 context 内容幂等返回；任何差异、
   tracked 路径、错误忽略规则、额外 context、损坏或部分初始化都停止。

一个 worktree 只承载一个 GOAL。执行、失败、恢复、merge、验收和 audit
期间都保留 `.steward/`；只有整个 worktree 被用户移除时才随之消失。新
GOAL 使用新 worktree，不覆盖、迁移或清理现有 workspace。
