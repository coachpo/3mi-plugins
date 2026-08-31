from __future__ import annotations

import json
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def test_entrypoint_exposes_accept_goal_and_fixed_control_paths(self) -> None:
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`accept-goal`", text)
        self.assertIn(".steward/project-adapter.json", text)
        self.assertIn(".steward/verification/campaign", text)
        self.assertIn("goal_workspace.py", text)
        self.assertIn("no numeric limit", text)
        self.assertIn("fresh regression from case one", text)
        self.assertIn("final audit", text)

    def test_skill_is_explicit_only(self) -> None:
        text = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("$steward:run-closed-loop-verification", text)
        self.assertIn("allow_implicit_invocation: false", text)

    def test_templates_are_current_and_goal_only(self) -> None:
        adapter = json.loads(
            (SKILL_ROOT / "assets" / "project-adapter.template.json").read_text(
                encoding="utf-8"
            )
        )
        fix = json.loads(
            (SKILL_ROOT / "assets" / "fix-audit.template.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(2, adapter["schemaVersion"])
        self.assertEqual("..", adapter["projectRoot"])
        self.assertEqual(".steward/verification/campaign", adapter["campaignRoot"])
        self.assertEqual([".steward"], adapter["source"]["excludes"])
        self.assertIn("goalContract", adapter)
        self.assertEqual(1, fix["schemaVersion"])
        self.assertIn("sourceDelta", fix)
        self.assertIn("affectedCriteria", fix)
        self.assertIn("failedSha256", fix["rootCauseSource"])

    def test_public_cli_names_are_documented(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [SKILL_ROOT / "SKILL.md", *sorted((SKILL_ROOT / "references").glob("*.md"))]
        )
        for name in (
            "validate-adapter", "observe-source", "init", "status", "run",
            "resume", "record-fix", "retest", "audit",
        ):
            self.assertIn(name, text)


if __name__ == "__main__":
    unittest.main()
