"""Release-surface contract for Steward's six-skill, three-workflow shape."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PLUGIN_ROOT.parents[1]
CODEX_MANIFEST = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
CLAUDE_MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
CLAUDE_MARKETPLACE = REPOSITORY_ROOT / ".claude-plugin" / "marketplace.json"
AGENTS_MARKETPLACE = REPOSITORY_ROOT / ".agents" / "plugins" / "marketplace.json"
PLUGIN_README = PLUGIN_ROOT / "README.md"
ROOT_README = REPOSITORY_ROOT / "README.md"

EXPECTED_SKILLS = {
    "write-agent-guides",
    "write-project-docs",
    "parallel-repository-research",
    "analyze-change-request",
    "draft-consensus-goal",
    "run-closed-loop-verification",
}
EXPECTED_KEYWORDS = [
    "agents-md",
    "claude-code",
    "codex",
    "documentation",
    "goals",
    "requirements-analysis",
    "repository-research",
    "verification",
    "workflows",
    "testing",
    "regression",
    "steward",
]
EXPECTED_DESCRIPTION = (
    "面向 Codex 与 Claude Code 的六技能工程工作流，覆盖项目文档维护、"
    "只读需求调研，以及 GOAL 起草与闭环验收。"
)
EXPECTED_POLICIES = {
    "write-agent-guides": True,
    "write-project-docs": False,
    "parallel-repository-research": True,
    "analyze-change-request": False,
    "draft-consensus-goal": False,
    "run-closed-loop-verification": False,
}


def _policy(agent: Path) -> bool:
    text = agent.read_text(encoding="utf-8")
    match = re.search(
        r"(?m)^\s*allow_implicit_invocation:\s*(true|false)\s*$",
        text,
    )
    if match is None:
        raise AssertionError(f"missing invocation policy: {agent}")
    return match.group(1) == "true"


class StewardReleaseSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.codex = json.loads(CODEX_MANIFEST.read_text(encoding="utf-8"))
        cls.claude = json.loads(CLAUDE_MANIFEST.read_text(encoding="utf-8"))
        cls.plugin_readme = PLUGIN_README.read_text(encoding="utf-8")
        cls.root_readme = ROOT_README.read_text(encoding="utf-8")
        cls.claude_marketplace = json.loads(
            CLAUDE_MARKETPLACE.read_text(encoding="utf-8")
        )
        cls.agents_marketplace = json.loads(
            AGENTS_MARKETPLACE.read_text(encoding="utf-8")
        )

    def test_exactly_six_public_skills_are_packaged(self) -> None:
        observed = {
            path.parent.name for path in (PLUGIN_ROOT / "skills").glob("*/SKILL.md")
        }
        self.assertEqual(EXPECTED_SKILLS, observed)

    def test_manifests_publish_the_same_010_release(self) -> None:
        self.assertEqual("steward", self.codex["name"])
        self.assertEqual(self.codex["name"], self.claude["name"])
        self.assertEqual("0.1.0", self.codex["version"])
        self.assertEqual(self.codex["version"], self.claude["version"])
        self.assertEqual(EXPECTED_DESCRIPTION, self.codex["description"])
        self.assertEqual(self.codex["description"], self.claude["description"])
        self.assertEqual(EXPECTED_KEYWORDS, self.codex["keywords"])
        self.assertEqual(self.codex["keywords"], self.claude["keywords"])
        self.assertEqual("./skills/", self.codex["skills"])
        self.assertEqual(self.codex["skills"], self.claude["skills"])

    def test_codex_starter_prompts_cover_three_workflows_with_ui_bounds(self) -> None:
        prompts = self.codex["interface"]["defaultPrompt"]
        self.assertEqual(3, len(prompts))
        self.assertTrue(all(isinstance(prompt, str) for prompt in prompts))
        self.assertTrue(all(0 < len(prompt) <= 128 for prompt in prompts))
        combined = "\n".join(prompts)
        for skill in EXPECTED_SKILLS:
            self.assertIn(f"$steward:{skill}", combined)

    def test_invocation_policies_match_the_public_routing_contract(self) -> None:
        observed = {
            skill: _policy(
                PLUGIN_ROOT / "skills" / skill / "agents" / "openai.yaml"
            )
            for skill in EXPECTED_SKILLS
        }
        self.assertEqual(EXPECTED_POLICIES, observed)

    def test_marketplace_entries_remain_well_formed(self) -> None:
        claude_entry = next(
            item
            for item in self.claude_marketplace["plugins"]
            if item["name"] == "steward"
        )
        self.assertEqual("./plugins/steward", claude_entry["source"])
        self.assertEqual(EXPECTED_DESCRIPTION, claude_entry["description"])

        codex_entry = next(
            item
            for item in self.agents_marketplace["plugins"]
            if item["name"] == "steward"
        )
        self.assertEqual(
            {"source": "local", "path": "./plugins/steward"},
            codex_entry["source"],
        )
        self.assertEqual(
            {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            codex_entry["policy"],
        )
        self.assertEqual("Productivity", codex_entry["category"])

    def test_docs_present_only_the_current_three_workflows(self) -> None:
        combined = "\n".join(
            (
                self.codex["description"],
                self.codex["interface"]["longDescription"],
                self.claude["description"],
                self.plugin_readme,
                self.root_readme,
            )
        )
        for skill in EXPECTED_SKILLS:
            self.assertIn(skill, combined)
        for workflow in ("项目文档", "调研分析", "GOAL 交付"):
            self.assertIn(workflow, self.plugin_readme)
            self.assertIn(workflow, self.root_readme)
        self.assertIn("整个目录", self.plugin_readme)
        self.assertIn("Git merge", self.plugin_readme)
        self.assertIn("repairPolicy", self.plugin_readme)
        self.assertIn("within-goal", self.plugin_readme)
        self.assertIn("verify-only", self.plugin_readme)


if __name__ == "__main__":
    unittest.main()
