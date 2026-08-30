"""Regression tests for the draft-consensus-goal handoff contract."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILL = PLUGIN_ROOT / "skills" / "draft-consensus-goal" / "SKILL.md"
AGENT = PLUGIN_ROOT / "skills" / "draft-consensus-goal" / "agents" / "openai.yaml"
AUTHORING = PLUGIN_ROOT / "references" / "goal-authoring.md"
HANDOFF = PLUGIN_ROOT / "references" / "handoff-file.md"
GOAL_SCHEMA = PLUGIN_ROOT / "references" / "goal-contract-v1.schema.json"
GOAL_TEMPLATE = PLUGIN_ROOT / "references" / "goal-template.txt"
README = PLUGIN_ROOT / "README.md"
CODEX_MANIFEST = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
CLAUDE_MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"


class GoalHandoffContractTests(unittest.TestCase):
    def test_every_goal_requires_exactly_one_handoff(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        authoring = AUTHORING.read_text(encoding="utf-8")
        handoff = HANDOFF.read_text(encoding="utf-8")

        self.assertIn("always create one project-local handoff", skill)
        self.assertIn("one\nhandoff for every delivered GOAL", skill)
        self.assertIn("For every GOAL", authoring)
        self.assertIn("prepare\nexactly one handoff", authoring)
        self.assertIn("每次起草 GOAL 都必须在交付前创建且只创建一份交接文件", handoff)
        self.assertIn("用户是否另行要求文件都不参与创建判断", handoff)

    def test_handoff_failure_always_blocks_goal_delivery(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        authoring = AUTHORING.read_text(encoding="utf-8")
        handoff = HANDOFF.read_text(encoding="utf-8")

        self.assertIn("handoff creation blocks", skill)
        self.assertIn("successful handoff creation\nis always required", authoring)
        self.assertIn("落点、校验或写盘失败也阻塞 GOAL 交付", handoff)
        self.assertIn("不存在退回纯内联 GOAL 的分支", handoff)

    def test_handoff_always_has_verified_source_content(self) -> None:
        authoring = AUTHORING.read_text(encoding="utf-8")
        handoff = HANDOFF.read_text(encoding="utf-8")

        self.assertIn("current request or later accepted decisions as provenance", authoring)
        self.assertIn("不得创建空文件，也不得虚构背景", handoff)
        self.assertIn("当前用户请求和后来明确接受的决定", handoff)
        self.assertIn("文件必须至少包含一项已核实来源或合格背景", handoff)
        self.assertIn("排除不合格内容后为空就阻塞", handoff)

    def test_the_seven_line_goal_remains_the_authority_boundary(self) -> None:
        handoff = HANDOFF.read_text(encoding="utf-8")
        template = GOAL_TEMPLATE.read_text(encoding="utf-8")
        schema = json.loads(GOAL_SCHEMA.read_text(encoding="utf-8"))

        self.assertEqual(7, len(template.splitlines()))
        self.assertEqual(4000, schema["properties"]["objective"]["maxLength"])
        self.assertIn("七行 GOAL 正文始终是边界事实源", handoff)
        for field in (
            "结果",
            "范围",
            "约束与授权",
            "完成标准",
            "正当阻塞项",
            "最终交付",
        ):
            self.assertIn(field, handoff)
        self.assertIn("不写授权、停止或完成判定的措辞", handoff)
        self.assertIn("不写 `C*` 编号", handoff)

    def test_location_validation_write_order_ignore_and_rollback_remain_required(
        self,
    ) -> None:
        handoff = HANDOFF.read_text(encoding="utf-8")

        self.assertIn("校验通过之后才开始写盘", handoff)
        for command in (
            'git -C "<target-worktree-root>" rev-parse --show-toplevel',
            'git -C "<target-worktree-root>" ls-files --error-unmatch',
            'git -C "<target-worktree-root>" check-ignore -q',
        ):
            self.assertIn(command, handoff)
        self.assertIn('worktree_binding.py" verify-view', handoff)
        self.assertIn("同一 Git 仓库的 sibling worktree", handoff)
        self.assertIn("内容恰为一行 `*`", handoff)
        self.assertIn("1 是唯一可恢复结果", handoff)
        self.assertIn("符号链接或其他类型不通过", handoff)
        self.assertIn("截取前 64 个字符", handoff)
        self.assertIn("结果为空时使用 `goal-context`", handoff)
        self.assertIn("内新建缺少的 `.steward`", handoff)
        self.assertIn("写盘任一步失败时", handoff)
        self.assertIn("先回滚本轮已新建且内容仍未变", handoff)
        self.assertIn("本轮新建且仍为空的目录", handoff)
        self.assertIn("撤回候选 GOAL 的引用句", handoff)
        self.assertIn("把外移背景恢复到内存", handoff)
        self.assertIn("带着悬空引用交付比没有附件更糟", handoff)

    def test_handoff_ignore_rule_does_not_hide_sibling_control_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(
                ["git", "init", "-q", str(root)],
                check=True,
                capture_output=True,
                text=True,
            )
            handoffs = root / ".steward" / "handoffs"
            handoffs.mkdir(parents=True)
            (handoffs / ".gitignore").write_text("*\n", encoding="utf-8")
            (handoffs / "context.md").write_text(
                "verified background\n", encoding="utf-8"
            )
            sibling = root / ".steward" / "invariants.json"
            sibling.write_text("{}\n", encoding="utf-8")

            status = subprocess.run(
                ["git", "-C", str(root), "status", "--short", "--untracked-files=all"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertNotIn("handoffs", status)
            self.assertIn("?? .steward/invariants.json", status)

    def test_public_prompts_do_not_reintroduce_the_old_length_gate(self) -> None:
        agent = AGENT.read_text(encoding="utf-8")
        readme = README.read_text(encoding="utf-8")
        manifest = json.loads(CODEX_MANIFEST.read_text(encoding="utf-8"))
        default_prompt = manifest["interface"]["defaultPrompt"][0]
        combined = f"{agent}\n{readme}\n{default_prompt}"

        self.assertIn("主会话已解析的唯一目标 worktree 根", agent)
        self.assertIn("不要读取宿主 Goal 或执行状态", agent)
        self.assertIn("主会话已解析的唯一目标 worktree 根", default_prompt)
        self.assertIn("必建交接文档", default_prompt)
        for obsolete in (
            "仅在超限或明确要求时",
            "仅在超长或明确要求时",
            "除超限或我明确要求外不要创建",
            "才在 `.steward/handoffs/` 下创建",
            "仅在普通压缩后正文仍超过",
        ):
            self.assertNotIn(obsolete, combined)

    def test_only_the_goal_authoring_skill_owns_this_channel(self) -> None:
        owners = []
        for path in sorted((PLUGIN_ROOT / "skills").glob("*/SKILL.md")):
            if "../../references/goal-authoring.md" in path.read_text(encoding="utf-8"):
                owners.append(path.parent.name)
        self.assertEqual(["draft-consensus-goal"], owners)

        manifest = json.loads(CODEX_MANIFEST.read_text(encoding="utf-8"))
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        claude_manifest = json.loads(CLAUDE_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], claude_manifest["version"])


if __name__ == "__main__":
    unittest.main()
