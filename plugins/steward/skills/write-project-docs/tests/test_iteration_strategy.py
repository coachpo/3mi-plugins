from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import safe_write  # noqa: E402
from canonical_paths import CANONICAL_DOCUMENTS, render_template  # noqa: E402
from doc_anchors import CHINESE_PROFILE, ENGLISH_PROFILE  # noqa: E402
from iteration_strategy import (  # noqa: E402
    END_MARKER,
    METADATA_PREFIX,
    METADATA_SUFFIX,
    START_MARKER,
    normalize_status_for_strategy,
    parse_iteration_strategy_handoff,
    validate_iteration_strategy_document,
)
from managed_blocks import locate_managed_block  # noqa: E402
from update_iteration_strategy import read_snapshot, write_atomically  # noqa: E402

UPDATE_STRATEGY = SCRIPTS / "update_iteration_strategy.py"
UPDATE_CONTRIBUTING = SCRIPTS / "update_contributing.py"
UPDATE_DEVELOPMENT = SCRIPTS / "update_development_rules.py"
VALIDATOR = SCRIPTS / "validate_project_docs.py"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def run_python(
    script: Path,
    root: Path,
    *options: str,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(script), str(root), *options],
        input=input_text,
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )


def strategy_handoff(profile, *, include_defer: bool = True) -> dict[str, object]:
    if profile is CHINESE_PROFILE:
        values = {
            "strategy": "项目处于开发中，本轮以可重复演示核心流程为目标。",
            "doNow": ["打通并验证演示所需的端到端流程。"],
            "defer": [
                "可推迟通用压力测试；依据：当前演示验收不含性能要求；"
                "重评：验收加入吞吐、并发或延迟指标，或出现外部流量时。"
            ],
            "guardrails": ["不扩大当前用户授权或覆盖明确禁止事项。"],
            "rederiveWhen": ["演示目标加入性能要求或出现真实负载时。"],
        }
    else:
        values = {
            "strategy": (
                "The project is in development; this iteration targets a repeatable "
                "demonstration of the core flow."
            ),
            "doNow": ["Complete and verify the end-to-end demonstration flow."],
            "defer": [
                "May defer generic load testing; basis: current demo acceptance has "
                "no performance target; re-evaluate when acceptance adds throughput, "
                "concurrency, or latency metrics, or external traffic appears."
            ],
            "guardrails": [
                "Do not expand current user authorization or override explicit "
                "prohibitions."
            ],
            "rederiveWhen": [
                "Re-derive when performance enters the demo goal or real load appears."
            ],
        }
    if not include_defer:
        values["defer"] = []
    return {"schemaVersion": 1, "language": profile.language.value, **values}


def build_project(root: Path, profile) -> dict[str, str]:
    selected = {
        document.key: document.path_for(profile.language)
        for document in CANONICAL_DOCUMENTS
    }
    write_text(root / "README.md", "# Demo\n")
    write_text(
        root / "STATUS.md",
        "# Status\n\n" + profile.mvp_status_enabled_line + "\n",
    )
    write_text(root / "CONTRIBUTING.md", "# Contributing\n")
    write_text(root / "docs" / "README.md", "# Documentation\n")
    write_text(root / selected["product"], "# Product\n")
    write_text(root / selected["architecture"], "# Architecture\n")
    write_text(
        root / selected["development_rules"],
        profile.development_rules_title + "\n",
    )
    source_asset = profile.asset_path(SKILL_ROOT, profile.source_size_asset_name)
    (root / selected["source_size_rules"]).write_bytes(
        render_template(source_asset.read_bytes(), selected, "source-size")
    )
    for script in (UPDATE_DEVELOPMENT, UPDATE_CONTRIBUTING):
        result = run_python(script, root)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
    return selected


def strategy_span(text: str):
    span = locate_managed_block(text, START_MARKER, END_MARKER, "test strategy")
    if span is None:
        raise AssertionError("strategy block missing")
    return span


def replace_strategy_body(text: str, transform) -> str:
    span = strategy_span(text)
    block = text[span.start : span.end]
    lines = block.splitlines(keepends=True)
    body = "".join(lines[2:-1])
    updated_body = transform(body)
    if not updated_body.endswith("\n"):
        raise AssertionError("test transform must retain a trailing LF")
    metadata_line = lines[1].rstrip("\n")
    metadata = json.loads(metadata_line[len(METADATA_PREFIX) : -len(METADATA_SUFFIX)])
    metadata["contentSha256"] = (
        "sha256:" + hashlib.sha256(updated_body.encode("utf-8")).hexdigest()
    )
    rewritten_metadata = (
        METADATA_PREFIX
        + json.dumps(
            metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        + METADATA_SUFFIX
        + "\n"
    )
    updated_block = lines[0] + rewritten_metadata + updated_body + lines[-1]
    return text[: span.start] + updated_block + text[span.end :]


def remove_first_item(body: str, title: str) -> str:
    prefix = f"### {title}\n\n"
    start = body.index(prefix) + len(prefix)
    end = body.index("\n", start) + 1
    if not body[start:end].startswith("- "):
        raise AssertionError("expected a rendered list item")
    return body[:start] + body[end:]


class IterationStrategyPipelineTests(unittest.TestCase):
    def test_bilingual_insert_idempotency_and_full_validation(self) -> None:
        for profile in (CHINESE_PROFILE, ENGLISH_PROFILE):
            with (
                self.subTest(language=profile.language),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                build_project(root, profile)
                before = (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
                shared_before = before[
                    before.index(
                        "<!-- write-project-docs:shared-contributing:start -->"
                    ) :
                ]
                payload = json.dumps(strategy_handoff(profile), ensure_ascii=False)

                first = run_python(UPDATE_STRATEGY, root, input_text=payload)
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                updated = (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
                self.assertLess(
                    updated.index(START_MARKER),
                    updated.index(
                        "<!-- write-project-docs:shared-contributing:start -->"
                    ),
                )
                self.assertIn(f"## {profile.iteration_strategy_title}\n", updated)
                self.assertTrue(updated.endswith(shared_before))
                if profile is ENGLISH_PROFILE:
                    self.assertIn(
                        "Derived from (the source documents remain authoritative): ",
                        updated,
                    )
                    self.assertNotIn("authoritative)：", updated)

                snapshot = (root / "CONTRIBUTING.md").read_bytes()
                second = run_python(UPDATE_STRATEGY, root, input_text=payload)
                self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
                self.assertIn("未修改", second.stdout)
                self.assertEqual((root / "CONTRIBUTING.md").read_bytes(), snapshot)

                validation = run_python(VALIDATOR, root, "--strict")
                self.assertEqual(
                    validation.returncode,
                    0,
                    validation.stdout + validation.stderr,
                )

    def test_optional_defer_section_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = build_project(root, ENGLISH_PROFILE)
            payload = json.dumps(strategy_handoff(ENGLISH_PROFILE, include_defer=False))
            result = run_python(UPDATE_STRATEGY, root, input_text=payload)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            text = (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
            self.assertNotIn("### Not Pursued This Iteration", text)
            validate_iteration_strategy_document(text, root, selected, ENGLISH_PROFILE)

    def test_comparison_delimiters_are_escaped_as_markdown_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_project(root, ENGLISH_PROFILE)
            handoff = strategy_handoff(ENGLISH_PROFILE)
            handoff["doNow"] = ["Demonstrate p95 < 200 ms and throughput > 10 rps."]
            result = run_python(
                UPDATE_STRATEGY,
                root,
                input_text=json.dumps(handoff, ensure_ascii=False),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            text = (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
            self.assertIn("p95 &lt; 200 ms", text)
            self.assertIn("throughput &gt; 10 rps", text)

    def test_maximum_length_escaped_text_remains_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_project(root, ENGLISH_PROFILE)
            handoff = strategy_handoff(ENGLISH_PROFILE)
            handoff["doNow"] = ["&" * 2_000]
            result = run_python(
                UPDATE_STRATEGY,
                root,
                input_text=json.dumps(handoff, ensure_ascii=False),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            text = (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
            self.assertIn("- " + "&amp;" * 2_000 + "\n", text)

            validation = run_python(VALIDATOR, root, "--strict")
            self.assertEqual(
                validation.returncode,
                0,
                validation.stdout + validation.stderr,
            )

    def test_strategy_content_may_reference_a_bound_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_project(root, ENGLISH_PROFILE)
            handoff = strategy_handoff(ENGLISH_PROFILE)
            handoff["doNow"] = ["Verify [`STATUS.md`](STATUS.md) before delivery."]
            result = run_python(
                UPDATE_STRATEGY,
                root,
                input_text=json.dumps(handoff, ensure_ascii=False),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            validation = run_python(VALIDATOR, root, "--strict")
            self.assertEqual(
                validation.returncode,
                0,
                validation.stdout + validation.stderr,
            )

    def test_fence_openers_are_rejected_at_handoff_boundary(self) -> None:
        for opener in ("```", "```python", "~~~", "~~~~text"):
            with self.subTest(opener=opener):
                payload = strategy_handoff(ENGLISH_PROFILE)
                payload["strategy"] = opener
                with self.assertRaisesRegex(ValueError, "围栏代码块"):
                    parse_iteration_strategy_handoff(
                        json.dumps(payload).encode("utf-8"),
                        ENGLISH_PROFILE.language,
                    )

    def test_non_heading_and_non_fence_prefixes_remain_valid(self) -> None:
        for strategy in ("#123 must be fixed", "```foo`bar"):
            with (
                self.subTest(strategy=strategy),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                build_project(root, ENGLISH_PROFILE)
                payload = strategy_handoff(ENGLISH_PROFILE)
                payload["strategy"] = strategy
                result = run_python(
                    UPDATE_STRATEGY,
                    root,
                    input_text=json.dumps(payload, ensure_ascii=False),
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                validation = run_python(VALIDATOR, root, "--strict")
                self.assertEqual(
                    validation.returncode,
                    0,
                    validation.stdout + validation.stderr,
                )

    def test_remove_is_idempotent_and_preserves_shared_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_project(root, CHINESE_PROFILE)
            payload = json.dumps(strategy_handoff(CHINESE_PROFILE), ensure_ascii=False)
            self.assertEqual(
                run_python(UPDATE_STRATEGY, root, input_text=payload).returncode,
                0,
            )
            text = (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
            shared_marker = "<!-- write-project-docs:shared-contributing:start -->"
            shared_before = text[text.index(shared_marker) :]

            removed = run_python(UPDATE_STRATEGY, root, "--remove")
            self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
            actual = (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
            self.assertNotIn(START_MARKER, actual)
            self.assertTrue(actual.endswith(shared_before))
            snapshot = (root / "CONTRIBUTING.md").read_bytes()
            absent = run_python(UPDATE_STRATEGY, root, "--remove")
            self.assertEqual(absent.returncode, 0, absent.stdout + absent.stderr)
            self.assertIn("未修改", absent.stdout)
            self.assertEqual((root / "CONTRIBUTING.md").read_bytes(), snapshot)

    def test_existing_strategy_reprojects_before_shared_after_source_change(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = build_project(root, CHINESE_PROFILE)
            payload = json.dumps(strategy_handoff(CHINESE_PROFILE), ensure_ascii=False)
            first = run_python(UPDATE_STRATEGY, root, input_text=payload)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)

            write_text(root / selected["product"], "# Product\n\n演示目标已刷新。\n")
            write_text(
                root / "STATUS.md",
                "# Status\n\n" + CHINESE_PROFILE.mvp_status_disabled_line + "\n",
            )
            reprojected = run_python(UPDATE_STRATEGY, root, input_text=payload)
            self.assertEqual(
                reprojected.returncode,
                0,
                reprojected.stdout + reprojected.stderr,
            )
            shared = run_python(UPDATE_CONTRIBUTING, root)
            self.assertEqual(shared.returncode, 0, shared.stdout + shared.stderr)
            validation = run_python(VALIDATOR, root, "--strict")
            self.assertEqual(
                validation.returncode,
                0,
                validation.stdout + validation.stderr,
            )

    def test_preserves_crlf_outside_the_independent_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_project(root, CHINESE_PROFILE)
            contributing = root / "CONTRIBUTING.md"
            text = contributing.read_text(encoding="utf-8")
            shared_marker = "<!-- write-project-docs:shared-contributing:start -->"
            shared = text[text.index(shared_marker) :]
            original = "# Contributing\r\n\r\nLocal.\r\n\r\n" + shared
            write_text(contributing, original)
            payload = json.dumps(strategy_handoff(CHINESE_PROFILE), ensure_ascii=False)
            inserted = run_python(UPDATE_STRATEGY, root, input_text=payload)
            self.assertEqual(inserted.returncode, 0, inserted.stdout + inserted.stderr)
            self.assertTrue(
                contributing.read_bytes().startswith(
                    b"# Contributing\r\n\r\nLocal.\r\n\r\n"
                )
            )
            removed = run_python(UPDATE_STRATEGY, root, "--remove")
            self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
            self.assertEqual(contributing.read_bytes(), original.encode("utf-8"))


class IterationStrategyOrthogonalityTests(unittest.TestCase):
    def test_all_mvp_states_leave_strategy_bytes_and_source_digest_unchanged(
        self,
    ) -> None:
        for profile in (CHINESE_PROFILE, ENGLISH_PROFILE):
            with (
                self.subTest(language=profile.language),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                selected = build_project(root, profile)
                payload = json.dumps(strategy_handoff(profile), ensure_ascii=False)
                result = run_python(UPDATE_STRATEGY, root, input_text=payload)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                initial_text = (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
                span = strategy_span(initial_text)
                expected_block = initial_text[span.start : span.end]
                states = (
                    profile.mvp_status_enabled_line,
                    profile.mvp_status_disabled_line,
                    None,
                )
                for state in states:
                    status = "# Status\n\n" + ((state + "\n") if state else "")
                    write_text(root / "STATUS.md", status)
                    mvp_update = run_python(UPDATE_CONTRIBUTING, root)
                    self.assertEqual(
                        mvp_update.returncode,
                        0,
                        mvp_update.stdout + mvp_update.stderr,
                    )
                    actual = (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
                    actual_span = strategy_span(actual)
                    self.assertEqual(
                        actual[actual_span.start : actual_span.end], expected_block
                    )
                    validate_iteration_strategy_document(
                        actual, root, selected, profile
                    )

    def test_status_normalization_removes_only_visible_exact_control_line(
        self,
    ) -> None:
        for profile in (CHINESE_PROFILE, ENGLISH_PROFILE):
            with self.subTest(language=profile.language):
                control = profile.mvp_status_enabled_line
                text = (
                    "before\n"
                    "```text\n"
                    f"{control}\n"
                    "```\n\n"
                    "<div>\n"
                    f"{control}\n"
                    "</div>\n\n"
                    f"{control}\n"
                    "after\n"
                )
                normalized = normalize_status_for_strategy(
                    text.encode("utf-8"), profile.language
                ).decode("utf-8")
                self.assertEqual(normalized.count(control), 2)
                self.assertIn(f"```text\n{control}\n```", normalized)
                self.assertIn(f"<div>\n{control}\n</div>", normalized)
                self.assertNotIn(f"\n{control}\nafter", normalized)

    def test_enabled_disabled_and_absent_have_same_normalized_digest(self) -> None:
        for profile in (CHINESE_PROFILE, ENGLISH_PROFILE):
            with self.subTest(language=profile.language):
                variants = (
                    f"# Status\n\n{profile.mvp_status_enabled_line}\n",
                    f"# Status\n\n{profile.mvp_status_disabled_line}\n",
                    "# Status\n\n",
                )
                normalized = {
                    normalize_status_for_strategy(
                        item.encode("utf-8"), profile.language
                    )
                    for item in variants
                }
                self.assertEqual(len(normalized), 1)

    def test_absent_status_without_terminal_lf_is_orthogonal(self) -> None:
        for profile in (CHINESE_PROFILE, ENGLISH_PROFILE):
            with self.subTest(language=profile.language):
                absent = normalize_status_for_strategy(b"# Status", profile.language)
                enabled = normalize_status_for_strategy(
                    ("# Status\n" + profile.mvp_status_enabled_line + "\n").encode(
                        "utf-8"
                    ),
                    profile.language,
                )
                self.assertEqual(absent, enabled)


class IterationStrategyFailureTests(unittest.TestCase):
    def test_strict_handoff_rejects_unknown_duplicate_and_mvp_fields(self) -> None:
        valid = strategy_handoff(CHINESE_PROFILE)
        cases = (
            {**valid, "unknown": True},
            {**valid, "mvpMode": "enabled"},
            {**valid, "language": "en"},
        )
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_iteration_strategy_handoff(
                        json.dumps(value, ensure_ascii=False).encode("utf-8"),
                        CHINESE_PROFILE.language,
                    )
        duplicate = (
            '{"schemaVersion":1,"schemaVersion":1,"language":"zh",'
            '"strategy":"s","doNow":["d"],"defer":[],'
            '"guardrails":["g"],"rederiveWhen":["r"]}'
        )
        with self.assertRaises(ValueError):
            parse_iteration_strategy_handoff(
                duplicate.encode("utf-8"), CHINESE_PROFILE.language
            )

    def test_strict_handoff_rejects_unicode_line_and_control_characters(self) -> None:
        unsafe = (
            "\v",
            "\f",
            "\x1c",
            "\x1d",
            "\x1e",
            "\x85",
            "\u2028",
            "\u2029",
            "\x1b",
            "\u202e",
        )
        for character in unsafe:
            with self.subTest(character=repr(character)):
                payload = strategy_handoff(CHINESE_PROFILE)
                payload["strategy"] = "safe" + character + "unsafe"
                with self.assertRaises(ValueError):
                    parse_iteration_strategy_handoff(
                        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                        CHINESE_PROFILE.language,
                    )

    def test_invalid_input_and_boundary_conflicts_never_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_project(root, CHINESE_PROFILE)
            contributing = root / "CONTRIBUTING.md"
            before = contributing.read_bytes()
            invalid = {**strategy_handoff(CHINESE_PROFILE), "mvp": True}
            result = run_python(
                UPDATE_STRATEGY,
                root,
                input_text=json.dumps(invalid, ensure_ascii=False),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(contributing.read_bytes(), before)

            write_text(
                contributing,
                before.decode("utf-8") + "\n## 当前迭代策略\n\n未托管。\n",
            )
            conflict_before = contributing.read_bytes()
            result = run_python(
                UPDATE_STRATEGY,
                root,
                input_text=json.dumps(
                    strategy_handoff(CHINESE_PROFILE), ensure_ascii=False
                ),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(contributing.read_bytes(), conflict_before)

    def test_overlap_partial_markers_and_source_symlink_never_write(self) -> None:
        for case in ("overlap", "partial", "source_symlink"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                selected = build_project(root, CHINESE_PROFILE)
                contributing = root / "CONTRIBUTING.md"
                original_text = contributing.read_text(encoding="utf-8")
                if case == "overlap":
                    write_text(
                        contributing,
                        START_MARKER + "\n" + original_text + END_MARKER + "\n",
                    )
                elif case == "partial":
                    write_text(contributing, original_text + "\n" + START_MARKER + "\n")
                else:
                    product = root / selected["product"]
                    product.unlink()
                    target = root / "real-product.md"
                    write_text(target, "# Product\n")
                    product.symlink_to(target)
                before = contributing.read_bytes()
                result = run_python(
                    UPDATE_STRATEGY,
                    root,
                    input_text=json.dumps(
                        strategy_handoff(CHINESE_PROFILE), ensure_ascii=False
                    ),
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(contributing.read_bytes(), before)

    def test_shared_updater_rejects_partial_strategy_marker_without_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_project(root, CHINESE_PROFILE)
            status = root / "STATUS.md"
            write_text(
                status,
                "# Status\n\n" + CHINESE_PROFILE.mvp_status_disabled_line + "\n",
            )
            contributing = root / "CONTRIBUTING.md"
            write_text(
                contributing,
                contributing.read_text(encoding="utf-8") + "\n" + START_MARKER + "\n",
            )
            before = contributing.read_bytes()
            result = run_python(UPDATE_CONTRIBUTING, root)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(contributing.read_bytes(), before)

    def test_rejects_strategy_after_shared_and_foreign_unmanaged_title(self) -> None:
        for case in ("after_shared", "foreign_title"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                build_project(root, CHINESE_PROFILE)
                contributing = root / "CONTRIBUTING.md"
                payload = json.dumps(
                    strategy_handoff(CHINESE_PROFILE), ensure_ascii=False
                )
                if case == "after_shared":
                    self.assertEqual(
                        run_python(
                            UPDATE_STRATEGY, root, input_text=payload
                        ).returncode,
                        0,
                    )
                    text = contributing.read_text(encoding="utf-8")
                    span = strategy_span(text)
                    block = text[span.start : span.end]
                    text = text[: span.start] + text[span.end :] + "\n" + block
                    write_text(contributing, text)
                else:
                    text = contributing.read_text(encoding="utf-8")
                    write_text(
                        contributing,
                        text + "\n## Current Iteration Strategy\n\nUnmanaged.\n",
                    )
                before = contributing.read_bytes()
                result = run_python(UPDATE_STRATEGY, root, input_text=payload)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(contributing.read_bytes(), before)

    def test_update_and_remove_reject_every_malformed_mvp_state_without_write(
        self,
    ) -> None:
        invalid_states = (
            (
                CHINESE_PROFILE.mvp_status_enabled_line
                + "\n"
                + CHINESE_PROFILE.mvp_status_enabled_line
                + "\n"
            ),
            (
                CHINESE_PROFILE.mvp_status_enabled_line
                + "\n"
                + CHINESE_PROFILE.mvp_status_disabled_line
                + "\n"
            ),
            "MVP 快速验证模式：未知\n",
            ENGLISH_PROFILE.mvp_status_enabled_line + "\n",
        )
        for operation in ("update", "remove"):
            for status in invalid_states:
                with (
                    self.subTest(operation=operation, status=status),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    root = Path(directory)
                    build_project(root, CHINESE_PROFILE)
                    payload = json.dumps(
                        strategy_handoff(CHINESE_PROFILE), ensure_ascii=False
                    )
                    self.assertEqual(
                        run_python(
                            UPDATE_STRATEGY, root, input_text=payload
                        ).returncode,
                        0,
                    )
                    write_text(root / "STATUS.md", "# Status\n\n" + status)
                    contributing = root / "CONTRIBUTING.md"
                    before = contributing.read_bytes()
                    result = (
                        run_python(UPDATE_STRATEGY, root, "--remove")
                        if operation == "remove"
                        else run_python(UPDATE_STRATEGY, root, input_text=payload)
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(contributing.read_bytes(), before)

    def test_existing_strategy_cannot_be_replaced_without_shared_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_project(root, CHINESE_PROFILE)
            payload = json.dumps(strategy_handoff(CHINESE_PROFILE), ensure_ascii=False)
            self.assertEqual(
                run_python(UPDATE_STRATEGY, root, input_text=payload).returncode,
                0,
            )
            contributing = root / "CONTRIBUTING.md"
            text = contributing.read_text(encoding="utf-8")
            shared = locate_managed_block(
                text,
                "<!-- write-project-docs:shared-contributing:start -->",
                "<!-- write-project-docs:shared-contributing:end -->",
                "test shared",
            )
            self.assertIsNotNone(shared)
            assert shared is not None
            write_text(contributing, text[: shared.start] + text[shared.end :])
            before = contributing.read_bytes()
            result = run_python(UPDATE_STRATEGY, root, input_text=payload)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("缺少共享区块", result.stdout)
            self.assertEqual(contributing.read_bytes(), before)

    def test_self_consistent_digest_cannot_hide_invalid_body_structure(self) -> None:
        for case in ("boundary", "do_now", "guardrail", "rederive"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                build_project(root, CHINESE_PROFILE)
                payload = json.dumps(
                    strategy_handoff(CHINESE_PROFILE), ensure_ascii=False
                )
                self.assertEqual(
                    run_python(UPDATE_STRATEGY, root, input_text=payload).returncode,
                    0,
                )
                contributing = root / "CONTRIBUTING.md"
                text = contributing.read_text(encoding="utf-8")
                sections = CHINESE_PROFILE.iteration_strategy_section_titles
                if case == "boundary":
                    transform = lambda body: body.replace(
                        next(
                            line for line in body.splitlines() if line.startswith("> ")
                        ),
                        "> 被篡改的边界。",
                        1,
                    )
                else:
                    section_index = {
                        "do_now": 0,
                        "guardrail": 2,
                        "rederive": 3,
                    }[case]
                    transform = lambda body, title=sections[section_index]: (
                        remove_first_item(body, title)
                    )
                write_text(contributing, replace_strategy_body(text, transform))
                validation = run_python(VALIDATOR, root, "--strict")
                self.assertNotEqual(validation.returncode, 0)
                self.assertIn("正文结构无效", validation.stdout)

    def test_insert_remove_round_trip_preserves_tight_prefix_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_project(root, CHINESE_PROFILE)
            contributing = root / "CONTRIBUTING.md"
            text = contributing.read_text(encoding="utf-8")
            shared = text.index("<!-- write-project-docs:shared-contributing:start -->")
            original = "# Contributing\n" + text[shared:]
            write_text(contributing, original)
            payload = json.dumps(strategy_handoff(CHINESE_PROFILE), ensure_ascii=False)
            self.assertEqual(
                run_python(UPDATE_STRATEGY, root, input_text=payload).returncode,
                0,
            )
            removed = run_python(UPDATE_STRATEGY, root, "--remove")
            self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
            self.assertEqual(contributing.read_text(encoding="utf-8"), original)

    def test_optimistic_compare_refuses_to_overwrite_concurrent_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "CONTRIBUTING.md"
            write_text(path, "original\n")
            expected = read_snapshot(path)
            write_text(path, "concurrent\n")
            with self.assertRaisesRegex(ValueError, "写入期间发生变化"):
                write_atomically(path, "replacement\n", expected, lambda: None)
            self.assertEqual(path.read_text(encoding="utf-8"), "concurrent\n")

    def test_coordinated_compare_rejects_changed_source_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "CONTRIBUTING.md"
            source = root / "STATUS.md"
            write_text(target, "original\n")
            write_text(source, "source\n")
            target_snapshot = read_snapshot(target)
            source_snapshot = read_snapshot(source)
            write_text(source, "changed\n")
            with self.assertRaisesRegex(ValueError, "STATUS.md.*写入期间发生变化"):
                write_atomically(
                    target,
                    "replacement\n",
                    target_snapshot,
                    lambda: None,
                    input_snapshots=((source, source_snapshot),),
                )
            self.assertEqual(target.read_text(encoding="utf-8"), "original\n")

    def test_hard_linked_input_alias_fails_without_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "CONTRIBUTING.md"
            source = root / "STATUS.md"
            write_text(target, "original\n")
            try:
                os.link(target, source)
            except OSError as error:  # pragma: no cover - filesystem capability
                self.skipTest(f"hard links unavailable: {error}")
            target_snapshot = read_snapshot(target)
            source_snapshot = read_snapshot(source)
            with self.assertRaisesRegex(ValueError, "硬链接别名"):
                write_atomically(
                    target,
                    "replacement\n",
                    target_snapshot,
                    lambda: None,
                    input_snapshots=((source, source_snapshot),),
                )
            self.assertEqual(target.read_text(encoding="utf-8"), "original\n")

    @unittest.skipIf(os.name == "nt", "POSIX fsync injection")
    def test_final_snapshot_check_follows_temporary_file_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "CONTRIBUTING.md"
            write_text(target, "original\n")
            expected = read_snapshot(target)
            real_fsync = safe_write.os.fsync
            injected = False

            def inject_change(descriptor: int) -> None:
                nonlocal injected
                real_fsync(descriptor)
                if not injected:
                    injected = True
                    write_text(target, "concurrent\n")

            with (
                mock.patch.object(safe_write.os, "fsync", side_effect=inject_change),
                self.assertRaisesRegex(ValueError, "写入期间发生变化"),
            ):
                write_atomically(target, "replacement\n", expected, lambda: None)
            self.assertEqual(target.read_text(encoding="utf-8"), "concurrent\n")

    @unittest.skipIf(os.name == "nt", "POSIX fsync injection")
    def test_fsync_failure_cleans_temporary_file_and_preserves_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "CONTRIBUTING.md"
            write_text(target, "original\n")
            expected = read_snapshot(target)
            with (
                mock.patch.object(
                    safe_write.os, "fsync", side_effect=OSError("injected fsync")
                ),
                self.assertRaisesRegex(OSError, "injected fsync"),
            ):
                write_atomically(target, "replacement\n", expected, lambda: None)
            self.assertEqual(target.read_text(encoding="utf-8"), "original\n")
            self.assertEqual(list(target.parent.glob(".CONTRIBUTING.md.*.tmp")), [])

    def test_precommit_validation_runs_again_immediately_before_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "CONTRIBUTING.md"
            write_text(target, "original\n")
            expected = read_snapshot(target)
            calls = 0

            def validate() -> None:
                nonlocal calls
                calls += 1

            write_atomically(target, "replacement\n", expected, validate)
            self.assertEqual(calls, 2)
            self.assertEqual(target.read_text(encoding="utf-8"), "replacement\n")

    def test_second_precommit_cannot_mutate_temporary_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "CONTRIBUTING.md"
            write_text(target, "original\n")
            expected = read_snapshot(target)
            calls = 0

            def mutate_temporary() -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    temporary = next(root.glob(".CONTRIBUTING.md.*.tmp"))
                    temporary.write_bytes(b"x" * 11 + b"\n")

            with self.assertRaisesRegex(ValueError, "临时文件"):
                write_atomically(target, "replacement\n", expected, mutate_temporary)
            self.assertEqual(target.read_text(encoding="utf-8"), "original\n")

    @unittest.skipIf(os.name == "nt", "POSIX mode semantics")
    def test_atomic_replace_preserves_target_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "CONTRIBUTING.md"
            write_text(target, "original\n")
            os.chmod(target, stat.S_IRUSR)
            expected = read_snapshot(target)
            write_atomically(target, "replacement\n", expected, lambda: None)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), stat.S_IRUSR)

    def test_post_replace_failure_reports_committed_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "CONTRIBUTING.md"
            write_text(target, "original\n")
            expected = read_snapshot(target)
            failure = safe_write.AtomicWriteDurabilityError("directory sync failed")
            with (
                mock.patch.object(
                    safe_write, "_fsync_parent_directory", side_effect=failure
                ),
                self.assertRaises(safe_write.AtomicWriteCommittedError),
            ):
                write_atomically(target, "replacement\n", expected, lambda: None)
            self.assertEqual(target.read_text(encoding="utf-8"), "replacement\n")

    @unittest.skipIf(os.name == "nt", "POSIX advisory-lock cleanup")
    def test_post_replace_unlock_failure_reports_committed_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "CONTRIBUTING.md"
            write_text(target, "original\n")
            expected = read_snapshot(target)
            with (
                mock.patch.object(
                    safe_write,
                    "_unlock_descriptor",
                    side_effect=OSError("injected unlock"),
                ),
                self.assertRaises(safe_write.AtomicWriteCommittedError),
            ):
                write_atomically(target, "replacement\n", expected, lambda: None)
            self.assertEqual(target.read_text(encoding="utf-8"), "replacement\n")

    def test_coordination_identity_normalizes_case_and_unicode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            first = parent / "CONTRIBUTING-É.md"
            second = parent / "contributing-é.MD"
            self.assertEqual(
                safe_write._coordination_identity(first),
                safe_write._coordination_identity(second),
            )
            with self.assertRaisesRegex(ValueError, "加锁前发生变化"):
                with safe_write._coordination_lock(first, expected_identity="0" * 64):
                    self.fail("mismatched coordination identity acquired")

    def test_coordination_identity_is_independent_of_tmpdir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "CONTRIBUTING.md"
            with mock.patch.object(
                safe_write.tempfile, "gettempdir", return_value="/tmp/first"
            ):
                first = safe_write._coordination_identity(target)
            with mock.patch.object(
                safe_write.tempfile, "gettempdir", return_value="/tmp/second"
            ):
                second = safe_write._coordination_identity(target)
            self.assertEqual(first, second)

    @unittest.skipIf(os.name == "nt", "POSIX fsync injection")
    def test_temporary_path_substitution_fails_before_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "CONTRIBUTING.md"
            decoy = root / "decoy.md"
            write_text(target, "original\n")
            write_text(decoy, "decoy\n")
            expected = read_snapshot(target)
            real_fsync = safe_write.os.fsync

            def substitute_temporary(descriptor: int) -> None:
                real_fsync(descriptor)
                temporary = next(root.glob(".CONTRIBUTING.md.*.tmp"))
                temporary.unlink()
                temporary.symlink_to(decoy)

            with (
                mock.patch.object(
                    safe_write.os, "fsync", side_effect=substitute_temporary
                ),
                self.assertRaisesRegex(ValueError, "临时文件"),
            ):
                write_atomically(target, "replacement\n", expected, lambda: None)
            self.assertEqual(target.read_text(encoding="utf-8"), "original\n")
            self.assertEqual(decoy.read_text(encoding="utf-8"), "decoy\n")
            self.assertFalse(any(root.glob(".CONTRIBUTING.md.*.tmp")))

    @unittest.skipIf(os.name == "nt", "POSIX directory-lock implementation")
    def test_coordination_parent_symlink_fails_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_parent = root / "real"
            real_parent.mkdir()
            target = real_parent / "CONTRIBUTING.md"
            write_text(target, "original\n")
            alias_parent = root / "alias"
            alias_parent.symlink_to(real_parent, target_is_directory=True)
            alias_target = alias_parent / target.name
            expected = read_snapshot(alias_target)

            with self.assertRaisesRegex(ValueError, "协调目标目录"):
                write_atomically(alias_target, "replacement\n", expected, lambda: None)
            self.assertEqual(target.read_text(encoding="utf-8"), "original\n")

    def test_validator_detects_content_all_sources_and_heading_drift(self) -> None:
        for case in (
            "content",
            "status_source",
            "product_source",
            "architecture_source",
            "development_source",
            "heading",
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                selected = build_project(root, CHINESE_PROFILE)
                payload = json.dumps(
                    strategy_handoff(CHINESE_PROFILE), ensure_ascii=False
                )
                self.assertEqual(
                    run_python(UPDATE_STRATEGY, root, input_text=payload).returncode,
                    0,
                )
                contributing = root / "CONTRIBUTING.md"
                source_key = {
                    "product_source": "product",
                    "architecture_source": "architecture",
                    "development_source": "development_rules",
                }.get(case)
                if case == "status_source":
                    write_text(
                        root / "STATUS.md",
                        "# Status\n\n"
                        + CHINESE_PROFILE.mvp_status_enabled_line
                        + "\n\nChanged.\n",
                    )
                elif source_key is not None:
                    write_text(root / selected[source_key], "# Changed\n")
                else:
                    text = contributing.read_text(encoding="utf-8")
                    if case == "content":
                        text = text.replace(
                            "打通并验证演示所需的端到端流程。",
                            "篡改后的流程。",
                            1,
                        )
                    else:
                        text = text.replace("### 不可降低的边界", "### 重新推导条件", 1)
                    write_text(contributing, text)
                validation = run_python(VALIDATOR, root, "--strict")
                self.assertNotEqual(validation.returncode, 0)
                if case.endswith("_source"):
                    self.assertIn("来源已漂移", validation.stdout)
                else:
                    self.assertIn("内容已漂移", validation.stdout)


if __name__ == "__main__":
    unittest.main()
