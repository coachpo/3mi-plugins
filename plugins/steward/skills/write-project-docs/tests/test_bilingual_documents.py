from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
GUIDE_SCRIPTS = SKILL_ROOT.parent / "write-agent-guides" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import update_agents_navigation as agents_navigation  # noqa: E402
from canonical_paths import (  # noqa: E402
    CANONICAL_DOCUMENTS,
    DocumentLanguage,
    detect_document_language,
    render_template,
    resolve_project_docs,
)
from contributing_blocks import MvpMode, parse_mvp_mode  # noqa: E402
from doc_anchors import (  # noqa: E402
    CHINESE_PROFILE,
    ENGLISH_PROFILE,
    LANGUAGE_PROFILES,
    profile_for,
)
from validate_project_docs import THRESHOLD_RE  # noqa: E402

PROFILES = (CHINESE_PROFILE, ENGLISH_PROFILE)
UPDATE_SCRIPTS = (
    "update_development_rules.py",
    "update_contributing.py",
    "update_agents_navigation.py",
)


def build_project(root: Path, profile) -> dict[str, str]:
    """Create a minimal but complete document set in one language."""

    (root / "docs").mkdir(parents=True, exist_ok=True)
    selected = {
        document.key: document.path_for(profile.language)
        for document in CANONICAL_DOCUMENTS
    }
    for key in ("product", "architecture"):
        (root / selected[key]).write_text("# doc\n", encoding="utf-8")
    (root / selected["development_rules"]).write_text(
        profile.development_rules_title + "\n", encoding="utf-8"
    )
    (root / selected["source_size_rules"]).write_bytes(
        render_template(
            profile.asset_path(
                SKILL_ROOT, profile.source_size_asset_name
            ).read_bytes(),
            selected,
            "source-size",
        )
    )
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    (root / "docs" / "README.md").write_text("# Index\n", encoding="utf-8")
    (root / "CONTRIBUTING.md").write_text("# Contributing\n", encoding="utf-8")
    (root / "STATUS.md").write_text(
        profile.mvp_status_enabled_line + "\n", encoding="utf-8"
    )
    (root / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    return selected


def run_script(
    name: str, root: Path, *options: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), str(root), *options],
        text=True,
        capture_output=True,
        check=False,
    )


class TemporaryProject(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()


class LanguageDetectionTests(TemporaryProject):
    def test_empty_project_defaults_to_chinese(self) -> None:
        language, errors = detect_document_language(self.root)
        self.assertIs(language, DocumentLanguage.CHINESE)
        self.assertEqual(errors, [])

        context = resolve_project_docs(self.root, require_existing=False)
        self.assertTrue(context.language_resolved)
        self.assertEqual(
            list(context.selected.values()),
            [document.chinese_path for document in CANONICAL_DOCUMENTS],
        )

    def test_each_language_is_detected_from_existing_paths(self) -> None:
        for profile in PROFILES:
            with self.subTest(language=profile.language):
                root = self.root / profile.assets_directory
                build_project(root, profile)
                language, errors = detect_document_language(root)
                self.assertIs(language, profile.language)
                self.assertEqual(errors, [])

    def test_missing_authority_follows_the_detected_language(self) -> None:
        root = self.root / "partial"
        (root / "docs").mkdir(parents=True)
        (root / "docs" / "product.md").write_text("# doc\n", encoding="utf-8")
        context = resolve_project_docs(root, require_existing=False)
        self.assertIs(context.language, DocumentLanguage.ENGLISH)
        self.assertEqual(
            context.selected["source_size_rules"],
            "docs/source-code-size-and-responsibility-rules.md",
        )

    def test_mixed_languages_are_reported_and_unresolved(self) -> None:
        root = self.root / "mixed"
        (root / "docs").mkdir(parents=True)
        (root / "docs" / "product.md").write_text("# doc\n", encoding="utf-8")
        (root / "docs" / "架构说明.md").write_text("# doc\n", encoding="utf-8")
        language, errors = detect_document_language(root)
        self.assertIs(language, DocumentLanguage.CHINESE)
        self.assertEqual(len(errors), 1)
        self.assertIn("无法确定项目文档语言", errors[0])

        context = resolve_project_docs(root, require_existing=False)
        self.assertFalse(context.language_resolved)
        self.assertEqual(context.language_errors, errors)

    def test_doubled_authority_carries_no_language_signal(self) -> None:
        root = self.root / "doubled"
        (root / "docs").mkdir(parents=True)
        (root / "docs" / "product.md").write_text("# doc\n", encoding="utf-8")
        (root / "docs" / "产品说明.md").write_text("# doc\n", encoding="utf-8")
        language, errors = detect_document_language(root)
        self.assertIs(language, DocumentLanguage.CHINESE)
        self.assertEqual(errors, [])

        context = resolve_project_docs(root, require_existing=False)
        self.assertTrue(context.language_resolved)
        self.assertTrue(
            any("必须只保留一个" in error for error in context.errors)
        )


class BilingualPipelineTests(TemporaryProject):
    def validate(
        self, root: Path, *options: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "validate_project_docs.py"),
                "--strict",
                str(root),
                *options,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_each_language_composes_and_validates(self) -> None:
        for profile in PROFILES:
            with self.subTest(language=profile.language):
                root = self.root / profile.assets_directory
                selected = build_project(root, profile)
                for name in UPDATE_SCRIPTS:
                    result = run_script(name, root)
                    self.assertEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )
                validation = self.validate(root)
                self.assertEqual(
                    validation.returncode,
                    0,
                    validation.stdout + validation.stderr,
                )

                development = (root / selected["development_rules"]).read_text(
                    encoding="utf-8"
                )
                self.assertTrue(
                    development.startswith(profile.development_rules_title)
                )
                contributing = (root / "CONTRIBUTING.md").read_text(
                    encoding="utf-8"
                )
                for title in profile.contributing_section_titles:
                    self.assertIn(f"## {title}\n", contributing)
                self.assertIn(profile.mvp_heading + "\n", contributing)
                agents = (root / "AGENTS.md").read_text(encoding="utf-8")
                for title in profile.agents_section_titles:
                    self.assertIn(f"## {title}\n", agents)
                strategy_anchor = (
                    "CONTRIBUTING.md#当前迭代策略"
                    if profile.language is DocumentLanguage.CHINESE
                    else "CONTRIBUTING.md#current-iteration-strategy"
                )
                self.assertIn(strategy_anchor, agents)
                self.assertIn(profile.mvp_title, agents)
                layers = (
                    ("“明确不做”“可推迟”“仍是约束”三层", "可观察重评条件")
                    if profile.language is DocumentLanguage.CHINESE
                    else (
                        '"Explicitly out of scope," "May be deferred," and '
                        '"Still constraints" layers',
                        "observable re-evaluation trigger",
                    )
                )
                for expected in layers:
                    self.assertIn(expected, agents)

    def test_updates_are_idempotent_in_each_language(self) -> None:
        for profile in PROFILES:
            with self.subTest(language=profile.language):
                root = self.root / profile.assets_directory
                build_project(root, profile)
                for name in UPDATE_SCRIPTS:
                    run_script(name, root)
                snapshot = {
                    path: path.read_bytes()
                    for path in sorted(root.rglob("*.md"))
                }
                for name in UPDATE_SCRIPTS:
                    result = run_script(name, root)
                    self.assertEqual(result.returncode, 0, result.stdout)
                    self.assertIn("未修改", result.stdout)
                for path, before in snapshot.items():
                    self.assertEqual(path.read_bytes(), before)

    def test_mixed_language_project_refuses_every_write(self) -> None:
        root = self.root / "mixed"
        build_project(root, ENGLISH_PROFILE)
        (root / "docs" / "architecture.md").rename(
            root / "docs" / "架构说明.md"
        )
        snapshot = {
            path: path.read_bytes() for path in sorted(root.rglob("*.md"))
        }
        for name in UPDATE_SCRIPTS:
            result = run_script(name, root)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("无法确定项目文档语言", result.stdout)
        for path, before in snapshot.items():
            self.assertEqual(path.read_bytes(), before)

        validation = self.validate(root)
        self.assertEqual(validation.returncode, 1)
        self.assertIn("无法确定项目文档语言", validation.stdout)
        self.assertNotIn("必须以唯一的", validation.stdout)

    def test_unresolved_language_still_reports_independent_findings(
        self,
    ) -> None:
        root = self.root / "mixed-with-findings"
        build_project(root, ENGLISH_PROFILE)
        (root / "docs" / "architecture.md").rename(
            root / "docs" / "架构说明.md"
        )
        (root / "README.md").write_text(
            "# Demo\n\n[missing](docs/missing.md)\n", encoding="utf-8"
        )
        (root / "docs" / "INDEX.md").write_text("# Legacy\n", encoding="utf-8")

        validation = self.validate(root)
        self.assertEqual(validation.returncode, 1)
        self.assertIn("无法确定项目文档语言", validation.stdout)
        self.assertIn("本地链接目标不存在", validation.stdout)
        self.assertIn("存在竞争或遗留 canonical 路径", validation.stdout)

    def test_agents_navigation_preserves_engineering_router_byte_for_byte(self) -> None:
        root = self.root / "router-owned-by-other-skill"
        build_project(root, ENGLISH_PROFILE)
        router = (
            "<!-- write-agent-guides:engineering-router:start -->\n"
            "## Engineering Router\n\n"
            "| Trigger | Authority | Invariant IDs | Validation entry |\n"
            "| --- | --- | --- | --- |\n"
            "| code | docs/产品说明.md | INV-PROJECT-0123456789AB | review |\n"
            "<!-- write-agent-guides:engineering-router:end -->\n"
        )
        agents_path = root / "AGENTS.md"
        agents_path.write_text("# Agents\n\n" + router, encoding="utf-8")

        result = run_script("update_agents_navigation.py", root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        updated = agents_path.read_text(encoding="utf-8")
        self.assertIn(router, updated)
        self.assertEqual(updated.count("docs/产品说明.md"), 1)
        self.assertIn("<!-- write-project-docs:document-navigation:start -->", updated)

    def test_agents_navigation_rejects_nested_owned_blocks(self) -> None:
        root = self.root / "nested-owned-blocks"
        build_project(root, ENGLISH_PROFILE)
        agents_path = root / "AGENTS.md"
        agents_path.write_text(
            "# Agents\n\n"
            "<!-- write-agent-guides:engineering-router:start -->\n"
            "## Engineering Router\n\n"
            "<!-- write-project-docs:document-navigation:start -->\n"
            "## Project Documentation Navigation\n"
            "<!-- write-project-docs:document-navigation:end -->\n"
            "<!-- write-agent-guides:engineering-router:end -->\n",
            encoding="utf-8",
        )
        before = agents_path.read_bytes()
        result = run_script("update_agents_navigation.py", root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("不得嵌套", result.stdout)
        self.assertEqual(agents_path.read_bytes(), before)

    def test_agents_navigation_only_normalizes_visible_unowned_link_targets(
        self,
    ) -> None:
        root = self.root / "protected-markdown"
        build_project(root, ENGLISH_PROFILE)
        agents_path = root / "AGENTS.md"
        foreign = (
            "<!-- foreign-skill:owned:start -->\n"
            "Foreign docs/INDEX.md\n"
            "<!-- foreign-skill:owned:end -->\n"
        )
        fenced = (
            "```text\n"
            "<!-- fenced-skill:owned:start -->\n"
            "Fenced docs/INDEX.md\n"
            "<!-- fenced-skill:owned:end -->\n"
            "```\n"
        )
        html = (
            "<div>\n"
            "<!-- html-skill:owned:start -->\n"
            "HTML docs/INDEX.md\n"
            "<!-- html-skill:owned:end -->\n"
            "</div>\n\n"
        )
        agents_path.write_text(
            "# Agents\n\n"
            "Visible docs/INDEX.md\n\n"
            "[Index](docs/INDEX.md)\n\n"
            + foreign
            + "\n"
            + fenced
            + "\n"
            + html,
            encoding="utf-8",
        )

        result = run_script("update_agents_navigation.py", root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        updated = agents_path.read_text(encoding="utf-8")
        self.assertIn("Visible docs/INDEX.md", updated)
        self.assertIn("[Index](docs/README.md)", updated)
        self.assertIn("未自动修改", result.stdout)
        self.assertIn(foreign, updated)
        self.assertIn(fenced, updated)
        self.assertIn(html, updated)

    def test_agents_navigation_rejects_malformed_or_overlapping_foreign_blocks(
        self,
    ) -> None:
        cases = {
            "partial": ("<!-- foreign-skill:owned:start -->\nForeign docs/INDEX.md\n"),
            "inline": (
                "Prefix <!-- foreign-skill:owned:start -->\n"
                "<!-- foreign-skill:owned:end -->\n"
            ),
            "overlap": (
                "<!-- foreign-skill:first:start -->\n"
                "<!-- foreign-skill:second:start -->\n"
                "<!-- foreign-skill:first:end -->\n"
                "<!-- foreign-skill:second:end -->\n"
            ),
        }
        for name, content in cases.items():
            with self.subTest(name=name):
                root = self.root / name
                build_project(root, ENGLISH_PROFILE)
                agents_path = root / "AGENTS.md"
                agents_path.write_text("# Agents\n\n" + content, encoding="utf-8")
                before = agents_path.read_bytes()

                result = run_script("update_agents_navigation.py", root)

                self.assertEqual(result.returncode, 1)
                self.assertIn("托管区块", result.stdout)
                self.assertEqual(agents_path.read_bytes(), before)

    def test_agents_navigation_rejects_insertion_into_unclosed_hidden_blocks(
        self,
    ) -> None:
        tails = {
            "backtick-fence": "```text\nunclosed\n",
            "tilde-fence": "~~~text\nunclosed\n",
            "script": "<script>\nunclosed\n",
            "pre": "<pre>\nunclosed\n",
            "comment": "<!-- unclosed\n",
        }
        for name, tail in tails.items():
            with self.subTest(name=name):
                root = self.root / f"hidden-tail-{name}"
                build_project(root, ENGLISH_PROFILE)
                agents_path = root / "AGENTS.md"
                agents_path.write_text("# Agents\n\n" + tail, encoding="utf-8")
                before = agents_path.read_bytes()

                result = run_script("update_agents_navigation.py", root)

                self.assertEqual(result.returncode, 1)
                self.assertEqual(agents_path.read_bytes(), before)

    def test_agents_navigation_cas_preserves_external_target_change(self) -> None:
        root = self.root / "navigation-target-race"
        build_project(root, ENGLISH_PROFILE)
        agents_path = root / "AGENTS.md"
        real_write = agents_navigation.write_atomically

        def inject_change(*args, **kwargs):
            agents_path.write_text("concurrent user change\n", encoding="utf-8")
            return real_write(*args, **kwargs)

        output = io.StringIO()
        with (
            mock.patch.object(
                agents_navigation, "write_atomically", side_effect=inject_change
            ),
            mock.patch.object(
                sys,
                "argv",
                ["update_agents_navigation.py", str(root)],
            ),
            mock.patch("sys.stdout", output),
        ):
            result = agents_navigation.main()

        self.assertEqual(result, 1)
        self.assertIn("写入期间发生变化", output.getvalue())
        self.assertEqual(
            agents_path.read_text(encoding="utf-8"), "concurrent user change\n"
        )

    def test_agents_navigation_cas_binds_canonical_inputs(self) -> None:
        root = self.root / "navigation-source-race"
        selected = build_project(root, ENGLISH_PROFILE)
        agents_path = root / "AGENTS.md"
        before = agents_path.read_bytes()
        product_path = root / selected["product"]
        real_write = agents_navigation.write_atomically

        def inject_source_change(*args, **kwargs):
            product_path.write_text("# changed product\n", encoding="utf-8")
            return real_write(*args, **kwargs)

        with (
            mock.patch.object(
                agents_navigation,
                "write_atomically",
                side_effect=inject_source_change,
            ),
            mock.patch.object(
                sys,
                "argv",
                ["update_agents_navigation.py", str(root)],
            ),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            result = agents_navigation.main()

        self.assertEqual(result, 1)
        self.assertEqual(agents_path.read_bytes(), before)

    def test_agents_navigation_noop_revalidates_canonical_inputs(self) -> None:
        root = self.root / "navigation-noop-source-race"
        selected = build_project(root, ENGLISH_PROFILE)
        self.assertEqual(
            run_script("update_agents_navigation.py", root).returncode,
            0,
        )
        agents_path = root / "AGENTS.md"
        before = agents_path.read_bytes()
        product_path = root / selected["product"]
        real_resolve = agents_navigation.resolve_project_docs
        calls = 0

        def mutate_before_noop_validation(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                product_path.write_text("# changed during no-op\n", encoding="utf-8")
            return real_resolve(*args, **kwargs)

        with (
            mock.patch.object(
                agents_navigation,
                "resolve_project_docs",
                side_effect=mutate_before_noop_validation,
            ),
            mock.patch.object(
                sys,
                "argv",
                ["update_agents_navigation.py", str(root)],
            ),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            result = agents_navigation.main()

        self.assertEqual(result, 1)
        self.assertEqual(agents_path.read_bytes(), before)

    def test_validator_enables_invariant_contract_only_when_present(self) -> None:
        root = self.root / "optional-invariants"
        build_project(root, ENGLISH_PROFILE)
        for name in UPDATE_SCRIPTS:
            result = run_script(name, root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        legacy = self.validate(root)
        self.assertEqual(legacy.returncode, 0, legacy.stdout + legacy.stderr)

        contract_dir = root / ".steward"
        contract_dir.mkdir()
        (contract_dir / "invariants.json").write_text(
            '{"schemaVersion":2,"bindings":[]}\n', encoding="utf-8"
        )
        validation = self.validate(root)
        self.assertEqual(validation.returncode, 1)
        self.assertIn("工程路由", validation.stdout)
        self.assertIn("schemaVersion", validation.stdout)

    def test_validator_accepts_matching_optional_invariant_router(self) -> None:
        root = self.root / "valid-optional-invariants"
        selected = build_project(root, ENGLISH_PROFILE)
        for name in UPDATE_SCRIPTS:
            result = run_script(name, root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        invariant_id = "INV-PROJECT-0123456789AB"
        authority = root / selected["architecture"]
        authority.write_text(
            '# Architecture\n\n<a id="inv-project-0123456789ab"></a>\nRule.\n',
            encoding="utf-8",
        )
        evidence = root / "tests" / "test_architecture.py"
        evidence.parent.mkdir()
        evidence.write_text("# evidence\n", encoding="utf-8")
        contract_dir = root / ".steward"
        contract_dir.mkdir()
        contract = {
            "schemaVersion": 1,
            "bindings": [
                {
                    "invariantId": invariant_id,
                    "source": {
                        "kind": "project",
                        "version": "1",
                        "digest": "sha256:"
                        + hashlib.sha256(authority.read_bytes()).hexdigest(),
                    },
                    "scopes": ["."],
                    "trigger": "changing architecture",
                    "authority": {
                        "path": selected["architecture"],
                        "anchor": invariant_id.lower(),
                    },
                    "applicability": "applicable",
                    "status": "direct",
                    "evidence": ["tests/test_architecture.py"],
                    "enforcement": {
                        "kind": "mechanical",
                        "evidence": ["tests/test_architecture.py"],
                        "validationEntry": "`python3 -m unittest`",
                    },
                }
            ],
        }
        (contract_dir / "invariants.json").write_text(
            json.dumps(contract, indent=2) + "\n", encoding="utf-8"
        )
        router_update = subprocess.run(
            [
                sys.executable,
                str(GUIDE_SCRIPTS / "update_engineering_router.py"),
                str(root),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            router_update.returncode,
            0,
            router_update.stdout + router_update.stderr,
        )
        validation = self.validate(root)
        self.assertEqual(
            validation.returncode,
            0,
            validation.stdout + validation.stderr,
        )


class ExplicitLanguageTests(TemporaryProject):
    def test_matching_explicit_language_behaves_like_detection(self) -> None:
        for profile in PROFILES:
            with self.subTest(language=profile.language):
                root = self.root / profile.assets_directory
                build_project(root, profile)
                for name in UPDATE_SCRIPTS:
                    result = run_script(
                        name, root, "--language", profile.assets_directory
                    )
                    self.assertEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )
                validation = run_script(
                    "validate_project_docs.py",
                    root,
                    "--language",
                    profile.assets_directory,
                )
                self.assertEqual(
                    validation.returncode,
                    0,
                    validation.stdout + validation.stderr,
                )

    def test_contradicting_explicit_language_refuses_every_write(self) -> None:
        root = self.root / "english"
        build_project(root, ENGLISH_PROFILE)
        snapshot = {path: path.read_bytes() for path in sorted(root.rglob("*.md"))}
        for name in UPDATE_SCRIPTS:
            result = run_script(name, root, "--language", "zh")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("与已存在的固定文档冲突", result.stdout)
        for path, before in snapshot.items():
            self.assertEqual(path.read_bytes(), before)

        validation = run_script("validate_project_docs.py", root, "--language", "zh")
        self.assertEqual(validation.returncode, 1)
        self.assertIn("与已存在的固定文档冲突", validation.stdout)


class CrossLanguageStatusTests(TemporaryProject):
    def test_status_line_from_the_other_language_is_rejected(self) -> None:
        for profile in PROFILES:
            other = next(
                candidate
                for candidate in LANGUAGE_PROFILES.values()
                if candidate.language is not profile.language
            )
            with self.subTest(language=profile.language):
                with self.assertRaises(ValueError) as caught:
                    parse_mvp_mode(
                        other.mvp_status_enabled_line + "\n", profile.language
                    )
                self.assertIn("不一致", str(caught.exception))

    def test_update_refuses_a_foreign_status_line(self) -> None:
        root = self.root / "english"
        build_project(root, ENGLISH_PROFILE)
        (root / "STATUS.md").write_text(
            CHINESE_PROFILE.mvp_status_enabled_line + "\n", encoding="utf-8"
        )
        before = (root / "CONTRIBUTING.md").read_bytes()
        result = run_script("update_contributing.py", root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("不一致", result.stdout)
        self.assertEqual((root / "CONTRIBUTING.md").read_bytes(), before)

    def test_each_language_parses_its_own_states(self) -> None:
        for profile in PROFILES:
            with self.subTest(language=profile.language):
                self.assertIs(
                    parse_mvp_mode(
                        profile.mvp_status_enabled_line + "\n",
                        profile.language,
                    ),
                    MvpMode.ENABLED,
                )
                self.assertIs(
                    parse_mvp_mode(
                        profile.mvp_status_disabled_line + "\n",
                        profile.language,
                    ),
                    MvpMode.DISABLED,
                )
                self.assertIs(
                    parse_mvp_mode("# Status\n", profile.language),
                    MvpMode.ABSENT,
                )


class SharedAssetTests(unittest.TestCase):
    def test_every_language_ships_all_five_assets(self) -> None:
        for profile in PROFILES:
            with self.subTest(language=profile.language):
                for name in (
                    profile.agents_asset_name,
                    profile.contributing_base_asset_name,
                    profile.contributing_mvp_asset_name,
                    profile.development_asset_name,
                    profile.source_size_asset_name,
                ):
                    path = profile.asset_path(SKILL_ROOT, name)
                    self.assertTrue(path.is_file(), path)
                    self.assertFalse(path.is_symlink(), path)
                    data = path.read_bytes()
                    self.assertNotIn(b"\r", data)
                    self.assertTrue(data.endswith(b"\n"))
                    self.assertFalse(data.endswith(b"\n\n"))

    def test_profiles_do_not_share_anchors(self) -> None:
        self.assertNotEqual(
            CHINESE_PROFILE.development_rules_title,
            ENGLISH_PROFILE.development_rules_title,
        )
        self.assertNotEqual(
            CHINESE_PROFILE.mvp_status_key, ENGLISH_PROFILE.mvp_status_key
        )
        for profile in PROFILES:
            self.assertIs(profile_for(profile.language), profile)

    def test_threshold_regex_covers_both_languages(self) -> None:
        expected_hits = (
            "超过 300 行的文件",
            "约 240 行",
            "300 行阈值",
            "files over 300 lines",
            "more than 300 lines",
            "exceeds 300 lines",
            "at least 240 lines",
            "keep functions under 50 lines",
            "a 300-line limit",
            "> 300 lines",
        )
        expected_misses = (
            "5000 lines of logs",
            "3000 行日志",
            "the 12 lines",
            "1240 lines",
        )
        for text in expected_hits:
            with self.subTest(text=text):
                self.assertIsNotNone(THRESHOLD_RE.search(text))
        for text in expected_misses:
            with self.subTest(text=text):
                self.assertIsNone(THRESHOLD_RE.search(text))


if __name__ == "__main__":
    unittest.main()
