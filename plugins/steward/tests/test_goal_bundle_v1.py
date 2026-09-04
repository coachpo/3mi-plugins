from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import goal_workspace  # noqa: E402  (runtime sys.path injection above)


def objective(alias: str, criteria: str = "(C1) 本地验收命令通过") -> str:
    return "\n".join(
        [
            "结果：交付经过验收的实现",
            f"证据与上下文：仓库事实；补充背景见 .steward/goals/{alias}/context.md",
            "范围：当前测试项目",
            "约束与授权：仅执行本地命令",
            "完成标准：" + criteria,
            "正当阻塞项：缺少可信运行环境",
            "最终交付：实现、验证证据和剩余风险",
        ]
    )


def plan(criteria: list[str] | None = None) -> dict:
    return {
        "schemaVersion": 1,
        "sourcePolicy": {"mode": "git-visible"},
        "cases": [
            {
                "id": "acceptance",
                "required": True,
                "platform": "any",
                "coversCriteria": criteria or ["C1"],
                "assertion": "项目原生验收命令成功并直接证明完成标准",
                "runnerHint": "运行项目现有的本地测试入口",
                "evidence": {"requiredFiles": [], "nonEmptyFiles": []},
            }
        ],
    }


def payload(alias: str, *, acceptance: dict | None = None) -> bytes:
    return json.dumps(
        {
            "objective": objective(alias),
            "context": "# 已核实背景\n\n- 当前用户请求与仓库文件。\n",
            "acceptancePlan": acceptance or plan(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


def staged_files(alias: str, *, acceptance: dict | None = None) -> dict[str, bytes]:
    """The same bundle content as payload(), laid out for the staged transport."""
    return {
        "goal.txt": (objective(alias) + "\n").encode("utf-8"),
        "context.md": "# 已核实背景\n\n- 当前用户请求与仓库文件。\n".encode(),
        "acceptance-plan.json": json.dumps(
            acceptance or plan(), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8"),
    }


def write_staging(root: Path, alias: str, **kwargs) -> Path:
    staging = root / ".staging"
    staging.mkdir(exist_ok=True)
    for name, data in staged_files(alias, **kwargs).items():
        (staging / name).write_bytes(data)
    return staging


class GoalBundleV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.name", "Goal Tests"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "config",
                "user.email",
                "goal@example.invalid",
            ],
            check=True,
        )
        (self.root / "app.py").write_text("print('ok')\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "app.py"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_create_view_list_and_idempotency(self) -> None:
        created = goal_workspace.create_goal_bundle(
            "goal-a", payload("goal-a"), self.root
        )
        self.assertEqual(".steward/goals/goal-a", created["path"])
        self.assertEqual(
            created,
            goal_workspace.create_goal_bundle("goal-a", payload("goal-a"), self.root),
        )
        self.assertEqual(created, goal_workspace.view_goal_bundle("goal-a", self.root))
        self.assertEqual(
            ["goal-a"], goal_workspace.list_goal_bundles(self.root)["aliases"]
        )
        bundle = self.root / ".steward" / "goals" / "goal-a"
        self.assertEqual(
            {"manifest.json", "goal.txt", "context.md", "acceptance-plan.json"},
            {item.name for item in bundle.iterdir()},
        )
        self.assertEqual(b"*\n", (self.root / ".steward" / ".gitignore").read_bytes())
        self.assertEqual(
            "",
            subprocess.run(
                ["git", "-C", str(self.root), "status", "--short"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout,
        )

    def test_multiple_aliases_coexist_without_global_selection(self) -> None:
        goal_workspace.create_goal_bundle("goal-a", payload("goal-a"), self.root)
        goal_workspace.create_goal_bundle("goal-b", payload("goal-b"), self.root)
        self.assertEqual(
            ["goal-a", "goal-b"], goal_workspace.list_goal_bundles(self.root)["aliases"]
        )
        self.assertEqual(
            "goal-b", goal_workspace.view_goal_bundle("goal-b", self.root)["alias"]
        )

    def test_alias_and_context_reference_are_strict(self) -> None:
        for alias in ("Goal-A", "goal_a", "goal--a", "a" * 65, "../goal"):
            with (
                self.subTest(alias=alias),
                self.assertRaises(goal_workspace.GoalWorkspaceError),
            ):
                goal_workspace.validate_create_request(
                    alias, payload("goal-a"), self.root
                )
        with self.assertRaisesRegex(goal_workspace.GoalWorkspaceError, "reference"):
            goal_workspace.validate_create_request(
                "goal-a", payload("goal-b"), self.root
            )

    def test_conflict_partial_symlink_and_tamper_fail_closed(self) -> None:
        goal_workspace.create_goal_bundle("goal-a", payload("goal-a"), self.root)
        changed = json.loads(payload("goal-a"))
        changed["context"] = "different\n"
        with self.assertRaisesRegex(goal_workspace.GoalWorkspaceError, "CONFLICT"):
            goal_workspace.create_goal_bundle(
                "goal-a", json.dumps(changed, ensure_ascii=False).encode(), self.root
            )
        context = self.root / ".steward" / "goals" / "goal-a" / "context.md"
        context.write_text("tampered\n", encoding="utf-8")
        with self.assertRaises(goal_workspace.GoalWorkspaceError):
            goal_workspace.view_goal_bundle("goal-a", self.root)

    def test_plan_requires_complete_required_coverage(self) -> None:
        bad = plan(["C1"])
        bad["cases"][0]["required"] = False
        with self.assertRaisesRegex(goal_workspace.GoalWorkspaceError, "coverage"):
            goal_workspace.validate_create_request(
                "goal-a", payload("goal-a", acceptance=bad), self.root
            )
        bad = plan(["C2"])
        with self.assertRaisesRegex(goal_workspace.GoalWorkspaceError, "unknown"):
            goal_workspace.validate_create_request(
                "goal-a", payload("goal-a", acceptance=bad), self.root
            )
        bad = plan()
        bad["cases"][0]["runnerHint"] = "replace-with-runner"
        with self.assertRaisesRegex(goal_workspace.GoalWorkspaceError, "placeholder"):
            goal_workspace.validate_create_request(
                "goal-a", payload("goal-a", acceptance=bad), self.root
            )

    def test_legacy_flat_layout_is_ignored(self) -> None:
        steward = self.root / ".steward"
        steward.mkdir()
        (steward / ".gitignore").write_bytes(b"*\n")
        (steward / "goal.txt").write_text("malformed legacy", encoding="utf-8")
        (steward / "goal-context").mkdir()
        (steward / "project-adapter.json").write_text("not json", encoding="utf-8")
        goal_workspace.create_goal_bundle("goal-a", payload("goal-a"), self.root)
        self.assertEqual(
            "goal-a", goal_workspace.view_goal_bundle("goal-a", self.root)["alias"]
        )

    def test_nested_cwd_resolves_the_same_worktree(self) -> None:
        nested = self.root / "src" / "nested"
        nested.mkdir(parents=True)
        goal_workspace.create_goal_bundle("goal-a", payload("goal-a"), nested)
        self.assertEqual(
            str(self.root.resolve()),
            goal_workspace.view_goal_bundle("goal-a", nested)["worktreeBinding"][
                "targetWorktreeRoot"
            ],
        )

    def test_linked_worktree_gets_its_own_exact_binding(self) -> None:
        linked = self.root.parent / f"{self.root.name}-linked"
        try:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.root),
                    "worktree",
                    "add",
                    "-q",
                    "-b",
                    "linked-goal-test",
                    str(linked),
                ],
                check=True,
            )
            goal_workspace.create_goal_bundle("goal-a", payload("goal-a"), linked)
            view = goal_workspace.view_goal_bundle("goal-a", linked)
            self.assertEqual(
                str(linked.resolve()), view["worktreeBinding"]["targetWorktreeRoot"]
            )
            with self.assertRaises(goal_workspace.GoalWorkspaceError):
                goal_workspace.view_goal_bundle("goal-a", self.root)
        finally:
            if linked.exists():
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(self.root),
                        "worktree",
                        "remove",
                        "--force",
                        str(linked),
                    ],
                    check=False,
                )

    def test_public_cli_uses_current_worktree_and_structured_stdin(self) -> None:
        script = SCRIPTS / "goal_workspace.py"
        preflight = subprocess.run(
            [
                sys.executable,
                "-B",
                str(script),
                "validate-create",
                "--goal",
                "goal-a",
                "-",
            ],
            cwd=self.root,
            input=payload("goal-a"),
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, preflight.returncode, preflight.stderr.decode())
        created = subprocess.run(
            [sys.executable, "-B", str(script), "create", "--goal", "goal-a", "-"],
            cwd=self.root,
            input=payload("goal-a"),
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, created.returncode, created.stderr.decode())
        self.assertEqual("goal-a", json.loads(created.stdout)["alias"])

    def test_create_from_staged_files_matches_json_transport(self) -> None:
        staging = write_staging(self.root, "goal-a")
        from_staged = goal_workspace.create_goal_bundle("goal-a", staging, self.root)
        shutil.rmtree(self.root / ".steward")
        from_json = goal_workspace.create_goal_bundle(
            "goal-a", payload("goal-a"), self.root
        )
        self.assertEqual(from_json, from_staged)

    def test_staged_create_is_idempotent_and_conflict_checked(self) -> None:
        staging = write_staging(self.root, "goal-a")
        first = goal_workspace.create_goal_bundle("goal-a", staging, self.root)
        self.assertEqual(
            first, goal_workspace.create_goal_bundle("goal-a", staging, self.root)
        )
        (staging / "context.md").write_bytes(b"different\n")
        with self.assertRaisesRegex(goal_workspace.GoalWorkspaceError, "CONFLICT"):
            goal_workspace.create_goal_bundle("goal-a", staging, self.root)

    def test_staged_create_validates_the_file_contract(self) -> None:
        staging = write_staging(self.root, "goal-a")
        (staging / "context.md").unlink()
        with self.assertRaisesRegex(goal_workspace.GoalWorkspaceError, "missing"):
            goal_workspace.validate_create_request("goal-a", staging, self.root)
        (staging / "context.md").write_bytes("# 无结尾 LF".encode())
        with self.assertRaisesRegex(goal_workspace.GoalWorkspaceError, "final LF"):
            goal_workspace.validate_create_request("goal-a", staging, self.root)
        (staging / "context.md").unlink()
        (staging / "context.md").symlink_to(self.root / "app.py")
        with self.assertRaises(goal_workspace.GoalWorkspaceError):
            goal_workspace.validate_create_request("goal-a", staging, self.root)

    def test_staged_goal_and_plan_stay_strict(self) -> None:
        staging = write_staging(self.root, "goal-a")
        (staging / "goal.txt").write_bytes((objective("goal-a") + "\nextra\n").encode())
        with self.assertRaises(goal_workspace.GoalWorkspaceError):
            goal_workspace.create_goal_bundle("goal-a", staging, self.root)
        (staging / "goal.txt").write_bytes((objective("goal-a") + "\n").encode())
        bad_plan = json.loads(staged_files("goal-a")["acceptance-plan.json"])
        bad_plan["cases"][0]["required"] = False
        (staging / "acceptance-plan.json").write_bytes(
            json.dumps(bad_plan, ensure_ascii=False).encode()
        )
        with self.assertRaisesRegex(goal_workspace.GoalWorkspaceError, "coverage"):
            goal_workspace.create_goal_bundle("goal-a", staging, self.root)

    def test_public_cli_create_from_staged_directory(self) -> None:
        script = SCRIPTS / "goal_workspace.py"
        staging = write_staging(self.root, "goal-a")
        preview = subprocess.run(
            [
                sys.executable,
                "-B",
                str(script),
                "validate-create-from",
                "--goal",
                "goal-a",
                str(staging),
            ],
            cwd=self.root,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, preview.returncode, preview.stderr.decode())
        self.assertEqual("goal-a", json.loads(preview.stdout)["alias"])
        self.assertFalse((self.root / ".steward" / "goals" / "goal-a").exists())
        created = subprocess.run(
            [
                sys.executable,
                "-B",
                str(script),
                "create-from",
                "--goal",
                "goal-a",
                str(staging),
            ],
            cwd=self.root,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, created.returncode, created.stderr.decode())
        self.assertEqual("goal-a", json.loads(created.stdout)["alias"])

    def test_optional_waive_and_writable_extend_v1(self) -> None:
        waived = plan()
        waived["cases"].append(
            {
                "id": "optional-probe",
                "required": False,
                "platform": "any",
                "coversCriteria": ["C1"],
                "assertion": "可选探针命令成功",
                "runnerHint": "运行可选探针入口",
                "evidence": {"requiredFiles": [], "nonEmptyFiles": []},
                "onFailure": "waive-with-report",
            }
        )
        waived["sourcePolicy"] = {
            "mode": "git-visible",
            "writable": ["reports/coverage.lcov", "note.log"],
        }
        view = goal_workspace.validate_create_request(
            "goal-a", payload("goal-a", acceptance=waived), self.root
        )
        self.assertEqual(
            ["acceptance", "optional-probe"], view["acceptancePlan"]["caseIds"]
        )
        created = goal_workspace.create_goal_bundle(
            "goal-a", payload("goal-a", acceptance=waived), self.root
        )
        self.assertEqual(
            created,
            goal_workspace.create_goal_bundle(
                "goal-a", payload("goal-a", acceptance=waived), self.root
            ),
        )

    def test_waive_is_only_valid_on_non_required_cases(self) -> None:
        bad = plan()
        bad["cases"][0]["onFailure"] = "waive-with-report"
        with self.assertRaisesRegex(goal_workspace.GoalWorkspaceError, "onFailure"):
            goal_workspace.validate_create_request(
                "goal-a", payload("goal-a", acceptance=bad), self.root
            )
        bad = plan()
        bad["cases"][0]["required"] = False
        bad["cases"].append(
            {
                "id": "optional-probe",
                "required": False,
                "platform": "any",
                "coversCriteria": ["C1"],
                "assertion": "可选探针命令成功",
                "runnerHint": "运行可选探针入口",
                "evidence": {"requiredFiles": [], "nonEmptyFiles": []},
                "onFailure": "retry-twice",
            }
        )
        with self.assertRaisesRegex(goal_workspace.GoalWorkspaceError, "onFailure"):
            goal_workspace.validate_create_request(
                "goal-a", payload("goal-a", acceptance=bad), self.root
            )

    def test_writable_paths_are_safety_checked_and_disjoint_from_files(self) -> None:
        for bad_writable in (
            ["../outside.log"],
            ["/abs/path.log"],
            [".steward/goals/x.md"],
            ["", "."],
            ["a.log", "a.log"],
        ):
            bad = plan()
            bad["sourcePolicy"] = {"mode": "git-visible", "writable": bad_writable}
            with (
                self.subTest(writable=bad_writable),
                self.assertRaises(goal_workspace.GoalWorkspaceError),
            ):
                goal_workspace.validate_create_request(
                    "goal-a", payload("goal-a", acceptance=bad), self.root
                )
        bad = plan()
        bad["sourcePolicy"] = {
            "mode": "files",
            "files": ["app.py"],
            "writable": ["app.py"],
        }
        with self.assertRaisesRegex(goal_workspace.GoalWorkspaceError, "disjoint"):
            goal_workspace.validate_create_request(
                "goal-a", payload("goal-a", acceptance=bad), self.root
            )
        good = plan()
        good["sourcePolicy"] = {
            "mode": "files",
            "files": ["app.py"],
            "writable": ["coverage.lcov"],
        }
        goal_workspace.validate_create_request(
            "goal-a", payload("goal-a", acceptance=good), self.root
        )

    def test_plans_without_new_fields_stay_byte_stable(self) -> None:
        normalized = goal_workspace.validate_acceptance_plan(plan(), ["C1"])
        self.assertEqual(
            {
                "id",
                "required",
                "platform",
                "coversCriteria",
                "assertion",
                "runnerHint",
                "evidence",
            },
            set(normalized["cases"][0]),
        )
        self.assertEqual({"mode": "git-visible"}, normalized["sourcePolicy"])
        self.assertEqual(
            goal_workspace.canonical_json_bytes(
                {
                    "schemaVersion": 1,
                    "sourcePolicy": {"mode": "git-visible"},
                    "cases": [
                        {
                            "id": "acceptance",
                            "required": True,
                            "platform": "any",
                            "coversCriteria": ["C1"],
                            "assertion": "项目原生验收命令成功并直接证明完成标准",
                            "runnerHint": "运行项目现有的本地测试入口",
                            "evidence": {"requiredFiles": [], "nonEmptyFiles": []},
                        }
                    ],
                }
            ),
            goal_workspace.canonical_json_bytes(normalized),
        )


if __name__ == "__main__":
    unittest.main()
