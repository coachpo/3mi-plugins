from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from doc_anchors import CHINESE_PROFILE  # noqa: E402
from markdown_links import (  # noqa: E402
    extract_link_targets,
    replace_visible_link_targets,
    visible_path_mentions,
)
from test_bilingual_documents import build_project  # noqa: E402


MAPPINGS = (
    ("docs/product.md", "docs/产品说明.md"),
    ("docs/architecture.md", "docs/架构说明.md"),
    ("docs/INDEX.md", "docs/README.md"),
)


class LinkTargetRewriteTests(unittest.TestCase):
    def rewrite(self, text: str) -> str:
        rewritten, _ = replace_visible_link_targets(text, MAPPINGS)
        return rewritten

    def test_rewrites_inline_and_reference_link_targets(self) -> None:
        text = (
            "[a](docs/product.md)\n"
            "[b]: docs/architecture.md\n"
            "[c](<docs/INDEX.md>)\n"
        )
        self.assertEqual(
            self.rewrite(text),
            "[a](docs/产品说明.md)\n"
            "[b]: docs/架构说明.md\n"
            "[c](<docs/README.md>)\n",
        )

    def test_preserves_dot_slash_fragment_and_query(self) -> None:
        cases = {
            "[a](./docs/product.md)": "[a](./docs/产品说明.md)",
            "[a](docs/product.md#section)": "[a](docs/产品说明.md#section)",
            "[a](docs/product.md?v=1)": "[a](docs/产品说明.md?v=1)",
            "[a](docs/product.md?v=1#section)": (
                "[a](docs/产品说明.md?v=1#section)"
            ),
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(self.rewrite(source + "\n"), expected + "\n")

    def test_leaves_prose_mentions_untouched(self) -> None:
        text = "参考上游仓库的 docs/architecture.md 与 docs/product.md。\n"
        self.assertEqual(self.rewrite(text), text)

    def test_leaves_fenced_and_html_blocks_untouched(self) -> None:
        fence = chr(96) * 3
        text = (
            fence + "text\n[a](docs/product.md)\n" + fence + "\n\n"
            "<div>\n[b](docs/product.md)\n</div>\n"
        )
        self.assertEqual(self.rewrite(text), text)

    def test_leaves_inline_code_untouched(self) -> None:
        text = (
            "示例：`[产品](docs/product.md)`；真实：[产品](docs/product.md)。\n"
            "双反引号：``[产品](docs/product.md)``。\n"
        )
        self.assertEqual(
            self.rewrite(text),
            "示例：`[产品](docs/product.md)`；真实：[产品](docs/产品说明.md)。\n"
            "双反引号：``[产品](docs/product.md)``。\n",
        )

    def test_leaves_multiline_inline_code_untouched(self) -> None:
        text = (
            "``before [产品](docs/product.md)\n"
            "after docs/product.md``\n"
            "[real](docs/product.md)\n"
        )
        self.assertEqual(
            self.rewrite(text),
            "``before [产品](docs/product.md)\n"
            "after docs/product.md``\n"
            "[real](docs/产品说明.md)\n",
        )

    def test_backslash_does_not_escape_closing_code_delimiter(self) -> None:
        text = (
            "`[fake](docs/product.md)\\`\n"
            "[real](docs/product.md)\n"
        )
        self.assertEqual(
            self.rewrite(text),
            "`[fake](docs/product.md)\\`\n"
            "[real](docs/产品说明.md)\n",
        )

    def test_code_formatted_link_label_keeps_a_real_link(self) -> None:
        text = "[`产品`](docs/product.md)\n"
        self.assertEqual(self.rewrite(text), "[`产品`](docs/产品说明.md)\n")

    def test_code_span_crossing_target_is_not_a_real_link(self) -> None:
        text = (
            "[foo `bar](docs/product.md)`\n"
            "[real](docs/product.md)\n"
        )
        self.assertEqual(
            self.rewrite(text),
            "[foo `bar](docs/product.md)`\n"
            "[real](docs/产品说明.md)\n",
        )

    def test_unclosed_code_does_not_cross_markdown_blocks(self) -> None:
        cases = (
            "`unclosed\n\n[real](docs/product.md)`\n",
            "`unclosed\n# [real](docs/product.md)`\n",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIn("[real](docs/产品说明.md)", self.rewrite(text))

    def test_leaves_absolute_and_external_targets_untouched(self) -> None:
        text = (
            "[a](https://example.com/docs/product.md)\n"
            "[b](/docs/product.md)\n"
        )
        self.assertEqual(self.rewrite(text), text)

    def test_never_matches_a_longer_path_by_substring(self) -> None:
        text = (
            "[a](docs/product.md.bak)\n"
            "[b](notes/docs/product.md)\n"
            "[c](docs/product.markdown)\n"
        )
        self.assertEqual(self.rewrite(text), text)

    def test_percent_encoded_target_stays_encoded(self) -> None:
        rewritten, replacements = replace_visible_link_targets(
            "[a](docs/product.md)\n",
            (("docs/product.md", "docs/产品说明.md"),),
        )
        self.assertIn("docs/产品说明.md", rewritten)
        self.assertEqual(1, len(replacements))

        rewritten, _ = replace_visible_link_targets(
            "[a](docs/%E6%97%A7.md)\n", (("docs/旧.md", "docs/新.md"),)
        )
        self.assertIn("%E6%96%B0.md", rewritten)
        self.assertNotIn("docs/新.md", rewritten)

    def test_reports_each_applied_replacement(self) -> None:
        _, replacements = replace_visible_link_targets(
            "[a](docs/product.md)\n[b](docs/architecture.md)\n", MAPPINGS
        )
        self.assertEqual(len(replacements), 2)
        self.assertIn("docs/product.md → docs/产品说明.md", replacements)

    def test_rewrite_is_idempotent(self) -> None:
        once = self.rewrite("[a](docs/product.md)\n")
        self.assertEqual(self.rewrite(once), once)


class PathMentionTests(unittest.TestCase):
    def test_reports_only_mentions_outside_link_targets(self) -> None:
        text = (
            "[a](docs/product.md)\n"
            "正文提到 docs/product.md。\n"
            "```\ndocs/product.md\n```\n"
        )
        self.assertEqual(
            visible_path_mentions(text, ("docs/product.md",)),
            [(2, "docs/product.md")],
        )

    def test_link_only_document_reports_nothing(self) -> None:
        text = "[a](docs/product.md)\n[b]: docs/product.md\n"
        self.assertEqual(visible_path_mentions(text, ("docs/product.md",)), [])

    def test_inline_code_is_not_reported_as_prose(self) -> None:
        text = "`docs/product.md`\n正文 docs/product.md。\n"
        self.assertEqual(
            visible_path_mentions(text, ("docs/product.md",)),
            [(2, "docs/product.md")],
        )

    def test_code_formatted_link_label_is_not_reported_as_prose(self) -> None:
        self.assertEqual(
            visible_path_mentions(
                "[`产品`](docs/product.md)\n", ("docs/product.md",)
            ),
            [],
        )

    def test_code_span_crossing_target_is_not_reported_as_prose(self) -> None:
        self.assertEqual(
            visible_path_mentions(
                "[foo `bar](docs/product.md)`\n", ("docs/product.md",)
            ),
            [],
        )

    def test_multiline_inline_code_is_not_reported_as_prose(self) -> None:
        text = "``before docs/product.md\nafter``\n正文 docs/product.md。\n"
        self.assertEqual(
            visible_path_mentions(text, ("docs/product.md",)),
            [(3, "docs/product.md")],
        )

    def test_unclosed_code_does_not_hide_new_paragraph_mentions(self) -> None:
        text = "`unclosed\n\n正文 docs/product.md`\n"
        self.assertEqual(
            visible_path_mentions(text, ("docs/product.md",)),
            [(3, "docs/product.md")],
        )


class ExtractTargetsTests(unittest.TestCase):
    def test_collects_inline_and_reference_targets(self) -> None:
        targets = extract_link_targets(
            "[a](docs/product.md)\n[b]: <docs/architecture.md>\n"
        )
        self.assertIn("docs/product.md", targets)
        self.assertIn("<docs/architecture.md>", targets)

    def test_ignores_links_inside_inline_code(self) -> None:
        targets = extract_link_targets(
            "`[fake](docs/product.md)` [real](docs/architecture.md)\n"
        )
        self.assertEqual(targets, ["docs/architecture.md"])

    def test_extracts_link_with_code_formatted_label(self) -> None:
        self.assertEqual(
            extract_link_targets("[`产品`](docs/product.md)\n"),
            ["docs/product.md"],
        )

    def test_does_not_extract_code_span_crossing_target(self) -> None:
        self.assertEqual(
            extract_link_targets("[foo `bar](docs/product.md)`\n"),
            [],
        )

    def test_ignores_links_inside_multiline_inline_code(self) -> None:
        targets = extract_link_targets(
            "``before [fake](docs/product.md)\nafter``\n"
            "[real](docs/architecture.md)\n"
        )
        self.assertEqual(targets, ["docs/architecture.md"])

    def test_unclosed_code_does_not_hide_new_block_links(self) -> None:
        targets = extract_link_targets(
            "`unclosed\n\n[real](docs/architecture.md)`\n"
        )
        self.assertEqual(targets, ["docs/architecture.md"])


class AgentsNavigationScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        build_project(self.root, CHINESE_PROFILE)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_external_prose_reference_survives_the_update(self) -> None:
        prose = "参考上游仓库的 docs/architecture.md 与 docs/product.md 对照。"
        (self.root / "AGENTS.md").write_text(
            f"# Agents\n\n{prose}\n\n本项目见 [产品](docs/product.md)。\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "update_agents_navigation.py"),
                str(self.root),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        actual = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(prose, actual)
        self.assertIn("[产品](docs/产品说明.md)", actual)
        self.assertIn("未自动修改", result.stdout)


if __name__ == "__main__":
    unittest.main()
