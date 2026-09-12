from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1] / "skills" / "write-project-docs"
SCRIPTS = SKILL_ROOT / "scripts"
START_MARKER = "<!-- write-project-docs:development-source-size:start -->"
END_MARKER = "<!-- write-project-docs:development-source-size:end -->"
FOREIGN_BLOCK = "<!-- another-skill:start -->\nKeep this rule.\n<!-- another-skill:end -->\n"


class ScopedProjectDocsTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def fixture(self, name: str, language: str = "en") -> tuple[Path, Path, Path]:
        root = self.root / name
        docs = root / "docs"
        docs.mkdir(parents=True)
        if language == "en":
            development = docs / "development-rules.md"
            source_policy = docs / "source-code-size-and-responsibility-rules.md"
            title = "# Development Rules"
            block_title = "## General Size and Responsibility Rules"
        else:
            development = docs / "开发规范.md"
            source_policy = docs / "源代码规模与职责规则.md"
            title = "# 开发规范"
            block_title = "## 通用规模与职责规则"
        development.write_text(
            f"{title}\n\n{START_MARKER}\n{block_title}\n\n"
            f"Use [the policy](old-policy.md).\n{END_MARKER}\n"
            "## Project Constraints\n\nPreserve public request formats.\n\n"
            + FOREIGN_BLOCK,
            encoding="utf-8",
        )
        source_policy.write_text(
            "# Source Responsibility Policy\n\nSeparate unrelated responsibilities.\n",
            encoding="utf-8",
        )
        return root, development, source_policy

    def run_script(self, name: str, root: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / name), str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def files(self, root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }

    def test_repair_with_only_development_rules_and_linked_policy(self) -> None:
        for language in ("en", "zh"):
            with self.subTest(language=language):
                root, development, source_policy = self.fixture(language, language)
                before = self.files(root)

                result = self.run_script("update_development_rules.py", root)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                updated = development.read_text(encoding="utf-8")
                links = re.findall(r"\]\(([^)]+)\)", updated)
                self.assertEqual(links, [source_policy.name])
                self.assertTrue((development.parent / links[0]).is_file())
                self.assertIn("Preserve public request formats.", updated)
                self.assertIn(FOREIGN_BLOCK, updated)
                self.assertEqual(updated.count(START_MARKER), 1)
                self.assertEqual(updated.count(END_MARKER), 1)
                before[development.relative_to(root).as_posix()] = development.read_bytes()
                self.assertEqual(self.files(root), before)

                repeated = self.run_script("update_development_rules.py", root)

                self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
                self.assertEqual(self.files(root), before)

    def test_missing_actual_dependency_fails_without_changes(self) -> None:
        for missing in ("development", "source_policy"):
            with self.subTest(missing=missing):
                root, development, source_policy = self.fixture(missing)
                path = development if missing == "development" else source_policy
                path.unlink()
                before = self.files(root)

                result = self.run_script("update_development_rules.py", root)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(path.name, result.stdout)
                self.assertEqual(self.files(root), before)

    def test_invalid_linked_policy_fails_without_changes(self) -> None:
        for kind in ("directory", "symlink", "broken_symlink"):
            with self.subTest(kind=kind):
                root, development, source_policy = self.fixture(kind)
                source_policy.unlink()
                if kind == "directory":
                    source_policy.mkdir()
                elif kind == "symlink":
                    source_policy.symlink_to(development)
                else:
                    source_policy.symlink_to(root / "missing-policy.md")
                before = self.files(root)

                result = self.run_script("update_development_rules.py", root)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(source_policy.name, result.stdout)
                self.assertEqual(self.files(root), before)

    def test_language_conflicts_still_fail_without_changes(self) -> None:
        for conflict in ("mixed", "duplicate", "explicit"):
            with self.subTest(conflict=conflict):
                root, _, _ = self.fixture(conflict)
                arguments: tuple[str, ...] = ()
                if conflict == "mixed":
                    (root / "docs" / "产品说明.md").write_text("# 产品说明\n", encoding="utf-8")
                elif conflict == "duplicate":
                    (root / "docs" / "源代码规模与职责规则.md").write_text(
                        "# 源代码规模与职责规则\n", encoding="utf-8"
                    )
                else:
                    arguments = ("--language", "zh")
                before = self.files(root)

                result = self.run_script("update_development_rules.py", root, *arguments)

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.files(root), before)

    def test_whole_set_validator_still_requires_unrelated_canonical_documents(self) -> None:
        root, _, _ = self.fixture("whole-set")
        repaired = self.run_script("update_development_rules.py", root)
        self.assertEqual(repaired.returncode, 0, repaired.stdout + repaired.stderr)
        before = self.files(root)

        result = self.run_script("validate_project_docs.py", root)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("docs/product.md", result.stdout)
        self.assertIn("docs/architecture.md", result.stdout)
        self.assertEqual(self.files(root), before)

    def test_other_updaters_keep_their_full_canonical_dependencies(self) -> None:
        for name in ("update_contributing.py", "update_agents_navigation.py"):
            with self.subTest(updater=name):
                root, _, _ = self.fixture(name)
                (root / "STATUS.md").write_text("Development Tier: MVP\n", encoding="utf-8")
                (root / "CONTRIBUTING.md").write_text("# Contributing\n", encoding="utf-8")
                (root / "AGENTS.md").write_text("# Agent Guidance\n", encoding="utf-8")
                before = self.files(root)

                result = self.run_script(name, root)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("docs/product.md", result.stdout)
                self.assertIn("docs/architecture.md", result.stdout)
                self.assertEqual(self.files(root), before)


if __name__ == "__main__":
    unittest.main()
