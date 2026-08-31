"""Behavioral tests for the worktree-local Steward GOAL workspace."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "scripts"
WORKSPACE_SCRIPT = SCRIPTS / "goal_workspace.py"
sys.path.insert(0, str(SCRIPTS))
import goal_workspace


class GoalWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        self._git("init", "-q", str(self.root), cwd=Path(self.temporary.name))
        self._git("config", "user.name", "Steward Tests", cwd=self.root)
        self._git(
            "config",
            "user.email",
            "steward-tests@example.invalid",
            cwd=self.root,
        )
        (self.root / "tracked.txt").write_text("initial\n", encoding="utf-8")
        self._git("add", "tracked.txt", cwd=self.root)
        self._git("commit", "-qm", "initial", cwd=self.root)
        self.context_path = ".steward/goal-context/goal.md"
        self.objective = "\n".join(
            (
                "结果：保存可供手动执行与后续验收的 GOAL",
                f"证据与上下文：已核实背景见 {self.context_path}",
                "范围：仅建立目标 worktree 的 GOAL 控制文件",
                "约束与授权：不开始执行 GOAL",
                "完成标准：(C1) goal.txt 是规范七行合同；(C2) context 与 GOAL 引用一致",
                "正当阻塞项：目标绑定漂移或控制路径不安全时停止",
                "最终交付：持久化 GOAL 并返回相同 objective",
            )
        )
        self.context = "## 已核实来源\n\n- 当前用户请求：持久化 GOAL workspace。\n"

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

    def _input(
        self,
        *,
        objective: str | None = None,
        context: str | None = None,
        context_path: str | None = None,
    ) -> bytes:
        return json.dumps(
            {
                "objective": self.objective if objective is None else objective,
                "context": {
                    "path": self.context_path if context_path is None else context_path,
                    "content": self.context if context is None else context,
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")

    def _workspace(
        self,
        command: str,
        root: Path | None = None,
        *,
        input_bytes: bytes | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        arguments = [sys.executable, str(WORKSPACE_SCRIPT), command, str(root or self.root)]
        if command == "create":
            arguments.append("-")
        return subprocess.run(
            arguments,
            cwd=cwd or PLUGIN_ROOT,
            input=input_bytes,
            check=False,
            capture_output=True,
        )

    def test_ensure_root_self_ignores_all_controls_and_preserves_existing_files(self) -> None:
        steward = self.root / ".steward"
        steward.mkdir()
        existing = steward / "invariants.json"
        existing.write_text("{}\n", encoding="utf-8")

        result = self._workspace("ensure-root")

        self.assertEqual(0, result.returncode, result.stderr.decode())
        self.assertEqual(b"*\n", (steward / ".gitignore").read_bytes())
        self.assertEqual("{}\n", existing.read_text(encoding="utf-8"))
        self.assertEqual(
            {
                "path": ".steward",
                "schemaId": "steward.goal-workspace-root",
                "schemaVersion": 1,
            },
            json.loads(result.stdout),
        )
        status = self._git(
            "status", "--short", "--untracked-files=all", cwd=self.root
        ).stdout
        self.assertEqual("", status)

    def test_create_writes_context_then_canonical_goal_and_view_replays_it(self) -> None:
        created = self._workspace("create", input_bytes=self._input())
        viewed = self._workspace("view")

        self.assertEqual(0, created.returncode, created.stderr.decode())
        self.assertEqual(0, viewed.returncode, viewed.stderr.decode())
        self.assertEqual(created.stdout, viewed.stdout)
        value = json.loads(created.stdout)
        self.assertEqual("steward.goal-workspace", value["schemaId"])
        self.assertEqual(1, value["schemaVersion"])
        self.assertEqual(
            {
                "path": ".steward/goal.txt",
                "contractVersion": 1,
                "sha256": value["goalContract"]["sha256"],
                "objective": self.objective,
                "criteriaIds": ["C1", "C2"],
            },
            value["goalContract"],
        )
        self.assertRegex(value["goalContract"]["sha256"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual({"path": self.context_path}, value["context"])
        self.assertEqual(
            self.objective.encode("utf-8") + b"\n",
            (self.root / ".steward" / "goal.txt").read_bytes(),
        )
        self.assertEqual(
            self.context.encode("utf-8"), (self.root / self.context_path).read_bytes()
        )
        self.assertEqual(
            ["goal.md"],
            [item.name for item in (self.root / ".steward/goal-context").iterdir()],
        )
        self.assertEqual(
            "",
            self._git("status", "--short", "--untracked-files=all", cwd=self.root).stdout,
        )

    def test_identical_create_is_idempotent_and_any_difference_conflicts(self) -> None:
        first = self._workspace("create", input_bytes=self._input())
        goal_path = self.root / ".steward/goal.txt"
        context_path = self.root / self.context_path
        initial_stats = (goal_path.stat(), context_path.stat())

        second = self._workspace("create", input_bytes=self._input())
        changed_context = self._workspace(
            "create", input_bytes=self._input(context=self.context + "extra\n")
        )
        changed_goal_text = self.objective.replace("相同 objective", "同一 objective")
        changed_goal = self._workspace(
            "create", input_bytes=self._input(objective=changed_goal_text)
        )

        self.assertEqual(0, first.returncode, first.stderr.decode())
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(0, second.returncode, second.stderr.decode())
        self.assertEqual(1, changed_context.returncode)
        self.assertEqual(1, changed_goal.returncode)
        self.assertIn(b"WORKSPACE_CONFLICT", changed_context.stderr)
        self.assertIn(b"WORKSPACE_CONFLICT", changed_goal.stderr)
        final_stats = (goal_path.stat(), context_path.stat())
        self.assertEqual(
            [(item.st_ino, item.st_mtime_ns) for item in initial_stats],
            [(item.st_ino, item.st_mtime_ns) for item in final_stats],
        )
        self.assertEqual(self.objective.encode("utf-8") + b"\n", goal_path.read_bytes())
        self.assertEqual(self.context.encode("utf-8"), context_path.read_bytes())

    def test_non_ascii_result_uses_the_documented_fallback_slug(self) -> None:
        fallback_path = ".steward/goal-context/goal-context.md"
        objective = self.objective.replace(
            "结果：保存可供手动执行与后续验收的 GOAL", "结果：保存目标"
        ).replace(self.context_path, fallback_path)

        created = self._workspace(
            "create",
            input_bytes=self._input(
                objective=objective,
                context_path=fallback_path,
            ),
        )
        self.assertEqual(0, created.returncode, created.stderr)
        self.assertTrue((self.root / fallback_path).is_file())

    def test_unicode_case_mapping_does_not_create_ascii_slug_characters(self) -> None:
        fallback_path = ".steward/goal-context/goal-context.md"
        objective = self.objective.replace(
            "结果：保存可供手动执行与后续验收的 GOAL", "结果：İ"
        ).replace(self.context_path, fallback_path)

        created = self._workspace(
            "create",
            input_bytes=self._input(
                objective=objective,
                context_path=fallback_path,
            ),
        )
        self.assertEqual(0, created.returncode, created.stderr)
        self.assertTrue((self.root / fallback_path).is_file())

    def test_partial_or_noncanonical_layout_is_rejected_without_conversion(self) -> None:
        steward = self.root / ".steward"
        context_directory = steward / "goal-context"
        context_directory.mkdir(parents=True)
        (context_directory / ".gitignore").write_text("*\n", encoding="utf-8")

        result = self._workspace("create", input_bytes=self._input())

        self.assertEqual(1, result.returncode)
        self.assertIn(b"WORKSPACE_LAYOUT", result.stderr)
        self.assertFalse((steward / ".gitignore").exists())
        self.assertFalse((steward / "goal.txt").exists())
        self.assertEqual(b"*\n", (context_directory / ".gitignore").read_bytes())

    def test_invalid_input_paths_and_references_are_zero_write(self) -> None:
        invalid_paths = (
            "./.steward/goal-context/persist-goal.md",
            ".steward/goal-context/Persist-Goal.md",
            ".steward/goal-context/../persist-goal.md",
            "/.steward/goal-context/persist-goal.md",
            ".steward/goal-context/persist-goal.md",
        )
        for path in invalid_paths:
            with self.subTest(path=path):
                result = self._workspace(
                    "create", input_bytes=self._input(context_path=path)
                )
                self.assertEqual(1, result.returncode)
                self.assertIn(b"WORKSPACE_CONTEXT_PATH", result.stderr)
                self.assertFalse((self.root / ".steward").exists())

        mismatched = self._workspace(
            "create",
            input_bytes=self._input(
                objective=self.objective.replace(
                    self.context_path, "缺少项目相对 context 引用"
                )
            ),
        )
        missing = self._workspace("view")
        self.assertEqual(1, mismatched.returncode)
        self.assertIn(b"WORKSPACE_CONTEXT_REFERENCE", mismatched.stderr)
        self.assertEqual(1, missing.returncode)
        self.assertIn(b"WORKSPACE_MISSING", missing.stderr)
        self.assertFalse((self.root / ".steward").exists())

    def test_wrong_ignore_tracked_paths_and_symbolic_root_fail_closed(self) -> None:
        steward = self.root / ".steward"
        steward.mkdir()
        wrong_ignore = steward / ".gitignore"
        wrong_ignore.write_text("goal-context/\n", encoding="utf-8")
        wrong = self._workspace("create", input_bytes=self._input())
        self.assertEqual(1, wrong.returncode)
        self.assertIn(b"WORKSPACE_IGNORE", wrong.stderr)
        self.assertEqual(b"goal-context/\n", wrong_ignore.read_bytes())

        wrong_ignore.unlink()
        tracked = steward / "tracked.json"
        tracked.write_text("{}\n", encoding="utf-8")
        self._git("add", "-f", ".steward/tracked.json", cwd=self.root)
        self._git("commit", "-qm", "track control", cwd=self.root)
        tracked_result = self._workspace("create", input_bytes=self._input())
        self.assertEqual(1, tracked_result.returncode)
        self.assertIn(b"WORKSPACE_TRACKED", tracked_result.stderr)
        self.assertFalse(wrong_ignore.exists())

        other = Path(self.temporary.name) / "outside"
        other.mkdir()
        second = Path(self.temporary.name) / "symbolic-project"
        self._git("init", "-q", str(second), cwd=Path(self.temporary.name))
        (second / ".steward").symlink_to(other, target_is_directory=True)
        symbolic = self._workspace("create", second, input_bytes=self._input())
        self.assertEqual(1, symbolic.returncode)
        self.assertIn(b"WORKSPACE_PATH", symbolic.stderr)
        self.assertEqual([], list(other.iterdir()))

        third = Path(self.temporary.name) / "symbolic-control-project"
        self._git("init", "-q", str(third), cwd=Path(self.temporary.name))
        third_steward = third / ".steward"
        third_steward.mkdir()
        outside_control = third / "outside.json"
        outside_control.write_text("{}\n", encoding="utf-8")
        (third_steward / "invariants.json").symlink_to(outside_control)
        symbolic_control = self._workspace("ensure-root", third)
        self.assertEqual(1, symbolic_control.returncode)
        self.assertIn(b"WORKSPACE_PATH", symbolic_control.stderr)
        self.assertFalse((third_steward / ".gitignore").exists())

    def test_failed_final_write_rolls_back_only_this_attempt(self) -> None:
        original = goal_workspace._write_new_regular

        def fail_goal(
            path: Path,
            content: bytes,
            transaction: goal_workspace._Transaction,
        ) -> None:
            if path.name == "goal.txt":
                raise goal_workspace.GoalWorkspaceError("TEST_FAILURE", "forced")
            original(path, content, transaction)

        with (
            mock.patch.object(
                goal_workspace, "_write_new_regular", side_effect=fail_goal
            ),
            self.assertRaisesRegex(goal_workspace.GoalWorkspaceError, "TEST_FAILURE"),
        ):
            goal_workspace.create_goal_workspace(str(self.root), self._input())

        self.assertFalse((self.root / ".steward").exists())

    def test_target_sibling_isolated_and_workspace_survives_merge(self) -> None:
        sibling = Path(self.temporary.name) / "sibling"
        self._git(
            "worktree",
            "add",
            "-q",
            "-b",
            "sibling-goal",
            str(sibling),
            cwd=self.root,
        )
        created = self._workspace(
            "create", sibling, input_bytes=self._input(), cwd=self.root
        )
        self.assertEqual(0, created.returncode, created.stderr.decode())
        self.assertTrue((sibling / ".steward/goal.txt").is_file())
        self.assertFalse((self.root / ".steward").exists())

        self._git("switch", "-c", "merged-change", cwd=sibling)
        (sibling / "tracked.txt").write_text("changed\n", encoding="utf-8")
        self._git("add", "tracked.txt", cwd=sibling)
        self._git("commit", "-qm", "change tracked file", cwd=sibling)
        self._git("switch", "sibling-goal", cwd=sibling)
        self._git("merge", "--ff-only", "merged-change", cwd=sibling)

        viewed = self._workspace("view", sibling)
        self.assertEqual(0, viewed.returncode, viewed.stderr.decode())
        self.assertEqual(created.stdout, viewed.stdout)


if __name__ == "__main__":
    unittest.main()
