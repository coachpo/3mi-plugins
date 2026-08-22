#!/usr/bin/env python3
"""Update the STATUS-tier-controlled managed block in CONTRIBUTING.md."""

from __future__ import annotations

import argparse
from pathlib import Path

from canonical_paths import (
    add_language_argument,
    requested_language,
    resolve_project_docs,
)
from contributing_blocks import (
    END_MARKER,
    START_MARKER,
    DevelopmentTier,
    all_legacy_mvp_heading_positions,
    all_managed_contributing_titles,
    all_strategy_heading_positions,
    compose_contributing_block,
    locate_legacy_strategy_block,
    parse_development_tier,
    remove_legacy_strategy_block,
    render_contributing_assets,
    strategy_heading_positions,
)
from doc_anchors import LanguageProfile, profile_for
from managed_blocks import (
    ManagedBlockError,
    locate_managed_block,
    visible_atx_headings,
    visible_section_titles,
)
from safe_write import AtomicWriteCommittedError, read_snapshot, write_atomically


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="按 STATUS.md 的开发档位更新 CONTRIBUTING.md 托管区块。"
    )
    parser.add_argument(
        "project_root",
        nargs="?",
        default=".",
        help="项目根目录，默认为当前目录。",
    )
    add_language_argument(parser)
    return parser.parse_args()


def complete_asset_issue(asset: str) -> str | None:
    if "\r" in asset or not asset.endswith("\n") or asset.endswith("\n\n"):
        return "CONTRIBUTING 组合 asset 必须使用 LF，并仅保留一个尾随换行"
    try:
        span = locate_managed_block(
            asset, START_MARKER, END_MARKER, "CONTRIBUTING 组合 asset"
        )
    except ManagedBlockError as error:
        return str(error)
    if span is None or span.start != 0 or span.end != len(asset):
        return "CONTRIBUTING 组合 asset 的 marker 必须包围整个 asset"
    return None


def insert_or_replace_block(
    text: str, asset: str, profile: LanguageProfile
) -> tuple[str, str]:
    """Insert or replace the complete shared block, accepting one legacy shape."""

    try:
        span = locate_managed_block(
            text, START_MARKER, END_MARKER, "CONTRIBUTING.md 的共享区块"
        )
    except ManagedBlockError as error:
        raise ValueError(str(error)) from error

    strategy_positions = strategy_heading_positions(text, profile)
    all_strategy_positions = all_strategy_heading_positions(text)
    legacy_mvp_positions = all_legacy_mvp_heading_positions(text)
    if span is None:
        if all_strategy_positions:
            raise ValueError("CONTRIBUTING.md 在托管区块外包含开发策略标题")
        if legacy_mvp_positions:
            raise ValueError("CONTRIBUTING.md 在托管区块外包含旧 MVP 策略标题")
        existing_titles = visible_section_titles(
            text, all_managed_contributing_titles()
        )
        if existing_titles:
            titles = "、".join(f"## {title}" for title in sorted(existing_titles))
            raise ValueError(f"CONTRIBUTING.md 的共享区块已漂移：{titles}")
        newline = "\r\n" if "\r\n" in text else "\n"
        prefix = text
        if prefix and not prefix.endswith(newline):
            prefix += newline
        if prefix and not prefix.endswith(newline * 2):
            prefix += newline
        return prefix + asset, "inserted"

    outside_strategy = [
        position
        for position in all_strategy_positions
        if not (span.start <= position < span.end)
    ]
    outside_legacy_mvp = [
        position
        for position in legacy_mvp_positions
        if not (span.start <= position < span.end)
    ]
    if outside_strategy:
        raise ValueError("CONTRIBUTING.md 在共享区块外包含开发策略标题")
    if outside_legacy_mvp:
        raise ValueError("CONTRIBUTING.md 在共享区块外包含旧 MVP 策略标题")
    inside_strategy = [
        position
        for position in strategy_positions
        if span.start <= position < span.end
    ]
    inside_legacy_mvp = [
        position
        for position in legacy_mvp_positions
        if span.start <= position < span.end
    ]
    if len(inside_strategy) > 1 or len(inside_legacy_mvp) > 1:
        raise ValueError("CONTRIBUTING.md 的共享区块包含重复策略标题")

    outside_titles = visible_section_titles(
        text[: span.start] + text[span.end :], all_managed_contributing_titles()
    )
    if outside_titles:
        titles = "、".join(f"## {title}" for title in sorted(outside_titles))
        raise ValueError(f"CONTRIBUTING.md 在共享区块外包含托管标题：{titles}")

    block_headings = [
        (level, title)
        for level, title, _ in visible_atx_headings(text[span.start : span.end])
    ]
    expected_current = [
        (2, profile.development_strategy_title),
        *(
            (3, title)
            for title in profile.development_strategy_section_titles
        ),
        *((2, title) for title in profile.contributing_section_titles),
    ]
    expected_legacy_base = [
        (2, title) for title in profile.contributing_section_titles
    ]
    expected_legacy_mvp = [
        (2, profile.contributing_section_titles[0]),
        (2, profile.contributing_section_titles[1]),
        (3, profile.legacy_mvp_title),
        (2, profile.contributing_section_titles[2]),
    ]
    if tuple(block_headings) not in {
        tuple(expected_current),
        tuple(expected_legacy_base),
        tuple(expected_legacy_mvp),
    }:
        raise ValueError("CONTRIBUTING.md 的共享区块标题缺失、重复或顺序错误")
    return text[: span.start] + asset + text[span.end :], "replaced"


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).expanduser().resolve()
    skill_root = Path(__file__).resolve().parent.parent
    status_path = root / "STATUS.md"
    contributing_path = root / "CONTRIBUTING.md"

    if not root.is_dir():
        print(f"错误：项目根目录不存在或不是目录：{root}")
        return 2

    context = resolve_project_docs(root, language=requested_language(args.language))
    if context.errors:
        print("错误：")
        for error in context.errors:
            print(f"- {error}")
        print("未修改 CONTRIBUTING.md")
        return 1
    selected = context.selected
    profile = profile_for(context.language)

    base_asset_path = profile.asset_path(
        skill_root, profile.contributing_base_asset_name
    )
    tier_asset_paths = {
        tier: profile.tier_asset_path(skill_root, tier.value)
        for tier in DevelopmentTier
    }

    for label, path in (
        ("STATUS.md", status_path),
        ("CONTRIBUTING.md", contributing_path),
    ):
        if path.is_symlink():
            print(f"错误：{label} 是符号链接；未修改")
            return 1
        if not path.is_file():
            print(f"错误：{label} 不存在或不是普通文件；未修改")
            return 1
    for label, path in (
        ("CONTRIBUTING 基础 asset", base_asset_path),
        *(
            (f"CONTRIBUTING {tier.value} 档位 asset", path)
            for tier, path in tier_asset_paths.items()
        ),
    ):
        if path.is_symlink() or not path.is_file():
            print(
                "错误：skill 缺少普通文件 "
                + f"{profile.asset_display(path.name)}（{label}）"
            )
            return 2

    try:
        status_snapshot = read_snapshot(status_path)
        contributing_snapshot = read_snapshot(contributing_path)
        base_asset_snapshot = read_snapshot(base_asset_path)
        tier_asset_snapshots = {
            tier: read_snapshot(path) for tier, path in tier_asset_paths.items()
        }
        status_text = status_snapshot.data.decode("utf-8")
        original = contributing_snapshot.data.decode("utf-8")
    except UnicodeDecodeError:
        print("错误：STATUS.md 或 CONTRIBUTING.md 不是有效 UTF-8；未修改")
        return 1
    except ValueError as error:
        print(f"错误：{error}；未修改")
        return 1

    try:
        development_tier = parse_development_tier(status_text, context.language)
    except ValueError as error:
        print(f"错误：{error}；未修改")
        return 1

    try:
        base_asset, tier_assets = render_contributing_assets(
            base_asset_snapshot.data,
            {
                tier: snapshot.data
                for tier, snapshot in tier_asset_snapshots.items()
            },
            selected,
            context.language,
        )
        asset = compose_contributing_block(
            base_asset,
            tier_assets[development_tier],
            development_tier=development_tier,
            language=context.language,
        )
    except (TypeError, ValueError) as error:
        print(f"错误：skill 共享资源无效：{error}；未修改")
        return 2

    asset_issue = complete_asset_issue(asset)
    if asset_issue:
        print(f"错误：skill 共享资源无效：{asset_issue}；未修改")
        return 2

    try:
        without_legacy, migrated_legacy = remove_legacy_strategy_block(original)
        updated, action = insert_or_replace_block(without_legacy, asset, profile)
    except ValueError as error:
        print(f"错误：{error}；未修改")
        return 1

    asset_snapshots = (
        (base_asset_path, base_asset_snapshot),
        *(
            (tier_asset_paths[tier], tier_asset_snapshots[tier])
            for tier in DevelopmentTier
        ),
    )
    bound_input_snapshots = ((status_path, status_snapshot), *asset_snapshots)

    def precommit_validate() -> None:
        current_context = resolve_project_docs(
            root, language=requested_language(args.language)
        )
        if (
            current_context.errors
            or current_context.language is not context.language
            or current_context.selected != context.selected
        ):
            raise ValueError("写入前固定文档路径或语言发生变化")
        current_status = read_snapshot(status_path).data.decode("utf-8")
        if (
            parse_development_tier(current_status, current_context.language)
            is not development_tier
        ):
            raise ValueError("STATUS.md 的开发档位在写入期间发生变化")
        if locate_legacy_strategy_block(updated) is not None:
            raise ValueError("CONTRIBUTING.md 仍包含旧动态策略区块")
        revalidated, _ = insert_or_replace_block(
            updated, asset, profile_for(current_context.language)
        )
        if revalidated != updated:
            raise ValueError("CONTRIBUTING.md 的静态档位策略未完整写入")

    if updated == original:
        try:
            precommit_validate()
            if read_snapshot(contributing_path) != contributing_snapshot:
                raise ValueError("CONTRIBUTING.md 在校验期间发生变化")
            for path, snapshot in bound_input_snapshots:
                if read_snapshot(path) != snapshot:
                    raise ValueError(f"{path.name} 在校验期间发生变化")
        except (OSError, UnicodeDecodeError, ValueError) as error:
            print(f"错误：{error}；未修改")
            return 1
        print(
            "CONTRIBUTING.md 已符合开发档位"
            f"（{development_tier.display}）；未修改"
        )
        return 0

    try:
        write_atomically(
            contributing_path,
            updated,
            contributing_snapshot,
            precommit_validate,
            input_snapshots=bound_input_snapshots,
        )
    except AtomicWriteCommittedError as error:
        print(f"错误：{error}；文件已替换")
        return 1
    except (OSError, UnicodeDecodeError, ValueError) as error:
        print(f"错误：{error}；未修改")
        return 1
    action_text = "已插入" if action == "inserted" else "已更新"
    migration_text = "；已移除旧动态策略区块" if migrated_legacy else ""
    print(
        f"{action_text} CONTRIBUTING.md 共享区块；"
        f"文档语言：{profile.language.label}；"
        f"开发档位：{development_tier.display}{migration_text}。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
