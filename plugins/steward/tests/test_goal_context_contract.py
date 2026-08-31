"""Behavioral and structural tests for the GOAL context contract."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILL = PLUGIN_ROOT / "skills" / "draft-consensus-goal" / "SKILL.md"
AGENT = PLUGIN_ROOT / "skills" / "draft-consensus-goal" / "agents" / "openai.yaml"
AUTHORING = PLUGIN_ROOT / "references" / "goal-authoring.md"
CONTEXT = PLUGIN_ROOT / "references" / "goal-context.md"
LEGACY_CONTEXT = PLUGIN_ROOT / "references" / "handoff-file.md"
CONTROL_PLANE = PLUGIN_ROOT / "references" / "control-plane-contracts.md"
GOAL_SCHEMA = PLUGIN_ROOT / "references" / "goal-contract-v1.schema.json"
GOAL_TEMPLATE = PLUGIN_ROOT / "references" / "goal-template.txt"


class GoalContextContractTests(unittest.TestCase):
    def test_context_resource_is_renamed_and_has_one_goal_author(self) -> None:
        self.assertTrue(CONTEXT.is_file())
        self.assertFalse(LEGACY_CONTEXT.exists())

        owners = []
        for path in sorted((PLUGIN_ROOT / "skills").glob("*/SKILL.md")):
            if "../../references/goal-authoring.md" in path.read_text(encoding="utf-8"):
                owners.append(path.parent.name)
        self.assertEqual(["draft-consensus-goal"], owners)
        self.assertEqual(
            1, AUTHORING.read_text(encoding="utf-8").count("(goal-context.md)")
        )

    def test_explicit_invocation_discloses_the_write_effect(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        agent = AGENT.read_text(encoding="utf-8")

        self.assertRegex(agent, r"allow_implicit_invocation:\s*false")
        self.assertRegex(
            agent,
            r"default_prompt:.*\.steward/goal-context/.*新建.*一份",
        )
        self.assertRegex(
            skill,
            r"description:.*writes exactly one.*\.steward/goal-context/",
        )

    def test_legacy_goal_path_is_only_named_by_the_prohibition(self) -> None:
        active_contracts = (SKILL, AUTHORING, CONTEXT, CONTROL_PLANE)
        occurrences = [
            path
            for path in active_contracts
            if ".steward/handoffs/" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual([CONTEXT], occurrences)

        context = CONTEXT.read_text(encoding="utf-8")
        prohibition = context[context.index("`.steward/handoffs/`") :]
        for required_term in ("不受支持", "读取", "迁移", "写入", "删除"):
            self.assertIn(required_term, prohibition[:100])

    def test_goal_remains_self_contained_and_context_is_exactly_one(self) -> None:
        authoring = AUTHORING.read_text(encoding="utf-8")
        context = CONTEXT.read_text(encoding="utf-8")
        schema = json.loads(GOAL_SCHEMA.read_text(encoding="utf-8"))

        self.assertEqual(7, len(GOAL_TEMPLATE.read_text(encoding="utf-8").splitlines()))
        self.assertEqual(4000, schema["properties"]["objective"]["maxLength"])
        self.assertRegex(authoring, r"For every\nGOAL,.*create exactly one")
        self.assertRegex(context, r"每次起草 GOAL.*新建且只新建一份")
        self.assertIn("GOAL 始终自包含", context)
        for boundary in ("结果", "范围", "授权", "完成", "停止"):
            self.assertIn(boundary, context)

    def test_protocol_preserves_non_overwrite_validation_ignore_and_rollback(
        self,
    ) -> None:
        context = CONTEXT.read_text(encoding="utf-8")

        self.assertRegex(context, r"目标已存在时.*`-2`、`-3`.*第一个不存在")
        self.assertLess(context.index("只有候选校验通过"), context.index("才按顺序写盘"))
        self.assertIn(".steward/goal-context/.gitignore", context)
        self.assertRegex(context, r"内容恰为一行 `\*`")
        rollback = context[context.index("## 失败回滚") :]
        for required_term in ("只回滚本轮新建", "内容仍未变化", "仍为空", "不得删除"):
            self.assertIn(required_term, rollback)
        self.assertRegex(context, r"不存在退回纯内联 GOAL 的成功分支")

    def test_context_ignore_rule_does_not_hide_sibling_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(
                ["git", "init", "-q", str(root)],
                check=True,
                capture_output=True,
                text=True,
            )
            context_dir = root / ".steward" / "goal-context"
            context_dir.mkdir(parents=True)
            (context_dir / ".gitignore").write_text("*\n", encoding="utf-8")
            (context_dir / "context.md").write_text(
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
            self.assertNotIn("goal-context", status)
            self.assertIn("?? .steward/invariants.json", status)

    def test_contract_uses_only_the_new_goal_context_namespace(self) -> None:
        context = CONTEXT.read_text(encoding="utf-8")
        paths = re.findall(r"\.steward/[a-z-]+(?:/[a-z*.<>-]+)*", context)
        active_paths = [path for path in paths if path != ".steward/handoffs"]
        self.assertTrue(active_paths)
        self.assertTrue(
            all(
                path == ".steward" or path.startswith(".steward/goal-context")
                for path in active_paths
            )
        )


if __name__ == "__main__":
    unittest.main()
