"""Contract tests for the persisted GOAL and its sole context."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILL = PLUGIN_ROOT / "skills" / "draft-consensus-goal" / "SKILL.md"
AGENT = PLUGIN_ROOT / "skills" / "draft-consensus-goal" / "agents" / "openai.yaml"
AUTHORING = PLUGIN_ROOT / "references" / "goal-authoring.md"
CONTEXT = PLUGIN_ROOT / "references" / "goal-context.md"
WORKSPACE_SCRIPT = PLUGIN_ROOT / "scripts" / "goal_workspace.py"
GOAL_SCHEMA = PLUGIN_ROOT / "references" / "goal-contract-v1.schema.json"
GOAL_TEMPLATE = PLUGIN_ROOT / "references" / "goal-template.txt"


class GoalContextContractTests(unittest.TestCase):
    def test_draft_skill_is_the_only_goal_author(self) -> None:
        owners = []
        for path in sorted((PLUGIN_ROOT / "skills").glob("*/SKILL.md")):
            if "../../references/goal-authoring.md" in path.read_text(encoding="utf-8"):
                owners.append(path.parent.name)
        self.assertEqual(["draft-consensus-goal"], owners)
        self.assertTrue(WORKSPACE_SCRIPT.is_file())
        self.assertEqual(
            1, AUTHORING.read_text(encoding="utf-8").count("(goal-context.md)")
        )

    def test_explicit_invocation_discloses_both_persisted_outputs(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        agent = AGENT.read_text(encoding="utf-8")

        self.assertRegex(agent, r"allow_implicit_invocation:\s*false")
        self.assertIn(".steward/", agent)
        self.assertIn("goal.txt", agent)
        self.assertIn("goal-context", agent)
        self.assertIn("do not start implementation", skill)
        self.assertIn("canonical .steward/goal.txt", skill)

    def test_goal_remains_self_contained_and_context_is_exactly_one(self) -> None:
        context = CONTEXT.read_text(encoding="utf-8")
        schema = json.loads(GOAL_SCHEMA.read_text(encoding="utf-8"))

        self.assertEqual(7, len(GOAL_TEMPLATE.read_text(encoding="utf-8").splitlines()))
        self.assertEqual(4000, schema["properties"]["objective"]["maxLength"])
        self.assertIn("一份且只持久化一份", context)
        self.assertIn("GOAL 始终", context)
        for boundary in ("结果", "范围", "授权", "完成", "停止"):
            self.assertIn(boundary, context)

    def test_context_sources_and_format_are_reviewable(self) -> None:
        context = CONTEXT.read_text(encoding="utf-8")
        for metadata in (
            "标题",
            "规范 URL",
            "适用版本或章节",
            "核实日期",
            "与 GOAL 的关系",
            "简短摘要",
        ):
            self.assertIn(metadata, context)
        self.assertIn("UTF-8", context)
        self.assertIn("无 BOM", context)
        self.assertIn("仅 LF", context)

    def test_workspace_contract_uses_one_root_self_ignore(self) -> None:
        authoring = AUTHORING.read_text(encoding="utf-8")
        context = CONTEXT.read_text(encoding="utf-8")
        combined = authoring + "\n" + context

        self.assertIn(".steward/.gitignore", combined)
        self.assertIn("exact bytes `*\\n`", authoring)
        self.assertNotIn(".steward/goal-context/.gitignore", combined)
        self.assertIn("项目根", context)
        self.assertIn(".git/info/exclude", context)
        self.assertIn("共享 Git 配置", context)

    def test_creator_input_and_output_handoff_are_explicit(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        authoring = AUTHORING.read_text(encoding="utf-8")

        self.assertIn('"objective"', authoring)
        self.assertIn('"context"', authoring)
        self.assertIn('"path"', authoring)
        self.assertIn('"content"', authoring)
        self.assertIn("goal_workspace.py\" create", authoring)
        self.assertIn("goalContract.objective", skill)
        self.assertIn("goalContract.objective", authoring)


if __name__ == "__main__":
    unittest.main()
