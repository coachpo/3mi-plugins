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
    def test_useful_verified_context_is_the_default_trigger(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        authoring = AUTHORING.read_text(encoding="utf-8")
        handoff = HANDOFF.read_text(encoding="utf-8")

        self.assertIn("externalize verified, eligible evidence by default", skill)
        self.assertIn("whether a handoff is default, required, or forbidden", skill)
        self.assertIn("GOAL length is not the default-creation gate", authoring)
        self.assertIn("**默认创建：**", handoff)
        self.assertIn("GOAL 是否接近 4,000 字符不参与这项判断", handoff)

    def test_over_limit_and_explicit_requests_require_the_handoff(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        authoring = AUTHORING.read_text(encoding="utf-8")
        handoff = HANDOFF.read_text(encoding="utf-8")

        self.assertIn("default, required, or forbidden", skill)
        self.assertIn("ordinarily compressed inline contract still exceeds", authoring)
        self.assertIn("user explicitly asks for a\ncontext file", authoring)
        self.assertIn("**强制创建：**", handoff)
        self.assertIn("内联正文在外移前经过普通压缩仍超过", handoff)
        self.assertIn("必须成功落盘后才能交付", handoff)
        self.assertIn("强制分支失败时交付不完整", handoff)

    def test_no_eligible_payload_means_no_file(self) -> None:
        authoring = AUTHORING.read_text(encoding="utf-8")
        handoff = HANDOFF.read_text(encoding="utf-8")

        self.assertIn("no-content branch", authoring)
        self.assertIn("没有合格内容时不得创建空文件", handoff)
        self.assertIn("不得通过复述 GOAL 凑出文件内容", handoff)
        self.assertIn("提供至少一项已核实的合格背景或撤回文件要求", handoff)
        self.assertIn("文件必须至少包含一项合格背景", handoff)
        self.assertIn("排除不合格内容后为空就不创建", handoff)

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
        self.assertIn("把引用句从“证据与上下文”撤回", handoff)
        self.assertIn("把外移的背景放回原处", handoff)
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
        self.assertIn("条件式交接文档", default_prompt)
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
