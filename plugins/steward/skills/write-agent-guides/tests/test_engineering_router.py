from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = SKILL_ROOT.parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
PROJECT_DOCS_SCRIPTS = SKILL_ROOT.parent / "write-project-docs" / "scripts"
for directory in (SCRIPTS, PROJECT_DOCS_SCRIPTS):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import update_agents_navigation as navigation_update  # noqa: E402
import update_engineering_router as router_update  # noqa: E402
from invariant_contract import ProfileSelection  # noqa: E402

UPDATE = SCRIPTS / "update_engineering_router.py"
VALIDATE = SCRIPTS / "validate_engineering_router.py"
INV_ID = "INV-PROJECT-0123456789AB"
START = "<!-- write-agent-guides:engineering-router:start -->"
END = "<!-- write-agent-guides:engineering-router:end -->"
DOCS_BLOCK = (
    "<!-- write-project-docs:document-navigation:start -->\n"
    "## Project Documentation Navigation\n\n"
    "Preserve me.\n"
    "<!-- write-project-docs:document-navigation:end -->\n"
)


class EngineeringRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        docs = self.root / "docs"
        docs.mkdir()
        for relative in ("README.md", "STATUS.md", "CONTRIBUTING.md"):
            (self.root / relative).write_text(f"# {relative}\n", encoding="utf-8")
        (docs / "README.md").write_text("# Docs\n", encoding="utf-8")
        (docs / "product.md").write_text("# Product\n", encoding="utf-8")
        self.authority = docs / "architecture.md"
        self.authority.write_text(
            '# Architecture\n\n<a id="inv-project-0123456789ab"></a>\nRule.\n',
            encoding="utf-8",
        )
        (docs / "development-rules.md").write_text(
            "# Development Rules\n", encoding="utf-8"
        )
        (docs / "source-code-size-and-responsibility-rules.md").write_text(
            "# Size\n", encoding="utf-8"
        )
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "test_architecture.py").write_text("# evidence\n", encoding="utf-8")
        (self.root / "AGENTS.md").write_text(
            "# Agents\n\n" + DOCS_BLOCK, encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def binding(self):
        digest = "sha256:" + hashlib.sha256(self.authority.read_bytes()).hexdigest()
        return {
            "invariantId": INV_ID,
            "source": {"kind": "project", "version": "1", "digest": digest},
            "scopes": ["."],
            "trigger": "changing architecture",
            "authority": {
                "path": "docs/architecture.md",
                "anchor": "inv-project-0123456789ab",
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

    def write_map(self, value=None) -> Path:
        directory = self.root / ".steward"
        directory.mkdir(exist_ok=True)
        path = directory / "invariants.json"
        document = value or {"schemaVersion": 1, "bindings": [self.binding()]}
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        return path

    def run_script(self, script: Path, *options: str):
        return subprocess.run(
            [sys.executable, str(script), str(self.root), *options],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_absent_index_is_byte_for_byte_legacy_noop(self) -> None:
        agents = self.root / "AGENTS.md"
        before = agents.read_bytes()
        result = self.run_script(UPDATE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("absent", result.stdout)
        self.assertEqual(agents.read_bytes(), before)
        validation = self.run_script(VALIDATE)
        self.assertEqual(validation.returncode, 0, validation.stdout)

    def test_insert_validate_and_idempotently_replace_router(self) -> None:
        self.write_map()
        first = self.run_script(UPDATE)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        agents = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(agents.count(START), 1)
        self.assertEqual(agents.count(END), 1)
        self.assertIn("| Trigger | Authority | Invariant IDs | Validation entry |", agents)
        self.assertIn(INV_ID, agents)
        self.assertIn(DOCS_BLOCK, agents)
        before = agents.encode()
        second = self.run_script(UPDATE)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("unchanged", second.stdout)
        self.assertEqual((self.root / "AGENTS.md").read_bytes(), before)
        validation = self.run_script(VALIDATE)
        self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)

    def test_chinese_asset_uses_same_owned_markers(self) -> None:
        binding = self.binding()
        renames = {
            "product.md": "产品说明.md",
            "architecture.md": "架构说明.md",
            "development-rules.md": "开发规范.md",
            "source-code-size-and-responsibility-rules.md": "源代码规模与职责规则.md",
        }
        for old_name, new_name in renames.items():
            (self.root / "docs" / old_name).rename(self.root / "docs" / new_name)
        binding["authority"]["path"] = "docs/架构说明.md"
        self.write_map({"schemaVersion": 1, "bindings": [binding]})
        result = self.run_script(UPDATE, "--language", "zh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        agents = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("| 触发条件 | 权威来源 | 不变量 ID | 验证入口 |", agents)
        self.assertIn(START, agents)

    def test_language_override_must_match_canonical_documents(self) -> None:
        self.write_map()
        agents = self.root / "AGENTS.md"
        before = agents.read_bytes()
        result = self.run_script(UPDATE, "--language", "zh")
        self.assertEqual(result.returncode, 1)
        self.assertIn("conflicts", result.stdout)
        self.assertEqual(agents.read_bytes(), before)

    def test_orphan_or_malformed_router_never_writes(self) -> None:
        agents_path = self.root / "AGENTS.md"
        agents_path.write_text(
            "# Agents\n\n" + START + "\n## Engineering Router\n" + END + "\n",
            encoding="utf-8",
        )
        before = agents_path.read_bytes()
        orphan = self.run_script(UPDATE)
        self.assertEqual(orphan.returncode, 1)
        self.assertEqual(agents_path.read_bytes(), before)

        self.write_map()
        agents_path.write_text(
            "# Agents\n\n" + START + "\n" + START + "\n" + END + "\n",
            encoding="utf-8",
        )
        before = agents_path.read_bytes()
        malformed = self.run_script(UPDATE)
        self.assertEqual(malformed.returncode, 1)
        self.assertEqual(agents_path.read_bytes(), before)

    def test_router_never_overwrites_navigation_or_duplicate_heading(self) -> None:
        self.write_map()
        agents_path = self.root / "AGENTS.md"
        nested = (
            "# Agents\n\n"
            + START
            + "\n## Engineering Router\n\n"
            + DOCS_BLOCK
            + END
            + "\n"
        )
        agents_path.write_text(nested, encoding="utf-8")
        before = agents_path.read_bytes()
        result = self.run_script(UPDATE)
        self.assertEqual(result.returncode, 1)
        self.assertIn("must not overlap", result.stdout)
        self.assertEqual(agents_path.read_bytes(), before)

        self.assertEqual((self.run_script(VALIDATE)).returncode, 1)

        agents_path.write_text(
            "# Agents\n\n" + DOCS_BLOCK,
            encoding="utf-8",
        )
        self.assertEqual(self.run_script(UPDATE).returncode, 0)
        with_duplicate = agents_path.read_text(encoding="utf-8")
        agents_path.write_text(
            with_duplicate + "\n## Engineering Router\n\nStale.\n",
            encoding="utf-8",
        )
        before = agents_path.read_bytes()
        duplicate = self.run_script(UPDATE)
        self.assertEqual(duplicate.returncode, 1)
        self.assertIn("duplicate unowned", duplicate.stdout)
        self.assertEqual(agents_path.read_bytes(), before)
        self.assertEqual(self.run_script(VALIDATE).returncode, 1)

    def test_router_rejects_foreign_managed_block_nested_inside_router(self) -> None:
        self.write_map()
        agents_path = self.root / "AGENTS.md"
        agents_path.write_text(
            "# Agents\n\n"
            + START
            + "\n## Engineering Router\n\n"
            "<!-- foreign-skill:owned:start -->\n"
            "Preserve this foreign content.\n"
            "<!-- foreign-skill:owned:end -->\n"
            + END
            + "\n",
            encoding="utf-8",
        )
        before = agents_path.read_bytes()

        result = self.run_script(UPDATE)

        self.assertEqual(result.returncode, 1)
        self.assertIn("不得嵌套或重叠", result.stdout)
        self.assertEqual(agents_path.read_bytes(), before)

    def test_router_rejects_insertion_into_unclosed_hidden_blocks(self) -> None:
        self.write_map()
        agents_path = self.root / "AGENTS.md"
        tails = {
            "backtick-fence": "```text\nunclosed\n",
            "tilde-fence": "~~~text\nunclosed\n",
            "script": "<script>\nunclosed\n",
            "pre": "<pre>\nunclosed\n",
            "comment": "<!-- unclosed\n",
        }
        for name, tail in tails.items():
            with self.subTest(name=name):
                agents_path.write_text("# Agents\n\n" + tail, encoding="utf-8")
                before = agents_path.read_bytes()

                result = self.run_script(UPDATE)

                self.assertEqual(result.returncode, 1)
                self.assertEqual(agents_path.read_bytes(), before)

    def test_router_markers_hidden_in_a_fence_are_rejected_without_writing(self) -> None:
        self.write_map()
        agents_path = self.root / "AGENTS.md"
        agents_path.write_text(
            "# Agents\n\n```markdown\n" + START + "\n" + END + "\n```\n",
            encoding="utf-8",
        )
        before = agents_path.read_bytes()
        result = self.run_script(UPDATE)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(agents_path.read_bytes(), before)

    def test_bad_contract_and_missing_agents_are_fail_closed(self) -> None:
        path = self.write_map({"schemaVersion": 2, "bindings": []})
        agents = self.root / "AGENTS.md"
        before = agents.read_bytes()
        result = self.run_script(UPDATE)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(agents.read_bytes(), before)
        path.unlink()
        self.write_map()
        agents.unlink()
        missing = self.run_script(UPDATE)
        self.assertEqual(missing.returncode, 1)

    def test_validator_detects_router_drift(self) -> None:
        self.write_map()
        self.assertEqual(self.run_script(UPDATE).returncode, 0)
        agents = self.root / "AGENTS.md"
        agents.write_text(
            agents.read_text(encoding="utf-8").replace(
                "changing architecture", "changing drifted architecture"
            ),
            encoding="utf-8",
        )
        result = self.run_script(VALIDATE)
        self.assertEqual(result.returncode, 1)
        self.assertIn("drifted", result.stdout)

    def test_replacement_preserves_crlf_outside_router(self) -> None:
        self.write_map()
        self.assertEqual(self.run_script(UPDATE).returncode, 0)
        agents = self.root / "AGENTS.md"
        text = agents.read_text(encoding="utf-8")
        start = text.index(START)
        end = text.index(END) + len(END) + 1
        prefix = (
            "# Agents\r\n\r\nLocal CRLF.\r\n\r\n"
            + DOCS_BLOCK.replace("\n", "\r\n")
            + "\r\n"
        )
        suffix = "\r\n## Tail\r\n\r\nKeep CRLF.\r\n"
        drifted_router = text[start:end].replace(
            "changing architecture", "changing drifted architecture"
        )
        agents.write_bytes(prefix.encode() + drifted_router.encode() + suffix.encode())
        result = self.run_script(UPDATE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        updated = agents.read_bytes()
        self.assertTrue(updated.startswith(prefix.encode()))
        self.assertTrue(updated.endswith(suffix.encode()))
        self.assertNotIn(b"changing drifted architecture", updated)

    def test_router_cas_preserves_external_target_change(self) -> None:
        self.write_map()
        agents = self.root / "AGENTS.md"
        real_write = router_update.write_atomically

        def inject_change(*args, **kwargs):
            agents.write_text("concurrent user change\n", encoding="utf-8")
            return real_write(*args, **kwargs)

        output = io.StringIO()
        with (
            mock.patch.object(
                router_update, "write_atomically", side_effect=inject_change
            ),
            mock.patch.object(
                sys,
                "argv",
                ["update_engineering_router.py", str(self.root)],
            ),
            mock.patch("sys.stdout", output),
        ):
            result = router_update.main()

        self.assertEqual(result, 1)
        self.assertIn("写入期间发生变化", output.getvalue())
        self.assertEqual(agents.read_text(encoding="utf-8"), "concurrent user change\n")

    def test_router_cas_binds_invariant_and_canonical_inputs(self) -> None:
        map_path = self.write_map()
        agents = self.root / "AGENTS.md"
        before = agents.read_bytes()
        real_write = router_update.write_atomically

        def inject_changes(*args, **kwargs):
            document = json.loads(map_path.read_text(encoding="utf-8"))
            document["bindings"][0]["trigger"] = "changed trigger"
            map_path.write_text(json.dumps(document) + "\n", encoding="utf-8")
            self.authority.write_text("# changed authority\n", encoding="utf-8")
            return real_write(*args, **kwargs)

        with (
            mock.patch.object(
                router_update, "write_atomically", side_effect=inject_changes
            ),
            mock.patch.object(
                sys,
                "argv",
                ["update_engineering_router.py", str(self.root)],
            ),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            result = router_update.main()

        self.assertEqual(result, 1)
        self.assertEqual(agents.read_bytes(), before)

    def test_router_cas_binds_evidence_inputs(self) -> None:
        self.write_map()
        agents = self.root / "AGENTS.md"
        before = agents.read_bytes()
        evidence = self.root / "tests" / "test_architecture.py"
        real_write = router_update.write_atomically

        def inject_change(*args, **kwargs):
            evidence.write_text("# changed evidence\n", encoding="utf-8")
            return real_write(*args, **kwargs)

        with (
            mock.patch.object(
                router_update, "write_atomically", side_effect=inject_change
            ),
            mock.patch.object(
                sys,
                "argv",
                ["update_engineering_router.py", str(self.root)],
            ),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            result = router_update.main()

        self.assertEqual(result, 1)
        self.assertEqual(agents.read_bytes(), before)

    def test_router_cas_binds_profile_package_and_selection_inputs(self) -> None:
        map_path = self.write_map()
        base_map = router_update.load_invariant_map(map_path)
        source = router_update.ProfileSource(
            "profile",
            "python",
            "1.0.0",
            "sha256:" + "0" * 64,
        )
        profile_map = replace(
            base_map,
            bindings=(replace(base_map.bindings[0], source=source),),
            profile_selection=ProfileSelection(
                ".steward/profile-selection.json",
                "sha256:" + "1" * 64,
            ),
        )
        selection = self.root / ".steward" / "profile-selection.json"
        selection.write_text("{}\n", encoding="utf-8")
        bundled_profiles = (
            PLUGIN_ROOT / "references" / "architecture-profiles"
        )
        agents = self.root / "AGENTS.md"
        original = agents.read_bytes()

        for name, relative in {
            "catalog": "catalog.json",
            "profile": "profiles/python.json",
            "selection": None,
        }.items():
            with self.subTest(name=name):
                profiles_root = self.root / f"architecture-profiles-{name}"
                shutil.copytree(bundled_profiles, profiles_root)
                agents.write_bytes(original)
                selection.write_text("{}\n", encoding="utf-8")
                changed = selection if relative is None else profiles_root / relative
                real_write = router_update.write_atomically

                def inject_change(*args, **kwargs):
                    changed.write_bytes(changed.read_bytes() + b" ")
                    return real_write(*args, **kwargs)

                with (
                    mock.patch.object(
                        router_update,
                        "load_invariant_map",
                        return_value=profile_map,
                    ),
                    mock.patch.object(
                        router_update,
                        "write_atomically",
                        side_effect=inject_change,
                    ),
                    mock.patch.object(
                        sys,
                        "argv",
                        [
                            "update_engineering_router.py",
                            str(self.root),
                            "--profiles-root",
                            str(profiles_root),
                        ],
                    ),
                    mock.patch("sys.stdout", io.StringIO()),
                ):
                    result = router_update.main()

                self.assertEqual(result, 1)
                self.assertEqual(agents.read_bytes(), original)

    def test_router_noop_revalidates_invariant_source(self) -> None:
        map_path = self.write_map()
        self.assertEqual(self.run_script(UPDATE).returncode, 0)
        agents = self.root / "AGENTS.md"
        before = agents.read_bytes()
        real_find = router_update.find_invariant_map
        calls = 0

        def mutate_before_noop_validation(root: Path):
            nonlocal calls
            calls += 1
            if calls == 2:
                document = json.loads(map_path.read_text(encoding="utf-8"))
                document["bindings"][0]["trigger"] = "changed during no-op"
                map_path.write_text(json.dumps(document) + "\n", encoding="utf-8")
            return real_find(root)

        with (
            mock.patch.object(
                router_update,
                "find_invariant_map",
                side_effect=mutate_before_noop_validation,
            ),
            mock.patch.object(
                sys,
                "argv",
                ["update_engineering_router.py", str(self.root)],
            ),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            result = router_update.main()

        self.assertEqual(result, 1)
        self.assertEqual(agents.read_bytes(), before)

    def test_router_noop_revalidates_evidence_source(self) -> None:
        self.write_map()
        self.assertEqual(self.run_script(UPDATE).returncode, 0)
        agents = self.root / "AGENTS.md"
        before = agents.read_bytes()
        evidence = self.root / "tests" / "test_architecture.py"
        real_find = router_update.find_invariant_map
        calls = 0

        def mutate_before_noop_validation(root: Path):
            nonlocal calls
            calls += 1
            if calls == 2:
                evidence.write_text(
                    "# changed during no-op\n", encoding="utf-8"
                )
            return real_find(root)

        with (
            mock.patch.object(
                router_update,
                "find_invariant_map",
                side_effect=mutate_before_noop_validation,
            ),
            mock.patch.object(
                sys,
                "argv",
                ["update_engineering_router.py", str(self.root)],
            ),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            result = router_update.main()

        self.assertEqual(result, 1)
        self.assertEqual(agents.read_bytes(), before)

    def test_navigation_and_router_writers_share_cas_locking(self) -> None:
        self.assertIs(
            navigation_update.write_atomically,
            router_update.write_atomically,
        )
        target = self.root / "shared-AGENTS.md"
        target.write_text("original\n", encoding="utf-8")
        expected = router_update.read_snapshot(target)
        barrier = threading.Barrier(3)
        results: list[str] = []

        def run(writer, value: str) -> None:
            barrier.wait()
            try:
                writer(target, value, expected, lambda: None)
            except ValueError:
                results.append("rejected")
            else:
                results.append("written")

        first = threading.Thread(
            target=run,
            args=(navigation_update.write_atomically, "navigation\n"),
        )
        second = threading.Thread(
            target=run,
            args=(router_update.write_atomically, "router\n"),
        )
        first.start()
        second.start()
        barrier.wait()
        first.join(timeout=10)
        second.join(timeout=10)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertCountEqual(results, ["written", "rejected"])
        self.assertIn(target.read_text(encoding="utf-8"), {"navigation\n", "router\n"})


if __name__ == "__main__":
    unittest.main()
