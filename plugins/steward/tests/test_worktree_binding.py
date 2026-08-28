"""Behavioral tests for exact target-worktree binding."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
BINDING_SCRIPT = PLUGIN_ROOT / "scripts" / "worktree_binding.py"
GOAL_SCRIPT = PLUGIN_ROOT / "scripts" / "goal_contract.py"
DRAFT_SKILL = PLUGIN_ROOT / "skills" / "draft-consensus-goal" / "SKILL.md"
CALLER_SKILL = PLUGIN_ROOT / "skills" / "run-engineering-control-loop" / "SKILL.md"
AUTHORING_CONTRACT = PLUGIN_ROOT / "references" / "goal-authoring.md"
HANDOFF_CONTRACT = PLUGIN_ROOT / "references" / "handoff-file.md"


class TargetWorktreeBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.primary = self.root / "primary"
        self.sibling = self.root / "sibling"
        self._git("init", "-q", str(self.primary), cwd=self.root)
        self._git("config", "user.name", "Steward Tests", cwd=self.primary)
        self._git(
            "config",
            "user.email",
            "steward-tests@example.invalid",
            cwd=self.primary,
        )
        (self.primary / "tracked.txt").write_text("initial\n", encoding="utf-8")
        self._git("add", "tracked.txt", cwd=self.primary)
        self._git("commit", "-qm", "initial", cwd=self.primary)
        self._git(
            "worktree",
            "add",
            "-q",
            "-b",
            "sibling-test",
            str(self.sibling),
            cwd=self.primary,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _git(self, *arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )

    def _binding(
        self,
        *arguments: str,
        cwd: Path,
        input_text: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(BINDING_SCRIPT), *arguments],
            cwd=cwd,
            input=input_text,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def _view(self, target: Path, cwd: Path) -> tuple[str, dict[str, object]]:
        result = self._binding("view", str(target), cwd=cwd)
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout, json.loads(result.stdout)

    def test_only_the_exact_sibling_worktree_matches_the_target(self) -> None:
        primary_text, primary = self._view(self.primary, self.root)
        sibling_text, sibling = self._view(self.sibling, self.root)
        self.assertEqual(primary["gitCommonDir"], sibling["gitCommonDir"])
        self.assertNotEqual(primary["gitDir"], sibling["gitDir"])

        accepted = self._binding(
            "verify-root",
            str(self.sibling),
            str(self.sibling),
            cwd=self.primary,
        )
        rejected = self._binding(
            "verify-root",
            str(self.sibling),
            str(self.primary),
            cwd=self.primary,
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertEqual(sibling_text, accepted.stdout)
        self.assertEqual(1, rejected.returncode)
        self.assertIn("does not equal <target-worktree-root>", rejected.stderr)

        unchanged = self._binding(
            "verify-view",
            str(self.sibling),
            "-",
            cwd=self.primary,
            input_text=sibling_text,
        )
        switched = self._binding(
            "verify-view",
            str(self.primary),
            "-",
            cwd=self.sibling,
            input_text=sibling_text,
        )
        self.assertEqual(0, unchanged.returncode, unchanged.stderr)
        self.assertEqual(1, switched.returncode)
        self.assertIn("differs from the frozen target binding", switched.stderr)
        self.assertNotEqual(primary_text, sibling_text)

    def test_cwd_and_plugin_location_do_not_change_handoff_destination(self) -> None:
        from_primary, primary_view = self._view(self.sibling, self.primary)
        from_plugin, plugin_view = self._view(self.sibling, PLUGIN_ROOT)
        self.assertEqual(from_primary, from_plugin)
        self.assertEqual(primary_view, plugin_view)

        misleading_environment = os.environ.copy()
        misleading_environment["GIT_DIR"] = str(self.primary / ".git")
        misleading_environment["GIT_WORK_TREE"] = str(self.primary)
        from_misleading_environment = self._binding(
            "view",
            str(self.sibling),
            cwd=PLUGIN_ROOT,
            environment=misleading_environment,
        )
        self.assertEqual(0, from_misleading_environment.returncode)
        self.assertEqual(from_plugin, from_misleading_environment.stdout)

        target = Path(str(plugin_view["targetWorktreeRoot"]))
        handoffs = target / ".steward" / "handoffs"
        handoffs.mkdir(parents=True)
        (handoffs / ".gitignore").write_text("*\n", encoding="utf-8")
        handoff = handoffs / "context.md"
        handoff.write_text("verified sibling context\n", encoding="utf-8")

        self.assertTrue(handoff.is_file())
        self.assertFalse((self.primary / ".steward").exists())
        status = self._git("status", "--porcelain", "-uall", cwd=self.sibling).stdout
        self.assertNotIn("handoffs", status)

    def test_missing_ambiguous_and_unresolvable_targets_are_zero_write(self) -> None:
        subdirectory = self.primary / "nested"
        subdirectory.mkdir()
        cases = (
            (),
            ("view",),
            ("view", str(self.primary), str(self.sibling)),
            ("view", str(self.root / "missing")),
            ("view", "relative-worktree"),
            ("view", str(subdirectory)),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self._binding(*arguments, cwd=PLUGIN_ROOT)
                self.assertEqual(1, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertIn("ERROR WORKTREE_BINDING:", result.stderr)

        self.assertFalse((self.primary / ".steward").exists())
        self.assertFalse((self.sibling / ".steward").exists())
        skill = DRAFT_SKILL.read_text(encoding="utf-8")
        self.assertIn("blocker before delivery", skill)
        self.assertIn("do not write a handoff", skill)

    def test_full_loop_caller_passes_the_frozen_target_unchanged(self) -> None:
        caller = CALLER_SKILL.read_text(encoding="utf-8")
        authoring = AUTHORING_CONTRACT.read_text(encoding="utf-8")
        self.assertIn("Pass that exact root and frozen binding", caller)
        self.assertIn("freshly provide its current workspace", caller)
        self.assertIn("pass it the exact frozen `<target-worktree-root>`", caller)
        self.assertIn("Do not derive or replace", caller)
        self.assertIn(
            "Read every repository fact from `<target-worktree-root>`", authoring
        )
        self.assertIn("explicit\nproject-root argument", authoring)
        self.assertIn("`<current-session-worktree-root>`", authoring)

    def test_goal_keeps_only_the_project_relative_handoff_reference(self) -> None:
        relative_handoff = ".steward/handoffs/context.md"
        goal = "\n".join(
            (
                "结果：交付绑定目标工作树的合同",
                f"证据与上下文：补充背景见 {relative_handoff}",
                "范围：只处理目标工作树中的项目事实",
                "约束与授权：绝对工作树根仅用于运行时绑定",
                "完成标准：(C1) GOAL 只含项目相对 handoff 引用",
                "正当阻塞项：目标工作树绑定缺失或漂移时停止",
                "最终交付：返回规范七行 GOAL",
            )
        )
        checked = subprocess.run(
            [sys.executable, str(GOAL_SCRIPT), "view", "-"],
            input=goal,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, checked.returncode, checked.stderr)
        objective = json.loads(checked.stdout)["objective"]
        self.assertIn(relative_handoff, objective)
        self.assertNotIn(str(self.primary), objective)
        self.assertNotIn(str(self.sibling), objective)

        handoff_contract = HANDOFF_CONTRACT.read_text(encoding="utf-8")
        self.assertIn("不写入本机绝对 `<target-worktree-root>`", handoff_contract)
        self.assertIn("补充背景见 .steward/handoffs/retry-backoff.md", handoff_contract)


if __name__ == "__main__":
    unittest.main()
