#!/usr/bin/env python3
"""Validate a project's canonical documentation set without modifying it."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from canonical_paths import (
    ALWAYS_REQUIRED_PATHS,
    CANONICAL_DOCUMENTS,
    ProjectDocsContext,
    add_language_argument,
    render_template,
    requested_language,
    resolve_project_docs,
)
from contributing_blocks import (
    ContributingBlockError,
    DevelopmentTier,
    all_legacy_mvp_heading_positions,
    all_strategy_heading_positions,
    compose_contributing_block,
    locate_legacy_strategy_block,
    parse_development_tier,
    render_contributing_assets,
    strategy_heading_positions,
)
from doc_anchors import profile_for
from managed_blocks import (
    ManagedBlockError,
    locate_managed_block,
    markdown_h1_lines,
)

COMPETING_PATHS = (
    "docs/INDEX.md",
    "docs/通用工程规范.md",
    "docs/general-engineering-rules.md",
)

IGNORED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "coverage",
    "target",
}

CONTRIBUTING_START_MARKER = (
    "<!-- write-project-docs:shared-contributing:start -->"
)
CONTRIBUTING_END_MARKER = (
    "<!-- write-project-docs:shared-contributing:end -->"
)
AGENTS_START_MARKER = "<!-- write-project-docs:document-navigation:start -->"
AGENTS_END_MARKER = "<!-- write-project-docs:document-navigation:end -->"
DEVELOPMENT_START_MARKER = (
    "<!-- write-project-docs:development-source-size:start -->"
)
DEVELOPMENT_END_MARKER = (
    "<!-- write-project-docs:development-source-size:end -->"
)

_THRESHOLD_VALUE = r"(?<!\d)`?(?:240|300|50)`?(?!\d)"
_THRESHOLD_UNIT = r"(?:行|lines?)"
_THRESHOLD_COMPARATOR = (
    r"超过|大于|达到|约|不少于|>=?|≤|"
    r"over|more than|no more than|greater than|larger than|longer than|"
    r"exceeds?|exceeding|at least|at most|up to|under|below|beyond|"
    r"about|around|approximately|reach(?:es|ing)?"
)
_THRESHOLD_LIMIT_WORD = r"阈值|上限|限制|limits?|thresholds?|caps?|maximum|max"
THRESHOLD_RE = re.compile(
    rf"(?:(?:{_THRESHOLD_COMPARATOR})\s*{_THRESHOLD_VALUE}\s*{_THRESHOLD_UNIT}|"
    rf"{_THRESHOLD_VALUE}\s*{_THRESHOLD_UNIT}\s*(?:{_THRESHOLD_LIMIT_WORD})|"
    rf"{_THRESHOLD_VALUE}-line\s+(?:{_THRESHOLD_LIMIT_WORD}))",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "验证固定项目文档的中英文 canonical 路径、共享内容、"
            "开发规范专项引用和根 AGENTS.md 文档区块。"
        )
    )
    parser.add_argument(
        "project_root",
        nargs="?",
        default=".",
        help="项目根目录，默认为当前目录。",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "把竞争/遗留 canonical 路径、可能重复的规模阈值等迁移警告"
            "视为失败；共享内容缺失、漂移或区块边界错误在普通模式也会失败。"
        ),
    )
    add_language_argument(parser)
    return parser.parse_args()


def markdown_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.md"):
        relative = path.relative_to(root)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        if path.is_file() and not path.is_symlink():
            files.append(path)
    return sorted(files)


def display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def complete_managed_asset_issue(
    data: bytes, start_marker: str, end_marker: str, label: str
) -> str | None:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return f"{label} 不是有效 UTF-8"
    if b"\r" in data or not data.endswith(b"\n") or data.endswith(b"\n\n"):
        return f"{label} 必须使用 LF，并保留且仅保留一个尾随换行"
    try:
        span = locate_managed_block(
            data, start_marker.encode(), end_marker.encode(), label
        )
    except ManagedBlockError as error:
        return str(error)
    if span is None:
        return f"{label} 缺少 marker"
    if span.start != 0 or span.end != len(data):
        return f"{label} 的 marker 必须包围整个 asset"
    return None


def check_language_anchors(
    root: Path, skill_root: Path, context: ProjectDocsContext
) -> tuple[list[str], list[str]]:
    """Check the anchors, assets and managed blocks of the resolved language."""

    errors: list[str] = []
    warnings: list[str] = []
    selected = context.selected
    profile = profile_for(context.language)

    development_tier: DevelopmentTier | None = None
    status_path = root / "STATUS.md"
    if status_path.is_file() and not status_path.is_symlink():
        try:
            status_text = status_path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            errors.append("STATUS.md 不是有效 UTF-8")
        else:
            try:
                development_tier = parse_development_tier(
                    status_text, context.language
                )
            except (ValueError, ContributingBlockError) as error:
                errors.append(str(error))

    for relative in selected.values():
        path = root / relative
        if path.is_symlink():
            errors.append(f"固定文档不得使用符号链接：{relative}")
        elif path.exists() and not path.is_file():
            errors.append(f"固定文档必须是普通文件：{relative}")

    development_rules = root / selected["development_rules"]
    if development_rules.is_file() and not development_rules.is_symlink():
        try:
            development_text = development_rules.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            pass
        else:
            development_title = profile.development_rules_title
            has_canonical_prefix = (
                development_text == development_title
                or development_text.startswith(development_title + "\n")
            )
            if (
                not has_canonical_prefix
                or markdown_h1_lines(development_text) != [development_title]
            ):
                errors.append(
                    f"{selected['development_rules']} 必须以唯一的"
                    f"“{development_title}”标题开头"
                )

    development_asset = profile.asset_path(
        skill_root, profile.development_asset_name
    )
    development_asset_issue: str | None = None
    if development_asset.is_symlink() or not development_asset.is_file():
        errors.append(
            "skill 缺少普通共享资源："
            + profile.asset_display(profile.development_asset_name)
        )
    else:
        try:
            expected_development_block = render_template(
                development_asset.read_bytes(),
                selected,
                "开发规范规模规则 asset",
            )
        except (ValueError, ContributingBlockError) as error:
            errors.append(f"skill 共享资源无效：{error}")
            expected_development_block = b""
        development_asset_issue = complete_managed_asset_issue(
            expected_development_block,
            DEVELOPMENT_START_MARKER,
            DEVELOPMENT_END_MARKER,
            "开发规范规模规则 asset",
        )
        if development_asset_issue:
            errors.append(f"skill 共享资源无效：{development_asset_issue}")
    if (
        development_asset.is_file()
        and not development_asset.is_symlink()
        and not development_asset_issue
        and development_rules.is_file()
        and not development_rules.is_symlink()
    ):
        actual_development = development_rules.read_bytes()
        try:
            span = locate_managed_block(
                actual_development,
                DEVELOPMENT_START_MARKER.encode(),
                DEVELOPMENT_END_MARKER.encode(),
                "开发规范的规模规则引用区块",
            )
        except ManagedBlockError as error:
            errors.append(str(error))
        else:
                if span is None:
                    errors.append(
                        f"{selected['development_rules']} 缺少规模规则引用区块"
                    )
                elif actual_development[: span.start] not in {
                    (profile.development_rules_title + "\n\n").encode("utf-8"),
                    (profile.development_rules_title + "\r\n\r\n").encode("utf-8"),
                }:
                    errors.append(
                        f"{selected['development_rules']} 的规模规则引用区块"
                        "必须紧跟标题"
                    )
                elif (
                    actual_development[span.start : span.end]
                    != expected_development_block
                    or actual_development.count(expected_development_block) != 1
                ):
                    errors.append(
                        f"{selected['development_rules']} 的规模规则引用区块"
                        "已漂移，必须用 asset 完整替换"
                    )

    source_asset = profile.asset_path(
        skill_root, profile.source_size_asset_name
    )
    project_source_rules = root / selected["source_size_rules"]
    if source_asset.is_symlink() or not source_asset.is_file():
        errors.append(
            "skill 缺少普通共享资源："
            + profile.asset_display(profile.source_size_asset_name)
        )
    elif project_source_rules.is_file():
        try:
            expected_source_rules = render_template(
                source_asset.read_bytes(), selected, "源代码规模与职责规则 asset"
            )
        except ValueError as error:
            errors.append(f"skill 共享资源无效：{error}")
        else:
            if project_source_rules.read_bytes() != expected_source_rules:
                errors.append(
                    f"{selected['source_size_rules']} 与 skill asset 的路径渲染结果"
                    "不一致"
                )

    contributing_asset = profile.asset_path(
        skill_root, profile.contributing_base_asset_name
    )
    tier_asset_paths = {
        tier: profile.tier_asset_path(skill_root, tier.value)
        for tier in DevelopmentTier
    }
    contributing = root / "CONTRIBUTING.md"
    asset_issue: str | None = None
    expected_base_block = b""
    expected_tier_blocks: dict[DevelopmentTier, bytes] = {}
    expected_contributing_block = b""
    base_asset_ready = (
        contributing_asset.is_file() and not contributing_asset.is_symlink()
    )
    tier_assets_ready = all(
        path.is_file() and not path.is_symlink()
        for path in tier_asset_paths.values()
    )
    if not base_asset_ready:
        errors.append(
            "skill 缺少普通共享资源："
            + profile.asset_display(profile.contributing_base_asset_name)
        )
    for tier, path in tier_asset_paths.items():
        if path.is_symlink() or not path.is_file():
            errors.append(
                "skill 缺少普通共享资源："
                + profile.asset_display(
                    profile.contributing_tier_asset_name(tier.value)
                )
            )
    if base_asset_ready and tier_assets_ready:
        try:
            expected_base_text, expected_tier_texts = render_contributing_assets(
                contributing_asset.read_bytes(),
                {
                    tier: path.read_bytes()
                    for tier, path in tier_asset_paths.items()
                },
                selected,
                context.language,
            )
        except ValueError as error:
            asset_issue = str(error)
            errors.append(f"skill 共享资源无效：{error}")
        else:
            expected_base_block = expected_base_text.encode("utf-8")
            expected_tier_blocks = {
                tier: text.encode("utf-8")
                for tier, text in expected_tier_texts.items()
            }
    if (
        not asset_issue
        and expected_base_block
        and expected_tier_blocks
        and development_tier is not None
    ):
        try:
            expected_contributing_text = compose_contributing_block(
                expected_base_block.decode("utf-8"),
                expected_tier_blocks[development_tier].decode("utf-8"),
                development_tier=development_tier,
                language=context.language,
            )
        except (UnicodeDecodeError, ValueError, ContributingBlockError) as error:
            asset_issue = str(error)
            errors.append(f"skill 共享资源无效：{error}")
        else:
            expected_contributing_block = expected_contributing_text.encode("utf-8")
            asset_issue = complete_managed_asset_issue(
                expected_contributing_block,
                CONTRIBUTING_START_MARKER,
                CONTRIBUTING_END_MARKER,
                "CONTRIBUTING 组合 asset",
            )
            if asset_issue:
                errors.append(f"skill 共享资源无效：{asset_issue}")
    if (
        contributing_asset.is_file()
        and not contributing_asset.is_symlink()
        and not asset_issue
        and expected_contributing_block
        and contributing.is_file()
        and not contributing.is_symlink()
    ):
        try:
            actual_contributing_text = contributing.read_bytes().decode("utf-8")
            expected_contributing_text = expected_contributing_block.decode("utf-8")
        except UnicodeDecodeError:
            errors.append("CONTRIBUTING.md 不是有效 UTF-8")
        else:
            try:
                legacy = locate_legacy_strategy_block(actual_contributing_text)
                if legacy is not None:
                    errors.append(
                        "CONTRIBUTING.md 包含旧动态策略区块；"
                        "必须运行 update_contributing.py 迁移"
                    )
                span = locate_managed_block(
                    actual_contributing_text,
                    CONTRIBUTING_START_MARKER,
                    CONTRIBUTING_END_MARKER,
                    "CONTRIBUTING.md 的共享区块",
                )
            except ManagedBlockError as error:
                errors.append(str(error))
            except ContributingBlockError as error:
                errors.append(str(error))
            else:
                strategy_positions = strategy_heading_positions(
                    actual_contributing_text, profile
                )
                all_strategy_positions = all_strategy_heading_positions(
                    actual_contributing_text
                )
                legacy_mvp_positions = all_legacy_mvp_heading_positions(
                    actual_contributing_text
                )
                if span is None:
                    errors.append("CONTRIBUTING.md 缺少共享 contribution asset")
                    if all_strategy_positions:
                        errors.append(
                            "CONTRIBUTING.md 在托管区块外包含开发策略标题"
                        )
                    if legacy_mvp_positions:
                        errors.append(
                            "CONTRIBUTING.md 在托管区块外包含旧 MVP 策略标题"
                        )
                else:
                    outside_strategy = [
                        position
                        for position in all_strategy_positions
                        if not (span.start <= position < span.end)
                    ]
                    inside_strategy = [
                        position
                        for position in strategy_positions
                        if span.start <= position < span.end
                    ]
                    outside_legacy_mvp = [
                        position
                        for position in legacy_mvp_positions
                        if not (span.start <= position < span.end)
                    ]
                    if outside_strategy:
                        errors.append(
                            "CONTRIBUTING.md 在托管区块外包含开发策略标题"
                        )
                    if outside_legacy_mvp:
                        errors.append(
                            "CONTRIBUTING.md 在托管区块外包含旧 MVP 策略标题"
                        )
                    if len(inside_strategy) != 1:
                        errors.append(
                            "CONTRIBUTING.md 的共享区块必须且只能包含一个"
                            f"“{profile.development_strategy_heading}”"
                        )
                    if (
                        actual_contributing_text[span.start : span.end]
                        != expected_contributing_text
                        or actual_contributing_text.count(expected_contributing_text)
                        != 1
                    ):
                        errors.append(
                            "CONTRIBUTING.md 的共享区块已漂移，"
                            "必须用 asset 完整替换"
                        )

    agents_asset = profile.asset_path(skill_root, profile.agents_asset_name)
    root_agents = root / "AGENTS.md"
    agents_asset_issue: str | None = None
    if agents_asset.is_symlink() or not agents_asset.is_file():
        errors.append(
            "skill 缺少普通共享资源："
            + profile.asset_display(profile.agents_asset_name)
        )
    else:
        try:
            expected_agents_block = render_template(
                agents_asset.read_bytes(), selected, "AGENTS 文档区块 asset"
            )
        except ValueError as error:
            errors.append(f"skill 共享资源无效：{error}")
            expected_agents_block = b""
        agents_asset_issue = complete_managed_asset_issue(
            expected_agents_block,
            AGENTS_START_MARKER,
            AGENTS_END_MARKER,
            "AGENTS 文档区块 asset",
        )
        if agents_asset_issue:
            errors.append(f"skill 共享资源无效：{agents_asset_issue}")
    if (
        agents_asset.is_file()
        and not agents_asset.is_symlink()
        and not agents_asset_issue
        and root_agents.exists()
    ):
        if root_agents.is_symlink():
            warnings.append("根 AGENTS.md 是符号链接，未验证或管理其文档区块")
        elif not root_agents.is_file():
            warnings.append("根 AGENTS.md 不是普通文件，未验证或管理其文档区块")
        else:
            actual = root_agents.read_bytes()
            try:
                agents_text = actual.decode("utf-8")
                expected_agents_text = expected_agents_block.decode("utf-8")
            except UnicodeDecodeError:
                errors.append("AGENTS.md 不是有效 UTF-8")
                agents_text = actual.decode("utf-8", errors="replace")
            else:
                try:
                    span = locate_managed_block(
                        agents_text,
                        AGENTS_START_MARKER,
                        AGENTS_END_MARKER,
                        "根 AGENTS.md 的文档区块",
                    )
                except ManagedBlockError as error:
                    errors.append(str(error))
                else:
                    if span is None:
                        errors.append("现有根 AGENTS.md 缺少文档区块 asset")
                    elif (
                        agents_text[span.start : span.end]
                        != expected_agents_text
                        or agents_text.count(expected_agents_text) != 1
                    ):
                        errors.append(
                            "根 AGENTS.md 的文档区块已漂移，"
                            "必须用 asset 完整替换"
                        )

    return errors, warnings


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).expanduser().resolve()
    skill_root = Path(__file__).resolve().parent.parent
    errors: list[str] = []
    warnings: list[str] = []

    if not root.is_dir():
        print(f"错误：项目根目录不存在或不是目录：{root}", file=sys.stderr)
        return 2

    docs_directory = root / "docs"
    if docs_directory.is_symlink():
        print("错误：")
        print("- docs 目录不得使用符号链接")
        return 1

    for relative in ALWAYS_REQUIRED_PATHS:
        path = root / relative
        if not path.is_file():
            errors.append(f"缺少固定文档：{relative}")
        elif path.is_symlink():
            errors.append(f"固定文档不得使用符号链接：{relative}")

    for relative in COMPETING_PATHS:
        if (root / relative).exists():
            warnings.append(f"存在竞争或遗留 canonical 路径：{relative}")

    context = resolve_project_docs(
        root, language=requested_language(args.language)
    )
    errors.extend(context.errors)
    # 语言未确定时，锚点和 asset 比对只会基于回退语言给出误导性结论；
    # 下面与语言无关的检查照常执行，一并报告。
    if context.language_resolved:
        anchor_errors, anchor_warnings = check_language_anchors(
            root, skill_root, context
        )
        errors.extend(anchor_errors)
        warnings.extend(anchor_warnings)
        size_rule_paths = {
            context.selected["source_size_rules"],
            context.selected["architecture"],
        }
        development_rules_path: str | None = context.selected["development_rules"]
    else:
        size_rule_paths = {
            candidate
            for document in CANONICAL_DOCUMENTS
            if document.key in {"source_size_rules", "architecture"}
            for candidate in (document.chinese_path, document.english_path)
        }
        development_rules_path = None

    docs = markdown_files(root)
    for path in docs:
        try:
            path.relative_to(skill_root / "assets")
        except ValueError:
            pass
        else:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(f"{display_path(path, root)}: 不是有效 UTF-8 Markdown")
            continue

        relative = path.relative_to(root).as_posix()
        if relative not in size_rule_paths:
            for line_number, line in enumerate(text.splitlines(), start=1):
                if THRESHOLD_RE.search(line):
                    message = (
                        f"{relative}:{line_number}: 可能重复了共享规模阈值；"
                        "应改为链接"
                    )
                    if relative == development_rules_path:
                        errors.append(message)
                    else:
                        warnings.append(message)

    if errors:
        print("错误：")
        for item in errors:
            print(f"- {item}")
    if warnings:
        print("警告：")
        for item in warnings:
            print(f"- {item}")
    if not errors and not warnings:
        print("项目文档验证通过。")
    elif not errors:
        print("项目文档基础验证通过，但仍有迁移警告。")

    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
