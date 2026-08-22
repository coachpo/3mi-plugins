from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from validate_project_docs import claude_pointer_warnings  # noqa: E402


class ClaudePointerTests(unittest.TestCase):
    """The bridge keeps AGENTS.md authoritative for both supported hosts."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")

    def write_pointer(self, text: str) -> None:
        (self.root / "CLAUDE.md").write_text(text, encoding="utf-8")

    def test_bare_pointer_passes(self) -> None:
        self.write_pointer("@AGENTS.md\n")
        self.assertEqual([], claude_pointer_warnings(self.root))

    def test_surrounding_blank_lines_are_tolerated(self) -> None:
        self.write_pointer("\n\n@AGENTS.md\n\n")
        self.assertEqual([], claude_pointer_warnings(self.root))

    def test_missing_pointer_warns(self) -> None:
        warnings = claude_pointer_warnings(self.root)
        self.assertEqual(1, len(warnings))
        self.assertIn("缺失", warnings[0])

    def test_extra_content_warns(self) -> None:
        self.write_pointer("@AGENTS.md\n\n## 额外的本地说明\n")
        warnings = claude_pointer_warnings(self.root)
        self.assertEqual(1, len(warnings))
        self.assertIn("引用行以外的内容", warnings[0])

    def test_pointer_to_other_file_warns(self) -> None:
        self.write_pointer("@README.md\n")
        warnings = claude_pointer_warnings(self.root)
        self.assertEqual(1, len(warnings))
        self.assertIn("引用行以外的内容", warnings[0])

    def test_empty_pointer_warns(self) -> None:
        self.write_pointer("")
        self.assertEqual(1, len(claude_pointer_warnings(self.root)))

    def test_non_utf8_pointer_warns(self) -> None:
        (self.root / "CLAUDE.md").write_bytes(b"\xff\xfe@AGENTS.md")
        warnings = claude_pointer_warnings(self.root)
        self.assertEqual(["根 CLAUDE.md 不是有效 UTF-8"], warnings)

    def test_symlink_to_agents_passes(self) -> None:
        (self.root / "CLAUDE.md").symlink_to("AGENTS.md")
        self.assertEqual([], claude_pointer_warnings(self.root))

    def test_broken_symlink_warns(self) -> None:
        (self.root / "CLAUDE.md").symlink_to("MISSING.md")
        self.assertEqual(
            ["根 CLAUDE.md 是失效的符号链接"],
            claude_pointer_warnings(self.root),
        )

    def test_symlink_to_wrong_target_warns(self) -> None:
        (self.root / "OTHER.md").write_text("x\n", encoding="utf-8")
        (self.root / "CLAUDE.md").symlink_to("OTHER.md")
        warnings = claude_pointer_warnings(self.root)
        self.assertEqual(
            ["根 CLAUDE.md 是符号链接，但未指向同目录 AGENTS.md"], warnings
        )

    def test_directory_pointer_warns(self) -> None:
        (self.root / "CLAUDE.md").mkdir()
        self.assertEqual(
            ["根 CLAUDE.md 不是普通文件"], claude_pointer_warnings(self.root)
        )


if __name__ == "__main__":
    unittest.main()
