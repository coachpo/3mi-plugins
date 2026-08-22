#!/usr/bin/env python3
"""Update the documentation sections in an existing root AGENTS.md."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PLUGIN_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(PLUGIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SCRIPTS))

from canonical_paths import (
    add_language_argument,
    canonical_path_mappings,
    render_template,
    requested_language,
    resolve_project_docs,
)
from doc_anchors import LanguageProfile, profile_for
from invariant_contract import (  # noqa: E402
    ROUTER_END_MARKER,
    ROUTER_START_MARKER,
)
from managed_blocks import (
    ManagedBlockError,
    locate_all_managed_blocks,
    locate_managed_block,
    visible_section_titles,
)
from markdown_links import replace_visible_link_targets, visible_path_mentions
from safe_write import AtomicWriteCommittedError, read_snapshot, write_atomically

START_MARKER = "<!-- write-project-docs:document-navigation:start -->"
END_MARKER = "<!-- write-project-docs:document-navigation:end -->"
FIXED_PATH_MAPPINGS = (
    ("docs/INDEX.md", "docs/README.md"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "仅更新现有项目根 AGENTS.md 的托管文档导航、内容边界和明确旧路径。"
        )
    )
    parser.add_argument(
        "project_root",
        nargs="?",
        default=".",
        help="项目根目录，默认为当前目录。",
    )
    add_language_argument(parser)
    return parser.parse_args()


def insert_or_replace_block(
    text: str, asset: str, profile: LanguageProfile
) -> tuple[str, str]:
    try:
        span = locate_managed_block(
            text, START_MARKER, END_MARKER, "根 AGENTS.md 的文档区块"
        )
    except ManagedBlockError as error:
        raise ValueError(str(error)) from error

    if span is None:
        existing_titles = visible_section_titles(
            text, profile.agents_section_titles
        )
        if existing_titles:
            titles = "、".join(f"## {title}" for title in sorted(existing_titles))
            raise ValueError(f"根 AGENTS.md 的文档区块已漂移：{titles}")
        prefix = text
        newline = "\r\n" if "\r\n" in prefix else "\n"
        if prefix and not prefix.endswith(newline):
            prefix += newline
        if prefix and not prefix.endswith(newline * 2):
            prefix += newline
        candidate = prefix + asset
        action = "inserted"
    else:
        candidate = text[: span.start] + asset + text[span.end :]
        action = "replaced"

    try:
        locate_all_managed_blocks(candidate)
        candidate_span = locate_managed_block(
            candidate,
            START_MARKER,
            END_MARKER,
            "投影后的根 AGENTS.md 文档区块",
        )
    except ManagedBlockError as error:
        raise ValueError(str(error)) from error
    if candidate_span is None:
        raise ValueError("投影后的文档区块 marker 被 Markdown 结构隐藏")
    return candidate, action


def validate_navigation_asset(asset: str) -> None:
    """Require one complete, canonical navigation asset."""

    try:
        span = locate_managed_block(
            asset, START_MARKER, END_MARKER, "AGENTS 文档区块 asset"
        )
    except ManagedBlockError as error:
        raise ValueError(str(error)) from error
    if (
        span is None
        or span.start != 0
        or span.end != len(asset)
        or not asset.endswith("\n")
        or asset.endswith("\n\n")
        or "\r" in asset
    ):
        raise ValueError("AGENTS 文档区块 asset 格式无效")


def normalize_legacy_paths(
    text: str, path_mappings: tuple[tuple[str, str], ...]
) -> tuple[str, list[str]]:
    """Rewrite visible link targets while preserving every managed block."""

    try:
        managed_blocks = locate_all_managed_blocks(text)
        router_span = locate_managed_block(
            text,
            ROUTER_START_MARKER,
            ROUTER_END_MARKER,
            "根 AGENTS.md 的工程路由区块",
        )
    except ManagedBlockError as error:
        raise ValueError(str(error)) from error

    try:
        navigation_span = locate_managed_block(
            text,
            START_MARKER,
            END_MARKER,
            "根 AGENTS.md 的文档区块",
        )
    except ManagedBlockError as error:
        raise ValueError(str(error)) from error
    if router_span is not None and navigation_span is not None:
        separated = (
            router_span.end <= navigation_span.start
            or navigation_span.end <= router_span.start
        )
        if not separated:
            raise ValueError("根 AGENTS.md 的工程路由与文档导航区块不得嵌套")

    protected_spans = sorted(
        (span for _name, span in managed_blocks), key=lambda span: span.start
    )
    pieces: list[str] = []
    replacements: list[str] = []
    cursor = 0
    for span in protected_spans:
        rewritten, segment_replacements = replace_visible_link_targets(
            text[cursor : span.start], path_mappings
        )
        pieces.extend((rewritten, text[span.start : span.end]))
        replacements.extend(segment_replacements)
        cursor = span.end
    rewritten, segment_replacements = replace_visible_link_targets(
        text[cursor:], path_mappings
    )
    pieces.append(rewritten)
    replacements.extend(segment_replacements)
    return "".join(pieces), replacements


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).expanduser().resolve()
    agents_path = root / "AGENTS.md"
    skill_root = Path(__file__).resolve().parent.parent

    if not root.is_dir():
        print(f"错误：项目根目录不存在或不是目录：{root}")
        return 2

    context = resolve_project_docs(root, language=requested_language(args.language))
    if context.errors:
        print("错误：")
        for error in context.errors:
            print(f"- {error}")
        print("未修改根 AGENTS.md")
        return 1
    selected = context.selected
    profile = profile_for(context.language)

    asset_path = profile.asset_path(skill_root, profile.agents_asset_name)
    if asset_path.is_symlink() or not asset_path.is_file():
        print(
            "错误：skill 缺少普通文件 "
            + profile.asset_display(profile.agents_asset_name)
        )
        return 2
    if agents_path.is_symlink():
        print("错误：根 AGENTS.md 是符号链接；未修改")
        return 1
    if not agents_path.exists():
        print("跳过：项目根 AGENTS.md 不存在；未创建")
        return 0
    if not agents_path.is_file():
        print("错误：根 AGENTS.md 不是普通文件；未修改")
        return 1

    try:
        asset_snapshot = read_snapshot(asset_path)
        asset = render_template(
            asset_snapshot.data, selected, "AGENTS 文档区块 asset"
        ).decode("utf-8")
        validate_navigation_asset(asset)
    except UnicodeDecodeError:
        print("错误：AGENTS 文档区块 asset 不是有效 UTF-8")
        return 2
    except ValueError as error:
        print(f"错误：{error}")
        return 2

    try:
        agents_snapshot = read_snapshot(agents_path)
        canonical_snapshots = tuple(
            (root / relative, read_snapshot(root / relative))
            for relative in selected.values()
        )
        original = agents_snapshot.data.decode("utf-8")
    except UnicodeDecodeError:
        print("错误：根 AGENTS.md 或固定文档不是有效 UTF-8；未修改")
        return 1
    except ValueError as error:
        print(f"错误：{error}；未修改")
        return 1

    path_mappings = canonical_path_mappings(selected) + FIXED_PATH_MAPPINGS
    try:
        normalized_original, replacements = normalize_legacy_paths(
            original, path_mappings
        )
    except ValueError as error:
        print(f"错误：{error}；未修改")
        return 1

    mentions = visible_path_mentions(
        normalized_original, tuple(old for old, _ in path_mappings)
    )

    try:
        updated, block_action = insert_or_replace_block(
            normalized_original, asset, profile
        )
    except ValueError as error:
        print(f"错误：{error}；未修改")
        return 1

    input_snapshots = ((asset_path, asset_snapshot), *canonical_snapshots)

    def precommit_validate() -> None:
        current_context = resolve_project_docs(
            root, language=requested_language(args.language)
        )
        if (
            current_context.errors
            or current_context.language is not context.language
            or current_context.selected != selected
        ):
            raise ValueError("写入前固定文档路径或语言发生变化")
        current_asset_snapshot = read_snapshot(asset_path)
        if current_asset_snapshot != asset_snapshot:
            raise ValueError("AGENTS 文档区块 asset 在写入期间发生变化")
        current_asset = render_template(
            current_asset_snapshot.data,
            current_context.selected,
            "AGENTS 文档区块 asset",
        ).decode("utf-8")
        validate_navigation_asset(current_asset)
        current_mappings = (
            canonical_path_mappings(current_context.selected) + FIXED_PATH_MAPPINGS
        )
        current_normalized, _ = normalize_legacy_paths(original, current_mappings)
        current_updated, current_action = insert_or_replace_block(
            current_normalized,
            current_asset,
            profile_for(current_context.language),
        )
        if current_updated != updated or current_action != block_action:
            raise ValueError("写入前 AGENTS.md 导航投影发生变化")

    def report_mentions() -> None:
        for line_number, path in mentions:
            print(
                f"提示：AGENTS.md:{line_number} 在正文中提到 {path}；"
                "不是链接目标，未自动修改"
            )

    if updated == original:
        try:
            precommit_validate()
            if read_snapshot(agents_path) != agents_snapshot:
                raise ValueError("AGENTS.md 在校验期间发生变化")
            for path, snapshot in input_snapshots:
                if read_snapshot(path) != snapshot:
                    raise ValueError(f"{path.name} 在校验期间发生变化")
        except (OSError, UnicodeDecodeError, ValueError) as error:
            print(f"错误：{error}；未修改")
            return 1
        print("根 AGENTS.md 已符合文档区块规范；未修改")
        report_mentions()
        return 0

    try:
        write_atomically(
            agents_path,
            updated,
            agents_snapshot,
            precommit_validate,
            input_snapshots=input_snapshots,
        )
    except AtomicWriteCommittedError as error:
        print(f"错误：{error}；文件已替换")
        return 1
    except (OSError, UnicodeDecodeError, ValueError) as error:
        print(f"错误：{error}；未修改")
        return 1
    action_text = "已插入" if block_action == "inserted" else "已更新"
    print(
        f"{action_text}根 AGENTS.md 文档区块；"
        f"文档语言：{profile.language.label}。"
    )
    for replacement in replacements:
        print(f"已修正链接：{replacement}")
    report_mentions()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
