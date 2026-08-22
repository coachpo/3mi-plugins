from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from canonical_paths import (
    DocumentLanguage,
    render_template,
    select_canonical_paths,
)
from contributing_blocks import (
    MvpMode,
    compose_contributing_block,
    parse_mvp_mode,
    validate_mvp_asset,
)
from doc_anchors import CHINESE_PROFILE, ENGLISH_PROFILE


ZH = DocumentLanguage.CHINESE
MVP_SECTION_HEADING = CHINESE_PROFILE.mvp_heading
MVP_STATUS_ENABLED = CHINESE_PROFILE.mvp_status_enabled_line
MVP_STATUS_DISABLED = CHINESE_PROFILE.mvp_status_disabled_line

UPDATE_SCRIPT = SCRIPTS / "update_contributing.py"
VALIDATE_SCRIPT = SCRIPTS / "validate_project_docs.py"
BASE_ASSET = CHINESE_PROFILE.asset_path(
    SKILL_ROOT, CHINESE_PROFILE.contributing_base_asset_name
)
MVP_ASSET = CHINESE_PROFILE.asset_path(
    SKILL_ROOT, CHINESE_PROFILE.contributing_mvp_asset_name
)
EN_BASE_ASSET = ENGLISH_PROFILE.asset_path(
    SKILL_ROOT, ENGLISH_PROFILE.contributing_base_asset_name
)
EN_MVP_ASSET = ENGLISH_PROFILE.asset_path(
    SKILL_ROOT, ENGLISH_PROFILE.contributing_mvp_asset_name
)
DEVELOPMENT_ASSET = CHINESE_PROFILE.asset_path(
    SKILL_ROOT, CHINESE_PROFILE.development_asset_name
)
SOURCE_SIZE_ASSET = CHINESE_PROFILE.asset_path(
    SKILL_ROOT, CHINESE_PROFILE.source_size_asset_name
)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


class MvpModeTests(unittest.TestCase):
    def test_parse_three_states(self) -> None:
        self.assertIs(parse_mvp_mode(MVP_STATUS_ENABLED, ZH), MvpMode.ENABLED)
        self.assertIs(parse_mvp_mode(MVP_STATUS_DISABLED, ZH), MvpMode.DISABLED)
        self.assertIs(parse_mvp_mode("# 项目状态\n", ZH), MvpMode.ABSENT)

    def test_rejects_malformed_duplicate_and_conflicting_states(self) -> None:
        cases = (
            "MVP 快速验证模式=启用\n",
            "MVP 快速验证模式:启用\n",
            MVP_STATUS_ENABLED + " \n",
            MVP_STATUS_ENABLED + "-临时\n",
            f"{MVP_STATUS_ENABLED}\n{MVP_STATUS_ENABLED}\n",
            f"{MVP_STATUS_ENABLED}\n{MVP_STATUS_DISABLED}\n",
        )
        for status_text in cases:
            with self.subTest(status_text=status_text):
                with self.assertRaises(ValueError):
                    parse_mvp_mode(status_text, ZH)

    def test_ignores_invisible_pseudo_states_and_ordinary_narrative(self) -> None:
        status_text = (
            "```text\n"
            f"{MVP_STATUS_DISABLED}\n"
            "```\n\n"
            "~~~text\n"
            f"{MVP_STATUS_DISABLED}\n"
            "~~~\n\n"
            "<!--\n"
            f"{MVP_STATUS_DISABLED}\n"
            "-->\n\n"
            "<script>\n"
            f"{MVP_STATUS_DISABLED}\n"
            "</script>\n\n"
            "<div>\n"
            f"{MVP_STATUS_DISABLED}\n"
            "</div>\n\n"
            "<mvp-state>\n"
            f"{MVP_STATUS_DISABLED}\n"
            "\n"
            "当前说明提到 MVP 快速验证模式，但不是状态键。\n\n"
            f"{MVP_STATUS_ENABLED}\n"
        )
        self.assertIs(parse_mvp_mode(status_text, ZH), MvpMode.ENABLED)

    def test_validates_and_composes_mvp_asset(self) -> None:
        base = BASE_ASSET.read_text(encoding="utf-8")
        mvp = MVP_ASSET.read_text(encoding="utf-8")
        validate_mvp_asset(mvp, CHINESE_PROFILE)
        enabled = compose_contributing_block(
            base, mvp, mvp_mode=MvpMode.ENABLED, language=ZH
        )
        self.assertEqual(enabled.count(MVP_SECTION_HEADING), 1)
        self.assertLess(enabled.index(MVP_SECTION_HEADING), enabled.index("## 完成定义"))
        self.assertEqual(
            compose_contributing_block(
                base, mvp, mvp_mode=MvpMode.ABSENT, language=ZH
            ),
            base,
        )
        embedded = base.replace(
            "## 完成定义\n",
            MVP_SECTION_HEADING + "\n\n说明。\n\n## 完成定义\n",
        )
        with self.assertRaises(ValueError):
            compose_contributing_block(
                embedded, mvp, mvp_mode=MvpMode.DISABLED, language=ZH
            )

    def test_enabled_assets_add_three_layer_scope_without_old_guardrail(
        self,
    ) -> None:
        cases = (
            (
                CHINESE_PROFILE,
                BASE_ASSET,
                MVP_ASSET,
                ("**明确不做：**", "**可推迟：**", "**仍是约束：**"),
                (
                    "已有兼容承诺和仓库必需检查本身不属于该分类，"
                    "也不构成排除授权"
                ),
                "至少一个可观察重评条件",
                (
                    "不扩大权限",
                    "不执行未授权外部写入",
                    "不执行未授权破坏性操作",
                    "不删除或重置现有数据",
                    "不虚构验证结果",
                    "不主动违反 [`STATUS.md`](STATUS.md) 的明确禁止事项",
                ),
                "不得以 MVP 为由跳过必要验证",
            ),
            (
                ENGLISH_PROFILE,
                EN_BASE_ASSET,
                EN_MVP_ASSET,
                (
                    "**Explicitly out of scope:**",
                    "**May be deferred:**",
                    "**Still constraints:**",
                ),
                (
                    "Existing compatibility commitments and repository-required "
                    "checks are not themselves in this category and do not authorize "
                    "exclusion"
                ),
                "at least one observable re-evaluation trigger",
                (
                    "Do not widen permissions",
                    "Do not perform unauthorized external writes",
                    "Do not perform unauthorized destructive operations",
                    "Do not delete or reset existing data",
                    "Do not fabricate validation results",
                    (
                        "Do not intentionally violate explicit prohibitions in "
                        "[`STATUS.md`](STATUS.md)"
                    ),
                ),
                "MVP status is never a reason to skip required verification",
            ),
        )
        for (
            profile,
            base_path,
            mvp_path,
            labels,
            distinction,
            trigger,
            constraints,
            removed,
        ) in cases:
            with self.subTest(language=profile.language):
                base = base_path.read_text(encoding="utf-8")
                mvp = mvp_path.read_text(encoding="utf-8")
                enabled = compose_contributing_block(
                    base,
                    mvp,
                    mvp_mode=MvpMode.ENABLED,
                    language=profile.language,
                )
                disabled = compose_contributing_block(
                    base,
                    mvp,
                    mvp_mode=MvpMode.DISABLED,
                    language=profile.language,
                )
                for label in labels:
                    self.assertIn(label, enabled)
                    self.assertNotIn(label, disabled)
                self.assertIn(distinction, enabled)
                self.assertIn(trigger, enabled)
                for constraint in constraints:
                    self.assertIn(constraint, enabled)
                self.assertNotIn(removed, enabled)

    def test_rejects_malformed_mvp_assets(self) -> None:
        valid = MVP_ASSET.read_text(encoding="utf-8")
        cases = (
            valid.replace("\n", "\r\n"),
            valid + "\n",
            valid + " \n",
            valid + "\t\n",
            valid.replace("### MVP 快速验证", "### MVP 快速验证 ###", 1),
            valid + "### 另一个 H3\n",
            valid + "## 非法 H2\n",
            valid + "非法 H2\n---\n",
        )
        for asset in cases:
            with self.subTest(asset=asset[-40:]):
                with self.assertRaises(ValueError):
                    validate_mvp_asset(asset, CHINESE_PROFILE)


class UpdateContributingTests(unittest.TestCase):
    def make_project(self, directory: str, status_text: str) -> tuple[Path, str, str]:
        root = Path(directory)
        docs = root / "docs"
        docs.mkdir(parents=True)
        write_text(root / "README.md", "# 项目\n")
        write_text(root / "STATUS.md", status_text)
        write_text(docs / "README.md", "# 文档\n")
        write_text(docs / "产品说明.md", "# 产品说明\n")
        write_text(docs / "架构说明.md", "# 架构说明\n")
        write_text(docs / "开发规范.md", "# 开发规范\n")
        write_text(docs / "源代码规模与职责规则.md", "# 规模规则\n")
        selected, errors = select_canonical_paths(root)
        self.assertEqual(errors, [])
        base = render_template(BASE_ASSET.read_bytes(), selected, "base").decode("utf-8")
        mvp = render_template(MVP_ASSET.read_bytes(), selected, "mvp").decode("utf-8")
        write_text(root / "CONTRIBUTING.md", "# 贡献指南\n\n" + base)
        return root, base, mvp

    def run_update(self, root: Path) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, str(UPDATE_SCRIPT), str(root)],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

    def run_validator(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATE_SCRIPT), "--strict", str(root)],
            text=True,
            capture_output=True,
            check=False,
        )

    def complete_project_fixture(self, root: Path) -> None:
        selected, errors = select_canonical_paths(root)
        self.assertEqual(errors, [])
        development = render_template(
            DEVELOPMENT_ASSET.read_bytes(), selected, "development"
        ).decode("utf-8")
        source_size = render_template(
            SOURCE_SIZE_ASSET.read_bytes(), selected, "source-size"
        ).decode("utf-8")
        write_text(root / selected["development_rules"], "# 开发规范\n\n" + development)
        write_text(root / selected["source_size_rules"], source_size)

    def test_toggle_and_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, base, mvp = self.make_project(directory, MVP_STATUS_ENABLED + "\n")
            first = self.run_update(root)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            enabled = (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
            self.assertIn(mvp, enabled)
            enabled_bytes = (root / "CONTRIBUTING.md").read_bytes()

            second = self.run_update(root)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual((root / "CONTRIBUTING.md").read_bytes(), enabled_bytes)

            write_text(root / "STATUS.md", MVP_STATUS_DISABLED + "\n")
            disabled = self.run_update(root)
            self.assertEqual(disabled.returncode, 0, disabled.stdout + disabled.stderr)
            self.assertEqual(
                (root / "CONTRIBUTING.md").read_text(encoding="utf-8"),
                "# 贡献指南\n\n" + base,
            )

    def test_absent_state_reports_default_without_claiming_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _base, _mvp = self.make_project(directory, "# 项目状态\n")
            result = self.run_update(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("未声明，按未启用处理", result.stdout)

    def test_invalid_status_never_writes(self) -> None:
        for case in (
            "missing",
            "symlink",
            "non_utf8",
            "malformed",
            "non_utf8_contributing",
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root, _base, _mvp = self.make_project(directory, MVP_STATUS_DISABLED + "\n")
                contributing = root / "CONTRIBUTING.md"
                original = contributing.read_bytes()
                status = root / "STATUS.md"
                if case == "missing":
                    status.unlink()
                elif case == "symlink":
                    status.unlink()
                    target = root / "real-status.md"
                    write_text(target, MVP_STATUS_ENABLED + "\n")
                    status.symlink_to(target)
                elif case == "non_utf8":
                    status.write_bytes(b"\xff\xfe")
                elif case == "non_utf8_contributing":
                    contributing.write_bytes(b"\xff\xfe")
                    original = contributing.read_bytes()
                else:
                    write_text(status, "MVP 快速验证模式=启用\n")
                result = self.run_update(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(contributing.read_bytes(), original)

    def test_rejects_ambiguous_boundaries_and_outside_mvp_heading(self) -> None:
        for case in ("duplicate_block", "partial_block", "wrong_order", "outside_mvp"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root, base, _mvp = self.make_project(directory, MVP_STATUS_DISABLED + "\n")
                contributing = root / "CONTRIBUTING.md"
                if case == "duplicate_block":
                    write_text(contributing, "# 贡献指南\n\n" + base + "\n" + base)
                elif case == "partial_block":
                    write_text(contributing, "# 贡献指南\n\n## 通用实现原则\n")
                elif case == "wrong_order":
                    swapped = base.replace("## 通用设计原则", "## 临时标题", 1)
                    swapped = swapped.replace("## 通用实现原则", "## 通用设计原则", 1)
                    swapped = swapped.replace("## 临时标题", "## 通用实现原则", 1)
                    write_text(contributing, "# 贡献指南\n\n" + swapped)
                else:
                    write_text(
                        contributing,
                        "# 贡献指南\n\n"
                        + base
                        + "\n  ### MVP 快速验证 ###\n\n外部内容。\n",
                    )
                original = contributing.read_bytes()
                result = self.run_update(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(contributing.read_bytes(), original)

    def test_appends_when_all_managed_headings_are_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _base, _mvp = self.make_project(
                directory, MVP_STATUS_ENABLED + "\n"
            )
            write_text(root / "CONTRIBUTING.md", "# 贡献指南\n\n本地说明。\n")
            result = self.run_update(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            actual = (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
            self.assertEqual(actual.count(MVP_SECTION_HEADING), 1)
            self.assertTrue(actual.startswith("# 贡献指南\n\n本地说明。\n\n"))

    def test_rejects_duplicate_mvp_heading_inside_managed_span(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, base, mvp = self.make_project(
                directory, MVP_STATUS_ENABLED + "\n"
            )
            enabled = compose_contributing_block(
                base, mvp, mvp_mode=MvpMode.ENABLED, language=ZH
            )
            duplicate = enabled.replace(
                "## 完成定义\n",
                "   ### MVP 快速验证 ###\n\n重复。\n\n## 完成定义\n",
            )
            contributing = root / "CONTRIBUTING.md"
            write_text(contributing, "# 贡献指南\n\n" + duplicate)
            original = contributing.read_bytes()
            result = self.run_update(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(contributing.read_bytes(), original)

    def test_renders_english_canonical_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_text(root / "README.md", "# Project\n")
            write_text(
                root / "STATUS.md",
                ENGLISH_PROFILE.mvp_status_enabled_line + "\n",
            )
            write_text(root / "docs" / "README.md", "# Docs\n")
            for relative in (
                "docs/product.md",
                "docs/architecture.md",
                "docs/development-rules.md",
                "docs/source-code-size-and-responsibility-rules.md",
            ):
                write_text(root / relative, "# Doc\n")
            write_text(root / "CONTRIBUTING.md", "# Contributing\n")
            result = self.run_update(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            actual = (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
            self.assertIn("(docs/product.md)", actual)
            self.assertIn("(docs/architecture.md)", actual)
            self.assertIn("(docs/development-rules.md)", actual)
            self.assertIn(ENGLISH_PROFILE.mvp_heading + "\n", actual)
            for title in ENGLISH_PROFILE.contributing_section_titles:
                self.assertIn(f"## {title}\n", actual)

    def test_validator_accepts_all_three_mvp_states(self) -> None:
        states = (MVP_STATUS_ENABLED + "\n", MVP_STATUS_DISABLED + "\n", "# 状态\n")
        for status_text in states:
            with self.subTest(status_text=status_text), tempfile.TemporaryDirectory() as directory:
                root, _base, _mvp = self.make_project(directory, status_text)
                self.complete_project_fixture(root)
                update = self.run_update(root)
                self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
                validation = self.run_validator(root)
                self.assertEqual(
                    validation.returncode,
                    0,
                    validation.stdout + validation.stderr,
                )

    def test_validator_rejects_invalid_mvp_state_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _base, _mvp = self.make_project(
                directory, "MVP 快速验证模式=启用\n"
            )
            self.complete_project_fixture(root)
            contributing = root / "CONTRIBUTING.md"
            before = contributing.read_bytes()
            validation = self.run_validator(root)
            self.assertNotEqual(validation.returncode, 0)
            self.assertIn("状态行无效", validation.stdout)
            self.assertEqual(contributing.read_bytes(), before)

    def test_preserves_crlf_outside_managed_span(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, base, _mvp = self.make_project(directory, MVP_STATUS_ENABLED + "\n")
            prefix = "# 贡献指南\r\n\r\n本地说明。\r\n\r\n"
            suffix = "\r\n## 本地附录\r\n\r\n保留 CRLF。\r\n"
            contributing = root / "CONTRIBUTING.md"
            write_text(contributing, prefix + base.rstrip("\n") + "\r\n" + suffix)
            result = self.run_update(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            updated = contributing.read_bytes()
            self.assertTrue(updated.startswith(prefix.encode("utf-8")))
            self.assertTrue(updated.endswith(suffix.encode("utf-8")))


if __name__ == "__main__":
    unittest.main()
